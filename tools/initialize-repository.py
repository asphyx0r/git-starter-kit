#!/usr/bin/env python3
"""Validate package system paths and prepare the unborn repository index."""

from __future__ import annotations

import argparse
import json
import logging
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from process_runner import run as run_process

INVENTORY = "_starter-kit-files.json"
CONTEXT = "tools/git-inventory-context"
CONTEXT_FILES = {
    "HEAD": b"ref: refs/heads/main\n",
    "objects/.gitkeep": b"",
    "refs/.gitkeep": b"",
}
GENERATED = frozenset(
    {
        INVENTORY,
        "starter-kit-manifest.json",
        "CHANGELOG.md",
        "VERSION",
        "manifest.json",
        "SHA256SUMS",
    }
)
REQUIRED = frozenset(
    {
        ".githooks/commit-msg",
        "commitlint.config.cjs",
        "tools/release-artifacts.py",
        "tools/git_objects.py",
        "tools/process_runner.py",
        "templates/release/repository-manifest.schema.json",
        *(f"{CONTEXT}/{name}" for name in CONTEXT_FILES),
    }
)


class InitializationError(RuntimeError):
    """A package cannot safely initialize a system-only repository."""


def run(command: list[str]) -> bytes:
    logging.debug("%s", " ".join(command))
    result = run_process(command, timeout=300)
    if result.returncode:
        raise InitializationError(
            result.stderr.decode("utf-8", errors="replace").strip()
            or f"Command failed: {command[0]}"
        )
    return result.stdout


def load_inventory(root: Path) -> dict[str, str]:
    resolved_root = root.resolve()
    inventory_path = root / INVENTORY
    if inventory_path.is_symlink() or not inventory_path.is_file():
        raise InitializationError(
            "Extract the composed starter release ZIP into a new directory; "
            f"its {INVENTORY} inventory is required. A source clone is not supported."
        )
    value = json.loads(inventory_path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or type(value.get("schemaVersion")) is not int
        or value["schemaVersion"] not in {1, 2, 3}
        or not isinstance(value.get("files"), list)
        or not value["files"]
    ):
        raise InitializationError(
            "Invalid package inventory; extract a complete release ZIP."
        )
    modes: dict[str, str] = {}
    seen: set[str] = set()
    for entry in value["files"]:
        if not isinstance(entry, dict):
            raise InitializationError("Invalid package inventory entry.")
        name, mode = entry.get("path"), entry.get("mode")
        if (
            not isinstance(name, str)
            or not name
            or "\\" in name
            or ":" in name
            or any(ord(character) < 32 for character in name)
            or name.startswith("/")
            or PurePosixPath(name).as_posix() != name
            or any(
                part in {".", "..", ".git"}
                or part.casefold() == ".git"
                or part.endswith((" ", "."))
                for part in name.split("/")
            )
            or name.casefold() in seen
            or name == INVENTORY
            or any(
                name.casefold() == generated.casefold() and name != generated
                for generated in GENERATED
            )
            or (name in GENERATED and mode != "100644")
            or not isinstance(mode, str)
            or mode not in {"100644", "100755"}
        ):
            raise InitializationError(
                f"Unsafe package path or mode: {name!r} / {mode!r}"
            )
        path = root / name
        if not path.resolve().is_relative_to(resolved_root):
            raise InitializationError(f"Package path resolves outside target: {name}")
        if (
            any(parent.is_symlink() for parent in (path, *path.parents))
            or not path.is_file()
        ):
            raise InitializationError(f"Missing or unsafe package file: {name}")
        seen.add(name.casefold())
        modes[name] = mode
    if (
        not REQUIRED.issubset(modes)
        or modes.get(".githooks/commit-msg") != "100755"
        or any(modes.get(f"{CONTEXT}/{name}") != "100644" for name in CONTEXT_FILES)
    ):
        raise InitializationError(
            "Release ZIP lacks required initializer tools or executable hook modes."
        )
    for name in GENERATED:
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise InitializationError(f"Unsafe generated system file: {name}")
        modes[name] = "100644"
    return modes


def validate_inventory_context(root: Path) -> Path:
    """Authenticate metadata before Git can hide it from the work-tree listing."""
    context = root / CONTEXT
    directories = {
        "": {"HEAD", "objects", "refs"},
        "objects": {".gitkeep"},
        "refs": {".gitkeep"},
    }
    try:
        for path in (root / "tools", *(context / name for name in directories)):
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or (
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                raise InitializationError(f"Unsafe inventory context directory: {path}")
        for name, children in directories.items():
            if {entry.name for entry in (context / name).iterdir()} != children:
                raise InitializationError(
                    f"Unexpected inventory context entries: {name}"
                )
        for name, expected in CONTEXT_FILES.items():
            path = context / name
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                or info.st_size != len(expected)
                or path.read_bytes() != expected
            ):
                raise InitializationError(
                    f"Modified or unsafe inventory context file: {name}"
                )
    except OSError as error:
        raise InitializationError(
            f"Missing or unreadable inventory context: {error}"
        ) from error
    return context


def committable_files(root: Path) -> set[str]:
    context = validate_inventory_context(root)
    command = ["git", "-C", str(root)]
    if not (root / ".git").exists():
        command.extend([f"--git-dir={context}", f"--work-tree={root}"])
    output = run(
        [*command, "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    )
    return {name.decode("utf-8") for name in output.split(b"\0") if name}


def validate(root: Path) -> dict[str, str]:
    modes = load_inventory(root)
    unexpected = committable_files(root) - modes.keys()
    if unexpected:
        raise InitializationError(
            "Application files cannot enter the initial system commit: "
            + ", ".join(sorted(unexpected))
            + ". Start application development after repository initialization. No file was removed."
        )
    # Schema validation is needed by release preparation before any first commit.
    import jsonschema  # type: ignore[import-untyped]

    try:
        jsonschema.Draft202012Validator.check_schema(
            json.loads(
                (
                    root / "templates/release/repository-manifest.schema.json"
                ).read_bytes()
            )
        )
    except jsonschema.SchemaError as error:
        raise InitializationError(
            "Release ZIP contains an invalid repository schema."
        ) from error

    return modes


def prepare_text(root: Path, tag: str, release_date: str) -> None:
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "All notable changes to this project will be documented in this file.\n\n"
        f"Initialisation du repository Git (version {tag[1:]}, {release_date[:10]} UTC).\n\n"
        "No tagged release entries have been documented yet.\n",
        encoding="utf-8",
        newline="\n",
    )


def prepare_index(root: Path, tag: str, release_date: str) -> None:
    modes = validate(root)
    prepare_text(root, tag, release_date)
    # Exact inventory paths prevent application files from being added implicitly.
    paths = sorted(name for name in modes if (root / name).is_file())
    if os.name != "nt":
        for name in paths:
            (root / name).chmod(0o755 if modes[name] == "100755" else 0o644)
    run(["git", "-C", str(root), "add", "--", *paths])
    for mode, option in (("100755", "--chmod=+x"), ("100644", "--chmod=-x")):
        selected = [name for name in paths if modes[name] == mode]
        if selected:
            run(["git", "-C", str(root), "update-index", option, "--", *selected])
    release_script = str(root / "tools/release-artifacts.py")
    run(
        [
            sys.executable,
            "-B",
            release_script,
            "--force",
            "prepare",
            "--kind",
            "repository",
            "--index",
            "--release-ref",
            tag,
            "--release-date",
            release_date,
            "--repository-root",
            str(root),
        ]
    )
    outputs = ["VERSION", "manifest.json", "SHA256SUMS"]
    run(["git", "-C", str(root), "add", "--", *outputs])
    run(["git", "-C", str(root), "update-index", "--chmod=-x", "--", *outputs])
    run(
        [
            sys.executable,
            "-B",
            release_script,
            "check",
            "--index",
            "--expected-ref",
            tag,
            "--repository-root",
            str(root),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="1.0.0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("operation", choices=("validate", "prepare"))
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--tag", default="v1.0.0")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING, format="%(message)s"
    )
    try:
        root = args.path.resolve()
        if args.dry_run:
            validate(root)
            print(
                f"Dry run: prepare system text and release artifacts from the main index for {args.tag}."
            )
        elif args.operation == "validate":
            validate(root)
        else:
            release_date = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            prepare_index(root, args.tag, release_date)
        return 0
    except (
        InitializationError,
        OSError,
        ValueError,
        ImportError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
