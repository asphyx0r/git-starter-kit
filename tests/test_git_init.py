"""Exercise public initializers with real Git and staged release artifacts.

The bounded hook/Commitlint fixtures isolate orchestration; they do not qualify
the full composed package and its production hooks.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
BASH = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


class InitializerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="initializer tests ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "package with spaces"
        self.root.mkdir()
        self.env = os.environ.copy()
        self.env.update(
            GIT_AUTHOR_NAME="Initializer Test",
            GIT_AUTHOR_EMAIL="init@example.test",
            GIT_COMMITTER_NAME="Initializer Test",
            GIT_COMMITTER_EMAIL="init@example.test",
            GIT_CONFIG_GLOBAL=str(Path(self.temporary.name) / "global.gitconfig"),
            GIT_CONFIG_NOSYSTEM="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        Path(self.env["GIT_CONFIG_GLOBAL"]).write_text(
            "[init]\n\tdefaultBranch = legacy\n[core]\n\tautocrlf = false\n",
            encoding="utf-8",
        )
        self.env["PATH"] = (
            str(Path(sys.executable).parent) + os.pathsep + self.env["PATH"]
        )
        for name in (
            "tools/release-artifacts.py",
            "tools/git_objects.py",
            "tools/process_runner.py",
            "templates/release/repository-manifest.schema.json",
        ):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, destination)
        self.write(".gitignore", "tools/quality/node_modules/\n")
        self.write("tools/git-inventory-context/HEAD", "ref: refs/heads/main\n")
        self.write("tools/git-inventory-context/objects/.gitkeep", "")
        self.write("tools/git-inventory-context/refs/.gitkeep", "")
        self.write("README.md", "System template\n")
        self.write("_agent-rules-source.json", '{"authentic": "fixture upstream"}\n')
        self.write("starter-kit-manifest.json", '{"version": "upstream-2.10.0"}\n')
        self.write("CHANGELOG.md", "# CHANGELOG\n\nSource history must disappear\n")
        self.write("commitlint.config.cjs", "module.exports = {};\n")
        self.write("runner", "#!/bin/sh\nexit 0\n")
        self.write("ordinary.sh", "plain system content\n")
        self.write(
            ".githooks/commit-msg",
            "#!/bin/sh\n"
            'test "$(git symbolic-ref --short HEAD)" = main || exit 31\n'
            'test "$(cat "$1")" = \'chore(git): initialize repository\'\n',
        )
        (self.root / ".githooks/commit-msg").chmod(0o755)
        bin_path = self.root / "tools/quality/node_modules/.bin"
        bin_path.mkdir(parents=True)
        self.write(
            "tools/quality/node_modules/.bin/commitlint",
            "#!/bin/sh\n"
            'test "$1" = --edit && test "$(cat "$2")" = '
            "'chore(git): initialize repository'\n",
        )
        (bin_path / "commitlint").chmod(0o755)
        if os.name == "nt":
            self.write("tools/quality/node_modules/.bin/commitlint.cmd", "@exit /b 0\n")
        self.inventory()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def inventory(self):
        entries = []
        for path in sorted(self.root.rglob("*")):
            name = path.relative_to(self.root).as_posix()
            if (
                path.is_file()
                and name != "_starter-kit-files.json"
                and "node_modules" not in name
            ):
                entries.append(
                    {
                        "path": name,
                        "mode": "100755"
                        if name in {"runner", ".githooks/commit-msg"}
                        else "100644",
                    }
                )
        self.write(
            "_starter-kit-files.json",
            json.dumps({"schemaVersion": 3, "files": entries}),
        )

    def git(self, *arguments, check=True):
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def run_initializer(self, shell, *arguments, answers="y\ny\ny\n"):
        executable = BASH if shell == "bash" else POWERSHELL
        assert executable is not None
        command = (
            [executable, str(SOURCE / "tools/git-init.sh")]
            if shell == "bash"
            else [executable, "-NoProfile", "-File", str(SOURCE / "tools/git-init.ps1")]
        )
        return subprocess.run(
            [*command, "--path", str(self.root), *arguments],
            env=self.env,
            input=answers,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )

    def shells(self):
        return [
            name
            for name, executable in (("bash", BASH), ("powershell", POWERSHELL))
            if executable
        ]

    def snapshot(self):
        return {
            path.relative_to(self.root).as_posix(): ("file", path.read_bytes())
            if path.is_file()
            else ("directory", None)
            for path in self.root.rglob("*")
        }

    def test_helper_standard_flags_report_version_and_preview_without_mutation(self):
        helper = SOURCE / "tools/initialize-repository.py"
        version = subprocess.run(
            [sys.executable, "-B", str(helper), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertTrue(version.stdout.strip())
        before = self.snapshot()
        preview = subprocess.run(
            [
                sys.executable,
                "-B",
                str(helper),
                "prepare",
                "--dry-run",
                "--verbose",
                "--path",
                str(self.root),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_interfaces_never_attempt_external_temporary_writes(self):
        observer = Path(self.temporary.name) / "observer"
        observer.mkdir()
        (observer / "sitecustomize.py").write_text(
            "import sys\n"
            "def observe(event, args):\n"
            "    if event in {'tempfile.mkdtemp', 'tempfile.mkstemp', 'os.mkdir'}:\n"
            "        raise AssertionError('dry-run write attempted: ' + event)\n"
            "sys.addaudithook(observe)\n",
            encoding="utf-8",
        )
        self.env["PYTHONPATH"] = str(observer)
        for unborn in (False, True):
            if unborn:
                self.git("init", "--initial-branch=main")
            for interface in ("helper", *self.shells()):
                with self.subTest(unborn=unborn, interface=interface):
                    before = self.snapshot()
                    config_before = Path(self.env["GIT_CONFIG_GLOBAL"]).read_bytes()
                    if interface == "helper":
                        result = subprocess.run(
                            [
                                sys.executable,
                                "-B",
                                str(SOURCE / "tools/initialize-repository.py"),
                                "validate",
                                "--dry-run",
                                "--path",
                                str(self.root),
                            ],
                            env=self.env,
                            capture_output=True,
                            text=True,
                            timeout=90,
                            check=False,
                        )
                    else:
                        result = self.run_initializer(interface, "--dry-run")
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(
                        Path(self.env["GIT_CONFIG_GLOBAL"]).read_bytes(), config_before
                    )

    def test_no_args_help_version_do_not_require_target_or_tools(self):
        help_env = self.env.copy()
        if os.name != "nt":
            help_bin = Path(self.temporary.name) / "help tools"
            help_bin.mkdir()
            cat_command = shutil.which("cat")
            assert cat_command is not None
            (help_bin / "cat").symlink_to(cat_command)
            help_env["PATH"] = str(help_bin)
        for shell in self.shells():
            executable = BASH if shell == "bash" else POWERSHELL
            assert executable is not None
            command = (
                [executable, str(SOURCE / "tools/git-init.sh")]
                if shell == "bash"
                else [
                    executable,
                    "-NoProfile",
                    "-File",
                    str(SOURCE / "tools/git-init.ps1"),
                ]
            )
            for arguments in ([], ["--help"], ["--version"]):
                with self.subTest(shell=shell, arguments=arguments):
                    result = subprocess.run(
                        [*command, *arguments],
                        env=help_env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(result.stdout.strip())
                    self.assertEqual(result.stderr, "")

    def test_inventory_non_string_mode_is_reported_without_traceback(self):
        value = json.loads((self.root / "_starter-kit-files.json").read_text())
        value["files"].append({"path": "new.txt", "mode": []})
        self.write("_starter-kit-files.json", json.dumps(value))
        before = self.snapshot()
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SOURCE / "tools/initialize-repository.py"),
                "validate",
                "--path",
                str(self.root),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_first_commit_prepares_release_on_main_and_restores_inventory_modes(self):
        # Missing pre-commit main selection, index preparation or exact modes
        # must fail this real first-commit and tag validation.
        for shell in self.shells():
            with self.subTest(shell=shell):
                before_provenance = (
                    self.root / "_agent-rules-source.json"
                ).read_bytes()
                self.git("init")
                self.git("config", "core.filemode", "false")
                result = self.run_initializer(shell, "--tag", "v2.3.4-beta.1+build.5")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.git("symbolic-ref", "--short", "HEAD"), "main")
                self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")
                self.assertEqual(
                    self.git("cat-file", "-t", "v2.3.4-beta.1+build.5"), "tag"
                )
                self.assertEqual(
                    self.git("rev-parse", "HEAD"),
                    self.git("rev-parse", "v2.3.4-beta.1+build.5^{}"),
                )
                for name, mode in (
                    ("runner", "100755"),
                    ("ordinary.sh", "100644"),
                    ("manifest.json", "100644"),
                    ("VERSION", "100644"),
                ):
                    self.assertTrue(
                        self.git("ls-tree", "HEAD", name).startswith(mode + " ")
                    )
                self.assertEqual(
                    (self.root / "VERSION").read_text(), "2.3.4-beta.1+build.5\n"
                )
                changelog = (self.root / "CHANGELOG.md").read_text()
                self.assertIn("Initialisation du repository Git", changelog)
                self.assertNotIn("Source history", changelog)
                self.assertNotIn("## ", changelog)
                self.assertNotIn("| Initial commit |", changelog)
                self.assertEqual(
                    (self.root / "_agent-rules-source.json").read_bytes(),
                    before_provenance,
                )
                check = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(self.root / "tools/release-artifacts.py"),
                        "check",
                        "--repository-root",
                        str(self.root),
                        "--treeish",
                        "v2.3.4-beta.1+build.5",
                        "--expected-ref",
                        "v2.3.4-beta.1+build.5",
                    ],
                    env=self.env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertEqual(self.git("status", "--porcelain"), "")
                self.assertIn(
                    "defaultBranch = legacy",
                    Path(self.env["GIT_CONFIG_GLOBAL"]).read_text(),
                )
            # Each shell must start with the original fixture, including no HEAD.
            if shell != self.shells()[-1]:
                self.reset_fixture()

    def reset_fixture(self):
        self.temporary.cleanup()
        self.setUp()

    def test_fresh_default_tag_and_explicit_local_remote_publish_exact_first_commit(
        self,
    ):
        for shell in self.shells():
            with self.subTest(shell=shell):
                remote = Path(self.temporary.name) / "explicit remote.git"
                create = subprocess.run(
                    ["git", "init", "--bare", str(remote)],
                    env=self.env,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(create.returncode, 0)
                result = self.run_initializer(shell, "--remote", str(remote))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")
                self.assertEqual(self.git("cat-file", "-t", "v1.0.0"), "tag")
                self.assertEqual(
                    self.git("rev-parse", "HEAD"), self.git("rev-parse", "v1.0.0^{}")
                )
                self.assertIn(
                    "Initialisation du repository Git",
                    self.git(
                        "for-each-ref", "--format=%(contents)", "refs/tags/v1.0.0"
                    ),
                )
                remote_commit = subprocess.check_output(
                    ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
                    env=self.env,
                    text=True,
                ).strip()
                self.assertEqual(remote_commit, self.git("rev-parse", "HEAD"))
                self.assertEqual(
                    self.git("config", "--get", "branch.main.remote"), "origin"
                )
                # Local success does not imply hosted/default branch mutation.
                remote_default = subprocess.check_output(
                    ["git", "--git-dir", str(remote), "symbolic-ref", "HEAD"],
                    env=self.env,
                    text=True,
                ).strip()
                self.assertEqual(remote_default, "refs/heads/legacy")
            if shell != self.shells()[-1]:
                self.reset_fixture()

    def test_dry_run_does_not_change_target_or_unborn_git(self):
        for shell in self.shells():
            for unborn in (False, True):
                with self.subTest(shell=shell, unborn=unborn):
                    if unborn:
                        self.git("init")
                        self.git("config", "core.hooksPath", "preserve-existing-hooks")
                        self.git("add", "README.md")
                    before = self.snapshot()
                    result = self.run_initializer(shell, "--dry-run", answers="")
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertEqual(self.snapshot(), before)
                    self.assertIn("main", result.stdout)
                self.reset_fixture()

    def test_unknown_application_file_is_refused_without_mutation(self):
        self.write("application.py", "print('app')\n")
        for shell in self.shells():
            with self.subTest(shell=shell):
                before = self.snapshot()
                result = self.run_initializer(shell)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("application.py", result.stdout + result.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_missing_inventory_explains_release_zip_without_mutation(self):
        (self.root / "_starter-kit-files.json").unlink()
        (self.root / ".githooks/commit-msg").unlink()
        for shell in self.shells():
            before = self.snapshot()
            result = self.run_initializer(shell)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ZIP", result.stdout + result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_cancel_at_both_confirmations_does_not_change_target(self):
        self.write(".env", "EXAMPLE=fixture\n")
        for shell in self.shells():
            for answers in ("n\n", "y\nn\n", "y\ny\nn\n"):
                before = self.snapshot()
                result = self.run_initializer(shell, answers=answers)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_unsafe_inventory_paths_modes_and_generated_aliases_are_refused(self):
        self.write("VERSION", "upstream\n")
        original = (self.root / "_starter-kit-files.json").read_text()
        for path, mode in (
            ("../outside.txt", "100644"),
            ("runner", "120000"),
            (".git/config", "100644"),
            ("VERSION", "100755"),
            ("README.md ", "100644"),
        ):
            for shell in self.shells():
                with self.subTest(path=path, mode=mode, shell=shell):
                    value = json.loads(original)
                    value["files"].append({"path": path, "mode": mode})
                    self.write("_starter-kit-files.json", json.dumps(value))
                    before = self.snapshot()
                    result = self.run_initializer(shell, "--dry-run", answers="")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.snapshot(), before)

    def test_commitlint_and_commit_failures_never_create_a_tag(self):
        for shell in self.shells():
            for failure in ("commitlint", "hook", "prepare"):
                with self.subTest(shell=shell, failure=failure):
                    if failure == "commitlint":
                        self.write(
                            "tools/quality/node_modules/.bin/commitlint",
                            "#!/bin/sh\nexit 37\n",
                        )
                        if os.name == "nt":
                            self.write(
                                "tools/quality/node_modules/.bin/commitlint.cmd",
                                "@exit /b 37\n",
                            )
                    elif failure == "hook":
                        self.write(".githooks/commit-msg", "#!/bin/sh\nexit 38\n")
                    else:
                        self.write(
                            "tools/release-artifacts.py", "raise SystemExit(39)\n"
                        )
                    result = self.run_initializer(shell)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.git("tag"), "")
                    self.assertEqual(self.git("rev-list", "--all", check=False), "")
                self.reset_fixture()

    def test_invalid_git_metadata_and_existing_history_are_refused(self):
        (self.root / ".git").mkdir()
        for shell in self.shells():
            before = self.snapshot()
            result = self.run_initializer(shell)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Git cannot read", result.stdout + result.stderr)
            self.assertEqual(self.snapshot(), before)
        (self.root / ".git").rmdir()
        self.git("init")
        self.git("add", "README.md")
        self.git("commit", "-m", "test: existing history")
        for shell in self.shells():
            before = self.snapshot()
            result = self.run_initializer(shell, "--dry-run", answers="")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already has commits", result.stdout + result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_unborn_head_with_other_reachable_history_is_refused_without_mutation(self):
        for branch in ("main", "archive"):
            for shell in self.shells():
                for dry_run in (False, True):
                    with self.subTest(branch=branch, shell=shell, dry_run=dry_run):
                        self.git("init", f"--initial-branch={branch}")
                        self.git("add", "README.md")
                        self.git("commit", "-m", "test: retained history")
                        retained_commit = self.git("rev-parse", "HEAD")
                        self.git("symbolic-ref", "HEAD", "refs/heads/unborn")
                        self.assertEqual(
                            self.git("rev-parse", "--verify", "HEAD", check=False), ""
                        )
                        before = self.snapshot()
                        arguments = ("--dry-run",) if dry_run else ()
                        result = self.run_initializer(shell, *arguments)
                        count = self.git("rev-list", "--all", "--count")
                        self.assertNotEqual(
                            result.returncode,
                            0,
                            f"Accepted retained {branch} history; {count} commits remain.\n"
                            + result.stdout
                            + result.stderr,
                        )
                        self.assertIn(
                            "already has commits", result.stdout + result.stderr
                        )
                        self.assertEqual(self.snapshot(), before)
                        self.assertEqual(
                            self.git("rev-parse", f"refs/heads/{branch}"),
                            retained_commit,
                        )
                    self.reset_fixture()

    def test_missing_commit_validation_tool_fails_before_git_init(self):
        shutil.rmtree(self.root / "tools/quality/node_modules")
        # Keep Git and Python accessible, with no Commitlint fallback on PATH.
        tool_dir = Path(self.temporary.name) / "only required tools"
        tool_dir.mkdir()
        if os.name == "nt":
            git_command = shutil.which("git")
            assert git_command is not None and BASH is not None
            git_bin = Path(git_command).parent
            self.env["PATH"] = os.pathsep.join(
                (
                    str(Path(sys.executable).parent),
                    str(git_bin),
                    str(Path(BASH).parent),
                    "C:/Windows/System32",
                )
            )
        else:
            for name, source in (
                ("git", shutil.which("git")),
                ("dirname", shutil.which("dirname")),
                ("basename", shutil.which("basename")),
                ("mktemp", shutil.which("mktemp")),
                ("rm", shutil.which("rm")),
            ):
                assert source is not None
                (tool_dir / name).symlink_to(source)
            python_command = tool_dir / "python"
            python_command.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8"
            )
            python_command.chmod(0o755)
            self.env["PATH"] = str(tool_dir)
        for shell in self.shells():
            before = self.snapshot()
            result = self.run_initializer(shell, "--dry-run", answers="")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("commitlint is required", result.stdout + result.stderr)
            self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == "nt", "Symlink fixture requires Linux permissions")
    def test_generated_output_symlink_is_refused_before_writing_outside_target(self):
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_text("untouched\n", encoding="utf-8")
        (self.root / "VERSION").symlink_to(outside)
        result = self.run_initializer("bash", "--dry-run", answers="")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outside.read_text(), "untouched\n")

    @unittest.skipUnless(os.name == "nt", "Directory junction fixture requires Windows")
    def test_inventory_directory_junction_outside_target_is_refused(self):
        outside = Path(self.temporary.name) / "outside target"
        outside.mkdir()
        external = outside / "external.txt"
        external.write_text("untouched\n", encoding="utf-8")
        junction = self.root / "junction"
        create = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(create.returncode, 0, create.stderr)
        value = json.loads((self.root / "_starter-kit-files.json").read_text())
        value["files"].append({"path": "junction/external.txt", "mode": "100644"})
        self.write("_starter-kit-files.json", json.dumps(value))
        before = self.snapshot()
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SOURCE / "tools/initialize-repository.py"),
                "validate",
                "--path",
                str(self.root),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside target", result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(external.read_text(), "untouched\n")


if __name__ == "__main__":
    unittest.main()
