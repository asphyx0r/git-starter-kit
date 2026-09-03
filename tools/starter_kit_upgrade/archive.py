"""Build and validate cumulative upgrade archives and toolkits."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any
import zipfile

from .common import (
    BASE_PAYLOAD_PREFIX,
    FILES_MANIFEST_PATH,
    MAX_ARCHIVE_SIZE,
    PAYLOAD_PREFIX,
    PROVENANCE_PATH,
    STARTER_MANIFEST_PATH,
    UPGRADE_MANIFEST_PATH,
    RunJournal,
    UpgradeError,
    canonical_sha256,
    content_metadata,
    load_json_bytes,
    log_archive_contents,
    log_managed_entries,
    sha256_bytes,
    sha256_file,
    starter_commit,
    starter_release_tag,
    validate_relative_path,
    write_json,
)

TOOLKIT_MODULE_NAMES = (
    "__init__.py",
    "application.py",
    "archive.py",
    "cli.py",
    "common.py",
    "planning.py",
)


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


def require_package_provenance(files: dict[str, bytes], label: str) -> dict[str, Any]:
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
    if schema_version not in {1, 2, 3} or not isinstance(manifest.get("files"), list):
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


def updated_agent_rules_provenance(
    local_content: bytes | None, new_content: bytes
) -> bytes:
    if local_content is None:
        raise UpgradeError(f"Target is missing {PROVENANCE_PATH}.")
    local_value = load_json_bytes(local_content, f"target {PROVENANCE_PATH}")
    if not isinstance(local_value.get("agentRules"), dict):
        raise UpgradeError(f"Target {PROVENANCE_PATH} has no agentRules object.")
    new_value = load_json_bytes(new_content, f"new {PROVENANCE_PATH}")
    for field in ("repository", "starterKit"):
        value = new_value.get(field)
        if not isinstance(value, dict):
            raise UpgradeError(f"New {PROVENANCE_PATH} has no {field} object.")
        local_value[field] = value
    return write_json(local_value)


def build_upgrade(args: argparse.Namespace, journal: RunJournal | None = None) -> int:
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
            ("BASE_RELEASE=" + starter_release_tag(base_provenance, "Base package")),
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
            "canonicalSha256": content_metadata(new_files[FILES_MANIFEST_PATH])[1],
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
        journal.set_outcome("ARTIFACT_CREATED", "ARTIFACT_COMPLIANT", "NOT_APPLICABLE")
    print(f"Created cumulative upgrade package: {output_path}")
    return 0


def build_toolkit(args: argparse.Namespace, journal: RunJournal | None = None) -> int:
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
    script_path = Path(__file__).resolve().parents[1] / "starter-kit-upgrade.py"
    package_root = Path(__file__).resolve().parent
    package_members = {
        f"starter_kit_upgrade/{name}": package_root / name
        for name in TOOLKIT_MODULE_NAMES
    }
    readme = f"""# Starter Kit Upgrade Toolkit

This toolkit contains:

- `starter-kit-upgrade.py`, the executable compatibility facade;
- `starter_kit_upgrade/`, the updater implementation package;
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
        for member, source in package_members.items():
            journal.write(
                "INFO",
                "file",
                f"path={member} action=ADD_TOOLKIT_MEMBER source={source}",
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
            for member, source in package_members.items():
                archive.write(source, member)
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
        *package_members,
        f"packages/{package_path.name}",
        "README.md",
    }
    if set(verified_files) != expected_members:
        raise UpgradeError("Created toolkit contains unexpected members.")
    if verified_files[script_path.name] != script_path.read_bytes():
        raise UpgradeError("Created toolkit contains an invalid updater.")
    for member, source in package_members.items():
        if verified_files[member] != source.read_bytes():
            raise UpgradeError(f"Created toolkit contains an invalid module: {member}")
    if verified_files[f"packages/{package_path.name}"] != package_path.read_bytes():
        raise UpgradeError("Created toolkit contains an invalid full package.")
    log_archive_contents(journal, "created-toolkit", output_path, verified_files)
    if journal is not None:
        journal.phase("post-verification", "END")
        journal.set_outcome("ARTIFACT_CREATED", "ARTIFACT_COMPLIANT", "NOT_APPLICABLE")
    print(f"Created upgrade toolkit: {output_path}")
    return 0


def load_upgrade(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    files = read_archive(path)
    if UPGRADE_MANIFEST_PATH not in files:
        raise UpgradeError(f"Upgrade package is missing {UPGRADE_MANIFEST_PATH}.")
    manifest = load_json_bytes(files[UPGRADE_MANIFEST_PATH], UPGRADE_MANIFEST_PATH)
    schema_version = manifest.get("schemaVersion")
    if schema_version not in {1, 2, 3} or not isinstance(manifest.get("entries"), list):
        raise UpgradeError("Unsupported upgrade package schema.")

    for entry in manifest["entries"]:
        if not isinstance(entry, dict):
            raise UpgradeError("Upgrade entries must be JSON objects.")
        entry_path = validate_relative_path(str(entry.get("path", "")))
        payload_path = validate_relative_path(str(entry.get("payload", "")))
        if not payload_path.startswith(PAYLOAD_PREFIX) or payload_path not in files:
            raise UpgradeError(f"Missing upgrade payload for {entry_path}.")
        if sha256_bytes(files[payload_path]) != entry.get("newSha256"):
            raise UpgradeError(f"Upgrade payload digest mismatch: {entry_path}")
        if schema_version >= 2:
            content_kind = str(entry.get("contentKind", ""))
            if canonical_sha256(files[payload_path], content_kind) != entry.get(
                "newCanonicalSha256"
            ):
                raise UpgradeError(f"Upgrade canonical digest mismatch: {entry_path}")
            base_payload = entry.get("basePayload")
            if base_payload is not None:
                base_payload = validate_relative_path(str(base_payload))
                if (
                    not base_payload.startswith(BASE_PAYLOAD_PREFIX)
                    or base_payload not in files
                ):
                    raise UpgradeError(f"Missing base payload for {entry_path}.")
                if sha256_bytes(files[base_payload]) != entry.get("baseSha256"):
                    raise UpgradeError(f"Base payload digest mismatch: {entry_path}")
    return manifest, files


__all__ = [
    "TOOLKIT_MODULE_NAMES",
    "build_toolkit",
    "build_upgrade",
    "load_upgrade",
    "read_archive",
    "require_package_provenance",
    "updated_agent_rules_provenance",
    "validate_new_package",
]
