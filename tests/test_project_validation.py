"""Project command execution and distributed core ownership contracts."""

import contextlib
import io
import json
import locale
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import project_config
import project_validation


class ProjectValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="project-validation-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.configuration = project_config.default_project_configuration()

    def write_configuration(self, checks=()):
        self.configuration["checks"] = list(checks)
        (self.root / ".starter-kit-project.json").write_text(
            json.dumps(self.configuration), encoding="utf-8"
        )

    def check(self, code="pass", cwd=".", platforms=("linux", "windows")):
        return {
            "name": "application",
            "argv": [sys.executable, "-c", code],
            "workingDirectory": cwd,
            "platforms": list(platforms),
        }

    def inventory(self, paths):
        for path in paths:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        (self.root / "_starter-kit-files.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 3,
                    "files": [{"path": p, "mode": "100644"} for p in paths],
                }
            ),
            encoding="utf-8",
        )

    def test_consumer_paths_use_inventory_not_application_directories(self):
        self.write_configuration()
        self.inventory(["tools/core.py", "tools/core.psm1", "tools/core.psd1"])
        for path in (
            "tools/app.py",
            "tests/app.py",
            "laravel/tests/Test.php",
            "laravel/vendor/pkg.php",
            "main.go",
            "app.sh",
            "app.ps1",
        ):
            self.assertFalse(project_validation.is_core_path(self.root, path), path)
        self.assertTrue(project_validation.is_core_path(self.root, "tools/core.psm1"))
        self.assertTrue(project_validation.is_core_path(self.root, "tools/core.psd1"))

    def test_missing_and_malformed_inventory_fail_for_configured_consumer(self):
        self.write_configuration()
        with self.assertRaises(ValueError):
            project_validation.core_paths(self.root)
        for mode in ([], {}):
            (self.root / "_starter-kit-files.json").write_text(
                json.dumps(
                    {"schemaVersion": 3, "files": [{"path": "core.py", "mode": mode}]}
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                project_validation.core_paths(self.root)
        (self.root / "_starter-kit-files.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            project_validation.core_paths(self.root)

    def test_source_and_legacy_without_inventory_retain_maintenance_scope(self):
        self.assertEqual(project_validation.repository_scope(self.root), "source")
        self.configuration["repositoryRole"] = "source"
        self.write_configuration()
        self.assertEqual(project_validation.repository_scope(self.root), "source")

    def test_public_ownership_cli_and_read_only_project_plan(self):
        self.inventory(["tools/core.py", "tools/missing.py"])
        (self.root / "tools/missing.py").unlink()
        self.write_configuration(
            [self.check("from pathlib import Path; Path('must-not-run').touch()")]
        )
        arguments = ["--repository-root", str(self.root)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(project_validation.main([*arguments, "--scope"]), 0)
            self.assertEqual(project_validation.main([*arguments, "--list-core"]), 0)
            self.assertEqual(
                project_validation.main([*arguments, "--owns", "tools/core.py"]), 0
            )
            self.assertEqual(
                project_validation.main([*arguments, "--owns", "app/main.py"]), 1
            )
            self.assertEqual(
                project_validation.main([*arguments, "--verbose", "--dry-run"]), 0
            )
        self.assertIn("project\n", output.getvalue())
        self.assertIn("tools/core.py\0", output.getvalue())
        self.assertNotIn("tools/missing.py\0", output.getvalue())
        self.assertIn("not run (read-only plan)", output.getvalue())
        self.assertFalse((self.root / "must-not-run").exists())

    def test_explicit_argv_and_cwd_are_executed_without_shell(self):
        (self.root / "application").mkdir()
        self.write_configuration(
            [
                self.check(
                    "from pathlib import Path; Path('ran').write_text('yes')",
                    "application",
                )
            ]
        )
        self.assertEqual(project_validation.run_checks(self.root, timeout=5), 0)
        self.assertEqual((self.root / "application/ran").read_text(), "yes")

    def test_invalid_command_output_retains_both_streams_and_exit_status(self):
        script = Path(project_validation.__file__).resolve()
        for command_status, expected_status in ((0, 0), (3, 1)):
            with self.subTest(command_status=command_status):
                self.write_configuration(
                    [
                        self.check(
                            "import os; "
                            "os.write(1, b'stdout-before\\xff-after\\n'); "
                            "os.write(2, b'stderr-before\\x81-after\\n'); "
                            f"raise SystemExit({command_status})"
                        )
                    ]
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-B",
                        str(script),
                        "--repository-root",
                        str(self.root),
                    ],
                    capture_output=True,
                    encoding="utf-8",
                    check=False,
                    timeout=10,
                )
                self.assertEqual(
                    result.returncode, expected_status, result.stdout + result.stderr
                )
                self.assertIn("stdout-before\\xff-after\n", result.stdout)
                self.assertIn("stderr-before\\x81-after\n", result.stderr)
                self.assertNotIn("None", result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertIn(
                    "application: passed"
                    if command_status == 0
                    else "application: failed",
                    result.stdout,
                )

    def test_list_owned_includes_absent_paths_without_changing_list_core(self):
        self.inventory(["docs/café [space].md", "tools/absent λ.py"])
        (self.root / "tools/absent λ.py").unlink()
        self.write_configuration()
        arguments = ["--repository-root", str(self.root)]
        script = Path(project_validation.__file__).resolve()
        owned = subprocess.run(
            [sys.executable, "-B", str(script), *arguments, "--list-owned"],
            env={**os.environ, "PYTHONIOENCODING": "cp1252"},
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(owned.returncode, 0, owned.stderr)
        self.assertIn("docs/café [space].md\0".encode("utf-8"), owned.stdout)
        self.assertEqual(
            set(owned.stdout.decode("utf-8").rstrip("\0").split("\0")),
            {
                "_starter-kit-files.json",
                ".starter-kit-project.json",
                "starter-kit-manifest.json",
                "VERSION",
                "CHANGELOG.md",
                "SHA256SUMS",
                "manifest.json",
                "docs/café [space].md",
                "tools/absent λ.py",
            },
        )
        present = io.StringIO()
        with contextlib.redirect_stdout(present):
            self.assertEqual(project_validation.main([*arguments, "--list-core"]), 0)
        self.assertEqual(
            set(present.getvalue().rstrip("\0").split("\0")),
            {
                "_starter-kit-files.json",
                ".starter-kit-project.json",
                "docs/café [space].md",
            },
        )

    def test_list_owned_rejects_unsafe_inventory_before_writing_paths(self):
        self.inventory(["tools/core.py"])
        inventory = self.root / "_starter-kit-files.json"
        value = json.loads(inventory.read_text(encoding="utf-8"))
        value["files"].append({"path": "../escape.py", "mode": "100644"})
        inventory.write_text(json.dumps(value), encoding="utf-8")
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            self.assertEqual(
                project_validation.main(
                    ["--repository-root", str(self.root), "--list-owned"]
                ),
                1,
            )
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Unsafe managed inventory path", error.getvalue())

    def test_list_owned_rejects_unencodable_inventory_before_writing_paths(self):
        (self.root / "_starter-kit-files.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 3,
                    "files": [{"path": "zzz/\ud800.py", "mode": "100644"}],
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(project_validation.__file__).resolve()),
                "--repository-root",
                str(self.root),
                "--list-owned",
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_failed_missing_binary_missing_cwd_and_timeout_block(self):
        for check in (
            self.check("raise SystemExit(3)"),
            self.check(cwd="absent"),
            self.check("import time; time.sleep(30)"),
            {**self.check(), "argv": ["definitely-absent-starter-command"]},
        ):
            with self.subTest(check=check):
                self.write_configuration([check])
                self.assertNotEqual(
                    project_validation.run_checks(self.root, timeout=0.4), 0
                )

    def test_empty_and_platform_ineligible_checks_are_not_passed(self):
        self.write_configuration()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(project_validation.run_checks(self.root), 0)
        self.assertIn("WARNING", output.getvalue())
        self.assertNotIn("passed", output.getvalue())
        self.write_configuration([self.check(platforms=("windows",))])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(
                project_validation.run_checks(self.root, platform="linux"), 0
            )
        self.assertIn("not run", output.getvalue())

    def test_initial_system_state_requires_first_commit_and_only_core(self):
        self.write_configuration()
        self.inventory(["tools/core.py"])
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        for args in (
            ["config", "user.name", "Test"],
            ["config", "user.email", "test@example.com"],
            ["add", "."],
            ["commit", "-qm", "chore: initial"],
        ):
            subprocess.run(["git", "-C", str(self.root), *args], check=True)
        self.assertTrue(project_validation.initial_system_only(self.root))
        (self.root / "main.go").write_text("package main\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "feat: application"],
            check=True,
        )
        self.assertFalse(project_validation.initial_system_only(self.root))

    def test_first_system_head_runs_new_declared_checks_in_real_cli(self):
        self.write_configuration()
        self.inventory(["tools/core.py"])
        git = ["git", "-C", str(self.root)]
        subprocess.run([*git, "init", "-q"], check=True)
        for arguments in (
            ["config", "user.name", "Test"],
            ["config", "user.email", "test@example.com"],
            ["add", "."],
            ["commit", "-qm", "chore: initial"],
            ["tag", "-a", "v1.0.0", "-m", "initial system"],
        ):
            subprocess.run([*git, *arguments], check=True)
        head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True)
        tag = subprocess.check_output([*git, "rev-parse", "v1.0.0"], text=True)
        self.assertTrue(project_validation.initial_system_only(self.root))
        script = Path(project_validation.__file__).resolve()

        def cli(*arguments):
            return subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(script),
                    "--repository-root",
                    str(self.root),
                    *arguments,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )

        result = cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "non-applicable (proven initial system-only commit)", result.stdout
        )
        marker = self.root / "declared-check-ran"
        self.write_configuration(
            [self.check("from pathlib import Path; Path('declared-check-ran').touch()")]
        )
        result = cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            marker.exists(), "declared check must run even with first system HEAD"
        )
        marker.unlink()
        self.write_configuration([self.check("raise SystemExit(3)")])
        result = cli()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Project check application: failed", result.stdout)
        self.write_configuration(
            [self.check("from pathlib import Path; Path('declared-check-ran').touch()")]
        )
        result = cli("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("not run (read-only plan)", result.stdout)
        self.assertFalse(marker.exists())
        self.write_configuration()
        result = cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "non-applicable (proven initial system-only commit)", result.stdout
        )
        self.assertEqual(
            subprocess.check_output([*git, "rev-parse", "HEAD"], text=True), head
        )
        self.assertEqual(
            subprocess.check_output([*git, "rev-parse", "v1.0.0"], text=True), tag
        )

    def test_hook_routes_consumer_application_without_source_tests(self):
        self.write_configuration()
        self.inventory(["tools/core.py"])
        dispatcher = Path(__file__).resolve().parents[1] / "tools/repository-audit.sh"
        bash = shutil.which("bash")
        if sys.platform == "win32":
            bash = "C:/Program Files/Git/bin/bash.exe"
        self.assertIsNotNone(bash)
        result = subprocess.run(
            [
                bash,
                "--noprofile",
                "--norc",
                "-c",
                """
export PATH="/usr/bin:/bin:$PATH"
source "$1" || exit
repository_root="$2"
run_python=false run_shell=false run_workflows=false full_snapshot=false python_modules=''
classify_hook_path 'laravel/tests/AppTest.php'
[[ "$run_python" == false && "$run_shell" == false ]]
""",
                "ownership-test",
                dispatcher.as_posix(),
                self.root.as_posix(),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_push_uses_exact_configuration_and_deduplicates_branch_tag(self):
        self.inventory(["tools/core.py"])
        (self.root / "main.go").write_text("package main\n", encoding="utf-8")
        trace = self.root.parent / (self.root.name + ".trace")
        self.addCleanup(lambda: trace.unlink(missing_ok=True))
        self.write_configuration(
            [
                self.check(
                    f"from pathlib import Path; p=Path({str(trace)!r}); p.write_text(p.read_text()+'pushed\\n' if p.exists() else 'pushed\\n')"
                )
            ]
        )
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        for args in (
            ["config", "user.name", "Test"],
            ["config", "user.email", "test@example.com"],
            ["add", "."],
            ["commit", "-qm", "feat: application"],
        ):
            subprocess.run(["git", "-C", str(self.root), *args], check=True)
        oid = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True
        ).strip()
        subprocess.run(
            ["git", "-C", str(self.root), "tag", "-a", "v1.0.0", "-m", "release"],
            check=True,
        )
        tag_oid = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "v1.0.0"], text=True
        ).strip()
        self.write_configuration(
            [{**self.check(), "argv": ["dirty-command-must-not-run"]}]
        )
        dispatcher = Path(__file__).resolve().parents[1] / "tools/repository-audit.sh"
        bash = (
            "C:/Program Files/Git/bin/bash.exe"
            if sys.platform == "win32"
            else shutil.which("bash")
        )
        result = subprocess.run(
            [
                bash,
                "--noprofile",
                "--norc",
                "-c",
                """
export PATH="/usr/bin:/bin:$PATH"
source "$1" || exit
repository_root="$2"
cd "$2" || exit
run_consumer_core() { printf 'core stub called\\n'; }
run_hook_release_check() { printf 'release stub called\\n'; }
printf 'refs/heads/main %s refs/heads/main %s\\nrefs/tags/v1.0.0 %s refs/tags/v1.0.0 %s\\n' "$3" "$4" "$5" "$4" | run_hook_pre_push origin "$2"
""",
                "immutable-test",
                dispatcher.as_posix(),
                self.root.as_posix(),
                oid,
                "0" * 40,
                tag_oid,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(trace.read_text().splitlines(), ["pushed"])

    def test_cwd_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory(
            prefix="project-validation-outside-"
        ) as outside:
            self.write_configuration([self.check(cwd="linked")])
            try:
                (self.root / "linked").symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Symlink unavailable: {error}")
            with self.assertRaises(project_config.ConfigurationError):
                project_validation.run_checks(self.root)

    def test_nonzero_and_timeout_remove_descendants(self):
        for parent_code, timeout in (
            ("raise SystemExit(3)", 5),
            ("import time; time.sleep(30)", 0.6),
        ):
            marker = self.root / "descendant-survived"
            child = f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).write_text('alive')"
            code = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); {parent_code}"
            self.write_configuration([self.check(code)])
            self.assertNotEqual(
                project_validation.run_checks(self.root, timeout=timeout), 0
            )
            time.sleep(1.2)
            self.assertFalse(marker.exists(), parent_code)

    def test_timeout_preserves_real_stdout_and_stderr(self):
        self.write_configuration(
            [
                self.check(
                    "import sys,time; print('before timeout', flush=True); "
                    "print('failure detail', file=sys.stderr, flush=True); time.sleep(30)"
                )
            ]
        )
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = project_validation.run_checks(self.root, timeout=0.8)
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue().count("before timeout"), 1)
        self.assertEqual(errors.getvalue().splitlines().count("failure detail"), 1)

    def test_timeout_uses_latest_cumulative_capture_without_duplicate_output(self):
        self.write_configuration([self.check()])
        for drain in (
            ("first\nlast\n", "detail\nmore\n"),
            subprocess.TimeoutExpired(
                [], 1, b"first\nlast\xff\n", b"detail\nmore\xfe\n"
            ),
            subprocess.TimeoutExpired([], 1),
        ):
            with self.subTest(drain=drain):
                scope = MagicMock()
                scope.process.communicate.side_effect = [
                    subprocess.TimeoutExpired([], 1, b"first\n", b"detail\n"),
                    drain,
                ]
                output, errors = io.StringIO(), io.StringIO()
                with (
                    patch.object(project_validation, "ProcessScope") as factory,
                    patch.object(locale, "getencoding", return_value="utf-8"),
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(errors),
                ):
                    factory.return_value.__enter__.return_value = scope
                    status = project_validation.run_checks(self.root, timeout=1)
                self.assertEqual(status, 1)
                self.assertEqual(output.getvalue().count("first\n"), 1)
                self.assertEqual(errors.getvalue().count("detail\n"), 1)
                if isinstance(drain, tuple) or drain.stdout is not None:
                    self.assertIn("last", output.getvalue())
                    self.assertIn("more", errors.getvalue())
                if isinstance(drain, subprocess.TimeoutExpired) and drain.stdout:
                    self.assertIn(r"\xff", output.getvalue())
                    self.assertIn(r"\xfe", errors.getvalue())

    def test_timeout_capture_uses_default_locale_or_utf8_mode_codec(self):
        self.write_configuration([self.check()])
        for utf8_mode, locale_encoding, expected in (
            (0, "cp1252", "éÿ"),
            (0, "ascii", r"\xe9\xff"),
            (1, "cp1252", r"\xe9\xff"),
        ):
            with self.subTest(utf8_mode=utf8_mode, locale_encoding=locale_encoding):
                scope = MagicMock()
                scope.process.communicate.side_effect = [
                    subprocess.TimeoutExpired([], 1, b"\xe9\xff\n", b"\xe9\xff\n"),
                    subprocess.TimeoutExpired([], 1),
                ]
                output, errors = io.StringIO(), io.StringIO()
                sys_proxy = SimpleNamespace(
                    platform=sys.platform,
                    flags=SimpleNamespace(utf8_mode=utf8_mode),
                    stdout=output,
                    stderr=errors,
                )
                with (
                    patch.object(project_validation, "ProcessScope") as factory,
                    patch.object(locale, "getencoding", return_value=locale_encoding),
                    patch.object(project_validation, "sys", sys_proxy),
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(errors),
                ):
                    factory.return_value.__enter__.return_value = scope
                    status = project_validation.run_checks(self.root, timeout=1)
                self.assertEqual(status, 1)
                self.assertEqual(output.getvalue().splitlines().count(expected), 1)
                self.assertEqual(errors.getvalue().splitlines().count(expected), 1)


if __name__ == "__main__":
    unittest.main()
