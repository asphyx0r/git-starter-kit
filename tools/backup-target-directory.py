#!/usr/bin/env python3
"""Back up a source directory tree into a staged Zip archive."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from typing import TextIO

SCRIPT_NAME = "backup-target-directory.py"
VERSION = "0.1.0"
DESCRIPTION = "Back up a source directory tree into a staged Zip archive."
DEFAULT_HEAD = "000000000000"
DEFAULT_SEMVER_TAG = "v0.0.0"
MAX_COMPRESSION = 9
HELP_WIDTH = 120
HELP_MAX_POSITION = 25
KNOWN_OPTION_STRINGS = frozenset(
    (
        "-b",
        "-d",
        "-h",
        "-t",
        "-v",
        "--buffer-directory",
        "--dry-run",
        "--help",
        "--source-directory",
        "--target-directory",
        "--verbose",
        "--version",
    )
)
PATH_OPTION_STRINGS = frozenset(
    (
        "-b",
        "-d",
        "-t",
        "--buffer-directory",
        "--source-directory",
        "--target-directory",
    )
)
EMBEDDED_OPTION_PATTERN = re.compile(
    r"\s+("
    r"-[bdhtv]"
    r"|--buffer-directory"
    r"|--dry-run"
    r"|--help"
    r"|--source-directory"
    r"|--target-directory"
    r"|--verbose"
    r"|--version"
    r")(?=\s|$)"
)
SEMVER_TAG_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(-((0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"
)
HEAD_PATTERN = re.compile(r"^[0-9a-f]{12}$")


class BackupError(Exception):
    """Raised when the backup cannot proceed safely."""


@dataclass(frozen=True)
class Logger:
    """Small stdout logger with fixed labels required by the CLI contract."""

    verbose: bool
    stream: TextIO

    def debug(self, message: str) -> None:
        if self.verbose:
            self._write("DEBUG", message)

    def info(self, message: str) -> None:
        self._write("INFO ", message)

    def warn(self, message: str) -> None:
        self._write("WARN ", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)

    def fatal(self, message: str) -> None:
        self._write("FATAL", message)

    def _write(self, level: str, message: str) -> None:
        print(f"[{level}] {message}", file=self.stream)


class StdoutArgumentParser(argparse.ArgumentParser):
    """Argument parser that keeps all user-facing output on stdout."""

    def format_help(self) -> str:
        return f"{SCRIPT_NAME} v{VERSION}\n\n{super().format_help()}"

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:
        if message:
            self._print_message(message, sys.stdout)
        raise SystemExit(status)

    def error(self, message: str) -> None:
        self.print_usage(sys.stdout)
        self.exit(2, f"{self.prog}: error: {message}\n")


def build_help_formatter(prog: str) -> argparse.HelpFormatter:
    return argparse.HelpFormatter(
        prog,
        max_help_position=HELP_MAX_POSITION,
        width=HELP_WIDTH,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = StdoutArgumentParser(
        prog=SCRIPT_NAME,
        description=DESCRIPTION,
        formatter_class=build_help_formatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=VERSION,
        help="show version and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="simulate execution without modifying data",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable DEBUG logs",
    )
    parser.add_argument(
        "-d",
        "--source-directory",
        required=True,
        metavar="BASEDIR",
        help="existing source directory tree to back up",
    )
    parser.add_argument(
        "-t",
        "--target-directory",
        required=True,
        metavar="TARGETDIR",
        help="existing directory where the Zip archive will be created",
    )
    parser.add_argument(
        "-b",
        "--buffer-directory",
        metavar="BUFFERDIR",
        help="existing staging parent directory; defaults to the user temp directory",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    raw_argv = sys.argv[1:] if argv is None else argv
    normalized_argv = normalize_escaped_windows_args(raw_argv)
    try:
        args = parser.parse_args(normalized_argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    logger = Logger(verbose=args.verbose, stream=sys.stdout)
    try:
        run_backup(
            source_directory=Path(args.source_directory),
            target_directory=Path(args.target_directory),
            buffer_directory=(
                Path(args.buffer_directory)
                if args.buffer_directory is not None
                else None
            ),
            dry_run=args.dry_run,
            logger=logger,
        )
    except BackupError as exc:
        logger.fatal(str(exc))
        return 1
    except OSError as exc:
        logger.fatal(f"Filesystem error: {exc}")
        return 1

    return 0


def normalize_escaped_windows_args(argv: list[str]) -> list[str]:
    split_args = []
    for argument in argv:
        split_args.extend(split_escaped_option_argument(argument))
    return join_split_path_option_values(split_args)


def split_escaped_option_argument(argument: str) -> list[str]:
    if '"' not in argument:
        return [argument]

    parts = EMBEDDED_OPTION_PATTERN.split(argument)
    if len(parts) == 1:
        return [strip_edge_quotes(argument)]

    repaired_args = []
    for part in parts:
        if not part:
            continue
        if part in KNOWN_OPTION_STRINGS:
            repaired_args.append(part)
        else:
            repaired_args.append(strip_edge_quotes(part))
    return repaired_args


def strip_edge_quotes(argument: str) -> str:
    return argument.strip().strip('"')


def join_split_path_option_values(argv: list[str]) -> list[str]:
    repaired_args = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        repaired_args.append(argument)
        index += 1

        if argument not in PATH_OPTION_STRINGS or index >= len(argv):
            continue

        value_parts = []
        while index < len(argv) and argv[index] not in KNOWN_OPTION_STRINGS:
            value_parts.append(strip_edge_quotes(argv[index]))
            index += 1

        if value_parts:
            repaired_args.append(" ".join(value_parts))

    return repaired_args


def run_backup(
    source_directory: Path,
    target_directory: Path,
    buffer_directory: Optional[Path],
    dry_run: bool,
    logger: Logger,
) -> None:
    if _is_linux_root():
        raise BackupError("This script must not run as root on Linux.")

    logger.debug("Validating source and target directories.")
    source = resolve_directory(
        source_directory,
        "Source directory",
        reject_symlink=True,
    )
    target = resolve_directory(target_directory, "Target directory")
    validate_source_tree(source)
    validate_target_location(source, target)

    backup_head, backup_tag = resolve_git_identity(source)
    log_git_identity(backup_head, backup_tag, logger)
    timestamp = current_timestamp()
    archive_name = build_archive_name(
        source.name,
        timestamp,
        backup_head,
        backup_tag,
    )
    archive_path = target / archive_name

    if archive_path.exists():
        raise BackupError(f"Target archive already exists: {archive_path}")

    buffer_parent = select_buffer_parent(source, buffer_directory, logger)
    logger.info(f"Using source directory: {source}")
    logger.info(f"Using target directory: {target}")
    logger.info(f"Using staging parent: {buffer_parent}")
    logger.info(f"Backup archive: {archive_path}")

    if dry_run:
        logger.info(f"Would stage source directory: {source}")
        logger.info(f"Would create Zip archive: {archive_path}")
        logger.info("Dry run completed without modifying data.")
        return

    with tempfile.TemporaryDirectory(
        prefix=f"{sanitize_name(source.name)}-",
        dir=str(buffer_parent),
    ) as staging_parent_name:
        staging_parent = Path(staging_parent_name)
        staged_source = staging_parent / source.name
        logger.debug(f"Copying source tree to staging directory: {staged_source}")
        shutil.copytree(source, staged_source, copy_function=shutil.copy2)
        logger.info(f"Staged source directory: {staged_source}")

        if resolve_git_identity(source) != (backup_head, backup_tag):
            raise BackupError(
                "Source Git identity changed during staging; "
                "no archive was created."
            )

        logger.debug("Creating Zip archive from staged data.")
        create_archive(staged_source, archive_path)
        logger.info(f"Created Zip archive: {archive_path}")


def resolve_directory(
    directory: Path,
    label: str,
    reject_symlink: bool = False,
) -> Path:
    expanded_directory = directory.expanduser()
    if not expanded_directory.exists():
        raise BackupError(f"{label} does not exist: {expanded_directory}")
    if reject_symlink and expanded_directory.is_symlink():
        raise BackupError(f"{label} must not be a symbolic link: {expanded_directory}")
    if not expanded_directory.is_dir():
        raise BackupError(f"{label} is not a directory: {expanded_directory}")
    return expanded_directory.resolve(strict=True)


def validate_source_tree(source: Path) -> None:
    if source.is_symlink():
        raise BackupError(f"Source directory must not be a symbolic link: {source}")

    for root_name, directory_names, file_names in os.walk(source):
        root = Path(root_name)
        for entry_name in [*directory_names, *file_names]:
            entry = root / entry_name
            if entry.is_symlink():
                raise BackupError(f"Source tree contains a symbolic link: {entry}")


def validate_target_location(source: Path, target: Path) -> None:
    if is_relative_to(target, source):
        raise BackupError("Target directory must not be inside the source directory.")
    if not is_accessible_directory(target):
        raise BackupError(f"Target directory is not accessible: {target}")


def resolve_git_identity(source: Path) -> tuple[str, str]:
    head_output = run_git(source, "rev-parse", "--short=12", "HEAD")
    if head_output is None:
        return DEFAULT_HEAD, DEFAULT_SEMVER_TAG

    head = head_output.strip()
    if not HEAD_PATTERN.fullmatch(head):
        return DEFAULT_HEAD, DEFAULT_SEMVER_TAG

    tag_output = run_git(
        source,
        "tag",
        "--sort=-creatordate",
        "--points-at",
        head,
    )
    if tag_output is None:
        return head, DEFAULT_SEMVER_TAG

    for tag in tag_output.splitlines():
        if SEMVER_TAG_PATTERN.fullmatch(tag):
            return head, tag

    return head, DEFAULT_SEMVER_TAG


def log_git_identity(head: str, semver_tag: str, logger: Logger) -> None:
    if head == DEFAULT_HEAD:
        logger.warn(
            "No readable Git commit found for source; using "
            f"{DEFAULT_HEAD} and {DEFAULT_SEMVER_TAG}."
        )
        return

    logger.debug(f"Resolved Git HEAD: {head}")
    if semver_tag == DEFAULT_SEMVER_TAG:
        logger.warn(
            f"No SemVer tag points to source HEAD; using {DEFAULT_SEMVER_TAG}."
        )
        return

    logger.debug(f"Resolved SemVer tag for HEAD: {semver_tag}")


def run_git(directory: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None
    return result.stdout


def current_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def build_archive_name(
    source_name: str,
    timestamp: str,
    head: str,
    semver_tag: str,
) -> str:
    safe_source_name = sanitize_name(source_name)
    if not safe_source_name:
        raise BackupError(f"Source directory name cannot be used in an archive name: {source_name}")
    return f"{safe_source_name}-{timestamp}-{head}-{semver_tag}.zip"


def sanitize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    safe_name = re.sub(r"[^a-z0-9]+", "-", ascii_name)
    safe_name = re.sub(r"-{2,}", "-", safe_name)
    return safe_name.strip("-")


def select_buffer_parent(
    source: Path,
    buffer_directory: Optional[Path],
    logger: Logger,
) -> Path:
    if buffer_directory is not None:
        buffer_parent = resolve_optional_buffer(buffer_directory, source, logger)
        if buffer_parent is not None:
            return buffer_parent

    default_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    if is_relative_to(default_parent, source):
        raise BackupError("Default temporary directory is inside the source directory.")
    if not is_accessible_directory(default_parent):
        raise BackupError(f"Default temporary directory is not accessible: {default_parent}")
    return default_parent


def resolve_optional_buffer(
    buffer_directory: Path,
    source: Path,
    logger: Logger,
) -> Optional[Path]:
    expanded_buffer = buffer_directory.expanduser()
    if not expanded_buffer.exists():
        logger.warn(f"Buffer directory does not exist; using default temporary directory: {expanded_buffer}")
        return None
    if not expanded_buffer.is_dir():
        logger.warn(f"Buffer path is not a directory; using default temporary directory: {expanded_buffer}")
        return None

    buffer_parent = expanded_buffer.resolve(strict=True)
    if is_relative_to(buffer_parent, source):
        logger.warn(f"Buffer directory is inside source; using default temporary directory: {buffer_parent}")
        return None
    if not is_accessible_directory(buffer_parent):
        logger.warn(f"Buffer directory is not accessible; using default temporary directory: {buffer_parent}")
        return None
    return buffer_parent


def is_accessible_directory(directory: Path) -> bool:
    return os.access(str(directory), os.R_OK | os.W_OK | os.X_OK)


def create_archive(staged_source: Path, archive_path: Path) -> None:
    temp_archive = archive_path.with_name(
        f".{archive_path.stem}.{uuid.uuid4().hex}.zip.tmp"
    )
    try:
        write_zip_from_staged_tree(staged_source, temp_archive)
        if archive_path.exists():
            raise BackupError(f"Target archive already exists: {archive_path}")
        temp_archive.replace(archive_path)
    except Exception:
        if temp_archive.exists():
            temp_archive.unlink()
        raise


def write_zip_from_staged_tree(staged_source: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=MAX_COMPRESSION,
    ) as archive:
        add_directory_entry(archive, staged_source.name)
        for directory in sorted(path for path in staged_source.rglob("*") if path.is_dir()):
            add_directory_entry(
                archive,
                f"{staged_source.name}/{directory.relative_to(staged_source).as_posix()}",
            )
        for file_path in sorted(path for path in staged_source.rglob("*") if path.is_file()):
            archive.write(
                file_path,
                f"{staged_source.name}/{file_path.relative_to(staged_source).as_posix()}",
            )


def add_directory_entry(archive: zipfile.ZipFile, archive_name: str) -> None:
    directory_name = archive_name.rstrip("/") + "/"
    directory_info = zipfile.ZipInfo(directory_name)
    directory_info.external_attr = 0o40755 << 16
    archive.writestr(directory_info, "")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_linux_root() -> bool:
    return (
        sys.platform.startswith("linux")
        and hasattr(os, "geteuid")
        and os.geteuid() == 0
    )


if __name__ == "__main__":
    sys.exit(main())
