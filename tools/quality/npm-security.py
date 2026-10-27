#!/usr/bin/env python3
"""Audit the locked npm development dependencies and block high or critical findings."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


VERSION = "0.1.0"
AUDIT_TIMEOUT_SECONDS = 120
SEVERITIES = ("info", "low", "moderate", "high", "critical")


def evaluate_audit(report: dict[str, Any]) -> dict[str, Any]:
    """Validate an npm v2 report and block every high or critical finding."""
    if (
        not isinstance(report, dict)
        or type(report.get("auditReportVersion")) is not int
        or report["auditReportVersion"] != 2
        or "error" in report
    ):
        raise ValueError("Invalid or failed npm audit report")
    vulnerabilities = report.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        raise ValueError("Missing npm vulnerability graph")
    counts = dict.fromkeys(SEVERITIES, 0)
    for name, record in vulnerabilities.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(record, dict)
            or record.get("name") != name
            or not isinstance(record.get("severity"), str)
            or record["severity"] not in counts
            or not isinstance(record.get("via"), list)
            or not record["via"]
            or not isinstance(record.get("nodes"), list)
            or not record["nodes"]
            or any(not isinstance(node, str) or not node for node in record["nodes"])
        ):
            raise ValueError(f"Invalid npm vulnerability record: {name}")
        for via in record["via"]:
            if isinstance(via, str):
                if not via:
                    raise ValueError(f"Invalid npm attribution: {name}")
            elif (
                not isinstance(via, dict)
                or via.get("name") != name
                or not isinstance(via.get("url"), str)
                or not via["url"]
                or not isinstance(via.get("severity"), str)
                or via["severity"] not in counts
            ):
                raise ValueError(f"Invalid npm attribution: {name}")
        counts[record["severity"]] += 1
    counts["total"] = len(vulnerabilities)
    metadata = report.get("metadata")
    reported_counts = (
        metadata.get("vulnerabilities") if isinstance(metadata, dict) else None
    )
    if (
        not isinstance(reported_counts, dict)
        or set(reported_counts) != set(counts)
        or any(
            type(value) is not int or value < 0 for value in reported_counts.values()
        )
        or reported_counts != counts
    ):
        raise ValueError("Inconsistent npm vulnerability counts")

    complete: set[str] = set()
    active: set[str] = set()
    for root in vulnerabilities:
        stack = [(root, False)]
        while stack:
            name, exiting = stack.pop()
            if name in complete:
                continue
            if name not in vulnerabilities:
                raise ValueError(f"Missing npm attribution: {name}")
            if exiting:
                active.remove(name)
                complete.add(name)
            else:
                if name in active:
                    raise ValueError(f"Cyclic npm attribution: {name}")
                active.add(name)
                stack.append((name, True))
                stack.extend(
                    (via, False)
                    for via in vulnerabilities[name]["via"]
                    if isinstance(via, str)
                )
    return {
        "rawReport": report,
        "rawCounts": counts,
        "blocked": sorted(
            name
            for name, record in vulnerabilities.items()
            if record["severity"] in {"high", "critical"}
        ),
    }


def audit(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Run the registry audit within a bounded process tree and isolated cache."""
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise ValueError("Node.js and npm must already be installed")
    npm_path = Path(npm).resolve()
    npm_cli = (
        npm_path
        if npm_path.suffix == ".js"
        else npm_path.parent / "node_modules/npm/bin/npm-cli.js"
    )
    if not npm_cli.is_file():
        raise ValueError(f"Cannot locate the npm CLI beside {npm_path}")
    command = [
        node,
        str(npm_cli),
        "audit",
        "--json",
        "--include=dev",
        "--audit-level=high",
        "--prefix",
        str(root),
    ]
    if dry_run:
        return {"operation": "audit", "dryRun": True, "command": command, "blocked": []}
    helper_path = Path(__file__).resolve().parents[1] / "process_runner.py"
    spec = importlib.util.spec_from_file_location("npm_process_runner", helper_path)
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    with tempfile.TemporaryDirectory(prefix="npm-security-") as cache:
        with helper.ProcessScope(
            [*command, "--cache", cache],
            timeout=AUDIT_TIMEOUT_SECONDS,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(os.environ, NPM_CONFIG_IGNORE_SCRIPTS="true"),
        ) as scope:
            stdout, stderr = scope.process.communicate(timeout=scope.work_remaining())
            if scope.expired.is_set():
                raise subprocess.TimeoutExpired(
                    command, AUDIT_TIMEOUT_SECONDS, stdout, stderr
                )
            if scope.process.returncode not in {0, 1}:
                raise ValueError(
                    f"npm audit failed ({scope.process.returncode}): {stderr.strip()}"
                )
    return evaluate_audit(json.loads(stdout))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("audit")
    command.add_argument("--quality-root", type=Path, default=Path(__file__).parent)
    command.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        result = audit(args.quality_root.absolute(), dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return int(bool(result["blocked"]))
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        if args.verbose:
            raise
        print(f"npm security: {error}", file=sys.stderr)
        for note in getattr(error, "__notes__", []):
            print(note, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
