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
from tempfile import TemporaryDirectory
from unittest import mock

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "backup-target-directory.py"
)


def load_script_module():
    spec = importlib.util.spec_from_file_location("backup_target_directory", SCRIPT_PATH)
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
                "source-with-spaces-20260718-125229-"
                "000000000000-v0.0.0.zip",
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

            archive_path = (
                target
                / "source-20260718-125229-ac42ebea5d4a-v1.0.0.zip"
            )
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
                target
                / "source-project-20260718-125229-"
                "ac42ebea5d4a-v1.0.0.zip"
            )
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("Source Project/data.txt", archive.namelist())

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

            archive_path = (
                target
                / f"repository-20260718-125229-{head}-v1.2.3.zip"
            )
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
