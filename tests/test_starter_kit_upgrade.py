import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
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


def provenance(starter_commit, agent_commit):
    return {
        "generatedAt": "2026-07-30T00:00:00Z",
        "starterKit": {
            "repository": "https://github.com/example/git-starter-kit",
            "ref": "v1.0.0",
            "commit": starter_commit,
        },
        "agentRules": {
            "repository": "https://github.com/example/agent-coding-rules",
            "ref": "v1.0.0",
            "commit": agent_commit,
        },
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
        self.new_provenance = json_bytes(provenance("c" * 40, "d" * 40))
        self.base_files = {
            "_agent-rules-source.json": self.base_provenance,
            "a.txt": b"base a\n",
            "merge.txt": (
                b"first base\nstable one\nstable two\nlast base\n"
            ),
            "README.md": b"base readme\n",
            "removed.txt": b"preserve removed\n",
        }
        self.new_files = {
            "_agent-rules-source.json": self.new_provenance,
            "a.txt": b"new a\n",
            "merge.txt": (
                b"first new\nstable one\nstable two\nlast base\n"
            ),
            "new.txt": b"new file\n",
            "README.md": b"new readme\n",
        }
        managed = []
        strategies = {
            "_agent-rules-source.json": "agent-rules",
            "a.txt": "replace",
            "merge.txt": "merge",
            "new.txt": "replace",
            "README.md": "initialize-only",
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
            "schemaVersion": 2,
            "starterKit": provenance("c" * 40, "d" * 40)["starterKit"],
            "agentRules": provenance("c" * 40, "d" * 40)["agentRules"],
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


if __name__ == "__main__":
    unittest.main()
