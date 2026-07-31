#!/usr/bin/env python3
"""Build, inspect, and safely apply cumulative starter-kit upgrades."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
from typing import Any
import zipfile

VERSION = "0.2.0"
MAX_ARCHIVE_SIZE = 256 * 1024 * 1024
PROVENANCE_PATH = "_agent-rules-source.json"
FILES_MANIFEST_PATH = "_starter-kit-files.json"
ADOPTION_PATH = ".starter-kit-adoption.json"
UPGRADE_MANIFEST_PATH = "upgrade-manifest.json"
PAYLOAD_PREFIX = "payload/"
BASE_PAYLOAD_PREFIX = "base/"


class UpgradeError(RuntimeError):
    """Raised when an upgrade cannot be built, planned, or applied safely."""


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
    if schema_version not in {1, 2} or not isinstance(manifest.get("files"), list):
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
        if strategy not in {"agent-rules", "initialize-only", "merge", "replace"}:
            raise UpgradeError(f"Invalid upgrade strategy for {path}: {strategy}")
        mode = str(raw_entry.get("mode", "100644"))
        if mode not in {"100644", "100755"}:
            raise UpgradeError(f"Unsupported Git mode for {path}: {mode}")
        content_kind, canonical_digest = content_metadata(files[path])
        if schema_version == 2:
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


def build_upgrade(args: argparse.Namespace) -> int:
    base_path = args.base_package.resolve()
    new_path = args.new_package.resolve()
    output_path = args.output.resolve()
    if output_path.exists():
        raise UpgradeError(f"Output already exists: {output_path}")
    if output_path.parent == output_path or not output_path.parent.is_dir():
        raise UpgradeError("Upgrade output directory must already exist.")

    base_files = read_archive(base_path)
    new_files = read_archive(new_path)
    base_provenance = require_package_provenance(base_files, "base package")
    new_provenance, managed = validate_new_package(new_files)

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
        if entry["strategy"] == "merge" and base_content is not None:
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

    obsolete = sorted(
        path
        for path in base_files
        if path not in managed_paths and path != FILES_MANIFEST_PATH
    )
    manifest = {
        "schemaVersion": 2,
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

    print(f"Created cumulative upgrade package: {output_path}")
    return 0


def build_toolkit(args: argparse.Namespace) -> int:
    package_path = args.new_package.resolve()
    output_path = args.output.resolve()
    if output_path.exists():
        raise UpgradeError(f"Output already exists: {output_path}")
    if not output_path.parent.is_dir():
        raise UpgradeError("Toolkit output directory must already exist.")
    package_files = read_archive(package_path)
    validate_new_package(package_files)
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
    print(f"Created upgrade toolkit: {output_path}")
    return 0


def load_upgrade(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    files = read_archive(path)
    if UPGRADE_MANIFEST_PATH not in files:
        raise UpgradeError(f"Upgrade package is missing {UPGRADE_MANIFEST_PATH}.")
    manifest = load_json_bytes(files[UPGRADE_MANIFEST_PATH], UPGRADE_MANIFEST_PATH)
    schema_version = manifest.get("schemaVersion")
    if schema_version not in {1, 2} or not isinstance(
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
        if schema_version == 2:
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
    if adoption.get("baseArchiveSha256") != manifest["base"]["archiveSha256"]:
        return None
    starter = adoption.get("starterKit")
    base_starter = manifest["base"]["provenance"].get("starterKit")
    if not isinstance(starter, dict) or not isinstance(base_starter, dict):
        return None
    if starter.get("commit") != base_starter.get("commit"):
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


def evaluate_target(
    manifest: dict[str, Any], files: dict[str, bytes], root: Path
) -> dict[str, Any]:
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

    actions: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        relative = entry["path"]
        local_path = target_path(root, relative)
        local_content = local_path.read_bytes() if local_path.is_file() else None
        content_kind = str(entry.get("contentKind", "binary"))
        schema_version = manifest.get("schemaVersion")
        local_digest = (
            canonical_sha256(local_content, content_kind)
            if local_content is not None and schema_version == 2
            else sha256_bytes(local_content)
            if local_content is not None
            else None
        )
        base_digest = (
            entry.get("baseCanonicalSha256")
            if schema_version == 2
            else entry.get("baseSha256")
        )
        new_digest = (
            entry.get("newCanonicalSha256")
            if schema_version == 2
            else entry["newSha256"]
        )
        strategy = entry["strategy"]
        if strategy == "agent-rules":
            action = "delegate-agent-rules"
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
    return {
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


def print_plan(plan: dict[str, Any]) -> None:
    print(json.dumps(plan, indent=2, sort_keys=False))


def create_rollback_archive(
    root: Path,
    backup_directory: Path,
    actions: list[dict[str, Any]],
) -> Path:
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
            elif action["action"] == "add":
                created.append(relative)
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


def apply_upgrade(
    manifest: dict[str, Any],
    files: dict[str, bytes],
    root: Path,
    plan: dict[str, Any],
    backup_directory: Path,
) -> Path:
    if not plan["applicable"]:
        raise UpgradeError("Upgrade is not applicable; inspect the plan.")
    changes = [
        action
        for action in plan["actions"]
        if action["action"] in {"add", "merge", "update"}
    ]
    adoption_path = target_path(root, ADOPTION_PATH)
    adoption_action = {
        "path": ADOPTION_PATH,
        "action": "update" if adoption_path.is_file() else "add",
    }
    backup_path = create_rollback_archive(
        root, backup_directory, changes + [adoption_action]
    )
    originals: dict[str, bytes | None] = {}
    try:
        entries = {entry["path"]: entry for entry in manifest["entries"]}
        for action in changes:
            relative = action["path"]
            destination = target_path(root, relative)
            originals[relative] = (
                destination.read_bytes() if destination.is_file() else None
            )
            entry = entries[relative]
            content = files[entry["payload"]]
            if action["action"] == "merge":
                base_payload = entry.get("basePayload")
                if not isinstance(base_payload, str):
                    raise UpgradeError(f"Missing merge baseline for {relative}.")
                content = merge_text_payload(
                    originals[relative],
                    files[base_payload],
                    content,
                )
                if content is None:
                    raise UpgradeError(f"Merge became conflicted for {relative}.")
            write_payload(destination, content, entry["mode"])

        originals[ADOPTION_PATH] = (
            adoption_path.read_bytes() if adoption_path.is_file() else None
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
        adoption = {
            "schemaVersion": 2,
            "baseArchiveSha256": manifest["target"]["archiveSha256"],
            "starterKit": manifest["target"]["provenance"]["starterKit"],
            "repositoryCommit": head.stdout.strip(),
            "acceptedFiles": accepted_files,
        }
        write_payload(adoption_path, write_json(adoption), "100644")
    except Exception:
        for relative, content in reversed(list(originals.items())):
            destination = target_path(root, relative)
            if content is None:
                if destination.exists():
                    destination.unlink()
            else:
                write_payload(destination, content, "100644")
        raise
    return backup_path


def plan_or_apply(args: argparse.Namespace) -> int:
    manifest, files = load_upgrade(args.upgrade_package.resolve())
    root = args.target.resolve()
    plan = evaluate_target(manifest, files, root)
    if args.command == "plan" or args.dry_run:
        print_plan(plan)
        return 0 if plan["applicable"] else 1

    backup_path = apply_upgrade(
        manifest,
        files,
        root,
        plan,
        args.backup_directory,
    )
    result = evaluate_target(manifest, files, root)
    result["backup"] = str(backup_path)
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
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            return build_upgrade(args)
        if args.command == "toolkit":
            return build_toolkit(args)
        return plan_or_apply(args)
    except (OSError, UpgradeError, subprocess.SubprocessError) as error:
        if getattr(args, "verbose", False):
            raise
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
