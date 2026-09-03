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

    def test_snapshot_query_uses_thirty_second_subprocess_timeout(self):
        observed_timeouts = []

        def query_runs(_repository, _sha, timeout_seconds):
            observed_timeouts.append(timeout_seconds)
            return [make_run(1, "main"), make_run(2, "v1.1.1")]

        with patch.object(MODULE, "_query_runs", side_effect=query_runs):
            self.assertEqual(
                set(
                    MODULE._wait_for_runs(
                        repository="owner/repository",
                        workflow_id=123,
                        sha=SHA,
                        expected_refs=("main", "v1.1.1"),
                        created_after=CREATED_AFTER,
                        timeout_seconds=0,
                        poll_seconds=0,
                        verbose=False,
                    )
                ),
                {"main", "v1.1.1"},
            )
        self.assertEqual(observed_timeouts, [30])

    def test_wait_query_caps_positive_remaining_budget_at_thirty_seconds(self):
        observed_timeouts = []

        def query_runs(_repository, _sha, timeout_seconds):
            observed_timeouts.append(timeout_seconds)
            return [make_run(1, "main"), make_run(2, "v1.1.1")]

        with (
            patch.object(MODULE.time, "monotonic", side_effect=[100, 101]),
            patch.object(MODULE, "_query_runs", side_effect=query_runs),
        ):
            MODULE._wait_for_runs(
                repository="owner/repository",
                workflow_id=123,
                sha=SHA,
                expected_refs=("main", "v1.1.1"),
                created_after=CREATED_AFTER,
                timeout_seconds=100,
                poll_seconds=1,
                verbose=False,
            )

        self.assertEqual(observed_timeouts, [30])

    def test_wait_query_uses_remaining_global_timeout_when_less_than_thirty(self):
        observed_timeouts = []

        def query_runs(_repository, _sha, timeout_seconds):
            observed_timeouts.append(timeout_seconds)
            return [make_run(1, "main"), make_run(2, "v1.1.1")]

        with (
            patch.object(MODULE.time, "monotonic", side_effect=[100, 101]),
            patch.object(MODULE, "_query_runs", side_effect=query_runs),
        ):
            MODULE._wait_for_runs(
                repository="owner/repository",
                workflow_id=123,
                sha=SHA,
                expected_refs=("main", "v1.1.1"),
                created_after=CREATED_AFTER,
                timeout_seconds=5,
                poll_seconds=1,
                verbose=False,
            )

        self.assertEqual(observed_timeouts, [4])

    def test_pending_two_argument_query_exhausts_global_budget(self):
        calls = []

        def query_runs(_repository, _sha):
            calls.append((_repository, _sha))
            return [
                make_run(1, "main", conclusion=None, status="in_progress"),
                make_run(2, "v1.1.1"),
            ]

        with (
            patch.object(
                MODULE.time,
                "monotonic",
                side_effect=[100, 100, 101, 101, 102],
            ),
            patch.object(MODULE.time, "sleep") as sleep,
            self.assertRaisesRegex(
                MODULE.VerificationError,
                "Timed out waiting for Repository audit runs: main",
            ),
        ):
            MODULE._wait_for_runs(
                repository="owner/repository",
                workflow_id=123,
                sha=SHA,
                expected_refs=("main", "v1.1.1"),
                created_after=CREATED_AFTER,
                timeout_seconds=2,
                poll_seconds=1,
                verbose=False,
                query_runs=query_runs,
            )

        self.assertEqual(calls, [("owner/repository", SHA)])
        sleep.assert_called_once_with(1)

    def test_query_timeout_keeps_partial_stderr_context(self):
        timeout = MODULE.subprocess.TimeoutExpired(
            cmd=["gh", "api"],
            timeout=7,
            stderr="API did not respond",
        )

        with (
            patch.object(MODULE.shutil, "which", return_value="gh"),
            patch.object(MODULE.subprocess, "run", side_effect=timeout),
            self.assertRaisesRegex(
                MODULE.VerificationError,
                "timed out after 7 seconds: API did not respond",
            ),
        ):
            MODULE._query_runs("owner/repository", SHA, timeout_seconds=7)

    def test_query_timeout_decodes_byte_diagnostics(self):
        timeout = MODULE.subprocess.TimeoutExpired(
            cmd=["gh", "api"],
            timeout=3,
            output=b"gateway did not respond\xff",
        )

        with (
            patch.object(MODULE.shutil, "which", return_value="gh"),
            patch.object(MODULE.subprocess, "run", side_effect=timeout),
            self.assertRaisesRegex(
                MODULE.VerificationError,
                "timed out after 3 seconds: gateway did not respond",
            ),
        ):
            MODULE._query_runs("owner/repository", SHA, timeout_seconds=3)

    def test_query_requires_github_cli(self):
        with (
            patch.object(MODULE.shutil, "which", return_value=None),
            self.assertRaisesRegex(
                MODULE.VerificationError,
                "gh is required to inspect GitHub Actions runs",
            ),
        ):
            MODULE._query_runs("owner/repository", SHA)

    def test_query_reports_github_cli_failure_detail(self):
        response = MODULE.subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="authentication required\n",
        )

        with (
            patch.object(MODULE.shutil, "which", return_value="gh"),
            patch.object(MODULE.subprocess, "run", return_value=response),
            self.assertRaisesRegex(
                MODULE.VerificationError,
                "GitHub Actions query failed: authentication required",
            ),
        ):
            MODULE._query_runs("owner/repository", SHA)

    def test_query_rejects_malformed_workflow_run_responses(self):
        responses = (
            "not JSON",
            json.dumps({"workflow_runs": {"id": 1}}),
        )

        for response_body in responses:
            with self.subTest(response_body=response_body):
                response = MODULE.subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=response_body,
                    stderr="",
                )
                with (
                    patch.object(MODULE.shutil, "which", return_value="gh"),
                    patch.object(MODULE.subprocess, "run", return_value=response),
                    self.assertRaisesRegex(
                        MODULE.VerificationError,
                        "invalid workflow-runs response",
                    ),
                ):
                    MODULE._query_runs("owner/repository", SHA)

    def test_applicable_run_requires_valid_created_at(self):
        malformed_runs = (
            ({}, "has no created_at value"),
            ({"created_at": "July 31"}, "invalid created_at value: July 31"),
        )

        for run, message in malformed_runs:
            with self.subTest(run=run):
                with self.assertRaisesRegex(MODULE.VerificationError, message):
                    MODULE._parse_run_time(run)

    def test_unrelated_ref_and_workflow_runs_are_ignored(self):
        runs = [
            make_run(1, "main"),
            make_run(2, "v1.1.1"),
            make_run(3, "other"),
            make_run(4, "main", workflow_id=999),
        ]

        verified = self.wait_for(runs)

        self.assertEqual(
            {ref_name: run["id"] for ref_name, run in verified.items()},
            {"main": 1, "v1.1.1": 2},
        )

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

    def test_missing_required_options_return_exit_one(self):
        error_output = io.StringIO()

        with redirect_stderr(error_output):
            exit_code = MODULE.main([])

        self.assertEqual(exit_code, 1)
        self.assertIn("the following arguments are required", error_output.getvalue())

    def test_validation_rejects_unsafe_or_inconsistent_arguments(self):
        valid_arguments = {
            "repository": "owner/repository",
            "workflow_id": 123,
            "sha": SHA,
            "refs": ["main", "v1.1.1"],
            "created_after": "2026-07-31T13:41:00Z",
            "timeout_seconds": 600,
            "poll_seconds": 5,
        }
        scenarios = (
            ({"repository": "owner"}, "--repository must use the OWNER/REPO format"),
            ({"workflow_id": 0}, "--workflow-id must be positive"),
            ({"sha": "abc123"}, "--sha must contain exactly 40 hexadecimal"),
            ({"timeout_seconds": -1}, "--timeout-seconds must not be negative"),
            ({"poll_seconds": -1}, "--poll-seconds must not be negative"),
            (
                {"timeout_seconds": 1, "poll_seconds": 0},
                "--poll-seconds must be positive when waiting is enabled",
            ),
            ({"refs": ["main", "main"]}, "Each --ref value must be unique"),
            (
                {"created_after": "2026-07-31"},
                "--created-after must use YYYY-MM-DDTHH:MM:SSZ",
            ),
        )

        for replacements, message in scenarios:
            with self.subTest(replacements=replacements):
                arguments = MODULE.argparse.Namespace(
                    **{**valid_arguments, **replacements}
                )
                with self.assertRaisesRegex(MODULE.VerificationError, message):
                    MODULE._validate_args(arguments)

    def test_verbose_wait_reports_pending_ref_before_success(self):
        snapshots = [
            [
                make_run(1, "main", conclusion=None, status="in_progress"),
                make_run(2, "v1.1.1"),
            ],
            [make_run(1, "main"), make_run(2, "v1.1.1")],
        ]

        def query_runs(_repository, _sha):
            return snapshots.pop(0)

        error_output = io.StringIO()
        with (
            patch.object(
                MODULE.time,
                "monotonic",
                side_effect=[100, 100, 100, 100, 101],
            ),
            patch.object(MODULE.time, "sleep"),
            redirect_stderr(error_output),
        ):
            verified = MODULE._wait_for_runs(
                repository="owner/repository",
                workflow_id=123,
                sha=SHA,
                expected_refs=("main", "v1.1.1"),
                created_after=CREATED_AFTER,
                timeout_seconds=10,
                poll_seconds=1,
                verbose=True,
                query_runs=query_runs,
            )

        self.assertEqual(set(verified), {"main", "v1.1.1"})
        self.assertRegex(
            error_output.getvalue(),
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
            r"Waiting for Repository audit: main\n$",
        )

    def test_successful_cli_reports_each_verified_ref(self):
        args = [
            "--repository",
            "owner/repository",
            "--workflow-id",
            "123",
            "--sha",
            SHA,
            "--ref",
            "main",
            "--ref",
            "v1.1.1",
            "--created-after",
            "2026-07-31T13:41:00Z",
            "--timeout-seconds",
            "0",
            "--poll-seconds",
            "0",
        ]
        output = io.StringIO()

        with (
            patch.object(
                MODULE,
                "_query_runs",
                return_value=[make_run(1, "main"), make_run(2, "v1.1.1")],
            ),
            redirect_stdout(output),
        ):
            exit_code = MODULE.main(args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "Repository audit succeeded for main: run_id=1 attempt=1 "
                "status=completed conclusion=success "
                "url=https://example.test/runs/1",
                "Repository audit succeeded for v1.1.1: run_id=2 attempt=1 "
                "status=completed conclusion=success "
                "url=https://example.test/runs/2",
            ],
        )

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
