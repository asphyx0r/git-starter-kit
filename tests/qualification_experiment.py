#!/usr/bin/env python3
"""Hosted, explicitly simulated qualification experiment; never a release gate."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("full", "reuse", "fallback")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def fingerprint(folder):
    result = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"linked experimental input: {path}")
        if path.is_file() and path != folder / "manifest.json":
            result[path.relative_to(folder).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def write_manifest(folder):
    write(folder / "manifest.json", fingerprint(folder))


def check_manifest(folder):
    if load(folder / "manifest.json") != fingerprint(folder):
        raise ValueError("experimental manifest differs")


def qualification():
    spec = importlib.util.spec_from_file_location(
        "qualification_experiment_source", ROOT / "tools/quality/qualification.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExperimentAPI:
    """Closed API fixture: real run/date/bytes, explicitly simulated eligibility."""

    def __init__(self, root, actual, sha, q):
        self.root, self.actual, self.sha, self.q = root, copy.deepcopy(actual), sha, q
        self.run = {
            **actual,
            "head_sha": sha,
            "event": "push",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "path": q.WORKFLOW,
        }
        self.archive = None
        self.artifact = None

    def bind(self, packet):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(self.q.PACKET_FILES | {"packet.json"}):
                archive.writestr(name, (packet / name).read_bytes())
        self.archive = buffer.getvalue()
        self.artifact = {
            "id": 1,
            "name": f"qualification-{self.sha}-{self.run['id']}-{self.run['run_attempt']}",
            "expired": False,
            "digest": "sha256:" + hashlib.sha256(self.archive).hexdigest(),
            "workflow_run": {"id": self.run["id"], "head_sha": self.sha},
        }

    def __call__(self, endpoint, *, binary=False):
        prefix = f"repos/{self.q.REPOSITORY}"
        parsed = urlsplit(endpoint)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError(f"unrecognized experimental API: {endpoint}")
        path, query = parsed.path, parse_qs(parsed.query)
        if binary:
            if (
                path == f"{prefix}/actions/artifacts/1/zip"
                and not query
                and self.archive is not None
            ):
                return self.archive
            raise ValueError(f"unrecognized experimental API: {endpoint}")
        if path == prefix and not query:
            return {"default_branch": "main"}
        if path == f"{prefix}/actions/workflows/repository-audit.yml" and not query:
            return {"id": self.run["workflow_id"], "path": self.q.WORKFLOW}
        if path == f"{prefix}/commits" and query == {
            "sha": ["main"],
            "per_page": ["1"],
        }:
            return [{"sha": self.sha}]
        for name in self.q.TRUSTED_FILES:
            if path == f"{prefix}/contents/{name}" and query == {"ref": [self.sha]}:
                return {
                    "encoding": "base64",
                    "content": base64.b64encode((self.root / name).read_bytes()).decode(
                        "ascii"
                    ),
                }
        if (
            path == f"{prefix}/actions/workflows/repository-audit.yml/runs"
            and query
            == {
                "per_page": ["100"],
                "event": ["push"],
                "head_sha": [self.sha],
                "branch": ["main"],
            }
        ):
            return [{"workflow_runs": [copy.deepcopy(self.run)]}]
        if path == f"{prefix}/actions/runs/{self.run['id']}" and not query:
            return copy.deepcopy(self.run)
        if path == f"{prefix}/actions/runs/{self.run['id']}/artifacts" and query == {
            "per_page": ["100"]
        }:
            return [
                {"artifacts": [copy.deepcopy(self.artifact)] if self.artifact else []}
            ]
        if path == f"{prefix}/actions/artifacts/1" and not query and self.artifact:
            return copy.deepcopy(self.artifact)
        raise ValueError(f"unrecognized experimental API: {endpoint}")


def require_packet(q, root, packet, fresh, context):
    value = load(packet / "packet.json")
    if value["files"] != {
        name: q.digest(packet / name) for name in sorted(q.PACKET_FILES)
    }:
        raise ValueError("retained packet files differ")
    if value["inputs"] != {name: q.digest(root / name) for name in q.INPUTS}:
        raise ValueError("retained packet inputs differ")
    with tempfile.TemporaryDirectory(dir=packet.parent) as temporary:
        scratch = Path(temporary)
        for name in q.PACKET_FILES:
            target = scratch / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(packet / name, target)
        q.validate_pair(root, scratch, value["producer"], fresh, context)
    return value


def distribution(values):
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def summarize(rows, warmup):
    scenarios = {}
    for name in SCENARIOS:
        platforms = {
            p: distribution(
                [r["scenarios"][name]["seconds"] for r in rows if r["platform"] == p]
            )
            for p in ("linux", "windows")
        }
        pairs = [
            [
                next(
                    r["scenarios"][name]["seconds"]
                    for r in rows
                    if r["platform"] == p and r["sample"] == sample
                )
                for p in ("linux", "windows")
            ]
            for sample in (1, 2, 3)
        ]
        scenarios[name] = {
            **platforms,
            "critical_path": distribution([max(pair) for pair in pairs]),
            "runner_sum": distribution([sum(pair) for pair in pairs]),
        }
    sequences = {
        name: {
            "critical_path": max(warmup.values())
            + 2 * scenarios[name]["critical_path"]["median"],
            "runner_sum": sum(warmup.values())
            + 2 * scenarios[name]["runner_sum"]["median"],
        }
        for name in SCENARIOS
    }
    if all("tag_seconds" in row["scenarios"]["reuse"] for row in rows):
        for metric, operation in (("critical_path", max), ("runner_sum", sum)):
            sequences["reuse"][metric] = operation(warmup.values()) + sum(
                statistics.median(
                    [
                        operation(
                            [
                                next(
                                    row["scenarios"]["reuse"][key]
                                    for row in rows
                                    if row["platform"] == platform
                                    and row["sample"] == sample
                                )
                                for platform in ("linux", "windows")
                            ]
                        )
                        for sample in (1, 2, 3)
                    ]
                )
                for key in ("tag_seconds", "release_seconds")
            )
    return {
        "scenarios": scenarios,
        "sequences": sequences,
        "warmup_python_shell_seconds": warmup,
    }


def measured(q, folder, platform):
    """Execute the same real Python discovery and shell commands as heavy CI."""
    artifacts = q.module("coverage-artifacts")
    folder.mkdir()
    started = time.monotonic()
    before = artifacts.environment(ROOT, platform)
    write(folder / "before.json", before)
    raw = folder / "raw.coverage"
    tests = folder / "tests.json"
    with (folder / "python.log").open("wb") as log:
        subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "coverage",
                "run",
                "--rcfile=tools/quality/pyproject.toml",
                "--data-file",
                str(raw),
                "tools/quality/coverage-artifacts.py",
                "tests",
                "--output",
                str(tests),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=900,
        )
    target = folder / "measurements"
    artifacts.export(ROOT, raw, target, platform)
    shutil.copyfile(tests, target / "tests.json")
    data, _ = artifacts.read_data(raw, ROOT)
    try:
        artifacts.coverage_report(ROOT, [data], target / "coverage.json")
    finally:
        data.close(force=True)
    if artifacts.run_shell(target, platform):
        raise ValueError(f"experimental shell failure: {platform}")
    after = artifacts.environment(ROOT, platform)
    write(target / "environment-before.json", before)
    write(target / "environment-after.json", after)
    if before != after:
        raise ValueError("experimental heavy environment changed")
    return {
        "seconds": time.monotonic() - started,
        "tests": load(tests),
        "measurements": target.relative_to(folder.parent).as_posix(),
    }


def run_sample(args):
    q = qualification()
    context = q.context_from_environment()
    if context["event"] != "workflow_dispatch" or context["repository"] != q.REPOSITORY:
        raise ValueError("experiment requires an actual canonical workflow_dispatch")
    result = subprocess.run(
        ["gh", "api", f"repos/{q.REPOSITORY}/actions/runs/{context['run']}"],
        capture_output=True,
        check=True,
        timeout=60,
    )
    actual = json.loads(result.stdout)
    if (
        actual["head_sha"] != context["sha"]
        or str(actual["run_attempt"]) != context["attempt"]
        or str(actual["id"]) != context["run"]
        or actual["event"] != context["event"]
        or actual["path"] != q.WORKFLOW
    ):
        raise ValueError("actual run differs from experiment identity")
    folder = args.output / f"sample-{args.platform}-{args.sample}"
    folder.mkdir(parents=True, exist_ok=False)
    source = folder / "source"
    fresh = folder / "fresh"
    shutil.copytree(args.measurements, source)
    shutil.copytree(args.fresh, fresh)
    for platform in ("linux", "windows"):
        meta = load(source / platform / "metadata.json")
        if any(
            meta[k] != context[v]
            for k, v in (("commit", "sha"), ("run", "run"), ("attempt", "attempt"))
        ):
            raise ValueError("warmup identity differs from experiment")
    current = q.module("coverage-artifacts").environment(ROOT, args.platform)
    if current != load(fresh / f"{args.platform}.json"):
        raise ValueError("sample runner differs from warmup environment")
    api = ExperimentAPI(ROOT, actual, context["sha"], q)
    producer_context = {
        **context,
        "event": "push",
        "ref": "refs/heads/main",
        "action": "",
    }
    packet = folder / "packet"
    sealed = q.seal(ROOT, producer_context, source, fresh, packet, api=api)
    if not sealed["sealed"]:
        raise ValueError(sealed["reason"])
    api.bind(packet)
    consumer = {
        **context,
        "event": "push",
        "ref": "refs/tags/v0.0.0-experiment",
        "action": "",
    }

    def verify(destination, selected_fresh=fresh):
        candidate = q.resolve(ROOT, consumer, api=api)
        return q.verify(ROOT, consumer, candidate, selected_fresh, destination, api=api)

    if verify(folder / "unmeasured-warmup")["decision"] != "reuse":
        raise ValueError("warm helper roundtrip failed")
    source_hashes = {name: q.digest(packet / name) for name in sorted(q.PACKET_FILES)}
    scenarios = {}
    order = SCENARIOS[args.sample - 1 :] + SCENARIOS[: args.sample - 1]
    for name in order:
        started = time.monotonic()
        if name == "full":
            missing_api = ExperimentAPI(ROOT, actual, context["sha"], q)
            selected = q.resolve(ROOT, consumer, api=missing_api)
            decision = q.verify(
                ROOT,
                consumer,
                selected,
                fresh,
                folder / "full-refused",
                api=missing_api,
            )
            if decision["decision"] != "full":
                raise ValueError("missing producer proof did not select full")
            scenarios[name] = {
                **measured(q, folder / name, args.platform),
                "decision": decision,
                "seconds": time.monotonic() - started,
            }
        elif name == "reuse":
            decision = verify(folder / "retained")
            if decision["decision"] != "reuse":
                raise ValueError(decision["reason"])
            require_packet(q, ROOT, folder / "retained", fresh, consumer)
            tag_seconds = time.monotonic() - started
            release_context = {**consumer, "event": "release", "action": "published"}
            release_started = time.monotonic()
            selected = q.resolve(ROOT, release_context, api=api)
            release_decision = q.verify(
                ROOT,
                release_context,
                selected,
                fresh,
                folder / "retained-release",
                api=api,
            )
            if release_decision != decision:
                raise ValueError(
                    "release consumer changed original producer identity or age"
                )
            require_packet(q, ROOT, folder / "retained-release", fresh, release_context)
            release_seconds = time.monotonic() - release_started
            scenarios[name] = {
                "seconds": (tag_seconds + release_seconds) / 2,
                "tag_seconds": tag_seconds,
                "release_seconds": release_seconds,
                "decision": decision,
                "release_decision": release_decision,
            }
        else:
            invalid = folder / "invalid-fresh"
            shutil.copytree(fresh, invalid)
            windows = load(invalid / "windows.json")
            windows["facts"]["image_version"] += "-experimental-drift"
            write(invalid / "windows.json", windows)
            decision = verify(folder / "fallback-refused", invalid)
            if decision["decision"] != "full":
                raise ValueError("Windows image drift was not refused")
            scenarios[name] = {
                **measured(q, folder / name, args.platform),
                "decision": decision,
                "seconds": time.monotonic() - started,
            }
        if name in ("full", "fallback"):
            expected_tests = load(source / args.platform / "tests.json")
            observed = scenarios[name]["tests"]
            if any(
                observed[key] != expected_tests[key] for key in ("run", "skipped")
            ) or any(
                observed[key] for key in ("failures", "errors", "unexpected_successes")
            ):
                raise ValueError("measured test discovery differs from frozen warmup")
    loss = folder / "postdecision-loss"
    shutil.copytree(folder / "retained", loss)
    (loss / "linux/.coverage").unlink()
    try:
        require_packet(q, ROOT, loss, fresh, consumer)
    except (ValueError, OSError):
        loss_refused = True
    else:
        raise ValueError("postdecision proof loss was not refused")
    if source_hashes != {
        name: q.digest(packet / name) for name in sorted(q.PACKET_FILES)
    }:
        raise ValueError("source packet changed")
    row = {
        "schema": 1,
        "experimental": True,
        "platform": args.platform,
        "sample": args.sample,
        "actual_context": context,
        "actual_run": actual,
        "simulated_producer": api.run,
        "consumer_context": consumer,
        "source_files": source_hashes,
        "source_packet": load(packet / "packet.json"),
        "order": order,
        "postdecision_loss_refused": loss_refused,
        "scenarios": scenarios,
        "setup_cache_hits": {
            name: {"true": True, "false": False}.get(
                os.environ.get(variable, "").lower()
            )
            for name, variable in (
                ("python", "PYTHON_CACHE_HIT"),
                ("npm", "NPM_CACHE_HIT"),
            )
        },
        "cache_regime": "setup pip/npm download caches; fresh node_modules per runner; no suite cache; unmeasured helper warmup",
    }
    write(folder / "sample.json", row)
    write_manifest(folder)
    print(
        json.dumps(
            {"sample": args.sample, "platform": args.platform, "result": "success"}
        )
    )


def aggregate(args):
    q = qualification()
    folders = sorted(args.input.glob("sample-*"))
    if len(folders) != 6:
        raise ValueError("expected exactly six experimental samples")
    rows = []
    for folder in folders:
        check_manifest(folder)
        row = load(folder / "sample.json")
        if (
            row.get("schema") != 1
            or row.get("experimental") is not True
            or row["postdecision_loss_refused"] is not True
        ):
            raise ValueError("invalid experimental sample")
        rows.append(row)
    if {(r["platform"], r["sample"]) for r in rows} != {
        (p, n) for p in ("linux", "windows") for n in (1, 2, 3)
    }:
        raise ValueError("mixed or duplicate sample identities")
    original = rows[0]
    for row in rows:
        for key in ("actual_context", "source_packet", "source_files"):
            if row[key] != original[key]:
                raise ValueError(f"mixed experimental {key}")
        if set(row["scenarios"]) != set(SCENARIOS) or any(
            not math.isfinite(row["scenarios"][name]["seconds"])
            or row["scenarios"][name]["seconds"] < 0
            for name in SCENARIOS
        ):
            raise ValueError("incomplete or failed scenarios")
        if any(
            row["scenarios"][name]["decision"]["decision"] != decision
            for name, decision in (
                ("full", "full"),
                ("reuse", "reuse"),
                ("fallback", "full"),
            )
        ):
            raise ValueError("unexpected scenario decisions")
    context = original["actual_context"]
    if any(
        context[k] != os.environ[v]
        for k, v in (
            ("sha", "AUDIT_COMMIT_SHA"),
            ("run", "GITHUB_RUN_ID"),
            ("attempt", "GITHUB_RUN_ATTEMPT"),
        )
    ):
        raise ValueError("aggregate run differs")
    producer = original["source_packet"]["producer"]
    if producer["created_at"] != original["actual_run"]["created_at"] or any(
        producer[key] != context[source]
        for key, source in (("commit", "sha"), ("run", "run"), ("attempt", "attempt"))
    ):
        raise ValueError("original producer identity or age changed")
    args.output.mkdir(parents=True, exist_ok=False)
    floors = []
    for folder, row in zip(folders, rows, strict=True):
        require_packet(
            q, ROOT, folder / "retained", folder / "fresh", row["consumer_context"]
        )
        if load(folder / "retained/packet.json") != original["source_packet"]:
            raise ValueError("retained producer identity or age changed")
        require_packet(
            q,
            ROOT,
            folder / "retained-release",
            folder / "fresh",
            {**row["consumer_context"], "event": "release", "action": "published"},
        )
        if load(folder / "retained-release/packet.json") != original["source_packet"]:
            raise ValueError("release retained producer identity or age changed")
    for sample in (1, 2, 3):
        for scenario in ("full", "fallback"):
            pair = args.output / f"sample-{sample}-{scenario}"
            for platform in ("linux", "windows"):
                folder = args.input / f"sample-{platform}-{sample}"
                shutil.copytree(folder / scenario / "measurements", pair / platform)
            q.validate_pair(
                ROOT,
                pair,
                original["source_packet"]["producer"],
                folders[0] / "fresh",
                original["consumer_context"],
            )
            floors.append(
                {
                    "sample": sample,
                    "scenario": scenario,
                    "combined": load(pair / "combined.json")["totals"],
                    "linux": load(pair / "linux-rechecked.json")["totals"],
                }
            )
    warmup = {}
    for platform in ("linux", "windows"):
        packet = folders[0] / "packet" / platform
        warmup[platform] = load(packet / "tests.json")["seconds"] + sum(
            s["seconds"] for s in load(packet / "shell.json")["suites"]
        )
    result = {
        "schema": 1,
        "experimental": True,
        "actual_context": context,
        "cost_scope": "Observed components assembled as producer once + two consumers; excludes queue, setup, fresh preflight/static/network guards, real API transport and producer sealing; not an end-to-end production measurement.",
        **summarize(rows, warmup),
        "floors": floors,
        "samples": [
            {
                key: row[key]
                for key in (
                    "platform",
                    "sample",
                    "order",
                    "setup_cache_hits",
                    "scenarios",
                )
            }
            for row in rows
        ],
        "source_packet": original["source_packet"],
        "sample_manifests": {
            folder.name: q.digest(folder / "manifest.json") for folder in folders
        },
    }
    write(args.output / "result.json", result)
    lines = [
        "# Experimental qualification measurements",
        "",
        result["cost_scope"],
        "",
        "| Scenario | Linux median (range), s | Windows median (range), s | Pair critical path, s | Runner sum, s |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, values in result["scenarios"].items():
        cells = [
            f"{values[p]['median']:.3f} ({values[p]['min']:.3f}-{values[p]['max']:.3f})"
            for p in ("linux", "windows")
        ]
        lines.append(
            f"| {name} | {cells[0]} | {cells[1]} | {values['critical_path']['median']:.3f} | {values['runner_sum']['median']:.3f} |"
        )
    lines += [
        "",
        "| Assembled producer + two consumers | Critical path, s | Runner sum, s |",
        "| --- | --- | --- |",
    ]
    for name, values in result["sequences"].items():
        lines.append(
            f"| {name} | {values['critical_path']:.3f} | {values['runner_sum']:.3f} |"
        )
    lines += [
        "",
        f"Source `{context['sha']}`, actual event `{context['event']}`, run `{context['run']}`, attempt `{context['attempt']}`. Setup cache hits are recorded per sample in result.json; null means unavailable. Node modules are fresh per runner; heavy suite caches are not cleared between measured paths.",
    ]
    lines += [
        "",
        "Three measured repetitions per OS after the normal real-suite warmup. All full/fallback pairs pass the unchanged coverage floors. API eligibility is simulated; original packet bytes, identities and age are retained.",
        "",
    ]
    (args.output / "result.summary.md").write_text("\n".join(lines), encoding="utf-8")
    write_manifest(args.output)
    print(json.dumps({"result": "success", "samples": len(rows)}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--platform", choices=("linux", "windows"), required=True)
    run.add_argument("--sample", type=int, choices=(1, 2, 3), required=True)
    run.add_argument("--measurements", type=Path, required=True)
    run.add_argument("--fresh", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    combined = commands.add_parser("aggregate")
    combined.add_argument("--input", type=Path, required=True)
    combined.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        (run_sample if args.command == "run" else aggregate)(args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"experimental qualification: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
