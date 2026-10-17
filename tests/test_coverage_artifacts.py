"""Verify that combined coverage uses two authentic, matching OS measurements."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import gc
import io
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
from coverage.files import relative_directory


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
        linux = json.loads((self.output / "linux-rechecked.json").read_text())
        self.assertEqual(linux["totals"]["covered_branches"], 1)
        paths = [Path(name.replace("\\", "/")) for name in report["files"]]
        self.assertEqual(
            {
                (
                    path.resolve().relative_to(self.root.resolve())
                    if path.is_absolute()
                    else path
                ).as_posix()
                for path in paths
            },
            {"tools/example.py"},
        )

    def test_combination_canonicalizes_absolute_measurement_paths(self):
        report = self.artifacts.combine(self.root / "tools" / "..", self.output)
        self.assertEqual(report["totals"]["covered_branches"], 2)

    def test_combination_closes_in_memory_sqlite_connections(self):
        gc.collect()
        with warnings.catch_warnings(record=True) as notices:
            warnings.simplefilter("always", ResourceWarning)
            self.artifacts.combine(self.root, self.output)
            gc.collect()
        self.assertFalse(
            [notice for notice in notices if notice.category is ResourceWarning]
        )

    def test_combination_preserves_callers_measurement_paths(self):
        before = (Path.cwd(), relative_directory())
        self.artifacts.combine(self.root, self.output)
        self.assertEqual((Path.cwd(), relative_directory()), before)

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

    def test_runtime_version_mismatch_is_rejected(self):
        path = self.root / "tools/quality/versions.json"
        path.write_text(json.dumps({"python": {"coverage": "0.0.0"}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "runtime"):
            self.artifacts.combine(self.root, self.output)

    def test_original_pair_can_be_rechecked_without_relabelling_metadata(self):
        expected = self.artifacts.identity(self.root)
        before = (self.output / "linux/metadata.json").read_bytes()
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "999"}):
            with self.assertRaises(ValueError):
                self.artifacts.combine(self.root, self.output)
            report = self.artifacts.combine(
                self.root, self.output, expected_identity=expected
            )
        self.assertEqual(report["totals"]["covered_branches"], 2)
        self.assertEqual((self.output / "linux/metadata.json").read_bytes(), before)

    def test_test_runner_records_real_success_failure_and_skips(self):
        self.assertTrue(hasattr(self.artifacts, "run_tests"))
        suite = unittest.TestSuite(
            [
                unittest.FunctionTestCase(lambda: None),
                unittest.FunctionTestCase(lambda: self.skipTest("fixture skip")),
                unittest.FunctionTestCase(lambda: self.fail("fixture failure")),
            ]
        )
        output = self.root / "tests.json"
        with redirect_stderr(io.StringIO()):
            status = self.artifacts.run_tests(output, suite=suite)
        self.assertEqual(status, 1)
        report = json.loads(output.read_text())
        self.assertEqual(
            (report["run"], report["skipped"], report["failures"]), (3, 1, 1)
        )
        self.assertGreaterEqual(report["seconds"], 0)

    def test_coverage_script_runner_imports_root_namespace_without_pythonpath(self):
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_namespace.py").write_text(
            "import unittest\nfrom tools.example import classify\n"
            "class NamespaceTests(unittest.TestCase):\n"
            "    def test_root_import(self):\n"
            "        self.assertEqual(classify(True), 1)\n",
            encoding="utf-8",
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key != "PYTHONPATH"
            and not key.startswith("GITHUB_")
            and key not in {"AUDIT_COMMIT_SHA", "ImageVersion"}
        }
        output = self.root / "namespace-results.json"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "coverage",
                "run",
                "--rcfile",
                str(self.root / "tools/quality/pyproject.toml"),
                "--data-file",
                str(self.root / "namespace.coverage"),
                str(SCRIPT),
                "tests",
                "--output",
                str(output),
            ],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            (report["run"], report["failures"], report["errors"]), (1, 0, 0)
        )

    def test_test_runner_restores_import_path_after_success_and_interruption(self):
        original = sys.path[:]
        original_list = sys.path
        for interruption in (None, KeyboardInterrupt()):
            with self.subTest(interruption=interruption):

                def exercise_path():
                    self.assertIn(str(Path.cwd()), sys.path)
                    sys.path.append("runner-path-mutation")
                    if interruption is not None:
                        raise interruption

                suite = unittest.TestSuite([unittest.FunctionTestCase(exercise_path)])
                try:
                    with redirect_stderr(io.StringIO()):
                        if interruption is None:
                            self.assertEqual(
                                self.artifacts.run_tests(
                                    self.root / "run.json", suite=suite
                                ),
                                0,
                            )
                        else:
                            with self.assertRaises(KeyboardInterrupt) as raised:
                                self.artifacts.run_tests(
                                    self.root / "run.json", suite=suite
                                )
                            self.assertIs(raised.exception, interruption)
                    self.assertIs(sys.path, original_list)
                    self.assertEqual(sys.path, original)
                finally:
                    sys.path[:] = original

    def test_test_runner_restores_import_path_after_discovery_error(self):
        original = sys.path[:]
        failure = RuntimeError("discovery failed")

        def fail_discovery(*args, **kwargs):
            sys.path.append("discovery-path-mutation")
            raise failure

        try:
            with mock.patch.object(
                unittest.defaultTestLoader, "discover", side_effect=fail_discovery
            ):
                with self.assertRaises(RuntimeError) as raised:
                    self.artifacts.run_tests(self.root / "run.json")
            self.assertIs(raised.exception, failure)
            self.assertEqual(sys.path, original)
            self.assertFalse((self.root / "run.json").exists())
        finally:
            sys.path[:] = original

    def test_shell_report_stops_on_failure_and_keeps_actual_output(self):
        output = self.root / "shell"
        commands = [
            [sys.executable, "-c", "print('first suite')"],
            [sys.executable, "-c", "raise SystemExit(7)"],
            [sys.executable, "-c", "print('must not run')"],
        ]
        with mock.patch.object(self.artifacts, "shell_suites", return_value=commands):
            self.assertEqual(self.artifacts.run_shell(output, "linux"), 7)
        report = json.loads((output / "shell.json").read_text())
        self.assertEqual([suite["returncode"] for suite in report["suites"]], [0, 7])
        self.assertIn("first suite", (output / "shell.log").read_text())
        self.assertNotIn("must not run", (output / "shell.log").read_text())
        with mock.patch.object(
            self.artifacts, "shell_suites", return_value=commands[:1]
        ):
            self.assertEqual(
                self.artifacts.main(
                    ["shell", "--platform", "linux", "--output", str(output)]
                ),
                0,
            )

    def test_environment_records_selected_versions_and_hosted_image(self):
        from types import SimpleNamespace

        quality = self.root / "tools/quality"
        (quality / "versions.json").write_text(
            json.dumps(
                {
                    "python": {"coverage": "7.16.2"},
                    "node": {"example": "1.2.3"},
                    "external": {"PSScriptAnalyzer": {}, "shellcheck": {}, "shfmt": {}},
                }
            )
        )
        package = quality / "node_modules/example/package.json"
        package.parent.mkdir(parents=True)
        package.write_text('{"version":"1.2.3"}')
        versions = SimpleNamespace(
            command_version=lambda command: SimpleNamespace(
                version="9.8.7", diagnostic="selected"
            ),
            external_commands=lambda registry: {
                name: [name, "--version"] for name in registry
            },
        )
        spec = SimpleNamespace(
            name="fixture_versions",
            loader=SimpleNamespace(exec_module=lambda module: None),
        )
        with (
            mock.patch.object(
                self.artifacts.importlib.util,
                "spec_from_file_location",
                return_value=spec,
            ),
            mock.patch.object(
                self.artifacts.importlib.util, "module_from_spec", return_value=versions
            ),
            mock.patch.dict(
                os.environ, {"ImageVersion": "20261016.1", "ImageOS": "win25"}
            ),
        ):
            result = self.artifacts.environment(self.root, "windows")
            self.assertEqual(result["facts"]["image_version"], "20261016.1")
            self.assertEqual(result["facts"]["tools"]["git"], "9.8.7")
            self.assertEqual(result["facts"]["tools"]["windows-powershell"], "9.8.7")
            self.assertEqual(result["facts"]["tools"]["npm:example"], "1.2.3")
            self.assertEqual(result["facts"]["tools"]["python:coverage"], "7.16.2")
            self.assertEqual(result["run"], "123")
            versions.command_version = lambda command: SimpleNamespace(
                version=None, diagnostic="not selected"
            )
            with self.assertRaisesRegex(ValueError, "cannot measure"):
                self.artifacts.environment(self.root, "windows")

    def test_shell_runner_and_probe_select_git_bash_on_windows(self):
        git = self.root / "Git/cmd/git.exe"
        bash = self.root / "Git/bin/bash.exe"
        bash.parent.mkdir(parents=True)
        bash.touch()
        with (
            mock.patch.object(self.artifacts.sys, "platform", "win32"),
            mock.patch.object(self.artifacts.shutil, "which", return_value=str(git)),
        ):
            self.assertEqual(self.artifacts.bash_executable(), str(bash))
            bash.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "Git Bash"):
                self.artifacts.bash_executable()
        with mock.patch.object(self.artifacts.sys, "platform", "linux"):
            self.assertEqual(self.artifacts.bash_executable(), "bash")

    def test_shell_children_cannot_reenter_ci_coverage_orchestration(self):
        command = [
            sys.executable,
            "-B",
            "-c",
            "import os; assert 'AUDIT_COVERAGE_DIR' not in os.environ; assert os.environ['QUALIFICATION_PARENT'] == 'retained'",
        ]
        with (
            mock.patch.object(self.artifacts, "shell_suites", return_value=[command]),
            mock.patch.dict(
                os.environ,
                {
                    "AUDIT_COVERAGE_DIR": str(self.output),
                    "QUALIFICATION_PARENT": "retained",
                },
            ),
        ):
            self.assertEqual(self.artifacts.run_shell(self.output, "linux"), 0)

    def test_measurement_commands_retain_discovery_results_and_environment(self):
        output = self.root / "measured.json"
        suite = unittest.TestSuite([unittest.FunctionTestCase(lambda: None)])
        with (
            mock.patch.object(
                unittest.defaultTestLoader, "discover", return_value=suite
            ),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(self.artifacts.main(["tests", "--output", str(output)]), 0)
        self.assertEqual(json.loads(output.read_text())["run"], 1)
        with mock.patch.object(
            self.artifacts,
            "environment",
            return_value={"facts": {"image_version": "exact"}},
        ):
            self.assertEqual(
                self.artifacts.main(
                    ["environment", "--platform", "linux", "--output", str(output)]
                ),
                0,
            )
        self.assertEqual(
            json.loads(output.read_text())["facts"]["image_version"], "exact"
        )

    def test_export_rejects_bad_platform_and_existing_destination(self):
        before = (self.output / "linux/metadata.json").read_bytes()
        for platform, error in (("unknown", ValueError), ("linux", FileExistsError)):
            with self.subTest(platform=platform), self.assertRaises(error):
                self.artifacts.export(
                    self.root,
                    self.root / ".coverage.linux",
                    self.output / "linux",
                    platform,
                )
        self.assertEqual((self.output / "linux/metadata.json").read_bytes(), before)

    def test_non_mapping_metadata_is_rejected(self):
        (self.output / "windows/metadata.json").write_text("[]\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metadata"):
            self.artifacts.combine(self.root, self.output)

    def test_main_validates_and_writes_both_operations(self):
        destination = self.output / "direct-linux"
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
            with mock.patch.object(Path, "cwd", return_value=self.root):
                self.assertEqual(self.artifacts.main(arguments), 0)
        self.assertTrue((destination / "metadata.json").is_file())
        report = json.loads((self.output / "combined.json").read_text(encoding="utf-8"))
        self.assertEqual(report["totals"]["covered_branches"], 2)

    def test_main_reports_failed_validation_without_success_output(self):
        with (
            mock.patch.object(Path, "cwd", return_value=self.root),
            mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "0"}),
            redirect_stderr(io.StringIO()) as stderr,
            redirect_stdout(io.StringIO()) as stdout,
        ):
            self.assertEqual(self.artifacts.main(["combine", str(self.output)]), 1)
        self.assertIn("require a full SHA, run and attempt", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        self.assertFalse((self.output / "combined.json").exists())

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
