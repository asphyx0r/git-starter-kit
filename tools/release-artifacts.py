#!/usr/bin/env python3
"""Prepare and validate release-identification artifacts for a Git tree."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, overload

# Load the sibling by path for standalone and importlib-based callers alike.
_GIT_SPEC = importlib.util.spec_from_file_location(
    "git_objects", Path(__file__).with_name("git_objects.py")
)
assert _GIT_SPEC is not None and _GIT_SPEC.loader is not None
git_objects = importlib.util.module_from_spec(_GIT_SPEC)
_GIT_SPEC.loader.exec_module(git_objects)

GIT_TIMEOUT_SECONDS = 30
GIT_BULK_TIMEOUT_SECONDS = 300

VERSION = "1.0.0"
VERSION_PATH = "VERSION"
CHECKSUMS_PATH = "SHA256SUMS"
MANIFEST_PATH = "manifest.json"
TEMPLATE_PATH = "templates/release/manifest.template.json"
SCHEMA_PATH = "templates/release/manifest.schema.json"
REPOSITORY_SCHEMA_PATH = "templates/release/repository-manifest.schema.json"
OUTPUT_PATHS = frozenset({CHECKSUMS_PATH, MANIFEST_PATH})
SEMVER_TAG_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(-((0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"
)
SEMVER_PATTERN = re.compile("^" + SEMVER_TAG_PATTERN.pattern[2:])
UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PLACEHOLDER_PATTERN = re.compile(r"^\{\{([A-Za-z0-9:-]+)\}\}$")
RAW_PLACEHOLDER_PATTERN = re.compile(r'(?<!")\{\{([A-Za-z0-9:-]+)\}\}(?!")')


class ReleaseArtifactError(RuntimeError):
    """Raised when release artifacts cannot be prepared or validated."""


@overload
def run_git(root: Path, *arguments: str, binary: Literal[False] = False) -> str: ...


@overload
def run_git(root: Path, *arguments: str, binary: Literal[True]) -> bytes: ...


def run_git(root: Path, *arguments: str, binary: bool = False) -> str | bytes:
    timeout = (
        GIT_BULK_TIMEOUT_SECONDS
        if arguments and arguments[0] in {"ls-files", "ls-tree"}
        else GIT_TIMEOUT_SECONDS
    )
    try:
        result = git_objects.process_runner.run(
            [git_objects.git_executable(), "-C", str(root), *arguments],
            text=not binary,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise ReleaseArtifactError(
            f"git {' '.join(arguments)} timed out after {timeout}s"
        ) from error
    except OSError as error:
        raise ReleaseArtifactError(
            f"Unable to run git {' '.join(arguments)}: {error}"
        ) from error
    if result.returncode != 0:
        stderr = (
            result.stderr.decode("utf-8", errors="replace") if binary else result.stderr
        )
        raise ReleaseArtifactError(
            f"git {' '.join(arguments)} failed: {stderr.strip()}"
        )
    return result.stdout


def require_repository_root(value: Path) -> Path:
    root = value.resolve()
    if not root.is_dir():
        raise ReleaseArtifactError(f"Repository root does not exist: {root}")
    actual = Path(str(run_git(root, "rev-parse", "--show-toplevel")).strip()).resolve()
    if actual != root:
        raise ReleaseArtifactError(f"Repository root must be the Git root: {root}")
    return root


def validate_relative_path(value: str) -> str:
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ReleaseArtifactError(f"Unsafe repository path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseArtifactError(f"Unsafe repository path: {value!r}")
    return path.as_posix()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_blobs(root: Path, records: list[tuple[str, str, str]]) -> dict[str, bytes]:
    """Compatibility adapter for callers that need all blob contents."""
    with git_objects.blob_stream(
        root,
        [record[2] for record in records],
        timeout=GIT_BULK_TIMEOUT_SECONDS,
        error_type=ReleaseArtifactError,
    ) as blobs:
        return {
            record[0]: content for record, content in zip(records, blobs, strict=True)
        }


def index_records(root: Path) -> list[tuple[str, str, str]]:
    output = bytes(run_git(root, "ls-files", "--stage", "-z", binary=True))
    records: list[tuple[str, str, str]] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, object_id, stage = metadata.decode("ascii").split(" ")
        if stage != "0":
            raise ReleaseArtifactError("The Git index contains unmerged entries.")
        if mode == "160000":
            continue
        if mode not in {"100644", "100755", "120000"}:
            raise ReleaseArtifactError(f"Unsupported Git mode: {mode}")
        try:
            path = validate_relative_path(raw_path.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise ReleaseArtifactError("Git paths must use UTF-8.") from error
        records.append((path, mode, object_id))
    return records


def tree_records(root: Path, treeish: str) -> list[tuple[str, str, str]]:
    output = bytes(run_git(root, "ls-tree", "-r", "-z", treeish, binary=True))
    records: list[tuple[str, str, str]] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        if object_type == "commit":
            continue
        if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ReleaseArtifactError(f"Unsupported Git tree entry: {metadata!r}")
        try:
            path = validate_relative_path(raw_path.decode("utf-8"))
        except UnicodeDecodeError as error:
            raise ReleaseArtifactError("Git paths must use UTF-8.") from error
        records.append((path, mode, object_id))
    return records


def git_entries(root: Path, treeish: str | None) -> dict[str, tuple[str, bytes]]:
    records = tree_records(root, treeish) if treeish else index_records(root)
    contents = read_blobs(root, records)
    return {path: (mode, contents[path]) for path, mode, _object_id in records}


def line_ending(content: str) -> str | None:
    crlf_count = content.count("\r\n")
    remaining = content.replace("\r\n", "")
    lf_count = remaining.count("\n")
    cr_count = remaining.count("\r")
    kinds = sum(count > 0 for count in (crlf_count, lf_count, cr_count))
    if kinds != 1:
        return None
    if crlf_count:
        return "CRLF"
    if lf_count:
        return "LF"
    return "CR"


def file_record(path: str, mode: str, content: bytes) -> dict[str, Any]:
    if b"\0" in content:
        text = None
    else:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = None
    is_text = text is not None
    return {
        "relative_path": path,
        "size_bytes": len(content),
        "file_type": "text" if is_text else "binary",
        "line_ending": line_ending(text) if text is not None else None,
        "encoding": "UTF-8" if is_text else None,
        "sha256": sha256_bytes(content),
        "mode": mode[-3:] if mode in {"100644", "100755"} else None,
    }


def release_inventory(
    root: Path, treeish: str | None
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, bytes]]]:
    """Hash one blob at a time, retaining only release control content."""
    records = tree_records(root, treeish) if treeish else index_records(root)
    retained_paths = {
        VERSION_PATH,
        CHECKSUMS_PATH,
        MANIFEST_PATH,
        SCHEMA_PATH,
        REPOSITORY_SCHEMA_PATH,
        TEMPLATE_PATH,
    }
    retained: dict[str, tuple[str, bytes]] = {}
    files: list[dict[str, Any]] = []
    with git_objects.blob_stream(
        root,
        [record[2] for record in records],
        timeout=GIT_BULK_TIMEOUT_SECONDS,
        error_type=ReleaseArtifactError,
    ) as blobs:
        for path, mode, _object_id in records:
            content = next(blobs)
            if path in retained_paths:
                retained[path] = (mode, content)
            if path not in OUTPUT_PATHS:
                files.append(file_record(path, mode, content))
            del content
        next(blobs, None)  # Consume the batch trailer and verify the exit status.
    return files, retained


def _payload_from_records(
    records: list[dict[str, Any]],
    version_entry: tuple[str, bytes] | None,
    version: str,
    prepare: bool,
) -> tuple[list[dict[str, Any]], bytes]:
    version_content = f"{version}\n".encode("utf-8")
    if prepare:
        records = [
            record for record in records if record["relative_path"] != VERSION_PATH
        ]
        records.append(file_record(VERSION_PATH, "100644", version_content))
    elif version_entry != ("100644", version_content):
        raise ReleaseArtifactError("VERSION does not match the manifest version.")
    records.sort(key=lambda record: record["relative_path"].encode("utf-8"))
    checksums = "".join(
        f"{record['sha256']}  {record['relative_path']}\n" for record in records
    ).encode("utf-8")
    return records, checksums


def release_payload(
    entries: dict[str, tuple[str, bytes]], version: str, prepare: bool
) -> tuple[list[dict[str, Any]], bytes]:
    """Compatibility adapter for callers with materialized Git entries."""
    records = [
        file_record(path, mode, content)
        for path, (mode, content) in entries.items()
        if path not in OUTPUT_PATHS
    ]
    return _payload_from_records(records, entries.get(VERSION_PATH), version, prepare)


def parse_release_date(value: str) -> str:
    if not UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise ReleaseArtifactError(
            "release date must use the UTC format YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReleaseArtifactError("release date is invalid") from error
    if parsed.tzinfo != UTC:
        raise ReleaseArtifactError("release date must use UTC")
    return value


def version_from_ref(ref: str) -> str:
    if not SEMVER_TAG_PATTERN.fullmatch(ref):
        raise ReleaseArtifactError("release ref must be a SemVer tag prefixed with v")
    return ref[1:]


def parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseArtifactError(f"Invalid JSON {label}.") from error
    if not isinstance(value, dict):
        raise ReleaseArtifactError(f"{label} must contain a JSON object.")
    return value


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        return parse_json_object(path.read_bytes(), label)
    except OSError as error:
        raise ReleaseArtifactError(f"Unable to read {label}: {path}") from error


def load_metadata(root: Path, path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved == root or root in resolved.parents:
        raise ReleaseArtifactError("metadata file must be outside the repository")
    value = load_json_object(resolved, "metadata file")
    expected = {
        "program_id",
        "name",
        "channel",
        "critical_update",
        "release_notes",
        "update",
        "artifact",
        "metadata",
    }
    if set(value) != expected:
        raise ReleaseArtifactError("metadata file must contain the exact fields")
    update = value.get("update")
    expected_update = {
        "min_source_version",
        "strategy",
        "preserve_paths",
        "remove_obsolete_files",
        "backup_required",
        "restart_required",
        "rollback_supported",
        "migrations",
    }
    if not isinstance(update, dict) or set(update) != expected_update:
        raise ReleaseArtifactError("update must contain the exact policy fields")
    artifact = value.get("artifact")
    if not isinstance(artifact, dict) or set(artifact) != {"id", "target"}:
        raise ReleaseArtifactError("artifact must contain id and target")
    target = artifact.get("target")
    if not isinstance(target, dict) or set(target) != {
        "os",
        "arch",
        "min_os_version",
    }:
        raise ReleaseArtifactError("artifact target fields are incomplete")
    metadata = value.get("metadata")
    if not isinstance(metadata, dict) or set(metadata) != {
        "author",
        "license",
        "support_url",
    }:
        raise ReleaseArtifactError("metadata must contain the exact identity fields")
    return value


def parse_template(content: bytes, label: str) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
        normalized = RAW_PLACEHOLDER_PATTERN.sub(r'"{{\1}}"', text)
        value = json.loads(normalized)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseArtifactError(f"Invalid {label}.") from error
    if not isinstance(value, dict):
        raise ReleaseArtifactError("manifest template must contain an object")
    return value


def load_template(path: Path) -> dict[str, Any]:
    try:
        return parse_template(path.read_bytes(), "manifest template")
    except OSError as error:
        raise ReleaseArtifactError(
            f"Unable to read manifest template: {path}"
        ) from error


def render_value(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, str):
        match = PLACEHOLDER_PATTERN.fullmatch(value)
        if not match:
            return value
        key = match.group(1)
        if key not in replacements:
            raise ReleaseArtifactError(f"Unknown template placeholder: {key}")
        return replacements[key]
    if isinstance(value, list):
        return [render_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, replacements) for key, item in value.items()}
    return value


def build_manifest(
    root: Path,
    metadata: dict[str, Any],
    version: str,
    release_date: str,
    files: list[dict[str, Any]],
    checksums: bytes,
    template_content: bytes | None = None,
) -> dict[str, Any]:
    template = (
        parse_template(template_content, "manifest template")
        if template_content is not None
        else load_template(root / TEMPLATE_PATH)
    )
    artifacts = template.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise ReleaseArtifactError(
            "manifest template must define one artifact prototype"
        )
    artifact_template = artifacts[0]
    if not isinstance(artifact_template, dict):
        raise ReleaseArtifactError("artifact prototype must be an object")
    file_templates = artifact_template.get("files")
    if not isinstance(file_templates, list) or len(file_templates) != 1:
        raise ReleaseArtifactError("manifest template must define one file prototype")
    file_template = file_templates[0]
    common = {
        "program-id": metadata["program_id"],
        "application-name": metadata["name"],
        "application-semver-number": version,
        "release-date-YYYY-MM-DDTHH:MM:SSZ": release_date,
        "application-deployment-channel": metadata["channel"],
        "critical-update-boolean": metadata["critical_update"],
        "release-notes-json-array": metadata["release_notes"],
        "minimum-upgradable-source-semver-number": metadata["update"].get(
            "min_source_version"
        ),
        "update-strategy-patch-or-full-reinstall": metadata["update"].get("strategy"),
        "preserve-paths-json-array": metadata["update"].get("preserve_paths"),
        "remove-obsolete-files-boolean": metadata["update"].get(
            "remove_obsolete_files"
        ),
        "backup-required-boolean": metadata["update"].get("backup_required"),
        "restart-required-boolean": metadata["update"].get("restart_required"),
        "rollback-supported-boolean": metadata["update"].get("rollback_supported"),
        "migrations-json-array": metadata["update"].get("migrations"),
        "artifact-id": metadata["artifact"]["id"],
        "target-os": metadata["artifact"]["target"]["os"],
        "target-architecture": metadata["artifact"]["target"]["arch"],
        "target-minimum-os-version": metadata["artifact"]["target"]["min_os_version"],
        "artifact-archive-type": "git-tree",
        "artifact-total-files": len(files),
        "artifact-size-in-bytes": sum(item["size_bytes"] for item in files),
        "artifact-build-date-YYYY-MM-DDTHH:MM:SSZ": release_date,
        "artifact-sha256-hash": sha256_bytes(checksums),
        "program-author-name": metadata["metadata"].get("author"),
        "program-license": metadata["metadata"].get("license"),
        "program-support-url": metadata["metadata"].get("support_url"),
    }
    rendered_files: list[dict[str, Any]] = []
    for item in files:
        replacements = dict(common)
        replacements.update(
            {
                "file-relative-path": item["relative_path"],
                "file-size-in-bytes": item["size_bytes"],
                "file-type-text-or-binary": item["file_type"],
                "file-line-ending-json-value": item["line_ending"],
                "file-encoding-json-value": item["encoding"],
                "file-sha256-hash": item["sha256"],
                "file-mode-json-value": item["mode"],
            }
        )
        rendered = render_value(file_template, replacements)
        if not isinstance(rendered, dict):
            raise ReleaseArtifactError("rendered file entry must be an object")
        rendered_files.append(rendered)
    artifact_copy = dict(artifact_template)
    artifact_copy["files"] = rendered_files
    template_copy = dict(template)
    template_copy["artifacts"] = [artifact_copy]
    manifest = render_value(template_copy, common)
    if not isinstance(manifest, dict):
        raise ReleaseArtifactError("rendered manifest must be an object")
    if "{{" in json.dumps(manifest, ensure_ascii=False):
        raise ReleaseArtifactError("rendered manifest contains unresolved placeholders")
    return manifest


def build_repository_manifest(
    version: str,
    release_date: str,
    files: list[dict[str, Any]],
    checksums: bytes,
) -> dict[str, Any]:
    return {
        "manifest_version": "3.0.0",
        "release_kind": "repository",
        "version": version,
        "release_date": release_date,
        "artifact": {
            "format": "git-tree",
            "files": files,
            "total_files": len(files),
            "size_bytes": sum(item["size_bytes"] for item in files),
            "sha256": sha256_bytes(checksums),
            "built_at": release_date,
        },
    }


def manifest_kind(manifest: dict[str, Any]) -> str:
    if (
        manifest.get("manifest_version") == "3.0.0"
        and manifest.get("release_kind") == "repository"
    ):
        return "repository"
    if manifest.get("manifest_version") == "2.0.0" and "release_kind" not in manifest:
        return "deployment"
    raise ReleaseArtifactError("Unsupported manifest_version or release_kind")


def validate_schema(
    root: Path,
    manifest: dict[str, Any],
    schema_content: bytes | None = None,
) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
    except ImportError as error:
        raise ReleaseArtifactError(
            "jsonschema is required; install tools/release-artifacts-requirements.txt"
        ) from error
    schema = (
        parse_json_object(schema_content, "manifest schema")
        if schema_content is not None
        else load_json_object(root / SCHEMA_PATH, "manifest schema")
    )
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(
            validator.iter_errors(manifest),
            key=lambda item: list(item.path),
        )
    except Exception as error:
        raise ReleaseArtifactError(
            f"Manifest schema validation failed: {error}"
        ) from error
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ReleaseArtifactError(f"Manifest does not match the schema: {details}")


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=4) + "\n").encode("utf-8")


def write_outputs(root: Path, outputs: dict[str, bytes]) -> None:
    previous: dict[str, bytes | None] = {}
    temporary: dict[str, Path] = {}
    replaced: list[str] = []
    try:
        for relative_path, content in outputs.items():
            target = root / relative_path
            previous[relative_path] = target.read_bytes() if target.exists() else None
            handle, raw_path = tempfile.mkstemp(
                dir=root, prefix=f".{relative_path}.", suffix=".tmp"
            )
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary[relative_path] = Path(raw_path)
        for relative_path in outputs:
            os.replace(temporary[relative_path], root / relative_path)
            replaced.append(relative_path)
    except OSError as error:
        for relative_path in reversed(replaced):
            target = root / relative_path
            old_content = previous[relative_path]
            if old_content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(old_content)
        raise ReleaseArtifactError(
            f"Unable to write release artifacts: {error}"
        ) from error
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)


def ref_exists(root: Path, ref: str) -> bool:
    try:
        result = git_objects.process_runner.run(
            [
                git_objects.git_executable(),
                "-C",
                str(root),
                "rev-parse",
                "--verify",
                "--quiet",
                ref,
            ],
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ReleaseArtifactError(
            f"git rev-parse {ref} timed out after {GIT_TIMEOUT_SECONDS}s"
        ) from error
    except OSError as error:
        raise ReleaseArtifactError(
            f"Unable to resolve Git ref {ref}: {error}"
        ) from error
    if result.returncode not in {0, 1}:
        raise ReleaseArtifactError(f"git rev-parse {ref} failed: {result.stderr!r}")
    return result.returncode == 0


def confirm_write(force: bool) -> None:
    if force:
        return
    if not sys.stdin.isatty():
        raise ReleaseArtifactError("writing requires --force in non-interactive mode")
    answer = input("Write VERSION, SHA256SUMS, and manifest.json? [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        raise ReleaseArtifactError("operation cancelled")


def prepare_artifacts(args: argparse.Namespace) -> int:
    root = require_repository_root(args.repository_root)
    if args.kind == "deployment" and args.metadata_file is None:
        raise ReleaseArtifactError("deployment preparation requires --metadata-file")
    if args.kind == "repository" and args.metadata_file is not None:
        raise ReleaseArtifactError("repository preparation rejects --metadata-file")
    version = version_from_ref(args.release_ref)
    release_date = parse_release_date(args.release_date)
    treeish = None if args.index else (args.treeish or "HEAD")
    records, retained = release_inventory(root, treeish)
    files, checksums = _payload_from_records(
        records, retained.get(VERSION_PATH), version, True
    )
    if args.kind == "repository":
        manifest = build_repository_manifest(version, release_date, files, checksums)
        schema_entry = retained.get(REPOSITORY_SCHEMA_PATH)
        if schema_entry is None:
            raise ReleaseArtifactError(
                "selected Git content does not contain the repository manifest schema"
            )
        validate_schema(root, manifest, schema_entry[1])
    else:
        metadata = load_metadata(root, args.metadata_file)
        manifest = build_manifest(
            root, metadata, version, release_date, files, checksums
        )
        validate_schema(root, manifest)
    outputs = {
        VERSION_PATH: f"{version}\n".encode("utf-8"),
        CHECKSUMS_PATH: checksums,
        MANIFEST_PATH: manifest_bytes(manifest),
    }
    changed = [
        path
        for path, content in outputs.items()
        if not (root / path).is_file() or (root / path).read_bytes() != content
    ]
    report = {
        "operation": "prepare",
        "releaseRef": args.release_ref,
        "files": len(files),
        "changed": changed,
        "treeish": treeish or "index",
    }
    if args.dry_run:
        print(json.dumps(report, indent=2))
        return 0
    if changed:
        confirm_write(args.force)
        write_outputs(root, outputs)
    print(json.dumps(report, indent=2))
    return 0


def check_artifacts(args: argparse.Namespace) -> int:
    root = require_repository_root(args.repository_root)
    requested_treeish = args.treeish
    if not args.index and requested_treeish is None:
        worktree_manifest = load_json_object(root / MANIFEST_PATH, "release manifest")
        worktree_version = worktree_manifest.get("version")
        if isinstance(worktree_version, str):
            recorded_ref = f"v{worktree_version}"
            if ref_exists(root, f"refs/tags/{recorded_ref}^{{commit}}"):
                requested_treeish = recorded_ref
    records, entries = release_inventory(root, requested_treeish)
    manifest_entry = entries.get(MANIFEST_PATH)
    if manifest_entry is None:
        raise ReleaseArtifactError(
            "selected Git content does not contain manifest.json"
        )
    try:
        manifest = json.loads(manifest_entry[1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseArtifactError("selected manifest.json is invalid JSON") from error
    if not isinstance(manifest, dict):
        raise ReleaseArtifactError("selected manifest.json must contain an object")
    kind = manifest_kind(manifest)
    schema_path = REPOSITORY_SCHEMA_PATH if kind == "repository" else SCHEMA_PATH
    schema_entry = entries.get(schema_path)
    if schema_entry is None:
        raise ReleaseArtifactError(
            "selected Git content does not contain the manifest schema"
        )
    validate_schema(root, manifest, schema_entry[1])
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
        raise ReleaseArtifactError("manifest version is not strict SemVer")
    expected_ref = args.expected_ref or f"v{version}"
    if expected_ref != f"v{version}":
        raise ReleaseArtifactError("manifest version does not match the expected ref")
    files, checksums = _payload_from_records(
        records, entries.get(VERSION_PATH), version, False
    )
    checksums_entry = entries.get(CHECKSUMS_PATH)
    if checksums_entry is None or checksums_entry[1] != checksums:
        raise ReleaseArtifactError("SHA256SUMS does not match the selected Git content")
    if kind == "repository":
        release_date = manifest.get("release_date")
        if not isinstance(release_date, str):
            raise ReleaseArtifactError("manifest release_date must be a UTC timestamp")
        parse_release_date(release_date)
        if manifest_entry[0] != "100644" or checksums_entry[0] != "100644":
            raise ReleaseArtifactError(
                "repository release outputs must use Git mode 100644"
            )
        expected_manifest = build_repository_manifest(
            version, release_date, files, checksums
        )
        if manifest != expected_manifest:
            raise ReleaseArtifactError("manifest git-tree inventory is inconsistent")
    else:
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) != 1:
            raise ReleaseArtifactError("manifest must contain one git-tree artifact")
        artifact = artifacts[0]
        template_entry = entries.get(TEMPLATE_PATH)
        if template_entry is None:
            raise ReleaseArtifactError(
                "selected Git content does not contain the manifest template"
            )
        expected_manifest = build_manifest(
            root,
            {
                "program_id": manifest["program_id"],
                "name": manifest["name"],
                "channel": manifest["channel"],
                "critical_update": manifest["critical_update"],
                "release_notes": manifest["release_notes"],
                "update": manifest["update"],
                "artifact": {
                    "id": artifact["id"],
                    "target": artifact["target"],
                },
                "metadata": manifest["metadata"],
            },
            version,
            manifest["release_date"],
            files,
            checksums,
            template_entry[1],
        )
        if manifest != expected_manifest:
            raise ReleaseArtifactError(
                "manifest.json does not match the selected manifest template"
            )
        expected_size = sum(item["size_bytes"] for item in files)
        if (
            artifact.get("format") != "git-tree"
            or artifact.get("files") != files
            or artifact.get("total_files") != len(files)
            or artifact.get("size_bytes") != expected_size
            or artifact.get("sha256") != sha256_bytes(checksums)
            or artifact.get("built_at") != manifest.get("release_date")
        ):
            raise ReleaseArtifactError("manifest git-tree inventory is inconsistent")
    print(
        json.dumps(
            {
                "operation": "check",
                "releaseRef": expected_ref,
                "files": len(files),
                "treeish": requested_treeish or "index",
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
    parser.add_argument(
        "--force", action="store_true", help="write without interactive confirmation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="prepare release artifacts")
    prepare.add_argument("--release-ref", required=True)
    prepare.add_argument("--release-date", required=True)
    prepare.add_argument(
        "--kind", choices=("repository", "deployment"), default="deployment"
    )
    prepare.add_argument("--metadata-file", type=Path)
    prepare_selected = prepare.add_mutually_exclusive_group()
    prepare_selected.add_argument("--treeish")
    prepare_selected.add_argument("--index", action="store_true")
    prepare.add_argument("--repository-root", type=Path, default=Path.cwd())

    check = subparsers.add_parser("check", help="validate release artifacts")
    check.add_argument("--expected-ref")
    selected = check.add_mutually_exclusive_group()
    selected.add_argument("--treeish")
    selected.add_argument("--index", action="store_true")
    check.add_argument("--repository-root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.verbose:
            print(f"Repository root: {args.repository_root.resolve()}", file=sys.stderr)
        if args.command == "prepare":
            return prepare_artifacts(args)
        return check_artifacts(args)
    except (ReleaseArtifactError, OSError, subprocess.SubprocessError) as error:
        if args.verbose:
            raise
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
