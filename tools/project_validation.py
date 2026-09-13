"""Select distributed core files and run explicit project checks in a snapshot."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

from process_runner import ProcessScope, run
from project_config import ConfigurationError, load_configuration

SYSTEM_PATHS = frozenset(
    {
        "_starter-kit-files.json",
        ".starter-kit-project.json",
        "starter-kit-manifest.json",
        "VERSION",
        "CHANGELOG.md",
        "SHA256SUMS",
        "manifest.json",
    }
)


def repository_scope(root: Path) -> str:
    """Distinguish source maintenance from a distributed consumer core."""
    configuration = load_configuration(root)
    if configuration.mode == "configured":
        return configuration.repository_role
    inventory = root / "_starter-kit-files.json"
    return "project" if inventory.exists() or inventory.is_symlink() else "source"


def core_paths(root: Path) -> frozenset[str]:
    """Read the package's exact ownership inventory, rejecting unsafe records."""
    root = root.resolve()
    inventory = root / "_starter-kit-files.json"
    if inventory.is_symlink():
        raise ValueError("Managed inventory must be a local regular file")
    try:
        value = json.loads(inventory.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read managed inventory: {error}") from error
    if (
        not isinstance(value, dict)
        or type(value.get("schemaVersion")) is not int
        or value["schemaVersion"] not in {1, 2, 3}
        or not isinstance(value.get("files"), list)
        or not value["files"]
    ):
        raise ValueError("Invalid managed inventory")
    paths: set[str] = set()
    seen: set[str] = set()
    for entry in value["files"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid managed inventory record")
        path = entry.get("path")
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or ":" in path
            or any(ord(c) < 32 for c in path)
            or PurePosixPath(path).is_absolute()
            or PurePosixPath(path).as_posix() != path
            or any(
                p in {".", ".."} or p.casefold() == ".git" or p.endswith((" ", "."))
                for p in path.split("/")
            )
            or path.casefold() in seen
            or not isinstance(entry.get("mode"), str)
            or entry["mode"] not in {"100644", "100755"}
        ):
            raise ValueError(f"Unsafe managed inventory path: {path!r}")
        target = root / path
        if not target.resolve().is_relative_to(root) or any(
            p.is_symlink() for p in (target, *target.parents)
        ):
            raise ValueError(f"Managed path escapes repository: {path}")
        seen.add(path.casefold())
        paths.add(path)
    return frozenset(paths | SYSTEM_PATHS)


def is_core_path(root: Path, path: str) -> bool:
    """Return ownership without assigning application directories to the core."""
    return repository_scope(root) == "source" or path.removeprefix("./") in core_paths(
        root
    )


def initial_system_only(root: Path) -> bool:
    """Prove a single root commit containing only managed and system files."""
    if repository_scope(root) != "project":
        return False
    parents = run(
        ["git", "--no-replace-objects", "-C", str(root), "cat-file", "-p", "HEAD"],
        timeout=10,
        text=True,
    )
    headers = parents.stdout.split("\n\n", 1)[0].splitlines()
    if (
        parents.returncode
        or not headers
        or any(line.startswith("parent ") for line in headers)
    ):
        return False
    listing = run(
        [
            "git",
            "--no-replace-objects",
            "-C",
            str(root),
            "ls-tree",
            "-rz",
            "--name-only",
            "HEAD",
        ],
        timeout=10,
        text=True,
    )
    names = set(listing.stdout.rstrip("\0").split("\0"))
    return listing.returncode == 0 and bool(names) and names <= core_paths(root)


def run_checks(
    root: Path,
    *,
    timeout: float = 900,
    platform: str | None = None,
    dry_run: bool = False,
) -> int:
    """Execute declared argv with a deadline and scoped descendant cleanup."""
    root = root.resolve()
    configuration = load_configuration(root)
    platform = platform or {"win32": "windows", "darwin": "macos"}.get(
        sys.platform, "linux"
    )
    print(
        "Automation state (configuration only): "
        + json.dumps(configuration.automations, sort_keys=True)
    )
    if configuration.mode == "legacy":
        print(
            "Project validation WARNING: legacy configuration; application validation was not run (no declared checks)."
        )
        return 0
    if not configuration.checks and initial_system_only(root):
        print("Project validation: non-applicable (proven initial system-only commit).")
        return 0
    if not configuration.checks:
        print(
            "Project validation WARNING: no checks configured; application validation was not run."
        )
        return 0
    status = 0
    for check in configuration.checks:
        if platform not in check.platforms:
            print(f"Project check {check.name}: not run on {platform}.")
            continue
        cwd = (root / check.working_directory).resolve()
        if (
            not cwd.is_relative_to(root)
            or not cwd.is_dir()
            or not os.access(cwd, os.R_OK | os.X_OK)
        ):
            print(
                f"Project check {check.name}: missing or escaped working directory.",
                file=sys.stderr,
            )
            status = 1
            continue
        if dry_run:
            print(
                f"Project check {check.name}: not run (read-only plan), cwd={check.working_directory}, argv={json.dumps(check.argv)}"
            )
            continue
        try:
            with ProcessScope(
                list(check.argv),
                timeout=timeout,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as scope:
                try:
                    stdout, stderr = scope.process.communicate(
                        timeout=scope.work_remaining()
                    )
                    if scope.expired.is_set():
                        raise subprocess.TimeoutExpired(check.argv, timeout)
                    returncode = scope.process.returncode
                except subprocess.TimeoutExpired:
                    scope.terminate()
                    scope.process.communicate(timeout=scope.remaining())
                    raise
            print(stdout, end="")
            print(stderr, end="", file=sys.stderr)
            print(
                f"Project check {check.name}: {'passed' if returncode == 0 else 'failed'}."
            )
            status |= int(returncode != 0)
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"Project check {check.name}: failed: {error}", file=sys.stderr)
            status = 1
    return status


def main(argv: list[str] | None = None) -> int:
    """Expose ownership and explicit project execution to hooks and CI."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--version", action="version", version="v1.0.0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--scope", action="store_true")
    parser.add_argument("--owns", metavar="PATH")
    parser.add_argument("--list-core", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout <= 0 or not math.isfinite(args.timeout):
        parser.error("--timeout must be positive and finite")
    try:
        if args.scope:
            scope = repository_scope(args.repository_root)
            if scope == "project":
                core_paths(args.repository_root)
            print(scope)
            return 0
        if args.owns is not None:
            return 0 if is_core_path(args.repository_root, args.owns) else 1
        if args.list_core:
            for path in sorted(core_paths(args.repository_root)):
                if (args.repository_root / path).is_file():
                    sys.stdout.write(path + "\0")
            return 0
        return run_checks(
            args.repository_root, timeout=args.timeout, dry_run=args.dry_run
        )
    except (ValueError, ConfigurationError, OSError) as error:
        print(f"Project validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
