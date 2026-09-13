"""Select optional automations using the shared strict configuration reader."""

from __future__ import annotations

import argparse
import base64
import binascii
from collections.abc import Callable
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import quote

from project_config import (
    AUTOMATION_NAMES,
    CONFIGURATION_FILE,
    ConfigurationError,
    load_configuration,
    parse_configuration,
)


def automation_enabled(
    root: Path, automation: str, *, event: str, legacy_sync: str = ""
) -> bool:
    """Select activation; callers supply a trusted immutable repository snapshot."""
    configuration = load_configuration(root)
    if automation not in AUTOMATION_NAMES:
        raise ConfigurationError(f"Unknown automation: {automation}")
    if automation == "agentRulesSync":
        if configuration.mode == "legacy":
            return event == "release" or legacy_sync != "false"
        if event == "workflow_dispatch":
            return True
    return configuration.automations[automation]


def remote_guarded_merge_enabled(
    repository: str, branch: str, read_json: Callable[[list[str]], Any]
) -> bool:
    """Read the request target's config from one immutable default-branch commit."""
    try:
        commit = read_json(
            ["api", f"repos/{repository}/commits/{quote(branch, safe='')}"]
        )
        sha = commit["sha"]
        tree_sha = commit["commit"]["tree"]["sha"]
        if any(
            not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}", oid)
            for oid in (sha, tree_sha)
        ):
            raise ConfigurationError("Invalid trusted default-branch commit identity")
        tree = read_json(["api", f"repos/{repository}/git/trees/{tree_sha}"])
        if (
            tree.get("sha") != tree_sha
            or tree.get("truncated") is not False
            or not isinstance(tree.get("tree"), list)
        ):
            raise ConfigurationError("Invalid trusted configuration tree")
        entries = [
            entry for entry in tree["tree"] if entry["path"] == CONFIGURATION_FILE
        ]
        content = None
        if entries:
            if (
                len(entries) != 1
                or entries[0]["mode"] not in ("100644", "100755")
                or entries[0]["type"] != "blob"
            ):
                raise ConfigurationError(
                    "Trusted configuration must be one regular file"
                )
            blob_sha = entries[0]["sha"]
            if not isinstance(blob_sha, str) or not re.fullmatch(
                r"[0-9a-f]{40}", blob_sha
            ):
                raise ConfigurationError("Invalid trusted configuration blob identity")
            blob = read_json(["api", f"repos/{repository}/git/blobs/{blob_sha}"])
            if blob["sha"] != blob_sha or blob["encoding"] != "base64":
                raise ConfigurationError("Invalid trusted configuration blob")
            content = base64.b64decode(
                "".join(blob["content"].splitlines()), validate=True
            )
        return parse_configuration(content).automations["guardedMerge"]
    except ConfigurationError:
        raise
    except (
        KeyError,
        TypeError,
        AttributeError,
        ValueError,
        binascii.Error,
        OSError,
    ) as error:
        raise ConfigurationError(
            f"Cannot read trusted automation configuration: {error}"
        ) from error


def main(argv: list[str] | None = None) -> int:
    """Print validated activation as a GitHub Actions output line."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--version", action="version", version="v1.0.0")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the read-only decision"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show decision context"
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--automation", choices=AUTOMATION_NAMES, required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--legacy-sync", default="")
    try:
        arguments = parser.parse_args(argv)
        enabled = automation_enabled(
            arguments.repository_root,
            arguments.automation,
            event=arguments.event,
            legacy_sync=arguments.legacy_sync,
        )
        if arguments.verbose:
            print(f"{arguments.automation}: event={arguments.event}", file=sys.stderr)
        print(f"enabled={str(enabled).lower()}")
        return 0
    except ConfigurationError as error:
        print(f"Error: {error}. Run with -h for help.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
