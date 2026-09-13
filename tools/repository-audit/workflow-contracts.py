#!/usr/bin/env python3
"""Validate workflow objects and executable boundaries independently of YAML layout.

Only presentation fields and lexical script formatting are ignored. In particular,
step order, quote boundaries, statement boundaries and Python control flow remain
part of the contract: a guard cannot be replaced by a comment or a later command.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import re
import sys
import textwrap
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


def compare_contract(actual: Any, expected: Any, context: str, field: str = "") -> None:
    """Compare the small workflow contracts with location-bearing diagnostics."""
    if field == "needs":
        actual = actual if isinstance(actual, list) else [actual]
        expected = expected if isinstance(expected, list) else [expected]
        if not all(isinstance(item, str) for item in actual):
            raise ContractError(f"{context}: job dependencies must be strings")
        actual, expected = sorted(actual), sorted(expected)
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ContractError(
                f"{context}: fields changed; expected {sorted(expected)}"
            )
        for key, value in expected.items():
            if key == "run":
                try:
                    matches = isinstance(actual[key], str) and normalize_script(
                        actual[key], expected.get("shell", "bash")
                    ) == normalize_script(value, expected.get("shell", "bash"))
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


def release_package_contract(node_version: str) -> dict:
    return {
        "name": "Release package",
        "on": {
            "release": {
                "types": [
                    "published",
                ],
            },
            "workflow_dispatch": {
                "inputs": {
                    "tag": {
                        "required": True,
                        "type": "string",
                    },
                    "agent_rules_ref": {
                        "required": True,
                        "type": "string",
                    },
                },
            },
        },
        "permissions": {
            "contents": "read",
        },
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
                            "ref": "${{ github.event_name == 'release' && github.event.release.tag_name || inputs.tag }}",
                        }
                    ),
                    setup_python("3.11", "tools/quality/requirements.lock"),
                    setup_node(node_version),
                    {
                        "shell": "bash",
                        "run": textwrap.dedent(r"""
                            python -m pip install --disable-pip-version-check --no-input \
                              --require-hashes -r tools/quality/requirements.lock
                            npm ci --ignore-scripts --prefix tools/quality
                            """).strip(),
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
                        "run": textwrap.dedent(r"""
                            if [ "$EVENT_NAME" = "release" ]; then
                              starter_ref="$RELEASE_TAG"
                              agent_rules_ref="latest"
                            else
                              starter_ref="$INPUT_TAG"
                              agent_rules_ref="$INPUT_AGENT_RULES_REF"
                            fi

                            # Keep this pattern aligned with repository-audit SemVer smoke tests.
                            semver_tag_pattern='^v(0|[1-9][0-9]*)\.'
                            semver_tag_pattern+='(0|[1-9][0-9]*)\.'
                            semver_tag_pattern+='(0|[1-9][0-9]*)'
                            semver_tag_pattern+='(-((0|[1-9][0-9]*|[0-9A-Za-z-]*'
                            semver_tag_pattern+='[A-Za-z-][0-9A-Za-z-]*)'
                            semver_tag_pattern+='(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*'
                            semver_tag_pattern+='[A-Za-z-][0-9A-Za-z-]*))*))?'
                            semver_tag_pattern+='(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$'
                            if ! [[ "$starter_ref" =~ $semver_tag_pattern ]]; then
                              echo "starter_ref must be a SemVer tag prefixed with v." >&2
                              exit 1
                            fi

                            if [ -z "${agent_rules_ref:-}" ]; then
                              echo "agent_rules_ref must be set to latest or a SemVer tag." >&2
                              exit 1
                            fi

                            if [ "$agent_rules_ref" != "latest" ] &&
                              ! [[ "$agent_rules_ref" =~ $semver_tag_pattern ]]; then
                              message="agent_rules_ref must be latest or a SemVer tag"
                              message+=" prefixed with v."
                              echo "$message" >&2
                              exit 1
                            fi

                            {
                              echo "starter_ref=$starter_ref"
                              echo "starter_sha=$(git rev-parse HEAD)"
                              echo "agent_rules_ref=$agent_rules_ref"
                            } >>"$GITHUB_OUTPUT"
                            """).strip(),
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
                        "run": textwrap.dedent(r"""
                            ./tools/build-release-package.ps1 `
                              -RepositoryRef $env:REPOSITORY_REF `
                              -AgentRulesRef $env:AGENT_RULES_REF `
                              -OutputDirectory $env:RUNNER_TEMP `
                              -PackageName $env:PACKAGE_NAME
                            """).strip(),
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "PACKAGE_PATH": "${{ steps.package.outputs.package_path }}",
                        },
                        "run": textwrap.dedent(r"""
                            validation_root="$RUNNER_TEMP/release-package-validation"
                            mkdir -p "$validation_root"
                            python -m zipfile -e "$PACKAGE_PATH" "$validation_root"
                            cd "$validation_root"
                            "$GITHUB_WORKSPACE/tools/quality/node_modules/.bin/markdownlint-cli2" \
                              --config .markdownlint-cli2.yaml "**/*.md"
                            codespell --config .codespellrc .
                            """).strip(),
                    },
                    {
                        "id": "toolkit",
                        "shell": "bash",
                        "env": {
                            "PACKAGE_PATH": "${{ steps.package.outputs.package_path }}",
                            "REPOSITORY_REF": "${{ steps.refs.outputs.starter_ref }}",
                        },
                        "run": textwrap.dedent(r"""
                            repository_name="${GITHUB_REPOSITORY##*/}"
                            toolkit_path="$RUNNER_TEMP/${repository_name}-${REPOSITORY_REF}-upgrade-toolkit.zip"
                            python tools/starter-kit-upgrade.py toolkit \
                              --new-package "$PACKAGE_PATH" \
                              --output "$toolkit_path"
                            echo "toolkit_path=$toolkit_path" >>"$GITHUB_OUTPUT"
                            """).strip(),
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
                        "run": textwrap.dedent(r"""
                            set -euo pipefail

                            if [ -e "$TRANSFER_ROOT" ]; then
                              echo "Release payload transfer path already exists." >&2
                              exit 1
                            fi
                            mkdir "$TRANSFER_ROOT"

                            package_name="git-starter-kit-${RELEASE_TAG}-with-agent-rules.zip"
                            toolkit_name="git-starter-kit-${RELEASE_TAG}-upgrade-toolkit.zip"
                            if [ "$(basename "$PACKAGE_PATH")" != "$package_name" ] ||
                              [ "$(basename "$TOOLKIT_PATH")" != "$toolkit_name" ]; then
                              echo "Release payload filenames do not match the validated tag." >&2
                              exit 1
                            fi

                            cp -- "$PACKAGE_PATH" "$TRANSFER_ROOT/$package_name"
                            cp -- "$TOOLKIT_PATH" "$TRANSFER_ROOT/$toolkit_name"
                            package_sha256="$(sha256sum "$TRANSFER_ROOT/$package_name" | cut -d' ' -f1)"
                            toolkit_sha256="$(sha256sum "$TRANSFER_ROOT/$toolkit_name" | cut -d' ' -f1)"
                            printf '%s  %s\n%s  %s\n' \
                              "$package_sha256" "$package_name" \
                              "$toolkit_sha256" "$toolkit_name" \
                              >"$TRANSFER_ROOT/SHA256SUMS"
                            printf '%s  %s\n%s  %s\n' \
                              "$package_sha256" "$package_name" \
                              "$toolkit_sha256" "$toolkit_name" \
                              >"$EXPECTED_SUMS_PATH"

                            python - "$TRANSFER_ROOT" \
                              "$package_name" "$toolkit_name" <<'PY'
                            import os
                            from pathlib import Path
                            import stat
                            import sys

                            root = Path(sys.argv[1])
                            allowed = {sys.argv[2], sys.argv[3], "SHA256SUMS"}
                            entries = list(os.scandir(root))
                            if len(entries) != 3 or {entry.name for entry in entries} != allowed:
                                raise SystemExit("Release payload must contain exactly three named files.")
                            for entry in entries:
                                mode = entry.stat(follow_symlinks=False).st_mode
                                if entry.is_symlink() or not stat.S_ISREG(mode):
                                    raise SystemExit(f"Release payload entry is not regular: {entry.name}")
                            PY
                            if ! cmp -s "$EXPECTED_SUMS_PATH" "$TRANSFER_ROOT/SHA256SUMS"; then
                              echo "Release payload checksum manifest changed." >&2
                              exit 1
                            fi
                            (
                              cd "$TRANSFER_ROOT"
                              sha256sum --check --strict SHA256SUMS
                            )

                            {
                              echo "package_name=$package_name"
                              echo "toolkit_name=$toolkit_name"
                              echo "package_sha256=$package_sha256"
                              echo "toolkit_sha256=$toolkit_sha256"
                            } >>"$GITHUB_OUTPUT"
                            """).strip(),
                    },
                    action(
                        "upload-artifact",
                        {
                            "name": "release-package-${{ steps.refs.outputs.starter_ref }}",
                            "path": "${{ runner.temp }}/release-package-transfer/${{ steps.seal.outputs.package_name }}\n${{ runner.temp }}/release-package-transfer/${{ steps.seal.outputs.toolkit_name }}\n${{ runner.temp }}/release-package-transfer/SHA256SUMS\n",
                            "if-no-files-found": "error",
                        },
                    ),
                ],
            },
            "release-checks": {
                "name": "Verify release event checks",
                "needs": "build",
                "if": "github.repository == 'asphyx0r/git-starter-kit'",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 35,
                "permissions": {
                    "contents": "read",
                    "actions": "read",
                },
                "steps": [
                    action(
                        "checkout",
                        {
                            "ref": "${{ github.workflow_sha }}",
                            "persist-credentials": False,
                            "sparse-checkout": "tools/verify-repository-audit-runs.py",
                            "sparse-checkout-cone-mode": False,
                        },
                    ),
                    {
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ github.token }}",
                            "GH_REPO": "${{ github.repository }}",
                            "RELEASE_TAG": "${{ needs.build.outputs.release_tag }}",
                            "RELEASE_SHA": "${{ needs.build.outputs.release_sha }}",
                        },
                        "run": textwrap.dedent(r"""
                            set -euo pipefail
                            deadline=$((SECONDS + 1800))
                            published_at="$(timeout 30s gh api "repos/$GH_REPO/releases/tags/$RELEASE_TAG" \
                              --jq 'select(.draft == false) | .published_at')"
                            if [[ -z "$published_at" || "$published_at" == null ]]; then
                              echo "A published release is required for event verification." >&2
                              exit 1
                            fi
                            workflow_ids=()
                            for workflow in repository-audit.yml agent-rules-update.yml; do
                              workflow_ids+=("$(timeout 30s gh api "repos/$GH_REPO/actions/workflows/$workflow" --jq '.id')")
                            done
                            for workflow_id in "${workflow_ids[@]}"; do
                              remaining=$((deadline - SECONDS))
                              if ((remaining <= 0)); then
                                echo "Release checks exceeded the shared 30-minute deadline." >&2
                                exit 1
                              fi
                              python tools/verify-repository-audit-runs.py \
                                --repository "$GH_REPO" --workflow-id "$workflow_id" \
                                --event release --sha "$RELEASE_SHA" --ref "$RELEASE_TAG" \
                                --created-after "$published_at" --timeout-seconds "$remaining" \
                                --poll-seconds 5 --verbose
                            done
                            """).strip(),
                    },
                ],
            },
            "publish": {
                "name": "Publish release package",
                "needs": [
                    "build",
                    "release-checks",
                ],
                "if": "github.repository == 'asphyx0r/git-starter-kit'",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 5,
                "environment": "release",
                "permissions": {
                    "contents": "write",
                },
                "steps": [
                    action(
                        "download-artifact",
                        {
                            "name": "release-package-${{ needs.build.outputs.release_tag }}",
                            "path": "${{ runner.temp }}/release-package-publish",
                        },
                    ),
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
                        "run": textwrap.dedent(r"""
                            set -euo pipefail

                            python - "$TRANSFER_ROOT" \
                              "$EXPECTED_PACKAGE_NAME" "$EXPECTED_TOOLKIT_NAME" <<'PY'
                            import os
                            from pathlib import Path
                            import stat
                            import sys

                            root = Path(sys.argv[1])
                            allowed = {sys.argv[2], sys.argv[3], "SHA256SUMS"}
                            entries = list(os.scandir(root))
                            if len(entries) != 3 or {entry.name for entry in entries} != allowed:
                                raise SystemExit("Release payload must contain exactly three named files.")
                            for entry in entries:
                                mode = entry.stat(follow_symlinks=False).st_mode
                                if entry.is_symlink() or not stat.S_ISREG(mode):
                                    raise SystemExit(f"Release payload entry is not regular: {entry.name}")
                            PY
                            printf '%s  %s\n%s  %s\n' \
                              "$EXPECTED_PACKAGE_SHA256" "$EXPECTED_PACKAGE_NAME" \
                              "$EXPECTED_TOOLKIT_SHA256" "$EXPECTED_TOOLKIT_NAME" \
                              >"$EXPECTED_SUMS_PATH"
                            if ! cmp -s "$EXPECTED_SUMS_PATH" "$TRANSFER_ROOT/SHA256SUMS"; then
                              echo "Release payload checksum manifest changed." >&2
                              exit 1
                            fi
                            (
                              cd "$TRANSFER_ROOT"
                              sha256sum --check --strict SHA256SUMS
                            )
                            """).strip(),
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
                        "run": textwrap.dedent(r"""
                            set -euo pipefail

                            gh release upload "$RELEASE_TAG" \
                              "$TRANSFER_ROOT/$PACKAGE_NAME" \
                              "$TRANSFER_ROOT/$TOOLKIT_NAME" \
                              "$TRANSFER_ROOT/SHA256SUMS" \
                              --repo "$GH_REPO"

                            if [[ "$EVENT_NAME" = "release" && "$PRERELEASE" = "true" ]]; then
                              gh release edit "$RELEASE_TAG" \
                                --repo "$GH_REPO" \
                                --prerelease=false \
                                --latest
                            fi
                            """).strip(),
                    },
                ],
            },
        },
    }


BOOTSTRAP = textwrap.dedent(r"""
    set -euo pipefail
    default_branch="$(gh api "repos/$GH_REPO" --jq '.default_branch')"
    export DEFAULT_BRANCH="$default_branch"
    encoded_branch="$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["DEFAULT_BRANCH"], safe=""))')"
    trusted_sha="$(gh api "repos/$GH_REPO/commits/$encoded_branch" --jq '.sha')"
    [[ "$trusted_sha" =~ ^[0-9a-f]{40}$ ]] || exit 1
    printf 'trusted_sha=%s\n' "$trusted_sha" >> "$GITHUB_OUTPUT"
    """).strip()
AUTOMATION_RUN = textwrap.dedent(r"""
    python3 -B tools/automation_config.py \
      --automation "$AUTOMATION" --event "$EVENT_NAME" \
      --legacy-sync "$LEGACY_SYNC" >> "$GITHUB_OUTPUT"
    """).strip()
REVISION_RUN = 'test "$(git rev-parse HEAD)" = "$AUDIT_COMMIT_SHA"'
AUDIT_ACTIVATION_RUN = textwrap.dedent(r"""
    python3 -B tools/automation_config.py \
      --automation releasePreflight --event "$EVENT_NAME" >> "$GITHUB_OUTPUT"
    """).strip()
AUDIT_BOOTSTRAP = textwrap.dedent(r"""
    set -euo pipefail
    if [[ "$EVENT_NAME" != push || "$REF_NAME" != codex/release-preflight-* ]]; then
      printf 'enabled=true\n' >> "$GITHUB_OUTPUT"
      exit 0
    fi
    set -euo pipefail
    default_branch="$(gh api "repos/$GH_REPO" --jq '.default_branch')"
    export DEFAULT_BRANCH="$default_branch"
    encoded_branch="$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["DEFAULT_BRANCH"], safe=""))')"
    trusted_sha="$(gh api "repos/$GH_REPO/commits/$encoded_branch" --jq '.sha')"
    [[ "$trusted_sha" =~ ^[0-9a-f]{40}$ ]] || exit 1
    printf 'trusted_sha=%s\n' "$trusted_sha" >> "$GITHUB_OUTPUT"
    """).strip()


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
                "run": BOOTSTRAP,
            },
            checkout(
                ref="${{ steps.resolve.outputs.trusted_sha }}", **{"fetch-depth": 1}
            ),
            {
                "id": "activation",
                "shell": "bash",
                "env": {
                    "AUTOMATION": automation,
                    "EVENT_NAME": "${{ github.event_name }}",
                    "LEGACY_SYNC": "${{ vars.AGENT_RULES_SYNC_ENABLED }}",
                },
                "run": AUTOMATION_RUN,
            },
        ],
    }


def audit_revision_step() -> dict:
    return {
        "shell": "bash",
        "env": {
            "AUDIT_COMMIT_SHA": "${{ github.event.pull_request.head.sha || github.sha }}"
        },
        "run": REVISION_RUN,
    }


def agent_rules_update_contract(node_version: str) -> dict:
    result: dict[str, Any] = {
        "name": "Agent rules update",
        "on": {
            "release": {
                "types": [
                    "published",
                ],
            },
            "schedule": [
                {
                    "cron": "17 5 * * *",
                },
            ],
            "workflow_dispatch": None,
        },
        "permissions": {
            "contents": "read",
        },
        "concurrency": {
            "group": "agent-rules-update",
            "cancel-in-progress": False,
        },
        "env": {
            "RULES_REPOSITORY": "asphyx0r/agent-coding-rules",
            "SYNC_BRANCH": "automation/agent-rules-update",
        },
        "jobs": {
            "prepare": {
                "if": "(\n  github.event_name == 'release' ||\n  vars.AGENT_RULES_SYNC_ENABLED != 'false'\n) && (\n  github.event_name != 'workflow_dispatch' ||\n  github.ref_name == github.event.repository.default_branch\n)",
                "name": "Prepare agent rules update",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 15,
                "permissions": {
                    "contents": "read",
                },
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
                            "ref": "${{ github.event.repository.default_branch }}",
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
                        "run": textwrap.dedent(r"""
                            set -euo pipefail
                            git switch --create "$TARGET_DEFAULT_BRANCH" "$TRUSTED_SHA"
                            bash tools/repository-audit/agent-rules-transfer.sh resolve
                        """).strip(),
                    },
                    {
                        "working-directory": "target",
                        "shell": "bash",
                        "env": {
                            "SOURCE_REF": "${{ steps.resolve.outputs.source_ref }}",
                            "SOURCE_COMMIT": "${{ steps.resolve.outputs.source_commit }}",
                        },
                        "run": textwrap.dedent(r"""
                            set -euo pipefail
                            isolated_root="${RUNNER_TEMP}/agent-rules-external"
                            source_root="${RUNNER_TEMP}/agent-rules-source"
                            plan_path="${RUNNER_TEMP}/agent-rules-plan.json"
                            python_path="$(command -v python)"
                            safe_path="$(dirname "${python_path}"):/usr/bin:/bin"
                            mkdir -p "${isolated_root}/home" "${isolated_root}/tmp"

                            env -i \
                              PATH="${safe_path}" \
                              HOME="${isolated_root}/home" \
                              TMPDIR="${isolated_root}/tmp" \
                              LANG=C.UTF-8 \
                              LC_ALL=C.UTF-8 \
                              PYTHONNOUSERSITE=1 \
                              "${python_path}" \
                              "${source_root}/tools/agent-rules-sync.py" plan \
                              --source "${source_root}" \
                              --target . >"${plan_path}"
                            env -i \
                              PATH="${safe_path}" \
                              HOME="${isolated_root}/home" \
                              TMPDIR="${isolated_root}/tmp" \
                              LANG=C.UTF-8 \
                              LC_ALL=C.UTF-8 \
                              PYTHONNOUSERSITE=1 \
                              "${python_path}" \
                              "${source_root}/tools/agent-rules-sync.py" apply \
                              --source "${source_root}" \
                              --target . \
                              --backup-directory "${isolated_root}/backup"
                            env -i \
                              PATH="${safe_path}" \
                              HOME="${isolated_root}/home" \
                              TMPDIR="${isolated_root}/tmp" \
                              LANG=C.UTF-8 \
                              LC_ALL=C.UTF-8 \
                              PYTHONNOUSERSITE=1 \
                              "${python_path}" \
                              "${source_root}/tools/agent-rules-sync.py" check \
                              --source "${source_root}" \
                              --target .
                            """).strip(),
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
                        "run": "bash tools/repository-audit/agent-rules-transfer.sh seal",
                    },
                    action(
                        "upload-artifact",
                        {
                            "name": "agent-rules-update",
                            "path": "${{ runner.temp }}/agent-rules-transfer/agent-rules.patch\n${{ runner.temp }}/agent-rules-transfer/agent-rules-plan.json\n${{ runner.temp }}/agent-rules-transfer/source.json\n${{ runner.temp }}/agent-rules-transfer/SHA256SUMS\n",
                            "if-no-files-found": "error",
                        },
                        **{
                            "if": "steps.seal.outputs.changed == 'true'",
                        },
                    ),
                ],
            },
            "publish": {
                "needs": "prepare",
                "if": "needs.prepare.outputs.changed == 'true'",
                "name": "Publish agent rules pull request",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 10,
                "permissions": {
                    "contents": "read",
                },
                "steps": [
                    checkout(
                        **{
                            "ref": "${{ needs.prepare.outputs.target_base_commit }}",
                            "path": "target",
                        }
                    ),
                    setup_python("3.11", None),
                    action(
                        "download-artifact",
                        {
                            "name": "agent-rules-update",
                            "path": "${{ runner.temp }}/agent-rules-transfer",
                        },
                    ),
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
                        "run": "bash tools/repository-audit/agent-rules-transfer.sh prepare-publish",
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
                        "run": "bash tools/repository-audit/agent-rules-transfer.sh publish",
                    },
                ],
            },
        },
    }

    result["jobs"]["activation"] = activation_contract("agentRulesSync")
    prepare = result["jobs"]["prepare"]
    prepare["needs"] = "activation"
    prepare["if"] = (
        "needs.activation.outputs.enabled == 'true' && (github.event_name != 'workflow_dispatch' || github.ref_name == github.event.repository.default_branch)"
    )
    prepare["steps"][0]["with"]["ref"] = "${{ needs.activation.outputs.trusted_sha }}"
    return result


def repository_audit_contract(node_version: str) -> dict:
    result: dict[str, Any] = {
        "name": "Repository audit",
        "on": {
            "release": {
                "types": [
                    "published",
                ],
            },
            "push": {
                "branches": [
                    "master",
                    "codex/release-preflight-*",
                ],
                "tags": [
                    "v*",
                ],
            },
            "pull_request": {
                "branches": [
                    "master",
                ],
            },
            "workflow_dispatch": None,
        },
        "permissions": {
            "contents": "read",
        },
        "env": {
            "NODE_VERSION": node_version,
        },
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
                    checkout(**{}),
                    setup_python("3.11", "tools/quality/requirements.lock"),
                    setup_node("${{ env.NODE_VERSION }}"),
                    {
                        "shell": "bash",
                        "run": textwrap.dedent(r"""
                            python -m pip install --disable-pip-version-check \
                              --require-hashes \
                              --requirement tools/quality/requirements.lock
                            npm ci --ignore-scripts --prefix tools/quality
                            """).strip(),
                    },
                    {
                        "shell": "bash",
                        "run": textwrap.dedent(r"""
                            python tools/quality/install-external-tools.py \
                              --platform linux-x64 \
                              --install-root "$RUNNER_TEMP/quality-tools"
                            echo "$RUNNER_TEMP/quality-tools/bin" >> "$GITHUB_PATH"
                            echo "PSModulePath=$RUNNER_TEMP/quality-tools/Modules:${PSModulePath:-}" \
                              >> "$GITHUB_ENV"
                            """).strip(),
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
                        "run": "bash tools/repository-audit.sh full",
                    },
                ],
            },
            "compatibility-windows": {
                "name": "Compatibility - Windows 2025 / Python 3.14",
                "runs-on": "windows-2025",
                "timeout-minutes": 25,
                "steps": [
                    checkout(**{}),
                    setup_python("3.14", "tools/quality/requirements.lock"),
                    setup_node("${{ env.NODE_VERSION }}"),
                    {
                        "shell": "pwsh",
                        "run": textwrap.dedent(r"""
                            python -m pip install --disable-pip-version-check `
                              --require-hashes `
                              --requirement tools/quality/requirements.lock
                            npm ci --ignore-scripts --prefix tools/quality
                            """).strip(),
                    },
                    {
                        "shell": "pwsh",
                        "run": textwrap.dedent(r"""
                            python tools/quality/install-external-tools.py `
                              --platform windows-x64 `
                              --tool PSScriptAnalyzer `
                              --install-root "$env:RUNNER_TEMP/quality-tools"
                            Add-Content $env:GITHUB_ENV `
                              "PSModulePath=$env:RUNNER_TEMP/quality-tools/Modules$([IO.Path]::PathSeparator)$env:PSModulePath"
                            """).strip(),
                    },
                    {
                        "shell": "bash",
                        "run": "bash tools/repository-audit.sh fast",
                    },
                    {
                        "shell": "pwsh",
                        "run": "python -m unittest discover -s tests -p 'test_*.py'",
                    },
                    {
                        "shell": "bash",
                        "run": (
                            "bash tests/test_quality_pre_commit.sh --windows\n"
                            "bash tests/test_quality_pre_push.sh --windows"
                        ),
                    },
                    {
                        "shell": "bash",
                        "run": "bash tools/repository-audit.sh powershell-static",
                    },
                ],
            },
            "repository-audit": {
                "name": "${{ github.event_name == 'workflow_dispatch' && 'Repository audit (manual)' || 'Repository audit' }}",
                "needs": [
                    "quality-linux",
                    "compatibility-windows",
                ],
                "if": "${{ always() }}",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 5,
                "steps": [
                    {
                        "env": {
                            "LINUX_RESULT": "${{ needs.quality-linux.result }}",
                            "WINDOWS_RESULT": "${{ needs.compatibility-windows.result }}",
                        },
                        "run": 'test "$LINUX_RESULT" = success && test "$WINDOWS_RESULT" = success\n',
                    },
                ],
            },
        },
    }

    result["on"]["push"]["branches"].insert(0, "main")
    result["on"]["pull_request"]["branches"].insert(0, "main")
    jobs = result["jobs"]
    jobs["activation"] = activation_contract("releasePreflight")
    jobs["activation"]["outputs"]["enabled"] = (
        "${{ steps.resolve.outputs.enabled || steps.activation.outputs.enabled }}"
    )
    resolve = jobs["activation"]["steps"][0]
    resolve["env"].update(
        {"EVENT_NAME": "${{ github.event_name }}", "REF_NAME": "${{ github.ref_name }}"}
    )
    resolve["run"] = AUDIT_BOOTSTRAP
    for step in jobs["activation"]["steps"][1:]:
        step["if"] = "steps.resolve.outputs.trusted_sha != ''"
    activation = jobs["activation"]["steps"][-1]
    activation["env"] = {"EVENT_NAME": "${{ github.event_name }}"}
    activation["run"] = AUDIT_ACTIVATION_RUN
    for job_id in ("quality-linux", "compatibility-windows"):
        job = jobs[job_id]
        job["needs"] = "activation"
        job["if"] = "needs.activation.outputs.enabled == 'true'"
        job["steps"][0]["with"]["ref"] = (
            "${{ github.event.pull_request.head.sha || github.sha }}"
        )
        job["steps"].insert(1, audit_revision_step())
    windows = jobs["compatibility-windows"]["steps"]
    windows.insert(
        3,
        {
            "id": "scope",
            "shell": "bash",
            "run": 'scope="$(python -B tools/project_validation.py --scope)"\nprintf "scope=%s\\n" "$scope" >> "$GITHUB_OUTPUT"',
        },
    )
    for step in windows:
        if step.get("run", "").startswith(
            ("python -m unittest", "bash tests/test_quality_pre_commit.sh")
        ):
            step["if"] = "steps.scope.outputs.scope == 'source'"
    for platform, runner, version in (
        ("linux", "ubuntu-24.04", "3.11"),
        ("windows", "windows-2025", "3.14"),
    ):
        jobs[f"project-{platform}"] = {
            "name": f"Project checks - {platform}",
            "runs-on": runner,
            "timeout-minutes": 20,
            "needs": "activation",
            "if": "needs.activation.outputs.enabled == 'true'",
            "steps": [
                checkout(ref="${{ github.event.pull_request.head.sha || github.sha }}"),
                audit_revision_step(),
                setup_python(version, None),
                {
                    "shell": "bash",
                    "run": "python -B tools/project_validation.py --repository-root . --timeout 900",
                },
            ],
        }
    aggregate = jobs["repository-audit"]
    aggregate["needs"] = [
        "activation",
        "quality-linux",
        "compatibility-windows",
        "project-linux",
        "project-windows",
    ]
    aggregate["if"] = "${{ always() && needs.activation.outputs.enabled != 'false' }}"
    aggregate["steps"][0]["env"].update(
        {
            "ACTIVATION_RESULT": "${{ needs.activation.result }}",
            "PROJECT_LINUX_RESULT": "${{ needs.project-linux.result }}",
            "PROJECT_WINDOWS_RESULT": "${{ needs.project-windows.result }}",
        }
    )
    aggregate["steps"][0]["run"] = (
        'test "$ACTIVATION_RESULT" = success &&\ntest "$LINUX_RESULT" = success && test "$WINDOWS_RESULT" = success &&\ntest "$PROJECT_LINUX_RESULT" = success && test "$PROJECT_WINDOWS_RESULT" = success\n'
    )
    return result


def guarded_pull_request_merge_contract(node_version: str) -> dict:
    result: dict[str, Any] = {
        "name": "Guarded pull request merge",
        "run-name": "Guarded merge ${{ github.event.client_payload.request_id }}",
        "on": {
            "repository_dispatch": {
                "types": [
                    "guarded-squash-merge",
                ],
            },
        },
        "permissions": {
            "contents": "read",
            "pull-requests": "read",
        },
        "concurrency": {
            "group": "guarded-merge-${{ github.event.client_payload.pull_request }}",
            "cancel-in-progress": False,
        },
        "env": {
            "NODE_VERSION": node_version,
        },
        "jobs": {
            "guarded-merge": {
                "name": "Validate and squash merge pull request",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 20,
                "steps": [
                    action(
                        "checkout",
                        {
                            "ref": "${{ github.sha }}",
                            "fetch-depth": 1,
                            "persist-credentials": False,
                        },
                    ),
                    setup_python("3.11", None),
                    setup_node("${{ env.NODE_VERSION }}"),
                    {
                        "run": "npm ci --ignore-scripts --prefix tools/quality",
                    },
                    {
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ github.token }}",
                        },
                        "run": textwrap.dedent(r"""
                            python tools/merge-pull-request.py --dry-run execute \
                              --event-file "$GITHUB_EVENT_PATH"
                            """).strip(),
                    },
                    app_token("guarded-merge-token"),
                    {
                        "shell": "bash",
                        "env": {
                            "GH_TOKEN": "${{ steps.guarded-merge-token.outputs.token }}",
                        },
                        "run": textwrap.dedent(r"""
                            python tools/merge-pull-request.py execute \
                              --event-file "$GITHUB_EVENT_PATH"
                            """).strip(),
                    },
                ],
            },
        },
    }

    result["jobs"]["activation"] = activation_contract("guardedMerge")
    merge = result["jobs"]["guarded-merge"]
    merge["needs"] = "activation"
    merge["if"] = "needs.activation.outputs.enabled == 'true'"
    merge["steps"][0]["with"]["ref"] = "${{ needs.activation.outputs.trusted_sha }}"
    return result


def release_artifacts_contract(node_version: str) -> dict:
    return {
        "name": "Release artifacts",
        "on": {
            "push": {
                "tags": [
                    "v*",
                ],
            },
        },
        "permissions": {
            "contents": "read",
        },
        "jobs": {
            "release-artifacts": {
                "name": "Release artifacts",
                "runs-on": "ubuntu-24.04",
                "timeout-minutes": 10,
                "steps": [
                    checkout(**{}),
                    setup_python("3.11", "tools/release-artifacts-requirements.txt"),
                    {
                        "run": "python -m pip install --disable-pip-version-check --no-input --require-hashes --requirement tools/release-artifacts-requirements.txt",
                    },
                    {
                        "env": {
                            "RELEASE_REF": "${{ github.ref_name }}",
                            "RELEASE_TREEISH": "${{ github.sha }}",
                        },
                        "run": 'python3 tools/release-artifacts.py check --expected-ref "${RELEASE_REF}" --treeish "${RELEASE_TREEISH}" --repository-root .',
                    },
                ],
            },
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
