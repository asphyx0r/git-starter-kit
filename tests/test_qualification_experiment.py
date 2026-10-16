"""Check the experimental harness without running its real heavy suites."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import test_qualification as packets


SCRIPT = Path(__file__).with_name("qualification_experiment.py")


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "experimental harness is missing")
        spec = importlib.util.spec_from_file_location("experiment", SCRIPT)
        self.experiment = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.experiment)
        self.fixture = packets.QualificationPacketTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.q = self.fixture.q

    def api(self):
        actual = dict(self.fixture.run, event="workflow_dispatch", head_branch="bench")
        return self.experiment.ExperimentAPI(
            self.fixture.root, actual, self.fixture.context["sha"], self.q
        )

    def test_real_packet_roundtrip_keeps_bytes_age_and_actual_event(self):
        api = self.api()
        api.bind(self.fixture.packet)
        candidate = self.q.resolve(
            self.fixture.root, self.fixture.context, api=api, now=packets.NOW
        )
        result = self.q.verify(
            self.fixture.root,
            self.fixture.context,
            candidate,
            self.fixture.fresh,
            self.fixture.root / "experiment-verified",
            api=api,
            now=packets.NOW,
        )
        self.assertEqual(result["decision"], "reuse", result)
        self.assertEqual(result["producer"]["created_at"], "2026-10-15T12:00:00Z")
        self.assertEqual(api.actual["event"], "workflow_dispatch")
        for name in self.q.PACKET_FILES:
            self.assertEqual(
                (self.fixture.root / "experiment-verified" / name).read_bytes(),
                (self.fixture.packet / name).read_bytes(),
            )

    def test_unknown_api_route_never_falls_through(self):
        with self.assertRaisesRegex(ValueError, "unrecognized experimental API"):
            self.api()("repos/asphyx0r/git-starter-kit/releases/latest")

    def test_windows_drift_selects_full_with_original_pair_untouched(self):
        api = self.api()
        api.bind(self.fixture.packet)
        before = (self.fixture.packet / "windows/environment-before.json").read_bytes()
        path = self.fixture.fresh / "windows.json"
        facts = json.loads(path.read_bytes())
        facts["facts"]["image_version"] = "experimental-drift"
        path.write_text(json.dumps(facts))
        candidate = self.q.resolve(
            self.fixture.root, self.fixture.context, api=api, now=packets.NOW
        )
        result = self.q.verify(
            self.fixture.root,
            self.fixture.context,
            candidate,
            self.fixture.fresh,
            self.fixture.root / "refused",
            api=api,
            now=packets.NOW,
        )
        self.assertEqual(result["decision"], "full")
        self.assertFalse((self.fixture.root / "refused").exists())
        self.assertEqual(
            (self.fixture.packet / "windows/environment-before.json").read_bytes(),
            before,
        )

    def test_postdecision_file_loss_is_refused(self):
        api = self.api()
        api.bind(self.fixture.packet)
        selected = self.q.resolve(
            self.fixture.root, self.fixture.context, api=api, now=packets.NOW
        )
        retained = self.fixture.root / "retained"
        result = self.q.verify(
            self.fixture.root,
            self.fixture.context,
            selected,
            self.fixture.fresh,
            retained,
            api=api,
            now=packets.NOW,
        )
        self.assertEqual(result["decision"], "reuse", result)
        (retained / "linux/.coverage").unlink()
        with self.assertRaises((ValueError, OSError)):
            self.experiment.require_packet(
                self.q,
                self.fixture.root,
                retained,
                self.fixture.fresh,
                self.fixture.context,
            )

    def test_retained_packet_recheck_keeps_all_input_bytes(self):
        before = {
            p.relative_to(self.fixture.packet).as_posix(): p.read_bytes()
            for p in self.fixture.packet.rglob("*")
            if p.is_file()
        }
        self.experiment.require_packet(
            self.q,
            self.fixture.root,
            self.fixture.packet,
            self.fixture.fresh,
            self.fixture.context,
        )
        after = {
            p.relative_to(self.fixture.packet).as_posix(): p.read_bytes()
            for p in self.fixture.packet.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_release_consumer_reuses_original_age(self):
        api = self.api()
        api.bind(self.fixture.packet)
        context = dict(self.fixture.context, event="release", action="published")
        selected = self.q.resolve(self.fixture.root, context, api=api, now=packets.NOW)
        result = self.q.verify(
            self.fixture.root,
            context,
            selected,
            self.fixture.fresh,
            self.fixture.root / "release-verified",
            api=api,
            now=packets.NOW,
        )
        self.assertEqual(result["decision"], "reuse", result)
        self.assertEqual(result["producer"]["created_at"], "2026-10-15T12:00:00Z")

    def test_summary_uses_paired_critical_paths_and_runner_sums(self):
        rows = [
            {
                "platform": platform,
                "sample": sample,
                "scenarios": {
                    name: {"seconds": seconds}
                    for name, seconds in (
                        ("full", base),
                        ("reuse", base / 10),
                        ("fallback", base + 1),
                    )
                },
            }
            for platform, base in (("linux", 10), ("windows", 20))
            for sample in (1, 2, 3)
        ]
        summary = self.experiment.summarize(rows, {"linux": 30, "windows": 40})
        self.assertEqual(summary["scenarios"]["full"]["critical_path"]["median"], 20)
        self.assertEqual(summary["scenarios"]["full"]["runner_sum"]["median"], 30)
        self.assertEqual(summary["sequences"]["full"]["critical_path"], 80)
        self.assertEqual(summary["sequences"]["reuse"]["critical_path"], 44)

    def test_manifest_refuses_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "sample.json").write_text('{"sample": 1}')
            self.experiment.write_manifest(folder)
            (folder / "sample.json").write_text('{"sample": 2}')
            with self.assertRaisesRegex(ValueError, "manifest"):
                self.experiment.check_manifest(folder)

    def test_aggregate_refuses_missing_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with self.assertRaisesRegex(ValueError, "exactly six"):
                self.experiment.aggregate(
                    SimpleNamespace(input=folder, output=folder / "output")
                )

    def test_aggregate_refuses_mixed_runs_and_altered_sample(self):
        for failure in ("mixed", "changed"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as temporary,
            ):
                base = Path(temporary)
                for platform in ("linux", "windows"):
                    for sample in (1, 2, 3):
                        folder = base / f"sample-{platform}-{sample}"
                        folder.mkdir()
                        row = {
                            "schema": 1,
                            "experimental": True,
                            "platform": platform,
                            "sample": sample,
                            "actual_context": {"run": "50"},
                            "source_packet": {},
                            "source_files": {},
                            "postdecision_loss_refused": True,
                            "scenarios": {
                                name: {"seconds": 1, "decision": {"decision": decision}}
                                for name, decision in (
                                    ("full", "full"),
                                    ("reuse", "reuse"),
                                    ("fallback", "full"),
                                )
                            },
                        }
                        if failure == "mixed" and platform == "windows":
                            row["actual_context"]["run"] = "51"
                        self.experiment.write(folder / "sample.json", row)
                        self.experiment.write_manifest(folder)
                if failure == "changed":
                    (base / "sample-linux-1/sample.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "mixed experimental|manifest"):
                    self.experiment.aggregate(
                        SimpleNamespace(input=base, output=base / "output")
                    )

    def test_real_heavy_command_failure_stops_before_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = self.q.module("coverage-artifacts")
            with (
                mock.patch.object(artifacts, "environment", return_value={}),
                mock.patch.object(self.q, "module", return_value=artifacts),
                mock.patch.object(
                    self.experiment.subprocess,
                    "run",
                    side_effect=self.experiment.subprocess.CalledProcessError(
                        23, ["python"]
                    ),
                ),
            ):
                with self.assertRaises(self.experiment.subprocess.CalledProcessError):
                    self.experiment.measured(self.q, Path(temporary) / "full", "linux")
                self.assertFalse(
                    (Path(temporary) / "full/measurements/shell.json").exists()
                )

    def test_run_and_aggregate_preserve_real_pair_and_recompute_floors(self):
        context = dict(
            self.fixture.context,
            event="workflow_dispatch",
            ref="refs/heads/bench",
            run="40",
            attempt="2",
        )
        actual = dict(self.fixture.run, event="workflow_dispatch", head_branch="bench")
        for platform in ("linux", "windows"):
            fresh = self.fixture.fresh / f"{platform}.json"
            value = self.q.load(fresh)
            value.update(run="40", attempt="2")
            self.experiment.write(fresh, value)
        artifacts = self.q.module("coverage-artifacts")
        native_module = self.q.module

        def measured(q, folder, platform):
            folder.mkdir()
            shutil.copytree(
                self.fixture.measurements / platform, folder / "measurements"
            )
            return {"seconds": 1.0, "tests": q.load(folder / "measurements/tests.json")}

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with (
                mock.patch.object(self.experiment, "ROOT", self.fixture.root),
                mock.patch.object(
                    self.experiment, "qualification", return_value=self.q
                ),
                mock.patch.object(
                    self.q, "context_from_environment", return_value=context
                ),
                mock.patch.object(
                    self.q,
                    "module",
                    side_effect=lambda name: (
                        artifacts
                        if name == "coverage-artifacts"
                        else native_module(name)
                    ),
                ),
                mock.patch.object(
                    artifacts,
                    "environment",
                    return_value=self.q.load(self.fixture.fresh / "linux.json"),
                ),
                mock.patch.object(
                    self.experiment.subprocess,
                    "run",
                    return_value=SimpleNamespace(stdout=json.dumps(actual).encode()),
                ),
                mock.patch.object(self.experiment, "measured", side_effect=measured),
            ):
                self.experiment.run_sample(
                    SimpleNamespace(
                        platform="linux",
                        sample=1,
                        measurements=self.fixture.measurements,
                        fresh=self.fixture.fresh,
                        output=base,
                    )
                )
                original = base / "sample-linux-1"
                self.experiment.check_manifest(original)
                row = self.experiment.load(original / "sample.json")
                self.assertEqual(row["actual_context"]["event"], "workflow_dispatch")
                self.assertEqual(
                    row["scenarios"]["full"]["decision"]["decision"], "full"
                )
                self.assertEqual(
                    row["scenarios"]["reuse"]["release_decision"]["decision"], "reuse"
                )
                for platform in ("linux", "windows"):
                    for sample in (1, 2, 3):
                        if (platform, sample) == ("linux", 1):
                            continue
                        target = base / f"sample-{platform}-{sample}"
                        shutil.copytree(original, target)
                        value = self.experiment.load(target / "sample.json")
                        value.update(platform=platform, sample=sample)
                        for scenario in ("full", "fallback"):
                            shutil.rmtree(target / scenario / "measurements")
                            shutil.copytree(
                                self.fixture.measurements / platform,
                                target / scenario / "measurements",
                            )
                        self.experiment.write(target / "sample.json", value)
                        self.experiment.write_manifest(target)
                with mock.patch.dict(
                    os.environ,
                    AUDIT_COMMIT_SHA=packets.SHA,
                    GITHUB_RUN_ID="40",
                    GITHUB_RUN_ATTEMPT="2",
                ):
                    self.experiment.aggregate(
                        SimpleNamespace(input=base, output=base / "results")
                    )
                report = self.experiment.load(base / "results/result.json")
                self.assertEqual(len(report["floors"]), 6)
                self.assertEqual(
                    report["source_packet"]["producer"]["created_at"],
                    "2026-10-15T12:00:00Z",
                )
                self.experiment.check_manifest(base / "results")


if __name__ == "__main__":
    unittest.main()
