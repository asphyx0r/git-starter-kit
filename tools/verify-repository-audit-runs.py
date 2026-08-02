#!/usr/bin/env python3
"""Verify that every expected Repository audit push run succeeded."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

VERSION = "v1.0.0"
REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class VerificationError(Exception):
    """Report an invalid request or an unsuccessful audit run."""


class CliArgumentParser(argparse.ArgumentParser):
    """Return repository-standard exit code one for invalid arguments."""

    def error(self, message: str) -> None:
        raise VerificationError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = CliArgumentParser(
        description=(
            "Wait for the exact Repository audit push runs required for a "
            "release SHA."
        )
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
        help="show the read-only verification plan without querying GitHub",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show timestamped polling details",
    )
    parser.add_argument(
        "--repository",
        required=True,
        metavar="OWNER/REPO",
        help="GitHub repository containing the workflow runs",
    )
    parser.add_argument(
        "--workflow-id",
        required=True,
        type=int,
        metavar="ID",
        help="resolved numeric Repository audit workflow identifier",
    )
    parser.add_argument(
        "--sha",
        required=True,
        metavar="SHA",
        help="exact 40-character target commit SHA",
    )
    parser.add_argument(
        "--ref",
        action="append",
        dest="refs",
        required=True,
        metavar="REF",
        help="expected head branch or tag; repeat for every required run",
    )
    parser.add_argument(
        "--created-after",
        required=True,
        metavar="UTC",
        help="inclusive UTC lower bound in YYYY-MM-DDTHH:MM:SSZ format",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        metavar="SECONDS",
        help="maximum wait time; default: 600",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=5,
        metavar="SECONDS",
        help="poll interval; default: 5",
    )
    return parser


def _parse_created_after(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise VerificationError(
            "--created-after must use YYYY-MM-DDTHH:MM:SSZ."
        ) from error
    return parsed.replace(tzinfo=UTC)


def _validate_ref(ref_name: str) -> None:
    if (
        not REF_PATTERN.fullmatch(ref_name)
        or ".." in ref_name
        or "//" in ref_name
        or ref_name.endswith(("/", "."))
        or "/." in ref_name
    ):
        raise VerificationError(f"Invalid expected ref: {ref_name}")


def _validate_args(args: argparse.Namespace) -> datetime:
    if not REPOSITORY_PATTERN.fullmatch(args.repository):
        raise VerificationError(
            "--repository must use the OWNER/REPO format."
        )
    if args.workflow_id <= 0:
        raise VerificationError("--workflow-id must be positive.")
    if not SHA_PATTERN.fullmatch(args.sha):
        raise VerificationError("--sha must contain exactly 40 hexadecimal characters.")
    if args.timeout_seconds < 0:
        raise VerificationError("--timeout-seconds must not be negative.")
    if args.poll_seconds < 0:
        raise VerificationError("--poll-seconds must not be negative.")
    if args.timeout_seconds > 0 and args.poll_seconds == 0:
        raise VerificationError(
            "--poll-seconds must be positive when waiting is enabled."
        )

    if len(args.refs) != len(set(args.refs)):
        raise VerificationError("Each --ref value must be unique.")
    for ref_name in args.refs:
        _validate_ref(ref_name)

    return _parse_created_after(args.created_after)


def _write_verbose(enabled: bool, message: str) -> None:
    if not enabled:
        return
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} {message}", file=sys.stderr)


def _query_runs(repository: str, sha: str) -> list[dict[str, Any]]:
    gh_command = shutil.which("gh")
    if gh_command is None:
        raise VerificationError("gh is required to inspect GitHub Actions runs.")

    query = urlencode(
        {
            "head_sha": sha,
            "event": "push",
            "per_page": 100,
        }
    )
    endpoint = f"repos/{repository}/actions/runs?{query}"
    completed = subprocess.run(
        [gh_command, "api", "--paginate", "--slurp", endpoint],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerificationError(f"GitHub Actions query failed: {detail}")

    try:
        payload = json.loads(completed.stdout)
        pages = payload if isinstance(payload, list) else [payload]
        workflow_runs = []
        for page in pages:
            if not isinstance(page, dict) or not isinstance(
                page.get("workflow_runs"),
                list,
            ):
                raise TypeError
            workflow_runs.extend(page["workflow_runs"])
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise VerificationError(
            "GitHub Actions returned an invalid workflow-runs response."
        ) from error
    return workflow_runs


def _parse_run_time(run: dict[str, Any]) -> datetime:
    created_at = run.get("created_at")
    if not isinstance(created_at, str):
        raise VerificationError("An applicable workflow run has no created_at value.")
    try:
        parsed = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise VerificationError(
            f"Workflow run has an invalid created_at value: {created_at}"
        ) from error
    return parsed.replace(tzinfo=UTC)


def _select_applicable_runs(
    workflow_runs: Sequence[dict[str, Any]],
    workflow_id: int,
    sha: str,
    expected_refs: Sequence[str],
    created_after: datetime,
) -> dict[str, list[dict[str, Any]]]:
    selected = {ref_name: [] for ref_name in expected_refs}
    for run in workflow_runs:
        ref_name = run.get("head_branch")
        if ref_name not in selected:
            continue
        if run.get("workflow_id") != workflow_id:
            continue
        if run.get("event") != "push" or run.get("head_sha") != sha:
            continue
        if _parse_run_time(run) < created_after:
            continue
        selected[ref_name].append(run)
    return selected


def _run_summary(run: dict[str, Any]) -> str:
    return (
        f"run_id={run.get('id')} attempt={run.get('run_attempt')} "
        f"status={run.get('status')} conclusion={run.get('conclusion')} "
        f"url={run.get('html_url')}"
    )


def _evaluate_runs(
    selected: dict[str, list[dict[str, Any]]],
) -> tuple[bool, list[str]]:
    pending: list[str] = []
    for ref_name, runs in selected.items():
        if len(runs) > 1:
            raise VerificationError(
                f"Multiple applicable Repository audit runs found for {ref_name}."
            )
        if not runs:
            pending.append(ref_name)
            continue

        run = runs[0]
        if run.get("status") != "completed":
            pending.append(ref_name)
            continue
        if run.get("conclusion") != "success":
            raise VerificationError(
                f"Repository audit failed for {ref_name}: {_run_summary(run)}"
            )
    return not pending, pending


def _wait_for_runs(
    repository: str,
    workflow_id: int,
    sha: str,
    expected_refs: Sequence[str],
    created_after: datetime,
    timeout_seconds: int,
    poll_seconds: int,
    verbose: bool,
    query_runs: Callable[[str, str], list[dict[str, Any]]] = _query_runs,
) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        workflow_runs = query_runs(repository, sha)
        selected = _select_applicable_runs(
            workflow_runs,
            workflow_id,
            sha,
            expected_refs,
            created_after,
        )
        complete, pending = _evaluate_runs(selected)
        if complete:
            return {
                ref_name: runs[0]
                for ref_name, runs in selected.items()
            }

        if time.monotonic() >= deadline:
            missing = ", ".join(pending)
            raise VerificationError(
                f"Timed out waiting for Repository audit runs: {missing}"
            )

        _write_verbose(verbose, f"Waiting for Repository audit: {', '.join(pending)}")
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        created_after = _validate_args(args)
        if args.dry_run:
            print(
                "Would verify Repository audit push runs: "
                f"repository={args.repository} workflow_id={args.workflow_id} "
                f"sha={args.sha} refs={','.join(args.refs)} "
                f"created_after={args.created_after}"
            )
            return 0

        verified = _wait_for_runs(
            repository=args.repository,
            workflow_id=args.workflow_id,
            sha=args.sha.lower(),
            expected_refs=args.refs,
            created_after=created_after,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            verbose=args.verbose,
        )
    except VerificationError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    for ref_name in args.refs:
        print(f"Repository audit succeeded for {ref_name}: {_run_summary(verified[ref_name])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
