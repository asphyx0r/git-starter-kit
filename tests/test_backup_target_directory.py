from __future__ import annotations

import errno
import hashlib
import importlib.util
import io
import os
import shutil
import stat
import subprocess
import sys
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory, gettempdir
from threading import Barrier
from types import SimpleNamespace
from unittest import mock

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "backup-target-directory.py"
)


def load_script_module():
    spec = importlib.util.spec_from_file_location(
        "backup_target_directory", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("Unable to load backup-target-directory.py.")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BackupTargetDirectoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = load_script_module()

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with mock.patch.object(self.script, "_is_linux_root", return_value=False):
            with mock.patch.object(
                self.script,
                "resolve_git_identity",
                return_value=(
                    self.script.DEFAULT_HEAD,
                    self.script.DEFAULT_SEMVER_TAG,
                ),
            ):
                with redirect_stdout(output):
                    code = self.script.main(list(args))
        return code, output.getvalue()

    def run_git(self, directory: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()

    def test_escaped_trailing_slash_arguments_are_reassembled(self) -> None:
        source = "G:\\Mon Drive\\Datalog\\Projects\\SWIFT\\vendor-interface-validation"
        target = "G:\\Mon Drive\\Backup\\Datalog\\vendor-interface-validation"

        normalized_args = self.script.normalize_escaped_windows_args(
            [
                "-d",
                f'{source}" -t G:\\Mon',
                'Drive\\Backup\\Datalog\\vendor-interface-validation"',
            ]
        )

        self.assertEqual(normalized_args, ["-d", source, "-t", target])

    def test_archive_name_includes_normalized_source_head_and_tag(self) -> None:
        archive_name = self.script.build_archive_name(
            "Répertoire Source",
            "20260718-125229",
            "ac42ebea5d4a",
            "v1.0.0",
        )

        self.assertEqual(
            archive_name,
            "repertoire-source-20260718-125229-ac42ebea5d4a-v1.0.0.zip",
        )

    def test_git_identity_uses_placeholders_without_readable_head(self) -> None:
        source = Path("source")
        with mock.patch.object(
            self.script,
            "run_git",
            return_value=None,
        ) as run_git:
            identity = self.script.resolve_git_identity(source)

        self.assertEqual(
            identity,
            (self.script.DEFAULT_HEAD, self.script.DEFAULT_SEMVER_TAG),
        )
        run_git.assert_called_once_with(
            source,
            "rev-parse",
            "--short=12",
            "HEAD",
        )

    def test_git_identity_rejects_invalid_head_output(self) -> None:
        with mock.patch.object(
            self.script,
            "run_git",
            return_value="not-a-commit\n",
        ):
            identity = self.script.resolve_git_identity(Path("source"))

        self.assertEqual(
            identity,
            (self.script.DEFAULT_HEAD, self.script.DEFAULT_SEMVER_TAG),
        )

    def test_git_identity_uses_tag_placeholder_when_tags_are_unreadable(
        self,
    ) -> None:
        with mock.patch.object(
            self.script,
            "run_git",
            side_effect=["abcdef123456\n", None],
        ):
            identity = self.script.resolve_git_identity(Path("source"))

        self.assertEqual(identity, ("abcdef123456", self.script.DEFAULT_SEMVER_TAG))

    def test_git_identity_selects_first_semver_tag_on_captured_head(self) -> None:
        source = Path("source")
        with mock.patch.object(
            self.script,
            "run_git",
            side_effect=[
                "abcdef123456\n",
                "release-candidate\nv1.2.3\nv1.2.2\n",
            ],
        ) as run_git:
            identity = self.script.resolve_git_identity(source)

        self.assertEqual(identity, ("abcdef123456", "v1.2.3"))
        self.assertEqual(
            run_git.call_args_list,
            [
                mock.call(source, "rev-parse", "--short=12", "HEAD"),
                mock.call(
                    source,
                    "tag",
                    "--sort=-creatordate",
                    "--points-at",
                    "abcdef123456",
                ),
            ],
        )

    def test_run_git_returns_none_when_git_is_unavailable(self) -> None:
        with mock.patch.object(
            self.script.subprocess,
            "run",
            side_effect=FileNotFoundError,
        ):
            output = self.script.run_git(Path("source"), "rev-parse", "HEAD")

        self.assertIsNone(output)

    @unittest.skipUnless(shutil.which("git"), "Git is required for this test.")
    def test_git_identity_requires_semver_tag_on_exact_head(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "repository"
            source.mkdir()

            with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": temp_dir}):
                self.assertEqual(
                    self.script.resolve_git_identity(source),
                    (self.script.DEFAULT_HEAD, self.script.DEFAULT_SEMVER_TAG),
                )

            self.run_git(source, "init", "--quiet")
            self.assertEqual(
                self.script.resolve_git_identity(source),
                (self.script.DEFAULT_HEAD, self.script.DEFAULT_SEMVER_TAG),
            )

            self.run_git(source, "config", "user.name", "Backup Test")
            self.run_git(
                source,
                "config",
                "user.email",
                "backup-test@example.invalid",
            )
            self.run_git(source, "config", "commit.gpgSign", "false")
            self.run_git(source, "config", "tag.gpgSign", "false")

            tracked_file = source / "tracked.txt"
            tracked_file.write_text("first\n", encoding="utf-8")
            self.run_git(source, "add", "tracked.txt")
            self.run_git(source, "commit", "--quiet", "-m", "first")
            first_head = self.run_git(
                source,
                "rev-parse",
                "--short=12",
                "HEAD",
            )
            self.run_git(source, "tag", "-a", "v1.0.0", "-m", "v1.0.0")

            self.assertEqual(
                self.script.resolve_git_identity(source),
                (first_head, "v1.0.0"),
            )

            tracked_file.write_text("second\n", encoding="utf-8")
            self.run_git(source, "add", "tracked.txt")
            self.run_git(source, "commit", "--quiet", "-m", "second")
            second_head = self.run_git(
                source,
                "rev-parse",
                "--short=12",
                "HEAD",
            )

            self.assertEqual(
                self.script.resolve_git_identity(source),
                (second_head, self.script.DEFAULT_SEMVER_TAG),
            )

            self.run_git(source, "tag", "release-candidate")
            self.assertEqual(
                self.script.resolve_git_identity(source),
                (second_head, self.script.DEFAULT_SEMVER_TAG),
            )

            self.run_git(source, "tag", "v1.1.0")
            self.assertEqual(
                self.script.resolve_git_identity(source),
                (second_head, "v1.1.0"),
            )

    def test_dry_run_accepts_split_windows_target_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source with spaces"
            target = temp_path / "target with spaces"
            buffer_directory = temp_path / "buffer with spaces"
            source.mkdir()
            target.mkdir()
            buffer_directory.mkdir()

            target_parts = str(target).split(" ")
            target_parts[-1] = f'{target_parts[-1]}"'

            with mock.patch.object(
                self.script,
                "current_timestamp",
                return_value="20260718-125229",
            ):
                code, output = self.run_cli(
                    "--dry-run",
                    "-d",
                    f'{source}" -t {target_parts[0]}',
                    *target_parts[1:],
                    "-b",
                    str(buffer_directory),
                )

            self.assertEqual(code, 0)
            self.assertIn("[INFO ] Using source directory:", output)
            self.assertIn("[INFO ] Using target directory:", output)
            self.assertIn(
                "source-with-spaces-20260718-125229-000000000000-v0.0.0.zip",
                output,
            )
            self.assertIn("[INFO ] Dry run completed without modifying data.", output)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(list(buffer_directory.iterdir()), [])

    def test_help_and_version_follow_cli_contract(self) -> None:
        help_code, help_output = self.run_cli("--help")
        version_code, version_output = self.run_cli("--version")

        self.assertEqual(help_code, 0)
        self.assertEqual(version_code, 0)
        self.assertEqual(version_output, f"{self.script.VERSION}\n")
        option_lines = (
            "  -h, --help",
            "  --version",
            "  --dry-run",
            "  -v, --verbose",
        )
        option_positions = [help_output.index(line) for line in option_lines]
        self.assertEqual(option_positions, sorted(option_positions))

    def test_missing_cli_arguments_report_usage_on_stdout(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            code = self.script.main([])

        self.assertEqual(code, 2)
        self.assertIn("usage: backup-target-directory.py", output.getvalue())
        self.assertIn("the following arguments are required", output.getvalue())

    def test_missing_source_is_reported_without_writing_target(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_source = temp_path / "missing-source"
            target = temp_path / "target"
            target.mkdir()

            code, output = self.run_cli(
                "--source-directory",
                str(missing_source),
                "--target-directory",
                str(target),
            )

            self.assertEqual(code, 1)
            self.assertIn(
                f"[FATAL] Source directory does not exist: {missing_source}",
                output,
            )
            self.assertEqual(list(target.iterdir()), [])

    def test_target_file_is_reported_without_modifying_it(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source"
            target_file = temp_path / "target.txt"
            source.mkdir()
            target_file.write_bytes(b"original\n")

            code, output = self.run_cli(
                "--source-directory",
                str(source),
                "--target-directory",
                str(target_file),
            )

            self.assertEqual(code, 1)
            self.assertIn(
                f"[FATAL] Target directory is not a directory: {target_file}",
                output,
            )
            self.assertEqual(target_file.read_bytes(), b"original\n")

    def test_linux_root_is_rejected_before_path_validation(self) -> None:
        with (
            mock.patch.object(self.script.sys, "platform", "linux"),
            mock.patch.object(
                self.script.os,
                "geteuid",
                return_value=0,
                create=True,
            ),
            self.assertRaisesRegex(
                self.script.BackupError,
                "This script must not run as root on Linux",
            ),
        ):
            self.script.run_backup(
                Path("missing-source"),
                Path("missing-target"),
                None,
                False,
                self.script.Logger(False, io.StringIO()),
            )

    def test_archive_name_rejects_source_without_ascii_characters(self) -> None:
        with self.assertRaisesRegex(
            self.script.BackupError,
            "Source directory name cannot be used in an archive name",
        ):
            self.script.build_archive_name(
                "\u65e5\u672c\u8a9e",
                "20260718-125229",
                "ac42ebea5d4a",
                "v1.0.0",
            )

    def test_dry_run_without_buffer_uses_system_temp_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source"
            target = temp_path / "target"
            source.mkdir()
            target.mkdir()

            code, output = self.run_cli(
                "--dry-run",
                "--verbose",
                "--source-directory",
                str(source),
                "--target-directory",
                str(target),
            )

            expected_parent = Path(gettempdir()).resolve(strict=True)
            self.assertEqual(code, 0)
            self.assertIn("[DEBUG] Validating source and target directories.", output)
            self.assertIn(f"[INFO ] Using staging parent: {expected_parent}", output)
            self.assertEqual(list(target.iterdir()), [])

    def test_invalid_optional_buffers_warn_and_use_system_temp(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source"
            missing_buffer = temp_path / "missing-buffer"
            buffer_file = temp_path / "buffer.txt"
            nested_buffer = source / "buffer"
            source.mkdir()
            buffer_file.write_text("not a directory\n", encoding="utf-8")
            nested_buffer.mkdir()
            expected_parent = Path(gettempdir()).resolve(strict=True)
            scenarios = (
                (missing_buffer, "Buffer directory does not exist"),
                (buffer_file, "Buffer path is not a directory"),
                (nested_buffer, "Buffer directory is inside source"),
            )

            for buffer_path, warning in scenarios:
                with self.subTest(buffer_path=buffer_path):
                    output = io.StringIO()
                    selected = self.script.select_buffer_parent(
                        source,
                        buffer_path,
                        self.script.Logger(False, output),
                    )

                    self.assertEqual(selected, expected_parent)
                    self.assertIn(f"[WARN ] {warning}", output.getvalue())

    def test_target_directory_inside_source_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            target = source / "backups"
            source.mkdir()
            target.mkdir()

            with mock.patch.object(
                self.script,
                "_is_linux_root",
                return_value=False,
            ):
                with self.assertRaisesRegex(
                    self.script.BackupError,
                    "Target directory must not be inside the source directory",
                ):
                    self.script.run_backup(
                        source,
                        target,
                        None,
                        False,
                        self.script.Logger(False, io.StringIO()),
                    )

            self.assertEqual(list(target.iterdir()), [])

    def test_existing_archive_is_not_replaced(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source"
            target = temp_path / "target"
            buffer_directory = temp_path / "buffer"
            source.mkdir()
            target.mkdir()
            buffer_directory.mkdir()

            archive_path = target / "source-20260718-125229-ac42ebea5d4a-v1.0.0.zip"
            archive_path.write_bytes(b"existing archive")

            with mock.patch.object(
                self.script,
                "_is_linux_root",
                return_value=False,
            ):
                with mock.patch.object(
                    self.script,
                    "resolve_git_identity",
                    return_value=("ac42ebea5d4a", "v1.0.0"),
                ):
                    with mock.patch.object(
                        self.script,
                        "current_timestamp",
                        return_value="20260718-125229",
                    ):
                        with self.assertRaisesRegex(
                            self.script.BackupError,
                            "Target archive already exists",
                        ):
                            self.script.run_backup(
                                source,
                                target,
                                buffer_directory,
                                False,
                                self.script.Logger(False, io.StringIO()),
                            )

            self.assertEqual(archive_path.read_bytes(), b"existing archive")
            self.assertEqual(list(buffer_directory.iterdir()), [])

    def test_source_tree_symbolic_link_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            source.mkdir()
            target_file = source / "target.txt"
            target_file.write_text("data\n", encoding="utf-8")
            link_path = source / "link.txt"
            try:
                link_path.symlink_to(target_file)
            except OSError as exc:
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            with self.assertRaisesRegex(
                self.script.BackupError,
                "Source tree contains a symbolic link",
            ):
                self.script.validate_source_tree(source)

    def test_source_junction_is_rejected_before_resolution(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            junction_stat = SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_reparse_tag=0xA0000003,
            )
            with mock.patch.object(Path, "lstat", return_value=junction_stat):
                with mock.patch.object(Path, "resolve") as resolve:
                    with self.assertRaisesRegex(self.script.BackupError, "junction"):
                        self.script.resolve_directory(source, "Source", True)
                    resolve.assert_not_called()

    def test_nested_junction_is_rejected_before_traversal(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            entry = source / "external"
            entry.mkdir()
            original_lstat = Path.lstat

            def entry_stat(path):
                if path == entry:
                    return SimpleNamespace(
                        st_mode=stat.S_IFDIR,
                        st_reparse_tag=0xA0000003,
                    )
                return original_lstat(path)

            def walk_before_descending():
                yield str(source), [entry.name], []
                self.fail("Source traversal descended through a junction")

            with mock.patch.object(Path, "lstat", entry_stat):
                with mock.patch.object(
                    self.script.os, "walk", return_value=walk_before_descending()
                ):
                    with self.assertRaisesRegex(self.script.BackupError, "junction"):
                        self.script.validate_source_tree(source)

    @unittest.skipUnless(sys.platform == "win32", "Windows junction test")
    def test_windows_junctions_abort_before_copy(self) -> None:
        for location in ("root", "external", "cyclic"):
            with self.subTest(location=location), TemporaryDirectory() as temp_dir:
                fixture = Path(temp_dir)
                source = fixture / "source"
                target = fixture / "target"
                buffer_directory = fixture / "buffer"
                external = fixture / "external"
                for directory in (source, target, buffer_directory, external):
                    directory.mkdir()
                (source / "data.txt").write_text("source data", encoding="utf-8")
                (external / "private.txt").write_text("external data", encoding="utf-8")
                link = fixture / "root-link" if location == "root" else source / "link"
                destination = source if location in ("root", "cyclic") else external
                subprocess.run(
                    [
                        "pwsh",
                        "-NoProfile",
                        "-Command",
                        "New-Item -ItemType Junction -Path $env:BACKUP_TEST_LINK "
                        "-Target $env:BACKUP_TEST_TARGET -ErrorAction Stop | Out-Null",
                    ],
                    env={
                        **os.environ,
                        "BACKUP_TEST_LINK": str(link),
                        "BACKUP_TEST_TARGET": str(destination),
                    },
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                selected_source = link if location == "root" else source
                for dry_run in (False, True):
                    arguments = [
                        "--source-directory",
                        str(selected_source),
                        "--target-directory",
                        str(target),
                        "--buffer-directory",
                        str(buffer_directory),
                    ]
                    if dry_run:
                        arguments.append("--dry-run")
                    with mock.patch.object(self.script.shutil, "copytree") as copy:
                        code, output = self.run_cli(*arguments)
                    self.assertEqual(code, 1, output)
                    self.assertIn("junction", output)
                    copy.assert_not_called()
                    self.assertEqual(list(target.iterdir()), [])
                    self.assertEqual(list(buffer_directory.iterdir()), [])

    def test_staging_is_cleaned_when_archive_creation_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source"
            target = temp_path / "target"
            buffer_directory = temp_path / "buffer"
            source.mkdir()
            target.mkdir()
            buffer_directory.mkdir()
            (source / "data.txt").write_text("data\n", encoding="utf-8")

            with mock.patch.object(
                self.script,
                "_is_linux_root",
                return_value=False,
            ):
                with mock.patch.object(
                    self.script,
                    "resolve_git_identity",
                    return_value=("ac42ebea5d4a", "v1.0.0"),
                ):
                    with mock.patch.object(
                        self.script,
                        "create_archive",
                        side_effect=OSError("archive failure"),
                    ):
                        with self.assertRaisesRegex(
                            OSError,
                            "archive failure",
                        ):
                            self.script.run_backup(
                                source,
                                target,
                                buffer_directory,
                                False,
                                self.script.Logger(False, io.StringIO()),
                            )

            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(list(buffer_directory.iterdir()), [])

    def test_git_identity_change_during_staging_aborts_archive(self) -> None:
        scenarios = (
            (
                ("aaaaaaaaaaaa", "v1.0.0"),
                ("bbbbbbbbbbbb", self.script.DEFAULT_SEMVER_TAG),
            ),
            (
                ("aaaaaaaaaaaa", "v1.0.0"),
                ("aaaaaaaaaaaa", "v1.0.1"),
            ),
        )

        for initial_identity, final_identity in scenarios:
            with self.subTest(final_identity=final_identity):
                with TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    source = temp_path / "source"
                    target = temp_path / "target"
                    buffer_directory = temp_path / "buffer"
                    source.mkdir()
                    target.mkdir()
                    buffer_directory.mkdir()
                    (source / "data.txt").write_text("data\n", encoding="utf-8")

                    with mock.patch.object(
                        self.script,
                        "_is_linux_root",
                        return_value=False,
                    ):
                        with mock.patch.object(
                            self.script,
                            "resolve_git_identity",
                            side_effect=[initial_identity, final_identity],
                        ):
                            with mock.patch.object(
                                self.script,
                                "current_timestamp",
                                return_value="20260718-125229",
                            ):
                                with mock.patch.object(
                                    self.script,
                                    "create_archive",
                                ) as create_archive:
                                    with self.assertRaisesRegex(
                                        self.script.BackupError,
                                        "Git identity changed during staging",
                                    ):
                                        self.script.run_backup(
                                            source,
                                            target,
                                            buffer_directory,
                                            False,
                                            self.script.Logger(False, io.StringIO()),
                                        )

                    create_archive.assert_not_called()
                    self.assertEqual(list(target.iterdir()), [])

    def test_backup_creates_archive_with_git_identity_in_name(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "Source Project"
            target = temp_path / "target"
            buffer_directory = temp_path / "buffer"
            source.mkdir()
            target.mkdir()
            buffer_directory.mkdir()
            (source / "data.txt").write_text("data\n", encoding="utf-8")

            with mock.patch.object(
                self.script,
                "_is_linux_root",
                return_value=False,
            ):
                with mock.patch.object(
                    self.script,
                    "resolve_git_identity",
                    return_value=("ac42ebea5d4a", "v1.0.0"),
                ):
                    with mock.patch.object(
                        self.script,
                        "current_timestamp",
                        return_value="20260718-125229",
                    ):
                        self.script.run_backup(
                            source,
                            target,
                            buffer_directory,
                            False,
                            self.script.Logger(False, io.StringIO()),
                        )

            archive_path = (
                target / "source-project-20260718-125229-ac42ebea5d4a-v1.0.0.zip"
            )
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("Source Project/data.txt", archive.namelist())

    def test_archive_writer_traverses_staging_tree_once_with_stable_contents(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            staged_source = temp_path / "source"
            nested_directory = staged_source / "nested"
            nested_directory.mkdir(parents=True)
            (staged_source / "root.txt").write_bytes(b"root\n")
            (nested_directory / "child.txt").write_bytes(b"child\n")
            archive_path = temp_path / "backup.zip"
            calls = []
            original_rglob = Path.rglob

            def track_rglob(path: Path, pattern: str):
                calls.append((path, pattern))
                return original_rglob(path, pattern)

            with mock.patch.object(Path, "rglob", track_rglob):
                self.script.write_zip_from_staged_tree(staged_source, archive_path)

            self.assertEqual(calls, [(staged_source, "*")])
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [
                        "source/",
                        "source/nested/",
                        "source/nested/child.txt",
                        "source/root.txt",
                    ],
                )
                self.assertEqual(archive.read("source/root.txt"), b"root\n")
                self.assertEqual(
                    archive.read("source/nested/child.txt"),
                    b"child\n",
                )

    def test_archive_publication_race_preserves_concurrent_destination(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            staged_source = temp_path / "source"
            staged_source.mkdir()
            (staged_source / "data.txt").write_bytes(b"new backup\n")
            archive_path = temp_path / "backup.zip"
            concurrent_contents = b"concurrent archive\n"
            operation = "rename" if sys.platform == "win32" else "link"
            original_publish = getattr(self.script.os, operation)

            def publish_after_concurrent_create(source: Path, target: Path) -> None:
                self.assertTrue(source.is_file())
                target.write_bytes(concurrent_contents)
                original_publish(source, target)

            with (
                mock.patch.object(
                    self.script.os,
                    operation,
                    side_effect=publish_after_concurrent_create,
                ),
                self.assertRaisesRegex(
                    self.script.BackupError, "Target archive already exists"
                ),
            ):
                self.script.create_archive(staged_source, archive_path)

            self.assertEqual(archive_path.read_bytes(), concurrent_contents)
            self.assertEqual(
                sorted(path.name for path in temp_path.iterdir()),
                ["backup.zip", "source"],
            )

    @unittest.skipUnless(shutil.which("git"), "Git is required for this test.")
    def test_backup_of_git_repository_is_complete_and_readable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "repository"
            target = temp_path / "target"
            buffer_directory = temp_path / "buffer"
            source.mkdir()
            target.mkdir()
            buffer_directory.mkdir()

            self.run_git(source, "init", "--quiet")
            self.run_git(source, "config", "user.name", "Backup Test")
            self.run_git(
                source,
                "config",
                "user.email",
                "backup-test@example.invalid",
            )
            self.run_git(source, "config", "commit.gpgSign", "false")
            self.run_git(source, "config", "tag.gpgSign", "false")
            (source / ".gitignore").write_text(
                "ignored.txt\n",
                encoding="utf-8",
            )
            (source / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            self.run_git(source, "add", ".gitignore", "tracked.txt")
            self.run_git(source, "commit", "--quiet", "-m", "initial")
            self.run_git(source, "tag", "v1.2.3")
            (source / "untracked.txt").write_text(
                "untracked\n",
                encoding="utf-8",
            )
            (source / "ignored.txt").write_text("ignored\n", encoding="utf-8")
            head = self.run_git(source, "rev-parse", "--short=12", "HEAD")

            with mock.patch.object(
                self.script,
                "_is_linux_root",
                return_value=False,
            ):
                with mock.patch.object(
                    self.script,
                    "current_timestamp",
                    return_value="20260718-125229",
                ):
                    self.script.run_backup(
                        source,
                        target,
                        buffer_directory,
                        False,
                        self.script.Logger(False, io.StringIO()),
                    )

            archive_path = target / f"repository-20260718-125229-{head}-v1.2.3.zip"
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
                archive_names = set(archive.namelist())
                self.assertIn("repository/.git/HEAD", archive_names)
                self.assertIn("repository/tracked.txt", archive_names)
                self.assertIn("repository/untracked.txt", archive_names)
                self.assertIn("repository/ignored.txt", archive_names)


class LocalBackupPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.script = load_script_module()
        self.fixture = TemporaryDirectory(prefix="backup-regression-")
        self.addCleanup(self.fixture.cleanup)
        self.root = Path(self.fixture.name).resolve()
        self.source = self.root / "source"
        self.target = self.root / "target"
        self.buffer = self.root / "buffer"
        for directory in (self.source, self.target, self.buffer):
            directory.mkdir()
        (self.source / "data.txt").write_bytes(b"complete backup\n")
        self.archive = self.target / "backup.zip"
        self.output = io.StringIO()
        self.logger = self.script.Logger(False, self.output)

    def assert_no_archive_temporaries(self) -> None:
        self.assertEqual(
            sorted(p.name for p in self.root.iterdir()), ["buffer", "source", "target"]
        )
        self.assertEqual(list(self.buffer.iterdir()), [])
        self.assertFalse(
            any(p.name.endswith(".zip.tmp") for p in self.target.iterdir())
        )

    @unittest.skipUnless(sys.platform == "win32", "Windows publication test")
    def test_windows_archive_succeeds_when_hard_links_are_unsupported(self) -> None:
        with mock.patch.object(
            self.script.os,
            "link",
            side_effect=OSError(
                1,
                "[WinError 1] Fonction incorrecte",  # codespell:ignore fonction
            ),
        ):
            self.script.create_archive(self.source, self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read("source/data.txt"), b"complete backup\n")
        self.assert_no_archive_temporaries()

    def test_zip_is_closed_locally_before_destination_is_opened(self) -> None:
        original_write = self.script.write_zip_from_staged_tree
        original_copy = self.script.shutil.copyfileobj
        local_archive = []

        def write_zip(source, archive):
            self.assertTrue(archive.is_relative_to(self.root))
            self.assertFalse(archive.is_relative_to(self.source))
            self.assertFalse(archive.is_relative_to(self.target))
            self.assertEqual(list(self.target.iterdir()), [])
            original_write(source, archive)
            local_archive.append(archive)

        def copy_zip(source, target, *args):
            target_name = getattr(target, "name", None)
            if target_name is None or Path(target_name).parent != self.target:
                return original_copy(source, target, *args)
            with zipfile.ZipFile(source.name) as archive:
                self.assertIsNone(archive.testzip())
            self.assertEqual(Path(source.name), local_archive[0])
            self.assertEqual(Path(target.name).parent, self.target)
            self.assertFalse(self.archive.exists())
            original_copy(source, target)

        with (
            mock.patch.object(
                self.script, "write_zip_from_staged_tree", side_effect=write_zip
            ),
            mock.patch.object(self.script.shutil, "copyfileobj", side_effect=copy_zip),
        ):
            self.script.create_archive(self.source, self.archive)
        self.assertTrue(self.archive.is_file())
        self.assertFalse(local_archive[0].exists())
        self.assert_no_archive_temporaries()

    def test_two_publishers_never_overwrite_the_winner(self) -> None:
        second_source = self.buffer / "other-source"
        second_source.mkdir()
        (second_source / "other.txt").write_bytes(b"other backup\n")
        operation = "rename" if sys.platform == "win32" else "link"
        original_publish = getattr(self.script.os, operation)
        barrier = Barrier(2)

        def publish(source, target):
            barrier.wait(timeout=10)
            original_publish(source, target)

        def create(source):
            try:
                self.script.create_archive(source, self.archive)
                return "created"
            except self.script.BackupError:
                return "collision"

        with mock.patch.object(self.script.os, operation, side_effect=publish):
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(create, [self.source, second_source]))
        self.assertEqual(sorted(outcomes), ["collision", "created"])
        with zipfile.ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            self.assertIn(
                names,
                [
                    {"source/", "source/data.txt"},
                    {"other-source/", "other-source/other.txt"},
                ],
            )
        self.assertEqual(list(self.target.iterdir()), [self.archive])

    def test_compression_failure_leaves_destination_untouched(self) -> None:
        def fail_write(source, archive):
            archive.write_bytes(b"partial zip")
            raise OSError(errno.ENOSPC, "No space left on device")

        with (
            mock.patch.object(
                self.script, "write_zip_from_staged_tree", side_effect=fail_write
            ),
            self.assertRaises(OSError),
        ):
            self.script.create_archive(self.source, self.archive)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assert_no_archive_temporaries()

    def test_transfer_failure_removes_only_owned_temporaries(self) -> None:
        sentinel = self.target / ".unrelated.zip.tmp"
        sentinel.write_bytes(b"keep")
        original_copy = self.script.shutil.copyfileobj

        def fail_copy(source, target, *args):
            target_name = getattr(target, "name", None)
            if target_name is None or Path(target_name).parent != self.target:
                return original_copy(source, target, *args)
            target.write(b"partial transfer")
            raise OSError(errno.ENOSPC, "No space left on device")

        with (
            mock.patch.object(self.script.shutil, "copyfileobj", side_effect=fail_copy),
            self.assertRaises(OSError),
        ):
            self.script.create_archive(self.source, self.archive)
        self.assertEqual(list(self.target.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertEqual(
            sorted(p.name for p in self.root.iterdir()), ["buffer", "source", "target"]
        )

    def test_destination_creation_denied_leaves_no_archive(self) -> None:
        with (
            mock.patch.object(
                self.script.tempfile,
                "NamedTemporaryFile",
                side_effect=PermissionError("target denied"),
            ),
            self.assertRaises(PermissionError),
        ):
            self.script.create_archive(self.source, self.archive)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assert_no_archive_temporaries()

    def test_cleanup_failure_reports_the_owned_path(self) -> None:
        original_unlink = Path.unlink
        retained = []

        def fail_unlink(path, *args, **kwargs):
            if path.parent == self.target and path.name.endswith(".zip.tmp"):
                retained.append(path)
                raise PermissionError("cleanup denied")
            return original_unlink(path, *args, **kwargs)

        try:
            with mock.patch.object(Path, "unlink", fail_unlink):
                with self.assertRaises(self.script.BackupError) as caught:
                    self.script.create_archive(self.source, self.archive)
            self.assertEqual(len(retained), 1)
            self.assertIn(str(retained[0]), str(caught.exception))
            # Windows has already renamed the temporary file on successful publication.
            self.assertTrue(self.archive.is_file())
        finally:
            for path in retained:
                path.unlink(missing_ok=True)
        self.assert_no_archive_temporaries()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux publication test")
    def test_linux_unsupported_hard_links_fail_without_final_archive(self) -> None:
        with (
            mock.patch.object(
                self.script.os,
                "link",
                side_effect=OSError(errno.EOPNOTSUPP, "Operation not supported"),
            ),
            self.assertRaises(OSError),
        ):
            self.script.create_archive(self.source, self.archive)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assert_no_archive_temporaries()

    def test_remote_buffer_warns_and_falls_back_locally(self) -> None:
        local_fallback = self.root / "local-temp"
        local_fallback.mkdir()
        with (
            mock.patch.object(
                self.script,
                "_is_local_directory",
                create=True,
                side_effect=lambda p: p != self.buffer,
            ),
            mock.patch.dict(os.environ, {"TMPDIR": str(local_fallback)}),
        ):
            selected = self.script.select_buffer_parent(
                self.source, self.buffer, self.logger
            )
        self.assertEqual(selected, local_fallback)
        self.assertIn("[WARN ]", self.output.getvalue())
        self.assertIn("local", self.output.getvalue())
        self.assertEqual(list(self.buffer.iterdir()), [])

    def test_default_buffer_skips_remote_and_missing_candidates_without_writing(
        self,
    ) -> None:
        missing = self.root / "missing"
        with (
            mock.patch.dict(
                os.environ,
                {
                    "TMPDIR": str(self.target),
                    "TEMP": str(missing),
                    "TMP": str(self.buffer),
                },
            ),
            mock.patch.object(
                self.script,
                "_is_local_directory",
                create=True,
                side_effect=lambda p: p == self.buffer,
            ),
            mock.patch.object(
                self.script.tempfile,
                "gettempdir",
                side_effect=AssertionError("must not probe temp files"),
            ),
        ):
            selected = self.script.select_buffer_parent(self.source, None, self.logger)
        self.assertEqual(selected, self.buffer)
        self.assertFalse(missing.exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_no_local_buffer_aborts_without_copy_or_archive(self) -> None:
        with (
            mock.patch.object(self.script, "_is_linux_root", return_value=False),
            mock.patch.object(
                self.script,
                "resolve_git_identity",
                return_value=("000000000000", "v0.0.0"),
            ),
            mock.patch.object(
                self.script, "_is_local_directory", create=True, return_value=False
            ),
            self.assertRaisesRegex(
                self.script.BackupError, "local temporary directory"
            ),
        ):
            self.script.run_backup(self.source, self.target, None, False, self.logger)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assert_no_archive_temporaries()

    def test_dry_run_creates_nothing_even_with_an_uncached_temp_directory(self) -> None:
        with (
            mock.patch.object(self.script, "_is_linux_root", return_value=False),
            mock.patch.object(
                self.script,
                "resolve_git_identity",
                return_value=("000000000000", "v0.0.0"),
            ),
            mock.patch.dict(os.environ, {"TMPDIR": str(self.buffer)}),
            mock.patch.object(
                self.script.tempfile,
                "gettempdir",
                side_effect=AssertionError("must not probe temp files"),
            ),
            mock.patch.object(
                self.script.tempfile,
                "TemporaryDirectory",
                side_effect=AssertionError("must not create staging"),
            ),
            mock.patch.object(
                self.script.tempfile,
                "NamedTemporaryFile",
                side_effect=AssertionError("must not create archive"),
            ),
        ):
            self.script.run_backup(self.source, self.target, None, True, self.logger)
        self.assertIn("Dry run completed", self.output.getvalue())
        self.assertEqual(list(self.target.iterdir()), [])
        self.assert_no_archive_temporaries()

    @unittest.skipUnless(
        os.environ.get("BACKUP_TEST_CLOUD_TARGET"),
        "Set BACKUP_TEST_CLOUD_TARGET for the mounted-cloud integration test",
    )
    def test_cloud_archive_integrity_collision_and_cleanup(self) -> None:
        cloud_parent = Path(os.environ["BACKUP_TEST_CLOUD_TARGET"]).resolve(strict=True)
        local_hashes = []
        original_write = self.script.write_zip_from_staged_tree

        def record_zip(source, archive):
            self.assertTrue(archive.is_relative_to(self.buffer))
            original_write(source, archive)
            local_hashes.append(hashlib.sha256(archive.read_bytes()).hexdigest())

        with TemporaryDirectory(
            prefix="backup-integration-", dir=cloud_parent
        ) as target_name:
            cloud_target = Path(target_name)
            with (
                mock.patch.object(self.script, "_is_linux_root", return_value=False),
                mock.patch.object(
                    self.script, "current_timestamp", return_value="20260930-233003"
                ),
                mock.patch.object(
                    self.script, "write_zip_from_staged_tree", side_effect=record_zip
                ),
            ):
                self.script.run_backup(
                    self.source, cloud_target, self.buffer, False, self.logger
                )
                archives = list(cloud_target.iterdir())
                self.assertEqual(len(archives), 1)
                archive = archives[0]
                published_bytes = archive.read_bytes()
                self.assertEqual(
                    hashlib.sha256(published_bytes).hexdigest(), local_hashes[0]
                )
                with zipfile.ZipFile(archive) as zipped:
                    self.assertIsNone(zipped.testzip())
                    self.assertEqual(
                        zipped.read("source/data.txt"), b"complete backup\n"
                    )
                with self.assertRaisesRegex(self.script.BackupError, "already exists"):
                    self.script.run_backup(
                        self.source, cloud_target, self.buffer, False, self.logger
                    )
            # Exercise the provider's publication collision, beyond the early exists check.
            with self.assertRaisesRegex(self.script.BackupError, "already exists"):
                self.script.create_archive(self.source, archive)
            self.assertEqual(archive.read_bytes(), published_bytes)
            self.assertEqual(list(cloud_target.iterdir()), [archive])
            cli_target = cloud_target / "cli"
            cli_target.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT_PATH),
                    "--source-directory",
                    str(self.source),
                    "--target-directory",
                    str(cli_target),
                    "--buffer-directory",
                    str(self.buffer),
                ],
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("WinError 1", result.stdout + result.stderr)
            cli_archives = list(cli_target.iterdir())
            self.assertEqual(len(cli_archives), 1)
            self.assertEqual(
                hashlib.sha256(cli_archives[0].read_bytes()).hexdigest(),
                local_hashes[0],
            )
        self.assertFalse(cloud_target.exists())
        self.assert_no_archive_temporaries()


class LocalBufferClassificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = load_script_module()

    def test_windows_volume_classification_refuses_other_platforms(self) -> None:
        directory = Path("buffer")
        for platform in ("linux", "darwin"):
            with (
                self.subTest(platform=platform),
                mock.patch.object(self.script.sys, "platform", platform),
                mock.patch.object(
                    self.script.ctypes,
                    "WinDLL",
                    create=True,
                    side_effect=AssertionError("Windows API loaded outside Windows"),
                ),
            ):
                self.assertFalse(self.script._windows_directory_is_local(directory))

    def test_windows_volume_classification_uses_mount_root_and_remote_storage_flag(
        self,
    ) -> None:
        scenarios = (
            (3, 0, True, True, True),
            (3, 0x100, True, True, False),
            (4, 0, True, True, False),
            (0, 0, True, True, False),
            (2, 0, True, True, True),
            (6, 0, True, True, True),
            (3, 0, False, True, False),
            (3, 0, True, False, False),
        )
        for drive_type, flags, path_ok, info_ok, expected in scenarios:
            with self.subTest(
                drive_type=drive_type, flags=flags, path_ok=path_ok, info_ok=info_ok
            ):
                kernel = mock.Mock()
                mount_root = "C:\\mounted-volume\\"

                def get_volume_path(directory, result, size):
                    self.assertEqual(directory, str(Path("buffer")))
                    self.assertGreater(size, len(mount_root))
                    result.value = mount_root
                    return path_ok

                def get_drive_type(root):
                    self.assertEqual(root, mount_root)
                    return drive_type

                def get_volume_information(
                    root,
                    name,
                    size,
                    serial,
                    maximum,
                    output_flags,
                    filesystem,
                    filesystem_size,
                ):
                    self.assertEqual(root, mount_root)
                    self.script.ctypes.cast(
                        output_flags,
                        self.script.ctypes.POINTER(self.script.wintypes.DWORD),
                    ).contents.value = flags
                    return info_ok

                kernel.GetVolumePathNameW.side_effect = get_volume_path
                kernel.GetDriveTypeW.side_effect = get_drive_type
                kernel.GetVolumeInformationW.side_effect = get_volume_information
                with (
                    mock.patch.object(self.script.sys, "platform", "win32"),
                    mock.patch.object(
                        self.script.ctypes, "WinDLL", create=True, return_value=kernel
                    ),
                ):
                    result = self.script._windows_directory_is_local(Path("buffer"))
                self.assertEqual(result, expected)

    def test_linux_mount_classification_respects_nested_mounts_and_escaped_paths(
        self,
    ) -> None:
        mountinfo = (
            "1 0 8:1 / / rw - ext4 /dev/root rw\n"
            "2 1 0:2 / /remote rw - nfs server:/data rw\n"
            "3 2 0:3 / /remote/local rw - tmpfs tmpfs rw\n"
            "4 1 0:4 / /cloud\\040drive rw - fuse.drive drive rw\n"
            "5 1 0:5 / /unknown rw - unknown device rw\n"
            "6 1 0:6 / /overlay rw - overlay overlay rw\n"
            "7 1 0:7 / /stacked rw - tmpfs tmpfs rw\n"
            "8 1 0:8 / /stacked rw - cifs //server/share rw\n"
            "malformed\n"
        )
        for path, expected in (
            ("/tmp/local", True),
            ("/remote", False),
            ("/remote/child", False),
            ("/remote/local/child", True),
            ("/remote-name-prefix", True),
            ("/cloud drive/cache", False),
            ("/unknown/cache", False),
            ("/overlay/cache", True),
            ("/stacked/cache", False),
        ):
            with (
                self.subTest(path=path),
                mock.patch.object(Path, "read_text", return_value=mountinfo),
            ):
                self.assertEqual(
                    self.script._linux_directory_is_local(PurePosixPath(path)), expected
                )

    def test_unreadable_or_missing_linux_mount_data_is_not_assumed_local(self) -> None:
        with mock.patch.object(
            Path, "read_text", side_effect=PermissionError("denied")
        ):
            self.assertFalse(
                self.script._linux_directory_is_local(PurePosixPath("/tmp"))
            )
        with mock.patch.object(Path, "read_text", return_value=""):
            self.assertFalse(
                self.script._linux_directory_is_local(PurePosixPath("/tmp"))
            )


if __name__ == "__main__":
    unittest.main()
