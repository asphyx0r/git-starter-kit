"""Apply verified upgrade plans with rollback protection."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Callable
import zipfile

from .archive import updated_agent_rules_provenance
from .common import (
    ADOPTION_PATH,
    PROVENANCE_PATH,
    STARTER_MANIFEST_PATH,
    FileSnapshot,
    RunJournal,
    UpgradeError,
    canonical_sha256,
    content_metadata,
    sha256_bytes,
    sha256_file,
    write_json,
)
from .planning import (
    merge_text_payload,
    parse_starter_manifest,
    run_git,
    target_path,
    updated_starter_manifest,
)


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
                | (
                    stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    if mode == "100755"
                    else 0
                )
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


def restore_snapshot(
    path: Path,
    snapshot: FileSnapshot,
    *,
    payload_writer: Callable[[Path, bytes, str], None] | None = None,
) -> None:
    git_mode = "100755" if snapshot.mode & 0o111 else "100644"
    writer = write_payload if payload_writer is None else payload_writer
    writer(path, snapshot.content, git_mode)
    if os.name != "nt":
        path.chmod(snapshot.mode)


def apply_upgrade(
    manifest: dict[str, Any],
    files: dict[str, bytes],
    root: Path,
    plan: dict[str, Any],
    backup_directory: Path,
    journal: RunJournal | None = None,
    *,
    payload_writer: Callable[[Path, bytes, str], None] | None = None,
) -> Path:
    writer = write_payload if payload_writer is None else payload_writer
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
                merged_content = merge_text_payload(
                    local_content,
                    files[base_payload],
                    content,
                )
                if merged_content is None:
                    raise UpgradeError(f"Merge became conflicted for {relative}.")
                content = merged_content
            elif entry["strategy"] == "starter-kit-state":
                content = updated_starter_manifest(
                    local_content,
                    manifest["base"]["provenance"],
                    content,
                )
            elif entry["strategy"] == "agent-rules" and relative == PROVENANCE_PATH:
                content = updated_agent_rules_provenance(local_content, content)
            writer(destination, content, entry["mode"])
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
        writer(adoption_path, write_json(next_adoption), "100644")
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
                restore_snapshot(
                    destination,
                    snapshot,
                    payload_writer=writer,
                )
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


__all__ = [
    "apply_upgrade",
    "create_rollback_archive",
    "require_planned_file_state",
    "restore_snapshot",
    "snapshot_file",
    "write_payload",
]
