"""Exercise the effective project configuration and its read-only CLI."""

import copy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "project_config.py"
PROJECT = {
    "schemaVersion": 1,
    "repositoryRole": "project",
    "releaseKind": "repository",
    "automations": {
        "agentRulesSync": False,
        "guardedMerge": False,
        "releasePreflight": False,
    },
    "checks": [],
}
CHECK = {
    "name": "unit",
    "argv": ["python", "-m", "unittest"],
    "workingDirectory": ".",
    "platforms": ["linux", "windows"],
}


class ProjectConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            MODULE_PATH.is_file(), "project configuration reader is missing"
        )
        self.module = importlib.import_module("tools.project_config")
        self.temporary = tempfile.TemporaryDirectory(prefix="starter-project-config-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.configuration_path = self.root / ".starter-kit-project.json"

    def write_configuration(self, value):
        self.configuration_path.write_text(json.dumps(value), encoding="utf-8")

    def test_in_memory_metadata_parser_has_no_writes_or_filesystem_containment(self):
        value = copy.deepcopy(PROJECT)
        value["checks"] = [dict(CHECK, workingDirectory="application")]
        with (
            mock.patch(
                "tempfile.TemporaryDirectory", side_effect=AssertionError("no temp")
            ),
            mock.patch.object(
                Path, "write_bytes", side_effect=AssertionError("no writes")
            ),
            mock.patch.object(
                Path, "resolve", side_effect=AssertionError("no filesystem")
            ),
        ):
            configuration = self.module.parse_configuration(json.dumps(value).encode())
        self.assertEqual(configuration.checks[0].working_directory, "application")
        self.assertEqual(self.module.parse_configuration(None).mode, "legacy")

    def test_in_memory_parser_preserves_strict_absent_invalid_and_local_containment(
        self,
    ):
        for content in (
            b"",
            b"{}",
            b"null",
            b'{"schemaVersion":1,"schemaVersion":1}',
            b"\xef\xbb\xbf{}",
            b"\xff",
        ):
            with (
                self.subTest(content=content),
                self.assertRaises(self.module.ConfigurationError),
            ):
                self.module.parse_configuration(content)
        value = copy.deepcopy(PROJECT)
        value["checks"] = [dict(CHECK, workingDirectory="../outside")]
        with self.assertRaises(self.module.ConfigurationError):
            self.module.parse_configuration(json.dumps(value).encode())

    def run_cli(self, *arguments):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(MODULE_PATH),
                "--repository-root",
                str(self.root),
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def test_missing_configuration_preserves_legacy_without_creating_file(self):
        configuration = self.module.load_configuration(self.root)
        self.assertEqual(configuration.mode, "legacy")
        self.assertEqual(configuration.repository_role, "project")
        self.assertEqual(configuration.release_kind, "deployment")
        self.assertEqual(
            configuration.automations,
            {
                "agentRulesSync": True,
                "guardedMerge": True,
                "releasePreflight": True,
            },
        )
        self.assertEqual(configuration.checks, ())
        self.assertFalse(self.configuration_path.exists())

    def test_new_project_defaults_are_explicit_and_round_trip(self):
        defaults = self.module.default_project_configuration()
        self.assertEqual(defaults, PROJECT)
        defaults["automations"]["guardedMerge"] = True
        self.assertEqual(self.module.default_project_configuration(), PROJECT)
        self.write_configuration(PROJECT)
        configuration = self.module.load_configuration(self.root)
        self.assertEqual(configuration.mode, "configured")
        self.assertEqual(configuration.repository_role, "project")
        self.assertEqual(configuration.release_kind, "repository")
        self.assertEqual(configuration.as_dict(), {"mode": "configured", **PROJECT})

    def test_invalid_existing_content_never_falls_back_to_legacy(self):
        for text in ("{", "null", "[]", '{"schemaVersion": 1}', "\ufeff{}"):
            with self.subTest(text=text):
                self.configuration_path.write_text(text, encoding="utf-8")
                with self.assertRaises(self.module.ConfigurationError):
                    self.module.load_configuration(self.root)

    def test_duplicate_json_fields_are_rejected_at_every_level(self):
        text = json.dumps({**PROJECT, "checks": [CHECK]})
        for old, replacement in (
            ('"schemaVersion": 1', '"schemaVersion": 2, "schemaVersion": 1'),
            ('"guardedMerge": false', '"guardedMerge": true, "guardedMerge": false'),
            ('"name": "unit"', '"name": "other", "name": "unit"'),
        ):
            with self.subTest(field=old):
                self.configuration_path.write_text(
                    text.replace(old, replacement), encoding="utf-8"
                )
                with self.assertRaises(self.module.ConfigurationError):
                    self.module.load_configuration(self.root)

    def test_oversized_json_integer_is_a_configuration_error_without_traceback(self):
        self.configuration_path.write_text(
            '{"schemaVersion": ' + "1" * 5000 + "}", encoding="utf-8"
        )
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        with self.assertRaises(self.module.ConfigurationError):
            self.module.load_configuration(self.root)

    def test_exact_root_fields_and_types_are_required(self):
        invalid = [[], None]
        for field in PROJECT:
            value = copy.deepcopy(PROJECT)
            del value[field]
            invalid.append(value)
        invalid.append({**PROJECT, "unknown": True})
        for field, value in (
            ("schemaVersion", True),
            ("schemaVersion", 1.0),
            ("schemaVersion", 2),
            ("repositoryRole", "legacy"),
            ("repositoryRole", []),
            ("releaseKind", "package"),
            ("releaseKind", None),
            ("automations", []),
            ("checks", {}),
        ):
            invalid.append({**PROJECT, field: value})
        for value in invalid:
            with self.subTest(value=value):
                self.write_configuration(value)
                with self.assertRaises(self.module.ConfigurationError):
                    self.module.load_configuration(self.root)

    def test_all_automation_fields_are_required_booleans(self):
        for field in PROJECT["automations"]:
            for bad in (None, 0, 1, "false", [], {}):
                with self.subTest(field=field, bad=bad):
                    value = copy.deepcopy(PROJECT)
                    value["automations"][field] = bad
                    self.write_configuration(value)
                    with self.assertRaises(self.module.ConfigurationError):
                        self.module.load_configuration(self.root)
            value = copy.deepcopy(PROJECT)
            del value["automations"][field]
            self.write_configuration(value)
            with self.assertRaises(self.module.ConfigurationError):
                self.module.load_configuration(self.root)
        self.write_configuration(
            {
                **PROJECT,
                "automations": {
                    **PROJECT["automations"],
                    "unknown": False,
                },
            }
        )
        with self.assertRaises(self.module.ConfigurationError):
            self.module.load_configuration(self.root)

    def test_source_deployment_and_checks_are_exposed_without_execution(self):
        check = {
            **CHECK,
            "argv": ["missing-command", ""],
            "workingDirectory": "not-created/yet",
            "platforms": ["linux"],
        }
        self.write_configuration(
            {
                **PROJECT,
                "repositoryRole": "source",
                "releaseKind": "deployment",
                "checks": [check],
            }
        )
        configuration = self.module.load_configuration(self.root)
        parsed = configuration.checks[0]
        self.assertEqual(configuration.repository_role, "source")
        self.assertEqual(configuration.release_kind, "deployment")
        self.assertEqual(parsed.name, "unit")
        self.assertEqual(parsed.argv, ("missing-command", ""))
        self.assertEqual(parsed.working_directory, "not-created/yet")
        self.assertEqual(parsed.platforms, ("linux",))
        self.assertEqual(configuration.as_dict()["checks"], [check])
        self.assertFalse((self.root / "not-created").exists())

    def test_checks_reject_missing_extra_and_invalid_fields(self):
        invalid = [None, [], {**CHECK, "extra": True}]
        for field in CHECK:
            invalid.append({key: value for key, value in CHECK.items() if key != field})
        for field, bad in (
            ("name", ""),
            ("name", "  "),
            ("name", 1),
            ("name", "a\0b"),
            ("argv", []),
            ("argv", "python"),
            ("argv", [1]),
            ("argv", [""]),
            ("argv", ["  "]),
            ("argv", ["python\0"]),
            ("argv", ["python", None]),
            ("argv", ["python", "a\0b"]),
            ("platforms", []),
            ("platforms", "linux"),
            ("platforms", ["macos"]),
            ("platforms", ["linux", "linux"]),
            ("platforms", [1]),
            ("platforms", ["windows\0"]),
        ):
            invalid.append({**CHECK, field: bad})
        for check in invalid:
            with self.subTest(check=check):
                self.write_configuration({**PROJECT, "checks": [check]})
                with self.assertRaises(self.module.ConfigurationError):
                    self.module.load_configuration(self.root)

    def test_duplicate_check_names_are_rejected(self):
        self.write_configuration({**PROJECT, "checks": [CHECK, CHECK]})
        with self.assertRaises(self.module.ConfigurationError):
            self.module.load_configuration(self.root)

    def test_working_directory_rejects_nonportable_and_escaping_paths(self):
        for path in (
            None,
            "",
            " ",
            "/tmp",
            "//server/share",
            "C:/temp",
            "C:temp",
            "\\temp",
            "a\\b",
            "..",
            "../outside",
            "a/../../outside",
            "a/../b",
            "a\0b",
            "a:b",
        ):
            with self.subTest(path=path):
                self.write_configuration(
                    {
                        **PROJECT,
                        "checks": [
                            {**CHECK, "workingDirectory": path},
                        ],
                    }
                )
                with self.assertRaises(self.module.ConfigurationError):
                    self.module.load_configuration(self.root)

    def test_working_directory_rejects_nonportable_windows_components(self):
        for path in (
            "CON",
            "con.txt",
            "PRN",
            "AUX.log",
            "NUL",
            "nul.config",
            "COM1",
            "com9.py",
            "LPT1",
            "lpt9.txt",
            "COM¹",
            "LPT².txt",
            "CONIN$",
            "CONOUT$",
            "CON .txt",
            "nested/NUL.log/child",
            "dir?",
            "dir*",
            'dir"',
            "dir<",
            "dir>",
            "dir|",
            "nested/dir?/child",
            "trailing.",
            "trailing ",
            "nested/trailing./child",
            "A/.. /outside",
            "A/.../outside",
            "tab\tname",
            "line\nname",
            "control\x01",
            "delete\x7f",
            "control\x85",
        ):
            with self.subTest(path=path):
                self.write_configuration(
                    {
                        **PROJECT,
                        "checks": [
                            {**CHECK, "workingDirectory": path},
                        ],
                    }
                )
                with self.assertRaises(self.module.ConfigurationError):
                    self.module.load_configuration(self.root)

    def test_working_directory_accepts_root_and_normalized_nested_spellings(self):
        for path in (
            ".",
            "./",
            "./not-created/./nested",
            "normal name/child",
            "console",
            "COM10",
            "LPT0",
            "prefix.CON",
        ):
            with self.subTest(path=path):
                self.write_configuration(
                    {
                        **PROJECT,
                        "checks": [
                            {**CHECK, "workingDirectory": path},
                        ],
                    }
                )
                configuration = self.module.load_configuration(self.root)
                self.assertEqual(configuration.checks[0].working_directory, path)
        self.assertEqual(list(self.root.iterdir()), [self.configuration_path])

    def test_symlink_escape_is_rejected_even_with_missing_descendants(self):
        with tempfile.TemporaryDirectory(prefix="starter-project-outside-") as outside:
            link = self.root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlink unavailable: {error}")
            self.write_configuration(
                {
                    **PROJECT,
                    "checks": [
                        {**CHECK, "workingDirectory": "linked/not-created"},
                    ],
                }
            )
            with self.assertRaises(self.module.ConfigurationError):
                self.module.load_configuration(self.root)

    @unittest.skipUnless(os.name == "nt", "Windows directory junction")
    def test_junction_escape_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="starter-project-outside-") as outside:
            link = self.root / "junction"
            result = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(link), outside],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode:
                self.skipTest(f"junction unavailable: {result.stderr}")
            try:
                self.write_configuration(
                    {
                        **PROJECT,
                        "checks": [
                            {**CHECK, "workingDirectory": "junction/not-created"},
                        ],
                    }
                )
                with self.assertRaises(self.module.ConfigurationError):
                    self.module.load_configuration(self.root)
            finally:
                link.rmdir()

    def test_existing_nonfile_configuration_is_an_error(self):
        self.configuration_path.mkdir()
        with self.assertRaises(self.module.ConfigurationError):
            self.module.load_configuration(self.root)

    def test_missing_repository_root_is_an_error(self):
        with self.assertRaises(self.module.ConfigurationError):
            self.module.load_configuration(self.root / "absent")

    def test_cli_outputs_effective_json_and_dotted_values_read_only(self):
        self.write_configuration(PROJECT)
        before = self.configuration_path.read_bytes()
        cases = (
            ((), {"mode": "configured", **PROJECT}),
            (("--get", "checks"), []),
            (("--get", "automations"), PROJECT["automations"]),
            (("--get", "automations.guardedMerge"), False),
            (("--get", "schemaVersion"), 1),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)
        result = self.run_cli("--get", "releaseKind")
        self.assertEqual(result.stdout, "repository\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.configuration_path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.configuration_path])

    def test_cli_dry_run_reports_plan_without_writing_or_running_checks(self):
        marker = self.root / "executed"
        self.write_configuration(
            {
                **PROJECT,
                "checks": [
                    {
                        **CHECK,
                        "argv": [
                            sys.executable,
                            "-c",
                            f"open({str(marker)!r}, 'w').close()",
                        ],
                    },
                ],
            }
        )
        before = self.configuration_path.read_bytes()
        result = self.run_cli("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("read", result.stdout.lower())
        self.assertFalse(marker.exists())
        self.assertEqual(self.configuration_path.read_bytes(), before)
        self.configuration_path.unlink()
        result = self.run_cli("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.configuration_path.exists())

    def test_cli_errors_are_nonzero_and_only_verbose_has_traceback(self):
        self.write_configuration(PROJECT)
        for key in ("unknown", "automations.unknown", "checks.name", "", ".mode"):
            result = self.run_cli("--get", key)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
        self.configuration_path.write_text("{", encoding="utf-8")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        result = self.run_cli("--verbose")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Traceback", result.stderr)

    def test_cli_help_version_and_invalid_options(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in (
            "--help",
            "--version",
            "--dry-run",
            "--verbose",
            "--repository-root",
            "--get",
        ):
            self.assertIn(option, result.stdout)
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^v\d+\.\d+\.\d+$")
        result = self.run_cli("--unknown-option")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
