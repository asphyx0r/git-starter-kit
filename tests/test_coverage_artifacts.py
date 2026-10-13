"""Verify that combined coverage uses two authentic, matching OS measurements."""

from __future__ import annotations

import importlib.util
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
from unittest import mock

from coverage import CoverageData


SCRIPT = Path(__file__).resolve().parents[1] / "tools/quality/coverage-artifacts.py"


class CoverageArtifactsTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("coverage_artifacts", SCRIPT)
        self.artifacts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.artifacts)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        quality = self.root / "tools/quality"
        quality.mkdir(parents=True)
        (quality / "versions.json").write_text(
            json.dumps({"python": {"coverage": "7.16.2"}}), encoding="utf-8"
        )
        (quality / "pyproject.toml").write_text(
            "[tool.coverage.run]\nbranch = true\nrelative_files = true\n"
            'source = ["tools"]\n',
            encoding="utf-8",
        )
        (self.root / "tools/example.py").write_text(
            "def classify(value):\n    if value:\n        return 1\n    return 0\n",
            encoding="utf-8",
        )
        self.environment = mock.patch.dict(
            os.environ,
            {
                "AUDIT_COMMIT_SHA": "a" * 40,
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.output = self.root / "artifacts"
        for platform, arcs in (
            ("linux", [(-1, 1), (1, -1), (-1, 2), (2, 3), (3, -1)]),
            ("windows", [(-1, 1), (1, -1), (-1, 2), (2, 4), (4, -1)]),
        ):
            data_path = self.root / f".coverage.{platform}"
            data = CoverageData(basename=str(data_path))
            path = "tools/example.py" if platform == "linux" else r"tools\example.py"
            data.add_arcs({path: arcs})
            data.write()
            self.artifacts.export(
                self.root, data_path, self.output / platform, platform
            )

    def test_combination_unions_windows_and_linux_branches(self):
        report = self.artifacts.combine(self.root, self.output)
        self.assertEqual(report["totals"]["covered_branches"], 2)
        self.assertEqual(report["totals"]["num_branches"], 2)
        self.assertEqual(
            {name.replace("\\", "/") for name in report["files"]},
            {"tools/example.py"},
        )

    def test_combination_closes_in_memory_sqlite_connections(self):
        gc.collect()
        with warnings.catch_warnings(record=True) as notices:
            warnings.simplefilter("always", ResourceWarning)
            self.artifacts.combine(self.root, self.output)
            gc.collect()
        self.assertFalse(
            [notice for notice in notices if notice.category is ResourceWarning]
        )

    def test_missing_platform_measurement_is_rejected(self):
        (self.output / "windows/metadata.json").unlink()
        with self.assertRaises((OSError, ValueError)):
            self.artifacts.combine(self.root, self.output)

    def test_stale_wrong_sha_version_and_policy_are_rejected(self):
        path = self.output / "windows/metadata.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for key, value in (
            ("commit", "b" * 40),
            ("run", "122"),
            ("attempt", "2"),
            ("coverage", "7.0.0"),
            ("policy", "0" * 64),
            ("platform", "linux"),
        ):
            with self.subTest(key=key):
                path.write_text(json.dumps({**original, key: value}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "metadata"):
                    self.artifacts.combine(self.root, self.output)
        path.write_text(json.dumps(original), encoding="utf-8")

    def test_changed_data_or_source_is_rejected(self):
        path = self.output / "windows/.coverage"
        original = path.read_bytes()
        path.write_bytes(original + b"tampered")
        with self.assertRaisesRegex(ValueError, "digest"):
            self.artifacts.combine(self.root, self.output)
        path.write_bytes(original)
        (self.root / "tools/example.py").write_text("pass\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source"):
            self.artifacts.combine(self.root, self.output)

    def test_empty_line_only_and_unsafe_measurements_are_rejected(self):
        for files, branch in (
            ({}, True),
            ({"tools/example.py": [1]}, False),
            ({"../outside.py": [(-1, 1)]}, True),
        ):
            with self.subTest(files=files):
                path = self.root / "bad.coverage"
                data = CoverageData(basename=str(path))
                data.erase()
                if branch:
                    data.add_arcs(files)
                else:
                    data.add_lines(files)
                data.write()
                with self.assertRaises(ValueError):
                    self.artifacts.export(self.root, path, self.output / "bad", "linux")

    def test_invalid_run_identity_is_rejected(self):
        with mock.patch.dict(os.environ, {"AUDIT_COMMIT_SHA": "main"}):
            with self.assertRaises(ValueError):
                self.artifacts.combine(self.root, self.output)

    def test_cli_reports_invalid_metadata_and_help(self):
        (self.output / "windows/metadata.json").write_text("[]\n", encoding="utf-8")
        for arguments, status, expected in (
            (["combine", str(self.output)], 1, "invalid coverage metadata"),
            (["--help"], 0, "export"),
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), *arguments],
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn(expected, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_cli_exports_and_combines_valid_measurements(self):
        destination = self.output / "cli-linux"
        for arguments in (
            [
                "export",
                str(self.root / ".coverage.linux"),
                str(destination),
                "--platform",
                "linux",
            ],
            ["combine", str(self.output)],
        ):
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), *arguments],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads((destination / "metadata.json").read_text(encoding="utf-8"))[
                "platform"
            ],
            "linux",
        )
        report = json.loads((self.output / "combined.json").read_text(encoding="utf-8"))
        self.assertEqual(report["totals"]["covered_branches"], 2)

    def test_linked_coverage_data_is_rejected_before_reading(self):
        with mock.patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(ValueError, "linked"):
                self.artifacts.read_data(self.output / "windows/.coverage", self.root)
