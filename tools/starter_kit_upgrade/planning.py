"""Inspect target repositories and construct upgrade plans."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from typing import Any

from .archive import updated_agent_rules_provenance
from .common import (
    ADOPTION_PATH,
    PROVENANCE_PATH,
    STARTER_MANIFEST_PATH,
    RunJournal,
    UpgradeError,
    canonical_sha256,
    canonicalize_text,
    load_json_bytes,
    sha256_bytes,
    starter_commit,
    write_json,
)


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
                raise UpgradeError(f"Invalid {release_name}.{field} in {label}.")
        expected_url = (
            release["repository"].rstrip("/") + "/releases/tag/" + release["ref"]
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


def normalized_starter_manifest(value: dict[str, Any], source: dict[str, Any]) -> bytes:
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
        if local_starter_commit == starter_commit(manifest["base"]["provenance"]):
            provenance_status = "base"
        elif local_starter_commit == starter_commit(manifest["target"]["provenance"]):
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
        schema_version = int(manifest.get("schemaVersion", 1))
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
            and local_content is not None
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
    status = run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
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
        journal.write("INFO", "target-analysis", f"TARGET_CLEAN={plan['clean']}")
        journal.phase("target-analysis", "END")
    return plan


def exact_release_alignment(plan: dict[str, Any]) -> str:
    return (
        "ALIGNED"
        if all(
            action["localCanonicalSha256"] == action["newCanonicalSha256"]
            for action in plan["actions"]
        )
        else "NOT_ALIGNED"
    )


def operational_compliance(
    plan: dict[str, Any], target_state_current: bool = False
) -> str:
    actions = {action["action"] for action in plan["actions"]}
    if (not target_state_current and plan["provenance"] != "target") or any(
        action.startswith("conflict-") for action in actions
    ):
        return "NON_COMPLIANT"
    if actions.intersection({"add", "merge", "update"}):
        return "NON_COMPLIANT"
    if actions.intersection({"delegate-agent-rules", "review-initialize-only"}):
        return "COMPLIANT_WITH_FOLLOW_UP"
    return "COMPLIANT"


def target_adoption_is_current(
    manifest: dict[str, Any], root: Path, journal: RunJournal | None = None
) -> bool:
    adoption_path = target_path(root, ADOPTION_PATH)
    if not adoption_path.is_file():
        if journal is not None:
            journal.write("ERROR", "post-verification", "ADOPTION_STATUS=MISSING")
        return False
    try:
        adoption = load_json_bytes(adoption_path.read_bytes(), str(adoption_path))
    except UpgradeError:
        if journal is not None:
            journal.write("ERROR", "post-verification", "ADOPTION_STATUS=INVALID")
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
        and adoption.get("baseArchiveSha256") == manifest["target"]["archiveSha256"]
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
            current = adoption.get("starterKitSource") == starter_manifest.get("source")
    if journal is not None:
        journal.write(
            "INFO" if current else "ERROR",
            "post-verification",
            f"ADOPTION_STATUS={'CURRENT' if current else 'INVALID'}",
        )
    return current


def print_plan(plan: dict[str, Any]) -> None:
    print(json.dumps(plan, indent=2, sort_keys=False))


__all__ = [
    "evaluate_target",
    "exact_release_alignment",
    "merge_text_payload",
    "normalized_starter_manifest",
    "operational_compliance",
    "parse_starter_manifest",
    "print_plan",
    "run_git",
    "starter_manifest_action",
    "starter_release_from_provenance",
    "target_adoption_is_current",
    "target_path",
    "updated_starter_manifest",
    "validate_adoption",
]
