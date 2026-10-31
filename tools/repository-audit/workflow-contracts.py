#!/usr/bin/env python3
"""Validate workflow objects and executable boundaries independently of YAML layout.

Presentation and bounded download-cache settings may vary. Script seals retain
step order, quote boundaries, statement boundaries and Python control flow: a
guard cannot be replaced by a comment or a later command.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any

yaml = importlib.import_module("yaml")


class ContractError(ValueError):
    """A workflow violates its security or functional contract."""


SafeLoader: Any = yaml.SafeLoader


class UniqueKeyLoader(SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""

    def construct_mapping(self, node: Any, deep: bool = False) -> dict:
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, (str, int, float, bool, type(None))):
                raise ContractError("mapping keys must be scalar")
            if key in result:
                raise ContractError(
                    f"duplicate mapping key {key!r} at line {key_node.start_mark.line + 1}"
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


# GitHub Actions uses YAML 1.2 booleans: an unquoted `on` remains an event key.
UniqueKeyLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
UniqueKeyLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"),
    list("tTfF"),
)


def load_workflow(path: Path) -> dict[str, Any]:
    """Read a workflow once, without YAML object construction or duplicate keys."""
    try:
        value = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as error:
        raise ContractError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{path}: workflow must be a mapping")
    return value


def normalize_shell(script: str, shell: str) -> str:
    """Keep quote contents and token adjacency; normalize only shell separators."""
    escape = "`" if shell == "pwsh" else "\\"
    quote = None
    substitutions: list[tuple[str | None, int]] = []
    output: list[str] = []
    index = 0
    while index < len(script):
        char = script[index]
        if script[index : index + 2] == "$(" and quote != "'":
            substitutions.append((quote, 1))
            quote = None
            output.extend(("$", "("))
            index += 2
            continue
        if quote is None and substitutions and char in {"(", ")"}:
            outer_quote, depth = substitutions[-1]
            depth += 1 if char == "(" else -1
            if depth == 0:
                substitutions.pop()
                quote = outer_quote
            else:
                substitutions[-1] = (outer_quote, depth)
        if (
            quote is None
            and char == "#"
            and (not output or output[-1] == "\n")
            and not (
                shell == "pwsh"
                and re.match(r"#requires\b", script[index:], re.IGNORECASE)
            )
        ):
            end = script.find("\n", index)
            index = len(script) if end < 0 else end
            continue
        if char == escape and quote != "'" and index + 1 < len(script):
            following = script[index + 1]
            # Outside strings, a continuation removes the newline; it adds no space.
            if following == "\n" and (quote is None or shell != "pwsh"):
                index += 2
                continue
            output.extend((char, following))
            index += 2
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        if quote is None and char in " \t":
            if output and output[-1] not in {" ", "\n"}:
                output.append(" ")
        elif quote is None and char == "\n":
            if output and output[-1] == " ":
                output.pop()
            if output and output[-1] != "\n":
                output.append("\n")
        else:
            output.append(char)
        index += 1
    return "".join(output).strip()


def normalize_script(script: str, shell: str) -> str:
    """Normalize shell formatting and compare embedded Python by syntax tree."""
    if "${{" in script:
        raise ContractError("Actions expressions in run scripts must use env instead")

    def python_body(match: re.Match) -> str:
        try:
            tree = ast.parse(match.group(1))
        except SyntaxError as error:
            raise ContractError(f"invalid embedded Python: {error.msg}") from error
        # Keep the legacy AST form across supported Python versions.
        for node in ast.walk(tree):
            setattr(
                node,
                "_fields",
                tuple(
                    field
                    for field in node._fields
                    if not (
                        isinstance(getattr(node, field, None), list)
                        and not getattr(node, field)
                    )
                    and not (
                        isinstance(node, (ast.Import, ast.ImportFrom))
                        and field == "is_lazy"
                        and getattr(node, field, None) == 0
                    )
                ),
            )
        # An opaque unquoted token keeps Python string contents out of shell lexing.
        dump_options = {"show_empty": True} if sys.version_info >= (3, 15) else {}
        dumped_tree = ast.dump(tree, include_attributes=False, **dump_options)
        encoded_tree = dumped_tree.encode("utf-8").hex()
        return "<<'PY'\nPYTHON_AST_" + encoded_tree + "\nPY"

    script = re.sub(r"<<'PY'\n(.*?)\nPY(?=\n|$)", python_body, script, flags=re.DOTALL)
    return normalize_shell(script.replace("\r\n", "\n"), shell)


def normalize_expression(value: str, *, bare: bool = False) -> str:
    def whitespace(expression: str) -> str:
        return re.sub(
            r"'[^']*'|\s+",
            lambda match: " " if match.group().isspace() else match.group(),
            expression.strip(),
        )

    if bare:
        return whitespace(value)
    return re.sub(
        r"\$\{\{(.*?)\}\}",
        lambda match: "${{ " + whitespace(match.group(1)) + " }}",
        value,
        flags=re.DOTALL,
    )


def without_cache(step: dict, kind: str, context: str) -> dict:
    """Permit optional download caches only for known locked dependency inputs."""
    inputs = step.get("with")
    if not isinstance(inputs, dict):
        raise ContractError(f"{context}/with: action inputs must be a mapping")
    if ("cache" in inputs) != ("cache-dependency-path" in inputs):
        raise ContractError(
            f"{context}/with: cache and dependency path require each other"
        )
    if "cache" in inputs and inputs["cache"] != kind:
        raise ContractError(f"{context}/with/cache: unexpected cache kind")
    if "cache-dependency-path" in inputs:
        value = inputs["cache-dependency-path"]
        allowed = {
            "tools/quality/requirements.lock",
            "tools/release-artifacts-requirements.txt",
            "tools/quality/package-lock.json",
            "tools/quality/versions.json",
        }
        paths = value.splitlines() if isinstance(value, str) else []
        if not paths or any(path.strip() not in allowed for path in paths):
            raise ContractError(f"{context}/with/cache-dependency-path: unlocked input")
    return {
        **step,
        "with": {
            key: value
            for key, value in inputs.items()
            if key not in {"cache", "cache-dependency-path"}
        },
    }


def compare_contract(actual: Any, expected: Any, context: str, field: str = "") -> None:
    """Compare the small workflow contracts with location-bearing diagnostics."""
    if field == "needs":
        actual = actual if isinstance(actual, list) else [actual]
        expected = expected if isinstance(expected, list) else [expected]
        if not all(isinstance(item, str) for item in actual):
            raise ContractError(f"{context}: job dependencies must be strings")
        actual, expected = sorted(actual), sorted(expected)
    if isinstance(expected, dict):
        if isinstance(actual, dict) and expected.get("uses") in CACHE_ACTIONS:
            kind = CACHE_ACTIONS[expected["uses"]]
            actual = without_cache(actual, kind, context)
            expected = without_cache(expected, kind, context)
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ContractError(
                f"{context}: fields changed; expected {sorted(expected)}"
            )
        for key, value in expected.items():
            if key == "run":
                try:
                    matches = isinstance(actual[key], str)
                    if matches:
                        normalized = normalize_script(
                            actual[key], expected.get("shell", "bash")
                        )
                        checksum = hashlib.sha256(
                            normalized.encode("utf-8")
                        ).hexdigest()
                        matches = f"sha256:{checksum}" == value
                except ContractError as error:
                    raise ContractError(f"{context}/run: {error}") from error
                if not matches:
                    raise ContractError(
                        f"{context}/run: executed command or guard changed"
                    )
            else:
                compare_contract(actual[key], value, f"{context}/{key}", key)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ContractError(f"{context}: ordered entries changed")
        for index, value in enumerate(expected):
            compare_contract(actual[index], value, f"{context}[{index}]")
    else:
        if isinstance(actual, str) and isinstance(expected, str):
            if field in {"path", "cache-dependency-path", "repositories"}:
                actual = tuple(
                    normalize_expression(line.strip())
                    for line in actual.strip().splitlines()
                )
                expected = tuple(
                    normalize_expression(line.strip())
                    for line in expected.strip().splitlines()
                )
            elif field in {"if", "name"} or "${{" in expected:
                actual = normalize_expression(actual, bare=field == "if")
                expected = normalize_expression(expected, bare=field == "if")
        if type(actual) is not type(expected) or actual != expected:
            raise ContractError(f"{context}: value changed; expected {expected!r}")


ACTION_REFS = {
    "checkout": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "setup-python": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
    "setup-node": "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1",
    "upload-artifact": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
    "download-artifact": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
    "create-github-app-token": (
        "actions/create-github-app-token@"  # Public action revision.
        "64ab729a6294000f5aa4a4bc0b73d1f32bc45510"
    ),
}

CACHE_ACTIONS = {
    ACTION_REFS["setup-python"]: "pip",
    ACTION_REFS["setup-node"]: "npm",
}


# Seal normalized execution, retaining the workflow/job/step role for review.
SEALED_SCRIPTS = {
    "agent-rules-update/activation/activation": "sha256:57e6b233454c68c0b066e6deb041f1194caaee8e6e45aacae48c40c64839c794",
    "agent-rules-update/activation/resolve": "sha256:c1c1d44df19bf461719e508f2aa7e7d86ae852eb1bf30fdc71aaedd8c0c0cc2c",
    "agent-rules-update/prepare/resolve": "sha256:5260dc8110474e80161901367e3161cacd19dc9317731212bcc87effb6aea534",
    "agent-rules-update/prepare/run-external-synchronization-without-credentials": "sha256:859e704bb29b9d0691f8ab2f11a8f1ec830d8d0a65bf70e75d1494bacacf65e9",
    "agent-rules-update/prepare/seal": "sha256:b665573511d92b2af6d4e48842301c188b9cfe71e2574a05f84723d7c6aa2b47",
    "agent-rules-update/publish/prepare-publish": "sha256:7ebc2cb608620025b6b88384daf491634fa0903adc9218a39141c3ed18610946",
    "agent-rules-update/publish/push-branch-and-create-or-update-pull-request": "sha256:dd112160132afb25508a4b396e7557b4da5c73910120a303b7e002cff3cc9681",
    "guarded-pull-request-merge/guarded-merge/install-locked-commitlint": "sha256:a44f53878073c66ebecde8da1cfbe3963b4752bdb4e7d41f19f3f8ed19069c5a",
    "guarded-pull-request-merge/guarded-merge/revalidate-and-squash-merge-with-the-guarded-token": "sha256:2705cf6861b29c920ed32609a1625530a0bc7be2bc66e2dbcf5a05addc767013",
    "guarded-pull-request-merge/guarded-merge/validate-guarded-merge-without-privileged-credentials": "sha256:6ec1b848e19fb1c5caf38ff85053425dd13b56385f8a335330c7288e76a2e37e",
    "release-artifacts/release-artifacts/install-manifest-validator": "sha256:76576e63dd0073d8ef2e59a9c8646bd83496908d7d564433af376c0c4223934f",
    "release-artifacts/release-artifacts/validate-release-identification": "sha256:346168d880b8a9e65447f17951b9d2de2c044aded137ca1dbd6545a9032b1cdf",
    "release-package/build/install-locked-quality-dependencies": "sha256:b654f075942844208705b7969bb22631317e7918ada8306c4c2591d48ec5b43d",
    "release-package/build/package": "sha256:e70350fd8b7e552956337d1f2b176ac9f757f3f1a4444b3e7ad7da28c3c27318",
    "release-package/build/refs": "sha256:7984b6b057b3c2c9766ea6766d3e20c297481bfa7639737b28e0f9c533b6985d",
    "release-package/build/seal": "sha256:a85539b5646f749bf93e5b5626aae5181eb0e4eb71a5ecdb947d2858d52552a8",
    "release-package/build/toolkit": "sha256:d6136325baee4819d3a9aafbb5443aee5e99fb35a2e5ea683212141bfa63fe71",
    "release-package/build/validate-composed-package": "sha256:c3300c59f222ca456ad803f2dedbe8ec12bafab4e611d60cf2cf28c4f4476459",
    "release-package/publish/publish": "sha256:a3cebbeb68284f3ae220c847b40dd5f40dc30c49e69f04ea6adf334d5de30dd6",
    "release-package/publish/verify": "sha256:324c33aed75e465d147b2b240a6ffd98419a7c2f9f0c6f75bebf52daa867985c",
    "release-package/release-checks/require-successful-release-event-workflows": "sha256:9fce436f57a77b549350f42a8e49574ef3af47a2bb101131ee2e741b83788aff",
    "repository-audit/quality-linux/verify-exact-audit-revision": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
}


def action(name: str, inputs: dict, **fields: Any) -> dict:
    return {"uses": ACTION_REFS[name], "with": inputs, **fields}


def checkout(**inputs: Any) -> dict:
    return action(
        "checkout", {"fetch-depth": 0, "persist-credentials": False, **inputs}
    )


def setup_python(version: str = "3.11", cache: str | None = None) -> dict:
    inputs = {"python-version": version}
    if cache:
        inputs.update({"cache": "pip", "cache-dependency-path": cache})
    return action("setup-python", inputs)


def setup_node(version: str = "${{ env.NODE_VERSION }}") -> dict:
    return action(
        "setup-node",
        {
            "node-version": version,
            "cache": "npm",
            "cache-dependency-path": "tools/quality/package-lock.json\ntools/quality/versions.json",
        },
    )


def app_token(step_id: str) -> dict:
    return action(
        "create-github-app-token",
        {
            "client-id": "${{ vars.AGENT_RULES_APP_CLIENT_ID }}",
            "private-key": "${{ secrets.AGENT_RULES_APP_PRIVATE_KEY }}",
            "owner": "${{ github.repository_owner }}",
            "repositories": "${{ github.event.repository.name }}",
            "permission-contents": "write",
            "permission-pull-requests": "write",
        },
        id=step_id,
    )


def activation_contract(automation: str) -> dict:
    return {
        "name": "Read trusted automation configuration",
        "runs-on": "ubuntu-24.04",
        "timeout-minutes": 5,
        "permissions": {"contents": "read"},
        "outputs": {
            "enabled": "${{ steps.activation.outputs.enabled }}",
            "trusted_sha": "${{ steps.resolve.outputs.trusted_sha }}",
        },
        "steps": [
            {
                "id": "resolve",
                "shell": "bash",
                "env": {
                    "GH_TOKEN": "${{ github.token }}",
                    "GH_REPO": "${{ github.repository }}",
                },
                "run": SEALED_SCRIPTS["agent-rules-update/activation/resolve"],
            },
            {
                "uses": ACTION_REFS["checkout"],
                "with": {
                    "fetch-depth": 1,
                    "persist-credentials": False,
                    "ref": "${{ steps.resolve.outputs.trusted_sha }}",
                },
            },
            {
                "id": "activation",
                "shell": "bash",
                "env": {
                    "AUTOMATION": automation,
                    "EVENT_NAME": "${{ github.event_name }}",
                    "LEGACY_SYNC": "${{ vars.AGENT_RULES_SYNC_ENABLED }}",
                },
                "run": SEALED_SCRIPTS["agent-rules-update/activation/activation"],
            },
        ],
    }


def audit_revision_step() -> dict:
    return {
        "shell": "bash",
        "env": {
            "AUDIT_COMMIT_SHA": "${{ github.event.pull_request.head.sha || github.sha }}"
        },
        "run": SEALED_SCRIPTS[
            "repository-audit/quality-linux/verify-exact-audit-revision"
        ],
    }


def release_package_contract(node_version: str) -> dict:
    return {
        "name": "Release package",
        "on": {
            "release": {"types": ["published"]},
            "workflow_dispatch": {
                "inputs": {
                    "tag": {"required": True, "type": "string"},
                    "agent_rules_ref": {"required": True, "type": "string"},
                }
            },
        },
        "permissions": {"contents": "read"},
        "concurrency": {
            "group": "release-package-${{ github.event_name == 'release' && github.event.release.tag_name || inputs.tag }}",
            "cancel-in-progress": False,
        },
        "jobs": {
            "build": {
                "name": "Build release package",
                "if": "github.repository == 'asphyx0r/git-starter-kit'",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 30,
                "outputs": {
                    "release_tag": "${{ steps.refs.outputs.starter_ref }}",
                    "release_sha": "${{ steps.refs.outputs.starter_sha }}",
                    "package_name": "${{ steps.seal.outputs.package_name }}",
                    "toolkit_name": "${{ steps.seal.outputs.toolkit_name }}",
                    "package_sha256": "${{ steps.seal.outputs.package_sha256 }}",
                    "toolkit_sha256": "${{ steps.seal.outputs.toolkit_sha256 }}",
                },
                "steps": [
                    checkout(
                        **{
                            "ref": "${{ github.event_name == 'release' && github.event.release.tag_name || inputs.tag }}"
                        }
                    ),
                    setup_python("3.11", "tools/quality/requirements.lock"),
                    setup_node(node_version),
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "release-package/build/install-locked-quality-dependencies"
                        ],
                    },
                    {
                        "id": "refs",
                        "shell": "bash",
                        "env": {
                            "EVENT_NAME": "${{ github.event_name }}",
                            "RELEASE_TAG": "${{ github.event.release.tag_name }}",
                            "INPUT_TAG": "${{ inputs.tag }}",
                            "INPUT_AGENT_RULES_REF": "${{ inputs.agent_rules_ref }}",
                        },
                        "run": SEALED_SCRIPTS["release-package/build/refs"],
                    },
                    {
                        "id": "package",
                        "shell": "pwsh",
                        "env": {
                            "REPOSITORY_REF": "${{ steps.refs.outputs.starter_ref }}",
                            "AGENT_RULES_REF": "${{ steps.refs.outputs.agent_rules_ref }}",
                            "PACKAGE_NAME": "git-starter-kit-${{ steps.refs.outputs.starter_ref }}-with-agent-rules.zip",
                            "GITHUB_TOKEN": "${{ github.token }}",
                        },
                        "run": SEALED_SCRIPTS["release-package/build/package"],
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "PACKAGE_PATH": "${{ steps.package.outputs.package_path }}"
                        },
                        "run": SEALED_SCRIPTS[
                            "release-package/build/validate-composed-package"
                        ],
                    },
                    {
                        "id": "toolkit",
                        "shell": "bash",
                        "env": {
                            "PACKAGE_PATH": "${{ steps.package.outputs.package_path }}",
                            "REPOSITORY_REF": "${{ steps.refs.outputs.starter_ref }}",
                        },
                        "run": SEALED_SCRIPTS["release-package/build/toolkit"],
                    },
                    {
                        "id": "seal",
                        "shell": "bash",
                        "env": {
                            "PACKAGE_PATH": "${{ steps.package.outputs.package_path }}",
                            "TOOLKIT_PATH": "${{ steps.toolkit.outputs.toolkit_path }}",
                            "RELEASE_TAG": "${{ steps.refs.outputs.starter_ref }}",
                            "TRANSFER_ROOT": "${{ runner.temp }}/release-package-transfer",
                            "EXPECTED_SUMS_PATH": "${{ runner.temp }}/release-package-build-expected-sha256s",
                        },
                        "run": SEALED_SCRIPTS["release-package/build/seal"],
                    },
                    {
                        "uses": ACTION_REFS["upload-artifact"],
                        "with": {
                            "name": "release-package-${{ steps.refs.outputs.starter_ref }}",
                            "path": "${{ runner.temp }}/release-package-transfer/${{ steps.seal.outputs.package_name }}\n${{ runner.temp }}/release-package-transfer/${{ steps.seal.outputs.toolkit_name }}\n${{ runner.temp }}/release-package-transfer/SHA256SUMS\n",
                            "if-no-files-found": "error",
                        },
                    },
                ],
            },
            "release-checks": {
                "name": "Verify release event checks",
                "needs": "build",
                "if": "github.repository == 'asphyx0r/git-starter-kit'",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 35,
                "permissions": {"contents": "read", "actions": "read"},
                "steps": [
                    {
                        "uses": ACTION_REFS["checkout"],
                        "with": {
                            "ref": "${{ github.workflow_sha }}",
                            "persist-credentials": False,
                            "sparse-checkout": "tools/verify-repository-audit-runs.py",
                            "sparse-checkout-cone-mode": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ github.token }}",
                            "GH_REPO": "${{ github.repository }}",
                            "RELEASE_TAG": "${{ needs.build.outputs.release_tag }}",
                            "RELEASE_SHA": "${{ needs.build.outputs.release_sha }}",
                        },
                        "run": SEALED_SCRIPTS[
                            "release-package/release-checks/require-successful-release-event-workflows"
                        ],
                    },
                ],
            },
            "publish": {
                "name": "Publish release package",
                "needs": ["build", "release-checks"],
                "if": "github.repository == 'asphyx0r/git-starter-kit'",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 5,
                "environment": "release",
                "permissions": {"contents": "write"},
                "steps": [
                    {
                        "uses": ACTION_REFS["download-artifact"],
                        "with": {
                            "name": "release-package-${{ needs.build.outputs.release_tag }}",
                            "path": "${{ runner.temp }}/release-package-publish",
                        },
                    },
                    {
                        "id": "verify",
                        "shell": "bash",
                        "env": {
                            "TRANSFER_ROOT": "${{ runner.temp }}/release-package-publish",
                            "EXPECTED_PACKAGE_NAME": "${{ needs.build.outputs.package_name }}",
                            "EXPECTED_TOOLKIT_NAME": "${{ needs.build.outputs.toolkit_name }}",
                            "EXPECTED_PACKAGE_SHA256": "${{ needs.build.outputs.package_sha256 }}",
                            "EXPECTED_TOOLKIT_SHA256": "${{ needs.build.outputs.toolkit_sha256 }}",
                            "EXPECTED_SUMS_PATH": "${{ runner.temp }}/release-package-publish-expected-sha256s",
                        },
                        "run": SEALED_SCRIPTS["release-package/publish/verify"],
                    },
                    {
                        "id": "publish",
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ github.token }}",
                            "GH_REPO": "${{ github.repository }}",
                            "RELEASE_TAG": "${{ needs.build.outputs.release_tag }}",
                            "EVENT_NAME": "${{ github.event_name }}",
                            "PRERELEASE": "${{ github.event.release.prerelease }}",
                            "TRANSFER_ROOT": "${{ runner.temp }}/release-package-publish",
                            "PACKAGE_NAME": "${{ needs.build.outputs.package_name }}",
                            "TOOLKIT_NAME": "${{ needs.build.outputs.toolkit_name }}",
                            "EXPECTED_PACKAGE_SHA256": "${{ needs.build.outputs.package_sha256 }}",
                            "EXPECTED_TOOLKIT_SHA256": "${{ needs.build.outputs.toolkit_sha256 }}",
                        },
                        "run": SEALED_SCRIPTS["release-package/publish/publish"],
                    },
                ],
            },
        },
    }


def agent_rules_update_contract(node_version: str) -> dict:
    return {
        "name": "Agent rules update",
        "on": {
            "release": {"types": ["published"]},
            "schedule": [{"cron": "17 5 * * *"}],
            "workflow_dispatch": None,
        },
        "permissions": {"contents": "read"},
        "concurrency": {"group": "agent-rules-update", "cancel-in-progress": False},
        "env": {
            "RULES_REPOSITORY": "asphyx0r/agent-coding-rules",
            "SYNC_BRANCH": "automation/agent-rules-update",
        },
        "jobs": {
            "prepare": {
                "if": "needs.activation.outputs.enabled == 'true' && (github.event_name != 'workflow_dispatch' || github.ref_name == github.event.repository.default_branch)",
                "name": "Prepare agent rules update",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 15,
                "permissions": {"contents": "read"},
                "outputs": {
                    "changed": "${{ steps.seal.outputs.changed }}",
                    "target_repository": "${{ steps.resolve.outputs.target_repository }}",
                    "target_default_branch": "${{ steps.resolve.outputs.target_default_branch }}",
                    "target_base_commit": "${{ steps.resolve.outputs.target_base_commit }}",
                    "source_ref": "${{ steps.resolve.outputs.source_ref }}",
                    "source_tag_oid": "${{ steps.resolve.outputs.source_tag_oid }}",
                    "source_commit": "${{ steps.resolve.outputs.source_commit }}",
                },
                "steps": [
                    checkout(
                        **{
                            "ref": "${{ needs.activation.outputs.trusted_sha }}",
                            "path": "target",
                            "fetch-depth": 1,
                        }
                    ),
                    setup_python("3.11", None),
                    {
                        "id": "resolve",
                        "working-directory": "target",
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ github.token }}",
                            "TARGET_REPOSITORY": "${{ github.repository }}",
                            "TARGET_DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
                            "TRUSTED_SHA": "${{ needs.activation.outputs.trusted_sha }}",
                        },
                        "run": SEALED_SCRIPTS["agent-rules-update/prepare/resolve"],
                    },
                    {
                        "working-directory": "target",
                        "shell": "bash",
                        "env": {
                            "SOURCE_REF": "${{ steps.resolve.outputs.source_ref }}",
                            "SOURCE_COMMIT": "${{ steps.resolve.outputs.source_commit }}",
                        },
                        "run": SEALED_SCRIPTS[
                            "agent-rules-update/prepare/run-external-synchronization-without-credentials"
                        ],
                    },
                    {
                        "id": "seal",
                        "working-directory": "target",
                        "shell": "bash",
                        "env": {
                            "TARGET_REPOSITORY": "${{ steps.resolve.outputs.target_repository }}",
                            "TARGET_DEFAULT_BRANCH": "${{ steps.resolve.outputs.target_default_branch }}",
                            "TARGET_BASE_COMMIT": "${{ steps.resolve.outputs.target_base_commit }}",
                            "SOURCE_REF": "${{ steps.resolve.outputs.source_ref }}",
                            "SOURCE_TAG_OID": "${{ steps.resolve.outputs.source_tag_oid }}",
                            "SOURCE_COMMIT": "${{ steps.resolve.outputs.source_commit }}",
                        },
                        "run": SEALED_SCRIPTS["agent-rules-update/prepare/seal"],
                    },
                    {
                        "uses": ACTION_REFS["upload-artifact"],
                        "with": {
                            "name": "agent-rules-update",
                            "path": "${{ runner.temp }}/agent-rules-transfer/agent-rules.patch\n${{ runner.temp }}/agent-rules-transfer/agent-rules-plan.json\n${{ runner.temp }}/agent-rules-transfer/source.json\n${{ runner.temp }}/agent-rules-transfer/SHA256SUMS\n",
                            "if-no-files-found": "error",
                        },
                        "if": "steps.seal.outputs.changed == 'true'",
                    },
                ],
                "needs": "activation",
            },
            "publish": {
                "needs": "prepare",
                "if": "needs.prepare.outputs.changed == 'true'",
                "name": "Publish agent rules pull request",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 10,
                "permissions": {"contents": "read"},
                "steps": [
                    checkout(
                        **{
                            "ref": "${{ needs.prepare.outputs.target_base_commit }}",
                            "path": "target",
                            "fetch-depth": 1,
                        }
                    ),
                    setup_python("3.11", None),
                    {
                        "uses": ACTION_REFS["download-artifact"],
                        "with": {
                            "name": "agent-rules-update",
                            "path": "${{ runner.temp }}/agent-rules-transfer",
                        },
                    },
                    {
                        "id": "prepare-publish",
                        "working-directory": "target",
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ github.token }}",
                            "TARGET_REPOSITORY": "${{ needs.prepare.outputs.target_repository }}",
                            "TARGET_DEFAULT_BRANCH": "${{ needs.prepare.outputs.target_default_branch }}",
                            "TARGET_BASE_COMMIT": "${{ needs.prepare.outputs.target_base_commit }}",
                            "SOURCE_REF": "${{ needs.prepare.outputs.source_ref }}",
                            "SOURCE_TAG_OID": "${{ needs.prepare.outputs.source_tag_oid }}",
                            "SOURCE_COMMIT": "${{ needs.prepare.outputs.source_commit }}",
                        },
                        "run": SEALED_SCRIPTS[
                            "agent-rules-update/publish/prepare-publish"
                        ],
                    },
                    app_token("target-token"),
                    {
                        "working-directory": "target",
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ steps.target-token.outputs.token }}",
                            "TARGET_REPOSITORY": "${{ needs.prepare.outputs.target_repository }}",
                            "TARGET_DEFAULT_BRANCH": "${{ needs.prepare.outputs.target_default_branch }}",
                            "TARGET_COMMIT": "${{ steps.prepare-publish.outputs.target_commit }}",
                            "SOURCE_REF": "${{ needs.prepare.outputs.source_ref }}",
                            "EXPECTED_REMOTE_OID": "${{ steps.prepare-publish.outputs.expected_remote_oid }}",
                            "PUSH_REQUIRED": "${{ steps.prepare-publish.outputs.push_required }}",
                        },
                        "run": SEALED_SCRIPTS[
                            "agent-rules-update/publish/push-branch-and-create-or-update-pull-request"
                        ],
                    },
                ],
            },
            "activation": activation_contract("agentRulesSync"),
        },
    }


def repository_audit_contract(node_version: str) -> dict:
    contract: dict = {
        "name": "Repository audit",
        "on": {
            "release": {"types": ["published"]},
            "push": None,
            "pull_request": {"branches": ["main", "master"]},
            "workflow_dispatch": None,
        },
        "permissions": {"contents": "read"},
        "env": {"NODE_VERSION": "24.20.0"},
        "concurrency": {
            "group": "repository-audit-${{ github.event_name }}-${{ "
            "github.event.pull_request.number || (github.event_name == 'push' && "
            "github.ref_type == 'branch' && !startsWith(github.ref_name, "
            "'codex/release-preflight-') && github.ref) || github.run_id }}",
            "cancel-in-progress": "${{ github.event_name == 'pull_request' || "
            "(github.event_name == 'push' && github.ref_type == "
            "'branch' && !startsWith(github.ref_name, "
            "'codex/release-preflight-')) }}",
        },
        "jobs": {
            "activation": {
                "name": "Read trusted automation configuration",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 5,
                "permissions": {"contents": "read", "actions": "read"},
                "outputs": {
                    "enabled": "${{ steps.resolve.outputs.enabled || "
                    "steps.activation.outputs.enabled }}",
                    "trusted_sha": "${{ steps.resolve.outputs.trusted_sha }}",
                },
                "steps": [
                    {
                        "id": "resolve",
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ github.token }}",
                            "GH_REPO": "${{ github.repository }}",
                            "EVENT_NAME": "${{ github.event_name }}",
                            "EVENT_DELETED": "${{ github.event.deleted }}",
                            "REF_NAME": "${{ github.ref_name }}",
                            "REF_TYPE": "${{ github.ref_type }}",
                        },
                        "run": "sha256:1116d9de267a68cef6c2ee1e2935be6ab250739384141c93d3f2d57bb218ee31",
                    },
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "fetch-depth": 1,
                            "persist-credentials": False,
                            "ref": "${{ steps.resolve.outputs.trusted_sha }}",
                        },
                        "if": "steps.resolve.outputs.trusted_sha != ''",
                    },
                    {
                        "id": "activation",
                        "shell": "bash",
                        "env": {"EVENT_NAME": "${{ github.event_name }}"},
                        "run": "sha256:bfde8d77e709627edd96a2a0452d069e083bc08d7fe3990bd3d441de6c862e94",
                        "if": "steps.resolve.outputs.trusted_sha != ''",
                    },
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ github.event.pull_request.head.sha || "
                            "github.sha }}",
                            "fetch-depth": 1,
                            "persist-credentials": False,
                        },
                        "if": "github.repository == 'asphyx0r/git-starter-kit' && "
                        "steps.resolve.outputs.enabled != 'false' && "
                        "(github.event_name == 'release' || (github.event_name "
                        "== 'push' && github.ref_type == 'tag'))",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:18b177a89d8f8384ce9f90fbc99f040f5a420c6efb808989ee939e35372dda76",
                        "if": "github.repository == 'asphyx0r/git-starter-kit' && "
                        "steps.resolve.outputs.enabled != 'false' && "
                        "(github.event_name == 'release' || (github.event_name "
                        "== 'push' && github.ref_type == 'tag'))",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "GH_TOKEN": "${{ github.token }}",
                        },
                    },
                    {
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "qualification-candidate-${{ github.run_id "
                            "}}-${{ github.run_attempt }}",
                            "path": "${{ runner.temp }}/candidate.json",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                        "if": "github.repository == 'asphyx0r/git-starter-kit' && "
                        "steps.resolve.outputs.enabled != 'false' && "
                        "(github.event_name == 'release' || (github.event_name "
                        "== 'push' && github.ref_type == 'tag'))",
                        "continue-on-error": True,
                    },
                ],
            },
            "quality-linux": {
                "needs": "activation",
                "if": "needs.activation.outputs.enabled == 'true'",
                "name": "Quality - Ubuntu 24.04 / Python 3.11",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 45,
                "outputs": {"scope": "${{ steps.scope.outputs.scope }}"},
                "steps": [
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ github.event.pull_request.head.sha || "
                            "github.sha }}",
                            "fetch-depth": 0,
                            "persist-credentials": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                        "run": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
                    },
                    {
                        "shell": "bash",
                        "timeout-minutes": 2,
                        "env": {
                            "EVENT_NAME": "${{ github.event_name }}",
                            "BEFORE_SHA": "${{ github.event.before }}",
                            "GH_TOKEN": "${{ github.token }}",
                            "GIT_TERMINAL_PROMPT": "0",
                            "GH_PROMPT_DISABLED": "1",
                        },
                        "run": "sha256:c634a7018a81908b746389cbfba183e998c2aadac8e32fcdbec167e0efb79c38",
                    },
                    {
                        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "with": {
                            "python-version": "3.11",
                            "cache": "pip",
                            "cache-dependency-path": "tools/quality/requirements.lock",
                        },
                    },
                    {
                        "uses": "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1",
                        "with": {
                            "node-version": "${{ env.NODE_VERSION }}",
                            "cache": "npm",
                            "cache-dependency-path": "tools/quality/package-lock.json\n"
                            "tools/quality/versions.json\n",
                        },
                    },
                    {
                        "id": "scope",
                        "shell": "bash",
                        "run": "sha256:0cbf4de9b6d95efb15fcef6bac5d89cadcc6bb988415b6422f8ec0b23ac7fd40",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:2da8204e0669a737bffd04a39f20890e89535bbc4ca44496cbdd6a7bd5852e08",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:d82e511dad71a513d6cedbcde046282a2d957d5108574988ab31753c7c999bb1",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:d324e2e10899f448aba26c2500a06737256b38215fb83c0b9429347756c02e65",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:734ab6d73d005c92cd408a1a5bb6b7bac54d7c872060b00d2fb8c932abc01f0f",
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "BEFORE_SHA": "${{ github.event_name == 'release' "
                            "&& "
                            "'0000000000000000000000000000000000000000' "
                            "|| github.event.before }}",
                            "GITHUB_TOKEN": "${{ github.token }}",
                            "GIT_AUTHOR_NAME": "Codex",
                            "GIT_AUTHOR_EMAIL": "codex@example.com",
                            "GIT_COMMITTER_NAME": "Codex",
                            "GIT_COMMITTER_EMAIL": "codex@example.com",
                        },
                        "run": "sha256:3e5c018e34689322a156534f00a9634b41ffb81ba6d4bf33b8297e6e99f8045f",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:ddfd5c91a81bd1f1c6f158867b3624e10efb3cbbde4fa8ecbf1d4238b8b98b56",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:372f46142d813e61f4fbfa9648d290bb01a5a476cc4c2d2b4bb26221c438359d",
                        "if": "steps.scope.outputs.scope == 'source'",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                    },
                    {
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "qualification-fresh-linux-${{ "
                            "github.run_id }}-${{ github.run_attempt "
                            "}}",
                            "path": "${{ runner.temp }}/fresh/linux.json",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                        "if": "steps.scope.outputs.scope == 'source'",
                        "continue-on-error": True,
                    },
                ],
            },
            "compatibility-windows": {
                "needs": "activation",
                "if": "needs.activation.outputs.enabled == 'true'",
                "name": "Compatibility - Windows 2025 / Python 3.14",
                "runs-on": "windows-2025",
                "timeout-minutes": 45,
                "steps": [
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "fetch-depth": 0,
                            "persist-credentials": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                        "run": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
                    },
                    {
                        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "with": {
                            "python-version": "3.14",
                            "cache": "pip",
                            "cache-dependency-path": "tools/quality/requirements.lock",
                        },
                    },
                    {
                        "id": "scope",
                        "shell": "bash",
                        "run": "sha256:0cbf4de9b6d95efb15fcef6bac5d89cadcc6bb988415b6422f8ec0b23ac7fd40",
                    },
                    {
                        "uses": "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1",
                        "with": {
                            "node-version": "${{ env.NODE_VERSION }}",
                            "cache": "npm",
                            "cache-dependency-path": "tools/quality/package-lock.json\n"
                            "tools/quality/versions.json\n",
                        },
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:2da8204e0669a737bffd04a39f20890e89535bbc4ca44496cbdd6a7bd5852e08",
                    },
                    {
                        "shell": "pwsh",
                        "run": "sha256:13a578bedcab1c4fbc15d4107903217306fe62de00526478783a681a97c13ecd",
                    },
                    {
                        "shell": "pwsh",
                        "run": "sha256:dd0f5ee141930a13f99b52ef6f6984e66aaf9b7ccc7cb170258f55395c1d1fdd",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:072fc07820540ec821834c712d23affc7d258008a43a08b1aeada0b69015e479",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:ea7625b2558eb3a6a01170181e9ec5f0439887175427665494a1f8b39db1eeb2",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:ddfd5c91a81bd1f1c6f158867b3624e10efb3cbbde4fa8ecbf1d4238b8b98b56",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:a2927d21c91fc48178e3e7d61ae4fe5f049dd3641a76a1a830a17b8ee05c3077",
                        "if": "steps.scope.outputs.scope == 'source'",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                    },
                    {
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "qualification-fresh-windows-${{ "
                            "github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/fresh/windows.json",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                        "if": "steps.scope.outputs.scope == 'source'",
                        "continue-on-error": True,
                    },
                ],
                "outputs": {"scope": "${{ steps.scope.outputs.scope }}"},
            },
            "qualification": {
                "name": "Choose common qualification",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 10,
                "permissions": {"contents": "read", "actions": "read"},
                "needs": ["activation", "quality-linux", "compatibility-windows"],
                "if": "needs.activation.outputs.enabled == 'true'",
                "outputs": {"decision": "${{ steps.decision.outputs.decision }}"},
                "env": {
                    "VERIFY_REUSE": "${{ github.repository == 'asphyx0r/git-starter-kit' && "
                    "needs.quality-linux.outputs.scope == 'source' && "
                    "(github.event_name == 'release' || "
                    "(github.event_name == 'push' && github.ref_type == 'tag')) }}"
                },
                "steps": [
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ github.event.pull_request.head.sha || "
                            "github.sha }}",
                            "fetch-depth": 1,
                            "persist-credentials": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                        "run": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
                    },
                    {
                        "if": "env.VERIFY_REUSE == 'true'",
                        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "with": {
                            "python-version": "3.11",
                            "cache": "pip",
                            "cache-dependency-path": "tools/quality/requirements.lock",
                        },
                    },
                    {
                        "if": "env.VERIFY_REUSE == 'true'",
                        "shell": "bash",
                        "run": "sha256:c497417714f0346ffb8c6159765bc5a6c3869f94940f5a88eb3760ef662261e2",
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "qualification-candidate-${{ github.run_id "
                            "}}-${{ github.run_attempt }}",
                            "path": "${{ runner.temp }}",
                        },
                        "if": "env.VERIFY_REUSE == 'true'",
                        "continue-on-error": True,
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "qualification-fresh-linux-${{ "
                            "github.run_id }}-${{ github.run_attempt "
                            "}}",
                            "path": "${{ runner.temp }}/fresh",
                        },
                        "if": "env.VERIFY_REUSE == 'true'",
                        "continue-on-error": True,
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "qualification-fresh-windows-${{ "
                            "github.run_id }}-${{ github.run_attempt "
                            "}}",
                            "path": "${{ runner.temp }}/fresh",
                        },
                        "if": "env.VERIFY_REUSE == 'true'",
                        "continue-on-error": True,
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:febde27dbacaf0a422efd3b4b8426e9a8bd8849fcfa9530b2921a4675d412c24",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "GH_TOKEN": "${{ github.token }}",
                        },
                        "id": "decision",
                    },
                    {
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "qualification-verified-${{ github.run_id "
                            "}}-${{ github.run_attempt }}",
                            "path": "${{ runner.temp }}/verified",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                        "if": "steps.decision.outputs.decision == 'reuse'",
                    },
                ],
            },
            "quality-linux-heavy": {
                "name": "Measured qualification - linux",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 45,
                "needs": [
                    "activation",
                    "quality-linux",
                    "compatibility-windows",
                    "qualification",
                ],
                "if": "needs.activation.outputs.enabled == 'true' && "
                "needs.quality-linux.outputs.scope == 'source' && "
                "needs.qualification.outputs.decision == 'full'",
                "steps": [
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "fetch-depth": 0,
                            "persist-credentials": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                        "run": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
                    },
                    {
                        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "with": {
                            "python-version": "3.11",
                            "cache": "pip",
                            "cache-dependency-path": "tools/quality/requirements.lock",
                        },
                    },
                    {
                        "uses": "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1",
                        "with": {
                            "node-version": "${{ env.NODE_VERSION }}",
                            "cache": "npm",
                            "cache-dependency-path": "tools/quality/package-lock.json\n"
                            "tools/quality/versions.json\n",
                        },
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:2da8204e0669a737bffd04a39f20890e89535bbc4ca44496cbdd6a7bd5852e08",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:d82e511dad71a513d6cedbcde046282a2d957d5108574988ab31753c7c999bb1",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:734ab6d73d005c92cd408a1a5bb6b7bac54d7c872060b00d2fb8c932abc01f0f",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:166ee0560625251c05616eed57e1a6ec74964842e995fd2654d377e316990635",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COVERAGE_DIR": "${{ runner.temp }}/coverage/linux",
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "BEFORE_SHA": "${{ github.event_name == "
                            "'release' && "
                            "'0000000000000000000000000000000000000000' "
                            "|| github.event.before }}",
                            "GITHUB_TOKEN": "${{ github.token }}",
                            "GIT_AUTHOR_NAME": "Codex",
                            "GIT_AUTHOR_EMAIL": "codex@example.com",
                            "GIT_COMMITTER_NAME": "Codex",
                            "GIT_COMMITTER_EMAIL": "codex@example.com",
                        },
                        "run": "sha256:aba2e93f91be4efc757d41bfcd7f7d7ad015888262ef8cbb906cec9e5d3c9227",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:67294089bc1942559bcccd67075045bd267fd7fd2bd7cdd415808e2b2eb6a36a",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                    },
                    {
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "coverage-linux-${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}-${{ github.run_id "
                            "}}-${{ github.run_attempt }}",
                            "path": "${{ runner.temp }}/coverage/linux",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                    },
                ],
            },
            "compatibility-windows-heavy": {
                "name": "Measured qualification - windows",
                "runs-on": "windows-2025",
                "timeout-minutes": 45,
                "needs": [
                    "activation",
                    "quality-linux",
                    "compatibility-windows",
                    "qualification",
                ],
                "if": "needs.activation.outputs.enabled == 'true' && "
                "needs.quality-linux.outputs.scope == 'source' && "
                "needs.qualification.outputs.decision == 'full'",
                "steps": [
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "fetch-depth": 0,
                            "persist-credentials": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha "
                            "}}"
                        },
                        "run": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
                    },
                    {
                        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "with": {
                            "python-version": "3.14",
                            "cache": "pip",
                            "cache-dependency-path": "tools/quality/requirements.lock",
                        },
                    },
                    {
                        "uses": "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1",
                        "with": {
                            "node-version": "${{ env.NODE_VERSION }}",
                            "cache": "npm",
                            "cache-dependency-path": "tools/quality/package-lock.json\n"
                            "tools/quality/versions.json\n",
                        },
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:2da8204e0669a737bffd04a39f20890e89535bbc4ca44496cbdd6a7bd5852e08",
                    },
                    {
                        "shell": "pwsh",
                        "run": "sha256:13a578bedcab1c4fbc15d4107903217306fe62de00526478783a681a97c13ecd",
                    },
                    {
                        "shell": "pwsh",
                        "run": "sha256:dd0f5ee141930a13f99b52ef6f6984e66aaf9b7ccc7cb170258f55395c1d1fdd",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:07e6c1917faeb721c4da862ccc5ba5fa2232951844944cb751692f111b7494dc",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha "
                            "}}"
                        },
                    },
                    {
                        "shell": "pwsh",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha "
                            "}}"
                        },
                        "run": "sha256:6a63c37d1fd4c82fbba6323114ffd6a6cff3e3174e4d4ec64d50525355a8e75f",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:5f4cb527ac9858d457c3afbf86352300f2b2d36ac461a81b62ecac0c2b75e4f5",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:febb2a39bc22b13fb02fbfea282ae5d6c147d15aa446f6b7a14116cfdbf4d548",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha "
                            "}}"
                        },
                    },
                    {
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "coverage-windows-${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}-${{ "
                            "github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/coverage/windows",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                    },
                ],
            },
            "repository-audit": {
                "name": "${{ github.event_name == 'workflow_dispatch' && "
                "'Repository audit (manual)' || 'Repository audit' }}",
                "needs": [
                    "activation",
                    "quality-linux",
                    "compatibility-windows",
                    "qualification",
                    "quality-linux-heavy",
                    "compatibility-windows-heavy",
                ],
                "if": "${{ always() && needs.activation.outputs.enabled != 'false' }}",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 10,
                "steps": [
                    {
                        "env": {
                            "LINUX_RESULT": "${{ needs.quality-linux.result }}",
                            "WINDOWS_RESULT": "${{ "
                            "needs.compatibility-windows.result "
                            "}}",
                            "ACTIVATION_RESULT": "${{ needs.activation.result }}",
                            "DECISION_RESULT": "${{ needs.qualification.result }}",
                            "DECISION": "${{ needs.qualification.outputs.decision }}",
                            "SCOPE": "${{ needs.quality-linux.outputs.scope }}",
                            "HEAVY_LINUX_RESULT": "${{ "
                            "needs.quality-linux-heavy.result "
                            "}}",
                            "HEAVY_WINDOWS_RESULT": "${{ "
                            "needs.compatibility-windows-heavy.result "
                            "}}",
                        },
                        "run": "sha256:7c9abcdc5c2356f0117662eef85f390a4cc3e68f4927e0380a86f181276d61da",
                    },
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "fetch-depth": 1,
                            "persist-credentials": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                        "run": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
                    },
                    {
                        "if": "needs.quality-linux.outputs.scope == 'source'",
                        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "with": {
                            "python-version": "3.11",
                            "cache": "pip",
                            "cache-dependency-path": "tools/quality/requirements.lock",
                        },
                    },
                    {
                        "if": "needs.quality-linux.outputs.scope == 'source'",
                        "shell": "bash",
                        "run": "sha256:c497417714f0346ffb8c6159765bc5a6c3869f94940f5a88eb3760ef662261e2",
                    },
                    {
                        "if": "needs.quality-linux.outputs.scope == 'source' && "
                        "needs.qualification.outputs.decision == 'full'",
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "coverage-linux-${{ "
                            "github.event.pull_request.head.sha || "
                            "github.sha }}-${{ github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/coverage/linux",
                        },
                    },
                    {
                        "if": "needs.quality-linux.outputs.scope == 'source' && "
                        "needs.qualification.outputs.decision == 'full'",
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "coverage-windows-${{ "
                            "github.event.pull_request.head.sha || "
                            "github.sha }}-${{ github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/coverage/windows",
                        },
                    },
                    {
                        "if": "needs.quality-linux.outputs.scope == 'source' && "
                        "needs.qualification.outputs.decision == 'full'",
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                        "run": "sha256:665aa1c1eafe042ce4b66db4ef0c1affad80bc3816fbc0644f325f1cd54b6e81",
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "qualification-fresh-linux-${{ "
                            "github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/fresh",
                        },
                        "if": "needs.quality-linux.outputs.scope == 'source'",
                        "continue-on-error": "${{ "
                        "needs.qualification.outputs.decision "
                        "== 'full' }}",
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "qualification-fresh-windows-${{ "
                            "github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/fresh",
                        },
                        "if": "needs.quality-linux.outputs.scope == 'source'",
                        "continue-on-error": "${{ "
                        "needs.qualification.outputs.decision "
                        "== 'full' }}",
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "qualification-verified-${{ "
                            "github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/verified",
                        },
                        "if": "needs.qualification.outputs.decision == 'reuse'",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:d076e3de6654544996eef152030e3fb280ceac0cf7e28f9242db497a562be681",
                        "if": "needs.qualification.outputs.decision == 'reuse'",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}"
                        },
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:3e19b8d77b367ec9f9955f7c782f5186b694bf1d6a7acb69ab6c7e033ac8919e",
                        "if": "github.repository == 'asphyx0r/git-starter-kit' "
                        "&& needs.quality-linux.outputs.scope == 'source' "
                        "&& needs.qualification.outputs.decision == 'full'",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ "
                            "github.event.pull_request.head.sha "
                            "|| github.sha }}",
                            "GH_TOKEN": "${{ github.token }}",
                        },
                        "id": "seal",
                    },
                    {
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "qualification-${{ "
                            "github.event.pull_request.head.sha || "
                            "github.sha }}-${{ github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/qualification",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                        "if": "steps.seal.outputs.sealed == 'true'",
                    },
                ],
                "permissions": {"contents": "read", "actions": "read"},
            },
        },
    }
    contract["on"]["workflow_dispatch"] = {
        "inputs": {
            "qualification_experiment": {
                "type": "boolean",
                "required": False,
                "default": False,
            }
        }
    }
    contract["jobs"].update(
        {
            "qualification-experiment": {
                "name": "Qualification experiment - ${{ matrix.platform }} / sample "
                "${{ matrix.sample }}",
                "needs": ["activation", "quality-linux", "repository-audit"],
                "if": "github.repository == 'asphyx0r/git-starter-kit' && "
                "github.event_name == 'workflow_dispatch' && "
                "inputs.qualification_experiment && "
                "needs.activation.outputs.enabled == 'true' && "
                "needs.quality-linux.outputs.scope == 'source'",
                "runs-on": "${{ matrix.runner }}",
                "timeout-minutes": 60,
                "permissions": {"contents": "read", "actions": "read"},
                "strategy": {
                    "fail-fast": False,
                    "matrix": {
                        "platform": ["linux", "windows"],
                        "sample": [1, 2, 3],
                        "include": [
                            {
                                "platform": "linux",
                                "runner": "ubuntu-24.04",
                                "python": "3.11",
                            },
                            {
                                "platform": "windows",
                                "runner": "windows-2025",
                                "python": "3.14",
                            },
                        ],
                    },
                },
                "steps": [
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ github.sha }}",
                            "fetch-depth": 0,
                            "persist-credentials": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {"AUDIT_COMMIT_SHA": "${{ github.sha }}"},
                        "run": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
                    },
                    {
                        "id": "python-runtime",
                        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "with": {
                            "python-version": "${{ matrix.python }}",
                            "cache": "pip",
                            "cache-dependency-path": "tools/quality/requirements.lock",
                        },
                    },
                    {
                        "id": "node-runtime",
                        "uses": "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1",
                        "with": {
                            "node-version": "${{ env.NODE_VERSION }}",
                            "cache": "npm",
                            "cache-dependency-path": "tools/quality/package-lock.json\n"
                            "tools/quality/versions.json\n",
                        },
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:2da8204e0669a737bffd04a39f20890e89535bbc4ca44496cbdd6a7bd5852e08",
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:f6ad64b84fa532d9c21ac2e01fcb1e436f9b96db90d57e60b523816c54d9d62a",
                    },
                    {
                        "if": "matrix.platform == 'linux'",
                        "shell": "bash",
                        "run": "sha256:a9940942eb7b522cb37ef4b2dea65698892e9871239c63ce6e5d53e908858606",
                    },
                    {
                        "if": "matrix.platform == 'windows'",
                        "shell": "pwsh",
                        "run": "sha256:fa1715d8e6ba490f5e860ac8c3be55c981514777ef63346c251ad75ed2d826d7",
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "coverage-linux-${{ github.sha }}-${{ "
                            "github.run_id }}-${{ github.run_attempt "
                            "}}",
                            "path": "${{ runner.temp }}/coverage/linux",
                        },
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "coverage-windows-${{ github.sha }}-${{ "
                            "github.run_id }}-${{ github.run_attempt "
                            "}}",
                            "path": "${{ runner.temp }}/coverage/windows",
                        },
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "qualification-fresh-linux-${{ "
                            "github.run_id }}-${{ github.run_attempt "
                            "}}",
                            "path": "${{ runner.temp }}/fresh",
                        },
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "name": "qualification-fresh-windows-${{ "
                            "github.run_id }}-${{ github.run_attempt "
                            "}}",
                            "path": "${{ runner.temp }}/fresh",
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "EXPERIMENT_PLATFORM": "${{ matrix.platform }}",
                            "PYTHON_CACHE_HIT": "${{ "
                            "steps.python-runtime.outputs.cache-hit "
                            "}}",
                            "NPM_CACHE_HIT": "${{ "
                            "steps.node-runtime.outputs.cache-hit "
                            "}}",
                            "EXPERIMENT_SAMPLE": "${{ matrix.sample }}",
                            "AUDIT_COMMIT_SHA": "${{ github.sha }}",
                            "GH_TOKEN": "${{ github.token }}",
                            "GIT_AUTHOR_NAME": "Codex",
                            "GIT_AUTHOR_EMAIL": "codex@example.com",
                            "GIT_COMMITTER_NAME": "Codex",
                            "GIT_COMMITTER_EMAIL": "codex@example.com",
                        },
                        "run": "sha256:3f71c873c34e0675633415cd620a680a237f9ff9514b941d62cdc328ac2581c4",
                    },
                    {
                        "if": "always()",
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "experiment-${{ matrix.platform }}-${{ "
                            "matrix.sample }}-${{ github.run_id "
                            "}}-${{ github.run_attempt }}",
                            "path": "${{ runner.temp }}/experiment",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                    },
                ],
            },
            "experiment-aggregate": {
                "name": "Qualification experiment results",
                "needs": [
                    "activation",
                    "quality-linux",
                    "repository-audit",
                    "qualification-experiment",
                ],
                "if": "github.repository == 'asphyx0r/git-starter-kit' && "
                "github.event_name == 'workflow_dispatch' && "
                "inputs.qualification_experiment && "
                "needs.activation.outputs.enabled == 'true' && "
                "needs.quality-linux.outputs.scope == 'source'",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 10,
                "permissions": {"contents": "read", "actions": "read"},
                "steps": [
                    {
                        "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                        "with": {
                            "ref": "${{ github.sha }}",
                            "fetch-depth": 0,
                            "persist-credentials": False,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {"AUDIT_COMMIT_SHA": "${{ github.sha }}"},
                        "run": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
                    },
                    {
                        "uses": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "with": {
                            "python-version": "3.11",
                            "cache": "pip",
                            "cache-dependency-path": "tools/quality/requirements.lock",
                        },
                    },
                    {
                        "shell": "bash",
                        "run": "sha256:c497417714f0346ffb8c6159765bc5a6c3869f94940f5a88eb3760ef662261e2",
                    },
                    {
                        "uses": "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                        "with": {
                            "pattern": "experiment-*-${{ github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/experiment-input",
                            "merge-multiple": True,
                        },
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ github.sha }}",
                            "GH_TOKEN": "${{ github.token }}",
                        },
                        "run": "sha256:5f83579811367cd565c4281f12910b5aa6eecf7bac9138b82606ba49e84d5e03",
                    },
                    {
                        "if": "always()",
                        "shell": "bash",
                        "run": "sha256:c8cef46594ea73ab48d9d9df9b9149cb85169cd4567e9b621f4274ba2dcdfc17",
                    },
                    {
                        "if": "always()",
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {
                            "name": "experiment-results-${{ github.run_id }}-${{ "
                            "github.run_attempt }}",
                            "path": "${{ runner.temp }}/experiment-results",
                            "include-hidden-files": True,
                            "if-no-files-found": "error",
                            "retention-days": 7,
                        },
                    },
                ],
            },
        }
    )
    contract["env"]["NODE_VERSION"] = node_version
    return contract


def guarded_pull_request_merge_contract(node_version: str) -> dict:
    return {
        "name": "Guarded pull request merge",
        "run-name": "Guarded merge ${{ github.event.client_payload.request_id }}",
        "on": {"repository_dispatch": {"types": ["guarded-squash-merge"]}},
        "permissions": {"contents": "read", "pull-requests": "read"},
        "concurrency": {
            "group": "guarded-merge-${{ github.event.client_payload.pull_request }}",
            "cancel-in-progress": False,
        },
        "env": {"NODE_VERSION": node_version},
        "jobs": {
            "guarded-merge": {
                "name": "Validate and squash merge pull request",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 20,
                "steps": [
                    {
                        "uses": ACTION_REFS["checkout"],
                        "with": {
                            "ref": "${{ needs.activation.outputs.trusted_sha }}",
                            "fetch-depth": 1,
                            "persist-credentials": False,
                        },
                    },
                    setup_python("3.11", None),
                    setup_node("${{ env.NODE_VERSION }}"),
                    {
                        "run": SEALED_SCRIPTS[
                            "guarded-pull-request-merge/guarded-merge/install-locked-commitlint"
                        ]
                    },
                    {
                        "shell": "bash",
                        "env": {"GH_TOKEN": "${{ github.token }}"},
                        "run": SEALED_SCRIPTS[
                            "guarded-pull-request-merge/guarded-merge/validate-guarded-merge-without-privileged-credentials"
                        ],
                    },
                    app_token("guarded-merge-token"),
                    {
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ steps.guarded-merge-token.outputs.token }}"
                        },
                        "run": SEALED_SCRIPTS[
                            "guarded-pull-request-merge/guarded-merge/revalidate-and-squash-merge-with-the-guarded-token"
                        ],
                    },
                ],
                "needs": "activation",
                "if": "needs.activation.outputs.enabled == 'true'",
            },
            "activation": activation_contract("guardedMerge"),
        },
    }


def release_artifacts_contract(node_version: str) -> dict:
    return {
        "name": "Release artifacts",
        "on": {"push": {"tags": ["v*"]}},
        "permissions": {"contents": "read"},
        "jobs": {
            "release-artifacts": {
                "name": "Release artifacts",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 10,
                "steps": [
                    checkout(),
                    setup_python("3.11", "tools/release-artifacts-requirements.txt"),
                    {
                        "run": SEALED_SCRIPTS[
                            "release-artifacts/release-artifacts/install-manifest-validator"
                        ]
                    },
                    {
                        "env": {
                            "RELEASE_REF": "${{ github.ref_name }}",
                            "RELEASE_TREEISH": "${{ github.sha }}",
                        },
                        "run": SEALED_SCRIPTS[
                            "release-artifacts/release-artifacts/validate-release-identification"
                        ],
                    },
                ],
            }
        },
    }


CONTRACTS = {
    "release-package": release_package_contract,
    "agent-rules-update": agent_rules_update_contract,
    "repository-audit": repository_audit_contract,
    "guarded-pull-request-merge": guarded_pull_request_merge_contract,
    "release-artifacts": release_artifacts_contract,
}


def validate_workflow(name: str, workflow: dict, registry: dict) -> None:
    """Validate one loaded workflow against its executable security boundary."""
    if name not in CONTRACTS:
        raise ContractError(f"unknown workflow contract: {name}")
    # Copy only the containing mappings; never mutate the caller's YAML document.
    workflow = dict(workflow)
    if isinstance(workflow.get("jobs"), dict):
        jobs = {}
        for job_id, job in workflow["jobs"].items():
            if not isinstance(job, dict):
                raise ContractError(f"{name}/jobs/{job_id}: expected mapping")
            job = dict(job)
            if isinstance(job.get("steps"), list):
                for index, step in enumerate(job["steps"]):
                    if isinstance(step, dict) and "name" in step:
                        label = step["name"]
                        if not isinstance(label, str) or "${{" in label:
                            raise ContractError(
                                f"{name}/jobs/{job_id}/steps[{index}]/name: "
                                "step labels must be literal presentation text"
                            )
                job["steps"] = [
                    {key: value for key, value in step.items() if key != "name"}
                    if isinstance(step, dict)
                    else step
                    for step in job["steps"]
                ]
            jobs[job_id] = job
        workflow["jobs"] = jobs
    events = workflow.get("on")
    if isinstance(events, dict) and isinstance(events.get("workflow_dispatch"), dict):
        dispatch = dict(events["workflow_dispatch"])
        if isinstance(dispatch.get("inputs"), dict):
            dispatch["inputs"] = {
                key: {
                    field: value
                    for field, value in item.items()
                    if field != "description"
                }
                if isinstance(item, dict)
                else item
                for key, item in dispatch["inputs"].items()
            }
        workflow["on"] = {**events, "workflow_dispatch": dispatch}
    node_version = registry.get("policy", {}).get("nodeCiVersion")
    if not isinstance(node_version, str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", node_version
    ):
        raise ContractError(
            "versions.json: policy.nodeCiVersion must be a pinned version"
        )
    compare_contract(workflow, CONTRACTS[name](node_version), name)


def applicable_workflows(repository_root: Path) -> tuple[str, ...]:
    """Require core workflows and the release workflow in source layouts."""
    source_release_required = any(
        (repository_root / relative).exists()
        for relative in (
            "tools/build-release-package.ps1",
            "tools/starter-kit-manifest.py",
            ".github/workflows/release-package.yml",
        )
    )
    return tuple(
        name
        for name in CONTRACTS
        if name != "release-package" or source_release_required
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=tuple(CONTRACTS))
    parser.add_argument("--path", type=Path, help="Path of the selected workflow")
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--versions", type=Path)
    args = parser.parse_args(argv)
    if args.path and not args.workflow:
        parser.error("--path requires --workflow")
    try:
        registry = json.loads(
            (
                args.versions or args.repository_root / "tools/quality/versions.json"
            ).read_text(encoding="utf-8")
        )
        selected = (
            (args.workflow,)
            if args.workflow
            else applicable_workflows(args.repository_root)
        )
        for name in selected:
            path = args.path or args.repository_root / f".github/workflows/{name}.yml"
            validate_workflow(name, load_workflow(path), registry)
    except (ContractError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"workflow contracts: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
