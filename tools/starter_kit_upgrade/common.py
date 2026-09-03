"""Shared constants, diagnostics, and content helpers for starter upgrades."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
import traceback
from typing import Any, NamedTuple

VERSION = "0.3.1"
MAX_ARCHIVE_SIZE = 256 * 1024 * 1024
PROVENANCE_PATH = "_agent-rules-source.json"
FILES_MANIFEST_PATH = "_starter-kit-files.json"
ADOPTION_PATH = ".starter-kit-adoption.json"
STARTER_MANIFEST_PATH = "starter-kit-manifest.json"
UPGRADE_MANIFEST_PATH = "upgrade-manifest.json"
PAYLOAD_PREFIX = "payload/"
BASE_PAYLOAD_PREFIX = "base/"
LOG_DIRECTORY = "logs"
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILENAME_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
SEMVER_TAG_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)$"
)


class UpgradeError(RuntimeError):
    """Raised when an upgrade cannot be built, planned, or applied safely."""


class FileSnapshot(NamedTuple):
    """Store the content and filesystem mode needed for safe restoration."""

    content: bytes
    mode: int


def local_now() -> datetime:
    """Return the local wall-clock time used by human-readable diagnostics."""
    return datetime.now().astimezone()


class RunJournal:
    """Write one timestamped, release-specific execution journal."""

    def __init__(self, command: str, arguments: list[str]) -> None:
        self.command = command
        self.arguments = list(arguments)
        self.path: Path | None = None
        self.target_release: str | None = None
        self.update_status = "FAILED"
        self.operational_compliance = "NON_COMPLIANT"
        self.exact_release_alignment = "UNKNOWN"
        self._stream: Any = None
        self._events: list[tuple[datetime, str, str, str]] = []
        self.write("INFO", "run", f"RUN_START command={command}")
        self.write("INFO", "run", f"PROGRAM_VERSION={VERSION}")
        self.write("INFO", "run", f"PID={os.getpid()}")
        self.write("INFO", "run", f"WORKING_DIRECTORY={Path.cwd().resolve()}")
        self.write("INFO", "run", f"ARGUMENTS={json.dumps(arguments)}")

    def write(self, level: str, phase: str, message: str) -> None:
        timestamp = self._now()
        lines = str(message).splitlines() or [""]
        for line in lines:
            event = (timestamp, level, phase, line)
            if self._stream is None:
                self._events.append(event)
            else:
                self._write_event(event)

    def phase(self, name: str, state: str) -> None:
        self.write("INFO", name, f"PHASE_{state}")

    def bind_target_release(self, release: str) -> Path:
        if self.path is not None:
            if release != self.target_release:
                raise UpgradeError("Target release changed during execution.")
            return self.path
        if not SEMVER_TAG_PATTERN.fullmatch(release):
            raise UpgradeError(
                "Target release must be a stable SemVer tag prefixed with v."
            )

        log_root = Path.cwd().resolve() / LOG_DIRECTORY
        log_root.mkdir(parents=True, exist_ok=True)
        while True:
            filename_timestamp = self._now().strftime(LOG_FILENAME_TIMESTAMP_FORMAT)
            candidate = log_root / (
                f"starter-kit-upgrade-{release}-{filename_timestamp}.log"
            )
            try:
                stream = candidate.open(
                    "x", encoding="utf-8", errors="strict", newline="\n"
                )
            except FileExistsError:
                time.sleep(0.05)
                continue
            self.path = candidate
            self.target_release = release
            self._stream = stream
            break

        buffered = self._events
        self._events = []
        for event in buffered:
            self._write_event(event)
        self.write("INFO", "run", f"TARGET_RELEASE={release}")
        self.write("INFO", "run", f"LOG_FILE={self.path}")
        return self.path

    def set_outcome(
        self,
        update_status: str,
        operational_compliance: str,
        exact_release_alignment: str,
    ) -> None:
        self.update_status = update_status
        self.operational_compliance = operational_compliance
        self.exact_release_alignment = exact_release_alignment

    def record_exception(self, error: BaseException) -> None:
        self.write(
            "ERROR",
            "failure",
            f"EXCEPTION_TYPE={type(error).__name__}",
        )
        self.write("ERROR", "failure", f"EXCEPTION_MESSAGE={error}")
        formatted = traceback.format_exc()
        if formatted and formatted.strip() != "NoneType: None":
            self.write("ERROR", "failure", "TRACEBACK_BEGIN")
            self.write("ERROR", "failure", formatted.rstrip())
            self.write("ERROR", "failure", "TRACEBACK_END")
        if self.update_status != "BLOCKED":
            self.set_outcome("FAILED", "NON_COMPLIANT", "UNKNOWN")

    def finalize(self, exit_code: int) -> None:
        if self._stream is None:
            return
        self.phase("summary", "START")
        self.write("INFO", "summary", f"UPDATE_STATUS={self.update_status}")
        self.write(
            "INFO",
            "summary",
            f"OPERATIONAL_COMPLIANCE={self.operational_compliance}",
        )
        self.write(
            "INFO",
            "summary",
            f"EXACT_RELEASE_ALIGNMENT={self.exact_release_alignment}",
        )
        self.write("INFO", "summary", f"EXIT_CODE={exit_code}")
        self.phase("summary", "END")
        self.write("INFO", "run", "RUN_END")
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        self._stream = None
        timestamp = self._now().strftime(LOG_TIMESTAMP_FORMAT)
        print(f"{timestamp} Log file: {self.path}", file=sys.stderr)

    def _now(self) -> datetime:
        return local_now()

    def _write_event(self, event: tuple[datetime, str, str, str]) -> None:
        timestamp, level, phase, message = event
        formatted_timestamp = timestamp.strftime(LOG_TIMESTAMP_FORMAT)
        self._stream.write(f"{formatted_timestamp} [{level}] [{phase}] {message}\n")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonicalize_text(content: bytes) -> bytes:
    """Return UTF-8 text with LF endings and exactly one final newline."""
    text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return (text.rstrip("\n") + "\n").encode("utf-8") if text else b""


def content_metadata(content: bytes) -> tuple[str, str]:
    """Classify content and return its canonical SHA-256 digest."""
    try:
        canonical = canonicalize_text(content)
    except UnicodeDecodeError:
        return "binary", sha256_bytes(content)
    return "text", sha256_bytes(canonical)


def canonical_sha256(content: bytes, content_kind: str) -> str:
    if content_kind == "binary":
        return sha256_bytes(content)
    if content_kind == "text":
        return sha256_bytes(canonicalize_text(content))
    raise UpgradeError(f"Unsupported content kind: {content_kind}")


def validate_relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise UpgradeError(f"Unsafe archive path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UpgradeError(f"Unsafe archive path: {value!r}")
    return path.as_posix()


def load_json_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpgradeError(f"Invalid JSON in {label}.") from error
    if not isinstance(value, dict):
        raise UpgradeError(f"{label} must contain a JSON object.")
    return value


def write_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=False) + "\n").encode("utf-8")


def starter_release_tag(provenance: dict[str, Any], label: str) -> str:
    starter = provenance.get("starterKit")
    release = starter.get("ref") if isinstance(starter, dict) else None
    if not isinstance(release, str) or not SEMVER_TAG_PATTERN.fullmatch(release):
        raise UpgradeError(
            f"{label} must identify a stable SemVer starter-kit release."
        )
    return release


def log_archive_contents(
    journal: RunJournal | None,
    label: str,
    path: Path,
    files: dict[str, bytes],
) -> None:
    if journal is None:
        return
    journal.write(
        "INFO",
        "archive-validation",
        (
            f"ARCHIVE label={label} path={path} members={len(files)} "
            f"sha256={sha256_file(path)}"
        ),
    )
    for relative, content in sorted(files.items()):
        journal.write(
            "INFO",
            "file",
            (
                f"path={relative} action=READ_ARCHIVE_MEMBER "
                f"archive={label} size={len(content)} "
                f"sha256={sha256_bytes(content)}"
            ),
        )


def log_managed_entries(
    journal: RunJournal | None, managed: list[dict[str, Any]]
) -> None:
    if journal is None:
        return
    for entry in sorted(managed, key=lambda item: item["path"]):
        journal.write(
            "INFO",
            "file",
            (
                f"path={entry['path']} action=VALIDATE_MANAGED_FILE "
                f"strategy={entry['strategy']} mode={entry['mode']} "
                f"contentKind={entry['contentKind']} "
                f"sha256={entry['sha256']} "
                f"canonicalSha256={entry['canonicalSha256']}"
            ),
        )


def starter_commit(provenance: dict[str, Any]) -> str | None:
    starter = provenance.get("starterKit")
    if not isinstance(starter, dict):
        return None
    commit = starter.get("commit")
    return commit if isinstance(commit, str) and commit else None


__all__ = [
    "ADOPTION_PATH",
    "BASE_PAYLOAD_PREFIX",
    "FILES_MANIFEST_PATH",
    "FileSnapshot",
    "LOG_DIRECTORY",
    "LOG_FILENAME_TIMESTAMP_FORMAT",
    "LOG_TIMESTAMP_FORMAT",
    "MAX_ARCHIVE_SIZE",
    "PAYLOAD_PREFIX",
    "PROVENANCE_PATH",
    "RunJournal",
    "SEMVER_TAG_PATTERN",
    "STARTER_MANIFEST_PATH",
    "UPGRADE_MANIFEST_PATH",
    "UpgradeError",
    "VERSION",
    "canonical_sha256",
    "canonicalize_text",
    "content_metadata",
    "load_json_bytes",
    "local_now",
    "log_archive_contents",
    "log_managed_entries",
    "sha256_bytes",
    "sha256_file",
    "starter_commit",
    "starter_release_tag",
    "validate_relative_path",
    "write_json",
]
