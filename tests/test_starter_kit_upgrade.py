import argparse
import copy
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "starter-kit-upgrade.py"
SPEC = importlib.util.spec_from_file_location("starter_kit_upgrade", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
UPGRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADE)


def json_bytes(value):
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def provenance(starter_commit, agent_commit, starter_ref="v1.0.0"):
    return {
        "schemaVersion": 3,
        "generatedAt": "2026-07-30T00:00:00Z",
        "repository": {
            "name": "git-starter-kit",
            "slug": "example/git-starter-kit",
            "ref": starter_ref,
            "commit": starter_commit,
        },
        "starterKit": {
            "repository": "https://github.com/example/git-starter-kit",
            "ref": starter_ref,
            "commit": starter_commit,
        },
        "agentRules": {
            "repository": "https://github.com/example/agent-coding-rules",
            "ref": "v1.0.0",
            "commit": agent_commit,
        },
    }


def starter_manifest(ref):
    release = {
        "repository": "https://github.com/example/git-starter-kit",
        "ref": ref,
        "releaseUrl": (
            "https://github.com/example/git-starter-kit/releases/tag/" + ref
        ),
        "generatedAt": "2026-07-30T00:00:00Z",
    }
    return {
        "schemaVersion": 1,
        "source": release,
        "current": dict(release),
        "files": [],
    }


def cleanup_temporary_directory(temporary):
    for attempt in range(3):
        try:
            temporary.cleanup()
            return
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.1)


class StarterKitUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.base_package = self.root / "base.zip"
        self.new_package = self.root / "new.zip"
        self.upgrade_package = self.root / "upgrade.zip"
        self.backup_directory = self.root / "backups"
        self.backup_directory.mkdir()

        self.base_provenance = json_bytes(provenance("a" * 40, "b" * 40))
        self.new_provenance = json_bytes(provenance("c" * 40, "d" * 40, "v2.0.0"))
        self.base_files = {
            "_agent-rules-source.json": self.base_provenance,
            "AGENTS.md": b"base agents\n",
            "CODING_RULES.md": b"base coding rules\n",
            "COMMIT_RULES.md": b"base commit rules\n",
            "DOCUMENTATION_RULES.md": b"base documentation rules\n",
            "LANGUAGE_RULES.md": b"base language rules\n",
            "RELEASE_RULES.md": b"base release rules\n",
            "a.txt": b"base a\n",
            "merge.txt": (b"first base\nstable one\nstable two\nlast base\n"),
            "README.md": b"base readme\n",
            "removed.txt": b"preserve removed\n",
            "starter-kit-manifest.json": json_bytes(starter_manifest("v1.0.0")),
        }
        self.new_files = {
            "_agent-rules-source.json": self.new_provenance,
            "AGENTS.md": b"new agents\n",
            "BRANCH_RULES.md": b"new branch rules\n",
            "CODING_RULES.md": b"new coding rules\n",
            "COMMIT_RULES.md": b"new commit rules\n",
            "DOCUMENTATION_RULES.md": b"new documentation rules\n",
            "LANGUAGE_RULES.md": b"new language rules\n",
            "RELEASE_RULES.md": b"new release rules\n",
            "a.txt": b"new a\n",
            "merge.txt": (b"first new\nstable one\nstable two\nlast base\n"),
            "new.txt": b"new file\n",
            "README.md": b"new readme\n",
            "starter-kit-manifest.json": json_bytes(starter_manifest("v2.0.0")),
        }
        managed = []
        strategies = {
            "_agent-rules-source.json": "agent-rules",
            "AGENTS.md": "agent-rules",
            "BRANCH_RULES.md": "agent-rules",
            "CODING_RULES.md": "agent-rules",
            "COMMIT_RULES.md": "agent-rules",
            "DOCUMENTATION_RULES.md": "agent-rules",
            "LANGUAGE_RULES.md": "agent-rules",
            "RELEASE_RULES.md": "agent-rules",
            "a.txt": "replace",
            "merge.txt": "merge",
            "new.txt": "replace",
            "README.md": "initialize-only",
            "starter-kit-manifest.json": "starter-kit-state",
        }
        for path, content in sorted(self.new_files.items()):
            content_kind, canonical_digest = UPGRADE.content_metadata(content)
            managed.append(
                {
                    "path": path,
                    "sha256": UPGRADE.sha256_bytes(content),
                    "canonicalSha256": canonical_digest,
                    "contentKind": content_kind,
                    "mode": "100644",
                    "strategy": strategies[path],
                }
            )
        files_manifest = {
            "schemaVersion": 3,
            "starterKit": provenance("c" * 40, "d" * 40, "v2.0.0")["starterKit"],
            "agentRules": provenance("c" * 40, "d" * 40, "v2.0.0")["agentRules"],
            "files": managed,
        }
        self.new_files["_starter-kit-files.json"] = json_bytes(files_manifest)
        self.write_zip(self.base_package, self.base_files)
        self.write_zip(self.new_package, self.new_files)
        self.build_upgrade()

    def tearDown(self):
        cleanup_temporary_directory(self.temporary)

    def test_temporary_cleanup_retries_transient_error(self):
        temporary = mock.Mock()
        temporary.cleanup.side_effect = [OSError(145, "directory not empty"), None]

        with mock.patch("time.sleep") as sleep:
            cleanup_temporary_directory(temporary)

        self.assertEqual(temporary.cleanup.call_count, 2)
        sleep.assert_called_once_with(0.1)

    def test_temporary_cleanup_preserves_persistent_error(self):
        temporary = mock.Mock()
        error = OSError(145, "directory not empty")
        temporary.cleanup.side_effect = error

        with mock.patch("time.sleep"), self.assertRaises(OSError) as raised:
            cleanup_temporary_directory(temporary)

        self.assertIs(raised.exception, error)
        self.assertEqual(temporary.cleanup.call_count, 3)

    @staticmethod
    def write_zip(path, files):
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    def build_upgrade(self):
        arguments = argparse.Namespace(
            base_package=self.base_package,
            new_package=self.new_package,
            output=self.upgrade_package,
            dry_run=False,
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(UPGRADE.build_upgrade(arguments), 0)

    def create_target(self):
        target = self.root / "target"
        target.mkdir()
        for path, content in self.base_files.items():
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        self.run_git(target, "init")
        self.run_git(target, "config", "user.name", "Starter Upgrade Test")
        self.run_git(target, "config", "user.email", "test@example.com")
        self.run_git(target, "add", "--all")
        self.run_git(target, "commit", "-m", "test: create baseline")
        return target

    @staticmethod
    def run_git(target, *arguments):
        subprocess.run(
            ["git", "-C", str(target), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def load_plan(self, target):
        manifest, files = UPGRADE.load_upgrade(self.upgrade_package)
        return manifest, files, UPGRADE.evaluate_target(manifest, files, target)

    def run_main(self, arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        previous_directory = Path.cwd()
        try:
            os.chdir(self.root)
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = UPGRADE.main(arguments)
        finally:
            os.chdir(previous_directory)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def single_log(self):
        logs = list((self.root / "logs").glob("*.log"))
        self.assertEqual(len(logs), 1)
        return logs[0]

    def assert_timestamped_log(self, path):
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(
                line,
                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
                r"\[(INFO|WARNING|ERROR)\] \[[a-z-]+\] ",
            )
        return "\n".join(lines)

    def test_tool_version_is_0_3_1(self):
        self.assertEqual(UPGRADE.VERSION, "0.3.1")

    def test_facade_re_exports_the_exact_supported_public_surface(self):
        expected_names = [
            "ADOPTION_PATH",
            "BASE_PAYLOAD_PREFIX",
            "FILES_MANIFEST_PATH",
            "FileSnapshot",
            "LOG_DIRECTORY",
            "LOG_FILENAME_TIMESTAMP_FORMAT",
            "LOG_TIMESTAMP_FORMAT",
            "MAX_ARCHIVE_SIZE",
            "PAYLOAD_PREFIX",
            "PROVENANCE_PATH",
            "RunJournal",
            "SEMVER_TAG_PATTERN",
            "STARTER_MANIFEST_PATH",
            "TOOLKIT_MODULE_NAMES",
            "UPGRADE_MANIFEST_PATH",
            "UpgradeError",
            "VERSION",
            "apply_upgrade",
            "build_parser",
            "build_toolkit",
            "build_upgrade",
            "canonical_sha256",
            "canonicalize_text",
            "content_metadata",
            "create_rollback_archive",
            "evaluate_target",
            "exact_release_alignment",
            "load_json_bytes",
            "load_upgrade",
            "local_now",
            "log_archive_contents",
            "log_managed_entries",
            "main",
            "merge_text_payload",
            "normalized_starter_manifest",
            "operational_compliance",
            "os",
            "parse_starter_manifest",
            "plan_or_apply",
            "print_plan",
            "read_archive",
            "require_package_provenance",
            "require_planned_file_state",
            "restore_snapshot",
            "run_git",
            "sha256_bytes",
            "sha256_file",
            "snapshot_file",
            "starter_commit",
            "starter_manifest_action",
            "starter_release_from_provenance",
            "starter_release_tag",
            "target_adoption_is_current",
            "target_path",
            "time",
            "updated_agent_rules_provenance",
            "updated_starter_manifest",
            "validate_adoption",
            "validate_new_package",
            "validate_relative_path",
            "write_json",
            "write_payload",
        ]

        self.assertEqual(UPGRADE.__all__, expected_names)

    def test_facade_imports_from_an_unrelated_isolated_working_directory(self):
        program = f"""
import importlib.util
from pathlib import Path

script_path = Path({str(SCRIPT_PATH)!r})
spec = importlib.util.spec_from_file_location("isolated_upgrade", script_path)
assert spec is not None
assert spec.loader is not None
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)
print(upgrade.VERSION)
"""

        result = subprocess.run(
            ["python", "-I", "-c", program],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0.3.1\n")

    def test_facade_patches_do_not_mutate_implementation_dependencies(self):
        application_module = importlib.import_module(UPGRADE.write_payload.__module__)
        common_module = importlib.import_module(UPGRADE.local_now.__module__)
        implementation_writer = application_module.write_payload
        implementation_clock = common_module.local_now
        restored = self.root / "restored.txt"
        snapshot = UPGRADE.FileSnapshot(b"restored\n", 0o644)

        def facade_writer(path, content, mode):
            self.assertIs(application_module.write_payload, implementation_writer)
            implementation_writer(path, content, mode)

        fixed_time = datetime(2026, 8, 2, 12, 34, 56).astimezone()

        def facade_clock():
            self.assertIs(common_module.local_now, implementation_clock)
            return fixed_time

        with mock.patch.object(UPGRADE, "write_payload", side_effect=facade_writer):
            UPGRADE.restore_snapshot(restored, snapshot)
        with mock.patch.object(UPGRADE, "local_now", side_effect=facade_clock):
            journal = UPGRADE.RunJournal("plan", ["plan"])
            journal.write("INFO", "test", "clock")

        self.assertEqual(restored.read_bytes(), snapshot.content)

    def test_upgrade_package_exposes_responsibility_modules(self):
        module_contracts = {
            "common": ("RunJournal", "UpgradeError"),
            "archive": ("build_toolkit", "build_upgrade", "load_upgrade"),
            "planning": ("evaluate_target", "operational_compliance"),
            "application": ("apply_upgrade", "write_payload"),
            "cli": ("build_parser", "main"),
        }

        for module_name, public_names in module_contracts.items():
            module = importlib.import_module(f"tools.starter_kit_upgrade.{module_name}")
            for public_name in public_names:
                self.assertIn(public_name, module.__all__)

    def test_build_plan_and_apply_preserve_local_repository_files(self):
        local_provenance = json.loads(self.base_provenance)
        local_provenance["agentRules"]["ref"] = "v1.0.1-local"
        local_provenance["preservedFiles"] = [
            {"path": "AGENTS.md", "canonicalSha256": "f" * 64}
        ]
        local_provenance["localMetadata"] = {"owner": "repository"}
        original_provenance = self.base_files["_agent-rules-source.json"]
        self.base_files["_agent-rules-source.json"] = json_bytes(local_provenance)
        try:
            target = self.create_target()
        finally:
            self.base_files["_agent-rules-source.json"] = original_provenance
        manifest, files, plan = self.load_plan(target)

        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["provenance"], "base")
        actions = {entry["path"]: entry["action"] for entry in plan["actions"]}
        self.assertEqual(actions["a.txt"], "update")
        self.assertEqual(actions["merge.txt"], "update")
        self.assertEqual(actions["new.txt"], "add")
        self.assertEqual(actions["README.md"], "review-initialize-only")
        self.assertEqual(plan["summary"]["review-initialize-only"], 1)
        self.assertEqual(actions["BRANCH_RULES.md"], "delegate-agent-rules")
        self.assertEqual(actions["_agent-rules-source.json"], "update")
        self.assertIn("removed.txt", plan["obsoletePaths"])

        backup = UPGRADE.apply_upgrade(
            manifest, files, target, plan, self.backup_directory
        )

        self.assertTrue(backup.is_file())
        self.assertEqual((target / "a.txt").read_bytes(), b"new a\n")
        self.assertEqual(
            (target / "merge.txt").read_bytes(),
            b"first new\nstable one\nstable two\nlast base\n",
        )
        self.assertEqual((target / "new.txt").read_bytes(), b"new file\n")
        self.assertEqual((target / "README.md").read_bytes(), b"base readme\n")
        self.assertFalse((target / "BRANCH_RULES.md").exists())
        for rule_path in (
            "AGENTS.md",
            "CODING_RULES.md",
            "COMMIT_RULES.md",
            "DOCUMENTATION_RULES.md",
            "LANGUAGE_RULES.md",
            "RELEASE_RULES.md",
        ):
            self.assertEqual(
                (target / rule_path).read_bytes(), self.base_files[rule_path]
            )
        self.assertEqual((target / "removed.txt").read_bytes(), b"preserve removed\n")
        updated_provenance = json.loads(
            (target / "_agent-rules-source.json").read_text(encoding="utf-8")
        )
        new_provenance = json.loads(self.new_provenance)
        self.assertEqual(updated_provenance["repository"], new_provenance["repository"])
        self.assertEqual(updated_provenance["starterKit"], new_provenance["starterKit"])
        self.assertEqual(
            updated_provenance["agentRules"], local_provenance["agentRules"]
        )
        self.assertEqual(
            updated_provenance["generatedAt"], local_provenance["generatedAt"]
        )
        self.assertEqual(
            updated_provenance["preservedFiles"],
            local_provenance["preservedFiles"],
        )
        self.assertEqual(
            updated_provenance["localMetadata"], local_provenance["localMetadata"]
        )
        self.assertTrue((target / "_starter-kit-files.json").is_file())
        self.assertTrue((target / ".starter-kit-adoption.json").is_file())
        state = json.loads(
            (target / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["source"]["ref"], "v1.0.0")
        self.assertEqual(state["current"]["ref"], "v2.0.0")

    def test_toolkit_contains_upgrader_and_full_package(self):
        toolkit = self.root / "toolkit.zip"
        arguments = argparse.Namespace(
            new_package=self.new_package,
            output=toolkit,
            dry_run=False,
        )

        with redirect_stdout(io.StringIO()):
            self.assertEqual(UPGRADE.build_toolkit(arguments), 0)

        with zipfile.ZipFile(toolkit) as archive:
            self.assertIn("starter-kit-upgrade.py", archive.namelist())
            self.assertIn("process_runner.py", archive.namelist())
            self.assertIn("packages/new.zip", archive.namelist())
            self.assertIn("README.md", archive.namelist())
            self.assertEqual(
                {
                    name
                    for name in archive.namelist()
                    if name.startswith("starter_kit_upgrade/")
                },
                {
                    "starter_kit_upgrade/__init__.py",
                    "starter_kit_upgrade/application.py",
                    "starter_kit_upgrade/archive.py",
                    "starter_kit_upgrade/cli.py",
                    "starter_kit_upgrade/common.py",
                    "starter_kit_upgrade/planning.py",
                },
            )
            self.assertIn(
                "Every non-dry-run command writes a detailed execution journal",
                archive.read("README.md").decode("utf-8"),
            )

        extracted = self.root / "toolkit"
        with zipfile.ZipFile(toolkit) as archive:
            archive.extractall(extracted)
        result = subprocess.run(
            ["python", str(extracted / "starter-kit-upgrade.py"), "--version"],
            cwd=extracted,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "starter-kit-upgrade.py 0.3.1\n")
        result = subprocess.run(
            [
                "python",
                "-B",
                "-c",
                "from pathlib import Path; "
                "from starter_kit_upgrade.planning import run_git; "
                "result = run_git(Path.cwd(), '--version'); "
                "print(result.stdout, end=''); raise SystemExit(result.returncode)",
            ],
            cwd=extracted,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("git version "))

    def test_toolkit_matches_release_skill_inventory(self):
        reference_path = (
            SCRIPT_PATH.parents[1]
            / ".agents/skills/git-commit-push-tag/references"
            / "git-starter-kit-release-package.txt"
        )
        inventories = re.findall(
            r"```json\n(.*?)\n```",
            reference_path.read_text(encoding="utf-8"),
            flags=re.DOTALL,
        )
        self.assertEqual(len(inventories), 1, "Expected one toolkit inventory")
        expected_members = [
            name.replace("<tag>", "v2.0.0") for name in json.loads(inventories[0])
        ]
        package = self.root / "git-starter-kit-v2.0.0-with-agent-rules.zip"
        package.write_bytes(self.new_package.read_bytes())
        toolkit = self.root / "toolkit.zip"
        arguments = argparse.Namespace(
            new_package=package,
            output=toolkit,
            dry_run=False,
        )

        with redirect_stdout(io.StringIO()):
            self.assertEqual(UPGRADE.build_toolkit(arguments), 0)

        with zipfile.ZipFile(toolkit) as archive:
            self.assertCountEqual(archive.namelist(), expected_members)
            self.assertEqual(
                archive.read(f"packages/{package.name}"), package.read_bytes()
            )

    def test_modified_managed_file_is_a_conflict(self):
        target = self.create_target()
        (target / "merge.txt").write_text("local merge\n", encoding="utf-8")
        self.run_git(target, "add", "merge.txt")
        self.run_git(target, "commit", "-m", "test: customize managed file")

        _, _, plan = self.load_plan(target)

        action = next(item for item in plan["actions"] if item["path"] == "merge.txt")
        self.assertEqual(action["action"], "conflict-merge")
        self.assertFalse(plan["applicable"])

    def test_non_overlapping_merge_customization_is_preserved(self):
        target = self.create_target()
        (target / "merge.txt").write_text(
            "first base\nstable one\nstable two\nlast local\n",
            encoding="utf-8",
        )
        self.run_git(target, "add", "merge.txt")
        self.run_git(target, "commit", "-m", "test: customize merge file")
        manifest, files, plan = self.load_plan(target)

        action = next(item for item in plan["actions"] if item["path"] == "merge.txt")
        self.assertEqual(action["action"], "merge")
        self.assertTrue(plan["applicable"])

        UPGRADE.apply_upgrade(manifest, files, target, plan, self.backup_directory)

        self.assertEqual(
            (target / "merge.txt").read_text(encoding="utf-8"),
            "first new\nstable one\nstable two\nlast local\n",
        )

    def test_missing_managed_file_is_a_conflict(self):
        target = self.create_target()
        (target / "a.txt").unlink()
        self.run_git(target, "add", "--all")
        self.run_git(target, "commit", "-m", "test: remove managed file")

        _, _, plan = self.load_plan(target)

        action = next(item for item in plan["actions"] if item["path"] == "a.txt")
        self.assertEqual(action["action"], "conflict-missing")
        self.assertFalse(plan["applicable"])

    def test_modified_starter_manifest_current_release_is_a_conflict(self):
        target = self.create_target()
        path = target / "starter-kit-manifest.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["current"]["ref"] = "v9.9.9"
        value["current"]["releaseUrl"] = (
            "https://github.com/example/git-starter-kit/releases/tag/v9.9.9"
        )
        path.write_bytes(json_bytes(value))
        self.run_git(target, "add", "starter-kit-manifest.json")
        self.run_git(target, "commit", "-m", "test: modify starter state")

        _, _, plan = self.load_plan(target)

        action = next(
            item
            for item in plan["actions"]
            if item["path"] == "starter-kit-manifest.json"
        )
        self.assertEqual(action["action"], "conflict-modified")
        self.assertFalse(plan["applicable"])

    def test_modified_starter_manifest_source_release_is_a_conflict(self):
        target = self.create_target()
        path = target / "starter-kit-manifest.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["source"]["ref"] = "v0.9.0"
        value["source"]["releaseUrl"] = (
            "https://github.com/example/git-starter-kit/releases/tag/v0.9.0"
        )
        path.write_bytes(json_bytes(value))
        self.run_git(target, "add", "starter-kit-manifest.json")
        self.run_git(target, "commit", "-m", "test: modify starter source")

        _, _, plan = self.load_plan(target)

        action = next(
            item
            for item in plan["actions"]
            if item["path"] == "starter-kit-manifest.json"
        )
        self.assertEqual(action["action"], "conflict-modified")
        self.assertFalse(plan["applicable"])

    def test_legacy_package_adds_manifest_with_original_source(self):
        legacy_base = self.root / "legacy-base.zip"
        legacy_upgrade = self.root / "legacy-upgrade.zip"
        legacy_files = dict(self.base_files)
        legacy_files.pop("starter-kit-manifest.json")
        self.write_zip(legacy_base, legacy_files)
        arguments = argparse.Namespace(
            base_package=legacy_base,
            new_package=self.new_package,
            output=legacy_upgrade,
            dry_run=False,
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(UPGRADE.build_upgrade(arguments), 0)

        target = self.create_target()
        (target / "starter-kit-manifest.json").unlink()
        self.run_git(target, "add", "--all")
        self.run_git(target, "commit", "-m", "test: remove unavailable state")
        manifest, files = UPGRADE.load_upgrade(legacy_upgrade)
        plan = UPGRADE.evaluate_target(manifest, files, target)

        state_action = next(
            item
            for item in plan["actions"]
            if item["path"] == "starter-kit-manifest.json"
        )
        self.assertEqual(state_action["action"], "add")
        self.assertTrue(plan["applicable"])

        UPGRADE.apply_upgrade(manifest, files, target, plan, self.backup_directory)

        state = json.loads(
            (target / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["source"]["ref"], "v1.0.0")
        self.assertEqual(state["current"]["ref"], "v2.0.0")

    def test_successive_upgrades_preserve_source_and_advance_current(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        UPGRADE.apply_upgrade(manifest, files, target, plan, self.backup_directory)
        self.run_git(target, "add", "--all")
        self.run_git(target, "commit", "-m", "test: apply second release")

        third_package = self.root / "third.zip"
        second_upgrade = self.root / "second-upgrade.zip"
        third_files = dict(self.new_files)
        third_files["_agent-rules-source.json"] = json_bytes(
            provenance("e" * 40, "f" * 40, "v3.0.0")
        )
        third_files["a.txt"] = b"third a\n"
        third_files["starter-kit-manifest.json"] = json_bytes(
            starter_manifest("v3.0.0")
        )
        managed_manifest = json.loads(
            third_files["_starter-kit-files.json"].decode("utf-8")
        )
        managed_manifest["starterKit"] = provenance("e" * 40, "f" * 40, "v3.0.0")[
            "starterKit"
        ]
        managed_manifest["agentRules"] = provenance("e" * 40, "f" * 40, "v3.0.0")[
            "agentRules"
        ]
        for entry in managed_manifest["files"]:
            content = third_files[entry["path"]]
            content_kind, canonical_digest = UPGRADE.content_metadata(content)
            entry["sha256"] = UPGRADE.sha256_bytes(content)
            entry["canonicalSha256"] = canonical_digest
            entry["contentKind"] = content_kind
        third_files["_starter-kit-files.json"] = json_bytes(managed_manifest)
        self.write_zip(third_package, third_files)

        arguments = argparse.Namespace(
            base_package=self.new_package,
            new_package=third_package,
            output=second_upgrade,
            dry_run=False,
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(UPGRADE.build_upgrade(arguments), 0)
        second_manifest, second_files = UPGRADE.load_upgrade(second_upgrade)
        second_plan = UPGRADE.evaluate_target(second_manifest, second_files, target)

        state_action = next(
            item
            for item in second_plan["actions"]
            if item["path"] == "starter-kit-manifest.json"
        )
        self.assertEqual(state_action["action"], "update")
        self.assertTrue(second_plan["applicable"])
        second_backup_directory = self.root / "backups-2"
        second_backup_directory.mkdir()
        UPGRADE.apply_upgrade(
            second_manifest,
            second_files,
            target,
            second_plan,
            second_backup_directory,
        )

        state = json.loads(
            (target / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["source"]["ref"], "v1.0.0")
        self.assertEqual(state["current"]["ref"], "v3.0.0")
        adoption = json.loads(
            (target / ".starter-kit-adoption.json").read_text(encoding="utf-8")
        )
        self.assertEqual(adoption["starterKitSource"]["ref"], "v1.0.0")
        self.run_git(target, "add", "--all")
        self.run_git(target, "commit", "-m", "test: commit third release")

        post_plan = UPGRADE.evaluate_target(second_manifest, second_files, target)
        state_action = next(
            item
            for item in post_plan["actions"]
            if item["path"] == "starter-kit-manifest.json"
        )
        self.assertEqual(state_action["action"], "aligned")
        adoption_is_current = UPGRADE.target_adoption_is_current(
            second_manifest, target
        )
        self.assertTrue(adoption_is_current)
        self.assertEqual(
            UPGRADE.operational_compliance(post_plan, adoption_is_current),
            "COMPLIANT_WITH_FOLLOW_UP",
        )

    def test_current_adoption_rejects_unrelated_evidence_commit(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        UPGRADE.apply_upgrade(manifest, files, target, plan, self.backup_directory)
        unrelated_commit = subprocess.run(
            [
                "git",
                "-C",
                str(target),
                "commit-tree",
                "HEAD^{tree}",
                "-m",
                "unrelated evidence",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        adoption_path = target / ".starter-kit-adoption.json"
        adoption = json.loads(adoption_path.read_text(encoding="utf-8"))
        adoption["repositoryCommit"] = unrelated_commit
        adoption_path.write_bytes(json_bytes(adoption))

        self.assertFalse(UPGRADE.target_adoption_is_current(manifest, target))

    def test_invalid_provenance_blocks_application(self):
        target = self.create_target()
        (target / "_agent-rules-source.json").write_text("{}\n", encoding="utf-8")
        self.run_git(target, "add", "_agent-rules-source.json")
        self.run_git(target, "commit", "-m", "test: replace provenance")

        _, _, plan = self.load_plan(target)

        self.assertEqual(plan["provenance"], "invalid")
        self.assertFalse(plan["applicable"])

    def test_agent_rules_provenance_drift_does_not_hide_starter_baseline(self):
        target = self.create_target()
        changed = provenance("a" * 40, "e" * 40)
        changed["generatedAt"] = "2026-07-31T00:00:00Z"
        (target / "_agent-rules-source.json").write_bytes(
            json.dumps(changed, indent=2).replace("\n", "\r\n").encode("utf-8")
        )
        self.run_git(target, "add", "_agent-rules-source.json")
        self.run_git(target, "commit", "-m", "test: update agent rules")

        _, _, plan = self.load_plan(target)

        self.assertEqual(plan["provenance"], "base")
        self.assertTrue(plan["applicable"])

    def test_untracked_project_file_is_preserved_and_does_not_block(self):
        target = self.create_target()
        extra = target / "project-only.txt"
        extra.write_text("keep\n", encoding="utf-8")

        _, _, plan = self.load_plan(target)

        self.assertTrue(plan["clean"])
        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["preservedUntrackedPaths"], ["project-only.txt"])
        self.assertEqual(extra.read_text(encoding="utf-8"), "keep\n")

    def test_tracked_worktree_change_blocks_application(self):
        target = self.create_target()
        (target / "a.txt").write_text("dirty\n", encoding="utf-8")

        _, _, plan = self.load_plan(target)

        self.assertFalse(plan["clean"])
        self.assertFalse(plan["applicable"])

    def test_adoption_manifest_cannot_replace_invalid_agent_rules_provenance(self):
        target = self.create_target()
        baseline_commit = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (target / "_agent-rules-source.json").write_text("{}\n", encoding="utf-8")
        adoption = {
            "schemaVersion": 1,
            "baseArchiveSha256": UPGRADE.sha256_file(self.base_package),
            "starterKit": {"commit": "a" * 40},
            "repositoryCommit": baseline_commit,
        }
        (target / ".starter-kit-adoption.json").write_bytes(json_bytes(adoption))
        self.run_git(target, "add", "--all")
        self.run_git(target, "commit", "-m", "test: adopt starter baseline")

        _, _, plan = self.load_plan(target)

        self.assertEqual(plan["provenance"], "adopted")
        provenance_action = next(
            item
            for item in plan["actions"]
            if item["path"] == "_agent-rules-source.json"
        )
        self.assertEqual(provenance_action["action"], "conflict-modified")
        self.assertFalse(plan["applicable"])

    def test_text_line_endings_do_not_create_false_drift(self):
        target = self.create_target()
        (target / "a.txt").write_bytes(b"base a\r\n\r\n")
        self.run_git(target, "add", "a.txt")
        self.run_git(target, "commit", "-m", "test: use Windows line endings")

        _, _, plan = self.load_plan(target)

        action = next(item for item in plan["actions"] if item["path"] == "a.txt")
        self.assertEqual(action["action"], "update")
        self.assertTrue(plan["applicable"])

    def test_archive_path_traversal_is_rejected(self):
        malicious = self.root / "malicious.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../outside.txt", b"unsafe")

        with self.assertRaises(UPGRADE.UpgradeError):
            UPGRADE.read_archive(malicious)

    def test_unsafe_portable_paths_are_rejected(self):
        for path in (
            "D:/x",
            "D:x",
            "safe/D:/x",
            ".git/config",
            "safe/.GiT/config",
            "x:stream",
            "CON.txt",
            "aux",
            "COM1",
            "LPT9.log",
            "COM¹.txt",
            "a./b",
            "a /b",
            "a\x01b",
            "a\x7fb",
            "a//b",
            "./a",
            "/a",
            "a/../b",
            "a\\b",
            "a?b",
            "a*b",
            42,
            None,
        ):
            with self.subTest(path=path), self.assertRaises(UPGRADE.UpgradeError):
                UPGRADE.validate_relative_path(path)
        self.assertEqual(
            UPGRADE.validate_relative_path("données/my file.txt"),
            "données/my file.txt",
        )

    def test_reserved_device_stems_with_spaces_are_rejected(self):
        for path in (
            "CON .txt",
            "NUL .log",
            "COM1 .txt",
            "LPT1 .foo",
            "nested/aux  .txt",
        ):
            with self.subTest(path=path), self.assertRaises(UPGRADE.UpgradeError):
                UPGRADE.validate_relative_path(path)
        for path in ("data file.txt", "config .txt", "nested/my document.txt"):
            with self.subTest(path=path):
                self.assertEqual(UPGRADE.validate_relative_path(path), path)

    def test_state_manifest_rejects_malformed_release_records(self):
        valid = starter_manifest("v1.0.0")
        self.assertEqual(
            UPGRADE.parse_starter_manifest(json_bytes(valid), "state"), valid
        )
        invalid_values = [[], {**valid, "schemaVersion": 2}, {**valid, "files": {}}]
        for release_name in ("source", "current"):
            invalid_values.append({**valid, release_name: None})
            for field in ("repository", "ref", "releaseUrl", "generatedAt"):
                invalid_values.append(
                    {**valid, release_name: {**valid[release_name], field: ""}}
                )
            invalid_values.append(
                {
                    **valid,
                    release_name: {
                        **valid[release_name],
                        "releaseUrl": "https://github.com/example/foreign/releases/tag/v1.0.0",
                    },
                }
            )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(UPGRADE.UpgradeError):
                UPGRADE.parse_starter_manifest(json_bytes(value), "state")

    def test_untrusted_adoption_is_not_evidence_of_a_known_release(self):
        target = self.create_target()
        manifest, _ = UPGRADE.load_upgrade(self.upgrade_package)
        adoption_path = target / UPGRADE.ADOPTION_PATH
        commit = subprocess.check_output(
            ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
        ).strip()
        valid = {
            "schemaVersion": 2,
            "starterKit": manifest["base"]["provenance"]["starterKit"],
            "baseArchiveSha256": manifest["base"]["archiveSha256"],
            "repositoryCommit": commit,
        }
        adoption_path.write_bytes(json_bytes(valid))
        self.assertEqual(
            UPGRADE.validate_adoption(target, manifest, adoption_path), valid
        )
        for fields in (
            {"schemaVersion": 3},
            {"starterKit": None},
            {"baseArchiveSha256": "0" * 64},
            {"starterKit": {"commit": "0" * 40}},
            {"repositoryCommit": ""},
            {"repositoryCommit": None},
        ):
            with self.subTest(fields=fields):
                adoption_path.write_bytes(json_bytes({**valid, **fields}))
                self.assertIsNone(
                    UPGRADE.validate_adoption(target, manifest, adoption_path)
                )

    def test_ambiguous_local_state_is_preserved_as_a_conflict(self):
        old = starter_manifest("v1.0.0")
        new = starter_manifest("v2.0.0")
        foreign = copy.deepcopy(old)
        foreign["source"]["repository"] = "https://github.com/example/foreign"
        foreign["source"]["releaseUrl"] = (
            "https://github.com/example/foreign/releases/tag/v1.0.0"
        )
        cases = (
            (json_bytes(foreign), json_bytes(old)),
            (json_bytes(old), b"invalid JSON"),
            (json_bytes(old), None),
        )
        for local_content, base_content in cases:
            with self.subTest(local=local_content, base=base_content):
                self.assertEqual(
                    UPGRADE.starter_manifest_action(
                        local_content, base_content, json_bytes(new), None
                    ),
                    "conflict-modified",
                )

    def test_archive_rejects_canonical_duplicates_and_special_members(self):
        for index, names in enumerate((("A.txt", "a.txt"), ("a/", "A/"), ("a/", "a"))):
            with self.subTest(names=names):
                unsafe = self.root / f"duplicate-{index}.zip"
                self.write_zip(unsafe, dict.fromkeys(names, b""))
                with self.assertRaises(UPGRADE.UpgradeError):
                    UPGRADE.read_archive(unsafe)
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK):
            with self.subTest(kind=kind):
                member = zipfile.ZipInfo("special")
                member.create_system = 3
                member.external_attr = (kind | 0o644) << 16
                unsafe = self.root / f"special-{kind}.zip"
                with zipfile.ZipFile(unsafe, "w") as archive:
                    archive.writestr(member, b"outside")
                with self.assertRaises(UPGRADE.UpgradeError):
                    UPGRADE.read_archive(unsafe)

    def test_archive_member_limit_counts_empty_directories_before_content(self):
        path = self.root / "many.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for index in range(10000):
                archive.writestr(f"directory-{index}/", b"")
        self.assertEqual(UPGRADE.read_archive(path), {})
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("extra.txt", b"")
        with (
            mock.patch.object(
                zipfile.ZipFile,
                "read",
                side_effect=AssertionError(
                    "Member content must not be read before count validation"
                ),
            ),
            self.assertRaises(UPGRADE.UpgradeError),
        ):
            UPGRADE.read_archive(path)

    def test_archive_rejects_nul_member_name_and_file_parent_collision(self):
        nul_path = self.root / "nul.zip"
        self.write_zip(nul_path, {"badXname": b"content"})
        nul_path.write_bytes(nul_path.read_bytes().replace(b"badXname", b"bad\0name"))
        with self.assertRaises(UPGRADE.UpgradeError):
            UPGRADE.read_archive(nul_path)
        conflict = self.root / "parent-conflict.zip"
        self.write_zip(conflict, {"Parent": b"file", "parent/child": b"child"})
        with self.assertRaises(UPGRADE.UpgradeError):
            UPGRADE.read_archive(conflict)

    def test_upgrade_manifest_rejects_invalid_consumed_fields(self):
        original, files = UPGRADE.load_upgrade(self.upgrade_package)
        invalid_entries = (
            ("path", 42),
            ("strategy", "invalid"),
            ("mode", 100644),
            ("mode", "120000"),
            ("contentKind", []),
            ("baseSha256", "invalid"),
            ("baseCanonicalSha256", "0" * 64),
            ("strategy", "starter-kit-state"),
        )
        for index, (field, value) in enumerate(invalid_entries):
            with self.subTest(field=field, value=value):
                manifest = copy.deepcopy(original)
                entry = next(e for e in manifest["entries"] if e["path"] == "merge.txt")
                entry[field] = value
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"invalid-entry-{index}.zip"
                self.write_zip(invalid, files)
                with self.assertRaises(UPGRADE.UpgradeError):
                    UPGRADE.load_upgrade(invalid)
        for index, (field, value) in enumerate(
            (
                ("base", None),
                ("target", {}),
                ("schemaVersion", True),
                ("schemaVersion", []),
                ("obsoletePaths", "removed.txt"),
            )
        ):
            with self.subTest(field=field):
                manifest = copy.deepcopy(original)
                manifest[field] = value
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"invalid-manifest-{index}.zip"
                self.write_zip(invalid, files)
                with self.assertRaises(UPGRADE.UpgradeError):
                    UPGRADE.load_upgrade(invalid)

    def test_upgrade_requires_an_object_catalogue_and_object_entries(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        cases = (
            (None, "Upgrade package is missing upgrade-manifest.json."),
            ([], "upgrade-manifest.json must contain a JSON object."),
            ({**original, "entries": {}}, "Unsupported upgrade package schema."),
            (
                {**original, "entries": ["merge.txt"]},
                "Upgrade entries must be JSON objects.",
            ),
            (
                {**original, "obsoletePaths": ["removed.txt", "REMOVED.txt"]},
                "Duplicate obsolete path.",
            ),
        )
        for index, (manifest, diagnostic) in enumerate(cases):
            with self.subTest(diagnostic=diagnostic):
                files = dict(original_files)
                if manifest is None:
                    files.pop(UPGRADE.UPGRADE_MANIFEST_PATH)
                else:
                    files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"invalid-catalogue-{index}.zip"
                self.write_zip(invalid, files)
                with self.assertRaisesRegex(
                    UPGRADE.UpgradeError, re.escape(diagnostic)
                ):
                    UPGRADE.load_upgrade(invalid)

    def test_upgrade_rejects_missing_misdirected_and_tampered_new_payloads(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        for defect in ("missing", "misdirected", "tampered"):
            with self.subTest(defect=defect):
                manifest = copy.deepcopy(original)
                files = dict(original_files)
                entry = next(e for e in manifest["entries"] if e["path"] == "merge.txt")
                if defect == "missing":
                    files.pop(entry["payload"])
                elif defect == "misdirected":
                    entry["payload"] = UPGRADE.PAYLOAD_PREFIX + "a.txt"
                else:
                    files[entry["payload"]] = b"unauthorized replacement\n"
                diagnostic = (
                    "Upgrade payload digest mismatch: merge.txt"
                    if defect == "tampered"
                    else "Missing upgrade payload for merge.txt."
                )
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"invalid-new-payload-{defect}.zip"
                self.write_zip(invalid, files)
                with self.assertRaisesRegex(
                    UPGRADE.UpgradeError, re.escape(diagnostic)
                ):
                    UPGRADE.load_upgrade(invalid)

    def test_upgrade_requires_consistent_base_digest_presence(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        for field in ("baseSha256", "baseCanonicalSha256"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(original)
                entry = next(e for e in manifest["entries"] if e["path"] == "merge.txt")
                entry[field] = None
                files = dict(original_files)
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"inconsistent-{field}.zip"
                self.write_zip(invalid, files)
                with self.assertRaisesRegex(
                    UPGRADE.UpgradeError, r"Inconsistent base digests: merge\.txt"
                ):
                    UPGRADE.load_upgrade(invalid)

    def test_upgrade_requires_authentic_decodable_merge_base_payloads(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        cases = (
            ("undeclared", "Missing base payload for merge.txt."),
            ("misdirected", "Missing base payload for merge.txt."),
            ("missing", "Missing base payload for merge.txt."),
            ("tampered", "Base payload digest mismatch: merge.txt"),
            ("non-text", "Invalid base text payload: merge.txt"),
        )
        for defect, diagnostic in cases:
            with self.subTest(defect=defect):
                manifest = copy.deepcopy(original)
                files = dict(original_files)
                entry = next(e for e in manifest["entries"] if e["path"] == "merge.txt")
                if defect == "undeclared":
                    entry["basePayload"] = None
                elif defect == "misdirected":
                    entry["basePayload"] = entry["payload"]
                elif defect == "missing":
                    files.pop(entry["basePayload"])
                elif defect == "tampered":
                    files[entry["basePayload"]] = b"unauthorized baseline\n"
                elif defect == "non-text":
                    files[entry["basePayload"]] = b"\xff\xfe"
                    entry["baseSha256"] = UPGRADE.sha256_bytes(b"\xff\xfe")
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"invalid-base-payload-{defect}.zip"
                self.write_zip(invalid, files)
                with self.assertRaisesRegex(
                    UPGRADE.UpgradeError, re.escape(diagnostic)
                ):
                    UPGRADE.load_upgrade(invalid)

    def test_upgrade_requires_target_provenance_payload_and_inventory_entry(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        for retain_payload in (False, True):
            with self.subTest(retain_payload=retain_payload):
                manifest = copy.deepcopy(original)
                manifest["entries"] = [
                    e
                    for e in manifest["entries"]
                    if e["path"] != UPGRADE.PROVENANCE_PATH
                ]
                files = dict(original_files)
                if not retain_payload:
                    files.pop(UPGRADE.PAYLOAD_PREFIX + UPGRADE.PROVENANCE_PATH)
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"unattested-provenance-{retain_payload}.zip"
                self.write_zip(invalid, files)
                with self.assertRaisesRegex(
                    UPGRADE.UpgradeError,
                    r"Upgrade package is missing its target provenance payload\.",
                ):
                    UPGRADE.load_upgrade(invalid)

    def test_upgrade_binds_target_release_metadata_to_provenance_payload(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        for defect in ("digest", "identity"):
            with self.subTest(defect=defect):
                manifest = copy.deepcopy(original)
                if defect == "digest":
                    manifest["target"]["provenanceSha256"] = "0" * 64
                else:
                    manifest["target"]["provenance"]["agentRules"]["commit"] = "e" * 40
                files = dict(original_files)
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"mismatched-provenance-{defect}.zip"
                self.write_zip(invalid, files)
                with self.assertRaisesRegex(
                    UPGRADE.UpgradeError,
                    r"Target provenance payload does not match release metadata\.",
                ):
                    UPGRADE.load_upgrade(invalid)

    def test_upgrade_manifest_rejects_duplicate_target_paths(self):
        manifest, files = UPGRADE.load_upgrade(self.upgrade_package)
        duplicate = dict(next(e for e in manifest["entries"] if e["path"] == "a.txt"))
        duplicate["path"] = "A.txt"
        manifest["entries"].append(duplicate)
        files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
        self.write_zip(self.root / "invalid.zip", files)
        with self.assertRaises(UPGRADE.UpgradeError):
            UPGRADE.load_upgrade(self.root / "invalid.zip")

    def test_plan_rejects_duplicate_canonical_destinations(self):
        target = self.create_target()
        manifest, files = UPGRADE.load_upgrade(self.upgrade_package)
        duplicate = dict(next(e for e in manifest["entries"] if e["path"] == "a.txt"))
        duplicate["path"] = "A.txt"
        manifest["entries"].append(duplicate)
        with self.assertRaises(UPGRADE.UpgradeError):
            UPGRADE.evaluate_target(manifest, files, target)

    def test_historical_upgrade_schemas_remain_readable(self):
        original, files = UPGRADE.load_upgrade(self.upgrade_package)
        target = self.create_target()
        for version in (1, 2):
            with self.subTest(version=version):
                manifest = copy.deepcopy(original)
                manifest["schemaVersion"] = version
                manifest["entries"] = [
                    e
                    for e in manifest["entries"]
                    if e["strategy"] != "starter-kit-state"
                ]
                if version == 1:
                    for entry in manifest["entries"]:
                        for field in (
                            "contentKind",
                            "baseCanonicalSha256",
                            "newCanonicalSha256",
                            "basePayload",
                        ):
                            entry.pop(field)
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                legacy = self.root / f"legacy-{version}.zip"
                self.write_zip(legacy, files)
                loaded, payloads = UPGRADE.load_upgrade(legacy)
                self.assertEqual(loaded["schemaVersion"], version)
                self.assertTrue(
                    UPGRADE.evaluate_target(loaded, payloads, target)["applicable"]
                )

    def test_upgrade_rejects_invalid_provenance_and_state_payload_before_plan(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        for index, (relative, replacement) in enumerate(
            (
                (
                    UPGRADE.PROVENANCE_PATH,
                    {**provenance("c" * 40, "d" * 40, "v2.0.0"), "repository": []},
                ),
                (UPGRADE.STARTER_MANIFEST_PATH, {"schemaVersion": 1}),
            )
        ):
            with self.subTest(relative=relative):
                manifest = copy.deepcopy(original)
                files = dict(original_files)
                entry = next(e for e in manifest["entries"] if e["path"] == relative)
                content = json_bytes(replacement)
                files[entry["payload"]] = content
                entry["newSha256"] = UPGRADE.sha256_bytes(content)
                entry["newCanonicalSha256"] = UPGRADE.content_metadata(content)[1]
                if relative == UPGRADE.PROVENANCE_PATH:
                    manifest["target"]["provenance"] = replacement
                    manifest["target"]["provenanceSha256"] = entry["newSha256"]
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"invalid-payload-{index}.zip"
                self.write_zip(invalid, files)
                with self.assertRaises(UPGRADE.UpgradeError):
                    UPGRADE.load_upgrade(invalid)

    def test_state_upgrade_rejects_incomplete_base_provenance_during_load(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        for field in ("generatedAt", "repository"):
            for index, value in enumerate((None, "", [], 42)):
                with self.subTest(field=field, value=value):
                    manifest = copy.deepcopy(original)
                    provenance = manifest["base"]["provenance"]
                    owner = (
                        provenance
                        if field == "generatedAt"
                        else provenance["starterKit"]
                    )
                    if value is None:
                        owner.pop(field)
                    else:
                        owner[field] = value
                    state = next(
                        e
                        for e in manifest["entries"]
                        if e["strategy"] == "starter-kit-state"
                    )
                    state["basePayload"] = None
                    state["baseSha256"] = None
                    state["baseCanonicalSha256"] = None
                    files = dict(original_files)
                    files.pop(
                        UPGRADE.BASE_PAYLOAD_PREFIX + UPGRADE.STARTER_MANIFEST_PATH
                    )
                    files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                    invalid = self.root / f"incomplete-state-{field}-{index}.zip"
                    self.write_zip(invalid, files)
                    with self.assertRaises(UPGRADE.UpgradeError):
                        UPGRADE.load_upgrade(invalid)
                    self.assertEqual(list(self.backup_directory.iterdir()), [])

    def test_legacy_upgrade_does_not_require_state_provenance_fields(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        for schema in (1, 2):
            with self.subTest(schema=schema):
                manifest = copy.deepcopy(original)
                manifest["schemaVersion"] = schema
                manifest["entries"] = [
                    e
                    for e in manifest["entries"]
                    if e["strategy"] != "starter-kit-state"
                ]
                manifest["base"]["provenance"].pop("generatedAt")
                manifest["base"]["provenance"]["starterKit"].pop("repository")
                if schema == 1:
                    for entry in manifest["entries"]:
                        for field in (
                            "contentKind",
                            "baseCanonicalSha256",
                            "newCanonicalSha256",
                            "basePayload",
                        ):
                            entry.pop(field)
                files = dict(original_files)
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                legacy = self.root / f"legacy-provenance-{schema}.zip"
                self.write_zip(legacy, files)
                loaded, _ = UPGRADE.load_upgrade(legacy)
                self.assertEqual(loaded["schemaVersion"], schema)

    def test_upgrade_requires_historical_entry_fields_and_provenance_digests(self):
        original, original_files = UPGRADE.load_upgrade(self.upgrade_package)
        entry_fields = (
            "strategy",
            "mode",
            "baseSha256",
            "baseCanonicalSha256",
            "newCanonicalSha256",
            "basePayload",
        )
        for field in entry_fields:
            with self.subTest(field=field):
                manifest = copy.deepcopy(original)
                manifest["entries"][0].pop(field)
                files = dict(original_files)
                files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                invalid = self.root / f"missing-{field}.zip"
                self.write_zip(invalid, files)
                with self.assertRaises(UPGRADE.UpgradeError):
                    UPGRADE.load_upgrade(invalid)
        for label in ("base", "target"):
            for field in ("archiveSha256", "provenanceSha256", "provenance"):
                with self.subTest(label=label, field=field):
                    manifest = copy.deepcopy(original)
                    manifest[label].pop(field)
                    files = dict(original_files)
                    files[UPGRADE.UPGRADE_MANIFEST_PATH] = json_bytes(manifest)
                    invalid = self.root / f"missing-{label}-{field}.zip"
                    self.write_zip(invalid, files)
                    with self.assertRaises(UPGRADE.UpgradeError):
                        UPGRADE.load_upgrade(invalid)

    def test_interruption_after_adoption_write_restores_all_originals(self):
        application = importlib.import_module("starter_kit_upgrade.application")
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        adoption_path = target / UPGRADE.ADOPTION_PATH
        adoption_path.write_bytes(b'{"original": true}\n')
        if os.name != "nt":
            (target / "a.txt").chmod(0o751)
            adoption_path.chmod(0o600)
        before = {
            p: UPGRADE.snapshot_file(target / p)
            for p in (*self.base_files, UPGRADE.ADOPTION_PATH)
        }
        for exception_type in (RuntimeError, KeyboardInterrupt):
            with self.subTest(exception_type=exception_type):
                error = exception_type("interrupted after adoption replacement")
                interrupted = False

                def interrupt_write(path, content, mode, error=error):
                    nonlocal interrupted
                    UPGRADE.write_payload(path, content, mode)
                    if path == adoption_path and not interrupted:
                        interrupted = True
                        raise error

                with self.assertRaises(exception_type) as raised:
                    application.apply_upgrade(
                        manifest,
                        files,
                        target,
                        plan,
                        self.backup_directory,
                        payload_writer=interrupt_write,
                    )
                self.assertIs(raised.exception, error)
                for relative, snapshot in before.items():
                    self.assertEqual(UPGRADE.snapshot_file(target / relative), snapshot)
                self.assertFalse((target / "new.txt").exists())
                self.assertFalse((target / UPGRADE.FILES_MANIFEST_PATH).exists())
                backups = list(self.backup_directory.glob("*.zip"))
                self.assertEqual(len(backups), 1)
                backups[0].unlink()

    def test_failed_restoration_attempts_remaining_files_and_reports_paths(self):
        application = importlib.import_module("starter_kit_upgrade.application")
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        error = KeyboardInterrupt("interrupted replacement")
        interrupted = False

        def failing_writer(path, content, mode):
            nonlocal interrupted
            if interrupted and path.name == "a.txt":
                raise OSError("restoration denied")
            UPGRADE.write_payload(path, content, mode)
            if path.name == "merge.txt" and not interrupted:
                interrupted = True
                raise error

        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(KeyboardInterrupt) as raised:
            application.apply_upgrade(
                manifest,
                files,
                target,
                plan,
                self.backup_directory,
                payload_writer=failing_writer,
            )
        self.assertIs(raised.exception, error)
        self.assertEqual(
            (target / "merge.txt").read_bytes(), self.base_files["merge.txt"]
        )
        self.assertEqual(
            (target / UPGRADE.PROVENANCE_PATH).read_bytes(), self.base_provenance
        )
        self.assertFalse((target / UPGRADE.FILES_MANIFEST_PATH).exists())
        self.assertIn("a.txt", stderr.getvalue())
        self.assertIn("restoration denied", stderr.getvalue())
        self.assertEqual(len(list(self.backup_directory.glob("*.zip"))), 1)

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_target_rejects_existing_junction_before_reading(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "private.txt").write_bytes(b"unchanged")
        target = self.root / "junction-target"
        target.mkdir()
        junction = target / "linked"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            check=True,
        )
        try:
            with self.assertRaises(UPGRADE.UpgradeError):
                UPGRADE.target_path(target, "linked/private.txt")
            with self.assertRaises(UPGRADE.UpgradeError):
                UPGRADE.target_path(target, "linked")
        finally:
            junction.rmdir()
        self.assertEqual((outside / "private.txt").read_bytes(), b"unchanged")

    def test_final_non_compliance_fails_without_reverting_concurrent_content(self):
        target = self.create_target()
        real_write = UPGRADE.write_payload

        def concurrent_change_after_adoption(path, content, mode):
            real_write(path, content, mode)
            if path.name == UPGRADE.ADOPTION_PATH:
                (target / "a.txt").write_bytes(b"concurrent content\n")

        with mock.patch.object(
            UPGRADE, "write_payload", side_effect=concurrent_change_after_adoption
        ):
            code, _, _ = self.run_main(
                [
                    "apply",
                    "--upgrade-package",
                    str(self.upgrade_package),
                    "--target",
                    str(target),
                    "--backup-directory",
                    str(self.backup_directory),
                ]
            )
        self.assertNotEqual(code, 0)
        self.assertEqual((target / "a.txt").read_bytes(), b"concurrent content\n")
        log = next((self.root / "logs").glob("*.log")).read_text(encoding="utf-8")
        self.assertIn("UPDATE_STATUS=FAILED", log)
        self.assertIn("OPERATIONAL_COMPLIANCE=NON_COMPLIANT", log)

    def test_git_timeout_is_bounded_and_merge_cleans_temporary_files(self):
        planning = importlib.import_module("starter_kit_upgrade.planning")
        observed = []

        def timeout(command, **kwargs):
            observed.append((command, kwargs.get("timeout")))
            raise subprocess.TimeoutExpired(
                command, kwargs.get("timeout"), stderr=b"slow" * 1000
            )

        with mock.patch.object(planning.process_runner, "run", side_effect=timeout):
            with self.assertRaises(UPGRADE.UpgradeError) as raised:
                planning.run_git(self.root, "rev-parse", "HEAD")
            self.assertLess(len(str(raised.exception)), 1200)
            self.assertEqual(observed[-1][1], 30)
            with self.assertRaises(UPGRADE.UpgradeError):
                planning.run_git(self.root, "status", "--porcelain=v1")
            self.assertEqual(observed[-1][1], 300)
            with self.assertRaises(UPGRADE.UpgradeError):
                planning.merge_text_payload(b"local\n", b"base\n", b"new\n")
            command, limit = observed[-1]
            self.assertEqual(limit, 300)
            self.assertFalse(Path(command[-1]).parent.exists())

    def test_git_and_merge_deadlines_contain_started_descendants(self):
        planning = importlib.import_module("starter_kit_upgrade.planning")
        marker = self.root / "descendant.pid"
        descendant = (
            "import os,pathlib,time; "
            f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
            "time.sleep(6)"
        )
        parent = (
            "import pathlib,subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-B','-c',{descendant!r}]); "
            f"marker=pathlib.Path({str(marker)!r}); "
            "exec('while not marker.exists(): time.sleep(0.01)')"
        )
        native_popen = subprocess.Popen
        real_run = planning.process_runner.run
        commands = []

        def bounded_run(command, **options):
            commands.append(command)
            options["timeout"] = 3
            return real_run(command, **options)

        for operation in (
            lambda: planning.run_git(self.root, "rev-parse", "HEAD"),
            lambda: planning.merge_text_payload(b"local\n", b"base\n", b"new\n"),
        ):
            marker.unlink(missing_ok=True)
            started = time.monotonic()
            with (
                mock.patch.object(planning.process_runner, "run", bounded_run),
                mock.patch.object(
                    subprocess,
                    "Popen",
                    side_effect=lambda *args, **kwargs: native_popen(
                        [sys.executable, "-B", "-c", parent], **kwargs
                    ),
                ),
                self.assertRaisesRegex(UPGRADE.UpgradeError, "timed out"),
            ):
                operation()
            self.assertTrue(marker.is_file())
            self.assertLess(time.monotonic() - started, 4)
        self.assertFalse(Path(commands[-1][-1]).parent.exists())

    def test_rollback_continues_when_the_journal_fails(self):
        application = importlib.import_module("starter_kit_upgrade.application")
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)

        class FailingJournal(UPGRADE.RunJournal):
            def write(self, level, phase, message):
                if getattr(self, "broken", False):
                    raise OSError("journal unavailable")
                super().write(level, phase, message)

        journal = FailingJournal("apply", [])

        def fail_after_replace(path, content, mode):
            UPGRADE.write_payload(path, content, mode)
            if path.name == "a.txt":
                journal.broken = True

        with redirect_stderr(io.StringIO()), self.assertRaises(OSError):
            application.apply_upgrade(
                manifest,
                files,
                target,
                plan,
                self.backup_directory,
                journal,
                payload_writer=fail_after_replace,
            )
        self.assertEqual((target / "a.txt").read_bytes(), self.base_files["a.txt"])
        self.assertFalse((target / UPGRADE.FILES_MANIFEST_PATH).exists())

    def test_failed_write_restores_already_updated_files(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        before = {
            path: (target / path).read_bytes()
            for path in ("_agent-rules-source.json", "a.txt", "merge.txt")
        }
        real_write = UPGRADE.write_payload
        calls = 0

        def fail_second_write(path, content, mode):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic write failure")
            real_write(path, content, mode)

        with mock.patch.object(UPGRADE, "write_payload", side_effect=fail_second_write):
            with self.assertRaises(OSError):
                UPGRADE.apply_upgrade(
                    manifest, files, target, plan, self.backup_directory
                )

        for path, content in before.items():
            self.assertEqual((target / path).read_bytes(), content)
        self.assertFalse((target / "new.txt").exists())

    def test_apply_rejects_a_file_changed_after_planning(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        changed = b"changed after planning\n"
        (target / "a.txt").write_bytes(changed)

        with self.assertRaisesRegex(
            UPGRADE.UpgradeError, "Target changed after planning: a.txt"
        ):
            UPGRADE.apply_upgrade(manifest, files, target, plan, self.backup_directory)

        self.assertEqual((target / "a.txt").read_bytes(), changed)
        self.assertFalse((target / "_starter-kit-files.json").exists())

    def test_apply_preserves_an_add_path_occupied_after_planning(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        concurrent = b"concurrent local file\n"
        (target / "new.txt").write_bytes(concurrent)

        with self.assertRaisesRegex(
            UPGRADE.UpgradeError, "Target changed after planning: new.txt"
        ):
            UPGRADE.apply_upgrade(manifest, files, target, plan, self.backup_directory)

        self.assertEqual((target / "new.txt").read_bytes(), concurrent)
        self.assertEqual((target / "a.txt").read_bytes(), self.base_files["a.txt"])
        self.assertEqual(
            (target / "merge.txt").read_bytes(), self.base_files["merge.txt"]
        )

    def test_apply_preserves_a_concurrently_modified_adoption_manifest(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        adoption_path = target / ".starter-kit-adoption.json"
        adoption_path.write_bytes(b'{"initial": true}\n')
        concurrent = b'{"concurrent": true}\n'
        real_write = UPGRADE.write_payload
        modified = False

        def modify_adoption_after_first_write(path, content, mode):
            nonlocal modified
            real_write(path, content, mode)
            if not modified and path != adoption_path:
                adoption_path.write_bytes(concurrent)
                modified = True

        with mock.patch.object(
            UPGRADE,
            "write_payload",
            side_effect=modify_adoption_after_first_write,
        ):
            with self.assertRaisesRegex(
                UPGRADE.UpgradeError,
                r"Target changed after planning: \.starter-kit-adoption\.json",
            ):
                UPGRADE.apply_upgrade(
                    manifest, files, target, plan, self.backup_directory
                )

        self.assertEqual(adoption_path.read_bytes(), concurrent)
        self.assertEqual((target / "a.txt").read_bytes(), self.base_files["a.txt"])
        self.assertFalse((target / "new.txt").exists())

    def test_restore_snapshot_reapplies_executable_mode(self):
        path = self.root / "restored.sh"
        snapshot = UPGRADE.FileSnapshot(b"#!/bin/sh\n", 0o751)

        with (
            mock.patch.object(UPGRADE, "write_payload") as write_mock,
            mock.patch.object(UPGRADE.os, "name", "posix"),
            mock.patch.object(Path, "chmod") as chmod_mock,
        ):
            UPGRADE.restore_snapshot(path, snapshot)

        write_mock.assert_called_once_with(path, snapshot.content, "100755")
        chmod_mock.assert_called_once_with(snapshot.mode)

    @unittest.skipIf(os.name == "nt", "POSIX file modes are unavailable on Windows")
    def test_failed_write_restores_exact_posix_mode(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        path = target / "a.txt"
        path.chmod(0o751)
        real_write = UPGRADE.write_payload
        calls = 0

        def fail_third_write(destination, content, mode):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("synthetic write failure after executable update")
            real_write(destination, content, mode)

        with mock.patch.object(UPGRADE, "write_payload", side_effect=fail_third_write):
            with self.assertRaises(OSError):
                UPGRADE.apply_upgrade(
                    manifest, files, target, plan, self.backup_directory
                )

        self.assertEqual(path.read_bytes(), self.base_files["a.txt"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o751)

    def test_main_build_writes_a_detailed_release_log(self):
        output = self.root / "main-upgrade.zip"

        exit_code, stdout, stderr = self.run_main(
            [
                "build",
                "--base-package",
                str(self.base_package),
                "--new-package",
                str(self.new_package),
                "--output",
                str(output),
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Created cumulative upgrade package", stdout)
        self.assertRegex(
            stderr,
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} Log file: ",
        )
        log = self.single_log()
        self.assertRegex(
            log.name,
            r"^starter-kit-upgrade-v2\.0\.0-\d{8}-\d{6}\.log$",
        )
        content = self.assert_timestamped_log(log)
        self.assertIn("PHASE_START", content)
        self.assertIn("BASE_RELEASE=v1.0.0", content)
        self.assertIn("TARGET_RELEASE=v2.0.0", content)
        self.assertIn("path=a.txt action=INCLUDE_UPGRADE_PAYLOAD", content)
        self.assertIn("path=removed.txt action=PRESERVE_OBSOLETE_FILE", content)
        self.assertIn("UPDATE_STATUS=ARTIFACT_CREATED", content)
        self.assertIn("OPERATIONAL_COMPLIANCE=ARTIFACT_COMPLIANT", content)
        self.assertIn("EXACT_RELEASE_ALIGNMENT=NOT_APPLICABLE", content)
        self.assertIn("EXIT_CODE=0", content)

    def test_main_toolkit_logs_each_created_member(self):
        output = self.root / "toolkit-main.zip"

        exit_code, _, _ = self.run_main(
            [
                "toolkit",
                "--new-package",
                str(self.new_package),
                "--output",
                str(output),
            ]
        )

        self.assertEqual(exit_code, 0)
        content = self.assert_timestamped_log(self.single_log())
        self.assertIn("path=starter-kit-upgrade.py action=ADD_TOOLKIT_MEMBER", content)
        self.assertIn("path=packages/new.zip action=ADD_TOOLKIT_MEMBER", content)
        self.assertIn("path=README.md action=ADD_TOOLKIT_MEMBER", content)
        self.assertIn("archive=created-toolkit", content)

    def test_main_plan_preserves_json_stdout_and_logs_readiness(self):
        target = self.create_target()

        exit_code, stdout, _ = self.run_main(
            [
                "plan",
                "--upgrade-package",
                str(self.upgrade_package),
                "--target",
                str(target),
            ]
        )

        self.assertEqual(exit_code, 0)
        plan = json.loads(stdout)
        self.assertTrue(plan["applicable"])
        content = self.assert_timestamped_log(self.single_log())
        for path in sorted(self.new_files):
            self.assertIn(f"path={path}", content)
        self.assertIn("PLAN_STATUS=READY", content)
        self.assertIn("UPDATE_STATUS=NOT_APPLIED", content)
        self.assertIn("OPERATIONAL_COMPLIANCE=READY", content)
        self.assertIn("EXACT_RELEASE_ALIGNMENT=NOT_ALIGNED", content)

    def test_main_apply_logs_writes_rollback_and_double_verdict(self):
        target = self.create_target()

        exit_code, stdout, _ = self.run_main(
            [
                "apply",
                "--upgrade-package",
                str(self.upgrade_package),
                "--target",
                str(target),
                "--backup-directory",
                str(self.backup_directory),
            ]
        )

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout)
        self.assertIn("backup", result)
        content = self.assert_timestamped_log(self.single_log())
        self.assertIn("action=SAVE_ROLLBACK_COPY", content)
        self.assertIn("path=a.txt action=UPDATE result=WRITTEN", content)
        self.assertIn("path=new.txt action=ADD result=WRITTEN", content)
        self.assertIn("path=.starter-kit-adoption.json", content)
        self.assertIn("ADOPTION_STATUS=CURRENT", content)
        self.assertIn("UPDATE_STATUS=SUCCEEDED", content)
        self.assertIn("OPERATIONAL_COMPLIANCE=COMPLIANT_WITH_FOLLOW_UP", content)
        self.assertIn("EXACT_RELEASE_ALIGNMENT=NOT_ALIGNED", content)

    def test_main_plan_logs_a_blocked_non_compliant_target(self):
        target = self.create_target()
        (target / "a.txt").write_text("locally changed\n", encoding="utf-8")
        self.run_git(target, "add", "a.txt")
        self.run_git(target, "commit", "-m", "test: diverge managed file")

        exit_code, stdout, _ = self.run_main(
            [
                "plan",
                "--upgrade-package",
                str(self.upgrade_package),
                "--target",
                str(target),
            ]
        )

        self.assertEqual(exit_code, 1)
        self.assertFalse(json.loads(stdout)["applicable"])
        content = self.assert_timestamped_log(self.single_log())
        self.assertIn("path=a.txt action=conflict-modified", content)
        self.assertIn("PLAN_STATUS=BLOCKED", content)
        self.assertIn("UPDATE_STATUS=NOT_APPLIED", content)
        self.assertIn("OPERATIONAL_COMPLIANCE=NON_COMPLIANT", content)
        self.assertIn("EXIT_CODE=1", content)

    def test_main_apply_failure_logs_automatic_restoration(self):
        target = self.create_target()
        before = (target / "a.txt").read_bytes()
        real_write = UPGRADE.write_payload
        calls = 0

        def fail_third_write(path, content, mode):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("synthetic journaled write failure")
            real_write(path, content, mode)

        with mock.patch.object(UPGRADE, "write_payload", side_effect=fail_third_write):
            exit_code, _, _ = self.run_main(
                [
                    "apply",
                    "--upgrade-package",
                    str(self.upgrade_package),
                    "--target",
                    str(target),
                    "--backup-directory",
                    str(self.backup_directory),
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual((target / "a.txt").read_bytes(), before)
        self.assertFalse((target / "new.txt").exists())
        content = self.assert_timestamped_log(self.single_log())
        self.assertIn("WRITE_FAILURE detected", content)
        self.assertIn("action=ROLLBACK_RESTORE result=RESTORED", content)
        self.assertIn("EXCEPTION_TYPE=OSError", content)
        self.assertIn("UPDATE_STATUS=FAILED", content)
        self.assertIn("EXIT_CODE=1", content)

    def test_failure_after_release_resolution_is_finalized_in_log(self):
        output = self.root / "already-exists.zip"
        output.write_bytes(b"existing")

        exit_code, _, stderr = self.run_main(
            [
                "build",
                "--base-package",
                str(self.base_package),
                "--new-package",
                str(self.new_package),
                "--output",
                str(output),
            ]
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: Output already exists", stderr)
        content = self.assert_timestamped_log(self.single_log())
        self.assertIn("EXCEPTION_TYPE=UpgradeError", content)
        self.assertIn("TRACEBACK_BEGIN", content)
        self.assertIn("UPDATE_STATUS=FAILED", content)
        self.assertIn("OPERATIONAL_COMPLIANCE=NON_COMPLIANT", content)
        self.assertIn("EXIT_CODE=1", content)

    def test_dry_run_help_version_and_parser_errors_do_not_write_logs(self):
        output = self.root / "dry-run-upgrade.zip"

        exit_code, stdout, stderr = self.run_main(
            [
                "--dry-run",
                "build",
                "--base-package",
                str(self.base_package),
                "--new-package",
                str(self.new_package),
                "--output",
                str(output),
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertFalse(output.exists())
        self.assertEqual(stderr, "")
        self.assertFalse((self.root / "logs").exists())
        self.assertFalse(json.loads(stdout)["wouldWrite"])

        previous_directory = Path.cwd()
        try:
            os.chdir(self.root)
            for arguments in (["--help"], ["--version"], ["build"]):
                with self.subTest(arguments=arguments):
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            UPGRADE.main(arguments)
        finally:
            os.chdir(previous_directory)
        self.assertFalse((self.root / "logs").exists())

        exit_code, _, _ = self.run_main(
            [
                "plan",
                "--upgrade-package",
                str(self.root / "missing.zip"),
                "--target",
                str(self.root),
            ]
        )
        self.assertEqual(exit_code, 1)
        self.assertFalse((self.root / "logs").exists())

    def test_log_name_collision_waits_for_the_next_second(self):
        logs = self.root / "logs"
        logs.mkdir()
        first = datetime(2026, 8, 2, 12, 34, 56).astimezone()
        second = datetime(2026, 8, 2, 12, 34, 57).astimezone()
        occupied = logs / "starter-kit-upgrade-v2.0.0-20260802-123456.log"
        occupied.write_text("existing\n", encoding="utf-8")
        previous_directory = Path.cwd()
        stderr = io.StringIO()
        try:
            os.chdir(self.root)
            with (
                mock.patch.object(
                    UPGRADE,
                    "local_now",
                    side_effect=[first] * 6 + [second] * 20,
                ),
                mock.patch.object(UPGRADE.time, "sleep") as sleep_mock,
            ):
                journal = UPGRADE.RunJournal("plan", ["plan"])
                created = journal.bind_target_release("v2.0.0")
                journal.set_outcome("NOT_APPLIED", "READY", "NOT_ALIGNED")
                with redirect_stderr(stderr):
                    journal.finalize(0)
        finally:
            os.chdir(previous_directory)

        self.assertEqual(
            created.name,
            "starter-kit-upgrade-v2.0.0-20260802-123457.log",
        )
        sleep_mock.assert_called()
        self.assertEqual(occupied.read_text(encoding="utf-8"), "existing\n")
        self.assertIn("2026-08-02 12:34:57 Log file:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
