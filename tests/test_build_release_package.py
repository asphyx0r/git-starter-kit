from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SOURCE_ROOT / "tools" / "build-release-package.ps1"
BASE_COMMIT = "ee1d79e1c0516ced2a5171e65e14bc0fef762ce5"
ARCHIVE_PREPARATION = "Add-Type -AssemblyName System.IO.Compression.FileSystem"
POST_BUILD_VALIDATION = "if ($zipEntries -notcontains $requiredFile) {"
REPLACEMENT = """[System.IO.File]::Replace(
            $temporaryPackagePath,
            $packagePath,
            $temporaryBackupPath
        )"""
PACKAGE_FIXTURE_PATHS = (
    ".github/workflows/agent-rules-update.yml",
    "_agent-rules-source.json",
    "starter-kit-manifest.json",
    "AGENTS.md",
    "BRANCH_RULES.md",
    "CODING_RULES.md",
    "COMMIT_RULES.md",
    "DOCUMENTATION_RULES.md",
    "LANGUAGE_RULES.md",
    "RELEASE_RULES.md",
)


class BuildReleasePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_script = subprocess.run(
            [
                "git",
                "show",
                f"{BASE_COMMIT}:tools/build-release-package.ps1",
            ],
            cwd=SOURCE_ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout

    def run_package(
        self,
        script_path: Path,
        output_directory: Path,
        environment: dict[str, str] | None = None,
        repository_root: Path = SOURCE_ROOT,
        powershell_executable: str = "pwsh",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                powershell_executable,
                "-NoProfile",
                "-File",
                str(script_path),
                "-RepositoryRoot",
                str(repository_root),
                "-OutputDirectory",
                str(output_directory),
                "-PackageName",
                "existing.zip",
                "-RepositorySlug",
                "asphyx0r/git-starter-kit",
                "-RepositoryRef",
                "audit-remediation",
                "-AgentRulesRef",
                "v1.42.0",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    def create_package_repository(self, parent: Path) -> Path:
        repository_root = parent / "git-starter-kit"
        repository_root.mkdir()
        for relative_path in PACKAGE_FIXTURE_PATHS:
            destination = repository_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE_ROOT / relative_path, destination)
        future_module = repository_root / "tools" / "starter_kit_upgrade" / "future.py"
        future_module.parent.mkdir(parents=True)
        future_module.write_text("future = True\n", encoding="utf-8")
        subprocess.run(
            ["git", "init", "--quiet"],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "https://github.com/asphyx0r/git-starter-kit.git",
            ],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            ["git", "add", "--all"],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Package Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--quiet",
                "-m",
                "test: create package fixture",
            ],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
        )
        return repository_root

    def write_script(self, directory: Path, content: str) -> Path:
        script_path = directory / "build-release-package.ps1"
        script_path.write_text(content, encoding="utf-8", newline="\n")
        return script_path

    def assert_no_temporary_archive(self, directory: Path) -> None:
        self.assertEqual(list(directory.glob(".existing.*.zip.tmp")), [])
        self.assertEqual(list(directory.glob(".existing.*.zip.bak")), [])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_full_package_applies_source_only_and_merge_policy(self) -> None:
        upgrade_module_paths = {
            "tools/starter_kit_upgrade/__init__.py",
            "tools/starter_kit_upgrade/application.py",
            "tools/starter_kit_upgrade/archive.py",
            "tools/starter_kit_upgrade/cli.py",
            "tools/starter_kit_upgrade/common.py",
            "tools/starter_kit_upgrade/planning.py",
        }
        source_only_paths = {
            ".github/CODEOWNERS",
            "tests/test_build_release_package.py",
            *upgrade_module_paths,
        }
        actual_upgrade_module_paths = {
            path.relative_to(SOURCE_ROOT).as_posix()
            for path in (SOURCE_ROOT / "tools" / "starter_kit_upgrade").iterdir()
            if path.is_file()
        }
        self.assertEqual(actual_upgrade_module_paths, upgrade_module_paths)
        merge_path = ".github/dependabot.yml"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            alternate_index = temporary_path / "index"
            alternate_objects = temporary_path / "objects"
            alternate_objects.mkdir()
            git_index = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "index"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            git_objects = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "objects"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            if not git_index.is_absolute():
                git_index = SOURCE_ROOT / git_index
            if not git_objects.is_absolute():
                git_objects = SOURCE_ROOT / git_objects
            shutil.copyfile(git_index, alternate_index)
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(alternate_index)
            environment["GIT_OBJECT_DIRECTORY"] = str(alternate_objects)
            environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(git_objects)
            subprocess.run(
                [
                    "git",
                    "add",
                    "--",
                    ".github/CODEOWNERS",
                    ".github/dependabot.yml",
                    "tests/test_build_release_package.py",
                    "tools/starter_kit_upgrade",
                ],
                cwd=SOURCE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            result = self.run_package(
                SCRIPT_PATH,
                temporary_path,
                environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(temporary_path / "existing.zip") as archive:
                archive_names = set(archive.namelist())
                self.assertTrue(source_only_paths.isdisjoint(archive_names))
                self.assertFalse(
                    any(
                        path.startswith("tools/starter_kit_upgrade/")
                        for path in archive_names
                    )
                )
                self.assertIn(merge_path, archive_names)
                file_manifest = json.load(archive.open("_starter-kit-files.json"))
            strategies = {
                entry["path"]: entry["strategy"] for entry in file_manifest["files"]
            }
            self.assertEqual(strategies[merge_path], "merge")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_full_package_excludes_future_upgrade_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repository_root = self.create_package_repository(temporary_path)
            output_directory = temporary_path / "output"

            result = self.run_package(
                SCRIPT_PATH,
                output_directory,
                repository_root=repository_root,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output_directory / "existing.zip") as archive:
                self.assertNotIn(
                    "tools/starter_kit_upgrade/future.py",
                    archive.namelist(),
                )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_full_package_replaces_complete_audit_runtime(self) -> None:
        audit_paths = {"tools/repository-audit.sh"} | {
            f"tools/repository-audit/{name}"
            for name in (
                "agent-rules-transfer.sh",
                "common.sh",
                "contracts.sh",
                "hooks.sh",
                "profiles.sh",
                "security.sh",
                "smoke.sh",
            )
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            alternate_index = temporary_path / "index"
            alternate_objects = temporary_path / "objects"
            alternate_objects.mkdir()
            git_index = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "index"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            git_objects = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "objects"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            if not git_index.is_absolute():
                git_index = SOURCE_ROOT / git_index
            if not git_objects.is_absolute():
                git_objects = SOURCE_ROOT / git_objects
            shutil.copyfile(git_index, alternate_index)
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(alternate_index)
            environment["GIT_OBJECT_DIRECTORY"] = str(alternate_objects)
            environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(git_objects)
            subprocess.run(
                [
                    "git",
                    "add",
                    "--",
                    "tools/repository-audit",
                    "tests/test_agent_rules_transfer.sh",
                ],
                cwd=SOURCE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )

            result = self.run_package(SCRIPT_PATH, temporary_path, environment)

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(temporary_path / "existing.zip") as archive:
                self.assertTrue(audit_paths.issubset(archive.namelist()))
                file_manifest = json.load(archive.open("_starter-kit-files.json"))
            strategies = {
                entry["path"]: entry["strategy"] for entry in file_manifest["files"]
            }
            self.assertEqual(
                {path: strategies[path] for path in audit_paths},
                {path: "replace" for path in audit_paths},
            )
            self.assertEqual(
                strategies["tests/test_agent_rules_transfer.sh"],
                "replace",
            )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_full_package_replaces_quality_configuration(self) -> None:
        quality_paths = {
            "tools/quality/check-versions.py",
            "tools/quality/install-external-tools.py",
            "tools/quality/package-lock.json",
            "tools/quality/package.json",
            "tools/quality/PSScriptAnalyzerSettings.psd1",
            "tools/quality/pyproject.toml",
            "tools/quality/requirements.in",
            "tools/quality/requirements.lock",
            "tools/quality/versions.json",
            "tools/quality/yamllint.yaml",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            alternate_index = temporary_path / "index"
            alternate_objects = temporary_path / "objects"
            alternate_objects.mkdir()
            git_index = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "index"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            git_objects = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "objects"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            if not git_index.is_absolute():
                git_index = SOURCE_ROOT / git_index
            if not git_objects.is_absolute():
                git_objects = SOURCE_ROOT / git_objects
            shutil.copyfile(git_index, alternate_index)
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(alternate_index)
            environment["GIT_OBJECT_DIRECTORY"] = str(alternate_objects)
            environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(git_objects)
            subprocess.run(
                ["git", "add", "--", "tools/quality"],
                cwd=SOURCE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )

            result = self.run_package(SCRIPT_PATH, temporary_path, environment)

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(temporary_path / "existing.zip") as archive:
                self.assertEqual(
                    {
                        path
                        for path in archive.namelist()
                        if path.startswith("tools/quality/")
                    },
                    quality_paths,
                )
                file_manifest = json.load(archive.open("_starter-kit-files.json"))
            strategies = {
                entry["path"]: entry["strategy"] for entry in file_manifest["files"]
            }
            self.assertEqual(
                {path: strategies[path] for path in quality_paths},
                {path: "replace" for path in quality_paths},
            )
            self.assertEqual(
                {path for path in strategies if path.startswith("tools/quality/")},
                quality_paths,
            )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_base_archive_preparation_failure_deletes_existing_destination(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")
            base_script = self.write_script(
                temporary_path,
                self.base_script.replace(
                    ARCHIVE_PREPARATION,
                    'throw "simulated archive preparation failure"',
                    1,
                ),
            )

            result = self.run_package(base_script, temporary_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("simulated archive preparation failure", result.stderr)
            self.assertFalse(existing_archive.exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_archive_preparation_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")
            script_path = self.write_script(
                temporary_path,
                SCRIPT_PATH.read_text(encoding="utf-8").replace(
                    ARCHIVE_PREPARATION,
                    'throw "simulated archive preparation failure"',
                    1,
                ),
            )

            result = self.run_package(script_path, temporary_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("simulated archive preparation failure", result.stderr)
            self.assertEqual(existing_archive.read_bytes(), b"previous release package")
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_post_build_validation_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")
            script_content = SCRIPT_PATH.read_text(encoding="utf-8")
            self.assertIn(POST_BUILD_VALIDATION, script_content)
            script_path = self.write_script(
                temporary_path,
                script_content.replace(POST_BUILD_VALIDATION, "if ($true) {", 1),
            )

            result = self.run_package(script_path, temporary_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Release package archive is missing required file", result.stderr
            )
            self.assertEqual(existing_archive.read_bytes(), b"previous release package")
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_successful_build_replaces_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")

            result = self.run_package(SCRIPT_PATH, temporary_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(
                existing_archive.read_bytes(), b"previous release package"
            )
            with zipfile.ZipFile(existing_archive) as archive:
                self.assertIsNone(archive.testzip())
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is required.",
    )
    def test_successful_build_replaces_destination_with_windows_powershell_5_1(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")

            result = self.run_package(
                SCRIPT_PATH,
                temporary_path,
                powershell_executable="powershell.exe",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(
                existing_archive.read_bytes(), b"previous release package"
            )
            with zipfile.ZipFile(existing_archive) as archive:
                self.assertIsNone(archive.testzip())
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_successful_build_publishes_when_destination_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)

            result = self.run_package(SCRIPT_PATH, temporary_path)

            archive_path = temporary_path / "existing.zip"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_replacement_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")
            script_content = SCRIPT_PATH.read_text(encoding="utf-8")
            self.assertIn(REPLACEMENT, script_content)
            script_path = self.write_script(
                temporary_path,
                script_content.replace(
                    REPLACEMENT,
                    'throw "simulated replacement failure"',
                    1,
                ),
            )

            result = self.run_package(script_path, temporary_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("simulated replacement failure", result.stderr)
            self.assertEqual(existing_archive.read_bytes(), b"previous release package")
            self.assert_no_temporary_archive(temporary_path)


if __name__ == "__main__":
    unittest.main()
