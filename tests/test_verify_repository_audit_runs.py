import importlib.util
import io
import json
import pathlib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from unittest.mock import patch


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "tools"
    / "verify-repository-audit-runs.py"
)
SPEC = importlib.util.spec_from_file_location(
    "verify_repository_audit_runs",
    MODULE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load Repository audit run verifier.")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SHA = "0" * 40
CREATED_AFTER = datetime(2026, 7, 31, 13, 41, tzinfo=UTC)


def make_run(
    run_id,
    ref_name,
    conclusion="success",
    event="push",
    workflow_id=123,
    status="completed",
    created_at="2026-07-31T13:42:00Z",
):
    return {
        "id": run_id,
        "run_attempt": 1,
        "workflow_id": workflow_id,
        "event": event,
        "head_branch": ref_name,
        "head_sha": SHA,
        "status": status,
        "conclusion": conclusion,
        "created_at": created_at,
        "html_url": f"https://example.test/runs/{run_id}",
    }


class VerifyRepositoryAuditRunsTests(unittest.TestCase):
    def wait_for(self, runs, refs=("main", "v1.1.1")):
        return MODULE._wait_for_runs(
            repository="owner/repository",
            workflow_id=123,
            sha=SHA,
            expected_refs=refs,
            created_after=CREATED_AFTER,
            timeout_seconds=0,
            poll_seconds=0,
            verbose=False,
            query_runs=lambda _repository, _sha: runs,
        )

    def test_failed_branch_blocks_green_tag_and_manual_run(self):
        runs = [
            make_run(1, "main", conclusion="failure"),
            make_run(2, "v1.1.1"),
            make_run(3, "main", event="workflow_dispatch"),
        ]

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "Repository audit failed for main",
        ):
            self.wait_for(runs)

    def test_manual_failure_does_not_replace_successful_push_runs(self):
        runs = [
            make_run(1, "main"),
            make_run(2, "v1.1.1"),
            make_run(
                3,
                "main",
                conclusion="failure",
                event="workflow_dispatch",
            ),
        ]

        verified = self.wait_for(runs)

        self.assertEqual(set(verified), {"main", "v1.1.1"})
        self.assertEqual(verified["main"]["id"], 1)

    def test_query_paginates_and_flattens_workflow_runs(self):
        response = MODULE.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                [
                    {"workflow_runs": [make_run(1, "main")]},
                    {"workflow_runs": [make_run(2, "v1.1.1")]},
                ]
            ),
            stderr="",
        )

        with (
            patch.object(MODULE.shutil, "which", return_value="gh"),
            patch.object(
                MODULE.subprocess,
                "run",
                return_value=response,
            ) as run_command,
        ):
            runs = MODULE._query_runs("owner/repository", SHA)

        self.assertEqual([run["id"] for run in runs], [1, 2])
        command = run_command.call_args.args[0]
        self.assertEqual(command[:4], ["gh", "api", "--paginate", "--slurp"])
        self.assertIn(f"head_sha={SHA}", command[4])
        self.assertIn("event=push", command[4])

    def test_run_before_push_does_not_satisfy_expected_ref(self):
        runs = [
            make_run(1, "main", created_at="2026-07-31T13:40:59Z"),
            make_run(2, "v1.1.1"),
        ]

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "Timed out waiting for Repository audit runs: main",
        ):
            self.wait_for(runs)

    def test_multiple_applicable_runs_are_ambiguous(self):
        runs = [
            make_run(1, "main"),
            make_run(2, "main"),
            make_run(3, "v1.1.1"),
        ]

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "Multiple applicable Repository audit runs found for main",
        ):
            self.wait_for(runs)

    def test_pending_run_times_out(self):
        runs = [
            make_run(1, "main", conclusion=None, status="in_progress"),
            make_run(2, "v1.1.1"),
        ]

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "Timed out waiting for Repository audit runs: main",
        ):
            self.wait_for(runs)

    def test_dry_run_reports_plan_without_querying_github(self):
        output = io.StringIO()
        args = [
            "--dry-run",
            "--repository",
            "owner/repository",
            "--workflow-id",
            "123",
            "--sha",
            SHA,
            "--ref",
            "main",
            "--created-after",
            "2026-07-31T13:41:00Z",
        ]

        with (
            patch.object(
                MODULE,
                "_wait_for_runs",
                side_effect=AssertionError("dry-run queried GitHub"),
            ),
            redirect_stdout(output),
        ):
            exit_code = MODULE.main(args)

        self.assertEqual(exit_code, 0)
        self.assertIn("Would verify Repository audit push runs", output.getvalue())

    def test_invalid_ref_returns_exit_one(self):
        args = [
            "--dry-run",
            "--repository",
            "owner/repository",
            "--workflow-id",
            "123",
            "--sha",
            SHA,
            "--ref",
            "invalid..ref",
            "--created-after",
            "2026-07-31T13:41:00Z",
        ]

        error_output = io.StringIO()
        with redirect_stderr(error_output):
            exit_code = MODULE.main(args)

        self.assertEqual(exit_code, 1)
        self.assertIn("Invalid expected ref", error_output.getvalue())

    def test_help_lists_repository_standard_options_first(self):
        option_order = [
            action.option_strings
            for action in MODULE._build_parser()._actions
            if action.option_strings
        ]

        self.assertEqual(
            option_order[:4],
            [
                ["-h", "--help"],
                ["--version"],
                ["--dry-run"],
                ["-v", "--verbose"],
            ],
        )

    def test_version_uses_semver_and_exits_zero(self):
        output = io.StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            MODULE.main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), "v1.0.0\n")


if __name__ == "__main__":
    unittest.main()
