"""Protect new application sources and fixtures from generic ignore rules."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GitIgnoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="starter-ignore-")
        self.root = Path(self.temporary.name)
        self.addCleanup(self.cleanup_fixture)
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        self.environment["GIT_CONFIG_NOSYSTEM"] = "1"
        self.environment["GIT_CONFIG_GLOBAL"] = os.devnull
        self.run_git("init", "--quiet")
        shutil.copyfile(REPOSITORY_ROOT / ".gitignore", self.root / ".gitignore")

    def cleanup_fixture(self):
        self.temporary.cleanup()
        self.assertFalse(self.root.exists(), f"fixture cleanup failed: {self.root}")

    def run_git(self, *arguments):
        return subprocess.run(
            ["git", "-c", f"core.excludesFile={os.devnull}", *arguments],
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_paths_ignored(self, paths, *, ignored):
        for relative_path in paths:
            with self.subTest(path=relative_path, ignored=ignored):
                path = self.root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("representative fixture\n", encoding="utf-8")
                tracked = self.run_git("ls-files", "--", relative_path)
                self.assertEqual(tracked.returncode, 0, tracked.stderr)
                self.assertEqual(tracked.stdout, "")
                result = self.run_git("check-ignore", "--quiet", "--", relative_path)
                diagnostic = ""
                if result.returncode != (0 if ignored else 1):
                    diagnostic = self.run_git(
                        "check-ignore", "--verbose", "--", relative_path
                    ).stdout
                self.assertEqual(
                    result.returncode,
                    0 if ignored else 1,
                    f"{relative_path}: {diagnostic}{result.stderr}",
                )

    def test_new_sources_fixtures_and_lockfiles_remain_trackable(self):
        self.assert_paths_ignored(
            (
                "src/log/logger.go",
                "build/build.sh",
                "tests/fixtures/expected.out",
                "tests/fixtures/archive.zip",
                "src/vendor/adapter.php",
                "scripts/build.sh",
                "scripts/Build.ps1",
                "src/parser.pl",
                "src/settings.py",
                "src/Main.java",
                "src/main.rs",
                "src/main.go",
                "laravel/app/Models/User.php",
                "laravel/tests/Feature/ExampleTest.php",
                "laravel/public/index.php",
                "src/index.js",
                "src/main.c",
                "src/main.cpp",
                "go.mod",
                "go.sum",
                "Cargo.lock",
                "composer.lock",
                "package-lock.json",
                "yarn.lock",
                "pnpm-lock.yaml",
                "laravel/composer.lock",
                "laravel/package-lock.json",
                "tests/fixtures/program.exe",
                "tests/fixtures/library.dll",
                "tests/fixtures/library.so",
                "tests/fixtures/certificate.pem",
                "tests/fixtures/private.key",
                "tests/fixtures/config.env",
                "tests/fixtures/.env",
                ".env.example",
                ".env.template",
                "tools/quality/custom.py",
                "tools/external/adapter.py",
                "src/tools/quality/external/adapter.py",
                "src/.venv/settings.py",
                "src/.tmp/template.txt",
                "dist/source.js",
                "target/source.rs",
                "vendor/adapter.php",
                "node_modules/fixture.js",
            ),
            ignored=False,
        )

    def test_case_variants_of_environment_sources_remain_trackable(self):
        for ignore_case in ("false", "true"):
            with self.subTest(ignore_case=ignore_case):
                result = self.run_git("config", "core.ignoreCase", ignore_case)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_paths_ignored(
                    ("env/settings.py", "ENV/settings.py", "Env/settings.py"),
                    ignored=False,
                )

    def test_shared_editor_configuration_remains_trackable(self):
        self.assert_paths_ignored(
            (
                ".idea/codeStyles/Project.xml",
                ".fleet/settings.json",
                ".zed/settings.json",
                ".vscode/custom.json",
                ".vscode/settings.json",
            ),
            ignored=False,
        )

    def test_known_root_local_outputs_and_secrets_are_ignored(self):
        self.assert_paths_ignored(
            (
                ".env",
                ".venv/pyvenv.cfg",
                ".tmp/package.zip",
                "tools/quality/node_modules/dependency/index.js",
                "tools/quality/external/bin/tool.exe",
            ),
            ignored=True,
        )

    def test_laravel_local_policy_owns_its_secrets_and_generated_outputs(self):
        self.assert_paths_ignored(("laravel/.env",), ignored=False)
        # A representative application policy, independent of the root policy.
        (self.root / "laravel" / ".gitignore").write_text(
            "/.env\n/vendor/\n/node_modules/\n/public/build/\n/storage/*.key\n",
            encoding="utf-8",
        )
        self.assert_paths_ignored(
            (
                "laravel/.env",
                "laravel/vendor/dependency/autoload.php",
                "laravel/node_modules/dependency/index.js",
                "laravel/public/build/assets/app.js",
                "laravel/storage/oauth-private.key",
            ),
            ignored=True,
        )
        self.assert_paths_ignored(
            (
                "laravel/.gitignore",
                "laravel/.env.example",
                "laravel/app/Models/User.php",
                "laravel/tests/fixtures/expected.out",
                "laravel/public/index.php",
                "laravel/composer.lock",
                "laravel/package-lock.json",
                "laravel/storage/app/.gitignore",
            ),
            ignored=False,
        )


if __name__ == "__main__":
    unittest.main()
