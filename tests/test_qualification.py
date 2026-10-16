"""Exercise qualification provenance with a controlled Actions API."""

from __future__ import annotations

import copy
import base64
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
import importlib.util
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from coverage import CoverageData


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/quality/qualification.py"
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
SHA = "a" * 40


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "qualification protocol is missing")
        spec = importlib.util.spec_from_file_location("qualification", SCRIPT)
        self.q = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.q)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".starter-kit-project.json").write_text(
            '{"repositoryRole":"source"}', encoding="utf-8"
        )
        self.context = {
            "repository": "asphyx0r/git-starter-kit",
            "sha": SHA,
            "event": "push",
            "ref": "refs/tags/v1.2.3",
            "action": "",
            "run": "50",
            "attempt": "1",
        }
        self.run = {
            "id": 40,
            "run_attempt": 2,
            "workflow_id": 7,
            "head_sha": SHA,
            "head_branch": "main",
            "event": "push",
            "path": ".github/workflows/repository-audit.yml",
            "repository": {"full_name": "asphyx0r/git-starter-kit"},
            "head_repository": {"full_name": "asphyx0r/git-starter-kit"},
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-10-15T12:00:00Z",
        }
        self.runs = [self.run]
        self.artifact = {
            "id": 71,
            "name": f"qualification-{SHA}-40-2",
            "expired": False,
            "digest": "sha256:" + "b" * 64,
            "workflow_run": {"id": 40, "head_sha": SHA},
        }
        self.artifacts = [self.artifact]

    def api(self, endpoint, *, binary=False):
        self.assertFalse(binary)
        if endpoint.endswith("/git-starter-kit"):
            return {"default_branch": "main"}
        if endpoint.endswith("/workflows/repository-audit.yml"):
            return {"id": 7, "path": ".github/workflows/repository-audit.yml"}
        if "/runs?" in endpoint:
            return [{"workflow_runs": self.runs}]
        if endpoint.endswith("/artifacts?per_page=100"):
            return [{"artifacts": self.artifacts}]
        if endpoint.endswith("/runs/40"):
            return self.run
        if endpoint.endswith("/artifacts/71"):
            return self.artifact
        self.fail(f"unexpected API request: {endpoint}")

    def resolve(self):
        return self.q.resolve(self.root, self.context, api=self.api, now=NOW)

    def test_selects_exact_successful_default_branch_producer(self):
        candidate = self.resolve()
        self.assertEqual(candidate["producer"]["run"], "40")
        self.assertEqual(candidate["producer"]["attempt"], "2")
        self.assertEqual(candidate["artifact"]["id"], 71)
        self.assertEqual(candidate["producer"]["created_at"], self.run["created_at"])

    def test_malformed_full_candidate_still_selects_common_full(self):
        result = self.q.verify(
            self.root,
            self.context,
            {"decision": "full"},
            self.root / "fresh",
            self.root / "verified",
            api=self.api,
        )
        self.assertEqual(result["decision"], "full")

    def test_newer_failed_or_pending_run_never_falls_back_to_older_green(self):
        for status, conclusion in (("completed", "failure"), ("in_progress", None)):
            with self.subTest(status=status):
                self.runs = [
                    self.run,
                    {
                        **self.run,
                        "id": 41,
                        "status": status,
                        "conclusion": conclusion,
                        "created_at": "2026-10-16T11:00:00Z",
                    },
                ]
                self.assertEqual(self.resolve()["decision"], "full")

    def test_rejects_wrong_sha_origin_path_workflow_and_expired_run(self):
        for key, value in (
            ("head_sha", "c" * 40),
            ("workflow_id", 8),
            ("path", ".github/workflows/other.yml"),
            ("head_repository", {"full_name": "other/fork"}),
            ("repository", {"full_name": "other/fork"}),
            ("created_at", "2026-10-08T12:00:00Z"),
            ("created_at", "2026-10-17T12:00:00Z"),
        ):
            with self.subTest(key=key), mock.patch.dict(self.run, {key: value}):
                self.assertEqual(self.resolve()["decision"], "full")

    def test_ordinary_events_consumers_and_noncanonical_repositories_are_full(self):
        for change in (
            {"event": "pull_request"},
            {"event": "workflow_dispatch"},
            {"ref": "refs/heads/main"},
            {"ref": "refs/heads/codex/release-preflight-x"},
            {"ref": "refs/tags/v01.2.3"},
            {"repository": "other/project"},
            {"event": "release", "action": "edited"},
        ):
            with self.subTest(change=change), mock.patch.dict(self.context, change):
                self.assertEqual(self.resolve()["decision"], "full")
        (self.root / ".starter-kit-project.json").write_text(
            '{"repositoryRole":"project"}', encoding="utf-8"
        )
        self.assertEqual(self.resolve()["decision"], "full")

    def test_release_published_can_select_but_never_produce(self):
        self.context.update(event="release", action="published")
        self.assertIn("producer", self.resolve())
        self.assertFalse(self.q.is_producer(self.root, self.context, "main"))

    def test_missing_duplicate_expired_or_unbound_artifact_is_full(self):
        for artifacts in (
            [],
            [self.artifact, self.artifact],
            [{**self.artifact, "expired": True}],
            [{**self.artifact, "digest": None}],
            [{**self.artifact, "workflow_run": {"id": 39, "head_sha": SHA}}],
        ):
            with self.subTest(artifacts=artifacts):
                self.artifacts = artifacts
                self.assertEqual(self.resolve()["decision"], "full")

    def test_ambiguous_latest_and_api_error_are_full(self):
        self.runs = [self.run, {**self.run, "id": 41}]
        self.assertEqual(self.resolve()["decision"], "full")
        with mock.patch.object(self.q, "api_request", side_effect=OSError("offline")):
            self.assertEqual(
                self.q.resolve(self.root, self.context, now=NOW)["decision"], "full"
            )

    def test_verify_lost_or_replaced_candidate_falls_back_both_operating_systems(self):
        candidate = self.resolve()
        for key, value in (("digest", "sha256:" + "d" * 64), ("expired", True)):
            with self.subTest(key=key), mock.patch.dict(self.artifact, {key: value}):
                decision = self.q.verify(
                    self.root,
                    self.context,
                    candidate,
                    self.root / "fresh",
                    self.root / "verified",
                    api=self.api,
                    now=NOW,
                )
                self.assertEqual(decision["decision"], "full")
                self.assertNotIn("linux", decision)

    def test_full_decision_contains_no_refreshable_producer_identity(self):
        result = self.q.verify(
            self.root,
            self.context,
            {"decision": "full", "reason": "no proof"},
            self.root / "fresh",
            self.root / "verified",
            api=self.api,
            now=NOW,
        )
        self.assertEqual(result, {"decision": "full", "reason": "no proof"})

    def test_verify_rechecks_exact_run_after_paginated_selection(self):
        candidate = self.resolve()

        def changed_run(endpoint, *, binary=False):
            if endpoint.endswith("/runs/40"):
                return {**self.run, "run_attempt": 3, "status": "in_progress"}
            return self.api(endpoint, binary=binary)

        result = self.q.verify(
            self.root,
            self.context,
            candidate,
            self.root / "fresh",
            self.root / "verified",
            api=changed_run,
            now=NOW,
        )
        self.assertEqual(result["decision"], "full")
        self.assertIn("producer changed", result["reason"])

    def test_seven_day_boundary_is_inclusive_without_renewal(self):
        with mock.patch.dict(self.run, {"created_at": "2026-10-09T12:00:00Z"}):
            self.assertIn("producer", self.resolve())
            result = self.q.resolve(
                self.root, self.context, api=self.api, now=NOW + timedelta(seconds=1)
            )
            self.assertEqual(result["decision"], "full")

    def test_cli_fallback_outputs_never_control_activation(self):
        event = self.root / "event.json"
        event.write_text('{"action":"published"}')
        output = self.root / "result.json"
        github_output = self.root / "outputs"
        environment = {
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_REPOSITORY": self.context["repository"],
            "AUDIT_COMMIT_SHA": SHA,
            "GITHUB_RUN_ID": "50",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_EVENT_NAME": "release",
            "GITHUB_REF": "refs/tags/v1.2.3",
            "GITHUB_OUTPUT": str(github_output),
        }
        with (
            mock.patch.dict(os.environ, environment),
            mock.patch.object(Path, "cwd", return_value=self.root),
            mock.patch.object(self.q, "api_request", side_effect=self.api),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(self.q.main(["resolve", "--output", str(output)]), 0)
            self.assertFalse(github_output.exists())
            self.assertEqual(
                self.q.main(
                    [
                        "verify",
                        "--candidate",
                        str(self.root / "absent.json"),
                        "--fresh",
                        str(self.root / "fresh"),
                        "--destination",
                        str(self.root / "verified"),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            self.assertEqual(json.loads(output.read_text())["decision"], "full")
            self.assertEqual(
                self.q.main(
                    [
                        "seal",
                        "--measurements",
                        str(self.root / "measurements"),
                        "--fresh",
                        str(self.root / "fresh"),
                        "--destination",
                        str(self.root / "sealed"),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
        self.assertEqual(github_output.read_text(), "decision=full\nsealed=false\n")
        with (
            mock.patch.dict(
                os.environ, {"GITHUB_EVENT_PATH": str(self.root / "missing")}
            ),
            redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(self.q.main(["resolve", "--output", str(output)]), 1)
        self.assertIn("qualification:", error.getvalue())
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{resolve,verify,seal}", result.stdout)

    def test_api_transport_is_get_only_bounded_and_preserves_binary(self):
        payload = subprocess.CompletedProcess([], 0, stdout=b'[{"workflow_runs": []}]')
        with mock.patch.object(subprocess, "run", return_value=payload) as process:
            self.assertEqual(
                self.q.api_request("repos/owner/repo/runs?per_page=100"),
                [{"workflow_runs": []}],
            )
            self.assertEqual(
                process.call_args.args[0],
                [
                    "gh",
                    "api",
                    "--paginate",
                    "--slurp",
                    "repos/owner/repo/runs?per_page=100",
                ],
            )
            self.assertEqual(process.call_args.kwargs["timeout"], 60)
            payload.stdout = b"raw archive"
            self.assertEqual(
                self.q.api_request("repos/owner/repo/artifacts/1/zip", binary=True),
                b"raw archive",
            )

    def test_invalid_json_types_links_and_api_pages_are_rejected(self):
        path = self.root / "value.json"
        path.write_text("[]")
        with self.assertRaises(ValueError):
            self.q.load(path)
        with (
            mock.patch.object(Path, "is_symlink", return_value=True),
            self.assertRaises(ValueError),
        ):
            self.q.digest(path)
        for pages in ({}, [None], [{"workflow_runs": {}}], [{"workflow_runs": [None]}]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                self.q.items(pages, "workflow_runs")
        for event in ("pull_request", "workflow_dispatch"):
            with mock.patch.dict(self.run, {"event": event}):
                self.assertEqual(self.resolve()["decision"], "full")
        self.runs = []
        self.assertEqual(self.resolve()["decision"], "full")


class QualificationPacketTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("packet_qualification", SCRIPT)
        self.q = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.q)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.measurements = self.root / "measurements"
        self.fresh = self.root / "fresh"
        self.fresh.mkdir()
        self.packet = self.root / "packet"
        self.context = {
            "repository": "asphyx0r/git-starter-kit",
            "sha": SHA,
            "event": "push",
            "ref": "refs/heads/main",
            "action": "",
            "run": "40",
            "attempt": "2",
        }
        for path in self.q.INPUTS:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "def flag(value):\n    if value:\n        return 1\n    return 0\n"
                if path.endswith(".py")
                else "fixture\n",
                encoding="utf-8",
            )
        (self.root / ".starter-kit-project.json").write_text(
            '{"repositoryRole":"source"}'
        )
        (self.root / "tools/quality/versions.json").write_text(
            json.dumps(
                {"python": {"coverage": "7.16.2"}, "policy": {"coverageFailUnder": 85}}
            )
        )
        (self.root / "tools/quality/pyproject.toml").write_text(
            '[tool.coverage.run]\nbranch = true\nrelative_files = true\nsource = ["tools"]\n'
        )
        self.run = {
            "id": 40,
            "run_attempt": 2,
            "workflow_id": 7,
            "head_sha": SHA,
            "head_branch": "main",
            "event": "push",
            "path": ".github/workflows/repository-audit.yml",
            "repository": {"full_name": self.context["repository"]},
            "head_repository": {"full_name": self.context["repository"]},
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-10-15T12:00:00Z",
        }
        self.artifact = {
            "id": 71,
            "name": f"qualification-{SHA}-40-2",
            "expired": False,
            "workflow_run": {"id": 40, "head_sha": SHA},
            "digest": "",
        }
        self.environment = mock.patch.dict(
            os.environ,
            {"AUDIT_COMMIT_SHA": SHA, "GITHUB_RUN_ID": "40", "GITHUB_RUN_ATTEMPT": "2"},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        artifacts = self.q.module("coverage-artifacts")
        for platform in ("linux", "windows"):
            raw = self.root / ("raw-" + platform)
            data = CoverageData(basename=str(raw))
            arcs = [(-1, 1), (1, -1), (-1, 2), (2, 3), (3, -1), (2, 4), (4, -1)]
            data.add_arcs(
                {
                    path.relative_to(self.root).as_posix(): arcs
                    for path in (self.root / "tools").rglob("*.py")
                }
            )
            data.write()
            data.close(force=True)
            folder = self.measurements / platform
            artifacts.export(self.root, raw, folder, platform)
            measured, _ = artifacts.read_data(raw, self.root)
            artifacts.coverage_report(self.root, [measured], folder / "coverage.json")
            measured.close(force=True)
            facts = {
                "commit": SHA,
                "run": "40",
                "attempt": "2",
                "platform": platform,
                "facts": {
                    "image_version": "20261015.1",
                    "python": "3.11.15" if platform == "linux" else "3.14.8",
                    "tools": {"coverage": "7.16.2"},
                },
            }
            for name in ("environment-before.json", "environment-after.json"):
                artifacts.write_json(folder / name, facts)
            artifacts.write_json(self.fresh / f"{platform}.json", facts)
            artifacts.write_json(
                folder / "tests.json",
                {
                    "run": 6,
                    "skipped": 1,
                    "failures": 0,
                    "errors": 0,
                    "expected_failures": 0,
                    "unexpected_successes": 0,
                    "seconds": 2.0,
                },
            )
            artifacts.write_json(
                folder / "shell.json",
                {
                    "platform": platform,
                    "suites": [
                        {"command": command, "returncode": 0, "seconds": 1.0}
                        for command in artifacts.shell_suites(platform)
                    ],
                },
            )
            (folder / "shell.log").write_text("real shell output fixture\n")
        sealed = self.q.seal(
            self.root,
            self.context,
            self.measurements,
            self.fresh,
            self.packet,
            api=self.api,
        )
        self.assertTrue(sealed["sealed"], sealed)
        self.context.update(ref="refs/tags/v1.2.3", run="50", attempt="1")
        for platform in ("linux", "windows"):
            path = self.fresh / f"{platform}.json"
            current = self.q.load(path)
            current.update(run="50", attempt="1")
            artifacts.write_json(path, current)
        self.archive()

    def api(self, endpoint, *, binary=False):
        if endpoint.endswith("/git-starter-kit"):
            return {"default_branch": "main"}
        if "/commits?" in endpoint:
            return [{"sha": "f" * 40}]
        if "/contents/" in endpoint:
            path = endpoint.split("/contents/", 1)[1].split("?", 1)[0]
            return {
                "encoding": "base64",
                "content": base64.b64encode((self.root / path).read_bytes()).decode(),
            }
        if endpoint.endswith("/runs/40"):
            return self.run
        if endpoint.endswith("/workflows/repository-audit.yml"):
            return {"id": 7, "path": ".github/workflows/repository-audit.yml"}
        if "/runs?" in endpoint:
            return [{"workflow_runs": [self.run]}]
        if endpoint.endswith("/artifacts?per_page=100"):
            return [{"artifacts": [self.artifact]}]
        if endpoint.endswith("/artifacts/71"):
            return self.artifact
        if endpoint.endswith("/artifacts/71/zip"):
            self.assertTrue(binary)
            return self.archive_bytes
        self.fail(endpoint)

    def archive(self, *, rehash=False):
        if rehash:
            packet = self.q.load(self.packet / "packet.json")
            packet["files"] = {
                name: self.q.digest(self.packet / name)
                for name in sorted(self.q.PACKET_FILES)
            }
            (self.packet / "packet.json").write_text(json.dumps(packet))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as zipped:
            for path in self.packet.rglob("*"):
                if path.is_file():
                    zipped.write(path, path.relative_to(self.packet).as_posix())
        self.archive_bytes = output.getvalue()
        self.artifact["digest"] = (
            "sha256:" + hashlib.sha256(self.archive_bytes).hexdigest()
        )

    def verify(self):
        candidate = self.q.resolve(self.root, self.context, api=self.api, now=NOW)
        return self.q.verify(
            self.root,
            self.context,
            candidate,
            self.fresh,
            self.root / "verified",
            api=self.api,
            now=NOW,
        )

    def test_roundtrip_reuses_complete_original_pair_without_refresh(self):
        before = {
            name: (self.packet / name).read_bytes() for name in self.q.PACKET_FILES
        }
        result = self.verify()
        self.assertEqual(result["decision"], "reuse", result)
        self.assertEqual(result["producer"]["run"], "40")
        self.assertEqual(result["producer"]["attempt"], "2")
        self.assertEqual(result["producer"]["created_at"], "2026-10-15T12:00:00Z")
        for name, content in before.items():
            self.assertEqual((self.root / "verified" / name).read_bytes(), content)
        self.assertFalse(
            self.q.seal(
                self.root,
                self.context,
                self.measurements,
                self.fresh,
                self.root / "copy",
                api=self.api,
            )["sealed"]
        )

    def test_rejects_altered_files_and_incomplete_or_unsafe_archive(self):
        original = self.archive_bytes
        for name in (
            "linux/.coverage",
            "windows/metadata.json",
            "linux/tests.json",
            "windows/environment-before.json",
        ):
            with self.subTest(name=name):
                path = self.packet / name
                content = path.read_bytes()
                path.write_bytes(content + b"altered")
                self.archive()
                self.assertEqual(self.verify()["decision"], "full")
                path.write_bytes(content)
        path = self.packet / "windows/.coverage"
        path.unlink()
        self.archive()
        self.assertEqual(self.verify()["decision"], "full")
        self.archive_bytes = original
        self.artifact["digest"] = "sha256:" + "0" * 64
        self.assertEqual(self.verify()["decision"], "full")

    def test_actions_directory_entries_are_allowed_but_no_other_paths(self):
        output = io.BytesIO(self.archive_bytes)
        with zipfile.ZipFile(output, "a") as zipped:
            zipped.writestr("linux/", b"")
            zipped.writestr("windows/", b"")
        self.archive_bytes = output.getvalue()
        self.artifact["digest"] = (
            "sha256:" + hashlib.sha256(self.archive_bytes).hexdigest()
        )
        self.assertEqual(self.verify()["decision"], "reuse")
        output = io.BytesIO(self.archive_bytes)
        with zipfile.ZipFile(output, "a") as zipped:
            zipped.writestr("unexpected/", b"")
        self.archive_bytes = output.getvalue()
        self.artifact["digest"] = (
            "sha256:" + hashlib.sha256(self.archive_bytes).hexdigest()
        )
        self.assertEqual(self.verify()["decision"], "full")

    def test_rejects_fresh_runtime_and_image_drift(self):
        path = self.fresh / "windows.json"
        original = self.q.load(path)
        for key, value in (
            ("image_version", "next-image"),
            ("python", "3.14.9"),
            ("tools", {"coverage": "0"}),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed["facts"][key] = value
                path.write_text(json.dumps(changed))
                self.assertEqual(self.verify()["decision"], "full")

    def test_rejects_preflight_from_another_run_attempt_or_platform(self):
        path = self.fresh / "windows.json"
        original = self.q.load(path)
        for key, value in (
            ("run", "40"),
            ("attempt", "2"),
            ("commit", "b" * 40),
            ("platform", "linux"),
        ):
            with self.subTest(key=key):
                path.write_text(json.dumps({**original, key: value}))
                result = self.verify()
                self.assertEqual(result["decision"], "full")
                self.assertIn("fresh environment provenance", result["reason"])

    def test_fresh_proof_missing_before_decision_falls_back_to_both_full(self):
        (self.fresh / "windows.json").unlink()
        self.assertEqual(self.verify()["decision"], "full")

    def test_rejects_mixed_runs_attempts_failed_counts_and_incomplete_shell(self):
        for name, key, value in (
            ("windows/metadata.json", "run", "39"),
            ("windows/metadata.json", "attempt", "1"),
            ("linux/tests.json", "run", 0),
            ("linux/tests.json", "failures", 1),
            ("linux/tests.json", "errors", 1),
            ("linux/tests.json", "unexpected_successes", 1),
            ("linux/shell.json", "suites", []),
            ("windows/environment-after.json", "facts", {"image_version": "changed"}),
        ):
            with self.subTest(name=name, key=key):
                path = self.packet / name
                content = path.read_bytes()
                changed = json.loads(content)
                changed[key] = value
                path.write_text(json.dumps(changed))
                self.archive(rehash=True)
                self.assertEqual(self.verify()["decision"], "full")
                path.write_bytes(content)

    def test_changed_locks_policy_registry_workflow_or_validator_is_full(self):
        for relative in self.q.INPUTS:
            with self.subTest(path=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                self.assertEqual(self.verify()["decision"], "full")
                path.write_bytes(original)

    def test_no_admissible_packet_when_heavy_and_fresh_images_differ(self):
        path = self.fresh / "linux.json"
        changed = self.q.load(path)
        changed["facts"]["image_version"] = "different"
        path.write_text(json.dumps(changed))
        self.context.update(ref="refs/heads/main", run="40", attempt="2")
        result = self.q.seal(
            self.root,
            self.context,
            self.measurements,
            self.fresh,
            self.root / "unsealed",
            api=self.api,
        )
        self.assertFalse(result["sealed"])
        self.assertFalse((self.root / "unsealed").exists())

    def test_malformed_api_objects_always_produce_common_full(self):
        for suffix in (
            "/git-starter-kit",
            "/workflows/repository-audit.yml",
            "/runs/40",
            "/artifacts/71",
        ):
            for invalid in ([], None):
                with self.subTest(endpoint=suffix, value=invalid):
                    candidate = self.q.resolve(
                        self.root, self.context, api=self.api, now=NOW
                    )

                    def malformed(endpoint, *, binary=False):
                        if endpoint.endswith(suffix):
                            return invalid
                        return self.api(endpoint, binary=binary)

                    result = self.q.verify(
                        self.root,
                        self.context,
                        candidate,
                        self.fresh,
                        self.root / "verified",
                        api=malformed,
                        now=NOW,
                    )
                    self.assertEqual(result["decision"], "full")

    def test_altered_linux_raw_coverage_cannot_hide_behind_green_combined(self):
        artifacts = self.q.module("coverage-artifacts")
        path = self.packet / "linux/.coverage"
        data = CoverageData(basename=str(path))
        data.erase()
        data.add_arcs(
            {
                p.relative_to(self.root).as_posix(): [
                    (-1, 1),
                    (1, -1),
                    (-1, 2),
                    (2, 3),
                    (3, -1),
                ]
                for p in (self.root / "tools").rglob("*.py")
            }
        )
        data.write()
        data.close(force=True)
        metadata = self.q.load(self.packet / "linux/metadata.json")
        metadata["digest"] = artifacts.digest(path)
        (self.packet / "linux/metadata.json").write_text(json.dumps(metadata))
        self.archive(rehash=True)
        result = self.verify()
        self.assertEqual(result["decision"], "full")
        self.assertIn("Coverage FAIL", result["reason"])

    def test_trust_changes_and_invalid_commits_are_full_without_writing_proof(self):
        for response in ([], [None], [{"sha": "short"}], [{"sha": "f" * 40}]):

            def changed_trust(endpoint, *, binary=False):
                if "/commits?" in endpoint:
                    return response
                if "/contents/" in endpoint:
                    return {
                        "encoding": "base64",
                        "content": base64.b64encode(b"other trusted source").decode(),
                    }
                return self.api(endpoint, binary=binary)

            with self.subTest(response=response):
                candidate = self.q.resolve(
                    self.root, self.context, api=self.api, now=NOW
                )
                result = self.q.verify(
                    self.root,
                    self.context,
                    candidate,
                    self.fresh,
                    self.root / "verified",
                    api=changed_trust,
                    now=NOW,
                )
                self.assertEqual(result["decision"], "full")
                self.assertFalse((self.root / "verified").exists())

    def test_seal_rejects_wrong_attempt_and_api_failure_without_uploadable_packet(self):
        self.context.update(ref="refs/heads/main", run="40", attempt="3")
        result = self.q.seal(
            self.root,
            self.context,
            self.measurements,
            self.fresh,
            self.root / "bad",
            api=self.api,
        )
        self.assertFalse(result["sealed"])
        with mock.patch.object(self.q, "api_request", side_effect=OSError("offline")):
            result = self.q.seal(
                self.root,
                self.context,
                self.measurements,
                self.fresh,
                self.root / "bad",
            )
        self.assertFalse(result["sealed"])
        self.assertFalse((self.root / "bad").exists())

    def test_missing_image_wrong_heavy_identity_and_invalid_sqlite_are_full(self):
        for change in ({"run": "39"}, {"facts": {"image_version": ""}}):
            originals = {}
            for name in ("environment-before.json", "environment-after.json"):
                path = self.packet / "linux" / name
                originals[path] = path.read_bytes()
                value = json.loads(originals[path])
                value.update(change)
                path.write_text(json.dumps(value))
            fresh = self.fresh / "linux.json"
            fresh_original = fresh.read_bytes()
            if "facts" in change:
                fresh.write_text(json.dumps({**json.loads(fresh_original), **change}))
            self.archive(rehash=True)
            self.assertEqual(self.verify()["decision"], "full")
            for path, content in originals.items():
                path.write_bytes(content)
            fresh.write_bytes(fresh_original)
        path = self.packet / "linux/.coverage"
        path.write_bytes(b"invalid SQLite data")
        metadata = self.packet / "linux/metadata.json"
        value = json.loads(metadata.read_text())
        value["digest"] = self.q.digest(path)
        metadata.write_text(json.dumps(value))
        self.archive(rehash=True)
        self.assertEqual(self.verify()["decision"], "full")


if __name__ == "__main__":
    unittest.main()
