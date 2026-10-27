"""Inspect target repositories and construct upgrade plans."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
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
    content_metadata,
    load_json_bytes,
    parse_starter_manifest,
    reject_link_or_reparse_point,
    sha256_bytes,
    starter_commit,
    starter_release_from_provenance,
    validate_relative_path,
    write_json,
)


_PROCESS_SPEC = importlib.util.spec_from_file_location(
    "process_runner", Path(__file__).resolve().parents[1] / "process_runner.py"
)
assert _PROCESS_SPEC is not None and _PROCESS_SPEC.loader is not None
process_runner = importlib.util.module_from_spec(_PROCESS_SPEC)
_PROCESS_SPEC.loader.exec_module(process_runner)


def target_path(root: Path, relative: str) -> Path:
    relative = validate_relative_path(relative)
    current = root.absolute()
    for ancestor in reversed((current, *current.parents)):
        reject_link_or_reparse_point(ancestor)
    resolved_root = current.resolve()
    for part in PurePosixPath(relative).parts:
        current = current / part
        reject_link_or_reparse_point(current)
    if not current.resolve().is_relative_to(resolved_root):
        raise UpgradeError(f"Target path escapes its repository: {relative}")
    return current


def run_git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    timeout = 300 if arguments and arguments[0] == "status" else 30
    try:
        return process_runner.run(
            ["git", "-C", str(root), *arguments],
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        operation = arguments[0][:80] if arguments else "query"
        raise _git_timeout_error(error, operation, timeout) from error


def _git_timeout_error(
    error: subprocess.TimeoutExpired, operation: str, seconds: int
) -> UpgradeError:
    output = error.stderr or error.stdout or b""
    diagnostic = (
        output.decode("utf-8", errors="replace")
        if isinstance(output, bytes)
        else str(output)
    )
    return UpgradeError(
        f"Git {operation} timed out after {seconds} seconds: {diagnostic[:800]}"
    )


def validate_adoption(
    root: Path, manifest: dict[str, Any], adoption_path: Path
) -> dict[str, Any] | None:
    if not adoption_path.is_file():
        return None
    adoption = load_json_bytes(adoption_path.read_bytes(), str(adoption_path))
    schema_version = adoption.get("schemaVersion")
    if type(schema_version) is not int or schema_version not in {1, 2}:
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
        try:
            result = process_runner.run(
                [
                    "git",
                    "merge-file",
                    "-p",
                    str(paths["local"]),
                    str(paths["base"]),
                    str(paths["new"]),
                ],
                timeout=300,
            )
        except subprocess.TimeoutExpired as error:
            raise _git_timeout_error(error, "merge-file", 300) from error
    if result.returncode == 0:
        return result.stdout
    if 1 <= result.returncode <= 127:
        return None
    raise UpgradeError("Unable to perform the three-way file merge.")


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

    provenance_path = target_path(root, PROVENANCE_PATH)
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
    adoption = validate_adoption(root, manifest, target_path(root, ADOPTION_PATH))
    if provenance_status == "invalid" and adoption is not None:
        provenance_status = "adopted"
    if journal is not None:
        journal.write(
            "INFO",
            "target-analysis",
            f"PROVENANCE_STATUS={provenance_status}",
        )

    actions: list[dict[str, Any]] = []
    destinations: set[str] = set()
    for entry in manifest["entries"]:
        relative = entry["path"]
        local_path = target_path(root, relative)
        destination_key = str(local_path.resolve()).casefold()
        if destination_key in destinations:
            raise UpgradeError(f"Duplicate canonical destination: {relative}")
        destinations.add(destination_key)
        local_content = local_path.read_bytes() if local_path.is_file() else None
        local_mode = (
            stat.S_IMODE(local_path.stat().st_mode)
            if os.name != "nt" and local_content is not None
            else None
        )
        mode_aligned = os.name == "nt" or (
            local_mode is not None
            and bool(local_mode & stat.S_IXUSR) == (entry["mode"] == "100755")
        )
        content_kind = str(entry.get("contentKind", "binary"))
        schema_version = int(manifest.get("schemaVersion", 1))
        base_content_kind = (
            entry["baseContentKind"] if schema_version == 4 else content_kind
        )
        classification_changed = (
            base_content_kind is not None and base_content_kind != content_kind
        )
        local_content_kind = content_kind
        local_digest: str | None
        local_raw_digest = None
        try:
            if classification_changed and local_content is not None:
                local_content_kind, local_digest = content_metadata(local_content)
                local_raw_digest = sha256_bytes(local_content)
            else:
                local_digest = (
                    canonical_sha256(local_content, content_kind)
                    if local_content is not None and schema_version >= 2
                    else sha256_bytes(local_content)
                    if local_content is not None
                    else None
                )
        except UnicodeDecodeError:
            assert local_content is not None
            local_digest = None
            local_raw_digest = sha256_bytes(local_content)
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
        elif local_content is not None and local_digest is None:
            action = "conflict-modified"
        elif local_content_kind == content_kind and local_digest == new_digest:
            action = "aligned"
        elif local_content is None and base_digest is None:
            action = "add"
        elif local_content is None:
            action = "conflict-missing"
        elif local_content_kind == base_content_kind and local_digest == base_digest:
            action = "update"
        elif (
            strategy == "merge"
            and content_kind == "text"
            and base_content_kind == content_kind
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
        mode_only = False
        if action == "aligned" and not mode_aligned:
            if strategy == "initialize-only":
                action = "review-initialize-only"
            else:
                action = "update"
                mode_only = True
        actions.append(
            {
                "path": relative,
                "strategy": strategy,
                "action": action,
                "localCanonicalSha256": local_digest,
                "baseCanonicalSha256": base_digest,
                "newCanonicalSha256": new_digest,
                "localMode": local_mode,
                "modeAligned": mode_aligned,
                "modeOnly": mode_only,
            }
        )
        if local_raw_digest is not None:
            actions[-1]["localRawSha256"] = local_raw_digest
        if journal is not None:
            journal.write(
                "INFO",
                "file",
                (
                    f"path={relative} action={action} strategy={strategy} "
                    f"localCanonicalSha256={local_digest} "
                    f"baseCanonicalSha256={base_digest} "
                    f"targetCanonicalSha256={new_digest} "
                    f"localMode={local_mode} targetMode={entry['mode']} "
                    f"modeAligned={mode_aligned} modeOnly={mode_only}"
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
            and action.get("modeAligned", True)
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
            try:
                current_digest = canonical_sha256(
                    destination.read_bytes(), entry.get("contentKind", "binary")
                )
            except UnicodeDecodeError:
                current = False
                break
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
