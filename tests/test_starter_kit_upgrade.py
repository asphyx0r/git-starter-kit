import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "starter-kit-upgrade.py"
)
SPEC = importlib.util.spec_from_file_location("starter_kit_upgrade", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
UPGRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADE)


def json_bytes(value):
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def provenance(starter_commit, agent_commit, starter_ref="v1.0.0"):
    return {
        "generatedAt": "2026-07-30T00:00:00Z",
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
        self.new_provenance = json_bytes(
            provenance("c" * 40, "d" * 40, "v2.0.0")
        )
        self.base_files = {
            "_agent-rules-source.json": self.base_provenance,
            "a.txt": b"base a\n",
            "merge.txt": (
                b"first base\nstable one\nstable two\nlast base\n"
            ),
            "README.md": b"base readme\n",
            "removed.txt": b"preserve removed\n",
            "starter-kit-manifest.json": json_bytes(starter_manifest("v1.0.0")),
        }
        self.new_files = {
            "_agent-rules-source.json": self.new_provenance,
            "a.txt": b"new a\n",
            "merge.txt": (
                b"first new\nstable one\nstable two\nlast base\n"
            ),
            "new.txt": b"new file\n",
            "README.md": b"new readme\n",
            "starter-kit-manifest.json": json_bytes(starter_manifest("v2.0.0")),
        }
        managed = []
        strategies = {
            "_agent-rules-source.json": "agent-rules",
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
            "starterKit": provenance("c" * 40, "d" * 40, "v2.0.0")[
                "starterKit"
            ],
            "agentRules": provenance("c" * 40, "d" * 40, "v2.0.0")[
                "agentRules"
            ],
            "files": managed,
        }
        self.new_files["_starter-kit-files.json"] = json_bytes(files_manifest)
        self.write_zip(self.base_package, self.base_files)
        self.write_zip(self.new_package, self.new_files)
        self.build_upgrade()

    def tearDown(self):
        self.temporary.cleanup()

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

    def test_tool_version_is_0_3_0(self):
        self.assertEqual(UPGRADE.VERSION, "0.3.0")

    def test_build_plan_and_apply_preserve_local_repository_files(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)

        self.assertTrue(plan["applicable"])
        self.assertEqual(plan["provenance"], "base")
        actions = {entry["path"]: entry["action"] for entry in plan["actions"]}
        self.assertEqual(actions["a.txt"], "update")
        self.assertEqual(actions["merge.txt"], "update")
        self.assertEqual(actions["new.txt"], "add")
        self.assertEqual(actions["README.md"], "review-initialize-only")
        self.assertEqual(plan["summary"]["review-initialize-only"], 1)
        self.assertEqual(
            actions["_agent-rules-source.json"], "delegate-agent-rules"
        )
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
        self.assertEqual(
            (target / "removed.txt").read_bytes(), b"preserve removed\n"
        )
        self.assertEqual(
            (target / "_agent-rules-source.json").read_bytes(),
            self.base_provenance,
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
            self.assertIn("packages/new.zip", archive.namelist())
            self.assertIn("README.md", archive.namelist())
            self.assertIn(
                "Every non-dry-run command writes a detailed execution journal",
                archive.read("README.md").decode("utf-8"),
            )

    def test_modified_managed_file_is_a_conflict(self):
        target = self.create_target()
        (target / "merge.txt").write_text("local merge\n", encoding="utf-8")
        self.run_git(target, "add", "merge.txt")
        self.run_git(target, "commit", "-m", "test: customize managed file")

        _, _, plan = self.load_plan(target)

        action = next(
            item for item in plan["actions"] if item["path"] == "merge.txt"
        )
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

        action = next(
            item for item in plan["actions"] if item["path"] == "merge.txt"
        )
        self.assertEqual(action["action"], "merge")
        self.assertTrue(plan["applicable"])

        UPGRADE.apply_upgrade(
            manifest, files, target, plan, self.backup_directory
        )

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

        UPGRADE.apply_upgrade(
            manifest, files, target, plan, self.backup_directory
        )

        state = json.loads(
            (target / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["source"]["ref"], "v1.0.0")
        self.assertEqual(state["current"]["ref"], "v2.0.0")

    def test_successive_upgrades_preserve_source_and_advance_current(self):
        target = self.create_target()
        manifest, files, plan = self.load_plan(target)
        UPGRADE.apply_upgrade(
            manifest, files, target, plan, self.backup_directory
        )
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
        managed_manifest["starterKit"] = provenance(
            "e" * 40, "f" * 40, "v3.0.0"
        )["starterKit"]
        managed_manifest["agentRules"] = provenance(
            "e" * 40, "f" * 40, "v3.0.0"
        )["agentRules"]
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
        second_plan = UPGRADE.evaluate_target(
            second_manifest, second_files, target
        )

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

        post_plan = UPGRADE.evaluate_target(
            second_manifest, second_files, target
        )
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

    def test_invalid_provenance_blocks_application(self):
        target = self.create_target()
        (target / "_agent-rules-source.json").write_text(
            "{}\n", encoding="utf-8"
        )
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

    def test_adoption_manifest_accepts_a_proven_baseline_commit(self):
        target = self.create_target()
        baseline_commit = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (target / "_agent-rules-source.json").write_text(
            "{}\n", encoding="utf-8"
        )
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
        self.assertEqual(provenance_action["action"], "delegate-agent-rules")
        self.assertTrue(plan["applicable"])

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

        with mock.patch.object(
            UPGRADE, "write_payload", side_effect=fail_second_write
        ):
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
            UPGRADE.apply_upgrade(
                manifest, files, target, plan, self.backup_directory
            )

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
            UPGRADE.apply_upgrade(
                manifest, files, target, plan, self.backup_directory
            )

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

        with mock.patch.object(UPGRADE, "write_payload") as write_mock, mock.patch.object(
            UPGRADE.os, "name", "posix"
        ), mock.patch.object(Path, "chmod") as chmod_mock:
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

        with mock.patch.object(
            UPGRADE, "write_payload", side_effect=fail_third_write
        ):
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
        self.assertIn(
            "path=starter-kit-upgrade.py action=ADD_TOOLKIT_MEMBER", content
        )
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
        self.assertIn(
            "OPERATIONAL_COMPLIANCE=COMPLIANT_WITH_FOLLOW_UP", content
        )
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

        with mock.patch.object(
            UPGRADE, "write_payload", side_effect=fail_third_write
        ):
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
                    with redirect_stdout(io.StringIO()), redirect_stderr(
                        io.StringIO()
                    ):
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
            with mock.patch.object(
                UPGRADE,
                "local_now",
                side_effect=[first] * 6 + [second] * 20,
            ), mock.patch.object(UPGRADE.time, "sleep") as sleep_mock:
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
