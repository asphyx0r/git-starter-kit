#!/usr/bin/env python3
"""Dispatch and execute repository-owned guarded squash merges."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote


VERSION = "v0.1.0"
EVENT_TYPE = "guarded-squash-merge"
WORKFLOW_PATH = ".github/workflows/guarded-pull-request-merge.yml"
MAX_CLIENT_PAYLOAD_CHARACTERS = 65_535
COMMAND_TIMEOUT_SECONDS = 30
POLL_SECONDS = 5
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PAYLOAD_FIELDS = {
    "request_id",
    "pull_request",
    "expected_head_oid",
    "message_sha256",
    "message_base64",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PULL_REQUEST_MUTATION_STATE_QUERY = """query PullRequestMergeQueueState(
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


class MergeRequestError(Exception):
    """Report an invalid request or a definite merge failure."""


class IndeterminateMergeError(Exception):
    """Report a dispatched request whose final outcome is unknown."""


class GitHubCommandStartError(MergeRequestError):
    """Report a GitHub CLI operation that could not begin."""


class GitHubCommandStartedError(MergeRequestError):
    """Report a failed GitHub CLI operation that may have changed remote state."""


class AmbiguousDispatchError(IndeterminateMergeError):
    """Report a repository dispatch whose acceptance is unknown."""


class UnmergedPullRequestError(MergeRequestError):
    """Report read-only evidence that the pull request is not merged."""


@dataclass(frozen=True)
class MergeMessage:
    """Keep the validated merge message and its exact component bytes."""

    raw: bytes
    subject: str
    body: bytes


@dataclass(frozen=True)
class DispatchRequest:
    """Hold a validated repository-dispatch request."""

    request_id: str
    pull_request: int
    expected_head_oid: str
    message_sha256: str
    message: MergeMessage
    repository: str
    default_branch: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Request or execute a guarded squash merge.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=VERSION,
        help="show version and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate without dispatching or merging",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show polling details",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    request = subparsers.add_parser(
        "request",
        help="validate and dispatch a guarded merge request",
    )
    request.add_argument(
        "--force",
        action="store_true",
        help="skip the uppercase Y confirmation",
    )
    request.add_argument(
        "--pull-request",
        required=True,
        type=int,
        metavar="NUMBER",
        help="open pull request number",
    )
    request.add_argument(
        "--message-file",
        required=True,
        type=Path,
        metavar="PATH",
        help="exact UTF-8 squash message file",
    )
    request.add_argument(
        "--repository",
        metavar="OWNER/REPO",
        help="target GitHub repository; default: current repository",
    )
    request.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        metavar="SECONDS",
        help="maximum finite workflow wait; default: 900",
    )

    execute = subparsers.add_parser(
        "execute",
        help="validate and execute a repository-dispatch event",
    )
    execute.add_argument(
        "--event-file",
        required=True,
        type=Path,
        metavar="PATH",
        help="trusted GitHub repository-dispatch event file",
    )
    return parser


def _parse_merge_message(raw: bytes) -> MergeMessage:
    if not raw:
        raise MergeRequestError("The message file must be non-empty.")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise MergeRequestError("The message file must not contain a UTF-8 BOM.")
    if b"\x00" in raw:
        raise MergeRequestError("The message file must not contain NUL bytes.")
    if b"\r" in raw:
        raise MergeRequestError("The message file must use LF, not CRLF.")
    if not raw.endswith(b"\n"):
        raise MergeRequestError("The message file is missing its final LF.")
    if raw.endswith(b"\n\n"):
        raise MergeRequestError("The message file has more than one final LF.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MergeRequestError("The message file must be valid UTF-8.") from error

    without_final_lf = text[:-1]
    if "\n" not in without_final_lf:
        if not without_final_lf:
            raise MergeRequestError("The message subject must be non-empty.")
        return MergeMessage(raw=raw, subject=without_final_lf, body=b"")

    subject, separator, body_text = without_final_lf.partition("\n\n")
    if not separator or not subject or "\n" in subject or not body_text:
        raise MergeRequestError(
            "The message shape must be subject\\n or subject\\n\\nbody\\n."
        )
    body_offset = len(subject.encode("utf-8")) + 2
    return MergeMessage(raw=raw, subject=subject, body=raw[body_offset:])


def _read_merge_message(path: Path) -> MergeMessage:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise MergeRequestError(
            f"Unable to read message file {path}: {error}"
        ) from error
    return _parse_merge_message(raw)


def _resolve_commitlint_command() -> str:
    executable = "commitlint.cmd" if os.name == "nt" else "commitlint"
    candidate = REPOSITORY_ROOT / "tools" / "quality" / "node_modules" / ".bin"
    command = candidate / executable
    if command.is_file():
        return str(command)
    raise MergeRequestError(
        "Repository-pinned Commitlint is unavailable; run "
        "npm ci --ignore-scripts --prefix tools/quality."
    )


def _validate_message_with_commitlint(path: Path) -> None:
    command = _resolve_commitlint_command()
    try:
        result = subprocess.run(
            [
                command,
                "--edit",
                str(path),
                "--config",
                str(REPOSITORY_ROOT / "commitlint.config.cjs"),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MergeRequestError(
            f"Commitlint could not validate the message: {error}"
        ) from error
    if result.returncode != 0:
        detail = (
            result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        )
        raise MergeRequestError(f"Commitlint rejected the message:\n{detail}")


def _resolve_gh_command() -> str:
    command = shutil.which("gh")
    if command is None:
        raise MergeRequestError("gh is required for guarded pull request merges.")
    return command


def _run_gh(
    arguments: Sequence[str],
    *,
    input_text: str | None = None,
    allowed_returncodes: Sequence[int] = (0,),
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    command = [_resolve_gh_command(), *arguments]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input_text,
            timeout=timeout_seconds,
        )
    except OSError as error:
        raise GitHubCommandStartError(
            f"GitHub CLI operation could not start: {error}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise GitHubCommandStartedError(
            f"GitHub CLI operation timed out: {error}"
        ) from error
    if result.returncode not in allowed_returncodes:
        detail = (
            result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        )
        raise GitHubCommandStartedError(f"GitHub CLI operation failed: {detail}")
    return result


def _run_gh_json(
    arguments: Sequence[str],
    *,
    allowed_returncodes: Sequence[int] = (0,),
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
) -> Any:
    result = _run_gh(
        arguments,
        allowed_returncodes=allowed_returncodes,
        timeout_seconds=timeout_seconds,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise MergeRequestError("GitHub CLI returned invalid JSON.") from error


def _validate_repository_name(repository: str) -> None:
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise MergeRequestError("Repository must use the OWNER/REPO format.")


def _resolve_repository(repository: str | None) -> tuple[str, str]:
    arguments = ["repo", "view"]
    if repository is not None:
        _validate_repository_name(repository)
        arguments.append(repository)
    arguments.extend(["--json", "nameWithOwner,defaultBranchRef"])
    value = _run_gh_json(arguments)
    try:
        resolved_repository = value["nameWithOwner"]
        default_branch = value["defaultBranchRef"]["name"]
    except (KeyError, TypeError) as error:
        raise MergeRequestError(
            "GitHub returned incomplete repository identity."
        ) from error
    if not isinstance(resolved_repository, str) or not isinstance(default_branch, str):
        raise MergeRequestError("GitHub returned invalid repository identity.")
    _validate_repository_name(resolved_repository)
    if not default_branch or any(character.isspace() for character in default_branch):
        raise MergeRequestError("GitHub returned an invalid default branch.")
    if repository is not None and repository.lower() != resolved_repository.lower():
        raise MergeRequestError("GitHub resolved a different target repository.")
    return resolved_repository, default_branch


def _load_guard_policy(repository: str, default_branch: str) -> frozenset[str]:
    repository_value = _run_gh_json(["api", f"repos/{repository}"])
    if not isinstance(repository_value, dict) or not isinstance(
        repository_value.get("allow_auto_merge"), bool
    ):
        raise MergeRequestError(
            "GitHub returned an invalid repository auto-merge policy."
        )
    if repository_value["allow_auto_merge"]:
        raise MergeRequestError(
            "Repository auto-merge must be disabled before guarded merges."
        )

    encoded_branch = quote(default_branch, safe="")
    pages = _run_gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repository}/rules/branches/{encoded_branch}?per_page=100",
        ]
    )
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise MergeRequestError("GitHub returned invalid effective branch rules.")

    required_checks: set[str] = set()
    for rule in (rule for page in pages for rule in page):
        if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
            raise MergeRequestError("GitHub returned invalid effective branch rules.")
        if rule["type"] == "merge_queue":
            raise MergeRequestError(
                "The default branch merge queue must be disabled before guarded merges."
            )
        if rule["type"] != "required_status_checks":
            continue
        parameters = rule.get("parameters")
        configured_checks = (
            parameters.get("required_status_checks")
            if isinstance(parameters, dict)
            else None
        )
        if not isinstance(configured_checks, list):
            raise MergeRequestError(
                "GitHub returned an unsupported required-status-check rule shape."
            )
        for configured_check in configured_checks:
            if (
                not isinstance(configured_check, dict)
                or set(configured_check) != {"context", "integration_id"}
                or not isinstance(configured_check.get("context"), str)
                or not configured_check["context"]
            ):
                raise MergeRequestError(
                    "GitHub returned an unsupported required-status-check rule shape."
                )
            integration_id = configured_check["integration_id"]
            if integration_id is not None and (
                type(integration_id) is not int or integration_id <= 0
            ):
                raise MergeRequestError(
                    "GitHub returned an unsupported required-status-check rule shape."
                )
            required_checks.add(configured_check["context"])
    return frozenset(required_checks)


def _load_pull_request_mutation_state(
    repository: str,
    pull_request: int,
) -> tuple[str, str, bool, bool, bool]:
    owner, repository_name = repository.split("/", maxsplit=1)
    value = _run_gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={PULL_REQUEST_MUTATION_STATE_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"repository={repository_name}",
            "-F",
            f"number={pull_request}",
        ]
    )
    if not isinstance(value, dict) or set(value) != {"data"}:
        raise MergeRequestError(
            "GitHub returned an invalid pull request mutation state."
        )
    data = value["data"]
    if not isinstance(data, dict) or set(data) != {"repository"}:
        raise MergeRequestError(
            "GitHub returned an invalid pull request mutation state."
        )
    repository_value = data["repository"]
    if not isinstance(repository_value, dict) or set(repository_value) != {
        "pullRequest"
    }:
        raise MergeRequestError(
            "GitHub returned an invalid pull request mutation state."
        )
    state = repository_value["pullRequest"]
    expected_fields = {
        "headRefOid",
        "baseRefName",
        "autoMergeRequest",
        "isInMergeQueue",
        "isMergeQueueEnabled",
    }
    if not isinstance(state, dict) or set(state) != expected_fields:
        raise MergeRequestError(
            "GitHub returned an invalid pull request mutation state."
        )
    head_oid = state["headRefOid"]
    base_ref_name = state["baseRefName"]
    auto_merge_request = state["autoMergeRequest"]
    in_merge_queue = state["isInMergeQueue"]
    merge_queue_enabled = state["isMergeQueueEnabled"]
    if not isinstance(head_oid, str) or not SHA_PATTERN.fullmatch(head_oid):
        raise MergeRequestError(
            "GitHub returned an invalid pull request mutation state."
        )
    if (
        not isinstance(base_ref_name, str)
        or not base_ref_name
        or any(character.isspace() for character in base_ref_name)
    ):
        raise MergeRequestError(
            "GitHub returned an invalid pull request mutation state."
        )
    if auto_merge_request is None:
        auto_merge_enabled = False
    elif (
        isinstance(auto_merge_request, dict)
        and set(auto_merge_request) == {"enabledAt"}
        and isinstance(auto_merge_request["enabledAt"], str)
        and auto_merge_request["enabledAt"]
    ):
        auto_merge_enabled = True
    else:
        raise MergeRequestError(
            "GitHub returned an invalid pull request mutation state."
        )
    if type(in_merge_queue) is not bool or type(merge_queue_enabled) is not bool:
        raise MergeRequestError(
            "GitHub returned an invalid pull request mutation state."
        )
    return (
        head_oid,
        base_ref_name,
        auto_merge_enabled,
        in_merge_queue,
        merge_queue_enabled,
    )


def _validate_pull_request(
    repository: str,
    default_branch: str,
    pull_request: int,
    expected_head_oid: str | None,
) -> dict[str, Any]:
    if pull_request <= 0:
        raise MergeRequestError("Pull request number must be positive.")
    required_checks = _load_guard_policy(repository, default_branch)
    if "Repository audit" not in required_checks:
        raise MergeRequestError(
            "The Repository audit context is not an effective required check."
        )
    value = _run_gh_json(
        [
            "pr",
            "view",
            str(pull_request),
            "--repo",
            repository,
            "--json",
            "number,state,isDraft,headRefOid,baseRefName,isCrossRepository,"
            "autoMergeRequest",
        ]
    )
    if not isinstance(value, dict) or value.get("number") != pull_request:
        raise MergeRequestError("GitHub returned a different pull request.")
    if value.get("state") != "OPEN":
        raise MergeRequestError("The pull request must be open.")
    if value.get("isDraft") is not False:
        raise MergeRequestError("The pull request must not be a draft.")
    if value.get("baseRefName") != default_branch:
        raise MergeRequestError("The pull request must target the default branch.")
    if "autoMergeRequest" not in value:
        raise MergeRequestError(
            "GitHub returned invalid pull request auto-merge state."
        )
    if value["autoMergeRequest"] is not None:
        raise MergeRequestError("The pull request must not have auto-merge enabled.")
    head_oid = value.get("headRefOid")
    if not isinstance(head_oid, str) or not SHA_PATTERN.fullmatch(head_oid):
        raise MergeRequestError("GitHub returned an invalid pull request head SHA.")
    if expected_head_oid is not None and head_oid != expected_head_oid:
        raise MergeRequestError(
            "The pull request head changed after the request was sealed."
        )

    checks = _run_gh_json(
        [
            "pr",
            "checks",
            str(pull_request),
            "--repo",
            repository,
            "--json",
            "bucket,event,link,name,state,workflow",
        ],
        allowed_returncodes=(0, 1, 8),
    )
    if not isinstance(checks, list):
        raise MergeRequestError("GitHub returned invalid pull request checks.")
    for required_check in sorted(required_checks):
        observed = [
            check
            for check in checks
            if isinstance(check, dict) and check.get("name") == required_check
        ]
        if not observed:
            raise MergeRequestError(f"The required check {required_check} is missing.")
        if any(check.get("state") != "SUCCESS" for check in observed):
            raise MergeRequestError(
                f"The required check {required_check} has not succeeded."
            )
    repository_audits = [
        check
        for check in checks
        if isinstance(check, dict) and check.get("name") == "Repository audit"
    ]
    if not repository_audits:
        raise MergeRequestError("The required Repository audit check is missing.")
    if not any(check.get("event") == "pull_request" for check in repository_audits):
        raise MergeRequestError(
            "The required Repository audit check must come from pull_request."
        )
    if not any(
        check.get("event") == "pull_request"
        and check.get("workflow") == "Repository audit"
        for check in repository_audits
    ):
        raise MergeRequestError(
            "The required Repository audit check has the wrong workflow identity."
        )
    (
        final_head_oid,
        final_base_ref_name,
        auto_merge_enabled,
        in_merge_queue,
        merge_queue_enabled,
    ) = _load_pull_request_mutation_state(
        repository,
        pull_request,
    )
    if final_head_oid != head_oid:
        raise MergeRequestError(
            "The pull request head changed while required checks were verified."
        )
    if final_base_ref_name != default_branch:
        raise MergeRequestError(
            "The pull request stopped targeting the default branch while required "
            "checks were verified."
        )
    if auto_merge_enabled:
        raise MergeRequestError(
            "The pull request enabled auto-merge while required checks were verified."
        )
    if in_merge_queue or merge_queue_enabled:
        raise MergeRequestError(
            "The pull request or its base branch has an active merge queue."
        )
    return value


def _build_client_payload(
    *,
    request_id: str,
    pull_request: int,
    expected_head_oid: str,
    message: MergeMessage,
) -> tuple[dict[str, Any], str]:
    payload = {
        "request_id": request_id,
        "pull_request": pull_request,
        "expected_head_oid": expected_head_oid,
        "message_sha256": hashlib.sha256(message.raw).hexdigest(),
        "message_base64": base64.b64encode(message.raw).decode("ascii"),
    }
    serialized = json.dumps(payload, separators=(",", ":"))
    if len(serialized) > MAX_CLIENT_PAYLOAD_CHARACTERS:
        raise MergeRequestError(
            "The compact serialized client payload exceeds 65,535 characters."
        )
    return payload, serialized


def _dispatch_request(
    repository: str,
    payload: dict[str, Any],
    request_id: str,
) -> None:
    body = json.dumps(
        {"event_type": EVENT_TYPE, "client_payload": payload},
        separators=(",", ":"),
    )
    try:
        _run_gh(
            [
                "api",
                "--method",
                "POST",
                f"repos/{repository}/dispatches",
                "--input",
                "-",
            ],
            input_text=body,
        )
    except GitHubCommandStartedError as error:
        raise AmbiguousDispatchError(
            f"Guarded merge {request_id}: repository dispatch submission is "
            f"indeterminate; do not retry automatically: {error}"
        ) from error


def _query_dispatch_runs(
    repository: str,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    encoded_workflow = quote(WORKFLOW_PATH, safe="")
    value = _run_gh_json(
        [
            "api",
            f"repos/{repository}/actions/workflows/{encoded_workflow}/"
            "runs?event=repository_dispatch&per_page=100",
        ],
        timeout_seconds=timeout_seconds,
    )
    runs = value.get("workflow_runs") if isinstance(value, dict) else None
    if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
        raise MergeRequestError("GitHub returned invalid workflow runs.")
    return runs


def _run_summary(run: dict[str, Any]) -> str:
    return (
        f"status={run.get('status')} conclusion={run.get('conclusion')} "
        f"url={run.get('html_url')}"
    )


def _wait_for_dispatch_run(
    repository: str,
    default_branch: str,
    request_id: str,
    timeout_seconds: float,
    verbose: bool,
) -> dict[str, Any]:
    expected_name = f"Guarded merge {request_id}"
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise IndeterminateMergeError(
                f"{expected_name}: indeterminate outcome after dispatch; "
                "timed out waiting for the correlated workflow run."
            )
        try:
            runs = _query_dispatch_runs(
                repository,
                min(COMMAND_TIMEOUT_SECONDS, remaining_seconds),
            )
        except MergeRequestError as error:
            raise IndeterminateMergeError(
                f"{expected_name}: indeterminate outcome after dispatch: {error}"
            ) from error
        matches = [
            run
            for run in runs
            if run.get("event") == "repository_dispatch"
            and run.get("display_title") == expected_name
            and run.get("path") in {WORKFLOW_PATH, f"{WORKFLOW_PATH}@{default_branch}"}
            and run.get("head_branch") == default_branch
            and isinstance(run.get("head_sha"), str)
            and SHA_PATTERN.fullmatch(run["head_sha"])
        ]
        if len(matches) > 1:
            raise IndeterminateMergeError(
                f"{expected_name}: indeterminate outcome after dispatch; "
                "multiple correlated workflow runs found."
            )
        if matches and matches[0].get("status") == "completed":
            return matches[0]
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise IndeterminateMergeError(
                f"{expected_name}: indeterminate outcome after dispatch; "
                "timed out waiting for the correlated workflow run."
            )
        if verbose:
            print(f"Waiting for {expected_name}.", file=sys.stderr)
        time.sleep(min(POLL_SECONDS, remaining_seconds))


def _validate_request_arguments(args: argparse.Namespace) -> float:
    if args.pull_request <= 0:
        raise MergeRequestError("Pull request number must be positive.")
    try:
        timeout_seconds = float(args.timeout_seconds)
    except OverflowError as error:
        raise MergeRequestError(
            "Timeout seconds must have a finite representable value."
        ) from error
    if not math.isfinite(timeout_seconds):
        raise MergeRequestError(
            "Timeout seconds must have a finite representable value."
        )
    if timeout_seconds < 0:
        raise MergeRequestError("Timeout seconds must not be negative.")
    if args.repository is not None:
        _validate_repository_name(args.repository)
    return timeout_seconds


def _request(args: argparse.Namespace) -> int:
    timeout_seconds = _validate_request_arguments(args)
    message = _read_merge_message(args.message_file)
    with tempfile.TemporaryDirectory(prefix="guarded-merge-request-") as temporary:
        candidate_path = Path(temporary) / "candidate-message.txt"
        candidate_path.write_bytes(message.raw)
        _validate_message_with_commitlint(candidate_path)
    repository, default_branch = _resolve_repository(args.repository)
    pull_request = _validate_pull_request(
        repository,
        default_branch,
        args.pull_request,
        None,
    )
    expected_head_oid = str(pull_request["headRefOid"])
    request_id = str(uuid.uuid4())
    payload, serialized = _build_client_payload(
        request_id=request_id,
        pull_request=args.pull_request,
        expected_head_oid=expected_head_oid,
        message=message,
    )
    sealed_request = DispatchRequest(
        request_id=request_id,
        pull_request=args.pull_request,
        expected_head_oid=expected_head_oid,
        message_sha256=str(payload["message_sha256"]),
        message=message,
        repository=repository,
        default_branch=default_branch,
    )

    if args.dry_run:
        print(
            f"Would dispatch {EVENT_TYPE}: repository={repository} "
            f"pull_request={args.pull_request} head={expected_head_oid} "
            f"request_id={request_id} payload_characters={len(serialized)}"
        )
        return 0
    if not args.force:
        confirmation = input(
            f"Dispatch guarded squash merge for {repository}#{args.pull_request}? [Y/N] "
        )
        if confirmation != "Y":
            raise MergeRequestError("Guarded squash merge request cancelled.")

    print(
        f"Guarded merge {request_id}: submitting repository dispatch.",
        flush=True,
    )
    try:
        _dispatch_request(repository, payload, request_id)
    except AmbiguousDispatchError as error:
        if args.verbose:
            print(str(error), file=sys.stderr)
    run = _wait_for_dispatch_run(
        repository,
        default_branch,
        request_id,
        timeout_seconds,
        args.verbose,
    )
    try:
        with tempfile.TemporaryDirectory(
            prefix="guarded-merge-postcondition-"
        ) as temporary:
            _verify_postcondition(
                sealed_request,
                Path(temporary) / "actual-message.txt",
            )
    except UnmergedPullRequestError as error:
        if run.get("conclusion") != "success":
            raise MergeRequestError(
                f"Guarded merge workflow failed: {_run_summary(run)}; {error}"
            ) from error
        raise MergeRequestError(
            f"Guarded merge workflow reported success but {error}"
        ) from error
    except OSError as error:
        raise IndeterminateMergeError(
            f"Guarded merge {request_id}: post-dispatch temporary storage is "
            f"unavailable: {error}"
        ) from error
    except MergeRequestError as error:
        workflow_state = (
            "did not succeed"
            if run.get("conclusion") != "success"
            else "reported success"
        )
        raise IndeterminateMergeError(
            f"Guarded merge {request_id}: workflow {workflow_state} and "
            f"the exact postcondition is unavailable or conflicting: {error}"
        ) from error
    if run.get("conclusion") != "success":
        print(
            f"Guarded merge {request_id} confirmed from the exact postcondition: "
            f"{_run_summary(run)}"
        )
        return 0
    print(f"Guarded merge {request_id} succeeded: {_run_summary(run)}")
    return 0


def _read_dispatch_event(path: Path) -> DispatchRequest:
    try:
        raw_event = path.read_bytes()
        if raw_event.startswith(b"\xef\xbb\xbf"):
            raise MergeRequestError("The event file must not contain a UTF-8 BOM.")
        event = json.loads(raw_event.decode("utf-8"))
    except MergeRequestError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MergeRequestError(
            f"Unable to read repository-dispatch event: {error}"
        ) from error
    if not isinstance(event, dict) or event.get("action") != EVENT_TYPE:
        raise MergeRequestError(
            f"Unexpected repository-dispatch event type; require {EVENT_TYPE}."
        )
    repository_value = event.get("repository")
    if not isinstance(repository_value, dict):
        raise MergeRequestError("The trusted event repository is missing.")
    repository = repository_value.get("full_name")
    default_branch = repository_value.get("default_branch")
    if not isinstance(repository, str) or not REPOSITORY_PATTERN.fullmatch(repository):
        raise MergeRequestError("The trusted event repository is invalid.")
    if not isinstance(default_branch, str) or not default_branch:
        raise MergeRequestError(
            "The trusted event repository default branch is invalid."
        )

    payload = event.get("client_payload")
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS:
        raise MergeRequestError("The client payload must contain the exact fields.")
    serialized_payload = json.dumps(payload, separators=(",", ":"))
    if len(serialized_payload) > MAX_CLIENT_PAYLOAD_CHARACTERS:
        raise MergeRequestError(
            "The compact serialized client payload exceeds 65,535 characters."
        )
    request_id = payload.get("request_id")
    if not isinstance(request_id, str):
        raise MergeRequestError("The request UUID is invalid.")
    try:
        parsed_request_id = uuid.UUID(request_id)
    except ValueError as error:
        raise MergeRequestError("The request UUID is invalid.") from error
    if str(parsed_request_id) != request_id:
        raise MergeRequestError("The request UUID must use canonical lowercase form.")
    pull_request = payload.get("pull_request")
    if (
        isinstance(pull_request, bool)
        or not isinstance(pull_request, int)
        or pull_request <= 0
    ):
        raise MergeRequestError("The pull request number is invalid.")
    expected_head_oid = payload.get("expected_head_oid")
    if not isinstance(expected_head_oid, str) or not SHA_PATTERN.fullmatch(
        expected_head_oid
    ):
        raise MergeRequestError("The expected head SHA is invalid.")
    message_sha256 = payload.get("message_sha256")
    if not isinstance(message_sha256, str) or not SHA256_PATTERN.fullmatch(
        message_sha256
    ):
        raise MergeRequestError("The message SHA-256 is invalid.")
    message_base64 = payload.get("message_base64")
    if not isinstance(message_base64, str):
        raise MergeRequestError("The message Base64 value is invalid.")
    try:
        message_raw = base64.b64decode(message_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise MergeRequestError("The message Base64 value is invalid.") from error
    if base64.b64encode(message_raw).decode("ascii") != message_base64:
        raise MergeRequestError("The message Base64 value is not canonical.")
    if hashlib.sha256(message_raw).hexdigest() != message_sha256:
        raise MergeRequestError("The message SHA-256 does not match its decoded bytes.")
    message = _parse_merge_message(message_raw)
    return DispatchRequest(
        request_id=request_id,
        pull_request=pull_request,
        expected_head_oid=expected_head_oid,
        message_sha256=message_sha256,
        message=message,
        repository=repository,
        default_branch=default_branch,
    )


def _post_merge_message(
    repository: str,
    pull_request: int,
    expected_base_ref_name: str,
    expected_head_oid: str,
) -> bytes:
    value = _run_gh_json(
        [
            "pr",
            "view",
            str(pull_request),
            "--repo",
            repository,
            "--json",
            "number,state,mergeCommit,baseRefName,headRefOid",
        ]
    )
    if not isinstance(value, dict) or value.get("number") != pull_request:
        raise MergeRequestError("GitHub returned conflicting pull request merge state.")
    if (
        value.get("baseRefName") != expected_base_ref_name
        or value.get("headRefOid") != expected_head_oid
    ):
        raise MergeRequestError(
            "GitHub returned conflicting pull request base or head identity."
        )
    if value.get("state") in {"OPEN", "CLOSED"} and value.get("mergeCommit") is None:
        (
            final_head_oid,
            final_base_ref_name,
            auto_merge_enabled,
            in_merge_queue,
            merge_queue_enabled,
        ) = _load_pull_request_mutation_state(repository, pull_request)
        if (
            final_base_ref_name != expected_base_ref_name
            or final_head_oid != expected_head_oid
        ):
            raise MergeRequestError(
                "GitHub returned conflicting pull request base or head identity."
            )
        if auto_merge_enabled or in_merge_queue or merge_queue_enabled:
            raise MergeRequestError(
                "GitHub returned a conflicting auto-merge or merge queue state."
            )
        raise UnmergedPullRequestError(
            "The pull request is not merged after the merge attempt."
        )
    if value.get("state") != "MERGED":
        raise MergeRequestError("GitHub returned conflicting pull request merge state.")
    merge_commit = value.get("mergeCommit")
    if isinstance(merge_commit, dict):
        merge_commit = merge_commit.get("oid")
    if not isinstance(merge_commit, str) or not SHA_PATTERN.fullmatch(merge_commit):
        raise MergeRequestError("GitHub returned an invalid merge commit SHA.")
    commit = _run_gh_json(["api", f"repos/{repository}/commits/{merge_commit}"])
    try:
        message = commit["commit"]["message"]
    except (KeyError, TypeError) as error:
        raise MergeRequestError("GitHub returned no merge commit message.") from error
    if not isinstance(message, str):
        raise MergeRequestError("GitHub returned an invalid merge commit message.")
    return message.encode("utf-8")


def _verify_postcondition(request: DispatchRequest, actual_path: Path) -> None:
    actual_message = _post_merge_message(
        request.repository,
        request.pull_request,
        request.default_branch,
        request.expected_head_oid,
    )
    try:
        actual_path.write_bytes(actual_message)
    except OSError as error:
        raise MergeRequestError(
            f"Unable to store the post-merge message: {error}"
        ) from error
    _validate_message_with_commitlint(actual_path)
    if actual_message not in (request.message.raw, request.message.raw[:-1]):
        raise MergeRequestError(
            "The real merge commit message does not match the validated candidate."
        )


def _execute(args: argparse.Namespace) -> int:
    request = _read_dispatch_event(args.event_file)
    with tempfile.TemporaryDirectory(prefix="guarded-merge-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        candidate_path = temporary_root / "candidate-message.txt"
        body_path = temporary_root / "body.txt"
        actual_path = temporary_root / "actual-message.txt"
        candidate_path.write_bytes(request.message.raw)
        body_path.write_bytes(request.message.body)
        _validate_message_with_commitlint(candidate_path)
        _validate_pull_request(
            request.repository,
            request.default_branch,
            request.pull_request,
            request.expected_head_oid,
        )
        if args.dry_run:
            print(
                f"Would squash merge {request.repository}#{request.pull_request} "
                f"at {request.expected_head_oid}."
            )
            return 0

        try:
            _run_gh(
                [
                    "pr",
                    "merge",
                    str(request.pull_request),
                    "--repo",
                    request.repository,
                    "--squash",
                    "--subject",
                    request.message.subject,
                    "--body-file",
                    str(body_path),
                    "--match-head-commit",
                    request.expected_head_oid,
                ]
            )
        except GitHubCommandStartedError as merge_error:
            try:
                _verify_postcondition(request, actual_path)
            except UnmergedPullRequestError as postcondition_error:
                raise MergeRequestError(
                    f"The merge command failed and the pull request is not merged: "
                    f"{merge_error}"
                ) from postcondition_error
            except MergeRequestError as postcondition_error:
                raise IndeterminateMergeError(
                    f"Guarded merge {request.request_id}: the merge command failed "
                    "after starting and the exact postcondition is unavailable or "
                    f"conflicting: {postcondition_error}"
                ) from postcondition_error
        else:
            try:
                _verify_postcondition(request, actual_path)
            except UnmergedPullRequestError as postcondition_error:
                raise MergeRequestError(
                    "The merge command completed but the pull request is not merged."
                ) from postcondition_error
            except MergeRequestError as postcondition_error:
                raise IndeterminateMergeError(
                    f"Guarded merge {request.request_id}: the merge command completed "
                    "but the exact postcondition is unavailable or conflicting: "
                    f"{postcondition_error}"
                ) from postcondition_error
    print(
        f"Squash merge confirmed for {request.repository}#{request.pull_request} "
        f"at {request.expected_head_oid}."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "request":
            return _request(args)
        return _execute(args)
    except IndeterminateMergeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 3
    except MergeRequestError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
