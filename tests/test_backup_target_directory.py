from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
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
            original_link = self.script.os.link
            original_replace = Path.replace

            def link_after_concurrent_create(source: Path, target: Path) -> None:
                self.assertTrue(source.is_file())
                target.write_bytes(concurrent_contents)
                original_link(source, target)

            def replace_after_concurrent_create(
                source: Path,
                target: Path,
            ) -> Path:
                self.assertTrue(source.is_file())
                target.write_bytes(concurrent_contents)
                return original_replace(source, target)

            with (
                mock.patch.object(
                    self.script.os,
                    "link",
                    side_effect=link_after_concurrent_create,
                ),
                mock.patch.object(
                    Path,
                    "replace",
                    autospec=True,
                    side_effect=replace_after_concurrent_create,
                ),
                self.assertRaisesRegex(
                    self.script.BackupError,
                    "Target archive already exists",
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


if __name__ == "__main__":
    unittest.main()
