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
        if quote is None and char == "#" and (not output or output[-1] == "\n"):
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

    def python_body(match: re.Match) -> str:
        try:
            tree = ast.parse(match.group(1))
        except SyntaxError as error:
            raise ContractError(f"invalid embedded Python: {error.msg}") from error
        # An opaque unquoted token keeps Python string contents out of shell lexing.
        encoded_tree = ast.dump(tree, include_attributes=False).encode("utf-8").hex()
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
    "setup-node": "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
    "upload-artifact": "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "download-artifact": "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "create-github-app-token": (
        "actions/create-github-app-token@"  # Public action revision.
        "bcd2ba49218906704ab6c1aa796996da409d3eb1"
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
    "guarded-pull-request-merge/guarded-merge/install-locked-commitlint": "sha256:99e570e3acd0021a7f55910ccfe1be1b97d077527ce6a0308ed943ca38a291db",
    "guarded-pull-request-merge/guarded-merge/revalidate-and-squash-merge-with-the-guarded-token": "sha256:2705cf6861b29c920ed32609a1625530a0bc7be2bc66e2dbcf5a05addc767013",
    "guarded-pull-request-merge/guarded-merge/validate-guarded-merge-without-privileged-credentials": "sha256:6ec1b848e19fb1c5caf38ff85053425dd13b56385f8a335330c7288e76a2e37e",
    "release-artifacts/release-artifacts/install-manifest-validator": "sha256:76576e63dd0073d8ef2e59a9c8646bd83496908d7d564433af376c0c4223934f",
    "release-artifacts/release-artifacts/validate-release-identification": "sha256:346168d880b8a9e65447f17951b9d2de2c044aded137ca1dbd6545a9032b1cdf",
    "release-package/build/install-locked-quality-dependencies": "sha256:3e2082a688f2ffda88d0648887e7006c40e3385951819b1b82ea34f1b8f0da3b",
    "release-package/build/package": "sha256:e70350fd8b7e552956337d1f2b176ac9f757f3f1a4444b3e7ad7da28c3c27318",
    "release-package/build/refs": "sha256:7984b6b057b3c2c9766ea6766d3e20c297481bfa7639737b28e0f9c533b6985d",
    "release-package/build/seal": "sha256:a85539b5646f749bf93e5b5626aae5181eb0e4eb71a5ecdb947d2858d52552a8",
    "release-package/build/toolkit": "sha256:d6136325baee4819d3a9aafbb5443aee5e99fb35a2e5ea683212141bfa63fe71",
    "release-package/build/validate-composed-package": "sha256:c3300c59f222ca456ad803f2dedbe8ec12bafab4e611d60cf2cf28c4f4476459",
    "release-package/publish/publish": "sha256:6b104f169dc0932ff08557c4f85331c16d2f22d02410be2213c8f43276afe81a",
    "release-package/publish/verify": "sha256:324c33aed75e465d147b2b240a6ffd98419a7c2f9f0c6f75bebf52daa867985c",
    "release-package/release-checks/require-successful-release-event-workflows": "sha256:9fce436f57a77b549350f42a8e49574ef3af47a2bb101131ee2e741b83788aff",
    "repository-audit/activation/activation": "sha256:bfde8d77e709627edd96a2a0452d069e083bc08d7fe3990bd3d441de6c862e94",
    "repository-audit/activation/resolve": "sha256:1116d9de267a68cef6c2ee1e2935be6ab250739384141c93d3f2d57bb218ee31",
    "repository-audit/compatibility-windows/analyze-powershell-on-windows": "sha256:ea7625b2558eb3a6a01170181e9ec5f0439887175427665494a1f8b39db1eeb2",
    "repository-audit/compatibility-windows/install-verified-powershell-analyzer": "sha256:ae239cbd7dc6da006d9e30de4114392c1e630ee2ea7d2adde8f8c92fc9179269",
    "repository-audit/compatibility-windows/run-cross-platform-compatibility-checks": "sha256:072fc07820540ec821834c712d23affc7d258008a43a08b1aeada0b69015e479",
    "repository-audit/compatibility-windows/run-the-complete-python-suite-on-3-14": "sha256:427b5f1ec0c3fef7fe60e688298b380f03cab2ff07dfdbd5d01fe7678c8b83ff",
    "repository-audit/compatibility-windows/scope": "sha256:0cbf4de9b6d95efb15fcef6bac5d89cadcc6bb988415b6422f8ec0b23ac7fd40",
    "repository-audit/compatibility-windows/verify-git-bash-hooks-on-windows": "sha256:999104a1301ddfe9fdc8727a167d73c327140d91f02bb5090b02c38e9ce94673",
    "repository-audit/project-linux/require-selected-checks-to-succeed": "sha256:ddfd5c91a81bd1f1c6f158867b3624e10efb3cbbde4fa8ecbf1d4238b8b98b56",
    "repository-audit/quality-linux/audit-locked-tool-dependencies": "sha256:d324e2e10899f448aba26c2500a06737256b38215fb83c0b9429347756c02e65",
    "repository-audit/quality-linux/install-locked-language-toolchains": "sha256:6d45c44da8cfc2a0316f4f65d9b0e8c1dbb47551652e1e55b9d4adb39577d201",
    "repository-audit/quality-linux/install-verified-external-tools": "sha256:734ab6d73d005c92cd408a1a5bb6b7bac54d7c872060b00d2fb8c932abc01f0f",
    "repository-audit/quality-linux/prepare-previous-push-commit": "sha256:c634a7018a81908b746389cbfba183e998c2aadac8e32fcdbec167e0efb79c38",
    "repository-audit/quality-linux/run-the-complete-quality-gate": "sha256:90bb94b137a4b1de8a24bb128dbb5e5b7fbda723972e879f0b9c9b4750a4c770",
    "repository-audit/quality-linux/verify-exact-audit-revision": "sha256:07e874a372fb20ac4337d8333f223c2b351b46193b92201c7c74a6b549b4ad8c",
    "repository-audit/repository-audit/require-selected-checks-to-succeed": "sha256:581139fc095100e754102128decfff6f12d175e8597725815b225a14e5655ad2",
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
    return {
        "name": "Repository audit",
        "on": {
            "release": {"types": ["published"]},
            "push": None,
            "pull_request": {"branches": ["main", "master"]},
            "workflow_dispatch": None,
        },
        "permissions": {"contents": "read"},
        "env": {"NODE_VERSION": node_version},
        "concurrency": {
            "group": "repository-audit-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}",
            "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
        },
        "jobs": {
            "quality-linux": {
                "name": "Quality - Ubuntu 24.04 / Python 3.11",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 25,
                "steps": [
                    checkout(
                        **{
                            "ref": "${{ github.event.pull_request.head.sha || github.sha }}"
                        }
                    ),
                    audit_revision_step(),
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
                        "run": SEALED_SCRIPTS[
                            "repository-audit/quality-linux/prepare-previous-push-commit"
                        ],
                    },
                    setup_python("3.11", "tools/quality/requirements.lock"),
                    setup_node("${{ env.NODE_VERSION }}"),
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/quality-linux/install-locked-language-toolchains"
                        ],
                    },
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/quality-linux/audit-locked-tool-dependencies"
                        ],
                    },
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/quality-linux/install-verified-external-tools"
                        ],
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "AUDIT_COMMIT_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
                            "BEFORE_SHA": "${{ github.event_name == 'release' && '0000000000000000000000000000000000000000' || github.event.before }}",
                            "GITHUB_TOKEN": "${{ github.token }}",
                            "GIT_AUTHOR_NAME": "Codex",
                            "GIT_AUTHOR_EMAIL": "codex@example.com",
                            "GIT_COMMITTER_NAME": "Codex",
                            "GIT_COMMITTER_EMAIL": "codex@example.com",
                        },
                        "run": SEALED_SCRIPTS[
                            "repository-audit/quality-linux/run-the-complete-quality-gate"
                        ],
                    },
                ],
                "needs": "activation",
                "if": "needs.activation.outputs.enabled == 'true'",
            },
            "compatibility-windows": {
                "name": "Compatibility - Windows 2025 / Python 3.14",
                "runs-on": "windows-2025",
                "timeout-minutes": 25,
                "steps": [
                    checkout(
                        **{
                            "ref": "${{ github.event.pull_request.head.sha || github.sha }}"
                        }
                    ),
                    audit_revision_step(),
                    setup_python("3.14", "tools/quality/requirements.lock"),
                    {
                        "id": "scope",
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/compatibility-windows/scope"
                        ],
                    },
                    setup_node("${{ env.NODE_VERSION }}"),
                    {
                        "shell": "pwsh",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/quality-linux/install-locked-language-toolchains"
                        ],
                    },
                    {
                        "shell": "pwsh",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/compatibility-windows/install-verified-powershell-analyzer"
                        ],
                    },
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/compatibility-windows/run-cross-platform-compatibility-checks"
                        ],
                    },
                    {
                        "shell": "pwsh",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/compatibility-windows/run-the-complete-python-suite-on-3-14"
                        ],
                        "if": "steps.scope.outputs.scope == 'source'",
                    },
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/compatibility-windows/verify-git-bash-hooks-on-windows"
                        ],
                        "if": "steps.scope.outputs.scope == 'source'",
                    },
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/compatibility-windows/analyze-powershell-on-windows"
                        ],
                    },
                ],
                "needs": "activation",
                "if": "needs.activation.outputs.enabled == 'true'",
            },
            "repository-audit": {
                "name": "${{ github.event_name == 'workflow_dispatch' && 'Repository audit (manual)' || 'Repository audit' }}",
                "needs": [
                    "activation",
                    "quality-linux",
                    "compatibility-windows",
                    "project-linux",
                    "project-windows",
                ],
                "if": "${{ always() && needs.activation.outputs.enabled != 'false' }}",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 5,
                "steps": [
                    {
                        "env": {
                            "LINUX_RESULT": "${{ needs.quality-linux.result }}",
                            "WINDOWS_RESULT": "${{ needs.compatibility-windows.result }}",
                            "ACTIVATION_RESULT": "${{ needs.activation.result }}",
                            "PROJECT_LINUX_RESULT": "${{ needs.project-linux.result }}",
                            "PROJECT_WINDOWS_RESULT": "${{ needs.project-windows.result }}",
                        },
                        "run": SEALED_SCRIPTS[
                            "repository-audit/repository-audit/require-selected-checks-to-succeed"
                        ],
                    }
                ],
            },
            "activation": {
                "name": "Read trusted automation configuration",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 5,
                "permissions": {"contents": "read"},
                "outputs": {
                    "enabled": "${{ steps.resolve.outputs.enabled || steps.activation.outputs.enabled }}",
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
                        "run": SEALED_SCRIPTS["repository-audit/activation/resolve"],
                    },
                    {
                        "uses": ACTION_REFS["checkout"],
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
                        "run": SEALED_SCRIPTS["repository-audit/activation/activation"],
                        "if": "steps.resolve.outputs.trusted_sha != ''",
                    },
                ],
            },
            "project-linux": {
                "name": "Project checks - linux",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 20,
                "needs": "activation",
                "if": "needs.activation.outputs.enabled == 'true'",
                "steps": [
                    checkout(
                        **{
                            "ref": "${{ github.event.pull_request.head.sha || github.sha }}"
                        }
                    ),
                    audit_revision_step(),
                    setup_python("3.11", None),
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/project-linux/require-selected-checks-to-succeed"
                        ],
                    },
                ],
            },
            "project-windows": {
                "name": "Project checks - windows",
                "runs-on": "windows-2025",
                "timeout-minutes": 20,
                "needs": "activation",
                "if": "needs.activation.outputs.enabled == 'true'",
                "steps": [
                    checkout(
                        **{
                            "ref": "${{ github.event.pull_request.head.sha || github.sha }}"
                        }
                    ),
                    audit_revision_step(),
                    setup_python("3.14", None),
                    {
                        "shell": "bash",
                        "run": SEALED_SCRIPTS[
                            "repository-audit/project-linux/require-selected-checks-to-succeed"
                        ],
                    },
                ],
            },
        },
    }


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
