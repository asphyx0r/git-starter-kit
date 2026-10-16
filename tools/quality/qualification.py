#!/usr/bin/env python3
"""Resolve, verify and seal indivisible source CI qualifications."""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlencode
import zipfile


REPOSITORY = "asphyx0r/git-starter-kit"
WORKFLOW = ".github/workflows/repository-audit.yml"
TTL = timedelta(days=7)
TRUSTED_FILES = (
    WORKFLOW,
    "tools/quality/qualification.py",
    "tools/repository-audit/workflow-contracts.py",
)
INPUTS = (
    *TRUSTED_FILES,
    "tools/quality/requirements.lock",
    "tools/release-artifacts-requirements.txt",
    "tools/quality/package-lock.json",
    "tools/quality/versions.json",
    "tools/quality/pyproject.toml",
    "tools/quality/coverage-artifacts.py",
    "tools/quality/check-coverage.py",
    "tools/repository-audit/profiles.sh",
)
OS_FILES = (
    ".coverage",
    "metadata.json",
    "coverage.json",
    "tests.json",
    "shell.json",
    "environment-before.json",
    "environment-after.json",
    "shell.log",
)
PACKET_FILES = {
    f"{platform}/{name}" for platform in ("linux", "windows") for name in OS_FILES
}
SEMVER = re.compile(
    r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


def api_request(endpoint: str, *, binary: bool = False) -> Any:
    """Read Actions metadata or archive bytes; never make a mutating request."""
    command = ["gh", "api"]
    if not binary and "?per_page=" in endpoint:
        command += ["--paginate", "--slurp"]
    result = subprocess.run(
        [*command, endpoint], capture_output=True, check=True, timeout=60
    )
    return result.stdout if binary else json.loads(result.stdout)


def load(path: Path) -> dict[str, Any]:
    return mapping(json.loads(path.read_text(encoding="utf-8")), path.name)


def mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {label}")
    return value


def digest(path: Path) -> str:
    if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"missing or linked input: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def full(reason: str) -> dict[str, Any]:
    return {"decision": "full", "reason": reason}


def source(root: Path, context: dict) -> bool:
    return (
        context["repository"] == REPOSITORY
        and load(root / ".starter-kit-project.json").get("repositoryRole") == "source"
    )


def is_producer(root: Path, context: dict, default_branch: str) -> bool:
    return (
        source(root, context)
        and context["event"] == "push"
        and context["ref"] == f"refs/heads/{default_branch}"
    )


def eligible_consumer(root: Path, context: dict) -> bool:
    tag = context["ref"].removeprefix("refs/tags/")
    return source(root, context) and (
        context["event"] == "release"
        and context["action"] == "published"
        or context["event"] == "push"
        and context["ref"].startswith("refs/tags/")
        and SEMVER.fullmatch(tag) is not None
    )


def items(pages: Any, key: str) -> list[dict]:
    if not isinstance(pages, list):
        raise ValueError("invalid paginated API response")
    result = []
    for page in pages:
        rows = mapping(page, "API page")[key]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid API entries")
        result.extend(rows)
    return result


def resolve(
    root: Path, context: dict, *, api=None, now: datetime | None = None
) -> dict:
    """Select the newest eligible producer before considering its outcome."""
    api = api or api_request
    now = now or datetime.now(UTC)
    try:
        if not eligible_consumer(root, context):
            return full("event or repository is not eligible")
        prefix = f"repos/{REPOSITORY}"
        default = mapping(api(prefix), "repository")["default_branch"]
        workflow = mapping(
            api(f"{prefix}/actions/workflows/repository-audit.yml"), "workflow"
        )
        if workflow["path"] != WORKFLOW:
            raise ValueError("unexpected workflow path")
        query = urlencode(
            {
                "per_page": 100,
                "event": "push",
                "head_sha": context["sha"],
                "branch": default,
            }
        )
        runs = items(
            api(f"{prefix}/actions/workflows/repository-audit.yml/runs?{query}"),
            "workflow_runs",
        )
        runs = [
            run
            for run in runs
            if run.get("event") == "push" and run.get("head_branch") == default
        ]
        if not runs:
            return full("no producer")
        newest = max(stamp(run["created_at"]) for run in runs)
        latest = [run for run in runs if stamp(run["created_at"]) == newest]
        if len(latest) != 1:
            raise ValueError("ambiguous latest producer")
        run = latest[0]
        if not (
            run["head_sha"] == context["sha"]
            and run["workflow_id"] == workflow["id"]
            and run["path"] == WORKFLOW
            and run["repository"]["full_name"] == REPOSITORY
            and run["head_repository"]["full_name"] == REPOSITORY
            and run["status"] == "completed"
            and run["conclusion"] == "success"
            and timedelta(0) <= now - newest <= TTL
            and type(run["id"]) is int
            and run["id"] > 0
            and type(run["run_attempt"]) is int
            and run["run_attempt"] > 0
        ):
            raise ValueError("latest producer is unsuccessful, expired or mismatched")
        producer = {
            "repository": REPOSITORY,
            "commit": context["sha"],
            "run": str(run["id"]),
            "attempt": str(run["run_attempt"]),
            "created_at": run["created_at"],
            "branch": default,
            "workflow_id": workflow["id"],
            "workflow": WORKFLOW,
        }
        expected_name = (
            f"qualification-{context['sha']}-{run['id']}-{run['run_attempt']}"
        )
        artifacts = items(
            api(f"{prefix}/actions/runs/{run['id']}/artifacts?per_page=100"),
            "artifacts",
        )
        matching = [a for a in artifacts if a.get("name") == expected_name]
        if len(matching) != 1:
            raise ValueError("missing or ambiguous qualification artifact")
        artifact = matching[0]
        if not (
            artifact["expired"] is False
            and type(artifact["id"]) is int
            and artifact["id"] > 0
            and isinstance(artifact.get("digest"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"])
            and artifact["workflow_run"]["id"] == run["id"]
            and artifact["workflow_run"]["head_sha"] == context["sha"]
        ):
            raise ValueError("expired or unbound qualification artifact")
        return {
            "producer": producer,
            "artifact": {k: artifact[k] for k in ("id", "name", "digest")},
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        return full(str(error))


def trusted_inputs(root: Path, branch: str, api) -> dict[str, str]:
    """Require workflow and validators to match an immutable default-branch tip."""
    query = urlencode({"sha": branch})
    commits = api(f"repos/{REPOSITORY}/commits?{query}&per_page=1")
    if not isinstance(commits, list) or len(commits) != 1:
        raise ValueError("expected one trusted commit")
    commit = mapping(commits[0], "trusted commit")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid trusted revision")
    for path in TRUSTED_FILES:
        remote = mapping(
            api(f"repos/{REPOSITORY}/contents/{path}?ref={commit}"), "trusted content"
        )
        content = base64.b64decode(remote["content"])
        if remote["encoding"] != "base64" or hashlib.sha256(
            content
        ).hexdigest() != digest(root / path):
            raise ValueError(f"trusted default-branch input differs: {path}")
    return {path: digest(root / path) for path in INPUTS}


def module(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def validate_pair(
    root: Path, directory: Path, producer: dict, fresh: Path, context: dict
) -> None:
    """Recheck original identities, executed environments and measured coverage."""
    policy = module("check-coverage")
    artifacts = module("coverage-artifacts")
    expected = {k: producer[k] for k in ("commit", "run", "attempt")}
    expected.update(
        coverage=artifacts.coverage.__version__,
        policy=digest(root / "tools/quality/pyproject.toml"),
    )
    for platform, suites in (("linux", 6), ("windows", 2)):
        folder = directory / platform
        before = load(folder / "environment-before.json")
        after = load(folder / "environment-after.json")
        current = load(fresh / f"{platform}.json")
        if {
            key: current.get(key) for key in ("commit", "run", "attempt", "platform")
        } != {
            "commit": context["sha"],
            "run": context["run"],
            "attempt": context["attempt"],
            "platform": platform,
        }:
            raise ValueError("fresh environment provenance differs")
        if (
            before != after
            or before["facts"] != current["facts"]
            or before["platform"] != platform
        ):
            raise ValueError(f"executed environment differs: {platform}")
        if {k: before[k] for k in expected if k in ("commit", "run", "attempt")} != {
            k: expected[k] for k in ("commit", "run", "attempt")
        }:
            raise ValueError("heavy environment provenance differs")
        if not mapping(before["facts"], "environment facts").get("image_version"):
            raise ValueError("missing hosted image identity")
        tests = load(folder / "tests.json")
        counts = [
            tests[k]
            for k in (
                "run",
                "skipped",
                "failures",
                "errors",
                "expected_failures",
                "unexpected_successes",
            )
        ]
        if (
            any(type(n) is not int or n < 0 for n in counts)
            or tests["run"] <= 0
            or tests["run"] <= tests["skipped"]
            or any(tests[k] for k in ("failures", "errors", "unexpected_successes"))
        ):
            raise ValueError("Python tests were not successful")
        shell = load(folder / "shell.json")
        expected_suites = artifacts.shell_suites(platform)
        if (
            shell.get("platform") != platform
            or len(shell["suites"]) != suites
            or [s["command"] for s in shell["suites"]] != expected_suites
            or any(s["returncode"] != 0 or s["seconds"] < 0 for s in shell["suites"])
        ):
            raise ValueError("shell suites are incomplete or failed")
    combined = artifacts.combine(root, directory, expected_identity=expected)
    minimum = load(root / "tools/quality/versions.json")["policy"]["coverageFailUnder"]
    for report in (load(directory / "linux-rechecked.json"), combined):
        passed, message = policy.evaluate_report(report, minimum)
        if not passed:
            raise ValueError(message)


def verify(
    root: Path,
    context: dict,
    candidate: dict,
    fresh: Path,
    destination: Path,
    *,
    api=None,
    now: datetime | None = None,
) -> dict:
    """Emit one fail-closed decision; preserve the original packet unchanged."""
    from coverage.exceptions import CoverageException

    api = api or api_request
    if candidate.get("decision") == "full":
        return full(
            str(candidate.get("reason", "candidate requires full qualification"))
        )
    try:
        current = resolve(root, context, api=api, now=now)
        if current != candidate:
            raise ValueError("candidate disappeared or changed after selection")
        producer = candidate["producer"]
        run = mapping(
            api(f"repos/{REPOSITORY}/actions/runs/{producer['run']}"), "producer"
        )
        if (
            str(run["id"]) != producer["run"]
            or str(run["run_attempt"]) != producer["attempt"]
            or run["head_sha"] != producer["commit"]
            or run["created_at"] != producer["created_at"]
            or run["status"] != "completed"
            or run["conclusion"] != "success"
            or run["path"] != WORKFLOW
            or run["workflow_id"] != producer["workflow_id"]
            or run["event"] != "push"
            or run["head_branch"] != producer["branch"]
            or run["repository"]["full_name"] != REPOSITORY
            or run["head_repository"]["full_name"] != REPOSITORY
        ):
            raise ValueError("producer changed after selection")
        inputs = trusted_inputs(root, producer["branch"], api)
        artifact = mapping(
            api(f"repos/{REPOSITORY}/actions/artifacts/{candidate['artifact']['id']}"),
            "artifact",
        )
        if artifact.get("expired") is not False or any(
            artifact.get(k) != v for k, v in candidate["artifact"].items()
        ):
            raise ValueError("artifact disappeared or changed")
        archive = api(
            f"repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip", binary=True
        )
        if (
            not isinstance(archive, bytes)
            or len(archive) > 64 * 1024 * 1024
            or "sha256:" + hashlib.sha256(archive).hexdigest() != artifact["digest"]
        ):
            raise ValueError("artifact archive digest mismatch")
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            unpacked = Path(temporary)
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                members = zipped.infolist()
                files = [member for member in members if not member.is_dir()]
                if (
                    {m.filename for m in files} != PACKET_FILES | {"packet.json"}
                    or len({m.filename for m in members}) != len(members)
                    or any(
                        m.filename not in {"linux/", "windows/"} or m.file_size
                        for m in members
                        if m.is_dir()
                    )
                    or sum(m.file_size for m in members) > 64 * 1024 * 1024
                ):
                    raise ValueError("unexpected qualification archive members")
                for member in files:
                    path = unpacked / member.filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(zipped.read(member))
            packet = load(unpacked / "packet.json")
            if (
                packet.get("schema") != 1
                or packet.get("producer") != producer
                or packet.get("inputs") != inputs
                or packet.get("files")
                != {name: digest(unpacked / name) for name in sorted(PACKET_FILES)}
            ):
                raise ValueError("qualification packet provenance or files differ")
            validate_pair(root, unpacked, producer, fresh, context)
            shutil.copytree(unpacked, destination)
        return {
            "decision": "reuse",
            "reason": "original Linux and Windows qualification verified",
            "producer": producer,
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
        CoverageException,
    ) as error:
        return full(str(error))


def seal(
    root: Path,
    context: dict,
    measurements: Path,
    fresh: Path,
    destination: Path,
    *,
    api=None,
) -> dict:
    """Prepare an original producer packet; never promote a consumer copy."""
    from coverage.exceptions import CoverageException

    api = api or api_request
    try:
        default = mapping(api(f"repos/{REPOSITORY}"), "repository")["default_branch"]
        if not is_producer(root, context, default):
            return {"sealed": False, "reason": "not a default-branch push producer"}
        run = mapping(
            api(f"repos/{REPOSITORY}/actions/runs/{context['run']}"), "producer"
        )
        if (
            run["head_sha"] != context["sha"]
            or run["event"] != "push"
            or run["head_branch"] != default
            or run["path"] != WORKFLOW
            or str(run["run_attempt"]) != context["attempt"]
            or run["head_repository"]["full_name"] != REPOSITORY
            or run["repository"]["full_name"] != REPOSITORY
        ):
            raise ValueError("current producer provenance differs")
        producer = {
            "repository": REPOSITORY,
            "commit": context["sha"],
            "run": context["run"],
            "attempt": context["attempt"],
            "created_at": run["created_at"],
            "branch": default,
            "workflow_id": run["workflow_id"],
            "workflow": WORKFLOW,
        }
        inputs = trusted_inputs(root, default, api)
        validate_pair(root, measurements, producer, fresh, context)
        packet = {
            "schema": 1,
            "producer": producer,
            "inputs": inputs,
            "files": {
                name: digest(measurements / name) for name in sorted(PACKET_FILES)
            },
        }
        destination.mkdir(parents=True, exist_ok=False)
        for name in PACKET_FILES:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(measurements / name, target)
        (destination / "packet.json").write_text(
            json.dumps(packet, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {"sealed": True, "reason": "full producer pair sealed"}
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        CoverageException,
    ) as error:
        return {"sealed": False, "reason": str(error)}


def context_from_environment() -> dict:
    event = load(Path(os.environ["GITHUB_EVENT_PATH"]))
    return {
        "repository": os.environ["GITHUB_REPOSITORY"],
        "sha": os.environ["AUDIT_COMMIT_SHA"],
        "run": os.environ["GITHUB_RUN_ID"],
        "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "event": os.environ["GITHUB_EVENT_NAME"],
        "ref": os.environ["GITHUB_REF"],
        "action": event.get("action", ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("resolve", "verify", "seal"):
        sub = commands.add_parser(command)
        sub.add_argument("--output", type=Path, required=True)
        if command != "resolve":
            sub.add_argument("--fresh", type=Path, required=True)
            sub.add_argument("--destination", type=Path, required=True)
            sub.add_argument(
                "--candidate" if command == "verify" else "--measurements",
                type=Path,
                required=True,
            )
    args = parser.parse_args(argv)
    try:
        context = context_from_environment()
        root = Path.cwd()
        if args.command == "resolve":
            result = resolve(root, context)
        elif args.command == "verify":
            try:
                candidate = load(args.candidate)
            except (OSError, ValueError):
                candidate = full("candidate is missing or invalid")
            result = verify(root, context, candidate, args.fresh, args.destination)
        else:
            result = seal(
                root, context, args.measurements, args.fresh, args.destination
            )
        args.output.write_text(
            json.dumps(result, sort_keys=True) + "\n", encoding="utf-8"
        )
        output = os.environ.get("GITHUB_OUTPUT")
        if output and args.command != "resolve":
            key = "decision" if args.command == "verify" else "sealed"
            value = str(result[key]).lower()
            with Path(output).open("a", encoding="utf-8") as stream:
                stream.write(f"{key}={value}\n")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"qualification: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
