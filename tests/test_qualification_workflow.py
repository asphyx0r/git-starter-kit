"""Run the common CI decision boundaries with controlled job outcomes."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from test_workflow_contracts import BASH


ROOT = Path(__file__).resolve().parents[1]


class QualificationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(
            (ROOT / ".github/workflows/repository-audit.yml").read_text()
        )

    def step(self, job, name):
        matches = [
            s for s in self.workflow["jobs"][job]["steps"] if s.get("name") == name
        ]
        self.assertEqual(len(matches), 1, f"missing executable boundary {job}/{name}")
        return matches[0]

    def run_step(self, step, directory, environment):
        return subprocess.run(
            [BASH, "-c", step["run"]],
            cwd=directory,
            env={**os.environ, **environment},
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_aggregate_never_accepts_partial_heavy_or_failed_fresh_checks(self):
        step = self.step("repository-audit", "Require selected checks to succeed")
        base = {
            "ACTIVATION_RESULT": "success",
            "LINUX_RESULT": "success",
            "WINDOWS_RESULT": "success",
            "DECISION_RESULT": "success",
            "DECISION": "full",
            "SCOPE": "source",
            "HEAVY_LINUX_RESULT": "success",
            "HEAVY_WINDOWS_RESULT": "success",
        }
        for key in (
            "ACTIVATION_RESULT",
            "LINUX_RESULT",
            "WINDOWS_RESULT",
            "DECISION_RESULT",
            "HEAVY_LINUX_RESULT",
            "HEAVY_WINDOWS_RESULT",
        ):
            for result in ("failure", "skipped", "cancelled"):
                with self.subTest(key=key, result=result):
                    self.assertNotEqual(
                        self.run_step(step, ROOT, {**base, key: result}).returncode, 0
                    )
        self.assertEqual(self.run_step(step, ROOT, base).returncode, 0)
        reuse = {
            **base,
            "DECISION": "reuse",
            "HEAVY_LINUX_RESULT": "skipped",
            "HEAVY_WINDOWS_RESULT": "skipped",
        }
        self.assertEqual(self.run_step(step, ROOT, reuse).returncode, 0)
        for key in ("LINUX_RESULT", "WINDOWS_RESULT", "DECISION_RESULT"):
            self.assertNotEqual(
                self.run_step(step, ROOT, {**reuse, key: "failure"}).returncode, 0
            )
        self.assertNotEqual(
            self.run_step(step, ROOT, {**base, "DECISION": "unexpected"}).returncode, 0
        )

    def test_exported_consumer_decision_runs_without_source_helper(self):
        self.assertIn(
            "qualification", self.workflow["jobs"], "common decision is missing"
        )
        step = self.step("qualification", "Choose one qualification path")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs"
            result = self.run_step(
                step,
                temporary,
                {
                    "GH_REPO": "example/consumer",
                    "SCOPE": "project",
                    "GITHUB_OUTPUT": str(output),
                    "RUNNER_TEMP": temporary,
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("decision=full", output.read_text())

    def test_only_optional_predecision_transfers_can_fail_without_blocking_full(self):
        for job, name in (
            ("activation", "Retain candidate identity"),
            ("quality-linux", "Upload fresh environment"),
            ("compatibility-windows", "Upload fresh environment"),
        ):
            with self.subTest(job=job):
                self.assertIs(self.step(job, name).get("continue-on-error"), True)
        for job, name in (
            ("qualification", "Retain verified original pair"),
            ("quality-linux-heavy", "Upload measured linux qualification"),
            ("compatibility-windows-heavy", "Upload measured windows qualification"),
        ):
            with self.subTest(job=job):
                self.assertFalse(self.step(job, name).get("continue-on-error", False))
        for platform in ("linux", "windows"):
            self.assertIs(
                self.step("qualification", f"Download fresh {platform}")[
                    "continue-on-error"
                ],
                True,
            )
            self.assertEqual(
                self.step("repository-audit", f"Download fresh {platform}")[
                    "continue-on-error"
                ],
                "${{ needs.qualification.outputs.decision == 'full' }}",
            )

    def test_contract_rejects_independent_reuse_or_missing_fresh_dependency(self):
        self.assertEqual(len(self.workflow["jobs"]), 7)
        path = ROOT / "tools/repository-audit/workflow-contracts.py"
        spec = importlib.util.spec_from_file_location("qualification_contract", path)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        registry = json.loads((ROOT / "tools/quality/versions.json").read_text())
        for job in ("quality-linux-heavy", "compatibility-windows-heavy"):
            for change in ({"if": "true"}, {"needs": ["activation"]}):
                with self.subTest(job=job, change=change):
                    changed = copy.deepcopy(self.workflow)
                    changed["jobs"][job].update(change)
                    with self.assertRaises(validator.ContractError):
                        validator.validate_workflow(
                            "repository-audit", changed, registry
                        )

    def test_local_modes_keep_complete_order_without_hosted_environment(self):
        script = """set -euo pipefail
source tools/repository-audit.sh
run_static_before() { printf 'fresh\\n'; }
run_python_coverage() { printf 'python\\n'; }
run_shell_behavior_tests() { printf 'shell\\n'; }
run_static_after() { printf 'smoke-commitlint\\n'; }
run_project_checks() { printf 'project\\n'; }
main "$MODE"
"""
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GITHUB_")
            and key not in {"AUDIT_COMMIT_SHA", "ImageVersion", "AUDIT_COVERAGE_DIR"}
        }
        for mode in ("all", "full", "static"):
            result = subprocess.run(
                [BASH, "-c", script],
                cwd=ROOT,
                env={**environment, "MODE": mode},
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stages = [
                line
                for line in result.stdout.splitlines()
                if line in {"fresh", "python", "shell", "smoke-commitlint", "project"}
            ]
            self.assertEqual(
                stages, ["fresh", "python", "shell", "smoke-commitlint", "project"]
            )

    def test_real_test_reporter_cli_needs_no_hosted_identity(self):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GITHUB_")
            and key not in {"AUDIT_COMMIT_SHA", "ImageVersion"}
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tests").mkdir()
            test = root / "tests/test_sample.py"
            test.write_text(
                "import unittest\nclass Sample(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(2 + 2, 4)\n"
            )
            output = root / "tests.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tools/quality/coverage-artifacts.py"),
                    "tests",
                    "--output",
                    str(output),
                ],
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["run"], 1)

    def test_proof_lost_after_common_decision_fails_aggregate(self):
        step = self.step(
            "repository-audit", "Recheck transported original qualification"
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_step(step, ROOT, {"RUNNER_TEMP": temporary})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("packet.json", result.stderr)


if __name__ == "__main__":
    unittest.main()
