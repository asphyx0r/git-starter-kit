#!/usr/bin/env python3
"""Install pinned quality tools into an explicit new CI or local root."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import hmac
import http.client
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit


SCHEMA_VERSION = 2
TOOL_NAMES = ("actionlint", "shfmt", "PSScriptAnalyzer", "shellcheck", "gitleaks")
PLATFORM_NAMES = frozenset(("linux-x64", "windows-x64"))
ARTIFACT_TYPES = frozenset(("tar.gz", "tar.xz", "binary", "zip"))
DOWNLOAD_TIMEOUT_SECONDS = 60
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
PROBE_TIMEOUT_SECONDS = 15
DIAGNOSTIC_LIMIT = 2_000
USER_AGENT = "quality-tools/1"
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
WINDOWS_RESERVED_NAMES = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$",
    re.IGNORECASE,
)
REGISTRY_KEYS = frozenset(("schemaVersion", "python", "node", "external", "policy"))
POLICY_KEYS = frozenset(
    (
        "coverageFailUnder",
        "nodeCiVersion",
        "nodeMinimum",
        "npmIgnoreScripts",
        "pythonRequireHashes",
    )
)
RECORD_KEYS = frozenset(
    ("version", "platforms", "url", "sha256", "artifactType", "install", "probe")
)
VARIANT_KEYS = frozenset(("url", "sha256", "artifactType", "install"))
PSSA_PROBE_SCRIPT = """$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion -lt [version]'7.4.6') {
  throw 'PowerShell 7.4.6 or newer is required.'
}
$modulePath = [IO.Path]::GetFullPath($env:QUALITY_PSSA_MODULE_PATH)
$manifestPath = Join-Path $modulePath 'PSScriptAnalyzer.psd1'
Remove-Module PSScriptAnalyzer -Force -ErrorAction SilentlyContinue
Import-Module $manifestPath -RequiredVersion 1.25.0 -Force -ErrorAction Stop
$module = Get-Module PSScriptAnalyzer
if ([IO.Path]::GetFullPath($module.ModuleBase) -ne $modulePath) {
  throw 'PSScriptAnalyzer was imported outside the staging root.'
}
$null = Invoke-ScriptAnalyzer -ScriptDefinition '$value = 1' -ErrorAction Stop
$module.Version.ToString()
"""
DOWNLOAD_WORKER_SCRIPT = """import importlib.util, json, pathlib, sys
spec = importlib.util.spec_from_file_location('quality_download_worker', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    module._download(sys.argv[2], json.loads(sys.argv[3]), pathlib.Path(sys.argv[4]),
                     module._safe_urlopen)
except module.InstallerError as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
"""


class InstallerError(Exception):
    """A safe, user-facing external-tool installation failure."""


def _require_exact_keys(
    value: object,
    expected: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InstallerError(f"{label}: expected an object")
    missing = sorted(expected - set(value))
    if missing:
        raise InstallerError(f"{label}: missing key {missing[0]}")
    unexpected = sorted(set(value) - expected)
    if unexpected:
        raise InstallerError(f"{label}: unexpected key {unexpected[0]}")
    return value


def _validate_https_url(url: object) -> str:
    if (
        not isinstance(url, str)
        or not url
        or any(ord(character) < 32 for character in url)
    ):
        raise InstallerError("unsafe URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise InstallerError("unsafe URL") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port is not None
        and not 1 <= port <= 65535
    ):
        raise InstallerError("unsafe URL")
    return url


def _normalized_member_name(name: object) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\0" in name or "\\" in name:
        raise InstallerError(f"unsafe archive entry: {name!r}")
    stripped = name[:-1] if name.endswith("/") else name
    components = stripped.split("/")
    if (
        not stripped
        or name.startswith("/")
        or WINDOWS_DRIVE_PATTERN.match(stripped)
        or any(component in ("", ".", "..") for component in components)
        or any(
            ":" in component
            or component.endswith((" ", "."))
            or WINDOWS_RESERVED_NAMES.match(component)
            for component in components
        )
    ):
        raise InstallerError(f"unsafe archive entry: {name!r}")
    return PurePosixPath(*components)


def _validate_archive_layout(
    entries: Iterable[tuple[str, bool]],
) -> list[PurePosixPath]:
    paths: list[PurePosixPath] = []
    kinds: list[bool] = []
    seen: set[str] = set()
    for name, is_directory in entries:
        path = _normalized_member_name(name)
        normalized = path.as_posix().casefold()
        if normalized in seen:
            raise InstallerError(f"unsafe archive entry: duplicate {name!r}")
        seen.add(normalized)
        paths.append(path)
        kinds.append(is_directory)
    for index, path in enumerate(paths):
        if kinds[index]:
            continue
        prefix = path.as_posix().casefold() + "/"
        if any(
            other.as_posix().casefold().startswith(prefix)
            for other_index, other in enumerate(paths)
            if other_index != index
        ):
            raise InstallerError(
                f"unsafe archive entry: file is a parent {path.as_posix()!r}"
            )
    return paths


def _validate_member_names(names: Iterable[str]) -> list[PurePosixPath]:
    return _validate_archive_layout((name, False) for name in names)


def _validate_tar_members(
    members: Iterable[tarfile.TarInfo],
) -> list[tuple[tarfile.TarInfo, PurePosixPath, bool]]:
    classified: list[tuple[tarfile.TarInfo, bool]] = []
    total_size = 0
    for member in members:
        if len(classified) >= MAX_ARCHIVE_MEMBERS:
            raise InstallerError("unsafe archive entry: archive member limit exceeded")
        total_size += member.size
        if member.size < 0 or total_size > MAX_EXTRACTED_BYTES:
            raise InstallerError("unsafe archive entry: archive size limit exceeded")
        if member.isfile():
            classified.append((member, False))
        elif member.isdir():
            classified.append((member, True))
        else:
            raise InstallerError(f"unsafe archive entry: {member.name!r}")
    paths = _validate_archive_layout(
        (member.name, is_directory) for member, is_directory in classified
    )
    return [
        (member, path, is_directory)
        for (member, is_directory), path in zip(classified, paths, strict=True)
    ]


def _validate_zip_members(
    members: Iterable[zipfile.ZipInfo],
) -> list[tuple[zipfile.ZipInfo, PurePosixPath, bool]]:
    classified: list[tuple[zipfile.ZipInfo, bool]] = []
    total_size = 0
    for member in members:
        if len(classified) >= MAX_ARCHIVE_MEMBERS:
            raise InstallerError("unsafe archive entry: archive member limit exceeded")
        total_size += member.file_size
        if member.file_size < 0 or total_size > MAX_EXTRACTED_BYTES:
            raise InstallerError("unsafe archive entry: archive size limit exceeded")
        if member.flag_bits & 1:
            raise InstallerError(f"unsafe archive entry: {member.filename!r}")
        unix_type = stat.S_IFMT(member.external_attr >> 16)
        dos_directory = bool(member.external_attr & 0x10)
        is_directory = member.is_dir() or dos_directory
        expected_type = stat.S_IFDIR if is_directory else stat.S_IFREG
        if unix_type not in (0, expected_type):
            raise InstallerError(f"unsafe archive entry: {member.filename!r}")
        classified.append((member, is_directory))
    paths = _validate_archive_layout(
        (member.filename, is_directory) for member, is_directory in classified
    )
    return [
        (member, path, is_directory)
        for (member, is_directory), path in zip(classified, paths, strict=True)
    ]


def _validate_relative_path(value: object) -> str:
    if not isinstance(value, str):
        raise InstallerError("invalid path")
    return _validate_member_names([value])[0].as_posix()


def _validate_record(tool_name: str, value: object) -> dict[str, Any]:
    record = _require_exact_keys(value, RECORD_KEYS, tool_name)
    if not isinstance(record["version"], str) or not SEMVER_PATTERN.fullmatch(
        record["version"]
    ):
        raise InstallerError(f"{tool_name}: invalid version")
    platforms = record["platforms"]
    if (
        not isinstance(platforms, list)
        or not platforms
        or any(not isinstance(platform, str) for platform in platforms)
        or len(platforms) != len(set(platforms))
        or not set(platforms).issubset(PLATFORM_NAMES)
    ):
        raise InstallerError(f"{tool_name}: invalid platforms")
    try:
        _validate_https_url(record["url"])
    except InstallerError as error:
        raise InstallerError(f"{tool_name}: {error}") from error
    if not isinstance(record["sha256"], str) or not SHA256_PATTERN.fullmatch(
        record["sha256"]
    ):
        raise InstallerError(f"{tool_name}: invalid sha256")
    if (
        not isinstance(record["artifactType"], str)
        or record["artifactType"] not in ARTIFACT_TYPES
    ):
        raise InstallerError(f"{tool_name}: invalid artifactType")

    artifact_type = record["artifactType"]
    if artifact_type == "tar.gz":
        install_keys = frozenset(("kind", "target", "memberBasename"))
    elif artifact_type == "tar.xz":
        install_keys = frozenset(("kind", "target", "member"))
    elif artifact_type == "binary":
        install_keys = frozenset(("kind", "target"))
    elif (
        isinstance(record["install"], dict)
        and record["install"].get("kind") == "executable"
    ):
        install_keys = frozenset(("kind", "target", "member", "allowedEntries"))
    else:
        install_keys = frozenset(("kind", "target", "requiredEntries"))
    install = _require_exact_keys(
        record["install"], install_keys, f"{tool_name}: install"
    )
    expected_kind = (
        "powershell-module"
        if artifact_type == "zip" and "requiredEntries" in install
        else "executable"
    )
    if install["kind"] != expected_kind:
        raise InstallerError(f"{tool_name}: invalid install kind")
    try:
        normalized_target = _validate_relative_path(install["target"])
    except InstallerError as error:
        raise InstallerError(f"{tool_name}: invalid install target") from error
    if normalized_target != install["target"]:
        raise InstallerError(f"{tool_name}: invalid install target")
    if "memberBasename" in install:
        basename = install["memberBasename"]
        if (
            not isinstance(basename, str)
            or not basename
            or _normalized_member_name(basename).as_posix() != basename
        ):
            raise InstallerError(f"{tool_name}: invalid memberBasename")
    if "member" in install:
        try:
            normalized_member = _validate_relative_path(install["member"])
        except InstallerError as error:
            raise InstallerError(f"{tool_name}: invalid member") from error
        if normalized_member != install["member"]:
            raise InstallerError(f"{tool_name}: invalid member")
    for entries_key in ("requiredEntries", "allowedEntries"):
        if entries_key not in install:
            continue
        entries = install[entries_key]
        if (
            not isinstance(entries, list)
            or not entries
            or any(not isinstance(entry, str) for entry in entries)
        ):
            raise InstallerError(f"{tool_name}: invalid {entries_key}")
        try:
            normalized_entries = [_validate_relative_path(entry) for entry in entries]
        except InstallerError as error:
            raise InstallerError(f"{tool_name}: invalid {entries_key}") from error
        if len(normalized_entries) != len(
            set(entry.casefold() for entry in normalized_entries)
        ):
            raise InstallerError(f"{tool_name}: invalid {entries_key}")
        if normalized_entries != entries:
            raise InstallerError(f"{tool_name}: invalid {entries_key}")
    if (
        "allowedEntries" in install
        and install["member"] not in install["allowedEntries"]
    ):
        raise InstallerError(f"{tool_name}: member must be an allowed entry")

    probe_keys = (
        frozenset(("expectedLine",))
        if expected_kind == "powershell-module"
        else frozenset(("arguments", "expectedLine"))
    )
    probe = _require_exact_keys(record["probe"], probe_keys, f"{tool_name}: probe")
    expected_line = probe["expectedLine"]
    if (
        not isinstance(expected_line, str)
        or not expected_line
        or expected_line.splitlines() != [expected_line]
    ):
        raise InstallerError(f"{tool_name}: invalid expectedLine")
    if "arguments" in probe:
        arguments = probe["arguments"]
        if (
            not isinstance(arguments, list)
            or not arguments
            or any(
                not isinstance(argument, str) or not argument or "\0" in argument
                for argument in arguments
            )
        ):
            raise InstallerError(f"{tool_name}: invalid probe arguments")
    return record


def platform_record(record: dict[str, Any], platform_name: str) -> dict[str, Any]:
    """Resolve one platform artifact, retaining the shared version and probe."""
    variants = record.get("variants", {})
    base = {key: value for key, value in record.items() if key != "variants"}
    variant = variants.get(platform_name)
    if variant is not None:
        return {**base, **variant, "platforms": [platform_name]}
    if platform_name not in record["platforms"]:
        raise InstallerError(f"tool is unavailable for {platform_name}")
    return base


def available_platforms(record: dict[str, Any]) -> set[str]:
    """Return base and explicitly declared variant capabilities."""
    return set(record["platforms"]) | set(record.get("variants", {}))


def validate_registry(registry: object) -> dict[str, Any]:
    """Validate and return the schema-2 quality-tool registry."""
    value = _require_exact_keys(registry, REGISTRY_KEYS, "versions.json")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != SCHEMA_VERSION
    ):
        raise InstallerError("schemaVersion must be 2")
    for section in ("python", "node"):
        declarations = value[section]
        if not isinstance(declarations, dict):
            raise InstallerError(f"versions.json: {section} must be an object")
        for name, version in declarations.items():
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(version, str)
                or SEMVER_PATTERN.fullmatch(version) is None
            ):
                raise InstallerError(
                    f"versions.json: {section}: invalid version for {name}"
                )
    policy = _require_exact_keys(value["policy"], POLICY_KEYS, "versions.json: policy")
    coverage_threshold = policy["coverageFailUnder"]
    if (
        type(coverage_threshold) is not int
        or coverage_threshold < 0
        or coverage_threshold > 100
    ):
        raise InstallerError("versions.json: policy: invalid coverageFailUnder")
    for name in ("npmIgnoreScripts", "pythonRequireHashes"):
        if type(policy[name]) is not bool:
            raise InstallerError(f"versions.json: policy: invalid {name}")
    for name in ("nodeCiVersion", "nodeMinimum"):
        version = policy[name]
        if not isinstance(version, str) or SEMVER_PATTERN.fullmatch(version) is None:
            raise InstallerError(f"versions.json: policy: invalid {name}")
    minimum = tuple(int(part) for part in policy["nodeMinimum"].split("."))
    ci_version = tuple(int(part) for part in policy["nodeCiVersion"].split("."))
    if ci_version < minimum:
        raise InstallerError(
            "versions.json: policy: nodeCiVersion is below nodeMinimum"
        )
    external = value["external"]
    if not isinstance(external, dict) or set(external) != set(TOOL_NAMES):
        raise InstallerError("external tools must be exactly " + ", ".join(TOOL_NAMES))
    validated_targets: dict[str, set[str]] = {name: set() for name in PLATFORM_NAMES}
    for tool_name in TOOL_NAMES:
        raw_record = external[tool_name]
        if not isinstance(raw_record, dict):
            raise InstallerError(f"{tool_name}: expected an object")
        base = {key: item for key, item in raw_record.items() if key != "variants"}
        record = _validate_record(tool_name, base)
        variants = raw_record.get("variants", {})
        if not isinstance(variants, dict):
            raise InstallerError(f"{tool_name}: variants must be an object")
        for platform_name, variant in variants.items():
            if (
                platform_name not in PLATFORM_NAMES
                or platform_name in record["platforms"]
            ):
                raise InstallerError(f"{tool_name}: invalid variant platform")
            override = _require_exact_keys(
                variant, VARIANT_KEYS, f"{tool_name}: variant"
            )
            _validate_record(
                tool_name, {**record, **override, "platforms": [platform_name]}
            )
        for platform_name in available_platforms(raw_record):
            target = platform_record(raw_record, platform_name)["install"][
                "target"
            ].casefold()
            if any(
                target == previous
                or target.startswith(previous + "/")
                or previous.startswith(target + "/")
                for previous in validated_targets[platform_name]
            ):
                raise InstallerError(f"{tool_name}: duplicate install target")
            validated_targets[platform_name].add(target)
    return value


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects that leave credential-free HTTPS."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        try:
            _validate_https_url(new_url)
        except InstallerError as error:
            raise urllib.error.URLError(str(error)) from error
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


def _safe_urlopen(
    request: urllib.request.Request,
    *,
    timeout: float,
) -> Any:
    opener = urllib.request.build_opener(SafeRedirectHandler())
    return opener.open(request, timeout=timeout)


def _download(
    tool_name: str,
    record: dict[str, Any],
    destination: Path,
    open_url: Callable[..., Any],
) -> None:
    request = urllib.request.Request(record["url"], headers={"User-Agent": USER_AGENT})
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS
    downloaded = 0
    try:
        with open_url(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            try:
                _validate_https_url(response.geturl())
            except InstallerError as error:
                raise InstallerError(f"download failed: {error}") from error
            with destination.open("xb") as output:
                while True:
                    if time.monotonic() >= deadline:
                        raise InstallerError("download failed: timed out")
                    chunk = response.read(64 * 1024)
                    if time.monotonic() >= deadline:
                        raise InstallerError("download failed: timed out")
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise InstallerError("download failed: size limit exceeded")
                    output.write(chunk)
    except InstallerError as error:
        raise InstallerError(f"{tool_name}: {error}") from error
    except (
        OSError,
        TimeoutError,
        http.client.HTTPException,
        urllib.error.URLError,
    ) as error:
        raise InstallerError(f"{tool_name}: download failed: {error}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file(source: Any, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        shutil.copyfileobj(source, output, length=64 * 1024)


def _install_tar_executable(
    record: dict[str, Any],
    artifact: Path,
    staging_root: Path,
) -> Path:
    mode: Literal["r:gz", "r:xz"] = (
        "r:gz" if record["artifactType"] == "tar.gz" else "r:xz"
    )
    with tarfile.open(artifact, mode=mode) as archive:
        members = _validate_tar_members(iter(archive))
        install = record["install"]
        if "memberBasename" in install:
            selected = [
                member
                for member, path, is_directory in members
                if not is_directory and path.name == install["memberBasename"]
            ]
        else:
            selected = [
                member
                for member, path, is_directory in members
                if not is_directory and path.as_posix() == install["member"]
            ]
        if len(selected) != 1:
            raise InstallerError("required member not found")
        source = archive.extractfile(selected[0])
        if source is None:
            raise InstallerError("required member not found")
        target = staging_root / install["target"]
        with source:
            _copy_file(source, target)
    if os.name != "nt":
        target.chmod(0o755)
    return target


def _install_binary(record: dict[str, Any], artifact: Path, staging_root: Path) -> Path:
    target = staging_root / record["install"]["target"]
    with artifact.open("rb") as source:
        _copy_file(source, target)
    if os.name != "nt":
        target.chmod(0o755)
    return target


def _install_powershell_module(
    record: dict[str, Any], artifact: Path, staging_root: Path
) -> Path:
    target = staging_root / record["install"]["target"]
    with zipfile.ZipFile(artifact) as archive:
        members = _validate_zip_members(archive.infolist())
        regular_names = {
            path.as_posix() for _, path, is_directory in members if not is_directory
        }
        if not set(record["install"]["requiredEntries"]).issubset(regular_names):
            raise InstallerError("required member not found")
        for member, path, is_directory in members:
            destination = target.joinpath(*path.parts)
            if is_directory:
                destination.mkdir(parents=True, exist_ok=True)
                continue
            with archive.open(member, "r") as source:
                _copy_file(source, destination)
    return target


def _install_zip_executable(
    record: dict[str, Any], artifact: Path, staging_root: Path
) -> Path:
    target = staging_root / record["install"]["target"]
    with zipfile.ZipFile(artifact) as archive:
        members = _validate_zip_members(archive.infolist())
        expected = record["install"]["member"]
        selected = [
            member
            for member, path, directory in members
            if not directory and path.as_posix() == expected
        ]
        if len(selected) != 1:
            raise InstallerError("required member not found")
        for _, path, directory in members:
            if (
                not directory
                and path.as_posix() not in record["install"]["allowedEntries"]
            ):
                raise InstallerError(f"unsafe archive entry: unexpected payload {path}")
        with archive.open(selected[0]) as source:
            _copy_file(source, target)
    if os.name != "nt":
        target.chmod(0o755)
    return target


def _install_artifact(
    tool_name: str,
    record: dict[str, Any],
    artifact: Path,
    staging_root: Path,
) -> Path:
    try:
        if record["artifactType"] in ("tar.gz", "tar.xz"):
            return _install_tar_executable(record, artifact, staging_root)
        if record["artifactType"] == "binary":
            return _install_binary(record, artifact, staging_root)
        if record["install"]["kind"] == "executable":
            return _install_zip_executable(record, artifact, staging_root)
        return _install_powershell_module(record, artifact, staging_root)
    except (
        EOFError,
        OSError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        raise InstallerError(f"{tool_name}: unsafe archive entry: {error}") from error
    except InstallerError as error:
        raise InstallerError(f"{tool_name}: {error}") from error


def _stream_text(value: object) -> str:
    if value is None:
        return "<empty>"
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    text = text.strip()
    if not text:
        return "<empty>"
    if len(text) > DIAGNOSTIC_LIMIT:
        return text[:DIAGNOSTIC_LIMIT] + "..."
    return text


def _probe_diagnostic(stdout: object, stderr: object) -> str:
    return f"stdout: {_stream_text(stdout)}; stderr: {_stream_text(stderr)}"


def _run_probe(
    tool_name: str,
    command: list[str],
    expected_line: str,
    staging_root: Path,
    run_command: Callable[..., subprocess.CompletedProcess[str]],
    *,
    environment: dict[str, str] | None = None,
) -> None:
    try:
        result = run_command(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            shell=False,
            cwd=staging_root,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        diagnostic = _probe_diagnostic(error.output, error.stderr)
        raise InstallerError(
            f"{tool_name}: version probe failed: timed out; {diagnostic}"
        ) from error
    except OSError as error:
        raise InstallerError(f"{tool_name}: version probe failed: {error}") from error
    diagnostic = _probe_diagnostic(result.stdout, result.stderr)
    if result.returncode != 0:
        raise InstallerError(
            f"{tool_name}: version probe failed: exited {result.returncode}; "
            f"{diagnostic}"
        )
    lines = [
        line
        for stream in (result.stdout, result.stderr)
        for line in _stream_text(stream).splitlines()
    ]
    if expected_line not in lines:
        raise InstallerError(
            f"{tool_name}: version probe failed: unexpected output; {diagnostic}"
        )


def _bounded_run(
    command: list[str],
    *,
    timeout: float,
    text: bool,
    cwd: Path,
    env: dict[str, str] | None,
    **_options: Any,
) -> subprocess.CompletedProcess[str]:
    helper_path = Path(__file__).resolve().parents[1] / "process_runner.py"
    spec = importlib.util.spec_from_file_location("quality_process_runner", helper_path)
    if spec is None or spec.loader is None:
        raise OSError(f"cannot load process containment helper: {helper_path}")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    with helper.ProcessScope(
        command,
        timeout=timeout,
        text=text,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    ) as scope:
        try:
            stdout, stderr = scope.process.communicate(timeout=scope.work_remaining())
        except subprocess.TimeoutExpired:
            scope.expired.set()
            scope.terminate()
            stdout, stderr = scope.process.communicate(timeout=scope.remaining())
        if scope.expired.is_set():
            raise subprocess.TimeoutExpired(command, timeout, stdout, stderr)
        return subprocess.CompletedProcess(
            command, scope.process.returncode, stdout, stderr
        )


def _bounded_download(
    tool_name: str, record: dict[str, Any], destination: Path
) -> None:
    """Contain the entire HTTPS request, including headers and slow body reads."""
    command = [
        sys.executable,
        "-B",
        "-c",
        DOWNLOAD_WORKER_SCRIPT,
        str(Path(__file__).resolve()),
        tool_name,
        json.dumps(record),
        str(destination),
    ]
    try:
        result = _bounded_run(
            command,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            text=True,
            cwd=destination.parent,
            env=None,
        )
    except subprocess.TimeoutExpired as error:
        raise InstallerError(f"{tool_name}: download failed: timed out") from error
    except OSError as error:
        raise InstallerError(f"{tool_name}: download failed: {error}") from error
    if result.returncode != 0:
        raise InstallerError(
            f"{tool_name}: download failed: "
            f"{_probe_diagnostic(result.stdout, result.stderr)}"
        )


def _probe_tool(
    tool_name: str,
    record: dict[str, Any],
    installed_path: Path,
    staging_root: Path,
    run_command: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    if record["install"]["kind"] == "executable":
        _run_probe(
            tool_name,
            [str(installed_path), *record["probe"]["arguments"]],
            record["probe"]["expectedLine"],
            staging_root,
            run_command,
        )
        return
    environment = os.environ.copy()
    module_root = installed_path.parents[1]
    current_module_path = environment.get("PSModulePath")
    environment["PSModulePath"] = (
        str(module_root)
        if not current_module_path
        else str(module_root) + os.pathsep + current_module_path
    )
    environment["QUALITY_PSSA_MODULE_PATH"] = str(installed_path)
    _run_probe(
        tool_name,
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", PSSA_PROBE_SCRIPT],
        record["probe"]["expectedLine"],
        staging_root,
        run_command,
        environment=environment,
    )


def _path_chain(path: Path) -> list[Path]:
    return list(reversed((path, *path.parents)))


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    except FileNotFoundError:
        return False


def validate_install_root(
    install_root: Path, runner_temp: Path | None = None, *, local: bool = False
) -> tuple[Path, Path]:
    """Validate an absent root with a safe local parent or CI confinement."""
    raw_install = install_root.absolute()
    try:
        for part in raw_install.parts[1:]:
            if any(ord(character) < 32 for character in part):
                raise InstallerError("invalid control character")
            _normalized_member_name(part)
    except InstallerError as error:
        raise InstallerError("unsafe install root") from error
    if any(_is_link(component) for component in _path_chain(raw_install)):
        raise InstallerError("install root must not contain a symlink or junction")
    if local:
        if raw_install.exists():
            raise InstallerError("install root must not already exist")
        if not raw_install.parent.is_dir():
            raise InstallerError(
                "local install root parent must exist and be a directory"
            )
        return raw_install.resolve(strict=False), raw_install.parent.resolve(
            strict=True
        )
    if runner_temp is None:
        raise InstallerError("RUNNER_TEMP is required")
    raw_runner = runner_temp.absolute()
    if not raw_runner.is_dir():
        raise InstallerError("RUNNER_TEMP must exist and be a directory")
    if any(_is_link(component) for component in _path_chain(raw_runner)):
        raise InstallerError("RUNNER_TEMP must not contain a symlink or junction")
    resolved_runner = raw_runner.resolve(strict=True)
    resolved_install = raw_install.resolve(strict=False)
    if resolved_install == resolved_runner or not resolved_install.is_relative_to(
        resolved_runner
    ):
        raise InstallerError("install root must be strictly under RUNNER_TEMP")
    if raw_install.exists():
        raise InstallerError("install root must not already exist")
    return resolved_install, resolved_runner


def _selected_tools(
    registry: dict[str, Any], platform_name: str, tool_names: list[str] | None
) -> list[str]:
    if platform_name not in PLATFORM_NAMES:
        raise InstallerError(f"unsupported platform: {platform_name}")
    requested = list(tool_names) if tool_names is not None else None
    if requested is not None:
        if len(requested) != len(set(requested)):
            raise InstallerError("duplicate --tool selection")
        unknown = set(requested) - set(TOOL_NAMES)
        if unknown:
            raise InstallerError(f"unknown tool: {sorted(unknown)[0]}")
        incompatible = [
            name
            for name in requested
            if platform_name not in available_platforms(registry["external"][name])
        ]
        if incompatible:
            raise InstallerError(
                f"{incompatible[0]} is unavailable for {platform_name}"
            )
    return [
        name
        for name in TOOL_NAMES
        if platform_name in available_platforms(registry["external"][name])
        and (requested is None or name in requested)
    ]


def native_platform() -> str:
    """Return the supported native x64 host capability, failing otherwise."""
    if platform.machine().lower() not in ("amd64", "x86_64"):
        raise InstallerError("unsupported native architecture")
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform == "linux":
        return "linux-x64"
    raise InstallerError("unsupported native platform")


def _publish(staging: Path, destination: Path) -> None:
    if sys.platform == "win32":
        staging.rename(destination)
        return
    if sys.platform != "linux":
        raise InstallerError("unsupported publication platform")
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as error:
        raise InstallerError(
            "atomic no-overwrite publication is unavailable"
        ) from error
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def install_tools(
    registry: dict[str, Any],
    *,
    platform_name: str,
    install_root: Path,
    runner_temp: Path | None = None,
    tool_names: list[str] | None = None,
    open_url: Callable[..., Any] | None = None,
    run_command: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    local: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    """Download, verify, probe, and atomically publish selected tools."""
    validated = validate_registry(registry)
    final_root, temporary_root = validate_install_root(
        install_root, runner_temp, local=local
    )
    selected = _selected_tools(validated, platform_name, tool_names)
    if local:
        if not tool_names:
            raise InstallerError("local mode requires an explicit --tool selection")
        if platform_name != native_platform():
            raise InstallerError("selected platform must match the native platform")
    if dry_run or verbose:
        print(
            f"external tools: {'dry-run' if dry_run else 'install'} {platform_name}: "
            f"{', '.join(selected)} -> {final_root}"
        )
    if dry_run:
        return
    runner = run_command if run_command is not None else _bounded_run
    with tempfile.TemporaryDirectory(
        dir=temporary_root, prefix=".external-tools-"
    ) as workspace_name:
        workspace = Path(workspace_name)
        downloads = workspace / "downloads"
        staging = workspace / "install"
        downloads.mkdir()
        staging.mkdir()
        for index, tool_name in enumerate(selected):
            record = platform_record(validated["external"][tool_name], platform_name)
            artifact = downloads / f"{index}.artifact"
            if open_url is None:
                _bounded_download(tool_name, record, artifact)
            else:
                _download(tool_name, record, artifact, open_url)
            actual_digest = _sha256(artifact)
            if not hmac.compare_digest(actual_digest, record["sha256"]):
                raise InstallerError(f"{tool_name}: digest mismatch")
            installed_path = _install_artifact(tool_name, record, artifact, staging)
            _probe_tool(tool_name, record, installed_path, staging, runner)
        validate_install_root(final_root, temporary_root, local=local)
        missing_parents: list[Path] = []
        parent = final_root.parent
        while not parent.exists():
            missing_parents.append(parent)
            parent = parent.parent
        publication_source, publication_target = staging, final_root
        if missing_parents:
            publication_target = missing_parents[-1]
            publication_source = workspace / "publication"
            publication_source.mkdir()
            private_install = publication_source / final_root.relative_to(
                publication_target
            )
            private_install.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(private_install)
        validate_install_root(final_root, temporary_root, local=local)
        # Prepare absent parents privately; never expose public mkdir names or
        # remove public paths during rollback. A raced target fails closed.
        _publish(publication_source, publication_target)


def build_parser() -> argparse.ArgumentParser:
    """Build the external-tool installer command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=f"quality-tools registry {SCHEMA_VERSION}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and show selection without writes or downloads",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show platform, selection and destination",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="install chosen tools locally without RUNNER_TEMP",
    )
    parser.add_argument("--platform", choices=sorted(PLATFORM_NAMES), required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--tool", action="append", choices=TOOL_NAMES)
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Install external tools declared by the sibling quality registry."""
    options = build_parser().parse_args(arguments)
    try:
        runner_temp_value = os.environ.get("RUNNER_TEMP")
        if not options.local and not runner_temp_value:
            raise InstallerError("RUNNER_TEMP is required")
        registry_path = Path(__file__).resolve().with_name("versions.json")
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        install_tools(
            registry,
            platform_name=options.platform,
            install_root=options.install_root,
            runner_temp=Path(runner_temp_value) if runner_temp_value else None,
            tool_names=options.tool,
            local=options.local,
            dry_run=options.dry_run,
            verbose=options.verbose,
        )
    except (InstallerError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"external tools: {error}", file=sys.stderr)
        return 1
    if not options.dry_run:
        print("external tools: installation complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
