"""Command-line parsing and orchestration for starter upgrades."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from typing import Callable

from .application import apply_upgrade
from .archive import (
    build_toolkit,
    build_upgrade,
    load_upgrade,
)
from .common import (
    VERSION,
    RunJournal,
    UpgradeError,
    log_archive_contents,
    starter_commit,
    starter_release_tag,
)
from .planning import (
    evaluate_target,
    exact_release_alignment,
    operational_compliance,
    print_plan,
    target_adoption_is_current,
)


def plan_or_apply(
    args: argparse.Namespace,
    journal: RunJournal | None = None,
    *,
    payload_writer: Callable[[Path, bytes, str], None] | None = None,
) -> int:
    upgrade_path = args.upgrade_package.resolve()
    root = args.target.resolve()
    if journal is not None:
        journal.phase("preflight", "START")
        journal.write("INFO", "preflight", f"UPGRADE_PACKAGE={upgrade_path}")
        journal.write("INFO", "preflight", f"TARGET={root}")
        if args.command == "apply":
            journal.write(
                "INFO",
                "preflight",
                f"BACKUP_DIRECTORY={args.backup_directory.resolve()}",
            )
        journal.phase("archive-validation", "START")
    manifest, files = load_upgrade(upgrade_path)
    target_provenance = manifest["target"]["provenance"]
    base_provenance = manifest["base"]["provenance"]
    target_release = starter_release_tag(target_provenance, "Upgrade target")
    if journal is not None:
        journal.bind_target_release(target_release)
        log_archive_contents(journal, "upgrade-package", upgrade_path, files)
        journal.write(
            "INFO",
            "provenance",
            "BASE_RELEASE=" + starter_release_tag(base_provenance, "Upgrade base"),
        )
        journal.write(
            "INFO",
            "provenance",
            f"BASE_STARTER_COMMIT={starter_commit(base_provenance)}",
        )
        journal.write(
            "INFO",
            "provenance",
            f"TARGET_STARTER_COMMIT={starter_commit(target_provenance)}",
        )
        journal.phase("archive-validation", "END")
        journal.phase("preflight", "END")
    plan = evaluate_target(manifest, files, root, journal)
    alignment = exact_release_alignment(plan)
    if args.command == "plan" or args.dry_run:
        if journal is not None:
            if plan["applicable"]:
                plan_status = "READY"
                compliance = "READY"
            elif plan["provenance"] == "target":
                compliance = operational_compliance(plan)
                plan_status = (
                    "ALREADY_CURRENT" if compliance != "NON_COMPLIANT" else "BLOCKED"
                )
            else:
                plan_status = "BLOCKED"
                compliance = "NON_COMPLIANT"
            journal.write("INFO", "summary", f"PLAN_STATUS={plan_status}")
            journal.set_outcome("NOT_APPLIED", compliance, alignment)
        print_plan(plan)
        return 0 if plan["applicable"] else 1

    if not plan["applicable"] and journal is not None:
        journal.set_outcome("BLOCKED", "NON_COMPLIANT", alignment)
    backup_path = apply_upgrade(
        manifest,
        files,
        root,
        plan,
        args.backup_directory,
        journal,
        payload_writer=payload_writer,
    )
    if journal is not None:
        journal.phase("post-verification", "START")
    result = evaluate_target(manifest, files, root, journal)
    result["backup"] = str(backup_path)
    adoption_is_current = target_adoption_is_current(manifest, root, journal)
    compliance = operational_compliance(result, adoption_is_current)
    alignment = exact_release_alignment(result)
    if journal is not None:
        journal.write("INFO", "post-verification", f"BACKUP={backup_path}")
        journal.phase("post-verification", "END")
        journal.set_outcome("SUCCEEDED", compliance, alignment)
    print_plan(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="help", help="show help and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the execution plan without writing",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show additional diagnostics"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build a cumulative upgrade ZIP")
    build.add_argument("--base-package", type=Path, required=True)
    build.add_argument("--new-package", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)

    toolkit = subparsers.add_parser(
        "toolkit", help="bundle the updater and a new full package"
    )
    toolkit.add_argument("--new-package", type=Path, required=True)
    toolkit.add_argument("--output", type=Path, required=True)

    plan = subparsers.add_parser("plan", help="inspect a target without writing")
    plan.add_argument("--upgrade-package", type=Path, required=True)
    plan.add_argument("--target", type=Path, required=True)

    apply = subparsers.add_parser("apply", help="apply a conflict-free upgrade")
    apply.add_argument("--upgrade-package", type=Path, required=True)
    apply.add_argument("--target", type=Path, required=True)
    apply.add_argument("--backup-directory", type=Path, required=True)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    journal_factory: Callable[[str, list[str]], RunJournal] = RunJournal,
    payload_writer: Callable[[Path, bytes, str], None] | None = None,
) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    journal = None if args.dry_run else journal_factory(args.command, arguments)
    exit_code = 1
    try:
        if args.command == "build":
            exit_code = build_upgrade(args, journal)
        elif args.command == "toolkit":
            exit_code = build_toolkit(args, journal)
        else:
            exit_code = plan_or_apply(
                args,
                journal,
                payload_writer=payload_writer,
            )
    except (OSError, UpgradeError, subprocess.SubprocessError) as error:
        if journal is not None:
            journal.record_exception(error)
        if getattr(args, "verbose", False):
            raise
        print(f"Error: {error}", file=sys.stderr)
        exit_code = 1
    except BaseException as error:
        if journal is not None:
            journal.record_exception(error)
        raise
    finally:
        if journal is not None:
            journal.finalize(exit_code)
    return exit_code


__all__ = [
    "build_parser",
    "main",
    "plan_or_apply",
]
