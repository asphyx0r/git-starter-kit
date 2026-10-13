#!/usr/bin/env python3
"""Patch, attest, and audit the locked npm development dependencies."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


VERSION = "0.1.0"
PATCH_ROOT = Path(__file__).resolve().parent / "patches/braces-3.0.3"
ADVISORY = "GHSA-vfj7-8cjw-p6xm"


def regular_file(path: Path) -> None:
    """Reject symbolic links and Windows reparse points before reading."""
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Unsafe linked path: {part}")
    if not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")


def digest(path: Path) -> str:
    regular_file(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> dict[str, Any]:
    """Validate the fixed package's recorded provenance and replacement bytes."""
    path = PATCH_ROOT / "manifest.json"
    regular_file(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value["package"] != "braces"
        or value["version"] != "3.0.3"
        or value["advisory"] != ADVISORY
        or value["sourceUrl"] != "https://registry.npmjs.org/braces/-/braces-3.0.3.tgz"
        or not isinstance(value["files"], dict)
        or not value["files"]
    ):
        raise ValueError("Invalid braces patch provenance")
    for name, record in value["files"].items():
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or relative.as_posix() != name
            or "\\" in name
            or ":" in name
            or any(part in {".", "..", ".git"} for part in name.split("/"))
            or set(record) != {"beforeSha256", "afterSha256"}
            or any(
                not isinstance(checksum, str)
                or len(checksum) != 64
                or any(character not in "0123456789abcdef" for character in checksum)
                for checksum in record.values()
            )
        ):
            raise ValueError(f"Invalid patch file record: {name}")
        if record["beforeSha256"] != record["afterSha256"]:
            if digest(PATCH_ROOT / name) != record["afterSha256"]:
                raise ValueError(f"Patch payload integrity mismatch: {name}")
    return value


def package_paths(root: Path, manifest: dict[str, Any]) -> list[Path]:
    """Select every locked braces occurrence with the original npm integrity."""
    path = root / "package-lock.json"
    regular_file(path)
    lock = json.loads(path.read_text(encoding="utf-8"))
    paths = []
    for name, record in lock["packages"].items():
        if name != "node_modules/braces" and not name.endswith("/node_modules/braces"):
            continue
        if (
            not name.startswith("node_modules/")
            or PurePosixPath(name).as_posix() != name
            or "\\" in name
            or ":" in name
            or any(part in {".", "..", ".git"} for part in name.split("/"))
            or record.get("version") != manifest["version"]
            or record.get("integrity") != manifest["sourceIntegrity"]
        ):
            raise ValueError(f"Unattested braces lock entry: {name}")
        paths.append(root / name)
    if not paths:
        raise ValueError("No locked braces 3.0.3 occurrence to attest")
    installed = set()

    def walk_error(error: OSError) -> None:
        raise error

    for directory, children, _ in os.walk(
        root / "node_modules", followlinks=False, onerror=walk_error
    ):
        folder = Path(directory)
        for child in [folder, *(folder / name for name in children)]:
            info = child.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError(f"Unsafe linked dependency directory: {child}")
        if folder.name == "node_modules" and "braces" in children:
            installed.add(folder / "braces")
    if installed != set(paths):
        raise ValueError("Missing or unlocked installed braces occurrence")
    return paths


def validate_package(package: Path, manifest: dict[str, Any], *, patched: bool) -> None:
    """Check the whole installed package, not only the changed functions."""
    actual: set[str] = set()
    for directory, children, names in os.walk(package, followlinks=False):
        children[:] = [name for name in children if name != "node_modules"]
        for name in children:
            child = Path(directory) / name
            info = child.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError(f"Unsafe linked package directory: {child}")
        actual.update(
            (Path(directory) / name).relative_to(package).as_posix() for name in names
        )
    if actual != set(manifest["files"]):
        raise ValueError(f"Unexpected installed braces files: {package}")
    for name, record in manifest["files"].items():
        checksum = digest(package / name)
        allowed = {record["afterSha256"]}
        if not patched:
            allowed.add(record["beforeSha256"])
        if checksum not in allowed:
            raise ValueError(f"Installed braces integrity mismatch: {package / name}")


def replace_file(path: Path, content: bytes, mode: int) -> None:
    """Replace one file atomically without leaving a staging file."""
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(name)
    failure: BaseException | None = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as error:
            if failure is None:
                raise
            failure.add_note(f"Patch staging cleanup failed: {temporary}: {error}")


def verify(root: Path) -> list[Path]:
    """Return occurrences only after complete installed-code attestation."""
    manifest = load_manifest()
    packages = package_paths(root, manifest)
    for package in packages:
        validate_package(package, manifest, patched=True)
    return packages


def patch(root: Path, *, dry_run: bool = False) -> list[Path]:
    """Apply the fixed payloads with idempotence and interruption rollback."""
    manifest = load_manifest()
    packages = package_paths(root, manifest)
    for package in packages:
        validate_package(package, manifest, patched=False)
    originals: dict[Path, tuple[bytes, int, str]] = {}
    try:
        for package in packages:
            for name, record in manifest["files"].items():
                destination = package / name
                checksum = digest(destination)
                if checksum == record["afterSha256"]:
                    continue
                if checksum != record["beforeSha256"]:
                    raise ValueError(
                        f"Installed braces changed during patch: {destination}"
                    )
                if dry_run:
                    continue
                original = destination.read_bytes()
                if hashlib.sha256(original).hexdigest() != record["beforeSha256"]:
                    raise ValueError(
                        f"Installed braces changed during patch: {destination}"
                    )
                payload = (PATCH_ROOT / name).read_bytes()
                if hashlib.sha256(payload).hexdigest() != record["afterSha256"]:
                    raise ValueError(
                        f"Patch payload changed during application: {name}"
                    )
                originals[destination] = (
                    original,
                    stat.S_IMODE(destination.stat().st_mode),
                    record["afterSha256"],
                )
                replace_file(
                    destination,
                    payload,
                    originals[destination][1],
                )
        if not dry_run:
            verify(root)
    except BaseException as error:
        for path, (content, mode, applied_hash) in reversed(list(originals.items())):
            try:
                checksum = digest(path)
                if checksum == hashlib.sha256(content).hexdigest():
                    continue
                if checksum != applied_hash:
                    raise ValueError(
                        "Concurrent change preserved; manual restoration required"
                    )
                replace_file(path, content, mode)
            except BaseException as rollback_error:
                error.add_note(f"Patch rollback incomplete: {path}: {rollback_error}")
        raise
    return packages


def evaluate_audit(report: dict[str, Any], patched_nodes: set[str]) -> dict[str, Any]:
    """Attest only high findings whose complete graph leads to this fixed advisory."""
    if (
        not isinstance(report, dict)
        or report.get("auditReportVersion") != 2
        or "error" in report
    ):
        raise ValueError("Invalid or failed npm audit report")
    vulnerabilities = report.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        raise ValueError("Missing npm vulnerability graph")
    counts = dict.fromkeys(("info", "low", "moderate", "high", "critical"), 0)
    for name, record in vulnerabilities.items():
        if (
            not isinstance(record, dict)
            or record.get("name") != name
            or record.get("severity") not in counts
            or not isinstance(record.get("via"), list)
            or not record["via"]
            or not isinstance(record.get("nodes"), list)
            or not record["nodes"]
            or any(not isinstance(node, str) for node in record["nodes"])
        ):
            raise ValueError(f"Invalid npm vulnerability record: {name}")
        counts[record["severity"]] += 1
    counts["total"] = len(vulnerabilities)
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("vulnerabilities") != counts:
        raise ValueError("Inconsistent npm vulnerability counts")

    attested: dict[str, bool] = {}
    active: set[str] = set()
    for root in vulnerabilities:
        stack = [(root, False)]
        while stack:
            name, exiting = stack.pop()
            if name in attested:
                continue
            if name not in vulnerabilities:
                raise ValueError(f"Missing npm attribution: {name}")
            record = vulnerabilities[name]
            links = [via for via in record["via"] if isinstance(via, str)]
            if exiting:
                leaves = [via for via in record["via"] if not isinstance(via, str)]
                leaf_matches = all(
                    isinstance(via, dict)
                    and via.get("name") == "braces"
                    and via.get("url") == f"https://github.com/advisories/{ADVISORY}"
                    and name == "braces"
                    for via in leaves
                )
                nodes_match = name != "braces" or set(record["nodes"]) == patched_nodes
                attested[name] = (
                    record["severity"] == "high"
                    and leaf_matches
                    and nodes_match
                    and all(attested[link] for link in links)
                )
                active.remove(name)
            else:
                if name in active:
                    raise ValueError(f"Cyclic npm attribution: {name}")
                active.add(name)
                stack.append((name, True))
                stack.extend((link, False) for link in links)
    blocking = [
        name
        for name, record in vulnerabilities.items()
        if record["severity"] in {"high", "critical"} and not attested[name]
    ]
    return {
        "rawReport": report,
        "rawCounts": counts,
        "attested": sorted(name for name, matched in attested.items() if matched),
        "blocked": sorted(blocking),
        "advisory": ADVISORY,
    }


def audit(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Run the registry audit within a bounded process tree and isolated cache."""
    packages = verify(root)
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise ValueError("Node.js and npm must already be installed")
    npm_path = Path(npm).resolve()
    npm_cli = (
        npm_path
        if npm_path.suffix == ".js"
        else npm_path.parent / "node_modules/npm/bin/npm-cli.js"
    )
    if not npm_cli.is_file():
        raise ValueError(f"Cannot locate the npm CLI beside {npm_path}")
    command = [
        node,
        str(npm_cli),
        "audit",
        "--json",
        "--include=dev",
        "--prefix",
        str(root),
    ]
    if dry_run:
        return {"operation": "audit", "dryRun": True, "command": command, "blocked": []}
    helper_path = Path(__file__).resolve().parents[1] / "process_runner.py"
    spec = importlib.util.spec_from_file_location("npm_process_runner", helper_path)
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    with tempfile.TemporaryDirectory(prefix="npm-security-") as cache:
        with helper.ProcessScope(
            [*command, "--cache", cache],
            timeout=120,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(os.environ, NPM_CONFIG_IGNORE_SCRIPTS="true"),
        ) as scope:
            stdout, stderr = scope.process.communicate(timeout=scope.work_remaining())
            if scope.expired.is_set():
                raise subprocess.TimeoutExpired(command, 120, stdout, stderr)
            if scope.process.returncode not in {0, 1}:
                raise ValueError(
                    f"npm audit failed ({scope.process.returncode}): {stderr.strip()}"
                )
    report = json.loads(stdout)
    packages = verify(root)
    return evaluate_audit(
        report,
        {package.relative_to(root).as_posix() for package in packages},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("patch", "verify", "audit"):
        command = commands.add_parser(name)
        command.add_argument("--quality-root", type=Path, default=Path(__file__).parent)
        command.add_argument(
            "--dry-run", action="store_true", default=argparse.SUPPRESS
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            result = audit(args.quality_root.absolute(), dry_run=args.dry_run)
            print(json.dumps(result, indent=2))
            return int(bool(result["blocked"]))
        packages = (
            patch(args.quality_root.absolute(), dry_run=args.dry_run)
            if args.command == "patch"
            else verify(args.quality_root.absolute())
        )
        print(
            json.dumps(
                {
                    "operation": args.command,
                    "advisory": ADVISORY,
                    "occurrences": len(packages),
                    "dryRun": args.dry_run,
                }
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        if args.verbose:
            raise
        print(f"npm security: {error}", file=sys.stderr)
        for note in getattr(error, "__notes__", []):
            print(note, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
