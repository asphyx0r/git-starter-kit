#!/usr/bin/env python3
"""Detect drift between the quality registry and locked declarations."""

from __future__ import annotations

import argparse
import importlib.util
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple
from urllib.parse import urlparse


_PROCESS_SPEC = importlib.util.spec_from_file_location(
    "quality_version_process_runner",
    Path(__file__).resolve().parents[1] / "process_runner.py",
)
assert _PROCESS_SPEC is not None and _PROCESS_SPEC.loader is not None
process_runner = importlib.util.module_from_spec(_PROCESS_SPEC)
_PROCESS_SPEC.loader.exec_module(process_runner)


# Validate PEP 440 pins before third-party dependencies are installed.
REQUIREMENT_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?)"
    r"==(?P<version>v?(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*"
    r"(?:[._-]?(?:alpha|a|beta|b|preview|pre|rc|c)[._-]?[0-9]*)?"
    r"(?:-[0-9]+|[._-]?(?:post|rev|r)[._-]?[0-9]*)?"
    r"(?:[._-]?dev[._-]?[0-9]*)?"
    r"(?:\+[a-z0-9]+(?:[._-][a-z0-9]+)*)?)",
    re.IGNORECASE | re.ASCII,
)
COMMAND_TIMEOUT_SECONDS = 15
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class VersionProbe(NamedTuple):
    """One external version probe result."""

    version: str | None
    diagnostic: str


def normalize_name(name: str) -> str:
    """Return the normalized distribution name without extras."""
    base_name = name.split("[", 1)[0]
    return re.sub(r"[-_.]+", "-", base_name).lower()


def semver_tuple(value: str) -> tuple[int, int, int]:
    """Return a strict three-part semantic version tuple."""
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid semantic version: {value}")
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
    )


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object or raise a useful declaration error."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def parse_requirements(path: Path) -> dict[str, str]:
    """Parse exact top-level requirement declarations."""
    declarations: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = re.split(r"\s+#", line.strip(), maxsplit=1)[0].rstrip()
        if not stripped or stripped.startswith(("#", "--hash=")):
            continue
        match = REQUIREMENT_PATTERN.fullmatch(stripped.removesuffix("\\").rstrip())
        if match is None:
            raise ValueError(f"{path.name}:{number}: expected an exact requirement pin")
        name = normalize_name(match.group("name"))
        if name in declarations:
            raise ValueError(f"{path.name}:{number}: duplicate requirement {name}")
        declarations[name] = match.group("version")
    return declarations


def parse_direct_requirements(path: Path) -> dict[str, str]:
    """Parse direct names exactly, retaining requested extras."""
    declarations: dict[str, str] = {}
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = re.split(r"\s+#", line.strip(), maxsplit=1)[0].rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = REQUIREMENT_PATTERN.fullmatch(stripped)
        if match is None:
            raise ValueError(f"{path.name}:{number}: expected an exact requirement pin")
        name = normalize_name(match.group("name"))
        if name in seen:
            raise ValueError(f"{path.name}:{number}: duplicate requirement {name}")
        seen.add(name)
        declarations[match.group("name")] = match.group("version")
    return declarations


def requirement_blocks(path: Path) -> list[str]:
    """Return logical requirement blocks from a pip-compile lock."""
    blocks: list[str] = []
    current: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            if current:
                blocks.append("\n".join(current))
            current = [stripped]
        else:
            current.append(stripped)
    if current:
        blocks.append("\n".join(current))
    return blocks


def compare_versions(
    expected: dict[str, str],
    actual: dict[str, str],
    declaration: str,
    *,
    allow_extra: bool = False,
) -> list[str]:
    """Describe missing, extra, and changed version declarations."""
    errors: list[str] = []
    normalized_expected = {
        normalize_name(name): version for name, version in expected.items()
    }
    names: set[str] = set(normalized_expected)
    if not allow_extra:
        names.update(actual)
    for name in sorted(names):
        expected_version = normalized_expected.get(name)
        actual_version = actual.get(name)
        if expected_version != actual_version:
            errors.append(
                f"{declaration}: {name} expected {expected_version}, "
                f"found {actual_version}"
            )
    return errors


def validate_registry(quality_root: Path, registry: dict[str, Any]) -> list[str]:
    """Validate the shared external-tool registry without installing tools."""
    installer_path = quality_root / "install-external-tools.py"
    spec = importlib.util.spec_from_file_location(
        "quality_external_installer_validation", installer_path
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load registry validator: {installer_path}")
    installer: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    try:
        installer.validate_registry(registry)
    except installer.InstallerError as error:
        return [f"versions.json: {error}"]
    return []


def check_declarations(quality_root: Path) -> list[str]:
    """Check every declaration owned by the quality toolchain."""
    registry = load_json(quality_root / "versions.json")
    registry_errors = validate_registry(quality_root, registry)
    if registry_errors:
        return registry_errors
    expected_python = registry["python"]
    direct_python = parse_direct_requirements(quality_root / "requirements.in")
    errors: list[str] = []
    for name, version in expected_python.items():
        if direct_python.get(name) != version:
            errors.append(
                f"requirements.in: expected direct requirement {name}=={version}"
            )
    for name in sorted(set(direct_python) - set(expected_python)):
        errors.append(f"requirements.in: unexpected direct requirement {name}")
    errors.extend(
        compare_versions(
            registry["python"],
            parse_requirements(quality_root / "requirements.in"),
            "requirements.in",
        )
    )
    policies = registry["policy"]
    for policy_name in ("npmIgnoreScripts", "pythonRequireHashes"):
        if policies.get(policy_name) is not True:
            errors.append(f"versions.json: policy {policy_name} must be true")
    lock_path = quality_root / "requirements.lock"
    errors.extend(
        compare_versions(
            registry["python"],
            parse_requirements(lock_path),
            "requirements.lock",
            allow_extra=True,
        )
    )
    for block in requirement_blocks(lock_path):
        if (
            policies.get("pythonRequireHashes") is True
            and "--hash=sha256:" not in block
        ):
            errors.append(f"requirements.lock: unhashed block: {block.splitlines()[0]}")

    package = load_json(quality_root / "package.json")
    package_lock = load_json(quality_root / "package-lock.json")
    expected_node = registry["node"]
    expected_overrides = registry.get("nodeOverrides", {})
    if package.get("overrides", {}) != expected_overrides:
        errors.append("package.json: overrides differ from versions.json")
    expected_engine = {"node": f">={policies['nodeMinimum']}"}
    if package.get("engines") != expected_engine:
        errors.append(f"package.json: node engine expected >={policies['nodeMinimum']}")
    package_dependencies = package.get("devDependencies", {})
    errors.extend(compare_versions(expected_node, package_dependencies, "package.json"))
    lock_root = package_lock.get("packages", {}).get("", {})
    if lock_root.get("engines") != expected_engine:
        errors.append(
            f"package-lock.json: node engine expected >={policies['nodeMinimum']}"
        )
    if lock_root.get("devDependencies") != expected_node:
        errors.append("package-lock.json: root dependencies differ from versions.json")
    lock_packages = package_lock.get("packages", {})
    for name, version in expected_overrides.items():
        occurrences = [
            record
            for path, record in lock_packages.items()
            if path == f"node_modules/{name}" or path.endswith(f"/node_modules/{name}")
        ]
        if not occurrences or any(
            record.get("version") != version for record in occurrences
        ):
            errors.append(f"package-lock.json: {name} override expected {version}")
    for name, expected_version in expected_node.items():
        locked = lock_packages.get(f"node_modules/{name}", {})
        actual_version = locked.get("version")
        if actual_version != expected_version:
            errors.append(
                f"package-lock.json: {name} expected {expected_version}, "
                f"found {actual_version}"
            )
        if "integrity" not in locked:
            errors.append(f"package-lock.json: {name} has no integrity digest")
    for package_path, locked in lock_packages.items():
        if not package_path:
            continue
        package_name = package_path.removeprefix("node_modules/")
        if not locked.get("version"):
            errors.append(f"package-lock.json: {package_name} has no version")
        if not locked.get("integrity"):
            errors.append(f"package-lock.json: {package_name} has no integrity digest")
        resolved = locked.get("resolved")
        parsed = urlparse(resolved) if isinstance(resolved, str) else None
        if (
            parsed is None
            or parsed.scheme != "https"
            or parsed.netloc != "registry.npmjs.org"
        ):
            errors.append(
                f"package-lock.json: {package_name} has non-registry resolved URL"
            )
        if policies.get("npmIgnoreScripts") is True and "hasInstallScript" in locked:
            errors.append(f"package-lock.json: {package_name} hasInstallScript")

    pyproject = tomllib.loads(
        (quality_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    threshold = pyproject["tool"]["coverage"]["report"]["fail_under"]
    expected_threshold = registry["policy"]["coverageFailUnder"]
    if threshold != expected_threshold:
        errors.append(
            f"pyproject.toml: coverage threshold expected {expected_threshold}, "
            f"found {threshold}"
        )
    return errors


def command_version(
    command: list[str], expected_line: str | None = None
) -> VersionProbe:
    """Return a bounded external version probe with a precise diagnostic."""
    requested = Path(command[0])
    resolved = (
        str(requested.absolute())
        if ("/" in command[0] or "\\" in command[0]) and requested.is_file()
        else shutil.which(command[0])
    )
    if resolved is None:
        return VersionProbe(None, "command not found")
    invocation = [resolved, *command[1:]]
    path = Path(resolved)
    if (
        sys.platform == "win32"
        and path.is_file()
        and path.suffix.lower() not in {".exe", ".cmd", ".bat"}
    ):
        git = shutil.which("git")
        candidates = (
            [parent / "bin/bash.exe" for parent in Path(git).parents] if git else []
        )
        bash = next(
            (candidate for candidate in candidates if candidate.is_file()), None
        )
        if bash is None:
            return VersionProbe(None, "Git Bash unavailable for the selected script")
        invocation = [
            str(bash),
            "-c",
            'exec "$@"',
            "quality-version",
            path.as_posix(),
            *command[1:],
        ]
    try:
        result = process_runner.run(
            invocation, timeout=COMMAND_TIMEOUT_SECONDS, text=True
        )
    except subprocess.TimeoutExpired:
        return VersionProbe(None, "timed out")
    except OSError as error:
        return VersionProbe(None, f"cannot launch: {error}")
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode != 0:
        return VersionProbe(None, f"exited {result.returncode}: {output.strip()}")
    if expected_line is not None and expected_line not in output.splitlines():
        return VersionProbe(None, f"unexpected output: {output.strip()}")
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", output)
    if match is None:
        return VersionProbe(None, f"unparsable output: {output.strip()}")
    return VersionProbe(match.group(1), "matched")


def external_commands(
    external: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Return a version command for every registry-owned external tool."""
    pssa_version = external["PSScriptAnalyzer"]["version"]
    pssa_probe = (
        "$expected = Get-Module -ListAvailable PSScriptAnalyzer | "
        f"Where-Object Version -EQ ([version]'{pssa_version}') | "
        "Select-Object -First 1; "
        f"if ($null -eq $expected) {{ throw 'PSScriptAnalyzer {pssa_version} not found' }}; "
        f"Import-Module $expected.Path -RequiredVersion {pssa_version} -Force "
        "-ErrorAction Stop; $loaded = Get-Module PSScriptAnalyzer; "
        "if ([IO.Path]::GetFullPath($loaded.ModuleBase) -ne "
        "[IO.Path]::GetFullPath($expected.ModuleBase)) { "
        "throw 'PSScriptAnalyzer path mismatch' }; "
        "$null = Invoke-ScriptAnalyzer -ScriptDefinition '$value = 1' "
        "-ErrorAction Stop; "
        "$loaded.Version.ToString()"
    )
    return {
        "gitleaks": ["gitleaks", *external["gitleaks"]["probe"]["arguments"]],
        "actionlint": ["actionlint", *external["actionlint"]["probe"]["arguments"]],
        "PSScriptAnalyzer": [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            pssa_probe,
        ],
        "shfmt": ["shfmt", *external["shfmt"]["probe"]["arguments"]],
        "shellcheck": [
            "shellcheck",
            *external["shellcheck"]["probe"]["arguments"],
        ],
    }


def check_installed_node_overrides(
    quality_root: Path, runtime_root: Path | None = None
) -> list[str]:
    """Check every locked occurrence of the pinned transitive npm packages."""
    overrides = load_json(quality_root / "versions.json").get("nodeOverrides", {})
    packages = load_json(quality_root / "package-lock.json")["packages"]
    errors = []
    for name, expected in overrides.items():
        for location in packages:
            if location != f"node_modules/{name}" and not location.endswith(
                f"/node_modules/{name}"
            ):
                continue
            if (
                not location.startswith("node_modules/")
                or PurePosixPath(location).as_posix() != location
                or ":" in location
                or "\\" in location
                or any(part in {".", "..", ".git"} for part in location.split("/"))
            ):
                raise ValueError(f"Unsafe npm lock location: {location}")
            package = (runtime_root or quality_root) / location / "package.json"
            actual = load_json(package).get("version") if package.is_file() else None
            if actual != expected:
                errors.append(
                    f"runtime: {location} expected {expected}, found {actual}"
                )
    return errors


def check_runtime(
    quality_root: Path,
    *,
    tools: list[str] | None = None,
    runtime_root: Path | None = None,
    executables: dict[str, str] | None = None,
) -> list[str]:
    """Check installed runtimes without installing or downloading anything."""
    registry = load_json(quality_root / "versions.json")
    available = {"node", *registry["python"], *registry["node"], *registry["external"]}
    selected = available if tools is None else set(tools)
    if selected - available:
        raise ValueError(f"unknown runtime tool: {sorted(selected - available)[0]}")
    executables = executables or {}
    if set(executables) - selected:
        raise ValueError("executable override must belong to a selected tool")
    runtime_root = runtime_root or quality_root
    python_commands = {
        name: [name, "--version"]
        for name in ("codespell", "coverage", "mypy", "pip-audit", "ruff", "yamllint")
    }
    if set(executables) - {
        "node",
        *python_commands,
        *registry["node"],
        *registry["external"],
    }:
        raise ValueError("library dependencies have no executable override")
    errors: list[str] = []
    node_minimum = registry["policy"]["nodeMinimum"]
    if "node" in selected or selected & set(registry["node"]):
        node_probe = command_version([executables.get("node", "node"), "--version"])
        if node_probe.version is None or semver_tuple(
            node_probe.version
        ) < semver_tuple(node_minimum):
            errors.append(
                f"runtime: node expected >={node_minimum}, "
                f"found {node_probe.version} ({node_probe.diagnostic})"
            )
    for name, expected_version in registry["python"].items():
        if name not in selected:
            continue
        distribution = normalize_name(name)
        try:
            actual_version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            actual_version = None
        if actual_version != expected_version:
            errors.append(
                f"runtime: {name} expected {expected_version}, found {actual_version}"
            )
        if name in python_commands:
            python_command = python_commands[name]
            probe = command_version(
                [executables.get(name, python_command[0]), *python_command[1:]]
            )
            if probe.version != expected_version:
                errors.append(
                    f"runtime executable: {name} expected {expected_version}, "
                    f"found {probe.version} ({probe.diagnostic})"
                )

    node_modules = runtime_root / "node_modules"
    for name, expected_version in registry["node"].items():
        if name not in selected:
            continue
        package_path = node_modules / name / "package.json"
        actual_version = (
            load_json(package_path).get("version") if package_path.is_file() else None
        )
        if actual_version != expected_version:
            errors.append(
                f"runtime: {name} expected {expected_version}, found {actual_version}"
            )
        alias = "commitlint" if name == "@commitlint/cli" else name
        local_command = node_modules / ".bin" / alias
        if not local_command.is_file() and local_command.with_suffix(".cmd").is_file():
            local_command = local_command.with_suffix(".cmd")
        executable = str(local_command) if local_command.is_file() else alias
        probe = command_version([executables.get(name, executable), "--version"])
        if probe.version != expected_version:
            errors.append(
                f"runtime executable: {name} expected {expected_version}, "
                f"found {probe.version} ({probe.diagnostic})"
            )

    if selected & set(registry["node"]):
        errors.extend(check_installed_node_overrides(quality_root, runtime_root))
    external = registry["external"]
    commands = external_commands(external)
    for name, record in external.items():
        if name not in selected:
            continue
        expected_version = record["version"]
        command = commands.get(name)
        if command is None:
            errors.append(f"runtime: {name} has no version probe")
            continue
        command = [executables.get(name, command[0]), *command[1:]]
        probe = command_version(command, record["probe"]["expectedLine"])
        if probe.version != expected_version:
            errors.append(
                f"runtime: {name} expected {expected_version}, "
                f"found {probe.version} ({probe.diagnostic})"
            )
    return errors


def build_parser() -> argparse.ArgumentParser:
    """Build the drift-checker command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quality-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="quality configuration directory",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="also validate locally installed tool versions",
    )
    parser.add_argument(
        "--tool",
        action="append",
        help="check only this runtime tool; repeat for multiple tools",
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help="installed quality tree when expected pins come from another snapshot",
    )
    parser.add_argument(
        "--executable",
        action="append",
        default=[],
        metavar="TOOL=PATH",
        help="probe the executable actually selected by the caller",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Run declaration and optional runtime drift checks."""
    options = build_parser().parse_args(arguments)
    quality_root = options.quality_root.resolve()
    try:
        if (
            options.tool or options.runtime_root or options.executable
        ) and not options.runtime:
            raise ValueError("scoped runtime options require --runtime")
        executables = {}
        for entry in options.executable:
            name, separator, path = entry.partition("=")
            if not separator or not name or not path or name in executables:
                raise ValueError("--executable requires a unique TOOL=PATH")
            executables[name] = path
        errors = check_declarations(quality_root)
        if options.runtime:
            errors.extend(
                check_runtime(
                    quality_root,
                    tools=options.tool,
                    runtime_root=options.runtime_root,
                    executables=executables,
                )
            )
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as caught_error:
        errors = [f"quality versions: {caught_error}"]
    if errors:
        for declaration_error in errors:
            print(declaration_error, file=sys.stderr)
        return 1
    print("quality versions: declarations match")
    if options.runtime:
        print("quality versions: runtimes match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
