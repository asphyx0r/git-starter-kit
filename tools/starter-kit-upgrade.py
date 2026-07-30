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

VERSION = "0.1.0"
MAX_ARCHIVE_SIZE = 256 * 1024 * 1024
PROVENANCE_PATH = "_agent-rules-source.json"
FILES_MANIFEST_PATH = "_starter-kit-files.json"
ADOPTION_PATH = ".starter-kit-adoption.json"
UPGRADE_MANIFEST_PATH = "upgrade-manifest.json"
PAYLOAD_PREFIX = "payload/"


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
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    provenance = require_package_provenance(files, "new package")
    if FILES_MANIFEST_PATH not in files:
        raise UpgradeError(f"New package is missing {FILES_MANIFEST_PATH}.")
    manifest = load_json_bytes(
        files[FILES_MANIFEST_PATH], f"new package/{FILES_MANIFEST_PATH}"
    )
    if manifest.get("schemaVersion") != 1 or not isinstance(manifest.get("files"), list):
        raise UpgradeError("Unsupported managed-file manifest schema.")

    managed: list[dict[str, str]] = []
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
        if strategy not in {"initialize-only", "merge", "replace"}:
            raise UpgradeError(f"Invalid upgrade strategy for {path}: {strategy}")
        mode = str(raw_entry.get("mode", "100644"))
        if mode not in {"100644", "100755"}:
            raise UpgradeError(f"Unsupported Git mode for {path}: {mode}")
        managed.append(
            {"path": path, "sha256": digest, "strategy": strategy, "mode": mode}
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
            "strategy": "replace",
            "mode": "100644",
        }
    )
    for entry in sorted(managed, key=lambda item: item["path"]):
        path = entry["path"]
        payload_path = PAYLOAD_PREFIX + path
        payload[payload_path] = new_files[path]
        entries.append(
            {
                "path": path,
                "strategy": entry["strategy"],
                "mode": entry["mode"],
                "baseSha256": (
                    sha256_bytes(base_files[path]) if path in base_files else None
                ),
                "newSha256": entry["sha256"],
                "payload": payload_path,
            }
        )

    obsolete = sorted(
        path
        for path in base_files
        if path not in managed_paths and path != FILES_MANIFEST_PATH
    )
    manifest = {
        "schemaVersion": 1,
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
    if manifest.get("schemaVersion") != 1 or not isinstance(
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
) -> bool:
    if not adoption_path.is_file():
        return False
    adoption = load_json_bytes(adoption_path.read_bytes(), str(adoption_path))
    if adoption.get("schemaVersion") != 1:
        return False
    if adoption.get("baseArchiveSha256") != manifest["base"]["archiveSha256"]:
        return False
    starter = adoption.get("starterKit")
    base_starter = manifest["base"]["provenance"].get("starterKit")
    if not isinstance(starter, dict) or not isinstance(base_starter, dict):
        return False
    if starter.get("commit") != base_starter.get("commit"):
        return False
    evidence_commit = adoption.get("repositoryCommit")
    if not isinstance(evidence_commit, str) or not evidence_commit:
        return False
    result = run_git(root, "merge-base", "--is-ancestor", evidence_commit, "HEAD")
    return result.returncode == 0


def evaluate_target(
    manifest: dict[str, Any], files: dict[str, bytes], root: Path
) -> dict[str, Any]:
    if not root.is_dir():
        raise UpgradeError(f"Target directory does not exist: {root}")
    if run_git(root, "rev-parse", "--show-toplevel").returncode != 0:
        raise UpgradeError(f"Target is not a Git repository: {root}")

    provenance_path = root / PROVENANCE_PATH
    provenance_digest = (
        sha256_file(provenance_path) if provenance_path.is_file() else None
    )
    expected_base = manifest["base"]["provenanceSha256"]
    expected_target = manifest["target"]["provenanceSha256"]
    provenance_status = "invalid"
    if provenance_digest == expected_base:
        provenance_status = "base"
    elif provenance_digest == expected_target:
        provenance_status = "target"
    elif validate_adoption(root, manifest, root / ADOPTION_PATH):
        provenance_status = "adopted"

    actions: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        relative = entry["path"]
        local_path = target_path(root, relative)
        local_digest = sha256_file(local_path) if local_path.is_file() else None
        base_digest = entry.get("baseSha256")
        new_digest = entry["newSha256"]
        strategy = entry["strategy"]
        if strategy == "initialize-only":
            action = "preserve"
        elif local_digest == new_digest:
            action = "aligned"
        elif local_digest is None and base_digest is None:
            action = "add"
        elif local_digest is None:
            action = "conflict-missing"
        elif local_digest == base_digest:
            action = "update"
        else:
            action = "conflict-modified"
        actions.append(
            {
                "path": relative,
                "strategy": strategy,
                "action": action,
                "localSha256": local_digest,
                "baseSha256": base_digest,
                "newSha256": new_digest,
            }
        )

    conflicts = [
        action for action in actions if action["action"].startswith("conflict-")
    ]
    status = run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        raise UpgradeError("Unable to inspect target Git status.")
    return {
        "schemaVersion": 1,
        "target": str(root),
        "provenance": provenance_status,
        "clean": not bool(status.stdout),
        "actions": actions,
        "obsoletePaths": manifest.get("obsoletePaths", []),
        "summary": {
            name: sum(1 for action in actions if action["action"] == name)
            for name in (
                "add",
                "aligned",
                "conflict-missing",
                "conflict-modified",
                "preserve",
                "update",
            )
        },
        "applicable": provenance_status in {"base", "adopted"}
        and not conflicts
        and not bool(status.stdout),
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
        for action in actions:
            if action["action"] != "update":
                continue
            relative = action["path"]
            archive.write(target_path(root, relative), "files/" + relative)
            saved.append(relative)
        archive.writestr(
            "rollback-manifest.json",
            write_json({"schemaVersion": 1, "savedPaths": saved}),
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
        action for action in plan["actions"] if action["action"] in {"add", "update"}
    ]
    backup_path = create_rollback_archive(root, backup_directory, changes)
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
            write_payload(destination, files[entry["payload"]], entry["mode"])
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
