"""Cover initializer safety and index preparation using real package fixtures."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_git_init as initializer_fixtures


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "tools"))
try:
    SPEC = importlib.util.spec_from_file_location(
        "initialize_repository", SOURCE / "tools/initialize-repository.py"
    )
    assert SPEC is not None and SPEC.loader is not None
    INITIALIZER = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(INITIALIZER)
finally:
    sys.path.remove(str(SOURCE / "tools"))


class PackageInitializerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = initializer_fixtures.InitializerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.environment = patch.dict(os.environ, self.fixture.env)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.inventory = json.loads((self.root / "_starter-kit-files.json").read_text())

    def cli(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                ["initialize-repository.py", *arguments, "--path", str(self.root)],
            ),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            result = INITIALIZER.main()
        return result, output.getvalue(), errors.getvalue()

    def test_all_supported_inventories_identify_only_existing_system_paths(self):
        for schema in (1, 2, 3):
            with self.subTest(schema=schema):
                self.inventory["schemaVersion"] = schema
                self.fixture.write(
                    "_starter-kit-files.json", json.dumps(self.inventory)
                )
                modes = INITIALIZER.validate(self.root)
                self.assertEqual(modes["runner"], "100755")
                self.assertTrue(INITIALIZER.REQUIRED.issubset(modes))
                self.assertFalse((self.root / ".git").exists())

    def test_malformed_and_unsafe_inventory_rejects_without_writes(self):
        cases = (
            {},
            {"schemaVersion": True, "files": self.inventory["files"]},
            {"schemaVersion": 4, "files": self.inventory["files"]},
            {"schemaVersion": 3, "files": []},
            {"schemaVersion": 3, "files": ["not an entry"]},
            {"schemaVersion": 3, "files": [{"path": "../outside", "mode": "100644"}]},
            {"schemaVersion": 3, "files": [{"path": "runner", "mode": []}]},
            {"schemaVersion": 3, "files": [{"path": "missing", "mode": "100644"}]},
            {"schemaVersion": 3, "files": [{"path": "runner", "mode": "100777"}]},
            {
                "schemaVersion": 3,
                "files": [*self.inventory["files"], self.inventory["files"][0]],
            },
        )
        for case in cases:
            with self.subTest(case=case):
                self.fixture.write("_starter-kit-files.json", json.dumps(case))
                before = self.fixture.snapshot()
                with self.assertRaises(INITIALIZER.InitializationError):
                    INITIALIZER.load_inventory(self.root)
                self.assertEqual(self.fixture.snapshot(), before)

    def test_missing_inventory_and_required_runtime_are_rejected(self):
        (self.root / "_starter-kit-files.json").unlink()
        with self.assertRaisesRegex(INITIALIZER.InitializationError, "release ZIP"):
            INITIALIZER.load_inventory(self.root)
        self.inventory["files"] = [
            entry
            for entry in self.inventory["files"]
            if entry["path"] != "tools/process_runner.py"
        ]
        self.fixture.write("_starter-kit-files.json", json.dumps(self.inventory))
        with self.assertRaisesRegex(
            INITIALIZER.InitializationError, "required initializer"
        ):
            INITIALIZER.load_inventory(self.root)

    def test_application_source_blocks_initial_system_commit(self):
        self.fixture.write("app/value.py", "value = 42\n")
        before = self.fixture.snapshot()
        code, _, error = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("Application files cannot enter", error)
        self.assertEqual(self.fixture.snapshot(), before)

    def test_static_context_rejects_extra_or_modified_content_before_git(self):
        context = self.root / "tools/git-inventory-context"
        for relative in (
            "config",
            "index",
            "app.py",
            "objects/app.py",
            "refs/main",
            "hooks/pre-commit",
        ):
            with self.subTest(extra=relative):
                path = context / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unexpected\n")
                before = self.fixture.snapshot()
                with patch.object(INITIALIZER, "run") as git:
                    with self.assertRaisesRegex(
                        INITIALIZER.InitializationError, "inventory context"
                    ):
                        INITIALIZER.committable_files(self.root)
                    git.assert_not_called()
                self.assertEqual(self.fixture.snapshot(), before)
                path.unlink()
                if relative.startswith("hooks/"):
                    path.parent.rmdir()
        for relative in ("HEAD", "objects/.gitkeep", "refs/.gitkeep"):
            with self.subTest(modified=relative):
                path = context / relative
                original = path.read_bytes()
                path.write_bytes(b"altered\n")
                with patch.object(INITIALIZER, "run") as git:
                    with self.assertRaisesRegex(
                        INITIALIZER.InitializationError, "inventory context"
                    ):
                        INITIALIZER.committable_files(self.root)
                    git.assert_not_called()
                path.write_bytes(original)
        (context / "HEAD").unlink()
        (context / "HEAD").mkdir()
        with patch.object(INITIALIZER, "run") as git:
            with self.assertRaisesRegex(
                INITIALIZER.InitializationError, "inventory context"
            ):
                INITIALIZER.committable_files(self.root)
            git.assert_not_called()

    def test_static_context_rejects_real_directory_links(self):
        for relative in (
            "tools",
            "tools/git-inventory-context",
            "tools/git-inventory-context/objects",
            "tools/git-inventory-context/refs",
        ):
            with self.subTest(directory=relative):
                path = self.root / relative
                saved = path.with_name(path.name + "-original")
                path.rename(saved)
                linked = False
                try:
                    if os.name == "nt":
                        import _winapi

                        _winapi.CreateJunction(str(saved), str(path))
                    else:
                        path.symlink_to(saved, target_is_directory=True)
                    linked = True
                    with patch.object(INITIALIZER, "run") as git:
                        with self.assertRaisesRegex(
                            INITIALIZER.InitializationError, "inventory context"
                        ):
                            INITIALIZER.committable_files(self.root)
                        git.assert_not_called()
                finally:
                    if linked and os.name == "nt":
                        path.rmdir()
                    elif linked:
                        path.unlink()
                    saved.rename(path)

    def test_static_context_rejects_real_file_symlink(self):
        path = self.root / "tools/git-inventory-context/HEAD"
        saved = self.root.parent / "original-head"
        path.rename(saved)
        try:
            try:
                path.symlink_to(saved)
            except OSError as error:
                if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege is unavailable")
                raise
            with patch.object(INITIALIZER, "run") as git:
                with self.assertRaisesRegex(
                    INITIALIZER.InitializationError, "inventory context"
                ):
                    INITIALIZER.committable_files(self.root)
                git.assert_not_called()
        finally:
            if path.is_symlink():
                path.unlink()
            saved.rename(path)

    def test_zip_ignore_inventory_matches_real_git_hierarchy(self):
        global_ignore = self.root.parent / "global.ignore"
        global_ignore.write_text("*.global\nroot-wins.txt\n", encoding="utf-8")
        self.fixture.git("config", "--global", "core.excludesFile", str(global_ignore))
        self.fixture.write(
            ".gitignore",
            "*.tmp\n!keep.tmp\n/root.txt\nblocked/\n!blocked/keep.txt\nopen/*\n!open/kept/\n!root-wins.txt\n",
        )
        self.fixture.write("nested/.gitignore", "!local.tmp\n/only-here.txt\n*.local\n")
        for name in (
            "x.global",
            "root-wins.txt",
            "a.tmp",
            "keep.tmp",
            "root.txt",
            "nested/root.txt",
            "nested/local.tmp",
            "nested/a.tmp",
            "nested/only-here.txt",
            "other/only-here.txt",
            "nested/x.local",
            "blocked/keep.txt",
            "blocked/.gitignore",
            "open/lost.txt",
            "open/kept/value.txt",
            "application.py",
        ):
            self.fixture.write(name, "fixture\n")
        before = self.fixture.snapshot()
        actual = INITIALIZER.committable_files(self.root)
        self.assertEqual(self.fixture.snapshot(), before)
        self.fixture.git("init", "--initial-branch=main")
        expected = set(
            self.fixture.git(
                "ls-files", "--cached", "--others", "--exclude-standard"
            ).splitlines()
        )
        self.assertEqual(actual, expected)
        self.assertIn("application.py", actual)
        self.assertIn("nested/local.tmp", actual)
        self.assertNotIn("blocked/keep.txt", actual)
        self.fixture.write(".git/info/exclude", "application.py\n")
        self.fixture.git("add", "-f", "a.tmp")
        actual = INITIALIZER.committable_files(self.root)
        self.assertIn("a.tmp", actual)
        self.assertNotIn("application.py", actual)

    def test_invalid_schema_and_generated_directory_are_rejected(self):
        self.fixture.write(
            "templates/release/repository-manifest.schema.json", '{"type": 42}'
        )
        with self.assertRaisesRegex(
            INITIALIZER.InitializationError, "invalid repository schema"
        ):
            INITIALIZER.validate(self.root)
        (self.root / "VERSION").mkdir()
        with self.assertRaisesRegex(
            INITIALIZER.InitializationError, "Unsafe generated"
        ):
            INITIALIZER.load_inventory(self.root)

    def test_zip_inventory_preserves_relative_global_exclusions_and_ignorecase(self):
        self.fixture.write("global.ignore", "*.GLOBAL\n")
        self.fixture.write(".gitignore", "*.TEMP\n!Keep.TEMP\n")
        for name in (
            "lower.global",
            "upper.GLOBAL",
            "value.temp",
            "KeEp.TeMp",
        ):
            self.fixture.write(name, "fixture\n")
        self.fixture.git("config", "--global", "core.excludesFile", "global.ignore")
        self.fixture.git("config", "--global", "core.ignorecase", "true")
        actual = INITIALIZER.committable_files(self.root)
        self.fixture.git("init", "--initial-branch=main")
        expected = set(
            self.fixture.git("ls-files", "--others", "--exclude-standard").splitlines()
        )
        self.assertEqual(actual, expected)
        self.assertNotIn("lower.global", actual)
        self.assertNotIn("value.temp", actual)
        self.assertIn("KeEp.TeMp", actual)

    def test_zip_inventory_matches_git_byte_wildcards_and_non_ascii_case(self):
        self.fixture.write(
            ".gitignore",
            "question-?.txt\ndouble-??.txt\nliteral-é.txt\ncase-É.txt\nfile[[:digit:]].tmp\n",
        )
        for name in (
            "question-é.txt",
            "double-é.txt",
            "literal-é.txt",
            "case-é.txt",
            "file4.tmp",
        ):
            self.fixture.write(name, "fixture\n")
        self.fixture.git("config", "--global", "core.ignorecase", "true")
        actual = INITIALIZER.committable_files(self.root)
        self.fixture.git("init", "--initial-branch=main")
        expected = set(
            INITIALIZER.run(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ]
            )
            .decode("utf-8")
            .split("\0")[:-1]
        )
        self.assertEqual(actual, expected)
        self.assertIn("question-é.txt", actual)
        self.assertNotIn("double-é.txt", actual)
        self.assertNotIn("literal-é.txt", actual)
        self.assertIn("case-é.txt", actual)

    def test_cli_dry_run_is_read_only_and_real_prepare_builds_checked_index(self):
        before = self.fixture.snapshot()
        code, output, error = self.cli("validate", "--dry-run")
        self.assertEqual((code, error), (0, ""))
        self.assertIn("Dry run:", output)
        self.assertEqual(self.fixture.snapshot(), before)
        code, _, error = self.cli("validate")
        self.assertEqual((code, error), (0, ""))
        self.fixture.git("init", "--initial-branch=main")
        code, _, error = self.cli("prepare", "--tag", "v1.0.0")
        self.assertEqual((code, error), (0, ""))
        self.assertEqual((self.root / "VERSION").read_text().strip(), "1.0.0")
        self.assertEqual(self.fixture.git("symbolic-ref", "--short", "HEAD"), "main")
        staged = self.fixture.git("ls-files", "--stage")
        self.assertIn("100755", staged)
        self.assertIn("SHA256SUMS", staged)
        self.assertIn("manifest.json", staged)
        context_entries = [
            line
            for line in staged.splitlines()
            if "\ttools/git-inventory-context/" in line
        ]
        self.assertEqual(len(context_entries), 3)
        self.assertTrue(all(line.startswith("100644 ") for line in context_entries))
        self.assertFalse(self.fixture.git("rev-list", "--all", "--max-count=1"))

    def test_real_failed_git_command_preserves_error(self):
        with self.assertRaisesRegex(
            INITIALIZER.InitializationError, "not a git repository"
        ):
            INITIALIZER.run(
                ["git", f"--git-dir={self.root / 'absent.git'}", "rev-parse", "HEAD"]
            )


if __name__ == "__main__":
    unittest.main()
