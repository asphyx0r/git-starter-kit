#!/usr/bin/env python3
"""Prepare and validate the tracked starter-kit release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, overload

VERSION = "1.1.0"
MANIFEST_PATH = "starter-kit-manifest.json"
CANONICAL_REPOSITORY = "https://github.com/asphyx0r/git-starter-kit"
CANONICAL_ORIGINS = frozenset({CANONICAL_REPOSITORY, f"{CANONICAL_REPOSITORY}.git"})
SEMVER_TAG_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(-((0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"
)

AGENT_RULE_PATHS = frozenset(
    {
        "AGENTS.md",
        "BRANCH_RULES.md",
        "CODING_RULES.md",
        "COMMIT_RULES.md",
        "DOCUMENTATION_RULES.md",
        "LANGUAGE_RULES.md",
        "RELEASE_RULES.md",
        "_agent-rules-source.json",
    }
)
SOURCE_ONLY_PATHS = frozenset(
    {
        (
            ".agents/skills/git-commit-push-tag/references/"
            "git-starter-kit-release-package.txt"
        ),
        ".github/CODEOWNERS",
        ".github/workflows/release-package.yml",
        "SHA256SUMS",
        "VERSION",
        "docs/release-package.md",
        "docs/upgrade-toolkit.md",
        "manifest.json",
        "tests/test_build_release_package.py",
        "tests/test_starter_kit_manifest.py",
        "tests/test_starter_kit_upgrade.py",
        "tools/build-release-package.ps1",
        "tools/starter-kit-manifest.py",
        "tools/starter-kit-upgrade.py",
        "tools/starter_kit_upgrade/__init__.py",
        "tools/starter_kit_upgrade/application.py",
        "tools/starter_kit_upgrade/archive.py",
        "tools/starter_kit_upgrade/cli.py",
        "tools/starter_kit_upgrade/common.py",
        "tools/starter_kit_upgrade/planning.py",
    }
)
SOURCE_ONLY_PREFIXES = ("tools/starter_kit_upgrade/",)
RESERVED_STATE_PATHS = frozenset(
    {".starter-kit-adoption.json", "_starter-kit-files.json", MANIFEST_PATH}
)
INITIALIZE_ONLY_PATHS = frozenset(
    {
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "SUPPORT.md",
        "docs/SKILLS.md",
        "docs/repository-files.md",
        "docs/repository-migration.md",
        "tools/README.md",
        "tools/repository-audit.sh",
    }
)
INITIALIZE_ONLY_PREFIXES = ("tools/repository-audit/",)
REPLACE_PREFIXES = ("tools/quality/",)
MERGE_PATHS = frozenset(
    {
        ".betterleaks.toml",
        ".codespellrc",
        ".editorconfig",
        ".gitattributes",
        ".gitleaks.toml",
        ".gitignore",
        ".github/dependabot.yml",
        ".github/workflows/repository-audit.yml",
    }
)
ENTRY_KEYS = {
    "path",
    "sha256",
    "canonicalSha256",
    "contentKind",
    "mode",
    "strategy",
}
RELEASE_KEYS = {"repository", "ref", "releaseUrl", "generatedAt"}


class ManifestError(RuntimeError):
    """Raised when the starter-kit manifest cannot be prepared or checked."""


@overload
def run_git(root: Path, *arguments: str, binary: Literal[False] = False) -> str: ...


@overload
def run_git(root: Path, *arguments: str, binary: Literal[True]) -> bytes: ...


def run_git(root: Path, *arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=not binary,
    )
    if result.returncode != 0:
        stderr = (
            result.stderr.decode("utf-8", errors="replace") if binary else result.stderr
        )
        raise ManifestError(f"git {' '.join(arguments)} failed: {stderr.strip()}")
    return result.stdout


def require_repository_root(value: Path) -> Path:
    root = value.resolve()
    if not root.is_dir():
        raise ManifestError(f"Repository root does not exist: {root}")
    actual = Path(str(run_git(root, "rev-parse", "--show-toplevel")).strip()).resolve()
    if actual != root:
        raise ManifestError(f"Repository root must be the Git root: {root}")
    return root


def require_canonical_origin(root: Path) -> None:
    origin = str(run_git(root, "remote", "get-url", "origin")).strip()
    if origin not in CANONICAL_ORIGINS:
        raise ManifestError(
            "prepare requires the canonical asphyx0r/git-starter-kit origin"
        )


def validate_relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise ManifestError(f"Unsafe repository path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError(f"Unsafe repository path: {value!r}")
    return path.as_posix()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonicalize_text(content: bytes) -> bytes:
    text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return (text.rstrip("\n") + "\n").encode("utf-8") if text else b""


def content_metadata(content: bytes) -> tuple[str, str]:
    try:
        canonical = canonicalize_text(content)
    except UnicodeDecodeError:
        return "binary", sha256_bytes(content)
    return "text", sha256_bytes(canonical)


def read_blobs(root: Path, object_ids: list[str]) -> list[bytes]:
    if not object_ids:
        return []
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=("\n".join(object_ids) + "\n").encode("ascii"),
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ManifestError(
            "git cat-file --batch failed: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    contents: list[bytes] = []
    offset = 0
    for expected_id in object_ids:
        header_end = result.stdout.find(b"\n", offset)
        if header_end < 0:
            raise ManifestError("git cat-file returned an incomplete header.")
        header = result.stdout[offset:header_end].decode("ascii").split(" ")
        if len(header) != 3 or header[0] != expected_id or header[1] != "blob":
            raise ManifestError(f"Unexpected Git object for {expected_id}.")
        size = int(header[2])
        content_start = header_end + 1
        content_end = content_start + size
        if result.stdout[content_end : content_end + 1] != b"\n":
            raise ManifestError("git cat-file returned incomplete blob content.")
        contents.append(result.stdout[content_start:content_end])
        offset = content_end + 1
    if offset != len(result.stdout):
        raise ManifestError("git cat-file returned unexpected trailing output.")
    return contents


def strategy_for(path: str, *, audit_runtime_managed: bool = False) -> str:
    if audit_runtime_managed and (
        path == "tools/repository-audit.sh"
        or path.startswith("tools/repository-audit/")
    ):
        return "replace"
    if path in INITIALIZE_ONLY_PATHS or path.startswith(INITIALIZE_ONLY_PREFIXES):
        return "initialize-only"
    if path in MERGE_PATHS:
        return "merge"
    if path.startswith(REPLACE_PREFIXES):
        return "replace"
    return "replace"


def is_core_path(path: str) -> bool:
    return (
        path not in AGENT_RULE_PATHS
        and path not in SOURCE_ONLY_PATHS
        and not path.startswith(SOURCE_ONLY_PREFIXES)
        and path not in RESERVED_STATE_PATHS
    )


def index_entries(root: Path) -> list[tuple[str, str, bytes]]:
    output = bytes(run_git(root, "ls-files", "--stage", "-z", binary=True))
    records: list[tuple[str, str, str]] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, object_id, stage = metadata.decode("ascii").split(" ")
        if stage != "0":
            raise ManifestError("The Git index contains unmerged entries.")
        path = validate_relative_path(raw_path.decode("utf-8"))
        if mode not in {"100644", "100755"}:
            raise ManifestError(f"Unsupported Git mode for {path}: {mode}")
        if not is_core_path(path):
            continue
        records.append((path, mode, object_id))
    contents = read_blobs(root, [record[2] for record in records])
    return [
        (path, mode, content)
        for (path, mode, _object_id), content in zip(records, contents, strict=True)
    ]


def tree_entries(root: Path, treeish: str) -> list[tuple[str, str, bytes]]:
    output = bytes(run_git(root, "ls-tree", "-r", "-z", treeish, binary=True))
    records: list[tuple[str, str, str]] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        path = validate_relative_path(raw_path.decode("utf-8"))
        if object_type != "blob" or not is_core_path(path):
            continue
        if mode not in {"100644", "100755"}:
            raise ManifestError(f"Unsupported Git mode for {path}: {mode}")
        records.append((path, mode, object_id))
    contents = read_blobs(root, [record[2] for record in records])
    return [
        (path, mode, content)
        for (path, mode, _object_id), content in zip(records, contents, strict=True)
    ]


def core_entries(root: Path, treeish: str | None) -> list[dict[str, str]]:
    raw_entries = tree_entries(root, treeish) if treeish else index_entries(root)
    audit_runtime_managed = any(
        path.startswith("tools/repository-audit/")
        for path, _mode, _content in raw_entries
    )
    entries: list[dict[str, str]] = []
    for path, mode, content in raw_entries:
        content_kind, canonical_digest = content_metadata(content)
        entries.append(
            {
                "path": path,
                "sha256": sha256_bytes(content),
                "canonicalSha256": canonical_digest,
                "contentKind": content_kind,
                "mode": mode,
                "strategy": strategy_for(
                    path,
                    audit_runtime_managed=audit_runtime_managed,
                ),
            }
        )
    return sorted(entries, key=lambda entry: entry["path"])


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def release_descriptor(ref: str, generated_at: str) -> dict[str, str]:
    if not SEMVER_TAG_PATTERN.fullmatch(ref):
        raise ManifestError("release ref must be a SemVer tag prefixed with v")
    return {
        "repository": CANONICAL_REPOSITORY,
        "ref": ref,
        "releaseUrl": f"{CANONICAL_REPOSITORY}/releases/tag/{ref}",
        "generatedAt": generated_at,
    }


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"Invalid JSON manifest: {path}") from error
    if not isinstance(value, dict):
        raise ManifestError("Manifest must contain a JSON object.")
    return value


def validate_release(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != RELEASE_KEYS:
        raise ManifestError(f"{label} must contain the exact release fields.")
    release = {key: str(value[key]) for key in RELEASE_KEYS}
    expected = release_descriptor(release["ref"], release["generatedAt"])
    if release != expected:
        raise ManifestError(f"{label} does not identify the canonical release.")
    try:
        timestamp = datetime.fromisoformat(
            release["generatedAt"].replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ManifestError(f"{label}.generatedAt must use RFC 3339 UTC.") from error
    if timestamp.tzinfo != UTC or not release["generatedAt"].endswith("Z"):
        raise ManifestError(f"{label}.generatedAt must use RFC 3339 UTC.")
    return release


def validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {"schemaVersion", "source", "current", "files"}:
        raise ManifestError("Manifest contains unsupported top-level fields.")
    if value.get("schemaVersion") != 1:
        raise ManifestError("Unsupported starter-kit manifest schema.")
    source = validate_release(value.get("source"), "source")
    current = validate_release(value.get("current"), "current")
    raw_files = value.get("files")
    if not isinstance(raw_files, list):
        raise ManifestError("files must be a JSON array.")
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_entry in raw_files:
        if not isinstance(raw_entry, dict) or set(raw_entry) != ENTRY_KEYS:
            raise ManifestError("Core entries must contain the exact file fields.")
        entry = {key: str(raw_entry[key]) for key in ENTRY_KEYS}
        path = validate_relative_path(entry["path"])
        if path in seen or not is_core_path(path):
            raise ManifestError(f"Invalid or duplicate core path: {path}")
        seen.add(path)
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ManifestError(f"Invalid SHA-256 for {path}")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["canonicalSha256"]):
            raise ManifestError(f"Invalid canonical SHA-256 for {path}")
        if entry["contentKind"] not in {"binary", "text"}:
            raise ManifestError(f"Invalid content kind for {path}")
        if entry["mode"] not in {"100644", "100755"}:
            raise ManifestError(f"Invalid Git mode for {path}")
        if entry["strategy"] not in {"initialize-only", "merge", "replace"}:
            raise ManifestError(f"Invalid strategy for {path}")
        files.append(entry)
    if files != sorted(files, key=lambda entry: entry["path"]):
        raise ManifestError("Core entries must be sorted by path.")
    return {
        "schemaVersion": 1,
        "source": source,
        "current": current,
        "files": files,
    }


def existing_timestamp(path: Path, ref: str, files: list[dict[str, str]]) -> str | None:
    if not path.is_file():
        return None
    try:
        existing = validate_manifest(read_manifest(path))
    except ManifestError:
        return None
    if existing["current"]["ref"] == ref and existing["files"] == files:
        return existing["current"]["generatedAt"]
    return None


def prepare_manifest(args: argparse.Namespace) -> int:
    root = require_repository_root(args.repository_root)
    require_canonical_origin(root)
    files = core_entries(root, args.treeish)
    path = root / MANIFEST_PATH
    generated_at = existing_timestamp(path, args.release_ref, files) or utc_timestamp()
    release = release_descriptor(args.release_ref, generated_at)
    manifest = {
        "schemaVersion": 1,
        "source": release,
        "current": dict(release),
        "files": files,
    }
    validate_manifest(manifest)
    content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(
            json.dumps(
                {
                    "operation": "prepare",
                    "path": str(path),
                    "wouldWrite": path.read_text(encoding="utf-8") != content
                    if path.is_file()
                    else True,
                    "manifest": manifest,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"Prepared starter-kit manifest: {path}")
    return 0


def ref_exists(root: Path, ref: str) -> bool:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/tags/{ref}^{{commit}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def check_manifest(args: argparse.Namespace) -> int:
    root = require_repository_root(args.repository_root)
    path = root / MANIFEST_PATH
    manifest = validate_manifest(read_manifest(path))
    current_ref = manifest["current"]["ref"]
    if args.expected_ref and current_ref != args.expected_ref:
        raise ManifestError(
            f"Manifest current ref {current_ref} does not match {args.expected_ref}."
        )
    treeish = args.treeish
    if treeish is None and ref_exists(root, current_ref):
        treeish = current_ref
    expected = core_entries(root, treeish)
    if manifest["files"] != expected:
        raise ManifestError("Manifest core inventory does not match the selected tree.")
    print(
        json.dumps(
            {
                "path": str(path),
                "ref": current_ref,
                "files": len(expected),
                "treeish": treeish or "worktree",
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="help", help="show help and exit")
    parser.add_argument("--version", action="version", version=f"v{VERSION}")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the execution plan without writing",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show additional diagnostics"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="prepare the tracked manifest")
    prepare.add_argument("--release-ref", required=True)
    prepare.add_argument("--repository-root", type=Path, default=Path.cwd())
    prepare.add_argument("--treeish")

    check = subparsers.add_parser("check", help="validate the tracked manifest")
    check.add_argument("--expected-ref")
    check.add_argument("--repository-root", type=Path, default=Path.cwd())
    check.add_argument("--treeish")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.verbose:
            print(f"Repository root: {args.repository_root.resolve()}", file=sys.stderr)
        if args.command == "prepare":
            return prepare_manifest(args)
        return check_manifest(args)
    except (ManifestError, OSError, subprocess.SubprocessError) as error:
        if args.verbose:
            raise
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
