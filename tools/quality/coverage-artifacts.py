#!/usr/bin/env python3
"""Export matching OS coverage artifacts and combine their branch measurements."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from typing import Any

import coverage
from coverage import Coverage, CoverageData
from coverage.exceptions import CoverageException


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
    data.read()
    files = data.measured_files()
    if not files or not data.has_arcs():
        raise ValueError("coverage artifact has no branch measurements")
    sources = {}
    for name in files:
        relative = canonical_name(name)
        source = root / relative
        sources[relative] = digest(source)
    return data, sources


def export(root: Path, data_path: Path, destination: Path, platform: str) -> None:
    expected = identity(root)
    if platform not in {"linux", "windows"}:
        raise ValueError("coverage platform must be linux or windows")
    _, sources = read_data(data_path, root)
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


def combine(root: Path, directory: Path) -> dict[str, Any]:
    """Validate both inputs before unioning any line or branch information."""
    expected = identity(root)
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
    merged = CoverageData(no_disk=True)
    previous = Path.cwd()
    report_data: CoverageData | None = None
    try:
        for data in measurements:
            merged.update(data, map_path=canonical_name)
        os.chdir(root)
        cov = Coverage(
            data_file=None,
            config_file=str(root / "tools/quality/pyproject.toml"),
        )
        report_data = cov.get_data()
        report_data.update(merged)
        report_path = directory / "combined.json"
        if report_path.is_symlink():
            raise ValueError("linked combined coverage report")
        cov.json_report(outfile=str(report_path))
        return json.loads(report_path.read_text(encoding="utf-8"))
    finally:
        if report_data is not None:
            report_data.close(force=True)
        merged.close(force=True)
        os.chdir(previous)


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
        else:
            combine(root, options.directory.absolute())
        return 0
    except (OSError, ValueError, KeyError, TypeError, CoverageException) as error:
        print(f"coverage artifacts: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
