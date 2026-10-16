#!/usr/bin/env python3
"""Export matching OS coverage artifacts and combine their branch measurements."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform as runtime_platform
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import unittest

import coverage
from coverage import Coverage, CoverageData
from coverage.exceptions import CoverageException
from coverage.files import canonical_filename


def digest(path: Path) -> str:
    if not path.is_file() or any(
        parent.is_symlink() for parent in (path, *path.parents)
    ):
        raise ValueError(f"missing or linked coverage input: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(root: Path) -> dict[str, str]:
    """Bind each measurement to its immutable workflow inputs and policy."""
    commit = os.environ.get("AUDIT_COMMIT_SHA", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not all(
        re.fullmatch(r"[1-9][0-9]*", value) for value in (run, attempt)
    ):
        raise ValueError("coverage artifacts require a full SHA, run and attempt")
    quality = root / "tools/quality"
    registry = json.loads((quality / "versions.json").read_text(encoding="utf-8"))
    if coverage.__version__ != registry["python"]["coverage"]:
        raise ValueError("coverage runtime differs from the locked version")
    return {
        "commit": commit,
        "run": run,
        "attempt": attempt,
        "coverage": coverage.__version__,
        "policy": digest(quality / "pyproject.toml"),
    }


def canonical_name(name: str) -> str:
    path = PurePosixPath(name.replace("\\", "/"))
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.parts[:1] != ("tools",)
        or path.suffix != ".py"
    ):
        raise ValueError(f"unsafe coverage source: {name}")
    return str(path)


def read_data(path: Path, root: Path) -> tuple[CoverageData, dict[str, str]]:
    if not path.is_file() or any(
        parent.is_symlink() for parent in (path, *path.parents)
    ):
        raise ValueError(f"missing or linked coverage data: {path}")
    data = CoverageData(basename=str(path))
    try:
        data.read()
        files = data.measured_files()
        if not files or not data.has_arcs():
            raise ValueError("coverage artifact has no branch measurements")
        sources = {}
        for name in files:
            relative = canonical_name(name)
            source = root / relative
            sources[relative] = digest(source)
    except (OSError, ValueError, CoverageException):
        data.close(force=True)
        raise
    return data, sources


def export(root: Path, data_path: Path, destination: Path, platform: str) -> None:
    expected = identity(root)
    if platform not in {"linux", "windows"}:
        raise ValueError("coverage platform must be linux or windows")
    data, sources = read_data(data_path, root)
    data.close(force=True)
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(data_path, destination / ".coverage")
    metadata = {
        **expected,
        "platform": platform,
        "digest": digest(data_path),
        "sources": sources,
    }
    (destination / "metadata.json").write_text(
        json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8"
    )


def combine(
    root: Path, directory: Path, *, expected_identity: dict[str, str] | None = None
) -> dict[str, Any]:
    """Validate both inputs before unioning any line or branch information."""
    expected = identity(root) if expected_identity is None else expected_identity
    measurements = []
    for platform in ("linux", "windows"):
        source = directory / platform
        metadata_path = source / "metadata.json"
        digest(metadata_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError(f"invalid coverage metadata: {platform}")
        if any(
            metadata.get(key) != value
            for key, value in {**expected, "platform": platform}.items()
        ):
            raise ValueError(f"coverage metadata mismatch: {platform}")
        data_path = source / ".coverage"
        if digest(data_path) != metadata.get("digest"):
            raise ValueError(f"coverage data digest mismatch: {platform}")
        data, files = read_data(data_path, root)
        if files != metadata.get("sources"):
            raise ValueError(f"coverage source mismatch: {platform}")
        measurements.append(data)
    coverage_report(root, measurements[:1], directory / "linux-rechecked.json")
    return coverage_report(root, measurements, directory / "combined.json")


def coverage_report(
    root: Path, measurements: list[CoverageData], report_path: Path
) -> dict[str, Any]:
    """Recompute exact totals from the original branch data, not saved percentages."""
    merged = CoverageData(no_disk=True)
    report_data: CoverageData | None = None
    try:
        for data in measurements:
            merged.update(data, map_path=canonical_name)
        cov = Coverage(
            data_file=None,
            config_file=str(root / "tools/quality/pyproject.toml"),
            source=[str(root / "tools")],
        )
        cov.set_option("run:relative_files", False)
        report_data = cov.get_data()
        report_data.update(
            merged,
            map_path=lambda name: canonical_filename(str(root / canonical_name(name))),
        )
        if report_path.is_symlink():
            raise ValueError("linked combined coverage report")
        cov.json_report(outfile=str(report_path))
        return json.loads(report_path.read_text(encoding="utf-8"))
    finally:
        if report_data is not None:
            report_data.close(force=True)
        merged.close(force=True)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def run_tests(output: Path, *, suite: unittest.TestSuite | None = None) -> int:
    """Run discovery once and retain actual unittest counts and elapsed time."""
    started = time.monotonic()
    original_path = sys.path[:]
    try:
        sys.path.insert(0, str(Path.cwd()))
        if suite is None:
            suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
        result = unittest.TextTestRunner().run(suite)
    finally:
        sys.path[:] = original_path
    write_json(
        output,
        {
            "run": result.testsRun,
            "skipped": len(result.skipped),
            "failures": len(result.failures),
            "errors": len(result.errors),
            "expected_failures": len(result.expectedFailures),
            "unexpected_successes": len(result.unexpectedSuccesses),
            "seconds": time.monotonic() - started,
        },
    )
    return 0 if result.wasSuccessful() else 1


def shell_suites(platform: str) -> list[list[str]]:
    if platform == "windows":
        return [
            ["bash", f"tests/test_quality_{family}.sh", "--windows"]
            for family in ("pre_commit", "pre_push")
        ]
    return [
        ["bash", f"tests/{name}.sh"]
        for name in (
            "test_repository_audit",
            "test_agent_rules_transfer",
            "test_quality_hooks",
            "test_quality_pre_commit",
            "test_commit_message_validation",
            "test_quality_pre_push",
        )
    ]


def bash_executable() -> str:
    """Select Git Bash rather than the Windows WSL launcher."""
    if sys.platform == "win32":
        git = shutil.which("git")
        for parent in Path(git).parents if git else ():
            candidate = parent / "bin/bash.exe"
            if candidate.is_file():
                return str(candidate)
        raise FileNotFoundError(
            "Git Bash executable was not found in the Git installation"
        )
    return "bash"


def run_shell(output: Path, platform: str) -> int:
    """Retain per-suite outcomes and logs; do not invent internal shell case counts."""
    output.mkdir(parents=True, exist_ok=True)
    results = []
    environment = os.environ.copy()
    environment.pop("AUDIT_COVERAGE_DIR", None)
    with (output / "shell.log").open("wb") as log:
        for command in shell_suites(platform):
            started = time.monotonic()
            invocation = (
                [bash_executable(), *command[1:]] if command[0] == "bash" else command
            )
            result = subprocess.run(
                invocation,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                env=environment,
            )
            results.append(
                {
                    "command": command,
                    "returncode": result.returncode,
                    "seconds": time.monotonic() - started,
                }
            )
            write_json(output / "shell.json", {"platform": platform, "suites": results})
            if result.returncode:
                return result.returncode
    return 0


def environment(root: Path, platform: str) -> dict:
    """Probe executables actually selected on this runner, including its image."""
    spec = importlib.util.spec_from_file_location(
        "quality_versions", Path(__file__).with_name("check-versions.py")
    )
    assert spec is not None and spec.loader is not None
    versions = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = versions
    spec.loader.exec_module(versions)
    registry = json.loads(
        (root / "tools/quality/versions.json").read_text(encoding="utf-8")
    )
    commands = {
        "node": ["node", "--version"],
        "npm": ["npm", "--version"],
        "git": ["git", "--version"],
        "bash": [bash_executable(), "--version"],
        "powershell": [
            "pwsh",
            "-NoProfile",
            "-Command",
            "$PSVersionTable.PSVersion.ToString()",
        ],
    }
    if platform == "windows":
        commands["windows-powershell"] = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "$PSVersionTable.PSVersion.ToString()",
        ]
    external = versions.external_commands(registry["external"])
    for name in (
        registry["external"]
        if platform == "linux"
        else ("PSScriptAnalyzer", "shellcheck", "shfmt")
    ):
        commands[name] = external[name]
    actual = {}
    for name, command in commands.items():
        probe = versions.command_version(command)
        if probe.version is None:
            raise ValueError(f"cannot measure {name}: {probe.diagnostic}")
        actual[name] = probe.version
    for name in registry["python"]:
        actual[f"python:{name}"] = importlib.metadata.version(name.split("[")[0])
    for name in registry["node"]:
        actual[f"npm:{name}"] = json.loads(
            (root / "tools/quality/node_modules" / name / "package.json").read_text(
                encoding="utf-8"
            )
        )["version"]
    facts = {
        "python": runtime_platform.python_version(),
        "system": runtime_platform.system(),
        "machine": runtime_platform.machine(),
        "image_version": os.environ.get("ImageVersion", ""),
        "image_os": os.environ.get("ImageOS", ""),
        "tools": actual,
    }
    current = identity(root)
    return {
        **{k: current[k] for k in ("commit", "run", "attempt")},
        "platform": platform,
        "facts": facts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export_parser = commands.add_parser(
        "export", help="seal one successful OS measurement"
    )
    export_parser.add_argument("data", type=Path)
    export_parser.add_argument("destination", type=Path)
    export_parser.add_argument(
        "--platform", choices=("linux", "windows"), required=True
    )
    combine_parser = commands.add_parser(
        "combine", help="validate and combine both OS artifacts"
    )
    combine_parser.add_argument("directory", type=Path)
    tests_parser = commands.add_parser(
        "tests", help="run Python discovery with measured counts"
    )
    tests_parser.add_argument("--output", type=Path, required=True)
    shell_parser = commands.add_parser(
        "shell", help="run reusable behavior suites with reports"
    )
    shell_parser.add_argument("--output", type=Path, required=True)
    shell_parser.add_argument("--platform", choices=("linux", "windows"), required=True)
    environment_parser = commands.add_parser(
        "environment", help="record the selected runner environment"
    )
    environment_parser.add_argument("--output", type=Path, required=True)
    environment_parser.add_argument(
        "--platform", choices=("linux", "windows"), required=True
    )
    options = parser.parse_args(argv)
    try:
        root = Path.cwd()
        if options.command == "export":
            export(
                root,
                options.data.absolute(),
                options.destination.absolute(),
                options.platform,
            )
        elif options.command == "combine":
            combine(root, options.directory.absolute())
        elif options.command == "tests":
            return run_tests(options.output)
        elif options.command == "shell":
            return run_shell(options.output, options.platform)
        else:
            write_json(options.output, environment(root, options.platform))
        return 0
    except (OSError, ValueError, KeyError, TypeError, CoverageException) as error:
        print(f"coverage artifacts: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
