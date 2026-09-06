import base64
import hashlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / "tools" / "merge-pull-request.py"
)
REQUEST_ID = "12345678-1234-4abc-8def-1234567890ab"
HEAD_OID = "0123456789abcdef0123456789abcdef01234567"
MERGE_OID = "89abcdef0123456789abcdef0123456789abcdef"
REPOSITORY = "owner/repository"


def completed(arguments, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        arguments,
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def valid_payload(message):
    encoded = base64.b64encode(message).decode("ascii")
    return {
        "request_id": REQUEST_ID,
        "pull_request": 17,
        "expected_head_oid": HEAD_OID,
        "message_sha256": hashlib.sha256(message).hexdigest(),
        "message_base64": encoded,
    }


def valid_event(message=b"fix(git): guard squash merges\n"):
    return {
        "action": "guarded-squash-merge",
        "repository": {
            "full_name": REPOSITORY,
            "default_branch": "main",
        },
        "client_payload": valid_payload(message),
    }


def valid_pull_request(*, head_oid=HEAD_OID, cross_repository=False):
    return {
        "number": 17,
        "state": "OPEN",
        "isDraft": False,
        "headRefOid": head_oid,
        "baseRefName": "main",
        "isCrossRepository": cross_repository,
        "autoMergeRequest": None,
    }


def valid_mutation_state(
    *,
    head_oid=HEAD_OID,
    base_ref_name="main",
    auto_merge_request=None,
    in_queue=False,
    queue_enabled=False,
):
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "headRefOid": head_oid,
                    "baseRefName": base_ref_name,
                    "autoMergeRequest": auto_merge_request,
                    "isInMergeQueue": in_queue,
                    "isMergeQueueEnabled": queue_enabled,
                }
            }
        }
    }


def valid_checks():
    return [
        {
            "bucket": "pass",
            "event": "pull_request",
            "name": "Repository audit",
            "state": "SUCCESS",
            "workflow": "Repository audit",
        }
    ]


def valid_policy():
    return frozenset({"Repository audit"})


def load_module(test_case):
    test_case.assertTrue(MODULE_PATH.is_file(), "Guarded merge CLI is missing.")
    spec = importlib.util.spec_from_file_location("merge_pull_request", MODULE_PATH)
    test_case.assertIsNotNone(spec)
    test_case.assertIsNotNone(spec.loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MergePullRequestTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module(self)

    def write_bytes(self, value):
        temporary = tempfile.NamedTemporaryFile(delete=False)
        self.addCleanup(pathlib.Path(temporary.name).unlink, missing_ok=True)
        temporary.write(value)
        temporary.close()
        return pathlib.Path(temporary.name)

    def write_event(self, event):
        path = self.write_bytes(json.dumps(event).encode("utf-8"))
        return path

    def run_main(self, arguments):
        output = io.StringIO()
        error_output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error_output):
            result = self.module.main(arguments)
        return result, output.getvalue(), error_output.getvalue()

    def test_help_lists_global_options_in_contract_order(self):
        help_text = self.module._build_parser().format_help()
        option_text = help_text[help_text.index("options:") :]

        positions = [
            option_text.index("-h, --help"),
            option_text.index("--version"),
            option_text.index("--dry-run"),
            option_text.index("-v, --verbose"),
        ]

        self.assertEqual(positions, sorted(positions))
        request_help = (
            self.module._build_parser()
            ._subparsers._group_actions[0]
            .choices["request"]
            .format_help()
        )
        self.assertIn("--force", request_help)
        self.assertIn("finite", request_help)
        execute_help = (
            self.module._build_parser()
            ._subparsers._group_actions[0]
            .choices["execute"]
            .format_help()
        )
        self.assertNotIn("--force", execute_help)

    def test_version_is_v0_1_0(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            self.module._build_parser().parse_args(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), "v0.1.0\n")

    def test_usage_errors_exit_two(self):
        error_output = io.StringIO()
        with redirect_stderr(error_output), self.assertRaises(SystemExit) as raised:
            self.module.main(["execute"])

        self.assertEqual(raised.exception.code, 2)

    def test_message_accepts_subject_only_without_normalizing(self):
        path = self.write_bytes(b"fix(git): preserve exact bytes\n")

        message = self.module._read_merge_message(path)

        self.assertEqual(message.subject, "fix(git): preserve exact bytes")
        self.assertEqual(message.body, b"")
        self.assertEqual(message.raw, path.read_bytes())

    def test_message_accepts_unicode_body_without_normalizing(self):
        raw = "fix(git): preserve unicode\n\nKeep \u6771\u4eac exact.\n".encode()
        path = self.write_bytes(raw)

        message = self.module._read_merge_message(path)

        self.assertEqual(message.subject, "fix(git): preserve unicode")
        self.assertEqual(message.body, "Keep \u6771\u4eac exact.\n".encode())
        self.assertEqual(message.raw, raw)

    def test_message_rejects_bom_crlf_nul_and_final_lf_errors(self):
        invalid_messages = {
            "BOM": b"\xef\xbb\xbffix(git): reject bom\n",
            "CRLF": b"fix(git): reject crlf\r\n",
            "NUL": b"fix(git): reject \x00 nul\n",
            "missing its final LF": b"fix(git): require final lf",
            "more than one final LF": b"fix(git): reject extra lf\n\n",
            "message shape": b"fix(git): reject body\nbody\n",
        }

        for diagnostic, raw in invalid_messages.items():
            with self.subTest(diagnostic=diagnostic):
                with self.assertRaisesRegex(self.module.MergeRequestError, diagnostic):
                    self.module._read_merge_message(self.write_bytes(raw))

    def test_message_rejects_empty_and_invalid_utf8(self):
        for diagnostic, raw in (("non-empty", b""), ("UTF-8", b"\xff\n")):
            with self.subTest(diagnostic=diagnostic):
                with self.assertRaisesRegex(self.module.MergeRequestError, diagnostic):
                    self.module._read_merge_message(self.write_bytes(raw))

    def test_message_rejects_a_multiline_subject_before_the_separator(self):
        raw = b"fix(git): reject multiline subject\nextra\n\nbody\n"

        with self.assertRaisesRegex(self.module.MergeRequestError, "message shape"):
            self.module._read_merge_message(self.write_bytes(raw))

    def test_client_payload_contains_only_exact_fields(self):
        message = self.module.MergeMessage(
            raw=b"fix(git): seal message\n",
            subject="fix(git): seal message",
            body=b"",
        )

        payload, serialized = self.module._build_client_payload(
            request_id=REQUEST_ID,
            pull_request=17,
            expected_head_oid=HEAD_OID,
            message=message,
        )

        self.assertEqual(payload, valid_payload(message.raw))
        self.assertEqual(serialized, json.dumps(payload, separators=(",", ":")))

    def test_client_payload_rejects_more_than_65535_serialized_characters(self):
        message = self.module.MergeMessage(
            raw=b"fix(git): large message\n\n" + b"x" * 50_000 + b"\n",
            subject="fix(git): large message",
            body=b"x" * 50_000 + b"\n",
        )

        with self.assertRaisesRegex(self.module.MergeRequestError, "65,535"):
            self.module._build_client_payload(
                request_id=REQUEST_ID,
                pull_request=17,
                expected_head_oid=HEAD_OID,
                message=message,
            )

    def test_dispatch_uses_one_exact_repository_dispatch_body(self):
        payload = valid_payload(b"fix(git): dispatch exact bytes\n")
        with patch.object(
            self.module,
            "_run_gh",
            return_value=completed([]),
        ) as gh:
            self.module._dispatch_request(REPOSITORY, payload, REQUEST_ID)

        self.assertEqual(
            gh.call_args.args[0],
            [
                "api",
                "--method",
                "POST",
                f"repos/{REPOSITORY}/dispatches",
                "--input",
                "-",
            ],
        )
        self.assertEqual(
            json.loads(gh.call_args.kwargs["input_text"]),
            {"event_type": "guarded-squash-merge", "client_payload": payload},
        )

    def test_dispatch_timeout_is_ambiguous_with_uuid_and_is_not_retried(self):
        payload = valid_payload(b"fix(git): dispatch once\n")
        with (
            patch.object(self.module, "_resolve_gh_command", return_value="gh"),
            patch.object(
                self.module.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["gh", "api"], 30),
            ) as run,
        ):
            with self.assertRaisesRegex(
                self.module.AmbiguousDispatchError,
                f"Guarded merge {REQUEST_ID}",
            ):
                self.module._dispatch_request(REPOSITORY, payload, REQUEST_ID)

        run.assert_called_once()

    def test_event_rejects_invalid_base64_hash_uuid_sha_and_extra_fields(self):
        mutations = {
            "Base64": lambda event: event["client_payload"].__setitem__(
                "message_base64", "***"
            ),
            "SHA-256": lambda event: event["client_payload"].__setitem__(
                "message_sha256", "0" * 64
            ),
            "UUID": lambda event: event["client_payload"].__setitem__(
                "request_id", "not-a-uuid"
            ),
            "head SHA": lambda event: event["client_payload"].__setitem__(
                "expected_head_oid", "abc"
            ),
            "exact fields": lambda event: event["client_payload"].__setitem__(
                "repository", REPOSITORY
            ),
        }

        for diagnostic, mutate in mutations.items():
            with self.subTest(diagnostic=diagnostic):
                event = valid_event()
                mutate(event)
                with self.assertRaisesRegex(self.module.MergeRequestError, diagnostic):
                    self.module._read_dispatch_event(self.write_event(event))

    def test_event_rejects_wrong_action_and_untrusted_repository_shape(self):
        for diagnostic, mutate in (
            (
                "event type",
                lambda event: event.__setitem__("action", "other"),
            ),
            (
                "repository",
                lambda event: event.__setitem__("repository", {"full_name": "bad"}),
            ),
        ):
            with self.subTest(diagnostic=diagnostic):
                event = valid_event()
                mutate(event)
                with self.assertRaisesRegex(self.module.MergeRequestError, diagnostic):
                    self.module._read_dispatch_event(self.write_event(event))

    def test_pull_request_accepts_fork_when_identity_and_checks_match(self):
        pull_request_response = valid_pull_request(cross_repository=True)
        responses = [pull_request_response, valid_checks(), pull_request_response]
        with (
            patch.object(
                self.module,
                "_load_guard_policy",
                return_value=valid_policy(),
            ),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=responses,
            ) as gh_json,
            patch.object(
                self.module,
                "_load_pull_request_mutation_state",
                return_value=(HEAD_OID, "main", False, False, False),
                create=True,
            ),
        ):
            pull_request = self.module._validate_pull_request(
                REPOSITORY,
                "main",
                17,
                HEAD_OID,
            )

        self.assertTrue(pull_request["isCrossRepository"])
        self.assertEqual(gh_json.call_count, 2)
        self.assertEqual(
            gh_json.call_args_list[0].args[0],
            [
                "pr",
                "view",
                "17",
                "--repo",
                REPOSITORY,
                "--json",
                "number,state,isDraft,headRefOid,baseRefName,isCrossRepository,"
                "autoMergeRequest",
            ],
        )

    def test_pull_request_rejects_stale_head_before_merge(self):
        with (
            patch.object(
                self.module,
                "_load_guard_policy",
                return_value=valid_policy(),
            ),
            patch.object(
                self.module,
                "_run_gh_json",
                return_value=valid_pull_request(head_oid="f" * 40),
            ) as gh_json,
        ):
            with self.assertRaisesRegex(self.module.MergeRequestError, "head changed"):
                self.module._validate_pull_request(
                    REPOSITORY,
                    "main",
                    17,
                    HEAD_OID,
                )

        self.assertEqual(gh_json.call_count, 1)

    def test_pull_request_rejects_closed_draft_wrong_base_and_failed_checks(self):
        pull_request_mutations = (
            ("open", lambda pr: pr.__setitem__("state", "CLOSED")),
            ("draft", lambda pr: pr.__setitem__("isDraft", True)),
            ("default branch", lambda pr: pr.__setitem__("baseRefName", "other")),
        )
        for diagnostic, mutate in pull_request_mutations:
            with self.subTest(diagnostic=diagnostic):
                pull_request = valid_pull_request()
                mutate(pull_request)
                with (
                    patch.object(
                        self.module,
                        "_load_guard_policy",
                        return_value=valid_policy(),
                    ),
                    patch.object(
                        self.module,
                        "_run_gh_json",
                        return_value=pull_request,
                    ),
                ):
                    with self.assertRaisesRegex(
                        self.module.MergeRequestError,
                        diagnostic,
                    ):
                        self.module._validate_pull_request(
                            REPOSITORY,
                            "main",
                            17,
                            HEAD_OID,
                        )

        failed_checks = valid_checks()
        failed_checks[0]["state"] = "FAILURE"
        with (
            patch.object(
                self.module,
                "_load_guard_policy",
                return_value=valid_policy(),
            ),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[valid_pull_request(), failed_checks],
            ),
            patch.object(
                self.module,
                "_load_pull_request_mutation_state",
                return_value=(HEAD_OID, "main", False, False, False),
                create=True,
            ),
        ):
            with self.assertRaisesRegex(
                self.module.MergeRequestError, "required check"
            ):
                self.module._validate_pull_request(
                    REPOSITORY,
                    "main",
                    17,
                    HEAD_OID,
                )

    def test_pull_request_requires_repository_audit_from_pull_request(self):
        for diagnostic, checks in (
            ("Repository audit", []),
            (
                "pull_request",
                [dict(valid_checks()[0], event="workflow_dispatch")],
            ),
        ):
            with self.subTest(diagnostic=diagnostic):
                with (
                    patch.object(
                        self.module,
                        "_load_guard_policy",
                        return_value=valid_policy(),
                    ),
                    patch.object(
                        self.module,
                        "_run_gh_json",
                        side_effect=[valid_pull_request(), checks],
                    ),
                    patch.object(
                        self.module,
                        "_load_pull_request_mutation_state",
                        return_value=(HEAD_OID, "main", False, False, False),
                        create=True,
                    ),
                ):
                    with self.assertRaisesRegex(
                        self.module.MergeRequestError,
                        diagnostic,
                    ):
                        self.module._validate_pull_request(
                            REPOSITORY,
                            "main",
                            17,
                            HEAD_OID,
                        )

    def test_pull_request_requires_repository_audit_in_effective_rules(self):
        with (
            patch.object(
                self.module,
                "_load_guard_policy",
                return_value=frozenset(),
            ),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[
                    valid_pull_request(),
                    valid_checks(),
                    valid_pull_request(),
                ],
            ),
        ):
            with self.assertRaisesRegex(
                self.module.MergeRequestError,
                "Repository audit.*required",
            ):
                self.module._validate_pull_request(
                    REPOSITORY,
                    "main",
                    17,
                    HEAD_OID,
                )

    def test_pull_request_accepts_one_passing_pull_request_audit_among_others(self):
        checks = [
            dict(valid_checks()[0], event="workflow_dispatch"),
            valid_checks()[0],
        ]
        pull_request_response = valid_pull_request()
        with (
            patch.object(
                self.module,
                "_load_guard_policy",
                return_value=valid_policy(),
            ),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[pull_request_response, checks, pull_request_response],
            ),
            patch.object(
                self.module,
                "_load_pull_request_mutation_state",
                return_value=(HEAD_OID, "main", False, False, False),
                create=True,
            ),
        ):
            result = self.module._validate_pull_request(
                REPOSITORY,
                "main",
                17,
                HEAD_OID,
            )

        self.assertEqual(result["number"], 17)

    def test_guard_policy_rejects_auto_merge_and_merge_queue(self):
        required_rule = {
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [
                    {"context": "Repository audit", "integration_id": None}
                ]
            },
        }
        for diagnostic, repository_value, rules in (
            (
                "auto-merge",
                {"data": {"repository": {"autoMergeAllowed": True}}},
                [[required_rule]],
            ),
            (
                "merge queue",
                {"data": {"repository": {"autoMergeAllowed": False}}},
                [[required_rule, {"type": "merge_queue", "parameters": {}}]],
            ),
        ):
            with self.subTest(diagnostic=diagnostic):
                with patch.object(
                    self.module,
                    "_run_gh_json",
                    side_effect=[repository_value, rules],
                ):
                    with self.assertRaisesRegex(
                        self.module.MergeRequestError,
                        diagnostic,
                    ):
                        self.module._load_guard_policy(REPOSITORY, "main")

    def test_guard_policy_reads_all_effective_default_branch_rules(self):
        required_rule = {
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [
                    {"context": "Repository audit", "integration_id": None},
                    {"context": "Unit tests", "integration_id": None},
                ]
            },
        }
        with patch.object(
            self.module,
            "_run_gh_json",
            side_effect=[
                {"data": {"repository": {"autoMergeAllowed": False}}},
                [[required_rule], [{"type": "pull_request", "parameters": {}}]],
            ],
        ) as gh_json:
            required_checks = self.module._load_guard_policy(
                REPOSITORY,
                "release/next",
            )

        self.assertEqual(
            required_checks,
            frozenset({"Repository audit", "Unit tests"}),
        )
        self.assertEqual(
            gh_json.call_args_list[0].args[0],
            [
                "api",
                "graphql",
                "-f",
                "query=query RepositoryAutoMergePolicy("
                "$owner: String!, $repository: String!) { "
                "repository(owner: $owner, name: $repository) { "
                "autoMergeAllowed } }",
                "-F",
                "owner=owner",
                "-F",
                "repository=repository",
            ],
        )
        self.assertEqual(
            gh_json.call_args_list[1].args[0],
            [
                "api",
                "--paginate",
                "--slurp",
                "repos/owner/repository/rules/branches/release%2Fnext?per_page=100",
            ],
        )

    def test_guard_policy_accepts_only_supported_integration_ids(self):
        for integration_id in (None, 1, 15368):
            with self.subTest(integration_id=integration_id):
                rules = [
                    [
                        {
                            "type": "required_status_checks",
                            "parameters": {
                                "required_status_checks": [
                                    {
                                        "context": "Repository audit",
                                        "integration_id": integration_id,
                                    }
                                ]
                            },
                        }
                    ]
                ]
                with patch.object(
                    self.module,
                    "_run_gh_json",
                    side_effect=[
                        {"data": {"repository": {"autoMergeAllowed": False}}},
                        rules,
                    ],
                ):
                    self.assertEqual(
                        self.module._load_guard_policy(REPOSITORY, "main"),
                        frozenset({"Repository audit"}),
                    )

        for integration_id in (True, False, "15368", 0, -1):
            with self.subTest(integration_id=integration_id):
                rules = [
                    [
                        {
                            "type": "required_status_checks",
                            "parameters": {
                                "required_status_checks": [
                                    {
                                        "context": "Repository audit",
                                        "integration_id": integration_id,
                                    }
                                ]
                            },
                        }
                    ]
                ]
                with patch.object(
                    self.module,
                    "_run_gh_json",
                    side_effect=[
                        {"data": {"repository": {"autoMergeAllowed": False}}},
                        rules,
                    ],
                ):
                    with self.assertRaisesRegex(
                        self.module.MergeRequestError,
                        "required-status-check",
                    ):
                        self.module._load_guard_policy(REPOSITORY, "main")

    def test_guard_policy_rejects_unsupported_required_check_shape(self):
        rules = [[{"type": "required_status_checks", "parameters": {}}]]
        with patch.object(
            self.module,
            "_run_gh_json",
            side_effect=[
                {"data": {"repository": {"autoMergeAllowed": False}}},
                rules,
            ],
        ):
            with self.assertRaisesRegex(
                self.module.MergeRequestError,
                "required-status-check",
            ):
                self.module._load_guard_policy(REPOSITORY, "main")

    def test_guard_policy_rejects_missing_or_ambiguous_auto_merge_policy(self):
        for response in (
            None,
            [],
            {},
            {"allow_auto_merge": False},
            {"data": None},
            {"data": {}},
            {"data": {"repository": None}},
            {"data": {"repository": {}}},
            {"data": {"repository": {"autoMergeAllowed": None}}},
            {"data": {"repository": {"autoMergeAllowed": 0}}},
            {"data": {"repository": {"autoMergeAllowed": "false"}}},
            {
                "data": {"repository": {"autoMergeAllowed": False}},
                "errors": [{"message": "Policy access denied"}],
            },
        ):
            with self.subTest(response=response):
                with patch.object(
                    self.module, "_run_gh_json", return_value=response
                ) as gh_json:
                    with self.assertRaisesRegex(
                        self.module.MergeRequestError, "auto-merge policy"
                    ):
                        self.module._load_guard_policy(REPOSITORY, "main")
                self.assertEqual(gh_json.call_count, 1)

    def test_pull_request_rejects_auto_merge_and_missing_required_context(self):
        auto_merge = dict(valid_pull_request(), autoMergeRequest={"enabledAt": "now"})
        with (
            patch.object(
                self.module,
                "_load_guard_policy",
                return_value=valid_policy(),
            ),
            patch.object(self.module, "_run_gh_json", return_value=auto_merge),
        ):
            with self.assertRaisesRegex(self.module.MergeRequestError, "auto-merge"):
                self.module._validate_pull_request(REPOSITORY, "main", 17, HEAD_OID)

        with (
            patch.object(
                self.module,
                "_load_guard_policy",
                return_value=frozenset({"Repository audit", "Unit tests"}),
            ),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[valid_pull_request(), valid_checks()],
            ),
            patch.object(
                self.module,
                "_load_pull_request_mutation_state",
                return_value=(HEAD_OID, "main", False, False, False),
                create=True,
            ),
        ):
            with self.assertRaisesRegex(
                self.module.MergeRequestError,
                "Unit tests",
            ):
                self.module._validate_pull_request(REPOSITORY, "main", 17, HEAD_OID)

    def test_mutation_state_query_uses_exact_graphql_argv_and_validates_response(self):
        expected_query = """query PullRequestMergeQueueState(
  $owner: String!
  $repository: String!
  $number: Int!
) {
  repository(owner: $owner, name: $repository) {
    pullRequest(number: $number) {
      headRefOid
      baseRefName
      autoMergeRequest {
        enabledAt
      }
      isInMergeQueue
      isMergeQueueEnabled
    }
  }
}"""
        with patch.object(
            self.module,
            "_run_gh_json",
            return_value=valid_mutation_state(),
        ) as gh_json:
            state = self.module._load_pull_request_mutation_state(REPOSITORY, 17)

        self.assertEqual(state, (HEAD_OID, "main", False, False, False))
        gh_json.assert_called_once_with(
            [
                "api",
                "graphql",
                "-f",
                f"query={expected_query}",
                "-F",
                "owner=owner",
                "-F",
                "repository=repository",
                "-F",
                "number=17",
            ]
        )

        for response in (
            valid_mutation_state(in_queue=None),
            valid_mutation_state(queue_enabled="false"),
            valid_mutation_state(head_oid="invalid"),
            valid_mutation_state(base_ref_name=""),
            valid_mutation_state(base_ref_name=17),
            valid_mutation_state(auto_merge_request={"enabledAt": None}),
            dict(valid_mutation_state(), unexpected=True),
            {"data": {"repository": {"pullRequest": None}}},
        ):
            with self.subTest(response=response):
                with patch.object(
                    self.module,
                    "_run_gh_json",
                    return_value=response,
                ):
                    with self.assertRaisesRegex(
                        self.module.MergeRequestError,
                        "mutation state",
                    ):
                        self.module._load_pull_request_mutation_state(REPOSITORY, 17)

    def test_pull_request_rejects_active_merge_queue_state(self):
        for mutation_state in (
            (HEAD_OID, "main", False, True, False),
            (HEAD_OID, "main", False, False, True),
        ):
            with self.subTest(mutation_state=mutation_state):
                with (
                    patch.object(
                        self.module,
                        "_load_guard_policy",
                        return_value=valid_policy(),
                    ),
                    patch.object(
                        self.module,
                        "_run_gh_json",
                        side_effect=[valid_pull_request(), valid_checks()],
                    ),
                    patch.object(
                        self.module,
                        "_load_pull_request_mutation_state",
                        return_value=mutation_state,
                        create=True,
                    ),
                ):
                    with self.assertRaisesRegex(
                        self.module.MergeRequestError,
                        "merge queue",
                    ):
                        self.module._validate_pull_request(
                            REPOSITORY,
                            "main",
                            17,
                            HEAD_OID,
                        )

    def test_pull_request_binds_audit_workflow_and_rechecks_head(self):
        wrong_workflow = [dict(valid_checks()[0], workflow="Other workflow")]
        for diagnostic, checks, mutation_state in (
            (
                "workflow",
                wrong_workflow,
                (HEAD_OID, "main", False, False, False),
            ),
            (
                "head changed",
                valid_checks(),
                ("f" * 40, "main", False, False, False),
            ),
            (
                "auto-merge",
                valid_checks(),
                (HEAD_OID, "main", True, False, False),
            ),
        ):
            with self.subTest(diagnostic=diagnostic):
                with (
                    patch.object(
                        self.module,
                        "_load_guard_policy",
                        return_value=valid_policy(),
                    ),
                    patch.object(
                        self.module,
                        "_run_gh_json",
                        side_effect=[valid_pull_request(), checks],
                    ),
                    patch.object(
                        self.module,
                        "_load_pull_request_mutation_state",
                        return_value=mutation_state,
                        create=True,
                    ),
                ):
                    with self.assertRaisesRegex(
                        self.module.MergeRequestError,
                        diagnostic,
                    ):
                        self.module._validate_pull_request(
                            REPOSITORY,
                            "main",
                            17,
                            HEAD_OID,
                        )

    def test_request_dry_run_validates_but_does_not_confirm_or_dispatch(self):
        message_path = self.write_bytes(b"fix(git): dry run\n")
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_dispatch_request") as dispatch,
            patch("builtins.input", side_effect=AssertionError("unexpected prompt")),
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
        ):
            code, output, error_output = self.run_main(
                [
                    "--dry-run",
                    "request",
                    "--pull-request",
                    "17",
                    "--message-file",
                    str(message_path),
                    "--repository",
                    REPOSITORY,
                ]
            )

        self.assertEqual(code, 0, error_output)
        self.assertIn("Would dispatch guarded-squash-merge", output)
        dispatch.assert_not_called()

    def test_request_requires_exact_uppercase_y_confirmation(self):
        message_path = self.write_bytes(b"fix(git): ask first\n")
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
            patch.object(self.module, "_dispatch_request") as dispatch,
            patch("builtins.input", return_value="y"),
        ):
            code, _, error_output = self.run_main(
                [
                    "request",
                    "--pull-request",
                    "17",
                    "--message-file",
                    str(message_path),
                    "--repository",
                    REPOSITORY,
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("cancelled", error_output)
        dispatch.assert_not_called()

    def test_force_request_dispatches_once_and_correlates_exact_run_name(self):
        message_path = self.write_bytes(b"fix(git): dispatch once\n")
        run = {
            "display_title": f"Guarded merge {REQUEST_ID}",
            "event": "repository_dispatch",
            "path": ".github/workflows/guarded-pull-request-merge.yml",
            "head_branch": "main",
            "head_sha": HEAD_OID,
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://example.test/runs/1",
        }
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_dispatch_request") as dispatch,
            patch.object(
                self.module,
                "_query_dispatch_runs",
                return_value=[run],
            ),
            patch.object(self.module, "_verify_postcondition") as verify,
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
        ):
            code, output, error_output = self.run_main(
                [
                    "request",
                    "--force",
                    "--pull-request",
                    "17",
                    "--message-file",
                    str(message_path),
                    "--repository",
                    REPOSITORY,
                ]
            )

        self.assertEqual(code, 0, error_output)
        dispatch.assert_called_once()
        verify.assert_called_once()
        self.assertIn(f"Guarded merge {REQUEST_ID}", output)

    def test_request_flushes_uuid_before_dispatch_starts(self):
        message_path = self.write_bytes(b"fix(git): expose dispatch identity\n")
        run = {
            "display_title": f"Guarded merge {REQUEST_ID}",
            "event": "repository_dispatch",
            "path": ".github/workflows/guarded-pull-request-merge.yml",
            "head_branch": "main",
            "head_sha": HEAD_OID,
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://example.test/runs/1",
        }

        class FlushTrackingOutput(io.StringIO):
            def __init__(self):
                super().__init__()
                self.flush_count = 0

            def flush(self):
                self.flush_count += 1
                super().flush()

        output = FlushTrackingOutput()

        def dispatch(_repository, _payload, _request_id):
            self.assertIn(f"Guarded merge {REQUEST_ID}", output.getvalue())
            self.assertGreater(output.flush_count, 0)

        args = self.module._build_parser().parse_args(
            [
                "request",
                "--force",
                "--pull-request",
                "17",
                "--message-file",
                str(message_path),
                "--repository",
                REPOSITORY,
            ]
        )
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_dispatch_request", side_effect=dispatch),
            patch.object(self.module, "_wait_for_dispatch_run", return_value=run),
            patch.object(self.module, "_verify_postcondition") as verify,
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
            redirect_stdout(output),
        ):
            result = self.module._request(args)

        self.assertEqual(result, 0)
        verify.assert_called_once()

    def test_request_correlates_after_ambiguous_dispatch_without_retry(self):
        message_path = self.write_bytes(b"fix(git): recover dispatch response\n")
        run = {
            "display_title": f"Guarded merge {REQUEST_ID}",
            "event": "repository_dispatch",
            "path": ".github/workflows/guarded-pull-request-merge.yml",
            "head_branch": "main",
            "head_sha": HEAD_OID,
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://example.test/runs/3",
        }
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(
                self.module,
                "_dispatch_request",
                side_effect=self.module.AmbiguousDispatchError(
                    f"Guarded merge {REQUEST_ID}: response lost"
                ),
            ) as dispatch,
            patch.object(self.module, "_query_dispatch_runs", return_value=[run]),
            patch.object(self.module, "_verify_postcondition") as verify,
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
        ):
            code, output, error_output = self.run_main(
                [
                    "request",
                    "--force",
                    "--pull-request",
                    "17",
                    "--message-file",
                    str(message_path),
                    "--repository",
                    REPOSITORY,
                ]
            )

        self.assertEqual(code, 0, error_output)
        self.assertIn(f"Guarded merge {REQUEST_ID}", output)
        dispatch.assert_called_once()
        verify.assert_called_once()

    def test_request_green_run_uses_postcondition_to_classify_outcome(self):
        message_path = self.write_bytes(b"fix(git): verify green workflow\n")
        successful_run = {
            "display_title": f"Guarded merge {REQUEST_ID}",
            "event": "repository_dispatch",
            "path": ".github/workflows/guarded-pull-request-merge.yml",
            "head_branch": "main",
            "head_sha": HEAD_OID,
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://example.test/runs/5",
        }
        for postcondition_error, expected_code, diagnostic in (
            (None, 0, "succeeded"),
            (
                self.module.UnmergedPullRequestError("not merged"),
                1,
                "not merged",
            ),
            (
                self.module.MergeRequestError("conflicting message"),
                3,
                "conflicting message",
            ),
        ):
            with self.subTest(expected_code=expected_code):
                verify_kwargs = (
                    {"return_value": None}
                    if postcondition_error is None
                    else {"side_effect": postcondition_error}
                )
                with (
                    patch.object(self.module, "_validate_message_with_commitlint"),
                    patch.object(
                        self.module,
                        "_resolve_repository",
                        return_value=(REPOSITORY, "main"),
                    ),
                    patch.object(
                        self.module,
                        "_validate_pull_request",
                        return_value=valid_pull_request(),
                    ),
                    patch.object(self.module, "_dispatch_request"),
                    patch.object(
                        self.module,
                        "_query_dispatch_runs",
                        return_value=[successful_run],
                    ),
                    patch.object(
                        self.module,
                        "_verify_postcondition",
                        **verify_kwargs,
                    ),
                    patch.object(
                        self.module.uuid,
                        "uuid4",
                        return_value=uuid.UUID(REQUEST_ID),
                    ),
                ):
                    code, output, error_output = self.run_main(
                        [
                            "request",
                            "--force",
                            "--pull-request",
                            "17",
                            "--message-file",
                            str(message_path),
                            "--repository",
                            REPOSITORY,
                        ]
                    )

                diagnostic_output = output if expected_code == 0 else error_output
                self.assertEqual(code, expected_code, diagnostic_output)
                self.assertIn(diagnostic, diagnostic_output)
                if expected_code == 3:
                    self.assertIn(
                        f"Guarded merge {REQUEST_ID}",
                        diagnostic_output,
                    )

    def test_request_post_dispatch_temporary_directory_failure_is_indeterminate(self):
        message_path = self.write_bytes(b"fix(git): classify post-dispatch io\n")
        pre_dispatch_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(pre_dispatch_temporary.cleanup)
        run = {
            "display_title": f"Guarded merge {REQUEST_ID}",
            "event": "repository_dispatch",
            "path": ".github/workflows/guarded-pull-request-merge.yml",
            "head_branch": "main",
            "head_sha": HEAD_OID,
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://example.test/runs/6",
        }
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_dispatch_request") as dispatch,
            patch.object(self.module, "_wait_for_dispatch_run", return_value=run),
            patch.object(
                self.module.tempfile,
                "TemporaryDirectory",
                side_effect=[
                    pre_dispatch_temporary,
                    OSError("post-dispatch temporary storage unavailable"),
                ],
            ),
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
        ):
            try:
                code, _, error_output = self.run_main(
                    [
                        "request",
                        "--force",
                        "--pull-request",
                        "17",
                        "--message-file",
                        str(message_path),
                        "--repository",
                        REPOSITORY,
                    ]
                )
            except OSError as error:
                self.fail(f"post-dispatch OSError escaped: {error}")

        self.assertEqual(code, 3, error_output)
        self.assertIn(f"Guarded merge {REQUEST_ID}", error_output)
        self.assertIn("temporary storage unavailable", error_output)
        dispatch.assert_called_once()

    def test_request_reports_workflow_failure_as_exit_one(self):
        message_path = self.write_bytes(b"fix(git): report failure\n")
        failed_run = {
            "display_title": f"Guarded merge {REQUEST_ID}",
            "event": "repository_dispatch",
            "path": ".github/workflows/guarded-pull-request-merge.yml",
            "head_branch": "main",
            "head_sha": HEAD_OID,
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://example.test/runs/2",
        }
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_dispatch_request"),
            patch.object(
                self.module,
                "_query_dispatch_runs",
                return_value=[failed_run],
            ),
            patch.object(
                self.module,
                "_verify_postcondition",
                side_effect=self.module.UnmergedPullRequestError(
                    "The pull request is not merged."
                ),
            ),
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
        ):
            code, _, error_output = self.run_main(
                [
                    "request",
                    "--force",
                    "--pull-request",
                    "17",
                    "--message-file",
                    str(message_path),
                    "--repository",
                    REPOSITORY,
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("conclusion=failure", error_output)

    def test_request_recovers_exact_success_and_preserves_uncertain_failures(self):
        message_path = self.write_bytes(b"fix(git): inspect failed workflow\n")
        failed_run = {
            "display_title": f"Guarded merge {REQUEST_ID}",
            "event": "repository_dispatch",
            "path": ".github/workflows/guarded-pull-request-merge.yml",
            "head_branch": "main",
            "head_sha": HEAD_OID,
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://example.test/runs/4",
        }
        for postcondition_error, expected_code, diagnostic in (
            (None, 0, "confirmed from the exact postcondition"),
            (
                self.module.MergeRequestError("message does not match"),
                3,
                "message does not match",
            ),
            (
                self.module.MergeRequestError("post-merge read unavailable"),
                3,
                "post-merge read unavailable",
            ),
        ):
            with self.subTest(expected_code=expected_code, diagnostic=diagnostic):
                verify_kwargs = (
                    {"return_value": None}
                    if postcondition_error is None
                    else {"side_effect": postcondition_error}
                )
                with (
                    patch.object(self.module, "_validate_message_with_commitlint"),
                    patch.object(
                        self.module,
                        "_resolve_repository",
                        return_value=(REPOSITORY, "main"),
                    ),
                    patch.object(
                        self.module,
                        "_validate_pull_request",
                        return_value=valid_pull_request(),
                    ),
                    patch.object(self.module, "_dispatch_request"),
                    patch.object(
                        self.module,
                        "_query_dispatch_runs",
                        return_value=[failed_run],
                    ),
                    patch.object(
                        self.module,
                        "_verify_postcondition",
                        **verify_kwargs,
                    ),
                    patch.object(
                        self.module.uuid,
                        "uuid4",
                        return_value=uuid.UUID(REQUEST_ID),
                    ),
                ):
                    code, output, error_output = self.run_main(
                        [
                            "request",
                            "--force",
                            "--pull-request",
                            "17",
                            "--message-file",
                            str(message_path),
                            "--repository",
                            REPOSITORY,
                        ]
                    )

                diagnostic_output = output if expected_code == 0 else error_output
                self.assertEqual(code, expected_code, diagnostic_output)
                self.assertIn(diagnostic, diagnostic_output)
                if expected_code == 3:
                    self.assertIn(
                        f"Guarded merge {REQUEST_ID}",
                        diagnostic_output,
                    )

    def test_request_timeout_after_dispatch_is_indeterminate_exit_three(self):
        message_path = self.write_bytes(b"fix(git): time out safely\n")
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_dispatch_request"),
            patch.object(
                self.module,
                "_query_dispatch_runs",
                return_value=[],
            ) as query_runs,
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
        ):
            code, _, error_output = self.run_main(
                [
                    "request",
                    "--force",
                    "--pull-request",
                    "17",
                    "--message-file",
                    str(message_path),
                    "--repository",
                    REPOSITORY,
                    "--timeout-seconds",
                    "0",
                ]
            )

        self.assertEqual(code, 3)
        self.assertIn("indeterminate", error_output.lower())
        self.assertIn(f"Guarded merge {REQUEST_ID}", error_output)
        query_runs.assert_not_called()

    def test_timeout_accepts_largest_finite_integer_conversion(self):
        args = self.module._build_parser().parse_args(
            [
                "request",
                "--pull-request",
                "17",
                "--message-file",
                "message.txt",
                "--timeout-seconds",
                str(int(sys.float_info.max)),
            ]
        )

        timeout_seconds = self.module._validate_request_arguments(args)

        self.assertEqual(timeout_seconds, sys.float_info.max)

    def test_timeout_rejects_unrepresentable_integer_before_dispatch(self):
        message_path = self.write_bytes(b"fix(git): reject timeout overflow\n")
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_dispatch_request") as dispatch,
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
        ):
            try:
                code, _, error_output = self.run_main(
                    [
                        "request",
                        "--force",
                        "--pull-request",
                        "17",
                        "--message-file",
                        str(message_path),
                        "--timeout-seconds",
                        str(10**400),
                    ]
                )
            except OverflowError as error:
                self.fail(f"timeout overflow escaped after dispatch: {error}")

        self.assertEqual(code, 1, error_output)
        self.assertIn("finite", error_output)
        dispatch.assert_not_called()

    def test_request_query_failure_after_dispatch_is_indeterminate_exit_three(self):
        message_path = self.write_bytes(b"fix(git): preserve uncertainty\n")
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_resolve_repository",
                return_value=(REPOSITORY, "main"),
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_dispatch_request"),
            patch.object(
                self.module,
                "_query_dispatch_runs",
                side_effect=self.module.MergeRequestError("query failed"),
            ),
            patch.object(
                self.module.uuid,
                "uuid4",
                return_value=uuid.UUID(REQUEST_ID),
            ),
        ):
            code, _, error_output = self.run_main(
                [
                    "request",
                    "--force",
                    "--pull-request",
                    "17",
                    "--message-file",
                    str(message_path),
                    "--repository",
                    REPOSITORY,
                ]
            )

        self.assertEqual(code, 3)
        self.assertIn("query failed", error_output)
        self.assertIn(f"Guarded merge {REQUEST_ID}", error_output)

    def test_workflow_run_query_is_workflow_specific_and_bounded(self):
        with patch.object(
            self.module,
            "_run_gh_json",
            return_value={"workflow_runs": []},
        ) as gh_json:
            runs = self.module._query_dispatch_runs(REPOSITORY, 4.25)

        self.assertEqual(runs, [])
        gh_json.assert_called_once_with(
            [
                "api",
                "repos/owner/repository/actions/workflows/"
                ".github%2Fworkflows%2Fguarded-pull-request-merge.yml/"
                "runs?event=repository_dispatch&per_page=100",
            ],
            timeout_seconds=4.25,
        )

    def test_workflow_wait_caps_query_and_rejects_wrong_or_duplicate_workflow(self):
        correct_run = {
            "display_title": f"Guarded merge {REQUEST_ID}",
            "event": "repository_dispatch",
            "path": ".github/workflows/guarded-pull-request-merge.yml",
            "head_branch": "main",
            "head_sha": HEAD_OID,
            "status": "completed",
            "conclusion": "success",
        }
        observed_timeouts = []

        def query_runs(_repository, timeout_seconds):
            observed_timeouts.append(timeout_seconds)
            return [correct_run]

        with (
            patch.object(self.module.time, "monotonic", side_effect=[10.0, 10.25]),
            patch.object(self.module, "_query_dispatch_runs", side_effect=query_runs),
        ):
            result = self.module._wait_for_dispatch_run(
                REPOSITORY,
                "main",
                REQUEST_ID,
                2,
                False,
            )

        self.assertIs(result, correct_run)
        self.assertEqual(observed_timeouts, [1.75])

        documented_path_run = dict(
            correct_run,
            path=".github/workflows/guarded-pull-request-merge.yml@main",
        )
        with (
            patch.object(self.module.time, "monotonic", side_effect=[15.0, 15.0]),
            patch.object(
                self.module,
                "_query_dispatch_runs",
                return_value=[documented_path_run],
            ),
        ):
            result = self.module._wait_for_dispatch_run(
                REPOSITORY,
                "main",
                REQUEST_ID,
                1,
                False,
            )

        self.assertIs(result, documented_path_run)

        for wrong_run in (
            dict(correct_run, path=".github/workflows/other.yml"),
            dict(
                correct_run,
                path=".github/workflows/guarded-pull-request-merge.yml@other",
            ),
            dict(correct_run, head_branch="other"),
            dict(correct_run, head_sha="invalid"),
        ):
            with self.subTest(wrong_run=wrong_run):
                with (
                    patch.object(
                        self.module.time,
                        "monotonic",
                        side_effect=[20.0, 20.0, 21.0],
                    ),
                    patch.object(self.module.time, "sleep"),
                    patch.object(
                        self.module,
                        "_query_dispatch_runs",
                        return_value=[wrong_run],
                    ),
                ):
                    with self.assertRaisesRegex(
                        self.module.IndeterminateMergeError,
                        f"Guarded merge {REQUEST_ID}",
                    ):
                        self.module._wait_for_dispatch_run(
                            REPOSITORY,
                            "main",
                            REQUEST_ID,
                            1,
                            False,
                        )

        wrong_event = dict(correct_run, event="workflow_dispatch")
        with (
            patch.object(
                self.module.time,
                "monotonic",
                side_effect=[25.0, 25.0, 26.0],
            ),
            patch.object(self.module.time, "sleep"),
            patch.object(
                self.module,
                "_query_dispatch_runs",
                return_value=[wrong_event],
            ),
        ):
            with self.assertRaisesRegex(
                self.module.IndeterminateMergeError,
                f"Guarded merge {REQUEST_ID}",
            ):
                self.module._wait_for_dispatch_run(
                    REPOSITORY,
                    "main",
                    REQUEST_ID,
                    1,
                    False,
                )

        with (
            patch.object(self.module.time, "monotonic", side_effect=[30.0, 30.0]),
            patch.object(
                self.module,
                "_query_dispatch_runs",
                return_value=[correct_run, dict(correct_run)],
            ),
        ):
            with self.assertRaisesRegex(
                self.module.IndeterminateMergeError,
                f"Guarded merge {REQUEST_ID}",
            ):
                self.module._wait_for_dispatch_run(
                    REPOSITORY,
                    "main",
                    REQUEST_ID,
                    1,
                    False,
                )

    def test_execute_dry_run_revalidates_without_merge(self):
        event_path = self.write_event(valid_event())
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ) as validate_pr,
            patch.object(self.module, "_run_gh") as gh,
        ):
            code, output, error_output = self.run_main(
                ["--dry-run", "execute", "--event-file", str(event_path)]
            )

        self.assertEqual(code, 0, error_output)
        validate_pr.assert_called_once_with(REPOSITORY, "main", 17, HEAD_OID)
        gh.assert_not_called()
        self.assertIn("Would squash merge", output)

    def test_execute_rejects_retarget_after_checks_before_merge(self):
        event_path = self.write_event(valid_event())
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_load_guard_policy",
                return_value=valid_policy(),
            ),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[
                    valid_pull_request(),
                    valid_checks(),
                    valid_mutation_state(base_ref_name="other"),
                ],
            ),
            patch.object(self.module, "_run_gh") as gh,
        ):
            code, _, error_output = self.run_main(
                ["execute", "--event-file", str(event_path)]
            )

        self.assertEqual(code, 1, error_output)
        self.assertIn("default branch", error_output)
        gh.assert_not_called()

    def test_execute_uses_exact_merge_arguments_and_empty_body_file(self):
        event_path = self.write_event(valid_event())
        observed_temporary_paths = []

        def run_gh(arguments, **_kwargs):
            body_path = pathlib.Path(arguments[arguments.index("--body-file") + 1])
            observed_temporary_paths.append(body_path)
            self.assertEqual(body_path.read_bytes(), b"")
            return completed(arguments)

        def validate_message(path):
            observed_temporary_paths.append(path)

        post_merge = dict(valid_pull_request(), state="MERGED", mergeCommit=MERGE_OID)
        with (
            patch.object(
                self.module,
                "_validate_message_with_commitlint",
                side_effect=validate_message,
            ),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_run_gh", side_effect=run_gh) as gh,
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[
                    post_merge,
                    {"commit": {"message": "fix(git): guard squash merges"}},
                ],
            ) as gh_json,
        ):
            code, _, error_output = self.run_main(
                ["execute", "--event-file", str(event_path)]
            )

        self.assertEqual(code, 0, error_output)
        merge_arguments = gh.call_args.args[0]
        self.assertEqual(
            merge_arguments,
            [
                "pr",
                "merge",
                "17",
                "--repo",
                REPOSITORY,
                "--squash",
                "--subject",
                "fix(git): guard squash merges",
                "--body-file",
                str(observed_temporary_paths[1]),
                "--match-head-commit",
                HEAD_OID,
            ],
        )
        self.assertNotIn("--auto", merge_arguments)
        self.assertNotIn("--admin", merge_arguments)
        self.assertNotIn("--delete-branch", merge_arguments)
        self.assertNotIn("--disable-auto", merge_arguments)
        self.assertEqual(
            gh_json.call_args_list[0].args[0],
            [
                "pr",
                "view",
                "17",
                "--repo",
                REPOSITORY,
                "--json",
                "number,state,mergeCommit,baseRefName,headRefOid",
            ],
        )
        self.assertEqual(len(observed_temporary_paths), 3)
        self.assertTrue(all(not path.exists() for path in observed_temporary_paths))

    def test_execute_preserves_exact_nonempty_body_file(self):
        raw = b"fix(git): preserve body\n\nLine one.\nLine two.\n"
        event_path = self.write_event(valid_event(raw))
        observed_body = []

        def run_gh(arguments, **_kwargs):
            body_path = pathlib.Path(arguments[arguments.index("--body-file") + 1])
            observed_body.append(body_path.read_bytes())
            return completed(arguments)

        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_run_gh", side_effect=run_gh),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[
                    dict(valid_pull_request(), state="MERGED", mergeCommit=MERGE_OID),
                    {
                        "commit": {
                            "message": "fix(git): preserve body\n\nLine one.\nLine two."
                        }
                    },
                ],
            ),
        ):
            code, _, error_output = self.run_main(
                ["execute", "--event-file", str(event_path)]
            )

        self.assertEqual(code, 0, error_output)
        self.assertEqual(observed_body, [b"Line one.\nLine two.\n"])

    def test_execute_pre_mutation_failure_does_not_read_postcondition(self):
        event_path = self.write_event(valid_event())
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(
                self.module,
                "_run_gh",
                side_effect=self.module.GitHubCommandStartError("could not start"),
            ),
            patch.object(self.module, "_run_gh_json") as gh_json,
        ):
            code, _, error_output = self.run_main(
                ["execute", "--event-file", str(event_path)]
            )

        self.assertEqual(code, 1)
        self.assertIn("could not start", error_output)
        gh_json.assert_not_called()

    def test_execute_recovers_success_after_ambiguous_merge_failure(self):
        event_path = self.write_event(valid_event())
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(
                self.module,
                "_run_gh",
                side_effect=self.module.GitHubCommandStartedError(
                    "merge response lost"
                ),
            ),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[
                    dict(valid_pull_request(), state="MERGED", mergeCommit=MERGE_OID),
                    {"commit": {"message": "fix(git): guard squash merges"}},
                ],
            ),
        ):
            code, output, error_output = self.run_main(
                ["execute", "--event-file", str(event_path)]
            )

        self.assertEqual(code, 0, error_output)
        self.assertIn("Squash merge confirmed", output)

    def test_execute_ambiguous_merge_uses_postcondition_to_classify_outcome(self):
        event_path = self.write_event(valid_event())
        cases = (
            (
                [valid_pull_request()],
                1,
                "not merged",
            ),
            (
                [
                    dict(valid_pull_request(), state="MERGED", mergeCommit=MERGE_OID),
                    {"commit": {"message": "fix(git): different message"}},
                ],
                3,
                "does not match",
            ),
            (
                [self.module.MergeRequestError("post-merge read unavailable")],
                3,
                "post-merge read unavailable",
            ),
        )
        for post_responses, expected_code, diagnostic in cases:
            with self.subTest(expected_code=expected_code, diagnostic=diagnostic):
                responses = iter(post_responses)

                def post_read(*_arguments, **_kwargs):
                    response = next(responses)
                    if isinstance(response, Exception):
                        raise response
                    return response

                with (
                    patch.object(self.module, "_validate_message_with_commitlint"),
                    patch.object(
                        self.module,
                        "_validate_pull_request",
                        return_value=valid_pull_request(),
                    ),
                    patch.object(
                        self.module,
                        "_run_gh",
                        side_effect=self.module.GitHubCommandStartedError(
                            "merge response lost"
                        ),
                    ),
                    patch.object(
                        self.module,
                        "_run_gh_json",
                        side_effect=post_read,
                    ),
                    patch.object(
                        self.module,
                        "_load_pull_request_mutation_state",
                        return_value=(HEAD_OID, "main", False, False, False),
                        create=True,
                    ),
                ):
                    code, _, error_output = self.run_main(
                        ["execute", "--event-file", str(event_path)]
                    )

                self.assertEqual(code, expected_code, error_output)
                self.assertIn(diagnostic, error_output)
                if expected_code == 3:
                    self.assertIn(
                        f"Guarded merge {REQUEST_ID}",
                        error_output,
                    )

    def test_execute_treats_post_merge_message_mismatch_as_indeterminate(self):
        event_path = self.write_event(valid_event())
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_run_gh", return_value=completed([])),
            patch.object(
                self.module,
                "_run_gh_json",
                side_effect=[
                    dict(valid_pull_request(), state="MERGED", mergeCommit=MERGE_OID),
                    {"commit": {"message": "fix(git): different message"}},
                ],
            ),
        ):
            code, _, error_output = self.run_main(
                ["execute", "--event-file", str(event_path)]
            )

        self.assertEqual(code, 3)
        self.assertIn("conflicting", error_output)
        self.assertIn("does not match", error_output)
        self.assertIn(f"Guarded merge {REQUEST_ID}", error_output)

    def test_execute_treats_merged_identity_mismatch_as_indeterminate_even_with_same_message(
        self,
    ):
        event_path = self.write_event(valid_event())
        for field, value in (("headRefOid", "f" * 40), ("baseRefName", "other")):
            with self.subTest(field=field):
                post_merge = dict(
                    valid_pull_request(),
                    state="MERGED",
                    mergeCommit=MERGE_OID,
                )
                post_merge[field] = value
                with (
                    patch.object(self.module, "_validate_message_with_commitlint"),
                    patch.object(
                        self.module,
                        "_validate_pull_request",
                        return_value=valid_pull_request(),
                    ),
                    patch.object(self.module, "_run_gh", return_value=completed([])),
                    patch.object(
                        self.module,
                        "_run_gh_json",
                        side_effect=[
                            post_merge,
                            {"commit": {"message": "fix(git): guard squash merges"}},
                        ],
                    ),
                ):
                    code, _, error_output = self.run_main(
                        ["execute", "--event-file", str(event_path)]
                    )

                self.assertEqual(code, 3, error_output)
                self.assertIn("conflicting", error_output)
                self.assertIn(f"Guarded merge {REQUEST_ID}", error_output)

    def test_execute_treats_unavailable_post_merge_read_as_indeterminate(self):
        event_path = self.write_event(valid_event())
        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_run_gh", return_value=completed([])),
            patch.object(
                self.module,
                "_verify_postcondition",
                side_effect=self.module.MergeRequestError(
                    "post-merge read unavailable"
                ),
            ),
        ):
            code, _, error_output = self.run_main(
                ["execute", "--event-file", str(event_path)]
            )

        self.assertEqual(code, 3)
        self.assertIn("post-merge read unavailable", error_output)
        self.assertIn(f"Guarded merge {REQUEST_ID}", error_output)

    def test_execute_treats_post_merge_message_write_failure_as_indeterminate(self):
        event_path = self.write_event(valid_event())

        def write_bytes(path, value):
            if path.name == "actual-message.txt":
                raise OSError("actual message storage unavailable")
            return len(value)

        with (
            patch.object(self.module, "_validate_message_with_commitlint"),
            patch.object(
                self.module,
                "_validate_pull_request",
                return_value=valid_pull_request(),
            ),
            patch.object(self.module, "_run_gh", return_value=completed([])) as gh,
            patch.object(
                self.module,
                "_post_merge_message",
                return_value=b"fix(git): guard squash merges",
            ),
            patch.object(
                pathlib.Path, "write_bytes", autospec=True, side_effect=write_bytes
            ),
        ):
            try:
                code, _, error_output = self.run_main(
                    ["execute", "--event-file", str(event_path)]
                )
            except OSError as error:
                self.fail(f"post-merge OSError escaped: {error}")

        self.assertEqual(code, 3, error_output)
        self.assertIn(f"Guarded merge {REQUEST_ID}", error_output)
        self.assertIn("actual message storage unavailable", error_output)
        gh.assert_called_once()

    def test_execute_classifies_unmerged_and_conflicting_states(self):
        event_path = self.write_event(valid_event())
        for diagnostic, post_merge, expected_code in (
            ("not merged", valid_pull_request(), 1),
            (
                "not merged",
                dict(valid_pull_request(), state="CLOSED", mergeCommit=None),
                1,
            ),
            (
                "merge commit",
                dict(valid_pull_request(), state="MERGED"),
                3,
            ),
        ):
            with self.subTest(diagnostic=diagnostic, expected_code=expected_code):
                with (
                    patch.object(
                        self.module,
                        "_validate_message_with_commitlint",
                    ),
                    patch.object(
                        self.module,
                        "_validate_pull_request",
                        return_value=valid_pull_request(),
                    ),
                    patch.object(
                        self.module,
                        "_run_gh",
                        return_value=completed([]),
                    ),
                    patch.object(
                        self.module,
                        "_run_gh_json",
                        return_value=post_merge,
                    ),
                    patch.object(
                        self.module,
                        "_load_pull_request_mutation_state",
                        return_value=(HEAD_OID, "main", False, False, False),
                        create=True,
                    ),
                ):
                    code, _, error_output = self.run_main(
                        ["execute", "--event-file", str(event_path)]
                    )

                self.assertEqual(code, expected_code)
                self.assertIn(diagnostic, error_output)
                if expected_code == 3:
                    self.assertIn("conflicting", error_output)
                    self.assertIn(
                        f"Guarded merge {REQUEST_ID}",
                        error_output,
                    )

    def test_execute_treats_queued_or_unreadable_unmerged_state_as_indeterminate(self):
        event_path = self.write_event(valid_event())
        for post_merge, mutation_effect, diagnostic in (
            (
                valid_pull_request(),
                (HEAD_OID, "main", True, False, False),
                "auto-merge",
            ),
            (
                valid_pull_request(),
                (HEAD_OID, "main", False, True, False),
                "merge queue",
            ),
            (
                dict(valid_pull_request(), state="CLOSED", mergeCommit=None),
                self.module.MergeRequestError("merge queue state unavailable"),
                "unavailable",
            ),
        ):
            with self.subTest(diagnostic=diagnostic):
                mutation_kwargs = (
                    {"side_effect": mutation_effect}
                    if isinstance(mutation_effect, Exception)
                    else {"return_value": mutation_effect}
                )
                with (
                    patch.object(self.module, "_validate_message_with_commitlint"),
                    patch.object(
                        self.module,
                        "_validate_pull_request",
                        return_value=valid_pull_request(),
                    ),
                    patch.object(self.module, "_run_gh", return_value=completed([])),
                    patch.object(
                        self.module,
                        "_run_gh_json",
                        return_value=post_merge,
                    ),
                    patch.object(
                        self.module,
                        "_load_pull_request_mutation_state",
                        create=True,
                        **mutation_kwargs,
                    ),
                ):
                    code, _, error_output = self.run_main(
                        ["execute", "--event-file", str(event_path)]
                    )

                self.assertEqual(code, 3, error_output)
                self.assertIn(diagnostic, error_output)
                self.assertIn(f"Guarded merge {REQUEST_ID}", error_output)

    def test_commitlint_failure_precedes_every_gh_call(self):
        message_path = self.write_bytes(b"fix(git): invalid for commitlint\n")
        events = []

        def reject_message(_path):
            events.append("commitlint")
            raise self.module.MergeRequestError("Commitlint rejected the message.")

        with (
            patch.object(
                self.module,
                "_validate_message_with_commitlint",
                side_effect=reject_message,
            ),
            patch.object(
                self.module,
                "_resolve_repository",
                side_effect=lambda _repository: events.append("gh"),
            ),
        ):
            code, _, error_output = self.run_main(
                [
                    "request",
                    "--force",
                    "--pull-request",
                    "17",
                    "--message-file",
                    str(message_path),
                    "--repository",
                    REPOSITORY,
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(events, ["commitlint"])
        self.assertIn("Commitlint", error_output)


if __name__ == "__main__":
    unittest.main()
