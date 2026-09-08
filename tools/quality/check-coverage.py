#!/usr/bin/env python3
"""Enforce the registry threshold for global and separate branch coverage."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


def measured_count(
    totals: dict[str, Any], total_key: str, covered_key: str
) -> tuple[int, int]:
    """Reject missing, empty or inconsistent measurement totals."""
    total = totals[total_key]
    covered = totals[covered_key]
    if (
        type(total) is not int
        or type(covered) is not int
        or not 0 <= covered <= total
        or total == 0
    ):
        raise ValueError(f"Invalid coverage totals: {total_key}/{covered_key}.")
    return covered, total


def evaluate_report(report: dict[str, Any], minimum: int) -> tuple[bool, str]:
    """Compare exact counts before rounding the displayed percentages."""
    if report["meta"].get("branch_coverage") is not True:
        raise ValueError("Coverage report has no branch measurement.")
    totals = report["totals"]
    covered_lines, lines = measured_count(totals, "num_statements", "covered_lines")
    covered_branches, branches = measured_count(
        totals, "num_branches", "covered_branches"
    )
    covered_global = covered_lines + covered_branches
    global_total = lines + branches
    passed = (
        covered_global * 100 >= minimum * global_total
        and covered_branches * 100 >= minimum * branches
    )
    result = "PASS" if passed else "FAIL"
    message = (
        f"Coverage {result}: global={100 * covered_global / global_total:.2f}% "
        f"({covered_global}/{global_total}) "
        f"statements={100 * covered_lines / lines:.2f}% "
        f"({covered_lines}/{lines}) "
        f"branches={100 * covered_branches / branches:.2f}% "
        f"({covered_branches}/{branches}) "
        f"minimum={minimum}%"
    )
    return passed, message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="JSON report from coverage json")
    args = parser.parse_args(argv)
    try:
        registry = json.loads(
            Path(__file__).with_name("versions.json").read_text(encoding="utf-8")
        )
        minimum = registry["policy"]["coverageFailUnder"]
        passed, message = evaluate_report(
            json.loads(args.report.read_text(encoding="utf-8")), minimum
        )
        print(message)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")
        return 0 if passed else 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"coverage policy: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
