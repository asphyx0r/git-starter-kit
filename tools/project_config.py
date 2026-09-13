"""Load and inspect repository-local starter-kit configuration without writes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from pathlib import PurePosixPath
from pathlib import PureWindowsPath
import sys
import traceback
from typing import Any


__all__ = [
    "Check",
    "Configuration",
    "ConfigurationError",
    "default_project_configuration",
    "load_configuration",
    "parse_configuration",
]
VERSION = "v1.0.0"
CONFIGURATION_FILE = ".starter-kit-project.json"
AUTOMATION_NAMES = ("agentRulesSync", "guardedMerge", "releasePreflight")
ROOT_FIELDS = {
    "schemaVersion",
    "repositoryRole",
    "releaseKind",
    "automations",
    "checks",
}
CHECK_FIELDS = {"name", "argv", "workingDirectory", "platforms"}
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"
}
WINDOWS_FORBIDDEN_CHARACTERS = '<>:"\\|?*'


class ConfigurationError(ValueError):
    """An existing project configuration or requested key is invalid."""


@dataclass(frozen=True)
class Check:
    """A declared command; loading configuration never executes it."""

    name: str
    argv: tuple[str, ...]
    working_directory: str
    platforms: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the check's portable JSON representation."""
        return {
            "name": self.name,
            "argv": list(self.argv),
            "workingDirectory": self.working_directory,
            "platforms": list(self.platforms),
        }


@dataclass(frozen=True)
class Configuration:
    """Effective configuration, including explicit legacy/configured mode."""

    mode: str
    repository_role: str
    release_kind: str
    automations: dict[str, bool]
    checks: tuple[Check, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a stable JSON object using configuration-file key names."""
        return {
            "mode": self.mode,
            "schemaVersion": 1,
            "repositoryRole": self.repository_role,
            "releaseKind": self.release_kind,
            "automations": dict(self.automations),
            "checks": [check.as_dict() for check in self.checks],
        }


def default_project_configuration() -> dict[str, Any]:
    """Return a fresh version 1 configuration for a new project."""
    return {
        "schemaVersion": 1,
        "repositoryRole": "project",
        "releaseKind": "repository",
        "automations": {name: False for name in AUTOMATION_NAMES},
        "checks": [],
    }


def load_configuration(root: Path) -> Configuration:
    """Load strict version 1 settings, or preserve legacy behavior if absent."""
    try:
        root = root.resolve()
        if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
            raise ConfigurationError(f"Repository root is not accessible: {root}")
        path = root / CONFIGURATION_FILE
        try:
            path.lstat()
        except FileNotFoundError:
            return parse_configuration(None)
        if not path.is_file() or not os.access(path, os.R_OK):
            raise ConfigurationError(f"Configuration is not a readable file: {path}")
        return parse_configuration(path.read_bytes(), root=root)
    except ConfigurationError:
        raise
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        raise ConfigurationError(
            f"Cannot read project configuration: {error}"
        ) from error


def parse_configuration(
    content: bytes | None, *, root: Path | None = None
) -> Configuration:
    """Parse strict UTF-8 bytes; None means absent. Metadata reads omit root.

    Without root, portable path syntax is validated without filesystem access.
    Local loading/execution supplies its actual resolved root for containment.
    """
    if content is None:
        return Configuration(
            "legacy",
            "project",
            "deployment",
            {name: True for name in AUTOMATION_NAMES},
            (),
        )
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
        return _parse_configuration(value, root)
    except ConfigurationError:
        raise
    except (UnicodeError, ValueError) as error:
        raise ConfigurationError(
            f"Cannot read project configuration: {error}"
        ) from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ConfigurationError(f"Duplicate configuration field: {name}")
        result[name] = value
    return result


def _exact_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ConfigurationError(
            f"{label} must contain exactly: {', '.join(sorted(fields))}"
        )
    return value


def _parse_configuration(value: Any, root: Path | None) -> Configuration:
    value = _exact_object(value, ROOT_FIELDS, "Configuration")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ConfigurationError("schemaVersion must be the integer 1")
    if value["repositoryRole"] not in ("project", "source"):
        raise ConfigurationError("repositoryRole must be project or source")
    if value["releaseKind"] not in ("repository", "deployment"):
        raise ConfigurationError("releaseKind must be repository or deployment")
    automations = _exact_object(
        value["automations"], set(AUTOMATION_NAMES), "automations"
    )
    if any(type(enabled) is not bool for enabled in automations.values()):
        raise ConfigurationError("All automations must be booleans")
    if not isinstance(value["checks"], list):
        raise ConfigurationError("checks must be an array")
    checks = tuple(_parse_check(check, root) for check in value["checks"])
    if len({check.name for check in checks}) != len(checks):
        raise ConfigurationError("Check names must be unique")
    return Configuration(
        "configured",
        value["repositoryRole"],
        value["releaseKind"],
        {name: automations[name] for name in AUTOMATION_NAMES},
        checks,
    )


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ConfigurationError(f"{label} must be a nonempty string without NULs")
    return value


def _parse_check(value: Any, root: Path | None) -> Check:
    value = _exact_object(value, CHECK_FIELDS, "Check")
    name = _nonempty_string(value["name"], "Check name")
    argv = value["argv"]
    if not isinstance(argv, list) or not argv:
        raise ConfigurationError(f"Check {name}: argv must be a nonempty string array")
    if any(not isinstance(arg, str) or "\0" in arg for arg in argv):
        raise ConfigurationError(
            f"Check {name}: argv must contain strings without NULs"
        )
    _nonempty_string(argv[0], f"Check {name} command")
    directory = _working_directory(value["workingDirectory"], root)
    platforms = value["platforms"]
    if (
        not isinstance(platforms, list)
        or not platforms
        or any(platform not in ("linux", "windows") for platform in platforms)
        or len(set(platforms)) != len(platforms)
    ):
        raise ConfigurationError(
            f"Check {name}: platforms must be unique linux/windows values"
        )
    return Check(name, tuple(argv), directory, tuple(platforms))


def _working_directory(value: Any, root: Path | None) -> str:
    directory = _nonempty_string(value, "workingDirectory")
    portable = PurePosixPath(directory)
    if (
        portable.is_absolute()
        or PureWindowsPath(directory).drive
        or "\\" in directory
        or ":" in directory
        or ".." in portable.parts
    ):
        raise ConfigurationError(
            "workingDirectory must be a portable relative path without '..'"
        )
    for component in portable.parts:
        _validate_path_component(component)
    if root is not None:
        resolved = root.joinpath(*portable.parts).resolve()
        if not resolved.is_relative_to(root):
            raise ConfigurationError("workingDirectory resolves outside the repository")
    return directory


def _validate_path_component(component: str) -> None:
    device_name = component.split(".", 1)[0].rstrip(" ").upper()
    if (
        device_name in WINDOWS_RESERVED_NAMES
        or component.endswith((".", " "))
        or any(character in WINDOWS_FORBIDDEN_CHARACTERS for character in component)
        or any(
            ord(character) < 32 or 127 <= ord(character) <= 159
            for character in component
        )
    ):
        raise ConfigurationError(
            "workingDirectory contains a component that is not portable to Windows"
        )


def _get_value(configuration: dict[str, Any], key: str) -> Any:
    value: Any = configuration
    for component in key.split("."):
        if not isinstance(value, dict) or component not in value:
            raise ConfigurationError(f"Unknown effective-configuration key: {key}")
        value = value[component]
    return value


def main(argv: list[str] | None = None) -> int:
    """Print effective configuration, a selected key, or a read-only plan."""
    parser = argparse.ArgumentParser(
        description="Read effective starter-kit project configuration without writes.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version", action="version", version=VERSION, help="show version and exit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the read-only execution plan without side effects",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="enable DEBUG console logging"
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: current directory)",
    )
    parser.add_argument(
        "--get", metavar="KEY", help="print a dotted effective-configuration key"
    )
    arguments = parser.parse_args(argv)
    logger = logging.getLogger(__name__)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if arguments.verbose else logging.WARNING)
    try:
        logger.debug("Reading configuration from %s", arguments.repository_root)
        configuration = load_configuration(arguments.repository_root).as_dict()
        value = (
            configuration
            if arguments.get is None
            else _get_value(configuration, arguments.get)
        )
        if arguments.dry_run:
            print(
                f"Read {arguments.repository_root / CONFIGURATION_FILE}; "
                f"print {arguments.get or 'effective configuration'} "
                f"(mode: {configuration['mode']}). No writes or check execution."
            )
        else:
            print(value if isinstance(value, str) else json.dumps(value, indent=2))
        return 0
    except ConfigurationError as error:
        print(f"Error: {error}. Run with -h for help.", file=sys.stderr)
        if arguments.verbose:
            traceback.print_exc()
        return 1
    finally:
        logger.removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
