"""Exercise the separately enforced statement and branch coverage contract."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "tools/quality/check-coverage.py"
SPEC = importlib.util.spec_from_file_location("coverage_policy", SCRIPT)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class CoveragePolicyTests(unittest.TestCase):
    def run_policy(self, totals, *, branch_coverage=True, subprocess_cli=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "coverage.json"
            report.write_text(
                json.dumps(
                    {"meta": {"branch_coverage": branch_coverage}, "totals": totals}
                ),
                encoding="utf-8",
            )
            summary = root / "summary.md"
            environment = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary)}
            if subprocess_cli:
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), str(report)],
                    capture_output=True,
                    text=True,
                    env=environment,
                    check=False,
                    timeout=30,
                )
            else:
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    mock.patch.dict(os.environ, environment),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    status = POLICY.main([str(report)])
                result = subprocess.CompletedProcess(
                    args=[str(report)],
                    returncode=status,
                    stdout=stdout.getvalue(),
                    stderr=stderr.getvalue(),
                )
            return result, summary.read_text(
                encoding="utf-8"
            ) if summary.exists() else ""

    def test_high_statement_coverage_does_not_hide_missing_branches(self):
        result, summary = self.run_policy(
            {
                "num_statements": 100,
                "covered_lines": 100,
                "num_branches": 2,
                "covered_branches": 1,
            }
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("branches=50.00%", result.stdout)
        self.assertIn("global=99.02%", result.stdout)
        self.assertIn("FAIL", summary)

    def test_exact_branch_threshold_passes(self):
        result, summary = self.run_policy(
            {
                "num_statements": 100,
                "covered_lines": 100,
                "num_branches": 20,
                "covered_branches": 17,
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("branches=85.00%", result.stdout)
        self.assertIn("PASS", summary)

    def test_high_branch_coverage_does_not_hide_low_global_coverage(self):
        result, _ = self.run_policy(
            {
                "num_statements": 100,
                "covered_lines": 50,
                "num_branches": 2,
                "covered_branches": 2,
            }
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("global=50.98%", result.stdout)

    def test_rounding_never_turns_an_insufficient_measurement_into_a_pass(self):
        result, _ = self.run_policy(
            {
                "num_statements": 100,
                "covered_lines": 100,
                "num_branches": 20000,
                "covered_branches": 16999,
            }
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("branches=85.00% (16999/20000)", result.stdout)

    def test_cli_entry_point_reports_measured_coverage(self):
        result, _ = self.run_policy(
            {
                "num_statements": 100,
                "covered_lines": 100,
                "num_branches": 20,
                "covered_branches": 20,
            },
            subprocess_cli=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Coverage PASS", result.stdout)

    def test_rounded_global_failure_exposes_exact_counts(self):
        result, _ = self.run_policy(
            {
                "num_statements": 20000,
                "covered_lines": 16999,
                "num_branches": 20000,
                "covered_branches": 17000,
            }
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("global=85.00% (33999/40000)", result.stdout)
        self.assertIn("statements=85.00% (16999/20000)", result.stdout)

    def test_unreadable_report_is_a_controlled_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "missing.json"
            with redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(POLICY.main([str(report)]), 1)
            self.assertIn("coverage policy:", stderr.getvalue())

    def test_stdout_without_github_summary(self):
        report = {
            "meta": {"branch_coverage": True},
            "totals": {
                "num_statements": 2,
                "covered_lines": 2,
                "num_branches": 2,
                "covered_branches": 2,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}),
                redirect_stdout(io.StringIO()) as stdout,
            ):
                self.assertEqual(POLICY.main([str(path)]), 0)
            self.assertIn("Coverage PASS", stdout.getvalue())

    def test_missing_branch_measurement_is_rejected(self):
        result, _ = self.run_policy(
            {"num_statements": 100, "covered_lines": 100}, branch_coverage=False
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("branch measurement", result.stderr)

    def test_invalid_totals_cannot_pass(self):
        for overrides in (
            {"num_branches": 0},
            {"num_branches": True},
            {"covered_branches": 21},
            {"covered_lines": -1},
        ):
            with self.subTest(overrides=overrides):
                result, _ = self.run_policy(
                    {
                        "num_statements": 100,
                        "covered_lines": 100,
                        "num_branches": 20,
                        "covered_branches": 20,
                        **overrides,
                    }
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("invalid", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
