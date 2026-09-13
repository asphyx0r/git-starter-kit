import importlib.util
import ctypes
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tracemalloc
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "release-artifacts.py"
SOURCE_ROOT = SCRIPT_PATH.parents[1]
SPEC = importlib.util.spec_from_file_location("release_artifacts", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
ARTIFACTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACTS)


class ReleaseArtifactTests(unittest.TestCase):
    def assert_process_stopped(self, process_id):
        if os.name == "nt":
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            api.OpenProcess.restype = ctypes.c_void_p
            api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            api.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = api.OpenProcess(0x100000, False, process_id)
            if handle:
                try:
                    # Allow bounded observation of asynchronous OS exit acknowledgement.
                    self.assertEqual(api.WaitForSingleObject(handle, 1000), 0)
                finally:
                    api.CloseHandle(handle)
            else:
                self.assertEqual(ctypes.get_last_error(), 87)
        else:
            try:
                os.kill(process_id, 0)
            except ProcessLookupError:
                return
            # An orphan can briefly await init reaping after group termination.
            try:
                status = Path(f"/proc/{process_id}/stat").read_text()
            except FileNotFoundError:
                return
            self.assertEqual(status.rsplit(")", 1)[1].split()[0], "Z")

    def test_interrupt_before_batch_eof_cleans_an_attested_descendant(self):
        native_popen = subprocess.Popen
        marker = Path(self.temporary.name) / "interrupted-descendant.pid"
        descendant = (
            "import os,pathlib,time; "
            f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
            "time.sleep(4)"
        )
        parent = (
            "import pathlib,subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-B','-c',{descendant!r}]); "
            f"marker=pathlib.Path({str(marker)!r}); "
            "exec('while not (marker.exists() and marker.stat().st_size): time.sleep(0.01)'); "
            "sys.stdout.buffer.write(b'abc blob 1\\nx\\n'); sys.stdout.buffer.flush()"
        )
        with patch.object(
            ARTIFACTS.subprocess,
            "Popen",
            side_effect=lambda *args, **kwargs: native_popen(
                [sys.executable, "-B", "-c", parent], **kwargs
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                with ARTIFACTS.git_objects.blob_stream(
                    self.root,
                    ["abc", "def"],
                    timeout=2,
                    error_type=ARTIFACTS.ReleaseArtifactError,
                ) as blobs:
                    self.assertEqual(next(blobs), b"x")
                    self.assertTrue(marker.is_file())
                    raise KeyboardInterrupt
        self.assert_process_stopped(int(marker.read_text()))

    def test_deadline_cleans_up_a_started_descendant_holding_pipes(self):
        native_popen = subprocess.Popen
        marker = Path(self.temporary.name) / "descendant.pid"
        child_code = (
            "import os,pathlib,time; "
            f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
            "time.sleep(6)"
        )
        parent_code = (
            "import pathlib,subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-B','-c',{child_code!r}]); "
            f"marker=pathlib.Path({str(marker)!r}); "
            "exec('while not (marker.exists() and marker.stat().st_size): time.sleep(0.01)')"
        )
        for operation in (
            lambda: ARTIFACTS.read_blobs(self.root, [("file", "100644", "abc")]),
            lambda: ARTIFACTS.run_git(self.root, "rev-parse", "HEAD"),
            lambda: ARTIFACTS.ref_exists(self.root, "missing"),
        ):
            marker.unlink(missing_ok=True)
            children = []

            def start_parent(*args, **kwargs):
                child = native_popen(
                    [sys.executable, "-B", "-c", parent_code], **kwargs
                )
                children.append(child)
                return child

            started = time.monotonic()
            with (
                patch.object(ARTIFACTS.subprocess, "Popen", start_parent),
                patch.object(ARTIFACTS, "GIT_TIMEOUT_SECONDS", 3),
                patch.object(ARTIFACTS, "GIT_BULK_TIMEOUT_SECONDS", 3),
                self.assertRaisesRegex(ARTIFACTS.ReleaseArtifactError, "timed out"),
            ):
                operation()
            self.assertTrue(marker.is_file(), "descendant did not start")
            self.assertLess(time.monotonic() - started, 4)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(children[0].stdout.closed)
            self.assertTrue(children[0].stderr.closed)
            self.assert_process_stopped(int(marker.read_text()))

    def test_short_git_and_ref_deadlines_reap_a_blocking_child(self):
        native_popen = subprocess.Popen
        children = []

        def start_child(*args, **kwargs):
            child = native_popen(
                [sys.executable, "-B", "-c", "import time; time.sleep(60)"], **kwargs
            )
            children.append(child)
            return child

        for operation in (
            lambda: ARTIFACTS.run_git(self.root, "rev-parse", "HEAD"),
            lambda: ARTIFACTS.ref_exists(self.root, "refs/tags/missing"),
        ):
            with (
                patch.object(ARTIFACTS.subprocess, "Popen", start_child),
                patch.object(ARTIFACTS, "GIT_TIMEOUT_SECONDS", 0.1),
                self.assertRaisesRegex(ARTIFACTS.ReleaseArtifactError, "timed out"),
            ):
                operation()
            self.assertIsNotNone(children[-1].poll())
            self.assertTrue(children[-1].stdout.closed)
            self.assertTrue(children[-1].stderr.closed)

    def test_batch_deadline_kills_a_blocking_child_and_releases_pipes(self):
        child_processes = []
        native_popen = subprocess.Popen

        def start_child(*args, **kwargs):
            if Path(args[0][0]).stem != "git":
                return native_popen(*args, **kwargs)
            child = native_popen(
                [sys.executable, "-B", "-c", "import time; time.sleep(60)"],
                **kwargs,
            )
            child_processes.append(child)
            return child

        started = time.monotonic()
        with (
            patch.object(ARTIFACTS.git_objects.subprocess, "Popen", start_child),
            patch.object(ARTIFACTS, "GIT_BULK_TIMEOUT_SECONDS", 0.1),
            self.assertRaisesRegex(ARTIFACTS.ReleaseArtifactError, "timed out"),
        ):
            ARTIFACTS.read_blobs(self.root, [("file", "100644", "abc")])
        self.assertLess(time.monotonic() - started, 2)
        for stream in (
            child_processes[0].stdin,
            child_processes[0].stdout,
            child_processes[0].stderr,
        ):
            self.assertTrue(stream.closed)
        self.assertIsNotNone(child_processes[0].wait(timeout=1))

    def test_batch_early_exit_and_interrupt_reap_the_child(self):
        native_popen = subprocess.Popen
        for interrupt in (False, True):
            children = []

            def start_child(*args, **kwargs):
                if Path(args[0][0]).stem != "git":
                    return native_popen(*args, **kwargs)
                child = native_popen(*args, **kwargs)
                children.append(child)
                return child

            object_id = self.run_git("rev-parse", "HEAD:README.md")
            with patch.object(ARTIFACTS.git_objects.subprocess, "Popen", start_child):
                try:
                    with ARTIFACTS.git_objects.blob_stream(
                        self.root,
                        [object_id, object_id],
                        timeout=5,
                        error_type=ARTIFACTS.ReleaseArtifactError,
                    ) as blobs:
                        self.assertEqual(
                            next(blobs), b"# Example" + os.linesep.encode()
                        )
                        if interrupt:
                            raise KeyboardInterrupt
                except KeyboardInterrupt:
                    self.assertTrue(interrupt)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(children[0].stdout.closed)

    def test_batch_drains_stderr_and_reports_nonzero_exit(self):
        native_popen = subprocess.Popen
        child = (
            "import sys; sys.stdin.buffer.readline(); "
            "sys.stderr.buffer.write(b'x' * 200000 + b'failure'); "
            "sys.stdout.buffer.write(b'abc blob 1\\nx\\n'); "
            "sys.stdout.buffer.flush(); sys.exit(7)"
        )
        with (
            patch.object(
                ARTIFACTS.git_objects.subprocess,
                "Popen",
                side_effect=lambda *args, **kwargs: native_popen(
                    (
                        [sys.executable, "-B", "-c", child]
                        if Path(args[0][0]).stem == "git"
                        else args[0]
                    ),
                    **kwargs,
                ),
            ),
            self.assertRaisesRegex(ARTIFACTS.ReleaseArtifactError, "failure") as caught,
        ):
            ARTIFACTS.read_blobs(self.root, [("file", "100644", "abc")])
        self.assertLess(len(str(caught.exception)), 66000)

    def test_streamed_release_metadata_matches_compatibility_api(self):
        for name, content in {
            "empty.txt": b"",
            "cr.txt": b"a\rb\r",
            "utf8-é.txt": "é\r\n".encode(),
            "invalid.bin": b"\xff\n",
            "mixed.txt": b"a\r\nb\nc\r",
        }.items():
            (self.root / name).write_bytes(content)
        self.run_git("add", ".")
        for treeish in (None, "HEAD"):
            expected = ARTIFACTS.release_payload(
                ARTIFACTS.git_entries(self.root, treeish), "1.2.3", True
            )
            records, retained = ARTIFACTS.release_inventory(self.root, treeish)
            actual = ARTIFACTS._payload_from_records(
                records, retained.get("VERSION"), "1.2.3", True
            )
            self.assertEqual(actual, expected)
            self.assertLessEqual(
                set(retained),
                {
                    "VERSION",
                    "SHA256SUMS",
                    "manifest.json",
                    ARTIFACTS.SCHEMA_PATH,
                    ARTIFACTS.TEMPLATE_PATH,
                },
            )

    def test_prepare_metadata_does_not_retain_the_whole_payload(self):
        for index in range(24):
            (self.root / f"large-{index}.bin").write_bytes(
                bytes([index]) + b"\xff" * (256 * 1024)
            )
        self.run_git("add", ".")
        self.run_git("commit", "-m", "test: add large payload")
        self.assertEqual(self.prepare()[0], 0)  # Warm schema imports before measuring.
        tracemalloc.start()
        try:
            code, _, stderr = self.prepare()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(code, 0, stderr)
        self.assertLess(peak, 4 * 1024 * 1024)

    def test_git_timeout_is_a_contextual_domain_error_including_ref_checks(self):
        for operation in (
            lambda: ARTIFACTS.run_git(self.root, "rev-parse", "HEAD"),
            lambda: ARTIFACTS.ref_exists(self.root, "refs/tags/missing"),
        ):
            with (
                patch.object(
                    ARTIFACTS.git_objects.process_runner,
                    "run",
                    side_effect=subprocess.TimeoutExpired("git", 0.01),
                ),
                self.assertRaisesRegex(ARTIFACTS.ReleaseArtifactError, "timed out"),
            ):
                operation()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.run_git("init")
        self.run_git("config", "user.name", "Release Artifact Test")
        self.run_git("config", "user.email", "test@example.com")
        self.run_git("config", "core.autocrlf", "false")
        (self.root / "templates" / "release").mkdir(parents=True)
        for name in ("manifest.template.json", "manifest.schema.json"):
            shutil.copyfile(
                SOURCE_ROOT / "templates" / "release" / name,
                self.root / "templates" / "release" / name,
            )
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Example\n", encoding="utf-8")
        (self.root / "mixed.txt").write_bytes(b"one\r\ntwo\n")
        (self.root / "binary.bin").write_bytes(b"\x00\x01\x02")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "test: create fixture")
        (self.root / "ignored.txt").write_text("ignored\n", encoding="utf-8")
        (self.root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        self.metadata_path = Path(self.temporary.name) / "metadata.json"
        self.write_metadata()

    def tearDown(self):
        self.temporary.cleanup()

    def run_git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def run_main(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = ARTIFACTS.main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def write_metadata(self, **changes):
        value = {
            "program_id": "example-app",
            "name": "Example App",
            "channel": "stable",
            "critical_update": False,
            "release_notes": ["Add release identification artifacts."],
            "update": {
                "min_source_version": "1.0.0",
                "strategy": "patch",
                "preserve_paths": ["config/local.json"],
                "remove_obsolete_files": True,
                "backup_required": True,
                "restart_required": False,
                "rollback_supported": True,
                "migrations": [],
            },
            "artifact": {
                "id": "source-tree",
                "target": {
                    "os": "any",
                    "arch": "any",
                    "min_os_version": "not-applicable",
                },
            },
            "metadata": {
                "author": "Example Maintainers",
                "license": "MIT",
                "support_url": "https://example.com/support",
            },
        }
        value.update(changes)
        self.metadata_path.write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )

    def prepare(self, ref="v1.2.3"):
        return self.run_main(
            "--force",
            "prepare",
            "--release-ref",
            ref,
            "--release-date",
            "2026-08-18T12:00:00Z",
            "--metadata-file",
            str(self.metadata_path),
            "--repository-root",
            str(self.root),
        )

    def test_rejects_unsafe_inputs_and_malformed_git_protocol_records(self):
        invalid_paths = ("", "../escape", "/absolute", "bad\\path", "bad\npath")
        for value in invalid_paths:
            with (
                self.subTest(path=value),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.validate_relative_path(value)

        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.require_repository_root(Path(self.temporary.name) / "missing")
        nested = self.root / "nested"
        nested.mkdir()
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.require_repository_root(nested)

        protocol_results = (
            subprocess.CompletedProcess([], 1, b"", b"failure"),
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, b"abc blob -1\n", b""),
            subprocess.CompletedProcess([], 0, b"abc blob nope\n", b""),
            subprocess.CompletedProcess([], 0, b"abc blob " + b"9" * 100 + b"\n", b""),
            subprocess.CompletedProcess([], 0, b"def blob 1\nx\n", b""),
            subprocess.CompletedProcess([], 0, b"abc blob 1\nx", b""),
            subprocess.CompletedProcess([], 0, b"abc blob 1\nx\nextra", b""),
        )
        native_popen = subprocess.Popen
        for result in protocol_results:
            child = (
                "import sys; sys.stdin.buffer.readline(); "
                f"sys.stdout.buffer.write({result.stdout!r}); "
                f"sys.stderr.buffer.write({result.stderr!r}); "
                f"sys.exit({result.returncode})"
            )
            with (
                self.subTest(stdout=result.stdout),
                patch.object(
                    ARTIFACTS.git_objects.subprocess,
                    "Popen",
                    side_effect=lambda *args, **kwargs: native_popen(
                        (
                            [sys.executable, "-B", "-c", child]
                            if Path(args[0][0]).stem == "git"
                            else args[0]
                        ),
                        **kwargs,
                    ),
                ),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError) as caught,
            ):
                ARTIFACTS.read_blobs(self.root, [("file", "100644", "abc")])
            if result.returncode:
                self.assertIn("failure", str(caught.exception))
        self.assertEqual(ARTIFACTS.read_blobs(self.root, []), {})

        invalid_index_records = (
            b"100644 abc 1\tfile\0",
            b"100600 abc 0\tfile\0",
            b"100644 abc 0\t\xff\0",
        )
        for output in invalid_index_records:
            with (
                self.subTest(index=output),
                patch.object(ARTIFACTS, "run_git", return_value=output),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.index_records(self.root)
        with patch.object(
            ARTIFACTS,
            "run_git",
            return_value=b"160000 abc 0\tsubmodule\0",
        ):
            self.assertEqual(ARTIFACTS.index_records(self.root), [])

        invalid_tree_records = (
            b"100600 blob abc\tfile\0",
            b"100644 blob abc\t\xff\0",
        )
        for output in invalid_tree_records:
            with (
                self.subTest(tree=output),
                patch.object(ARTIFACTS, "run_git", return_value=output),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.tree_records(self.root, "HEAD")
        with patch.object(
            ARTIFACTS,
            "run_git",
            return_value=b"160000 commit abc\tsubmodule\0",
        ):
            self.assertEqual(ARTIFACTS.tree_records(self.root, "HEAD"), [])

    def test_validates_release_metadata_and_template_boundaries(self):
        self.assertEqual(ARTIFACTS.line_ending("one\r\ntwo\r\n"), "CRLF")
        self.assertEqual(ARTIFACTS.line_ending("one\ntwo\n"), "LF")
        self.assertEqual(ARTIFACTS.line_ending("one\rtwo\r"), "CR")
        self.assertIsNone(ARTIFACTS.line_ending("one\r\ntwo\n"))
        self.assertIsNone(ARTIFACTS.line_ending("one"))
        self.assertEqual(
            ARTIFACTS.file_record("binary", "120000", b"\xff")["file_type"],
            "binary",
        )
        self.assertEqual(
            ARTIFACTS.file_record("nul", "100644", b"a\0b")["file_type"],
            "binary",
        )

        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.release_payload({}, "1.2.3", False)
        files, checksums = ARTIFACTS.release_payload({}, "1.2.3", True)
        self.assertEqual(files[0]["relative_path"], "VERSION")
        self.assertIn(b"  VERSION\n", checksums)

        invalid_dates = ("2026-08-18", "2026-02-30T12:00:00Z")
        for value in invalid_dates:
            with (
                self.subTest(date=value),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.parse_release_date(value)
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.version_from_ref("1.2.3")

        invalid_json = (b"\xff", b"{", b"[]")
        for content in invalid_json:
            with (
                self.subTest(json=content),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.parse_json_object(content, "test JSON")
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.load_json_object(
                Path(self.temporary.name) / "missing.json", "test JSON"
            )
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.load_metadata(self.root, self.root / "metadata.json")

        invalid_metadata = (
            {"unexpected": True},
            {**json.loads(self.metadata_path.read_text("utf-8")), "update": {}},
            {**json.loads(self.metadata_path.read_text("utf-8")), "artifact": {}},
            {
                **json.loads(self.metadata_path.read_text("utf-8")),
                "artifact": {"id": "source", "target": {}},
            },
            {**json.loads(self.metadata_path.read_text("utf-8")), "metadata": {}},
        )
        for index, value in enumerate(invalid_metadata):
            candidate = Path(self.temporary.name) / f"invalid-{index}.json"
            candidate.write_text(json.dumps(value), encoding="utf-8")
            with (
                self.subTest(metadata=index),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.load_metadata(self.root, candidate)

        for content in (b"{", b"[]"):
            with (
                self.subTest(template=content),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.parse_template(content, "test template")
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.load_template(Path(self.temporary.name) / "missing-template")
        self.assertEqual(
            ARTIFACTS.render_value({"nested": ["{{value}}", 3]}, {"value": "resolved"}),
            {"nested": ["resolved", 3]},
        )
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.render_value("{{missing}}", {})

        metadata = json.loads(self.metadata_path.read_text("utf-8"))
        invalid_templates = (
            b'{"artifacts": []}',
            b'{"artifacts": ["invalid"]}',
            b'{"artifacts": [{"files": []}]}',
        )
        for content in invalid_templates:
            with (
                self.subTest(build_template=content),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.build_manifest(
                    self.root,
                    metadata,
                    "1.2.3",
                    "2026-08-18T12:00:00Z",
                    [],
                    b"",
                    content,
                )

    def test_confirmation_and_template_rendering_fail_closed(self):
        with (
            patch.object(ARTIFACTS.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="yes"),
        ):
            ARTIFACTS.confirm_write(False)
        with (
            patch.object(ARTIFACTS.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="no"),
            self.assertRaises(ARTIFACTS.ReleaseArtifactError),
        ):
            ARTIFACTS.confirm_write(False)

        metadata = json.loads(self.metadata_path.read_text("utf-8"))
        invalid_render_templates = (
            b'{"artifacts": [{"files": ["{{file-relative-path}}"]}]}',
            b'{"unresolved": "prefix {{unknown}}", "artifacts": [{"files": [{}]}]}',
        )
        file_record = ARTIFACTS.file_record("VERSION", "100644", b"1.2.3\n")
        for content in invalid_render_templates:
            with (
                self.subTest(render_template=content),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.build_manifest(
                    self.root,
                    metadata,
                    "1.2.3",
                    "2026-08-18T12:00:00Z",
                    [file_record],
                    b"checksum",
                    content,
                )

        for returncode, expected in ((0, True), (1, False)):
            result = subprocess.CompletedProcess([], returncode, b"", b"")
            with (
                self.subTest(returncode=returncode),
                patch.object(
                    ARTIFACTS.git_objects.process_runner, "run", return_value=result
                ),
            ):
                self.assertEqual(
                    ARTIFACTS.ref_exists(self.root, "refs/tags/v1.2.3"), expected
                )

    def test_cli_reports_missing_content_and_preserves_verbose_failures(self):
        code, _, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )
        self.assertEqual(code, 1)
        self.assertIn("does not contain manifest.json", stderr)

        with (
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
            self.assertRaises(ARTIFACTS.ReleaseArtifactError),
        ):
            ARTIFACTS.main(
                [
                    "--verbose",
                    "--force",
                    "prepare",
                    "--release-ref",
                    "invalid",
                    "--release-date",
                    "2026-08-18T12:00:00Z",
                    "--metadata-file",
                    str(self.metadata_path),
                    "--repository-root",
                    str(self.root),
                ]
            )

    def test_prepare_writes_deterministic_release_identification(self):
        code, stdout, stderr = self.prepare()

        self.assertEqual(code, 0, stderr)
        self.assertEqual((self.root / "VERSION").read_bytes(), b"1.2.3\n")
        checksums = (self.root / "SHA256SUMS").read_text(encoding="utf-8")
        self.assertIn("  VERSION\n", checksums)
        self.assertNotIn("manifest.json", checksums)
        self.assertNotIn("SHA256SUMS", checksums)
        self.assertNotIn("ignored.txt", checksums)
        self.assertNotIn("untracked.txt", checksums)
        manifest = json.loads((self.root / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["version"], "1.2.3")
        self.assertEqual(manifest["artifacts"][0]["format"], "git-tree")
        paths = [item["relative_path"] for item in manifest["artifacts"][0]["files"]]
        self.assertEqual(
            paths,
            sorted(paths, key=lambda path: path.encode("utf-8")),
        )
        self.assertIn("VERSION", paths)
        self.assertNotIn("manifest.json", paths)
        mixed = next(
            item
            for item in manifest["artifacts"][0]["files"]
            if item["relative_path"] == "mixed.txt"
        )
        binary = next(
            item
            for item in manifest["artifacts"][0]["files"]
            if item["relative_path"] == "binary.bin"
        )
        self.assertIsNone(mixed["line_ending"])
        self.assertEqual(binary["file_type"], "binary")
        self.assertIsNone(binary["encoding"])
        self.assertEqual(
            json.loads(stdout)["changed"],
            ["VERSION", "SHA256SUMS", "manifest.json"],
        )

    def test_dry_run_does_not_write(self):
        code, stdout, stderr = self.run_main(
            "--dry-run",
            "prepare",
            "--release-ref",
            "v1.2.3",
            "--release-date",
            "2026-08-18T12:00:00Z",
            "--metadata-file",
            str(self.metadata_path),
            "--repository-root",
            str(self.root),
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(json.loads(stdout)["changed"]), 3)
        for path in ("VERSION", "SHA256SUMS", "manifest.json"):
            self.assertFalse((self.root / path).exists())

    def test_prepare_requires_force_without_a_terminal(self):
        with patch.object(ARTIFACTS.sys.stdin, "isatty", return_value=False):
            code, _, stderr = self.run_main(
                "prepare",
                "--release-ref",
                "v1.2.3",
                "--release-date",
                "2026-08-18T12:00:00Z",
                "--metadata-file",
                str(self.metadata_path),
                "--repository-root",
                str(self.root),
            )

        self.assertEqual(code, 1)
        self.assertIn("--force", stderr)

    def test_prepare_rejects_unknown_metadata(self):
        self.write_metadata(channel="")

        code, _, stderr = self.prepare()

        self.assertEqual(code, 1)
        self.assertIn("schema", stderr.lower())
        self.assertFalse((self.root / "VERSION").exists())

    def test_check_validates_index_and_tag(self):
        self.assertEqual(self.prepare()[0], 0)
        self.run_git("add", "VERSION", "SHA256SUMS", "manifest.json")

        code, stdout, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["treeish"], "index")

        self.run_git("commit", "-m", "chore: prepare release artifacts")
        self.run_git("tag", "-a", "v1.2.3", "-m", "Release v1.2.3")
        code, stdout, stderr = self.run_main(
            "check",
            "--expected-ref",
            "v1.2.3",
            "--treeish",
            "v1.2.3",
            "--repository-root",
            str(self.root),
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["releaseRef"], "v1.2.3")

    def test_check_rejects_checksum_drift(self):
        self.assertEqual(self.prepare()[0], 0)
        (self.root / "SHA256SUMS").write_text(
            "0" * 64 + "  VERSION\n",
            encoding="utf-8",
        )
        self.run_git("add", "VERSION", "SHA256SUMS", "manifest.json")

        code, _, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )

        self.assertEqual(code, 1)
        self.assertIn("SHA256SUMS", stderr)

    def test_prepare_accepts_full_semver(self):
        code, _, stderr = self.prepare("v2.0.0-rc.1+build.7")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            (self.root / "VERSION").read_text(encoding="utf-8"),
            "2.0.0-rc.1+build.7\n",
        )

    def test_prepare_rejects_incomplete_nested_metadata(self):
        self.write_metadata(update={"strategy": "patch"})

        code, _, stderr = self.prepare()

        self.assertEqual(code, 1)
        self.assertIn("exact policy fields", stderr)

    def test_check_uses_template_and_schema_from_selected_git_content(self):
        self.assertEqual(self.prepare()[0], 0)
        self.run_git("add", "VERSION", "SHA256SUMS", "manifest.json")
        (self.root / "templates" / "release" / "manifest.template.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (self.root / "templates" / "release" / "manifest.schema.json").write_text(
            "{}\n",
            encoding="utf-8",
        )

        code, _, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )

        self.assertEqual(code, 0, stderr)

    def test_check_rejects_staged_template_drift(self):
        self.assertEqual(self.prepare()[0], 0)
        template_path = self.root / "templates" / "release" / "manifest.template.json"
        template_path.write_text("{}\n", encoding="utf-8")
        self.run_git(
            "add",
            "VERSION",
            "SHA256SUMS",
            "manifest.json",
            "templates/release/manifest.template.json",
        )

        code, _, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )

        self.assertEqual(code, 1)
        self.assertIn("SHA256SUMS", stderr)


class RepositoryArtifactTests(unittest.TestCase):
    run_git = ReleaseArtifactTests.run_git
    run_main = ReleaseArtifactTests.run_main

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.run_git("init")
        self.run_git("config", "user.name", "Repository Inventory Test")
        self.run_git("config", "user.email", "test@example.com")
        self.run_git("config", "core.autocrlf", "false")
        self.schema_path = (
            self.root / "templates/release/repository-manifest.schema.json"
        )
        self.schema_path.parent.mkdir(parents=True)
        shutil.copyfile(
            SOURCE_ROOT / "templates/release/repository-manifest.schema.json",
            self.schema_path,
        )
        (self.root / "tracked.txt").write_bytes(b"staged\n")
        self.run_git("add", ".")

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self, *options, dry_run=False):
        try:
            return self.run_main(
                "--dry-run" if dry_run else "--force",
                "prepare",
                "--kind",
                "repository",
                "--release-ref",
                "v1.0.0",
                "--release-date",
                "2026-09-12T12:00:00Z",
                "--repository-root",
                str(self.root),
                *options,
            )
        except SystemExit as error:
            return error.code, "", "CLI rejected repository preparation"

    def stage_outputs(self):
        self.run_git("add", "VERSION", "SHA256SUMS", "manifest.json")

    def test_skill_repository_commands_select_runnable_format(self):
        reference = (
            SOURCE_ROOT
            / ".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt"
        ).read_text(encoding="utf-8")
        commands = [
            shlex.split(
                block.replace("\\\n", " ")
                .replace("<tag>", "v1.0.0")
                .replace("<date-UTC>", "2026-09-12T12:00:00Z")
            )
            for block in re.findall(r"```text\n(.*?)```", reference, re.DOTALL)
            if "prepare --kind repository" in block
        ]
        self.assertEqual(
            len(commands), 2, "Document repository dry-run and apply commands"
        )
        self.run_git("commit", "-m", "test: initial repository fixture")
        before = (self.root / ".git/index").read_bytes()
        for command, option in zip(commands, ("--dry-run", "--force"), strict=True):
            self.assertEqual(command[:2], ["python", "tools/release-artifacts.py"])
            self.assertIn(option, command)
            self.assertNotIn("--metadata-file", command)
            code, _, error = self.run_main(
                *command[2:], "--repository-root", str(self.root)
            )
            self.assertEqual(code, 0, error)
            if option == "--dry-run":
                self.assertFalse((self.root / "manifest.json").exists())
                self.assertEqual((self.root / ".git/index").read_bytes(), before)
        self.stage_outputs()
        self.assertEqual(self.check("--index", "--expected-ref", "v1.0.0")[0], 0)

    def check(self, *options):
        return self.run_main("check", "--repository-root", str(self.root), *options)

    def test_unborn_index_prepares_inventory_and_first_tag_passes_existing_check(self):
        (self.root / "tracked.txt").write_bytes(b"unstaged drift\n")
        code, stdout, stderr = self.prepare("--index")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["releaseRef"], "v1.0.0")
        manifest = json.loads((self.root / "manifest.json").read_bytes())
        self.assertEqual(
            set(manifest),
            {"manifest_version", "release_kind", "version", "release_date", "artifact"},
        )
        self.assertEqual(manifest["manifest_version"], "3.0.0")
        inventory = manifest["artifact"]
        tracked = next(
            item
            for item in inventory["files"]
            if item["relative_path"] == "tracked.txt"
        )
        self.assertEqual(
            tracked["sha256"],
            "9ac007af3de930baf647288da0c843b26a5f046a3fe1351f1bb039b242d22cdf",
        )
        self.assertEqual(tracked["size_bytes"], 7)
        self.stage_outputs()
        self.schema_path.write_text("invalid worktree schema", encoding="utf-8")
        for name in ("VERSION", "SHA256SUMS", "manifest.json"):
            (self.root / name).write_bytes(b"worktree drift")
        self.assertEqual(self.check("--index")[0], 0)
        self.run_git("commit", "-m", "test: first repository commit")
        self.run_git("tag", "-a", "v1.0.0", "-m", "Repository v1.0.0")
        code, stdout, stderr = self.check(
            "--treeish", "v1.0.0", "--expected-ref", "v1.0.0"
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["treeish"], "v1.0.0")

    def test_repository_dry_run_does_not_write_or_change_index(self):
        before = self.run_git("ls-files", "--stage")
        code, stdout, stderr = self.prepare("--index", dry_run=True)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            json.loads(stdout)["changed"], ["VERSION", "SHA256SUMS", "manifest.json"]
        )
        self.assertEqual(self.run_git("ls-files", "--stage"), before)
        for name in ("VERSION", "SHA256SUMS", "manifest.json"):
            self.assertFalse((self.root / name).exists())

    def test_repository_preparation_uses_selected_schema_and_requires_it(self):
        self.schema_path.write_text(
            '{"type":"object","properties":{"release_kind":{"const":"deployment"}}}',
            encoding="utf-8",
        )
        self.run_git("add", str(self.schema_path))
        code, _, stderr = self.prepare("--index")
        self.assertEqual(code, 1)
        self.assertIn("schema", stderr)
        self.run_git("rm", "--cached", str(self.schema_path))
        code, _, stderr = self.prepare("--index")
        self.assertEqual(code, 1)
        self.assertIn("schema", stderr)
        self.assertFalse((self.root / "VERSION").exists())

    def test_repository_rejects_metadata_instead_of_ignoring_it(self):
        code, _, stderr = self.prepare(
            "--index", "--metadata-file", str(Path(self.temporary.name) / "absent.json")
        )
        self.assertEqual(code, 1)
        self.assertIn("metadata", stderr)

    def test_repository_preparation_rejects_invalid_ref_date_and_selection(self):
        for options in (
            ("--release-ref", "v01.0.0"),
            ("--release-date", "2026-09-12T14:00:00+02:00"),
            ("--release-date", "2026-02-30T12:00:00Z"),
        ):
            with self.subTest(options=options):
                self.assertEqual(self.prepare("--index", *options)[0], 1)
                self.assertFalse((self.root / "VERSION").exists())
        self.assertEqual(self.prepare("--index", "--treeish", "HEAD")[0], 2)
        self.assertEqual(self.prepare("--index", "--kind", "unknown")[0], 2)

    def test_deployment_still_requires_explicit_metadata(self):
        code, _, stderr = self.run_main(
            "prepare",
            "--release-ref",
            "v1.0.0",
            "--release-date",
            "2026-09-12T12:00:00Z",
            "--repository-root",
            str(self.root),
        )
        self.assertEqual(code, 1)
        self.assertIn("requires --metadata-file", stderr)
        self.assertFalse((self.root / "VERSION").exists())

    def test_repository_treeish_and_default_head_remain_distinct_from_index(self):
        self.run_git("commit", "-m", "test: repository fixture")
        (self.root / "tracked.txt").write_bytes(b"new staged data\n")
        self.run_git("add", "tracked.txt")
        for options in ((), ("--treeish", "HEAD")):
            code, _, stderr = self.prepare(*options)
            self.assertEqual(code, 0, stderr)
            self.assertIn(b"  tracked.txt\n", (self.root / "SHA256SUMS").read_bytes())
            manifest = json.loads((self.root / "manifest.json").read_bytes())
            record = next(
                item
                for item in manifest["artifact"]["files"]
                if item["relative_path"] == "tracked.txt"
            )
            self.assertEqual(record["size_bytes"], 7)

    def test_repository_check_rejects_missing_altered_controls_inventory_and_modes(
        self,
    ):
        self.assertEqual(self.prepare("--index")[0], 0)
        self.stage_outputs()
        originals = {
            name: (self.root / name).read_bytes()
            for name in ("VERSION", "SHA256SUMS", "manifest.json")
        }
        for name in (
            "VERSION",
            "SHA256SUMS",
            "templates/release/repository-manifest.schema.json",
        ):
            with self.subTest(missing=name):
                self.run_git("rm", "--cached", name)
                self.assertEqual(self.check("--index")[0], 1)
                self.run_git("add", name)
        for name in ("VERSION", "SHA256SUMS"):
            with self.subTest(altered=name):
                (self.root / name).write_bytes(b"incorrect\n")
                self.run_git("add", name)
                self.assertEqual(self.check("--index")[0], 1)
                (self.root / name).write_bytes(originals[name])
                self.run_git("add", name)
        for name in ("VERSION", "SHA256SUMS", "manifest.json", "tracked.txt"):
            with self.subTest(mode=name):
                self.run_git("update-index", "--chmod=+x", name)
                self.assertEqual(self.check("--index")[0], 1)
                self.run_git("update-index", "--chmod=-x", name)
        (self.root / "tracked.txt").write_bytes(b"altered inventory\n")
        self.run_git("add", "tracked.txt")
        self.assertEqual(self.check("--index")[0], 1)

    def test_repository_check_rejects_unsupported_manifest_and_invalid_values(self):
        self.assertEqual(self.prepare("--index")[0], 0)
        self.stage_outputs()
        original = json.loads((self.root / "manifest.json").read_bytes())
        mutations = (
            {"manifest_version": "9.0.0"},
            {"manifest_version": "2.0.0"},
            {"release_kind": "deployment"},
            {"release_kind": None},
            {"version": "01.0.0"},
            {"release_date": "2026-09-12T14:00:00+02:00"},
            {"release_date": "2026-02-30T12:00:00Z"},
            {"artifact": {**original["artifact"], "total_files": 999}},
            {"artifact": {**original["artifact"], "files": []}},
            {"artifact": {**original["artifact"], "size_bytes": 0}},
            {"artifact": {**original["artifact"], "sha256": "0" * 64}},
            {"artifact": {**original["artifact"], "format": "zip"}},
            {"metadata": {"author": "invented"}},
            {"artifact": {**original["artifact"], "built_at": "2026-09-11T12:00:00Z"}},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                (self.root / "manifest.json").write_text(
                    json.dumps({**original, **mutation}), encoding="utf-8"
                )
                self.run_git("add", "manifest.json")
                self.assertEqual(self.check("--index")[0], 1)
        (self.root / "manifest.json").write_bytes(b"[]")
        self.run_git("add", "manifest.json")
        self.assertEqual(self.check("--index")[0], 1)


class ReleaseDependencyTests(unittest.TestCase):
    def test_release_lock_preserves_shared_versions_and_hashes_without_linters(self):
        def declarations(path):
            text = path.read_text(encoding="utf-8")
            blocks = re.split(
                r"(?m)^(?=[A-Za-z][A-Za-z0-9_.-]*(?:\[[^\]]+\])?==)", text
            )
            result = {}
            for block in blocks:
                match = re.match(r"([A-Za-z0-9_.-]+)(\[[^\]]+\])?==([^\s\\]+)", block)
                if match:
                    hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})\b", block))
                    self.assertTrue(hashes, match.group(1))
                    result[match.group(1)] = (match.group(3), hashes, match.group(2))
            return result

        release = declarations(SOURCE_ROOT / "tools/release-artifacts-requirements.txt")
        quality = declarations(SOURCE_ROOT / "tools/quality/requirements.lock")
        self.assertIn("jsonschema", release)
        self.assertEqual(release["jsonschema"][2], "[format]")
        self.assertLess(len(release), len(quality))
        for name, (version, hashes, _extras) in release.items():
            with self.subTest(name=name):
                self.assertIn(name, quality)
                self.assertEqual((version, hashes), quality[name][:2])
        for name in ("codespell", "coverage", "mypy", "ruff", "yamllint", "pyyaml"):
            self.assertNotIn(name, release)


if __name__ == "__main__":
    unittest.main()
