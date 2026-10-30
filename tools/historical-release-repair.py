#!/usr/bin/env python3
"""Prepare and independently verify six explicitly allowlisted historical repairs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY = "asphyx0r/git-starter-kit"
RULES_REPOSITORY = "asphyx0r/agent-coding-rules"
RULES_REF = "v1.42.0"
RULES_COMMIT = "7cdf1cb2688813694c4982f909bf79be52880f22"
TAGS = {
    "v1.7.3": "7e964d89a9f1553e2575191f60ca333c2a15dc93",
    "v2.0.1": "4a8e45c0eaef3030e263a34d694b9b4d10d3af3b",
    "v2.1.0": "3db8add2135ec04fc70c59a635e9de3a4f7bc464",
    "v2.2.0": "c3f031e5cbe8a7d4fe6d571fb3935b97caf5f2b6",
    "v2.8.0": "00745498a7e6f00d2f10341e4ba493a69b6cefef",
    "v2.11.0": "4bd47329e6a989823472eb015c62e75bb7318bc3",
}
REUSED_TAGS = {"v2.0.1", "v2.1.0"}
RELEASE_IDS = {
    "v2.0.1": 357402329,
    "v2.1.0": 362702751,
    "v2.8.0": 383049548,
    "v2.11.0": 388017021,
}
DRAFT_TAG = "v2.8.0"
DRAFT_ENDPOINT = f"repos/{REPOSITORY}/releases/{RELEASE_IDS[DRAFT_TAG]}"
RELEASE_STATE_FIELDS = (
    "id",
    "tag_name",
    "draft",
    "prerelease",
    "published_at",
    "updated_at",
    "body",
)
FAILED_RUNS = {"v2.0.1": 29838636736, "v2.8.0": 33926454048, "v2.11.0": 34779306282}
RULE_FILES = (
    "AGENTS.md",
    "BRANCH_RULES.md",
    "CODING_RULES.md",
    "COMMIT_RULES.md",
    "DOCUMENTATION_RULES.md",
    "LANGUAGE_RULES.md",
    "RELEASE_RULES.md",
)
PROVENANCE = "_agent-rules-source.json"
INVENTORY = "_starter-kit-files.json"
PROOF = "historical-repair-proof.json"
BUILDER = "tools/build-release-package.ps1"
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
_SPEC = importlib.util.spec_from_file_location(
    "repair_git_objects", Path(__file__).with_name("git_objects.py")
)
assert _SPEC is not None and _SPEC.loader is not None
git_objects = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(git_objects)


class RepairError(RuntimeError):
    """A repair candidate failed its closed-scope validation."""


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    timeout: int = 120,
) -> bytes:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            input=input_bytes,
            env=env,
            cwd=cwd,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RepairError(f"Unable to run {Path(command[0]).name}: {error}") from error
    if result.returncode:
        raise RepairError(
            f"{Path(command[0]).name} failed: {result.stderr.decode('utf-8', errors='replace')[-4000:]}"
        )
    return result.stdout


def git(root: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    return run(
        [
            git_objects.git_executable(),
            "-c",
            "core.attributesFile=" + os.devnull,
            "-C",
            str(root),
            *arguments,
        ],
        input_bytes=input_bytes,
    )


def tag_identity(root: Path, tag: str) -> dict[str, str]:
    if tag not in TAGS:
        raise RepairError("Tag is outside the historical repair allowlist")
    reference = f"refs/tags/{tag}"
    tag_object = git(root, "rev-parse", "--verify", reference).decode().strip()
    if git(root, "cat-file", "-t", tag_object).strip() != b"tag":
        raise RepairError("Historical source tag must remain annotated")
    commit = (
        git(root, "rev-parse", "--verify", reference + "^{commit}").decode().strip()
    )
    if commit != TAGS[tag]:
        raise RepairError(f"Allowlisted commit mismatch for {tag}")
    tree = git(root, "rev-parse", reference + "^{tree}").decode().strip()
    return {"tag": tag, "tagObject": tag_object, "commit": commit, "tree": tree}


def safe_path(name: str) -> str:
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise RepairError(f"Unsafe archive or source path: {name!r}")
    return name


def read_archive(content: bytes) -> dict[str, bytes]:
    if len(content) > MAX_ARCHIVE_BYTES:
        raise RepairError("Archive exceeds size limit")
    files: dict[str, bytes] = {}
    names: set[str] = set()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
                raise RepairError("Expanded archive exceeds size limit")
            for entry in entries:
                if "\\" in entry.orig_filename or "\0" in entry.orig_filename:
                    raise RepairError("Unsafe original ZIP filename")
                name = safe_path(
                    entry.filename[:-1] if entry.is_dir() else entry.filename
                )
                folded = name.casefold()
                if folded in names:
                    raise RepairError(f"Archive duplicate or case collision: {name}")
                names.add(folded)
                kind = stat.S_IFMT(entry.external_attr >> 16)
                if kind not in {0, stat.S_IFREG, stat.S_IFDIR} or entry.flag_bits & 1:
                    raise RepairError(f"Unsupported archive entry: {name}")
                if not entry.is_dir():
                    files[name] = archive.read(entry)
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        raise RepairError(f"Invalid ZIP archive: {error}") from error
    for name in files:
        if any(
            "/".join(name.split("/")[:index]) in files
            for index in range(1, len(name.split("/")))
        ):
            raise RepairError(f"Archive path collision: {name}")
    return files


def source_files(root: Path, commit: str) -> dict[str, tuple[str, bytes]]:
    records = []
    for raw in git(root, "ls-tree", "-rz", commit).split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        path = safe_path(raw_path.decode("utf-8"))
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise RepairError(f"Unsupported source object: {path}")
        records.append((path, mode, object_id))
    attributes = git(
        root,
        "check-attr",
        f"--source={commit}",
        "-z",
        "--stdin",
        "eol",
        "text",
        input_bytes=b"".join(path.encode() + b"\0" for path, _, _ in records),
    ).split(b"\0")
    eol = {}
    for index in range(0, len(attributes) - 1, 3):
        attribute_path, attribute, value = attributes[index : index + 3]
        if attribute == b"eol":
            eol[attribute_path.decode()] = value
    with git_objects.blob_stream(
        root, [row[2] for row in records], timeout=120, error_type=RepairError
    ) as blobs:
        result = {}
        for (path, mode, _), content in zip(records, blobs, strict=True):
            if eol.get(path) == b"crlf":
                content = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            result[path] = (mode, content)
    return result


def map_source_files(
    files: dict[str, bytes],
    expected: dict[str, tuple[str, bytes]],
    generated: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if set(files) != set(expected) | set(generated):
        raise RepairError(
            f"Source path coverage mismatch: missing={sorted(set(expected) - set(files))}; "
            f"extra={sorted(set(files) - set(expected) - set(generated))}"
        )
    result = []
    for path, content in sorted(files.items()):
        if path in generated:
            mapping = generated[path]
            mode = mapping.get("mode", "100644")
        else:
            mode, original = expected[path]
            if content != original:
                raise RepairError(f"Source content mismatch: {path}")
            mapping = {"kind": "git", "path": path}
        result.append(
            {
                "path": path,
                "size": len(content),
                "sha256": digest(content),
                "mode": mode,
                "source": mapping,
            }
        )
    return result


def canonical(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        return content
    return (text.rstrip("\n") + "\n").encode() if text else b""


def validate_inventory(files: dict[str, bytes], tag: str) -> list[str]:
    if INVENTORY not in files:
        if tag in {"v1.7.3", "v2.0.1"}:
            return []
        raise RepairError("Required internal inventory missing")
    manifest = json.loads(files[INVENTORY])
    seen = set()
    for record in manifest["files"]:
        path = safe_path(record["path"])
        if path in seen or path not in files or path == INVENTORY:
            raise RepairError(f"Invalid internal inventory path: {path}")
        seen.add(path)
        if record["sha256"] != digest(files[path]):
            raise RepairError(f"Internal inventory digest mismatch: {path}")
        if "canonicalSha256" in record and record["canonicalSha256"] != digest(
            canonical(files[path])
        ):
            raise RepairError(f"Internal canonical digest mismatch: {path}")
        if record.get("mode", "100644") not in {"100644", "100755"}:
            raise RepairError(f"Invalid internal inventory mode: {path}")
    missing = sorted(set(files) - seen - {INVENTORY})
    if missing:
        if tag != "v2.1.0":
            raise RepairError(f"Internal inventory missing coverage: {missing}")
        if any(
            not any(part.startswith(".") for part in path.split("/"))
            for path in missing
        ):
            raise RepairError(
                "v2.1.0 supplemental inventory permits only historical hidden omissions"
            )
    return missing


def validate_checksums(content: bytes, archives: dict[str, bytes]) -> None:
    expected = b"".join(
        f"{digest(data)}  {name}\n".encode() for name, data in sorted(archives.items())
    )
    if content != expected:
        raise RepairError(
            "SHA256SUMS must cover exactly both ZIPs with correct digests"
        )


def validate_inventory_document(files: dict[str, bytes], header: str) -> None:
    document = files["docs/repository-files.md"].decode("utf-8")
    prefix = header + "\n\n```text\n"
    if not document.startswith(prefix) or not document.endswith("\n```\n"):
        raise RepairError("Historical composed inventory template/fence mismatch")
    paths = document[len(prefix) : -len("\n```\n")].split("\n")
    # The immutable PowerShell recipe sorts with the platform's culture.
    if len(paths) != len(set(paths)) or set(paths) != set(files):
        raise RepairError(
            "Historical composed repository inventory path coverage mismatch"
        )


def validate_archive_modes(content: bytes, records: list[dict[str, Any]]) -> None:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for record in records:
            entry = archive.getinfo(record["path"])
            actual = "100755" if (entry.external_attr >> 16) & 0o111 else "100644"
            if actual != record["mode"]:
                raise RepairError(
                    f"ZIP executable mode differs from Git source: {record['path']}"
                )


def validate_consumer_inventory(
    files: dict[str, bytes], tag: str, modes: dict[str, str]
) -> None:
    state = json.loads(files["starter-kit-manifest.json"])
    if state["source"]["ref"] != tag or state["current"]["ref"] != tag:
        raise RepairError("Consumer state source ref mismatch")
    expected = set(files) - {
        *RULE_FILES,
        PROVENANCE,
        INVENTORY,
        "starter-kit-manifest.json",
    }
    records = state["files"]
    paths = [record["path"] for record in records]
    if len(set(paths)) != len(paths) or set(paths) != expected:
        raise RepairError("Consumer state inventory coverage mismatch")
    for record in records:
        path = record["path"]
        if (
            record["sha256"] != digest(files[path])
            or record["mode"] != modes[path]
            or record["canonicalSha256"] != digest(canonical(files[path]))
        ):
            raise RepairError(
                f"Consumer state digest/mode/canonical metadata mismatch: {path}"
            )
        try:
            files[path].decode("utf-8")
            kind = "text"
        except UnicodeDecodeError:
            kind = "binary"
        if record["contentKind"] != kind:
            raise RepairError(f"Consumer state content kind mismatch: {path}")


def validate_transformations(
    tag: str, transformations: list[dict[str, Any]], files: dict[str, bytes]
) -> None:
    if tag in REUSED_TAGS:
        if transformations:
            raise RepairError("Existing archives cannot claim build transformations")
        return
    final = {
        "operation": "repack final enriched ZIP with Git modes, sorted paths and fixed ZIP timestamps"
    }
    if not transformations or transformations[-1] != final:
        raise RepairError("Missing final ZIP transformation evidence")
    seen = set()
    allowed = {*RULE_FILES, PROVENANCE, INVENTORY, "starter-kit-manifest.json"}
    for record in transformations[:-1]:
        path = record.get("path")
        if (
            set(record) != {"path", "beforeSha256", "afterSha256", "operation"}
            or path not in allowed
            or path in seen
            or path not in files
        ):
            raise RepairError("Invalid or duplicate build transformation")
        seen.add(path)
        before = record["beforeSha256"]
        operation = (
            "immutable public rule overlay"
            if path in RULE_FILES
            else "regenerate dependent provenance/inventory"
        )
        if (
            record["afterSha256"] != digest(files[path])
            or record["beforeSha256"] == record["afterSha256"]
            or (before is not None and not re.fullmatch(r"[0-9a-f]{64}", before))
            or record["operation"] != operation
        ):
            raise RepairError(f"Build transformation digest/operation mismatch: {path}")


def qualification() -> dict[str, Any] | None:
    values = [
        os.environ.get(name, "")
        for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA")
    ]
    if not any(values):
        return None
    if (
        not all(values)
        or not values[0].isdigit()
        or not values[1].isdigit()
        or not re.fullmatch(r"[0-9a-f]{40}", values[2])
    ):
        raise RepairError("Incomplete qualification run identity")
    return {
        "runId": int(values[0]),
        "runAttempt": int(values[1]),
        "sourceSha": values[2],
    }


class PublicAPI:
    """The only authenticated boundary; all operations are explicit GET requests."""

    def get(self, path: str) -> Any:
        command = [
            "gh",
            "api",
            "--method",
            "GET",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
            path,
        ]
        return json.loads(run(command, timeout=90))

    def download(self, asset_id: int) -> bytes:
        return run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                "-H",
                "Accept: application/octet-stream",
                f"repos/{REPOSITORY}/releases/assets/{asset_id}",
            ],
            timeout=180,
        )


def public_rules(
    api: Any, reference: str, commit: str, names: list[str]
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if (
        not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", reference)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or not names
        or len(set(names)) != len(names)
        or not set(names).issubset(RULE_FILES)
    ):
        raise RepairError("Invalid immutable public rules selection")
    prefix = f"repos/{RULES_REPOSITORY}/git"
    tag = api.get(f"{prefix}/ref/tags/{reference}")
    if tag["ref"] != f"refs/tags/{reference}":
        raise RepairError("Public upstream tag ref mismatch")
    obj = tag["object"]
    tag_object = obj["sha"]
    seen = set()
    while obj["type"] == "tag":
        if obj["sha"] in seen:
            raise RepairError("Cyclic public upstream tag")
        seen.add(obj["sha"])
        tag_record = api.get(f"{prefix}/tags/{obj['sha']}")
        if tag_record["sha"] != obj["sha"]:
            raise RepairError("Public upstream tag object mismatch")
        obj = tag_record["object"]
    if obj["type"] != "commit" or obj["sha"] != commit:
        raise RepairError("Public upstream commit mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RepairError("Invalid public upstream commit")
    commit_record = api.get(f"{prefix}/commits/{commit}")
    tree_id = commit_record["tree"]["sha"]
    tree = api.get(f"{prefix}/trees/{tree_id}")
    if (
        commit_record["sha"] != commit
        or tree["sha"] != tree_id
        or tree.get("truncated")
    ):
        raise RepairError("Public upstream commit/tree object mismatch")
    files = {}
    blob_ids = {}
    for name in names:
        entries = [entry for entry in tree["tree"] if entry["path"] == name]
        if (
            len(entries) != 1
            or entries[0]["type"] != "blob"
            or entries[0]["mode"] != "100644"
        ):
            raise RepairError(f"Public upstream rule must be one regular blob: {name}")
        object_id = entries[0]["sha"]
        blob = api.get(f"{prefix}/blobs/{object_id}")
        if blob["sha"] != object_id or blob["encoding"] != "base64":
            raise RepairError("Public upstream blob identity mismatch")
        content = base64.b64decode(blob["content"].replace("\n", ""), validate=True)
        actual = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if actual != object_id:
            raise RepairError(f"Public upstream blob bytes mismatch: {name}")
        files[name] = content
        blob_ids[name] = object_id
    return (
        {
            "repository": RULES_REPOSITORY,
            "ref": reference,
            "tagObject": tag_object,
            "commit": commit,
            "tree": tree_id,
            "blobs": blob_ids,
            "sha256": {name: digest(content) for name, content in files.items()},
        },
        files,
    )


def asset_names(tag: str) -> list[str]:
    names = [f"git-starter-kit-{tag}-with-agent-rules.zip"]
    if tag not in {"v1.7.3", "v2.0.1"}:
        names.append(f"git-starter-kit-{tag}-upgrade-toolkit.zip")
    if tag in {"v2.8.0", "v2.11.0"}:
        names.append("SHA256SUMS")
    return names


def validate_release_before(tag: str, release: dict[str, Any] | None) -> None:
    expected_id = RELEASE_IDS.get(tag)
    if expected_id is None:
        if release is not None:
            raise RepairError(
                "Unexpected existing release for an absent historical profile"
            )
        return
    if (
        release is None
        or release["id"] != expected_id
        or release["tag_name"] != tag
        or type(release["draft"]) is not bool
        or type(release["prerelease"]) is not bool
    ):
        raise RepairError("Known historical release ID/tag/state identity mismatch")


def require_release_absent(api: Any, tag: str) -> None:
    seen = set()
    page = 1
    while True:
        releases = api.get(f"repos/{REPOSITORY}/releases?per_page=100&page={page}")
        if not isinstance(releases, list) or len(releases) > 100:
            raise RepairError("Invalid paginated release inventory")
        for release in releases:
            if release["tag_name"] == tag:
                raise RepairError(
                    "Unexpected existing release/draft for absent historical profile"
                )
            if release["id"] in seen:
                raise RepairError("Duplicate release ID in paginated inventory")
            seen.add(release["id"])
        if len(releases) < 100:
            return
        page += 1


def release_snapshot(
    api: Any, tag: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, bytes]]:
    if tag not in RELEASE_IDS:
        require_release_absent(api, tag)
        return None, [], {}
    release = api.get(f"repos/{REPOSITORY}/releases/{RELEASE_IDS[tag]}")
    validate_release_before(tag, release)
    assets = []
    content = {}
    for asset in release["assets"]:
        name = safe_path(asset["name"])
        if "/" in name or name in content or asset["state"] != "uploaded":
            raise RepairError("Invalid or duplicate existing asset")
        data = api.download(asset["id"])
        sha256 = digest(data)
        if len(data) != asset["size"] or asset.get("digest") not in {
            None,
            "sha256:" + sha256,
        }:
            raise RepairError(f"Existing release asset digest/size mismatch: {name}")
        assets.append(
            {
                "id": asset["id"],
                "name": name,
                "size": len(data),
                "sha256": sha256,
                "state": asset["state"],
            }
        )
        content[name] = data
    baseline_names = set(asset_names(tag)) if tag in REUSED_TAGS else set()
    if not baseline_names.issubset(content):
        raise RepairError("Historical existing assets are missing")
    return (
        {key: release[key] for key in RELEASE_STATE_FIELDS},
        sorted(assets, key=lambda asset: asset["name"]),
        content,
    )


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RepairError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_bytes(), object_pairs_hook=_unique_json_object)


def validate_utc_timestamp(value: Any, description: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
    ):
        raise RepairError(f"{description} requires a UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise RepairError(f"{description} timestamp is invalid") from error


def validate_release_observation(value: Any, tag: str) -> None:
    if (
        tag != DRAFT_TAG
        or not isinstance(value, dict)
        or set(value)
        != {
            "schemaVersion",
            "repository",
            "method",
            "endpoint",
            "observedAt",
            "provenance",
            "releaseBefore",
            "assetsBefore",
        }
    ):
        raise RepairError("Invalid or unsupported draft release observation fields")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["repository"] != REPOSITORY
        or value["method"] != "GET"
        or value["endpoint"] != DRAFT_ENDPOINT
        or value["provenance"] != "operator-authenticated-get"
    ):
        raise RepairError("Draft release observation identity/provenance mismatch")
    validate_utc_timestamp(value["observedAt"], "Draft release observation capture")
    release = value["releaseBefore"]
    if not isinstance(release, dict) or set(release) != set(RELEASE_STATE_FIELDS):
        raise RepairError(
            "Draft release observation must contain exactly seven API fields"
        )
    if (
        type(release["id"]) is not int
        or not isinstance(release["updated_at"], str)
        or any(
            release[key] is not None and not isinstance(release[key], str)
            for key in ("published_at", "body")
        )
    ):
        raise RepairError("Invalid draft release observation API field types")
    validate_release_before(tag, release)
    if (
        release["draft"] is not True
        or type(value["assetsBefore"]) is not list
        or value["assetsBefore"]
    ):
        raise RepairError("Observation is limited to the known empty draft")


def read_release_observation(path: Path, tag: str) -> dict[str, Any]:
    observation = read_json_file(path)
    validate_release_observation(observation, tag)
    return observation


def observe_draft(output: Path, *, api: Any = None) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise RepairError("Refusing preexisting draft observation output file")
    release = (api or PublicAPI()).get(DRAFT_ENDPOINT)
    if (
        not isinstance(release, dict)
        or not set(RELEASE_STATE_FIELDS).issubset(release)
        or type(release.get("assets")) is not list
        or release["assets"]
    ):
        raise RepairError("Capture is limited to the known empty draft metadata")
    observation: dict[str, Any] = {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        "method": "GET",
        "endpoint": DRAFT_ENDPOINT,
        "observedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provenance": "operator-authenticated-get",
        "releaseBefore": {key: release[key] for key in RELEASE_STATE_FIELDS},
        "assetsBefore": [],
    }
    validate_release_observation(observation, DRAFT_TAG)
    with output.open("xb") as stream:
        stream.write(json_bytes(observation))
    return observation


def powershell_paths(recipe: str, variable: str) -> list[str]:
    match = re.search(r"\$" + variable + r"\s*=\s*@\((.*?)\)", recipe, re.S)
    return re.findall(r'"([^"\r\n]+)"', match.group(1)) if match else []


def package_sources(
    root: Path, tag: str, source: dict[str, tuple[str, bytes]]
) -> dict[str, tuple[str, bytes]]:
    if tag not in {"v2.8.0", "v2.11.0"}:
        return dict(source)
    recipe = source[BUILDER][1].decode("utf-8-sig")
    state = json.loads(source["starter-kit-manifest.json"][1])
    paths = (
        {record["path"] for record in state["files"]}
        | set(RULE_FILES)
        | {PROVENANCE, "starter-kit-manifest.json"}
    )
    excluded = set(powershell_paths(recipe, "StarterOnlyPaths"))
    prefixes = tuple(powershell_paths(recipe, "StarterOnlyPrefixes"))
    selected = {
        path: source[path]
        for path in paths
        if path not in excluded and not path.startswith(prefixes)
    }
    if tag == "v2.11.0":
        for path, entry in source.items():
            if path.startswith("templates/project/"):
                selected[path.removeprefix("templates/project/")] = entry
    return selected


def validate_provenance(
    files: dict[str, bytes],
    tag: str,
    commit: str,
    rules: dict[str, bytes],
    upstream: dict[str, Any],
) -> None:
    provenance = json.loads(files[PROVENANCE])
    starter = provenance["starterKit"]
    if starter["ref"] != tag or starter["commit"] != commit:
        raise RepairError("Archive starter source provenance mismatch")
    agent = provenance["agentRules"]
    if (
        agent["repository"].removeprefix("https://github.com/").removesuffix(".git")
        != RULES_REPOSITORY
        or agent["ref"] != upstream["ref"]
        or agent["commit"] != upstream["commit"]
        or set(agent["files"]) != set(rules)
    ):
        raise RepairError("Archive rules provenance mismatch")
    for path, content in rules.items():
        if path not in files or files[path].replace(b"\r\n", b"\n") != content.replace(
            b"\r\n", b"\n"
        ):
            raise RepairError(
                f"Archive rule differs from immutable public blob: {path}"
            )


def inspect_package(
    root: Path,
    tag: str,
    content: bytes,
    rules: dict[str, bytes],
    upstream: dict[str, Any],
) -> dict[str, Any]:
    identity = tag_identity(root, tag)
    source = source_files(root, identity["commit"])
    files = read_archive(content)
    validate_provenance(files, tag, identity["commit"], rules, upstream)
    omissions = validate_inventory(files, tag)
    if tag == "v2.1.0" and len(omissions) != 22:
        raise RepairError(
            "v2.1.0 must preserve precisely its 22 historical hidden inventory omissions"
        )
    expected = package_sources(root, tag, source)
    generated: dict[str, dict[str, Any]] = {
        PROVENANCE: {
            "kind": "generated",
            "recipe": BUILDER,
            "operation": "source/rules provenance",
        },
    }
    if INVENTORY in files:
        generated[INVENTORY] = {
            "kind": "generated",
            "recipe": BUILDER,
            "operation": "package file inventory",
        }
    for path, data in rules.items():
        generated[path] = {
            "kind": "upstream",
            "repository": RULES_REPOSITORY,
            "commit": upstream["commit"],
            "path": path,
            "blob": upstream["blobs"][path],
        }
        expected.pop(path, None)
        if files[path].replace(b"\r\n", b"\n") != data.replace(b"\r\n", b"\n"):
            raise RepairError(f"Rule overlay mismatch: {path}")
    if "starter-kit-manifest.json" in files and tag in {"v2.8.0", "v2.11.0"}:
        generated["starter-kit-manifest.json"] = {
            "kind": "generated",
            "recipe": BUILDER,
            "operation": "consumer inventory rebase",
        }
        state = json.loads(files["starter-kit-manifest.json"])
        original_state = json.loads(source["starter-kit-manifest.json"][1])
        if {key: value for key, value in state.items() if key != "files"} != {
            key: value for key, value in original_state.items() if key != "files"
        }:
            raise RepairError("Consumer state source metadata mismatch")
    if tag == "v2.11.0":
        config_path = ".starter-kit-project.json"
        configuration = json.loads(files[config_path])
        if configuration != {
            "schemaVersion": 1,
            "repositoryRole": "project",
            "releaseKind": "repository",
            "automations": {
                "agentRulesSync": False,
                "guardedMerge": False,
                "releasePreflight": False,
            },
            "checks": [],
        }:
            raise RepairError("Historical generated project configuration mismatch")
        generated[config_path] = {
            "kind": "generated",
            "recipe": "tools/project_config.py",
            "operation": "default project configuration",
        }
        document = "docs/repository-files.md"
        header = source["templates/project/" + document][1].decode().rstrip()
        validate_inventory_document(files, header)
        generated[document] = {
            "kind": "generated",
            "recipe": BUILDER,
            "operation": "template plus exhaustive package paths",
        }
    for path in generated:
        expected.pop(path, None)
    records = map_source_files(files, expected, generated)
    validate_archive_modes(content, records)
    if tag in {"v2.8.0", "v2.11.0"}:
        validate_consumer_inventory(
            files, tag, {record["path"]: record["mode"] for record in records}
        )
    for record in records:
        template_path = "templates/project/" + record["path"]
        if (
            tag == "v2.11.0"
            and record["source"]["kind"] == "git"
            and template_path in source
        ):
            record["source"]["path"] = template_path
    if INVENTORY in files:
        modes = {
            record["path"]: record.get("mode", "100644")
            for record in json.loads(files[INVENTORY])["files"]
        }
        for record in records:
            if record["path"] in modes and modes[record["path"]] != record["mode"]:
                raise RepairError(f"Git mode mismatch in inventory: {record['path']}")
    return {
        "files": records,
        "internalInventoryOmissions": omissions,
        "upstream": upstream,
    }


def toolkit_sources(
    source: dict[str, tuple[str, bytes]],
) -> dict[str, tuple[str, bytes]]:
    expected = {"starter-kit-upgrade.py": source["tools/starter-kit-upgrade.py"]}
    for path, entry in source.items():
        if path.startswith("tools/starter_kit_upgrade/") and path.endswith(".py"):
            expected[path.removeprefix("tools/")] = entry
    archive_recipe = source.get("tools/starter_kit_upgrade/archive.py", ("", b""))[1]
    if b'package_members["process_runner.py"]' in archive_recipe:
        expected["process_runner.py"] = source["tools/process_runner.py"]
    return expected


def inspect_toolkit(
    root: Path, tag: str, content: bytes, package_name: str, package: bytes
) -> dict[str, Any]:
    files = read_archive(content)
    nested = f"packages/{package_name}"
    if files.get(nested) != package:
        raise RepairError("Toolkit nested ZIP byte identity mismatch")
    source = source_files(root, TAGS[tag])
    expected = toolkit_sources(source)
    recipe_path = (
        "tools/starter-kit-upgrade.py"
        if tag in {"v2.1.0", "v2.2.0"}
        else "tools/starter_kit_upgrade/archive.py"
    )
    # Python normalizes source newlines before encoding this literal into the ZIP.
    template = re.search(
        rb'^    readme = f"""(.*?)"""',
        source[recipe_path][1].replace(b"\r\n", b"\n"),
        re.M | re.S,
    )
    if template is None:
        raise RepairError("Historical toolkit README template is missing")
    readme = template[1].replace(b"{package_path.name}", package_name.encode())
    if files.get("README.md") != readme:
        raise RepairError("Toolkit generated README differs from historical recipe")
    generated = {
        nested: {"kind": "nested-archive", "name": package_name},
        "README.md": {
            "kind": "generated",
            "recipe": recipe_path,
            "operation": "toolkit instructions",
        },
    }
    records = map_source_files(files, expected, generated)
    validate_archive_modes(content, records)
    for record in records:
        if record["source"]["kind"] == "git":
            record["source"]["path"] = "tools/" + record["path"]
    return {"files": records, "nestedArchive": nested}


def tokenless_environment(work: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("GH_", "GITHUB_", "GIT_", "ACTIONS_"))
        and not any(
            word in key.upper()
            for word in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
        )
    }
    home = work / "home"
    home.mkdir()
    config = home / "gitconfig"
    config.write_text(
        '[credential]\n\thelper =\n[core]\n\tautocrlf = false\n[protocol "file"]\n\tallow = always\n',
        encoding="utf-8",
    )
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "GH_CONFIG_DIR": str(home / "gh"),
            "XDG_CONFIG_HOME": str(home),
            "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": str(work),
            "TMP": str(work),
            "TMPDIR": str(work),
        }
    )
    return environment


def run_recipe(command: list[str], environment: dict[str, str], work: Path) -> None:
    try:
        with git_objects.process_runner.ProcessScope(
            command,
            timeout=600,
            cwd=work,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as scope:
            try:
                stdout, stderr = scope.process.communicate(
                    timeout=scope.work_remaining()
                )
            except subprocess.TimeoutExpired:
                scope.expired.set()
                scope.terminate()
                raise RepairError(
                    "Historical recipe exceeded its 600s deadline"
                ) from None
            if scope.expired.is_set() or scope.process.returncode:
                raise RepairError(
                    "Historical recipe failed: "
                    + (stderr + stdout).decode("utf-8", errors="replace")[-6000:]
                )
    except OSError as error:
        raise RepairError(f"Unable to execute historical recipe: {error}") from error


def write_archive(path: Path, files: dict[str, bytes], modes: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (
                int("100755" if modes.get(name) == "100755" else "100644", 8) << 16
            )
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)


def recompose_package(
    path: Path, tag: str, rules: dict[str, bytes], source: dict[str, tuple[str, bytes]]
) -> list[dict[str, Any]]:
    original = read_archive(path.read_bytes())
    files = dict(original)
    modes = {name: mode for name, (mode, _) in source.items()}
    files.update(rules)
    provenance = json.loads(files[PROVENANCE])
    provenance.pop("preservedFiles", None)
    agent = provenance["agentRules"]
    agent.update(
        {
            "repository": f"https://github.com/{RULES_REPOSITORY}",
            "requestedRef": RULES_REF,
            "ref": RULES_REF,
            "commit": RULES_COMMIT,
            "files": list(RULE_FILES),
            "fileHashes": {
                name: digest(canonical(content)) for name, content in rules.items()
            },
        }
    )
    files[PROVENANCE] = json_bytes(provenance)
    prior_inventory = json.loads(files[INVENTORY]) if INVENTORY in files else None
    prior_records = (
        {record["path"]: record for record in prior_inventory["files"]}
        if prior_inventory
        else {}
    )

    def file_record(name: str, prior: dict[str, Any] | None = None) -> dict[str, Any]:
        record = dict(prior or {})
        record.update(
            {
                "path": name,
                "sha256": digest(files[name]),
                "mode": modes.get(name, "100644"),
            }
        )
        if prior_inventory is None or prior_inventory.get("schemaVersion", 1) >= 2:
            normalized = canonical(files[name])
            try:
                files[name].decode("utf-8")
                kind = "text"
            except UnicodeDecodeError:
                kind = "binary"
            record.update({"canonicalSha256": digest(normalized), "contentKind": kind})
        if "strategy" not in record:
            record["strategy"] = (
                "agent-rules"
                if tag in {"v2.8.0", "v2.11.0"} and name in {*RULE_FILES, PROVENANCE}
                else "replace"
            )
        return record

    if tag in {"v2.8.0", "v2.11.0"}:
        state_path = "starter-kit-manifest.json"
        state = json.loads(files[state_path])
        prior_state = {record["path"]: record for record in state["files"]}
        state["files"] = [
            file_record(name, prior_state.get(name))
            for name in sorted(files)
            if name not in {*RULE_FILES, PROVENANCE, INVENTORY, state_path}
        ]
        files[state_path] = json_bytes(state)
    if prior_inventory:
        prior_inventory["files"] = [
            file_record(name, prior_records.get(name))
            for name in sorted(files)
            if name != INVENTORY
        ]
        prior_inventory["agentRules"].update({"ref": RULES_REF, "commit": RULES_COMMIT})
        files[INVENTORY] = json_bytes(prior_inventory)
    transformations = [
        {
            "path": name,
            "beforeSha256": digest(original[name]) if name in original else None,
            "afterSha256": digest(content),
            "operation": "immutable public rule overlay"
            if name in RULE_FILES
            else "regenerate dependent provenance/inventory",
        }
        for name, content in sorted(files.items())
        if original.get(name) != content
    ]
    write_archive(path, files, modes)
    transformations.append(
        {
            "operation": "repack final enriched ZIP with Git modes, sorted paths and fixed ZIP timestamps"
        }
    )
    return transformations


def build_archives(
    root: Path,
    tag: str,
    output: Path,
    rules: dict[str, bytes],
    upstream: dict[str, Any],
) -> list[dict[str, Any]]:
    # Old builders nest another clone below TEMP; deep bundle paths exceed Windows limits.
    with tempfile.TemporaryDirectory(prefix="hr-", dir=root) as temporary:
        work = Path(temporary)
        environment = tokenless_environment(work)
        checkout = work / "git-starter-kit"
        git_program = git_objects.git_executable()
        run(
            [
                git_program,
                "clone",
                "--no-local",
                "--no-checkout",
                str(root),
                str(checkout),
            ],
            env=environment,
        )
        run(
            [
                git_program,
                "-C",
                str(checkout),
                "remote",
                "set-url",
                "origin",
                f"https://github.com/{REPOSITORY}.git",
            ],
            env=environment,
        )
        run(
            [git_program, "-C", str(checkout), "checkout", "--detach", TAGS[tag]],
            env=environment,
        )
        source = source_files(root, TAGS[tag])
        if tag in {"v1.7.3", "v2.2.0"}:
            mirror = work / "rules.git"
            run(
                [
                    git_program,
                    "clone",
                    "--bare",
                    "--depth",
                    "1",
                    "--branch",
                    RULES_REF,
                    f"https://github.com/{RULES_REPOSITORY}.git",
                    str(mirror),
                ],
                env=environment,
                timeout=180,
            )
            mirror_commit = (
                run(
                    [
                        git_program,
                        "-C",
                        str(mirror),
                        "rev-parse",
                        f"refs/tags/{RULES_REF}^{{commit}}",
                    ],
                    env=environment,
                )
                .decode()
                .strip()
            )
            if mirror_commit != upstream["commit"]:
                raise RepairError("Public rules mirror object mismatch")
            for name, content in rules.items():
                if (
                    run(
                        [
                            git_program,
                            "-C",
                            str(mirror),
                            "show",
                            f"{RULES_COMMIT}:{name}",
                        ],
                        env=environment,
                    )
                    != content
                ):
                    raise RepairError(f"Rules mirror blob mismatch: {name}")
            run(
                [
                    git_program,
                    "config",
                    "--file",
                    environment["GIT_CONFIG_GLOBAL"],
                    f"url.{mirror.as_uri()}.insteadOf",
                    f"https://github.com/{RULES_REPOSITORY}.git",
                ],
                env=environment,
            )
        elif tag == "v2.11.0":
            # The unchanged builder performs its own tokenless latest/ref/object/blob checks.
            tracked = json.loads(source[PROVENANCE][1])["agentRules"]
            if tracked["ref"] != RULES_REF or tracked["commit"] != RULES_COMMIT:
                raise RepairError("Historical recipe tracked upstream pin mismatch")
        package = output / asset_names(tag)[0]
        command = [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(checkout / BUILDER),
            "-RepositoryRoot",
            str(checkout),
            "-OutputDirectory",
            str(output),
            "-AgentRulesRef",
            RULES_REF,
            "-PackageName",
            package.name,
        ]
        if tag == "v1.7.3":
            command.extend(["-StarterRef", tag])
        else:
            command.extend(
                [
                    "-RepositoryRef",
                    tag,
                    "-RepositorySlug",
                    REPOSITORY,
                    "-StarterKitRef",
                    tag,
                    "-StarterKitCommit",
                    TAGS[tag],
                ]
            )
        run_recipe(command, environment, work)
        transformations = recompose_package(package, tag, rules, source)
        if tag != "v1.7.3":
            toolkit = output / asset_names(tag)[1]
            run_recipe(
                [
                    sys.executable,
                    "-B",
                    str(checkout / "tools/starter-kit-upgrade.py"),
                    "toolkit",
                    "--new-package",
                    str(package),
                    "--output",
                    str(toolkit),
                ],
                environment,
                work,
            )
        return transformations


def recipe_records(source: dict[str, tuple[str, bytes]]) -> list[dict[str, Any]]:
    paths = [
        path
        for path in source
        if path == BUILDER
        or path == ".github/workflows/release-package.yml"
        or path == "tools/starter-kit-upgrade.py"
        or path.startswith("tools/starter_kit_upgrade/")
    ]
    return [
        {"path": path, "sha256": digest(source[path][1]), "mode": source[path][0]}
        for path in sorted(paths)
    ]


def build_proof(
    root: Path,
    tag: str,
    archives: dict[str, bytes],
    upstream: dict[str, Any],
    rules: dict[str, bytes],
    transformations: list[dict[str, Any]],
    identity: dict[str, Any],
    run_identity: dict[str, Any] | None,
    release_observation: dict[str, Any] | None = None,
    prepared_at: str | None = None,
) -> dict[str, Any]:
    if release_observation is not None:
        validate_release_observation(release_observation, tag)
    if prepared_at is not None:
        validate_utc_timestamp(prepared_at, "Release preparation")
    package_name = asset_names(tag)[0]
    package = archives[package_name]
    validate_transformations(tag, transformations, read_archive(package))
    proof_archives = []
    for name, content in sorted(archives.items()):
        if not name.endswith(".zip"):
            continue
        inspection = (
            inspect_package(root, tag, content, rules, upstream)
            if name == package_name
            else inspect_toolkit(root, tag, content, package_name, package)
        )
        proof_archives.append(
            {
                "name": name,
                "size": len(content),
                "sha256": digest(content),
                **inspection,
            }
        )
    if "SHA256SUMS" in archives:
        validate_checksums(
            archives["SHA256SUMS"],
            {name: data for name, data in archives.items() if name.endswith(".zip")},
        )
    proof = {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        **identity,
        "qualification": run_identity,
        "originalFailedRunId": FAILED_RUNS.get(tag),
        "recipe": recipe_records(source_files(root, TAGS[tag])),
        "upstream": upstream,
        "transformations": transformations,
        "archives": proof_archives,
        "provenance": "Existing asset bytes preserved"
        if tag in REUSED_TAGS
        else "Historical source recipe executed again; these new bytes are not a reconstruction of the original missing assets",
        "publication": {"draft": False, "prerelease": False, "make_latest": False},
    }
    if release_observation is not None:
        proof["releaseObservation"] = release_observation
    if prepared_at is not None:
        proof["preparedAt"] = prepared_at
    return proof


def notes_body(
    tag: str, previous: str | None, names: list[str], *, prepared_at: str | None = None
) -> str:
    if prepared_at is not None:
        validate_utc_timestamp(prepared_at, "Release preparation")
    failed = FAILED_RUNS.get(tag)
    text = (
        "## Historical release repair\n\n"
        + (f"Prepared: {prepared_at}\n\n" if prepared_at is not None else "")
        + f"Source: `{tag}` at `{TAGS[tag]}`.\n\n"
        + (
            "Existing release ZIP bytes and asset identities were preserved.\n\n"
            if tag in REUSED_TAGS
            else "Missing assets were built with the historical source recipe and explicitly recorded immutable rules overlays. "
            "These bytes do not claim to reproduce an original missing archive.\n\n"
        )
        + "`historical-repair-proof.json` records source, upstream, recipe, transformations, exhaustive archive inventories, "
        "and qualification run identity. Publication is a separate operation; no future outcome is asserted.\n\n"
    )
    if tag == "v2.1.0":
        text += "The supplemental proof covers historical hidden paths omitted from the embedded inventory; all existing embedded records were verified.\n\n"
    if failed:
        text += f"Original automatic package run [{failed}](https://github.com/{REPOSITORY}/actions/runs/{failed}) remains failed; this repair does not change that evidence.\n\n"
    text += "Assets: " + ", ".join(f"`{name}`" for name in names + [PROOF]) + ".\n"
    return ((previous.rstrip() + "\n\n") if previous else "") + text


def prepare(
    root: Path,
    tag: str,
    output: Path,
    *,
    api: Any = None,
    draft_release_snapshot: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    if output.exists():
        raise RepairError("Refusing preexisting output directory")
    release_observation = (
        read_release_observation(draft_release_snapshot, tag)
        if draft_release_snapshot is not None
        else None
    )
    identity = tag_identity(root, tag)
    api = api or PublicAPI()
    if release_observation is None:
        release, existing, retained = release_snapshot(api, tag)
    else:
        release = release_observation["releaseBefore"]
        existing = []
        retained = {}
    if PROOF in retained:
        raise RepairError(
            "Release already has a historical repair proof; use its sealed original candidate"
        )
    latest = api.get(f"repos/{REPOSITORY}/releases/latest")
    latest_before = {"id": latest["id"], "tag": latest["tag_name"]}
    names = asset_names(tag)
    if set(retained) - set(names):
        raise RepairError("Unexpected existing release asset names")
    if tag not in REUSED_TAGS and any(name.endswith(".zip") for name in retained):
        raise RepairError("Refusing to rebuild a release with preexisting ZIP assets")
    run_identity = qualification()
    prepared_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if tag in REUSED_TAGS:
        provenance = json.loads(read_archive(retained[names[0]])[PROVENANCE])[
            "agentRules"
        ]
        upstream, rules = public_rules(
            api, provenance["ref"], provenance["commit"], provenance["files"]
        )
    else:
        upstream, rules = public_rules(api, RULES_REF, RULES_COMMIT, list(RULE_FILES))
    output.mkdir(parents=True)
    payload = output / "payload"
    payload.mkdir()
    retained_root = output / "retained"
    if retained:
        retained_root.mkdir()
        for name, content in retained.items():
            (retained_root / name).write_bytes(content)
    transformations = []
    if tag not in REUSED_TAGS:
        transformations = build_archives(root, tag, payload, rules, upstream)
    archives = dict(retained)
    archives.update({path.name: path.read_bytes() for path in payload.iterdir()})
    if "SHA256SUMS" in names and "SHA256SUMS" not in archives:
        sums = b"".join(
            f"{digest(archives[name])}  {name}\n".encode()
            for name in sorted(names)
            if name.endswith(".zip")
        )
        (payload / "SHA256SUMS").write_bytes(sums)
        archives["SHA256SUMS"] = sums
    proof = build_proof(
        root,
        tag,
        archives,
        upstream,
        rules,
        transformations,
        identity,
        run_identity,
        release_observation=release_observation,
        prepared_at=prepared_at,
    )
    (payload / PROOF).write_bytes(json_bytes(proof))
    candidate = {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        **identity,
        "qualification": run_identity,
        "preparedAt": prepared_at,
        "releaseBefore": release,
        "assetsBefore": existing,
        "latestBefore": latest_before,
        "notes": notes_body(
            tag, release["body"] if release else None, names, prepared_at=prepared_at
        ),
        "payload": [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": digest(path.read_bytes()),
            }
            for path in sorted(payload.iterdir())
        ],
    }
    if release_observation is not None:
        candidate["releaseObservation"] = release_observation
    (output / "candidate.json").write_bytes(json_bytes(candidate))
    verify(root, output, api=api)
    return candidate


def regular_files(directory: Path, names: set[str]) -> dict[str, bytes]:
    if directory.is_symlink() or not directory.is_dir():
        raise RepairError(f"Expected regular directory: {directory}")
    paths = list(directory.iterdir())
    if {path.name for path in paths} != names:
        raise RepairError(f"Unexpected bundle file coverage: {directory.name}")
    result = {}
    for path in paths:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RepairError(f"Bundle file must be regular: {path.name}")
        result[path.name] = path.read_bytes()
    return result


def verify(root: Path, bundle: Path, *, api: Any = None) -> dict[str, Any]:
    if bundle.is_symlink() or (bundle / "candidate.json").is_symlink():
        raise RepairError("Bundle/candidate must not be a symlink")
    candidate = read_json_file(bundle / "candidate.json")
    if candidate["schemaVersion"] != 1 or candidate["repository"] != REPOSITORY:
        raise RepairError("Candidate schema/repository mismatch")
    tag = candidate["tag"]
    prepared_at = candidate.get("preparedAt")
    if "preparedAt" in candidate:
        validate_utc_timestamp(prepared_at, "Release preparation")
    elif candidate.get("qualification") is not None:
        raise RepairError("Qualified candidate requires a preparation timestamp")
    release_observation = candidate.get("releaseObservation")
    if "releaseObservation" in candidate:
        validate_release_observation(release_observation, tag)
        if json_bytes(release_observation["releaseBefore"]) != json_bytes(
            candidate["releaseBefore"]
        ) or json_bytes(release_observation["assetsBefore"]) != json_bytes(
            candidate["assetsBefore"]
        ):
            raise RepairError(
                "Candidate state differs from the operator draft observation"
            )
    validate_release_before(tag, candidate["releaseBefore"])
    identity = tag_identity(root, tag)
    if any(candidate[key] != value for key, value in identity.items()):
        raise RepairError("Candidate source/tag/tree identity changed")
    if {path.name for path in bundle.iterdir()} - {
        "candidate.json",
        "payload",
        "retained",
    }:
        raise RepairError("Unexpected bundle paths")
    expected_names = set(asset_names(tag)) | {PROOF}
    before = candidate["assetsBefore"]
    if len({asset["name"] for asset in before}) != len(before) or len(
        {asset["id"] for asset in before}
    ) != len(before):
        raise RepairError("Duplicate existing asset identity")
    retained_names = {asset["name"] for asset in before}
    payload_records = candidate["payload"]
    payload_names = {record["name"] for record in payload_records}
    if (
        len(payload_names) != len(payload_records)
        or payload_names & retained_names
        or payload_names != expected_names - retained_names
    ):
        raise RepairError("Candidate payload coverage mismatch")
    for name in payload_names | retained_names:
        if safe_path(name) != name or "/" in name:
            raise RepairError("Unsafe asset name")
    payload = regular_files(bundle / "payload", payload_names)
    for record in payload_records:
        content = payload[record["name"]]
        if len(content) != record["size"] or digest(content) != record["sha256"]:
            raise RepairError(f"Payload digest mismatch: {record['name']}")
    api = api or PublicAPI()
    retained = (
        regular_files(bundle / "retained", retained_names)
        if (bundle / "retained").exists()
        else {record["name"]: api.download(record["id"]) for record in before}
    )
    for record in before:
        content = retained[record["name"]]
        if (
            len(content) != record["size"]
            or digest(content) != record["sha256"]
            or record["state"] != "uploaded"
        ):
            raise RepairError("Retained asset digest/identity mismatch")
    archives = {**retained, **payload}
    archives.pop(PROOF)
    proof = json.loads(payload[PROOF], object_pairs_hook=_unique_json_object)
    if "releaseObservation" in proof:
        validate_release_observation(proof["releaseObservation"], tag)
    if "preparedAt" in proof:
        validate_utc_timestamp(proof["preparedAt"], "Release preparation")
    if tag in REUSED_TAGS:
        agent = json.loads(read_archive(archives[asset_names(tag)[0]])[PROVENANCE])[
            "agentRules"
        ]
        upstream, rules = public_rules(
            api, agent["ref"], agent["commit"], agent["files"]
        )
    else:
        upstream, rules = public_rules(api, RULES_REF, RULES_COMMIT, list(RULE_FILES))
    rebuilt = build_proof(
        root,
        tag,
        archives,
        upstream,
        rules,
        proof["transformations"],
        identity,
        candidate["qualification"],
        release_observation=release_observation,
        prepared_at=prepared_at,
    )
    if proof != rebuilt:
        raise RepairError("Historical repair proof source/inventory mismatch")
    if candidate["notes"] != notes_body(
        tag,
        candidate["releaseBefore"]["body"] if candidate["releaseBefore"] else None,
        asset_names(tag),
        prepared_at=prepared_at,
    ):
        raise RepairError("Candidate final notes mismatch")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--repository-root", type=Path, required=True)
    prepare_parser.add_argument("--tag", choices=sorted(TAGS), required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    prepare_parser.add_argument("--draft-release-snapshot", type=Path)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--repository-root", type=Path, required=True)
    verify_parser.add_argument("--bundle-dir", type=Path, required=True)
    observe_parser = commands.add_parser("observe-draft")
    observe_parser.add_argument("--output-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "observe-draft":
            observation = observe_draft(args.output_file)
            print(
                json.dumps({"tag": DRAFT_TAG, "observedAt": observation["observedAt"]})
            )
            return 0
        if args.command == "prepare":
            candidate = prepare(
                args.repository_root,
                args.tag,
                args.output_dir,
                draft_release_snapshot=args.draft_release_snapshot,
            )
        else:
            candidate = verify(args.repository_root, args.bundle_dir)
        print(
            json.dumps(
                {
                    "tag": candidate["tag"],
                    "payload": candidate["payload"],
                    "qualification": candidate["qualification"],
                }
            )
        )
        return 0
    except (RepairError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Historical repair rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
