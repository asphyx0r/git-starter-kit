#!/usr/bin/env python3
"""Executable compatibility facade for cumulative starter-kit upgrades."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
import time
from typing import Any

_facade_directory = str(Path(__file__).resolve().parent)
_facade_directory_added = _facade_directory not in sys.path
if _facade_directory_added:
    sys.path.insert(0, _facade_directory)
try:
    from starter_kit_upgrade.application import (
        apply_upgrade as _apply_upgrade,
    )
    from starter_kit_upgrade.application import create_rollback_archive
    from starter_kit_upgrade.application import require_planned_file_state
    from starter_kit_upgrade.application import (
        restore_snapshot as _restore_snapshot,
    )
    from starter_kit_upgrade.application import snapshot_file
    from starter_kit_upgrade.application import write_payload
    from starter_kit_upgrade.archive import TOOLKIT_MODULE_NAMES
    from starter_kit_upgrade.archive import build_toolkit
    from starter_kit_upgrade.archive import build_upgrade
    from starter_kit_upgrade.archive import load_upgrade
    from starter_kit_upgrade.archive import read_archive
    from starter_kit_upgrade.archive import require_package_provenance
    from starter_kit_upgrade.archive import updated_agent_rules_provenance
    from starter_kit_upgrade.archive import validate_new_package
    from starter_kit_upgrade.cli import build_parser
    from starter_kit_upgrade.cli import main as _main
    from starter_kit_upgrade.cli import plan_or_apply as _plan_or_apply
    from starter_kit_upgrade.common import ADOPTION_PATH
    from starter_kit_upgrade.common import BASE_PAYLOAD_PREFIX
    from starter_kit_upgrade.common import FILES_MANIFEST_PATH
    from starter_kit_upgrade.common import FileSnapshot
    from starter_kit_upgrade.common import LOG_DIRECTORY
    from starter_kit_upgrade.common import LOG_FILENAME_TIMESTAMP_FORMAT
    from starter_kit_upgrade.common import LOG_TIMESTAMP_FORMAT
    from starter_kit_upgrade.common import MAX_ARCHIVE_SIZE
    from starter_kit_upgrade.common import PAYLOAD_PREFIX
    from starter_kit_upgrade.common import PROVENANCE_PATH
    from starter_kit_upgrade.common import RunJournal as _RunJournal
    from starter_kit_upgrade.common import SEMVER_TAG_PATTERN
    from starter_kit_upgrade.common import STARTER_MANIFEST_PATH
    from starter_kit_upgrade.common import UPGRADE_MANIFEST_PATH
    from starter_kit_upgrade.common import UpgradeError
    from starter_kit_upgrade.common import VERSION
    from starter_kit_upgrade.common import canonical_sha256
    from starter_kit_upgrade.common import canonicalize_text
    from starter_kit_upgrade.common import content_metadata
    from starter_kit_upgrade.common import load_json_bytes
    from starter_kit_upgrade.common import local_now
    from starter_kit_upgrade.common import log_archive_contents
    from starter_kit_upgrade.common import log_managed_entries
    from starter_kit_upgrade.common import sha256_bytes
    from starter_kit_upgrade.common import sha256_file
    from starter_kit_upgrade.common import starter_commit
    from starter_kit_upgrade.common import starter_release_tag
    from starter_kit_upgrade.common import validate_relative_path
    from starter_kit_upgrade.common import write_json
    from starter_kit_upgrade.planning import evaluate_target
    from starter_kit_upgrade.planning import exact_release_alignment
    from starter_kit_upgrade.planning import merge_text_payload
    from starter_kit_upgrade.planning import normalized_starter_manifest
    from starter_kit_upgrade.planning import operational_compliance
    from starter_kit_upgrade.planning import parse_starter_manifest
    from starter_kit_upgrade.planning import print_plan
    from starter_kit_upgrade.planning import run_git
    from starter_kit_upgrade.planning import starter_manifest_action
    from starter_kit_upgrade.planning import starter_release_from_provenance
    from starter_kit_upgrade.planning import target_adoption_is_current
    from starter_kit_upgrade.planning import target_path
    from starter_kit_upgrade.planning import updated_starter_manifest
    from starter_kit_upgrade.planning import validate_adoption
finally:
    if _facade_directory_added:
        sys.path.remove(_facade_directory)
del _facade_directory
del _facade_directory_added


class RunJournal(_RunJournal):
    """Journal adapter preserving the facade's patchable clock."""

    def _now(self) -> datetime:
        return local_now()


def restore_snapshot(path: Path, snapshot: FileSnapshot) -> None:
    """Restore through the facade's patchable payload writer."""
    _restore_snapshot(path, snapshot, payload_writer=write_payload)


def apply_upgrade(
    manifest: dict[str, Any],
    files: dict[str, bytes],
    root: Path,
    plan: dict[str, Any],
    backup_directory: Path,
    journal: RunJournal | None = None,
) -> Path:
    """Apply through the facade's patchable payload writer."""
    return _apply_upgrade(
        manifest,
        files,
        root,
        plan,
        backup_directory,
        journal,
        payload_writer=write_payload,
    )


def plan_or_apply(
    args: argparse.Namespace,
    journal: RunJournal | None = None,
) -> int:
    """Plan or apply through the facade's patchable payload writer."""
    return _plan_or_apply(
        args,
        journal,
        payload_writer=write_payload,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the CLI through the facade's patchable dependencies."""
    return _main(
        argv,
        journal_factory=RunJournal,
        payload_writer=write_payload,
    )


__all__ = [
    "ADOPTION_PATH",
    "BASE_PAYLOAD_PREFIX",
    "FILES_MANIFEST_PATH",
    "FileSnapshot",
    "LOG_DIRECTORY",
    "LOG_FILENAME_TIMESTAMP_FORMAT",
    "LOG_TIMESTAMP_FORMAT",
    "MAX_ARCHIVE_SIZE",
    "PAYLOAD_PREFIX",
    "PROVENANCE_PATH",
    "RunJournal",
    "SEMVER_TAG_PATTERN",
    "STARTER_MANIFEST_PATH",
    "TOOLKIT_MODULE_NAMES",
    "UPGRADE_MANIFEST_PATH",
    "UpgradeError",
    "VERSION",
    "apply_upgrade",
    "build_parser",
    "build_toolkit",
    "build_upgrade",
    "canonical_sha256",
    "canonicalize_text",
    "content_metadata",
    "create_rollback_archive",
    "evaluate_target",
    "exact_release_alignment",
    "load_json_bytes",
    "load_upgrade",
    "local_now",
    "log_archive_contents",
    "log_managed_entries",
    "main",
    "merge_text_payload",
    "normalized_starter_manifest",
    "operational_compliance",
    "os",
    "parse_starter_manifest",
    "plan_or_apply",
    "print_plan",
    "read_archive",
    "require_package_provenance",
    "require_planned_file_state",
    "restore_snapshot",
    "run_git",
    "sha256_bytes",
    "sha256_file",
    "snapshot_file",
    "starter_commit",
    "starter_manifest_action",
    "starter_release_from_provenance",
    "starter_release_tag",
    "target_adoption_is_current",
    "target_path",
    "time",
    "updated_agent_rules_provenance",
    "updated_starter_manifest",
    "validate_adoption",
    "validate_new_package",
    "validate_relative_path",
    "write_json",
    "write_payload",
]


if __name__ == "__main__":
    raise SystemExit(main())
