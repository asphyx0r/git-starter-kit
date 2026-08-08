#!/usr/bin/env python3
"""Build, inspect, and safely apply cumulative starter-kit upgrades."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, NamedTuple
import zipfile

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
        timestamp = local_now()
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
            filename_timestamp = local_now().strftime(
                LOG_FILENAME_TIMESTAMP_FORMAT
            )
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
        timestamp = local_now().strftime(LOG_TIMESTAMP_FORMAT)
        print(f"{timestamp} Log file: {self.path}", file=sys.stderr)

    def _write_event(self, event: tuple[datetime, str, str, str]) -> None:
        timestamp, level, phase, message = event
        formatted_timestamp = timestamp.strftime(LOG_TIMESTAMP_FORMAT)
        self._stream.write(
            f"{formatted_timestamp} [{level}] [{phase}] {message}\n"
        )


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


def read_archive(path: Path) -> dict[str, bytes]:
    if not path.is_file():
        raise UpgradeError(f"Archive does not exist: {path}")

    files: dict[str, bytes] = {}
    total_size = 0
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = validate_relative_path(info.filename)
                if name in files:
                    raise UpgradeError(f"Duplicate archive path: {name}")
                total_size += info.file_size
                if total_size > MAX_ARCHIVE_SIZE:
                    raise UpgradeError("Archive expands beyond the safety limit.")
                files[name] = archive.read(info)
    except zipfile.BadZipFile as error:
        raise UpgradeError(f"Invalid ZIP archive: {path}") from error
    return files


def load_json_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpgradeError(f"Invalid JSON in {label}.") from error
    if not isinstance(value, dict):
        raise UpgradeError(f"{label} must contain a JSON object.")
    return value


def require_package_provenance(
    files: dict[str, bytes], label: str
) -> dict[str, Any]:
    if PROVENANCE_PATH not in files:
        raise UpgradeError(f"{label} is missing {PROVENANCE_PATH}.")
    provenance = load_json_bytes(files[PROVENANCE_PATH], f"{label}/{PROVENANCE_PATH}")
    starter = provenance.get("starterKit")
    agent_rules = provenance.get("agentRules")
    if not isinstance(starter, dict) or not starter.get("commit"):
        raise UpgradeError(f"{label} has no starter-kit commit provenance.")
    if not isinstance(agent_rules, dict) or not agent_rules.get("commit"):
        raise UpgradeError(f"{label} has no agent-rules commit provenance.")
    return provenance


def validate_new_package(
    files: dict[str, bytes],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    provenance = require_package_provenance(files, "new package")
    if FILES_MANIFEST_PATH not in files:
        raise UpgradeError(f"New package is missing {FILES_MANIFEST_PATH}.")
    manifest = load_json_bytes(
        files[FILES_MANIFEST_PATH], f"new package/{FILES_MANIFEST_PATH}"
    )
    schema_version = manifest.get("schemaVersion")
    if schema_version not in {1, 2, 3} or not isinstance(
        manifest.get("files"), list
    ):
        raise UpgradeError("Unsupported managed-file manifest schema.")

    managed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_entry in manifest["files"]:
        if not isinstance(raw_entry, dict):
            raise UpgradeError("Managed-file entries must be JSON objects.")
        path = validate_relative_path(str(raw_entry.get("path", "")))
        if path in seen or path not in files:
            raise UpgradeError(f"Invalid managed-file entry: {path}")
        seen.add(path)
        digest = str(raw_entry.get("sha256", ""))
        if digest != sha256_bytes(files[path]):
            raise UpgradeError(f"Managed-file digest mismatch: {path}")
        strategy = str(raw_entry.get("strategy", ""))
        allowed_strategies = {
            "agent-rules",
            "initialize-only",
            "merge",
            "replace",
        }
        if schema_version == 3:
            allowed_strategies.add("starter-kit-state")
        if strategy not in allowed_strategies:
            raise UpgradeError(f"Invalid upgrade strategy for {path}: {strategy}")
        if strategy == "starter-kit-state" and path != STARTER_MANIFEST_PATH:
            raise UpgradeError(f"Invalid starter-kit state path: {path}")
        mode = str(raw_entry.get("mode", "100644"))
        if mode not in {"100644", "100755"}:
            raise UpgradeError(f"Unsupported Git mode for {path}: {mode}")
        content_kind, canonical_digest = content_metadata(files[path])
        if schema_version >= 2:
            if raw_entry.get("contentKind") != content_kind:
                raise UpgradeError(f"Managed-file content kind mismatch: {path}")
            if raw_entry.get("canonicalSha256") != canonical_digest:
                raise UpgradeError(f"Managed-file canonical digest mismatch: {path}")
        managed.append(
            {
                "path": path,
                "sha256": digest,
                "canonicalSha256": canonical_digest,
                "contentKind": content_kind,
                "strategy": strategy,
                "mode": mode,
            }
        )
    return provenance, managed


def write_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=False) + "\n").encode("utf-8")


def updated_agent_rules_provenance(
    local_content: bytes | None, new_content: bytes
) -> bytes:
    if local_content is None:
        raise UpgradeError(f"Target is missing {PROVENANCE_PATH}.")
    local_value = load_json_bytes(local_content, f"target {PROVENANCE_PATH}")
    if not isinstance(local_value.get("agentRules"), dict):
        raise UpgradeError(
            f"Target {PROVENANCE_PATH} has no agentRules object."
        )
    new_value = load_json_bytes(new_content, f"new {PROVENANCE_PATH}")
    for field in ("repository", "starterKit"):
        value = new_value.get(field)
        if not isinstance(value, dict):
            raise UpgradeError(f"New {PROVENANCE_PATH} has no {field} object.")
        local_value[field] = value
    return write_json(local_value)


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


def build_upgrade(
    args: argparse.Namespace, journal: RunJournal | None = None
) -> int:
    if journal is not None:
        journal.phase("preflight", "START")
    base_path = args.base_package.resolve()
    new_path = args.new_package.resolve()
    output_path = args.output.resolve()
    if journal is not None:
        journal.write("INFO", "preflight", f"BASE_PACKAGE={base_path}")
        journal.write("INFO", "preflight", f"NEW_PACKAGE={new_path}")
        journal.write("INFO", "preflight", f"OUTPUT={output_path}")

    if journal is not None:
        journal.phase("archive-validation", "START")
    base_files = read_archive(base_path)
    new_files = read_archive(new_path)
    log_archive_contents(journal, "base-package", base_path, base_files)
    log_archive_contents(journal, "new-package", new_path, new_files)
    base_provenance = require_package_provenance(base_files, "base package")
    new_provenance, managed = validate_new_package(new_files)
    target_release = starter_release_tag(new_provenance, "New package")
    if journal is not None:
        journal.bind_target_release(target_release)
        journal.write(
            "INFO",
            "provenance",
            (
                "BASE_RELEASE="
                + starter_release_tag(base_provenance, "Base package")
            ),
        )
        journal.write(
            "INFO",
            "provenance",
            f"BASE_STARTER_COMMIT={starter_commit(base_provenance)}",
        )
        journal.write(
            "INFO",
            "provenance",
            f"TARGET_STARTER_COMMIT={starter_commit(new_provenance)}",
        )
        log_managed_entries(journal, managed)
        journal.phase("archive-validation", "END")

    if output_path.exists():
        raise UpgradeError(f"Output already exists: {output_path}")
    if output_path.parent == output_path or not output_path.parent.is_dir():
        raise UpgradeError("Upgrade output directory must already exist.")
    if journal is not None:
        journal.phase("preflight", "END")
        journal.phase("manifest-construction", "START")

    entries: list[dict[str, Any]] = []
    payload: dict[str, bytes] = {}
    managed_paths = {entry["path"] for entry in managed}
    managed.append(
        {
            "path": FILES_MANIFEST_PATH,
            "sha256": sha256_bytes(new_files[FILES_MANIFEST_PATH]),
            "canonicalSha256": content_metadata(
                new_files[FILES_MANIFEST_PATH]
            )[1],
            "contentKind": content_metadata(new_files[FILES_MANIFEST_PATH])[0],
            "strategy": "replace",
            "mode": "100644",
        }
    )
    for entry in sorted(managed, key=lambda item: item["path"]):
        path = entry["path"]
        payload_path = PAYLOAD_PREFIX + path
        payload[payload_path] = new_files[path]
        base_content = base_files.get(path)
        base_payload_path = None
        if (
            entry["strategy"] in {"merge", "starter-kit-state"}
            and base_content is not None
        ):
            base_payload_path = BASE_PAYLOAD_PREFIX + path
            payload[base_payload_path] = base_content
        base_canonical_digest = (
            canonical_sha256(base_content, entry["contentKind"])
            if base_content is not None
            else None
        )
        entries.append(
            {
                "path": path,
                "strategy": entry["strategy"],
                "mode": entry["mode"],
                "contentKind": entry["contentKind"],
                "baseSha256": (
                    sha256_bytes(base_content) if base_content is not None else None
                ),
                "baseCanonicalSha256": base_canonical_digest,
                "newSha256": entry["sha256"],
                "newCanonicalSha256": entry["canonicalSha256"],
                "payload": payload_path,
                "basePayload": base_payload_path,
            }
        )
        if journal is not None:
            journal.write(
                "INFO",
                "file",
                (
                    f"path={path} action=INCLUDE_UPGRADE_PAYLOAD "
                    f"strategy={entry['strategy']} mode={entry['mode']} "
                    f"basePresent={base_content is not None} "
                    f"baseCanonicalSha256={base_canonical_digest} "
                    f"targetCanonicalSha256={entry['canonicalSha256']}"
                ),
            )

    obsolete = sorted(
        path
        for path in base_files
        if path not in managed_paths and path != FILES_MANIFEST_PATH
    )
    if journal is not None:
        for path in obsolete:
            journal.write(
                "INFO",
                "file",
                f"path={path} action=PRESERVE_OBSOLETE_FILE",
            )
    manifest = {
        "schemaVersion": 3,
        "base": {
            "archiveSha256": sha256_file(base_path),
            "provenanceSha256": sha256_bytes(base_files[PROVENANCE_PATH]),
            "provenance": base_provenance,
        },
        "target": {
            "archiveSha256": sha256_file(new_path),
            "provenanceSha256": sha256_bytes(new_files[PROVENANCE_PATH]),
            "provenance": new_provenance,
        },
        "entries": entries,
        "obsoletePaths": obsolete,
    }
    if journal is not None:
        journal.write(
            "INFO",
            "manifest-construction",
            f"UPGRADE_ENTRIES={len(entries)}",
        )
        journal.write(
            "INFO",
            "manifest-construction",
            f"OBSOLETE_PATHS={len(obsolete)}",
        )
        journal.phase("manifest-construction", "END")

    if args.dry_run:
        print(
            json.dumps(
                {
                    "operation": "build",
                    "output": str(output_path),
                    "entries": len(entries),
                    "obsoletePaths": len(obsolete),
                    "wouldWrite": False,
                },
                indent=2,
            )
        )
        return 0

    if journal is not None:
        journal.phase("artifact-write", "START")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=output_path.name + ".",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(UPGRADE_MANIFEST_PATH, write_json(manifest))
            for path, content in sorted(payload.items()):
                archive.writestr(path, content)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    if journal is not None:
        journal.write(
            "INFO",
            "artifact-write",
            f"path={output_path} action=CREATE_UPGRADE_ARCHIVE",
        )
        journal.phase("artifact-write", "END")
        journal.phase("post-verification", "START")
    verified_manifest, verified_files = load_upgrade(output_path)
    if verified_manifest["target"]["provenance"] != new_provenance:
        raise UpgradeError("Created upgrade target provenance is inconsistent.")
    log_archive_contents(journal, "created-upgrade", output_path, verified_files)
    if journal is not None:
        journal.phase("post-verification", "END")
        journal.set_outcome(
            "ARTIFACT_CREATED", "ARTIFACT_COMPLIANT", "NOT_APPLICABLE"
        )
    print(f"Created cumulative upgrade package: {output_path}")
    return 0


def build_toolkit(
    args: argparse.Namespace, journal: RunJournal | None = None
) -> int:
    if journal is not None:
        journal.phase("preflight", "START")
    package_path = args.new_package.resolve()
    output_path = args.output.resolve()
    if journal is not None:
        journal.write("INFO", "preflight", f"NEW_PACKAGE={package_path}")
        journal.write("INFO", "preflight", f"OUTPUT={output_path}")
        journal.phase("archive-validation", "START")
    package_files = read_archive(package_path)
    log_archive_contents(journal, "new-package", package_path, package_files)
    new_provenance, managed = validate_new_package(package_files)
    target_release = starter_release_tag(new_provenance, "New package")
    if journal is not None:
        journal.bind_target_release(target_release)
        journal.write(
            "INFO",
            "provenance",
            f"TARGET_STARTER_COMMIT={starter_commit(new_provenance)}",
        )
        log_managed_entries(journal, managed)
        journal.phase("archive-validation", "END")
    if output_path.exists():
        raise UpgradeError(f"Output already exists: {output_path}")
    if not output_path.parent.is_dir():
        raise UpgradeError("Toolkit output directory must already exist.")
    if journal is not None:
        journal.phase("preflight", "END")
    script_path = Path(__file__).resolve()
    readme = f"""# Starter Kit Upgrade Toolkit

This toolkit contains:

- `starter-kit-upgrade.py`, the cumulative upgrade builder and guarded applier;
- `packages/{package_path.name}`, the new complete starter-kit package.

Build a cumulative package by supplying the exact full package used to
initialize the target:

```text
python starter-kit-upgrade.py build --base-package BASE.zip --new-package packages/{package_path.name} --output UPGRADE.zip
```

Inspect a target before writing:

```text
python starter-kit-upgrade.py plan --upgrade-package UPGRADE.zip --target REPOSITORY
```

Application additionally requires a clean repository, valid provenance, no
conflicts, and an existing backup directory outside the target.

Every non-dry-run command writes a detailed execution journal below `logs/` in
the current directory. The log filename identifies the target release and run
timestamp. Dry-run, help, version, and argument-parser exits do not write logs.
"""
    if args.dry_run:
        print(
            json.dumps(
                {
                    "operation": "toolkit",
                    "output": str(output_path),
                    "newPackage": str(package_path),
                    "wouldWrite": False,
                },
                indent=2,
            )
        )
        return 0

    if journal is not None:
        journal.phase("artifact-write", "START")
        journal.write(
            "INFO",
            "file",
            f"path={script_path.name} action=ADD_TOOLKIT_MEMBER source={script_path}",
        )
        journal.write(
            "INFO",
            "file",
            (
                f"path=packages/{package_path.name} "
                f"action=ADD_TOOLKIT_MEMBER source={package_path}"
            ),
        )
        journal.write(
            "INFO",
            "file",
            "path=README.md action=ADD_TOOLKIT_MEMBER source=generated",
        )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=output_path.name + ".",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.write(script_path, script_path.name)
            archive.write(package_path, f"packages/{package_path.name}")
            archive.writestr("README.md", readme.encode("utf-8"))
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    if journal is not None:
        journal.write(
            "INFO",
            "artifact-write",
            f"path={output_path} action=CREATE_TOOLKIT_ARCHIVE",
        )
        journal.phase("artifact-write", "END")
        journal.phase("post-verification", "START")
    verified_files = read_archive(output_path)
    expected_members = {
        script_path.name,
        f"packages/{package_path.name}",
        "README.md",
    }
    if set(verified_files) != expected_members:
        raise UpgradeError("Created toolkit contains unexpected members.")
    if verified_files[script_path.name] != script_path.read_bytes():
        raise UpgradeError("Created toolkit contains an invalid updater.")
    if verified_files[f"packages/{package_path.name}"] != package_path.read_bytes():
        raise UpgradeError("Created toolkit contains an invalid full package.")
    log_archive_contents(journal, "created-toolkit", output_path, verified_files)
    if journal is not None:
        journal.phase("post-verification", "END")
        journal.set_outcome(
            "ARTIFACT_CREATED", "ARTIFACT_COMPLIANT", "NOT_APPLICABLE"
        )
    print(f"Created upgrade toolkit: {output_path}")
    return 0


def load_upgrade(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    files = read_archive(path)
    if UPGRADE_MANIFEST_PATH not in files:
        raise UpgradeError(f"Upgrade package is missing {UPGRADE_MANIFEST_PATH}.")
    manifest = load_json_bytes(files[UPGRADE_MANIFEST_PATH], UPGRADE_MANIFEST_PATH)
    schema_version = manifest.get("schemaVersion")
    if schema_version not in {1, 2, 3} or not isinstance(
        manifest.get("entries"), list
    ):
        raise UpgradeError("Unsupported upgrade package schema.")

    for entry in manifest["entries"]:
        if not isinstance(entry, dict):
            raise UpgradeError("Upgrade entries must be JSON objects.")
        path = validate_relative_path(str(entry.get("path", "")))
        payload_path = validate_relative_path(str(entry.get("payload", "")))
        if not payload_path.startswith(PAYLOAD_PREFIX) or payload_path not in files:
            raise UpgradeError(f"Missing upgrade payload for {path}.")
        if sha256_bytes(files[payload_path]) != entry.get("newSha256"):
            raise UpgradeError(f"Upgrade payload digest mismatch: {path}")
        if schema_version >= 2:
            content_kind = str(entry.get("contentKind", ""))
            if canonical_sha256(files[payload_path], content_kind) != entry.get(
                "newCanonicalSha256"
            ):
                raise UpgradeError(f"Upgrade canonical digest mismatch: {path}")
            base_payload = entry.get("basePayload")
            if base_payload is not None:
                base_payload = validate_relative_path(str(base_payload))
                if (
                    not base_payload.startswith(BASE_PAYLOAD_PREFIX)
                    or base_payload not in files
                ):
                    raise UpgradeError(f"Missing base payload for {path}.")
                if sha256_bytes(files[base_payload]) != entry.get("baseSha256"):
                    raise UpgradeError(f"Base payload digest mismatch: {path}")
    return manifest, files


def target_path(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise UpgradeError(f"Target path traverses a symbolic link: {relative}")
    if path.is_symlink():
        raise UpgradeError(f"Target file is a symbolic link: {relative}")
    return path


def run_git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def validate_adoption(
    root: Path, manifest: dict[str, Any], adoption_path: Path
) -> dict[str, Any] | None:
    if not adoption_path.is_file():
        return None
    adoption = load_json_bytes(adoption_path.read_bytes(), str(adoption_path))
    if adoption.get("schemaVersion") not in {1, 2}:
        return None
    starter = adoption.get("starterKit")
    if not isinstance(starter, dict):
        return None
    matches_known_release = False
    for release_name in ("base", "target"):
        release = manifest[release_name]
        release_starter = release["provenance"].get("starterKit")
        if (
            adoption.get("baseArchiveSha256") == release["archiveSha256"]
            and isinstance(release_starter, dict)
            and starter.get("commit") == release_starter.get("commit")
        ):
            matches_known_release = True
            break
    if not matches_known_release:
        return None
    evidence_commit = adoption.get("repositoryCommit")
    if not isinstance(evidence_commit, str) or not evidence_commit:
        return None
    result = run_git(root, "merge-base", "--is-ancestor", evidence_commit, "HEAD")
    return adoption if result.returncode == 0 else None


def starter_commit(provenance: dict[str, Any]) -> str | None:
    starter = provenance.get("starterKit")
    if not isinstance(starter, dict):
        return None
    commit = starter.get("commit")
    return commit if isinstance(commit, str) and commit else None


def merge_text_payload(local: bytes, base: bytes, new: bytes) -> bytes | None:
    """Return a clean three-way text merge, or None when Git reports conflicts."""
    with tempfile.TemporaryDirectory(prefix="starter-kit-merge-") as directory:
        merge_root = Path(directory)
        paths = {
            "local": merge_root / "local",
            "base": merge_root / "base",
            "new": merge_root / "new",
        }
        paths["local"].write_bytes(canonicalize_text(local))
        paths["base"].write_bytes(canonicalize_text(base))
        paths["new"].write_bytes(canonicalize_text(new))
        result = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                str(paths["local"]),
                str(paths["base"]),
                str(paths["new"]),
            ],
            check=False,
            capture_output=True,
        )
    if result.returncode == 0:
        return result.stdout
    if 1 <= result.returncode <= 127:
        return None
    raise UpgradeError("Unable to perform the three-way file merge.")


def parse_starter_manifest(content: bytes, label: str) -> dict[str, Any]:
    value = load_json_bytes(content, label)
    if value.get("schemaVersion") != 1:
        raise UpgradeError(f"Unsupported starter-kit manifest schema in {label}.")
    if set(value) != {"schemaVersion", "source", "current", "files"}:
        raise UpgradeError(f"Invalid starter-kit manifest fields in {label}.")
    for release_name in ("source", "current"):
        release = value.get(release_name)
        if not isinstance(release, dict):
            raise UpgradeError(f"Invalid {release_name} release in {label}.")
        for field in ("repository", "ref", "releaseUrl", "generatedAt"):
            if not isinstance(release.get(field), str) or not release[field]:
                raise UpgradeError(
                    f"Invalid {release_name}.{field} in {label}."
                )
        expected_url = (
            release["repository"].rstrip("/")
            + "/releases/tag/"
            + release["ref"]
        )
        if release["releaseUrl"] != expected_url:
            raise UpgradeError(f"Invalid {release_name} release URL in {label}.")
    if not isinstance(value.get("files"), list):
        raise UpgradeError(f"Invalid core file inventory in {label}.")
    return value


def starter_release_from_provenance(provenance: dict[str, Any]) -> dict[str, str]:
    starter = provenance.get("starterKit")
    generated_at = provenance.get("generatedAt")
    if not isinstance(starter, dict) or not isinstance(generated_at, str):
        raise UpgradeError("Base package has incomplete starter-kit provenance.")
    repository = starter.get("repository")
    ref = starter.get("ref")
    if not isinstance(repository, str) or not isinstance(ref, str):
        raise UpgradeError("Base package has incomplete starter-kit provenance.")
    return {
        "repository": repository,
        "ref": ref,
        "releaseUrl": repository.rstrip("/") + "/releases/tag/" + ref,
        "generatedAt": generated_at,
    }


def normalized_starter_manifest(
    value: dict[str, Any], source: dict[str, Any]
) -> bytes:
    normalized = dict(value)
    normalized["source"] = source
    return write_json(normalized)


def starter_manifest_action(
    local_content: bytes | None,
    base_content: bytes | None,
    new_content: bytes,
    adopted_source: dict[str, Any] | None,
) -> str:
    new_value = parse_starter_manifest(new_content, "new starter-kit manifest")
    if local_content is None:
        return "add" if base_content is None else "conflict-missing"
    try:
        local_value = parse_starter_manifest(
            local_content, "target starter-kit manifest"
        )
    except UpgradeError:
        return "conflict-modified"
    if local_value["source"]["repository"] != new_value["source"]["repository"]:
        return "conflict-modified"
    base_value = None
    if base_content is not None:
        try:
            base_value = parse_starter_manifest(
                base_content, "base starter-kit manifest"
            )
        except UpgradeError:
            return "conflict-modified"
    expected_source = (
        adopted_source
        if adopted_source is not None
        else base_value["source"]
        if base_value is not None
        else None
    )
    if expected_source is not None and local_value["source"] != expected_source:
        return "conflict-modified"
    if normalized_starter_manifest(local_value, new_value["source"]) == new_content:
        return "aligned"
    if base_value is None:
        return "conflict-modified"
    if normalized_starter_manifest(local_value, base_value["source"]) == base_content:
        return "update"
    return "conflict-modified"


def updated_starter_manifest(
    local_content: bytes | None,
    base_provenance: dict[str, Any],
    new_content: bytes,
) -> bytes:
    new_value = parse_starter_manifest(new_content, "new starter-kit manifest")
    if local_content is None:
        source = starter_release_from_provenance(base_provenance)
    else:
        local_value = parse_starter_manifest(
            local_content, "target starter-kit manifest"
        )
        source = local_value["source"]
    return normalized_starter_manifest(new_value, source)


def evaluate_target(
    manifest: dict[str, Any],
    files: dict[str, bytes],
    root: Path,
    journal: RunJournal | None = None,
) -> dict[str, Any]:
    if journal is not None:
        journal.phase("target-analysis", "START")
        journal.write("INFO", "target-analysis", f"TARGET={root}")
    if not root.is_dir():
        raise UpgradeError(f"Target directory does not exist: {root}")
    if run_git(root, "rev-parse", "--show-toplevel").returncode != 0:
        raise UpgradeError(f"Target is not a Git repository: {root}")

    provenance_path = root / PROVENANCE_PATH
    provenance_status = "invalid"
    if provenance_path.is_file():
        try:
            local_provenance = load_json_bytes(
                provenance_path.read_bytes(), str(provenance_path)
            )
        except UpgradeError:
            local_provenance = {}
        local_starter_commit = starter_commit(local_provenance)
        if local_starter_commit == starter_commit(
            manifest["base"]["provenance"]
        ):
            provenance_status = "base"
        elif local_starter_commit == starter_commit(
            manifest["target"]["provenance"]
        ):
            provenance_status = "target"
    adoption = validate_adoption(root, manifest, root / ADOPTION_PATH)
    if provenance_status == "invalid" and adoption is not None:
        provenance_status = "adopted"
    if journal is not None:
        journal.write(
            "INFO",
            "target-analysis",
            f"PROVENANCE_STATUS={provenance_status}",
        )

    actions: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        relative = entry["path"]
        local_path = target_path(root, relative)
        local_content = local_path.read_bytes() if local_path.is_file() else None
        content_kind = str(entry.get("contentKind", "binary"))
        schema_version = manifest.get("schemaVersion")
        local_digest = (
            canonical_sha256(local_content, content_kind)
            if local_content is not None and schema_version >= 2
            else sha256_bytes(local_content)
            if local_content is not None
            else None
        )
        base_digest = (
            entry.get("baseCanonicalSha256")
            if schema_version >= 2
            else entry.get("baseSha256")
        )
        new_digest = (
            entry.get("newCanonicalSha256")
            if schema_version >= 2
            else entry["newSha256"]
        )
        strategy = entry["strategy"]
        if strategy == "agent-rules":
            if relative != PROVENANCE_PATH:
                action = "delegate-agent-rules"
            else:
                try:
                    updated_provenance = updated_agent_rules_provenance(
                        local_content, files[entry["payload"]]
                    )
                except UpgradeError:
                    action = (
                        "conflict-missing"
                        if local_content is None
                        else "conflict-modified"
                    )
                else:
                    action = (
                        "delegate-agent-rules"
                        if canonical_sha256(updated_provenance, content_kind)
                        == local_digest
                        else "update"
                    )
        elif strategy == "starter-kit-state":
            base_payload = entry.get("basePayload")
            base_content = (
                files[base_payload] if isinstance(base_payload, str) else None
            )
            action = starter_manifest_action(
                local_content,
                base_content,
                files[entry["payload"]],
                adoption.get("starterKitSource")
                if adoption is not None
                and isinstance(adoption.get("starterKitSource"), dict)
                else None,
            )
        elif strategy == "initialize-only":
            if local_digest == new_digest:
                action = "aligned"
            elif base_digest != new_digest:
                action = "review-initialize-only"
            else:
                action = "preserve"
        elif local_digest == new_digest:
            action = "aligned"
        elif local_digest is None and base_digest is None:
            action = "add"
        elif local_digest is None:
            action = "conflict-missing"
        elif local_digest == base_digest:
            action = "update"
        elif (
            strategy == "merge"
            and content_kind == "text"
            and entry.get("basePayload") in files
        ):
            merged = merge_text_payload(
                local_content,
                files[entry["basePayload"]],
                files[entry["payload"]],
            )
            if merged is None:
                action = "conflict-merge"
            elif canonical_sha256(merged, content_kind) == local_digest:
                action = "aligned"
            else:
                action = "merge"
        else:
            action = "conflict-modified"
        actions.append(
            {
                "path": relative,
                "strategy": strategy,
                "action": action,
                "localCanonicalSha256": local_digest,
                "baseCanonicalSha256": base_digest,
                "newCanonicalSha256": new_digest,
            }
        )
        if journal is not None:
            journal.write(
                "INFO",
                "file",
                (
                    f"path={relative} action={action} strategy={strategy} "
                    f"localCanonicalSha256={local_digest} "
                    f"baseCanonicalSha256={base_digest} "
                    f"targetCanonicalSha256={new_digest}"
                ),
            )

    conflicts = [
        action for action in actions if action["action"].startswith("conflict-")
    ]
    status = run_git(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    if status.returncode != 0:
        raise UpgradeError("Unable to inspect target Git status.")
    write_paths = {
        action["path"]
        for action in actions
        if action["action"] in {"add", "merge", "update"}
    } | {ADOPTION_PATH}
    blocking_status: list[str] = []
    preserved_untracked: list[str] = []
    for status_entry in status.stdout.split("\0"):
        if not status_entry:
            continue
        if status_entry.startswith("?? "):
            untracked_path = status_entry[3:]
            if untracked_path in write_paths:
                blocking_status.append(status_entry)
            else:
                preserved_untracked.append(untracked_path)
        else:
            blocking_status.append(status_entry)
    if journal is not None:
        for path in sorted(manifest.get("obsoletePaths", [])):
            journal.write(
                "INFO",
                "file",
                f"path={path} action=PRESERVE_OBSOLETE_FILE",
            )
        for path in sorted(preserved_untracked):
            journal.write(
                "INFO",
                "file",
                f"path={path} action=PRESERVE_UNTRACKED_FILE",
            )
        for entry in blocking_status:
            journal.write(
                "WARNING",
                "target-analysis",
                f"BLOCKING_GIT_STATUS={entry}",
            )
    plan = {
        "schemaVersion": 2,
        "target": str(root),
        "provenance": provenance_status,
        "clean": not blocking_status,
        "preservedUntrackedPaths": sorted(preserved_untracked),
        "actions": actions,
        "obsoletePaths": manifest.get("obsoletePaths", []),
        "summary": {
            name: sum(1 for action in actions if action["action"] == name)
            for name in (
                "add",
                "aligned",
                "delegate-agent-rules",
                "conflict-merge",
                "conflict-missing",
                "conflict-modified",
                "merge",
                "preserve",
                "review-initialize-only",
                "update",
            )
        },
        "applicable": provenance_status in {"base", "adopted"}
        and not conflicts
        and not blocking_status,
    }
    if journal is not None:
        journal.write(
            "INFO",
            "target-analysis",
            f"PLAN_SUMMARY={json.dumps(plan['summary'], sort_keys=True)}",
        )
        journal.write(
            "INFO",
            "target-analysis",
            f"PLAN_APPLICABLE={plan['applicable']}",
        )
        journal.write(
            "INFO", "target-analysis", f"TARGET_CLEAN={plan['clean']}"
        )
        journal.phase("target-analysis", "END")
    return plan


def exact_release_alignment(plan: dict[str, Any]) -> str:
    return (
        "ALIGNED"
        if all(
            action["localCanonicalSha256"]
            == action["newCanonicalSha256"]
            for action in plan["actions"]
        )
        else "NOT_ALIGNED"
    )


def operational_compliance(
    plan: dict[str, Any], target_state_current: bool = False
) -> str:
    actions = {action["action"] for action in plan["actions"]}
    if (
        not target_state_current
        and plan["provenance"] != "target"
    ) or any(
        action.startswith("conflict-") for action in actions
    ):
        return "NON_COMPLIANT"
    if actions.intersection({"add", "merge", "update"}):
        return "NON_COMPLIANT"
    if actions.intersection(
        {"delegate-agent-rules", "review-initialize-only"}
    ):
        return "COMPLIANT_WITH_FOLLOW_UP"
    return "COMPLIANT"


def target_adoption_is_current(
    manifest: dict[str, Any], root: Path, journal: RunJournal | None = None
) -> bool:
    adoption_path = target_path(root, ADOPTION_PATH)
    if not adoption_path.is_file():
        if journal is not None:
            journal.write(
                "ERROR", "post-verification", "ADOPTION_STATUS=MISSING"
            )
        return False
    try:
        adoption = load_json_bytes(adoption_path.read_bytes(), str(adoption_path))
    except UpgradeError:
        if journal is not None:
            journal.write(
                "ERROR", "post-verification", "ADOPTION_STATUS=INVALID"
            )
        return False
    starter = adoption.get("starterKit")
    target_starter = manifest["target"]["provenance"].get("starterKit")
    evidence_commit = adoption.get("repositoryCommit")
    evidence_is_ancestor = (
        isinstance(evidence_commit, str)
        and bool(evidence_commit)
        and run_git(
            root, "merge-base", "--is-ancestor", evidence_commit, "HEAD"
        ).returncode
        == 0
    )
    current = (
        adoption.get("schemaVersion") == 2
        and adoption.get("baseArchiveSha256")
        == manifest["target"]["archiveSha256"]
        and isinstance(starter, dict)
        and isinstance(target_starter, dict)
        and starter == target_starter
        and evidence_is_ancestor
        and isinstance(adoption.get("acceptedFiles"), dict)
    )
    expected_accepted_files: dict[str, str] = {}
    if current:
        for entry in manifest["entries"]:
            if entry["strategy"] != "merge":
                continue
            destination = target_path(root, entry["path"])
            if not destination.is_file():
                current = False
                break
            current_digest = canonical_sha256(
                destination.read_bytes(), entry.get("contentKind", "binary")
            )
            if current_digest != entry.get("newCanonicalSha256"):
                expected_accepted_files[entry["path"]] = current_digest
        if current:
            current = adoption["acceptedFiles"] == expected_accepted_files
    provenance_path = target_path(root, PROVENANCE_PATH)
    if current:
        if not provenance_path.is_file():
            current = False
        else:
            try:
                provenance = load_json_bytes(
                    provenance_path.read_bytes(), str(provenance_path)
                )
            except UpgradeError:
                current = False
            else:
                target_provenance = manifest["target"]["provenance"]
                current = all(
                    provenance.get(field) == target_provenance.get(field)
                    for field in ("repository", "starterKit")
                )
    starter_manifest_path = target_path(root, STARTER_MANIFEST_PATH)
    if current and starter_manifest_path.is_file():
        try:
            starter_manifest = parse_starter_manifest(
                starter_manifest_path.read_bytes(), str(starter_manifest_path)
            )
        except UpgradeError:
            current = False
        else:
            current = (
                adoption.get("starterKitSource")
                == starter_manifest.get("source")
            )
    if journal is not None:
        journal.write(
            "INFO" if current else "ERROR",
            "post-verification",
            f"ADOPTION_STATUS={'CURRENT' if current else 'INVALID'}",
        )
    return current


def print_plan(plan: dict[str, Any]) -> None:
    print(json.dumps(plan, indent=2, sort_keys=False))


def create_rollback_archive(
    root: Path,
    backup_directory: Path,
    actions: list[dict[str, Any]],
    journal: RunJournal | None = None,
) -> Path:
    if journal is not None:
        journal.phase("rollback", "START")
    backup_root = backup_directory.resolve()
    target_root = root.resolve()
    if not backup_root.is_dir():
        raise UpgradeError(f"Backup directory does not exist: {backup_root}")
    try:
        backup_root.relative_to(target_root)
    except ValueError:
        pass
    else:
        raise UpgradeError("Backup directory must stay outside the target.")

    name = f"{root.name}-starter-upgrade-{os.getpid()}.zip"
    backup_path = backup_root / name
    if backup_path.exists():
        raise UpgradeError(f"Backup already exists: {backup_path}")
    with zipfile.ZipFile(backup_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        saved: list[str] = []
        created: list[str] = []
        for action in actions:
            relative = action["path"]
            existing = target_path(root, relative)
            if action["action"] in {"merge", "update"} and existing.is_file():
                archive.write(existing, "files/" + relative)
                saved.append(relative)
                if journal is not None:
                    journal.write(
                        "INFO",
                        "file",
                        (
                            f"path={relative} action=SAVE_ROLLBACK_COPY "
                            f"rollback={backup_path}"
                        ),
                    )
            elif action["action"] == "add":
                created.append(relative)
                if journal is not None:
                    journal.write(
                        "INFO",
                        "file",
                        (
                            f"path={relative} action=RECORD_ROLLBACK_DELETE "
                            f"rollback={backup_path}"
                        ),
                    )
        archive.writestr(
            "rollback-manifest.json",
            write_json(
                {
                    "schemaVersion": 2,
                    "savedPaths": saved,
                    "createdPaths": created,
                }
            ),
        )
    if journal is not None:
        journal.write(
            "INFO",
            "rollback",
            (
                f"ROLLBACK_ARCHIVE={backup_path} saved={len(saved)} "
                f"created={len(created)} sha256={sha256_file(backup_path)}"
            ),
        )
        journal.phase("rollback", "END")
    return backup_path


def write_payload(path: Path, content: bytes, mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            temporary.chmod(
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IRGRP
                | stat.S_IROTH
                | (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH if mode == "100755" else 0)
            )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def snapshot_file(path: Path) -> FileSnapshot | None:
    if path.is_symlink():
        raise UpgradeError(f"Target file is a symbolic link: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise UpgradeError(f"Target path is not a regular file: {path}")
    with path.open("rb") as stream:
        content = stream.read()
        mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
    return FileSnapshot(content=content, mode=mode)


def require_planned_file_state(
    path: Path,
    action: dict[str, Any],
    entry: dict[str, Any],
    schema_version: int,
) -> FileSnapshot | None:
    snapshot = snapshot_file(path)
    actual_digest = None
    if snapshot is not None:
        actual_digest = (
            canonical_sha256(snapshot.content, entry.get("contentKind", "binary"))
            if schema_version >= 2
            else sha256_bytes(snapshot.content)
        )
    if actual_digest != action.get("localCanonicalSha256"):
        raise UpgradeError(f"Target changed after planning: {action['path']}")
    return snapshot


def restore_snapshot(path: Path, snapshot: FileSnapshot) -> None:
    git_mode = "100755" if snapshot.mode & 0o111 else "100644"
    write_payload(path, snapshot.content, git_mode)
    if os.name != "nt":
        path.chmod(snapshot.mode)


def apply_upgrade(
    manifest: dict[str, Any],
    files: dict[str, bytes],
    root: Path,
    plan: dict[str, Any],
    backup_directory: Path,
    journal: RunJournal | None = None,
) -> Path:
    if not plan["applicable"]:
        raise UpgradeError("Upgrade is not applicable; inspect the plan.")
    changes = [
        action
        for action in plan["actions"]
        if action["action"] in {"add", "merge", "update"}
    ]
    adoption_path = target_path(root, ADOPTION_PATH)
    adoption_snapshot = snapshot_file(adoption_path)
    adoption_action = {
        "path": ADOPTION_PATH,
        "action": "update" if adoption_snapshot is not None else "add",
    }
    backup_path = create_rollback_archive(
        root,
        backup_directory,
        changes + [adoption_action],
        journal,
    )
    if snapshot_file(adoption_path) != adoption_snapshot:
        raise UpgradeError(f"Target changed after planning: {ADOPTION_PATH}")
    originals: dict[str, FileSnapshot | None] = {}
    try:
        if journal is not None:
            journal.phase("target-write", "START")
        entries = {entry["path"]: entry for entry in manifest["entries"]}
        for action in changes:
            relative = action["path"]
            destination = target_path(root, relative)
            entry = entries[relative]
            original = require_planned_file_state(
                destination,
                action,
                entry,
                int(manifest.get("schemaVersion", 1)),
            )
            local_content = original.content if original is not None else None
            content = files[entry["payload"]]
            if action["action"] == "merge":
                base_payload = entry.get("basePayload")
                if not isinstance(base_payload, str) or local_content is None:
                    raise UpgradeError(f"Missing merge baseline for {relative}.")
                content = merge_text_payload(
                    local_content,
                    files[base_payload],
                    content,
                )
                if content is None:
                    raise UpgradeError(f"Merge became conflicted for {relative}.")
            elif entry["strategy"] == "starter-kit-state":
                content = updated_starter_manifest(
                    local_content,
                    manifest["base"]["provenance"],
                    content,
                )
            elif (
                entry["strategy"] == "agent-rules"
                and relative == PROVENANCE_PATH
            ):
                content = updated_agent_rules_provenance(local_content, content)
            write_payload(destination, content, entry["mode"])
            originals[relative] = original
            if journal is not None:
                written_kind, written_canonical_digest = content_metadata(content)
                journal.write(
                    "INFO",
                    "file",
                    (
                        f"path={relative} action={action['action'].upper()} "
                        f"result=WRITTEN mode={entry['mode']} "
                        f"contentKind={written_kind} size={len(content)} "
                        f"sha256={sha256_bytes(content)} "
                        f"canonicalSha256={written_canonical_digest}"
                    ),
                )

        head = run_git(root, "rev-parse", "HEAD")
        if head.returncode != 0:
            raise UpgradeError("Unable to resolve the target Git commit.")
        accepted_files: dict[str, str] = {}
        for entry in manifest["entries"]:
            if entry["strategy"] != "merge":
                continue
            destination = target_path(root, entry["path"])
            if not destination.is_file():
                continue
            current_digest = canonical_sha256(
                destination.read_bytes(), entry.get("contentKind", "binary")
            )
            if current_digest != entry.get("newCanonicalSha256"):
                accepted_files[entry["path"]] = current_digest
        next_adoption = {
            "schemaVersion": 2,
            "baseArchiveSha256": manifest["target"]["archiveSha256"],
            "starterKit": manifest["target"]["provenance"]["starterKit"],
            "repositoryCommit": head.stdout.strip(),
            "acceptedFiles": accepted_files,
        }
        starter_manifest_path = target_path(root, STARTER_MANIFEST_PATH)
        if starter_manifest_path.is_file():
            starter_manifest = parse_starter_manifest(
                starter_manifest_path.read_bytes(),
                str(starter_manifest_path),
            )
            next_adoption["starterKitSource"] = starter_manifest["source"]
        if snapshot_file(adoption_path) != adoption_snapshot:
            raise UpgradeError(f"Target changed after planning: {ADOPTION_PATH}")
        write_payload(adoption_path, write_json(next_adoption), "100644")
        originals[ADOPTION_PATH] = adoption_snapshot
        if journal is not None:
            adoption_content = adoption_path.read_bytes()
            journal.write(
                "INFO",
                "file",
                (
                    f"path={ADOPTION_PATH} action={adoption_action['action'].upper()} "
                    f"result=WRITTEN size={len(adoption_content)} "
                    f"sha256={sha256_bytes(adoption_content)}"
                ),
            )
            journal.phase("target-write", "END")
    except Exception:
        if journal is not None:
            journal.write(
                "ERROR",
                "rollback",
                "WRITE_FAILURE detected; restoring in-memory originals",
            )
        for relative, snapshot in reversed(list(originals.items())):
            destination = target_path(root, relative)
            if snapshot is None:
                if destination.exists():
                    destination.unlink()
                if journal is not None:
                    journal.write(
                        "WARNING",
                        "file",
                        f"path={relative} action=ROLLBACK_DELETE result=RESTORED",
                    )
            else:
                restore_snapshot(destination, snapshot)
                if journal is not None:
                    journal.write(
                        "WARNING",
                        "file",
                        (
                            f"path={relative} action=ROLLBACK_RESTORE "
                            f"result=RESTORED mode={snapshot.mode:04o} "
                            f"sha256={sha256_bytes(snapshot.content)}"
                        ),
                    )
        raise
    return backup_path


def plan_or_apply(
    args: argparse.Namespace, journal: RunJournal | None = None
) -> int:
    upgrade_path = args.upgrade_package.resolve()
    root = args.target.resolve()
    if journal is not None:
        journal.phase("preflight", "START")
        journal.write("INFO", "preflight", f"UPGRADE_PACKAGE={upgrade_path}")
        journal.write("INFO", "preflight", f"TARGET={root}")
        if args.command == "apply":
            journal.write(
                "INFO",
                "preflight",
                f"BACKUP_DIRECTORY={args.backup_directory.resolve()}",
            )
        journal.phase("archive-validation", "START")
    manifest, files = load_upgrade(upgrade_path)
    target_provenance = manifest["target"]["provenance"]
    base_provenance = manifest["base"]["provenance"]
    target_release = starter_release_tag(target_provenance, "Upgrade target")
    if journal is not None:
        journal.bind_target_release(target_release)
        log_archive_contents(journal, "upgrade-package", upgrade_path, files)
        journal.write(
            "INFO",
            "provenance",
            "BASE_RELEASE=" + starter_release_tag(
                base_provenance, "Upgrade base"
            ),
        )
        journal.write(
            "INFO",
            "provenance",
            f"BASE_STARTER_COMMIT={starter_commit(base_provenance)}",
        )
        journal.write(
            "INFO",
            "provenance",
            f"TARGET_STARTER_COMMIT={starter_commit(target_provenance)}",
        )
        journal.phase("archive-validation", "END")
        journal.phase("preflight", "END")
    plan = evaluate_target(manifest, files, root, journal)
    alignment = exact_release_alignment(plan)
    if args.command == "plan" or args.dry_run:
        if journal is not None:
            if plan["applicable"]:
                plan_status = "READY"
                compliance = "READY"
            elif plan["provenance"] == "target":
                compliance = operational_compliance(plan)
                plan_status = (
                    "ALREADY_CURRENT"
                    if compliance != "NON_COMPLIANT"
                    else "BLOCKED"
                )
            else:
                plan_status = "BLOCKED"
                compliance = "NON_COMPLIANT"
            journal.write(
                "INFO", "summary", f"PLAN_STATUS={plan_status}"
            )
            journal.set_outcome("NOT_APPLIED", compliance, alignment)
        print_plan(plan)
        return 0 if plan["applicable"] else 1

    if not plan["applicable"] and journal is not None:
        journal.set_outcome("BLOCKED", "NON_COMPLIANT", alignment)
    backup_path = apply_upgrade(
        manifest,
        files,
        root,
        plan,
        args.backup_directory,
        journal,
    )
    if journal is not None:
        journal.phase("post-verification", "START")
    result = evaluate_target(manifest, files, root, journal)
    result["backup"] = str(backup_path)
    adoption_is_current = target_adoption_is_current(manifest, root, journal)
    compliance = operational_compliance(result, adoption_is_current)
    alignment = exact_release_alignment(result)
    if journal is not None:
        journal.write(
            "INFO", "post-verification", f"BACKUP={backup_path}"
        )
        journal.phase("post-verification", "END")
        journal.set_outcome("SUCCEEDED", compliance, alignment)
    print_plan(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="help", help="show help and exit")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {VERSION}"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the execution plan without writing",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show additional diagnostics"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build a cumulative upgrade ZIP")
    build.add_argument("--base-package", type=Path, required=True)
    build.add_argument("--new-package", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)

    toolkit = subparsers.add_parser(
        "toolkit", help="bundle the updater and a new full package"
    )
    toolkit.add_argument("--new-package", type=Path, required=True)
    toolkit.add_argument("--output", type=Path, required=True)

    plan = subparsers.add_parser("plan", help="inspect a target without writing")
    plan.add_argument("--upgrade-package", type=Path, required=True)
    plan.add_argument("--target", type=Path, required=True)

    apply = subparsers.add_parser("apply", help="apply a conflict-free upgrade")
    apply.add_argument("--upgrade-package", type=Path, required=True)
    apply.add_argument("--target", type=Path, required=True)
    apply.add_argument("--backup-directory", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    journal = (
        None if args.dry_run else RunJournal(args.command, arguments)
    )
    exit_code = 1
    try:
        if args.command == "build":
            exit_code = build_upgrade(args, journal)
        elif args.command == "toolkit":
            exit_code = build_toolkit(args, journal)
        else:
            exit_code = plan_or_apply(args, journal)
    except (OSError, UpgradeError, subprocess.SubprocessError) as error:
        if journal is not None:
            journal.record_exception(error)
        if getattr(args, "verbose", False):
            raise
        print(f"Error: {error}", file=sys.stderr)
        exit_code = 1
    except BaseException as error:
        if journal is not None:
            journal.record_exception(error)
        raise
    finally:
        if journal is not None:
            journal.finalize(exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
