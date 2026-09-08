"""Read one Git batch incrementally with a deadline and bounded diagnostics."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import IO

_PROCESS_SPEC = importlib.util.spec_from_file_location(
    "process_runner", Path(__file__).with_name("process_runner.py")
)
assert _PROCESS_SPEC is not None and _PROCESS_SPEC.loader is not None
process_runner = importlib.util.module_from_spec(_PROCESS_SPEC)
_PROCESS_SPEC.loader.exec_module(process_runner)

STDERR_LIMIT = 65536


def git_executable() -> str:
    """Bypass the Git for Windows launcher so deadlines own the Git process."""
    executable = shutil.which("git") or "git"
    if (
        os.name == "nt"
        and Path(executable).name.lower() == "git.exe"
        and Path(executable).parent.name.lower() in {"cmd", "bin"}
    ):
        installation = Path(executable).parent.parent
        for architecture in ("mingw64", "mingw32"):
            native = installation / architecture / "bin" / "git.exe"
            if native.is_file():
                return str(native)
    return executable


def _read_blob(
    stream: IO[bytes], expected_id: str, error_type: type[RuntimeError]
) -> bytes:
    header = stream.readline(256)
    if not header.endswith(b"\n"):
        raise error_type("git cat-file returned an incomplete header.")
    fields = header.rstrip(b"\n").split(b" ")
    if (
        len(fields) != 3
        or fields[0] != expected_id.encode("ascii")
        or fields[1] != b"blob"
        or not fields[2].isdigit()
    ):
        raise error_type(f"Unexpected Git object for {expected_id}.")
    size = int(fields[2])
    if size > sys.maxsize:
        raise error_type("git cat-file returned an invalid blob size.")
    content = stream.read(size)
    if len(content) != size or stream.read(1) != b"\n":
        raise error_type("git cat-file returned incomplete blob content.")
    return content


@contextmanager
def blob_stream(
    root: Path,
    object_ids: Sequence[str],
    *,
    timeout: float,
    error_type: type[RuntimeError],
) -> Iterator[Iterator[bytes]]:
    """Yield blobs in request order; leaving the context always reaps the child."""
    if not object_ids:
        yield iter(())
        return
    diagnostics = bytearray()
    scope = process_runner.ProcessScope(
        [git_executable(), "-C", str(root), "cat-file", "--batch"],
        timeout=timeout,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with scope:
            process = scope.process
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None

            def drain_stderr() -> None:
                while chunk := process.stderr.read(8192):
                    diagnostics.extend(chunk)
                    del diagnostics[:-STDERR_LIMIT]

            def read_objects() -> Iterator[bytes]:
                for object_id in object_ids:
                    # One request at a time prevents pipe backpressure deadlocks.
                    process.stdin.write(object_id.encode("ascii") + b"\n")
                    process.stdin.flush()
                    yield _read_blob(process.stdout, object_id, error_type)
                process.stdin.close()
                if process.stdout.read(1):
                    raise error_type(
                        "git cat-file returned unexpected trailing output."
                    )
                process.wait(timeout=scope.remaining())
                if process.returncode:
                    raise error_type(
                        f"git cat-file --batch exited with status {process.returncode}"
                    )

            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()
            try:
                yield read_objects()
            finally:
                scope.terminate()
                process.wait(timeout=scope.remaining())
                stderr_thread.join(timeout=scope.remaining())
                if stderr_thread.is_alive():
                    raise error_type(
                        "git cat-file stderr cleanup exceeded its deadline"
                    )
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass  # A failed child can leave a buffered request unwritten.
                process.stdout.close()
                process.stderr.close()
            if scope.expired.is_set():
                raise error_type(f"git cat-file --batch timed out after {timeout}s")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        if scope.expired.is_set() or isinstance(error, subprocess.TimeoutExpired):
            raise error_type(
                f"git cat-file --batch timed out after {timeout}s"
            ) from error
        details = diagnostics.decode("utf-8", errors="replace").strip()
        if isinstance(error, error_type) and not details:
            raise
        raise error_type(f"git cat-file --batch failed: {error}: {details}") from error
