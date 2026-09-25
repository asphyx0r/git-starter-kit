from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools/repository-audit/workflow-contracts.py"
WORKFLOWS = (
    "release-package",
    "agent-rules-update",
    "repository-audit",
    "guarded-pull-request-merge",
    "release-artifacts",
)


def resolve_bash():
    if sys.platform == "win32":
        git = shutil.which("git")
        if git:
            for parent in Path(git).parents:
                candidate = parent / "bin/bash.exe"
                if candidate.is_file():
                    return str(candidate)
        raise FileNotFoundError(
            "Git Bash executable was not found in the Git installation."
        )
    return shutil.which("bash") or "bash"


BASH = resolve_bash()


class WorkflowContractTests(unittest.TestCase):
    def test_bash_resolution_uses_path_and_verified_git_layout_fallback(self):
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(shutil, "which", return_value="/chosen/bash"),
        ):
            self.assertEqual(resolve_bash(), "/chosen/bash")
        with tempfile.TemporaryDirectory() as temporary:
            installation = Path(temporary) / "Git"
            executable = installation / "bin/bash.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"owned resolver fixture")
            for layout in (
                "cmd/git.exe",
                "mingw64/bin/git.exe",
                "mingw64/libexec/git-core/git.exe",
            ):
                with (
                    self.subTest(layout=layout),
                    mock.patch.object(sys, "platform", "win32"),
                    mock.patch.object(
                        shutil,
                        "which",
                        side_effect={
                            "git": str(installation / layout),
                            "bash": "C:/Windows/System32/bash.exe",
                        }.get,
                    ),
                ):
                    self.assertEqual(resolve_bash(), str(executable))
            executable.unlink()
            with (
                mock.patch.object(sys, "platform", "win32"),
                mock.patch.object(
                    shutil,
                    "which",
                    return_value=str(installation / "mingw64/bin/git.exe"),
                ),
                self.assertRaises(FileNotFoundError),
            ):
                resolve_bash()
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(shutil, "which", return_value=None) as lookup,
        ):
            self.assertEqual(resolve_bash(), "bash")
            lookup.assert_called_once_with("bash")

    def test_cli_accepts_current_workflows(self):
        result = subprocess.run(
            [sys.executable, "-B", str(VALIDATOR)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        if self._testMethodName == "test_cli_accepts_current_workflows":
            return
        spec = importlib.util.spec_from_file_location("workflow_contracts", VALIDATOR)
        self.validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.validator)
        self.registry = json.loads((ROOT / "tools/quality/versions.json").read_text())
        self.workflows = self.validator.applicable_workflows(ROOT)

    def read_workflow(self, name):
        if name == "release-package" and name not in self.workflows:
            self.skipTest("consumer package does not ship the source release workflow")
        return self.validator.load_workflow(ROOT / f".github/workflows/{name}.yml")

    def test_windows_hook_subset_is_mandatory(self):
        workflow = self.read_workflow("repository-audit")
        steps = workflow["jobs"]["compatibility-windows"]["steps"]
        expected_run = (
            "bash tests/test_quality_pre_commit.sh --windows\n"
            "bash tests/test_quality_pre_push.sh --windows"
        )
        matches = [
            step for step in steps if step.get("run", "").strip() == expected_run
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["shell"], "bash")
        self.validate("repository-audit", workflow)
        steps.remove(matches[0])
        with self.assertRaises(self.validator.ContractError):
            self.validate("repository-audit", workflow)

    def validate(self, name, workflow):
        self.validator.validate_workflow(name, workflow, self.registry)

    def test_audit_checks_exact_actual_head_and_distinct_project_results(self):
        workflow = self.read_workflow("repository-audit")
        self.assertIsNone(workflow["on"]["push"])
        self.assertIn("main", workflow["on"]["pull_request"]["branches"])
        self.assertIn("master", workflow["on"]["pull_request"]["branches"])
        for job_id in (
            "quality-linux",
            "compatibility-windows",
            "project-linux",
            "project-windows",
        ):
            job = workflow["jobs"][job_id]
            checkout = next(
                step
                for step in job["steps"]
                if "actions/checkout@" in step.get("uses", "")
            )
            self.assertEqual(
                checkout["with"]["ref"],
                "${{ github.event.pull_request.head.sha || github.sha }}",
            )
            self.assertIn(
                "Verify exact audit revision",
                [step.get("name") for step in job["steps"]],
            )
        self.assertIn("project-linux", workflow["jobs"]["repository-audit"]["needs"])
        self.assertIn("project-windows", workflow["jobs"]["repository-audit"]["needs"])
        self.validate("repository-audit", workflow)

    def test_optional_automation_jobs_gate_before_install_or_credentials(self):
        for name, job_id in (
            ("agent-rules-update", "prepare"),
            ("guarded-pull-request-merge", "guarded-merge"),
        ):
            workflow = self.read_workflow(name)
            gate = workflow["jobs"]["activation"]
            self.assertEqual(gate["permissions"], {"contents": "read"})
            self.assertNotIn("setup-", json.dumps(gate))
            self.assertNotIn("secrets.", json.dumps(gate))
            self.assertNotIn("npm ci", json.dumps(gate))
            job = workflow["jobs"][job_id]
            self.assertEqual(job["needs"], "activation")
            self.assertIn("needs.activation.outputs.enabled == 'true'", job["if"])
            self.assertEqual(
                job["steps"][0]["with"]["ref"],
                "${{ needs.activation.outputs.trusted_sha }}",
            )
            self.validate(name, workflow)

    def test_agent_sync_attaches_default_branch_at_the_trusted_commit(self):
        workflow = self.read_workflow("agent-rules-update")
        step = next(
            item
            for item in workflow["jobs"]["prepare"]["steps"]
            if item.get("id") == "resolve"
        )
        for branch in ("main", "master"):
            with (
                self.subTest(branch=branch),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)

                def git(*args):
                    return subprocess.check_output(
                        ["git", *args], cwd=root, text=True, stderr=subprocess.PIPE
                    ).strip()

                git("init", "--quiet", "--initial-branch=fixture")
                commit = (
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "core.hooksPath=",
                    "commit",
                    "--quiet",
                    "--allow-empty",
                    "-m",
                    "fixture",
                )
                git(*commit)
                trusted = git("rev-parse", "HEAD")
                git(*commit)
                git("update-ref", f"refs/remotes/origin/{branch}", "HEAD")
                git("checkout", "--quiet", "--detach", trusted)
                resolver = root / "tools/repository-audit/agent-rules-transfer.sh"
                resolver.parent.mkdir(parents=True)
                resolver.write_text(
                    "#!/bin/bash\nset -euo pipefail\n"
                    'test "$(git symbolic-ref --short HEAD)" = "$TARGET_DEFAULT_BRANCH"\n'
                    'test "$(git rev-parse HEAD)" = "$TRUSTED_SHA"\n',
                    encoding="utf-8",
                    newline="\n",
                )
                for expected, success in (("0" * 40, False), (trusted, True)):
                    result = subprocess.run(
                        [BASH, "-c", step["run"]],
                        cwd=root,
                        env={
                            **os.environ,
                            "TARGET_DEFAULT_BRANCH": branch,
                            "TRUSTED_SHA": expected,
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode == 0, success, result.stderr)
                    self.assertEqual(git("rev-parse", "HEAD"), trusted)
                self.assertEqual(git("symbolic-ref", "--short", "HEAD"), branch)
        self.assertEqual(
            step["env"]["TRUSTED_SHA"], "${{ needs.activation.outputs.trusted_sha }}"
        )

    def test_push_audit_has_no_branch_tag_or_path_filters(self):
        workflow = self.read_workflow("repository-audit")
        self.assertIsNone(workflow["on"]["push"])
        self.assertEqual(workflow["on"]["pull_request"]["branches"], ["main", "master"])
        self.assertEqual(workflow["on"]["release"]["types"], ["published"])

    def test_reference_deletion_stops_before_metadata_or_checkout(self):
        resolve = self.read_workflow("repository-audit")["jobs"]["activation"]["steps"][
            0
        ]
        for ref_type, ref in (
            ("branch", "feature/finished"),
            ("branch", "codex/release-preflight-v1.0.0"),
            ("tag", "snapshot/finished"),
        ):
            with self.subTest(ref=ref), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "outputs"
                marker = Path(temporary) / "forbidden-access"
                for name in ("gh", "python3"):
                    shim = Path(temporary) / name
                    shim.write_text(
                        '#!/usr/bin/env bash\nprintf access >> "$ACCESS_MARKER"\nexit 99\n'
                    )
                    shim.chmod(0o755)
                result = subprocess.run(
                    [BASH, "-c", resolve["run"]],
                    cwd=temporary,
                    env={
                        **os.environ,
                        "EVENT_NAME": "push",
                        "EVENT_DELETED": "true",
                        "REF_NAME": ref,
                        "REF_TYPE": ref_type,
                        "GITHUB_OUTPUT": str(output),
                        "GH_REPO": "invalid/no-metadata",
                        "ACCESS_MARKER": str(marker),
                        "PATH": temporary + os.pathsep + os.environ["PATH"],
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.read_text(), "enabled=false\n")
                self.assertIn("no new commit", result.stdout)
                self.assertFalse(marker.exists())

    def test_dependency_audit_blocks_advisories_and_registry_errors(self):
        steps = self.read_workflow("repository-audit")["jobs"]["quality-linux"]["steps"]
        audits = [step for step in steps if step.get("run", "").startswith("npm audit")]
        self.assertEqual(
            len(audits), 1, "the locked npm toolchain needs a blocking audit"
        )
        step = audits[0]
        self.assertNotIn("continue-on-error", step)
        self.assertNotIn("if", step)
        for status in (0, 1, 42):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as temporary,
            ):
                arguments = Path(temporary) / "arguments"
                result = subprocess.run(
                    [
                        BASH,
                        "-c",
                        'npm() { printf "%s\\n" "$*" > "$AUDIT_ARGUMENTS"; '
                        'return "$AUDIT_EXIT"; }\n' + step["run"],
                    ],
                    env={
                        **os.environ,
                        "AUDIT_ARGUMENTS": str(arguments),
                        "AUDIT_EXIT": str(status),
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(
                    arguments.read_text().strip(),
                    "audit --audit-level=high --include=dev --prefix tools/quality",
                )

    def test_push_history_restores_missing_commit_without_moving_refs(self):
        step = self.read_workflow("repository-audit")["jobs"]["quality-linux"]["steps"][
            2
        ]
        self.assertEqual(step.get("timeout-minutes"), 2)
        with tempfile.TemporaryDirectory() as temporary:
            origin = Path(temporary) / "origin"
            checkout = Path(temporary) / "checkout"
            origin.mkdir()

            def git(root, *arguments):
                return subprocess.check_output(
                    ["git", *arguments], cwd=root, text=True, stderr=subprocess.PIPE
                ).strip()

            git(origin, "init", "--quiet", "--initial-branch=main")
            commit = (
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "-c",
                "core.hooksPath=",
                "commit",
                "--quiet",
                "--allow-empty",
            )
            git(origin, *commit, "-m", "base")
            git(origin, "switch", "--quiet", "-c", "old")
            git(origin, *commit, "-m", "previous push")
            before = git(origin, "rev-parse", "HEAD")
            git(origin, "switch", "--quiet", "main")
            git(origin, *commit, "-m", "rewritten push")
            git(
                origin,
                "clone",
                "--quiet",
                "--no-local",
                "--single-branch",
                "--branch=main",
                str(origin),
                str(checkout),
            )
            missing = subprocess.run(
                ["git", "cat-file", "-e", before],
                cwd=checkout,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(missing.returncode, 0)
            head = git(checkout, "rev-parse", "HEAD")
            refs = git(checkout, "show-ref")
            config = (checkout / ".git/config").read_bytes()
            fetch_head = checkout / ".git/FETCH_HEAD"
            fetch_head.write_bytes(b"preserved previous fetch\n")
            previous_fetch = fetch_head.read_bytes()

            def run_step(sha):
                return subprocess.run(
                    [BASH, "-c", step["run"]],
                    cwd=checkout,
                    env={
                        **os.environ,
                        "EVENT_NAME": "push",
                        "BEFORE_SHA": sha,
                        "GH_TOKEN": "",
                        "GH_PROMPT_DISABLED": "1",
                        "GIT_TERMINAL_PROMPT": "0",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )

            restored = run_step(before)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            git(checkout, "cat-file", "-e", before + "^{commit}")
            git(checkout, "diff", "--check", before + "..HEAD")
            self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)
            self.assertEqual(git(checkout, "show-ref"), refs)
            self.assertEqual((checkout / ".git/config").read_bytes(), config)
            self.assertEqual(
                fetch_head.read_bytes() if fetch_head.exists() else None,
                previous_fetch,
            )
            git(
                checkout, "remote", "set-url", "origin", str(Path(temporary) / "absent")
            )
            self.assertEqual(run_step(before).returncode, 0)
            unavailable = run_step("f" * 40)
            self.assertNotEqual(unavailable.returncode, 0)
            self.assertEqual(git(checkout, "rev-parse", "HEAD"), head)
            self.assertEqual(git(checkout, "show-ref"), refs)

    def test_push_history_skips_other_events_and_rejects_invalid_sha(self):
        step = self.read_workflow("repository-audit")["jobs"]["quality-linux"]["steps"][
            2
        ]
        self.assertIn("run", step, "push history needs an explicit preparation step")
        for event, sha, success in (
            ("pull_request", "invalid", True),
            ("release", "invalid", True),
            ("workflow_dispatch", "invalid", True),
            ("push", "0" * 40, True),
            ("push", "", False),
            ("push", "--invalid-option", False),
            ("push", "main", False),
        ):
            with self.subTest(event=event, sha=sha):
                result = subprocess.run(
                    [
                        BASH,
                        "-c",
                        "git() { echo unexpected-git-access >&2; return 99; }\n"
                        + step["run"],
                    ],
                    env={**os.environ, "EVENT_NAME": event, "BEFORE_SHA": sha},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, success, result.stderr)
                self.assertNotIn("unexpected-git-access", result.stderr)

    def test_ordinary_audit_bootstraps_without_new_default_branch_runtime(self):
        gate = self.read_workflow("repository-audit")["jobs"]["activation"]
        resolve = gate["steps"][0]
        for event, ref, ref_type in (
            ("pull_request", "feature/bootstrap", "branch"),
            ("push", "main", "branch"),
            ("push", "master", "branch"),
            ("push", "feature/nested/name", "branch"),
            ("push", "v1.0.0", "tag"),
            ("push", "snapshot/nightly", "tag"),
            ("push", "codex/release-preflight-v1.0.0", "tag"),
            ("release", "v1.0.0", "tag"),
            ("workflow_dispatch", "main", "branch"),
        ):
            with (
                self.subTest(event=event, ref=ref),
                tempfile.TemporaryDirectory() as temporary,
            ):
                output = Path(temporary) / "outputs"
                marker = Path(temporary) / "forbidden-access"
                for name in ("gh", "python3"):
                    shim = Path(temporary) / name
                    shim.write_text(
                        '#!/usr/bin/env bash\nprintf access >> "$ACCESS_MARKER"\nexit 99\n'
                    )
                    shim.chmod(0o755)
                result = subprocess.run(
                    [BASH, "-c", resolve["run"]],
                    cwd=temporary,
                    env={
                        **os.environ,
                        "EVENT_NAME": event,
                        "EVENT_DELETED": "true" if event != "push" else "false",
                        "REF_NAME": ref,
                        "REF_TYPE": ref_type,
                        "GITHUB_OUTPUT": str(output),
                        "GH_REPO": "invalid/no-metadata",
                        "ACCESS_MARKER": str(marker),
                        "PATH": temporary + os.pathsep + os.environ["PATH"],
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.read_text(), "enabled=true\n")
                self.assertFalse((Path(temporary) / "tools").exists())
                self.assertFalse(marker.exists())
        for step in gate["steps"][1:]:
            self.assertEqual(step["if"], "steps.resolve.outputs.trusted_sha != ''")

    def test_selected_preflight_missing_trusted_runtime_fails_without_enabled_output(
        self,
    ):
        gate = self.read_workflow("repository-audit")["jobs"]["activation"]
        step = gate["steps"][-1]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs"
            command = step["run"].replace(
                "python3", '"' + sys.executable.replace("\\", "/") + '"', 1
            )
            result = subprocess.run(
                [BASH, "-c", command],
                cwd=temporary,
                env={**os.environ, "EVENT_NAME": "push", "GITHUB_OUTPUT": str(output)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("automation_config.py", result.stderr)
            self.assertEqual(output.read_text(), "")

    def test_consumer_does_not_select_source_maintenance_tests(self):
        steps = self.read_workflow("repository-audit")["jobs"]["compatibility-windows"][
            "steps"
        ]
        for step in steps:
            if step.get("run", "").startswith(
                ("python -m unittest", "bash tests/test_quality_pre_commit.sh")
            ):
                self.assertEqual(step["if"], "steps.scope.outputs.scope == 'source'")

    def test_aggregate_rejects_each_selected_failed_cancelled_or_skipped_result(self):
        step = self.read_workflow("repository-audit")["jobs"]["repository-audit"][
            "steps"
        ][0]
        for selected in step["env"]:
            for failure in ("failure", "cancelled", "skipped", ""):
                with self.subTest(selected=selected, failure=failure):
                    environment = dict.fromkeys(step["env"], "success")
                    environment[selected] = failure
                    result = subprocess.run(
                        [BASH, "-c", step["run"]],
                        env={**os.environ, **environment},
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
        result = subprocess.run(
            [BASH, "-c", step["run"]],
            env={**os.environ, **dict.fromkeys(step["env"], "success")},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_revision_guard_rejects_merge_or_wrong_head(self):
        step = self.read_workflow("repository-audit")["jobs"]["project-linux"]["steps"][
            1
        ]
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run(["git", "init", "--quiet", temporary], check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "core.hooksPath=",
                    "commit",
                    "--quiet",
                    "--allow-empty",
                    "-m",
                    "fixture",
                ],
                cwd=temporary,
                check=True,
            )
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=temporary, text=True
            ).strip()
            for expected, success in (("0" * 40, False), (head, True)):
                result = subprocess.run(
                    [BASH, "-c", step["run"]],
                    cwd=temporary,
                    env={**os.environ, "AUDIT_COMMIT_SHA": expected},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, success, result.stderr)

    def test_mapping_order_indentation_comments_and_step_names_are_irrelevant(self):
        def reorder(value):
            if isinstance(value, dict):
                return {
                    key: reorder(item) for key, item in reversed(list(value.items()))
                }
            if isinstance(value, list):
                return [reorder(item) for item in value]
            return value

        for name in self.workflows:
            with self.subTest(workflow=name):
                workflow = reorder(self.read_workflow(name))
                for job in workflow["jobs"].values():
                    for step in job["steps"]:
                        step["name"] = "A descriptive replacement name"
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "workflow.yml"
                    path.write_text(
                        "# equivalent formatting\n"
                        + yaml.safe_dump(workflow, sort_keys=False, indent=4),
                        encoding="utf-8",
                    )
                    self.validate(name, self.validator.load_workflow(path))

    def test_fixture_loading_accepts_quoted_and_unquoted_event_keys(self):
        name = "repository-audit"
        content = (ROOT / f".github/workflows/{name}.yml").read_text(encoding="utf-8")
        for event_key in ('"on":', "on:"):
            with (
                self.subTest(event_key=event_key),
                tempfile.TemporaryDirectory() as temporary,
            ):
                fixture_root = Path(temporary)
                path = fixture_root / f".github/workflows/{name}.yml"
                path.parent.mkdir(parents=True)
                path.write_text(content.replace('"on":', event_key), encoding="utf-8")
                with mock.patch(f"{__name__}.ROOT", fixture_root):
                    workflow = self.read_workflow(name)
                self.assertIn("on", workflow)
                self.validate(name, workflow)

    def test_invalid_top_level_heredoc_indentation_is_not_normalized(self):
        for job_id, step_id in (("build", "seal"), ("publish", "verify")):
            with self.subTest(job=job_id):
                workflow = self.read_workflow("release-package")
                step = next(
                    step
                    for step in workflow["jobs"][job_id]["steps"]
                    if step.get("id") == step_id
                )
                match = re.search(r"<<'PY'\n(.*?)\nPY(?=\n|$)", step["run"], re.DOTALL)
                indented = "\n".join(
                    "    " + line for line in match.group(1).splitlines()
                )
                with self.assertRaises(IndentationError):
                    compile(indented, "<workflow heredoc>", "exec")
                step["run"] = (
                    step["run"][: match.start(1)]
                    + indented
                    + step["run"][match.end(1) :]
                )
                with self.assertRaises(self.validator.ContractError):
                    self.validate("release-package", workflow)

    def test_valid_embedded_python_formatting_remains_accepted(self):
        workflow = self.read_workflow("release-package")
        verify = workflow["jobs"]["publish"]["steps"][1]
        verify["run"] = (
            verify["run"]
            .replace(
                'allowed = {sys.argv[2], sys.argv[3], "SHA256SUMS"}',
                'allowed = {\n    sys.argv[2],\n    sys.argv[3],\n    "SHA256SUMS",\n}',
            )
            .replace("import os\n", "import os  # harmless comment\n\n")
        )
        self.validate("release-package", workflow)

    def test_literal_whitespace_around_repository_expression_is_rejected(self):
        for prefix, suffix in ((" ", " "), ("\t", ""), ("", "\n")):
            with self.subTest(prefix=prefix, suffix=suffix):
                workflow = self.read_workflow("release-package")
                publish = workflow["jobs"]["publish"]["steps"][2]
                publish["env"]["GH_REPO"] = prefix + publish["env"]["GH_REPO"] + suffix
                with self.assertRaises(self.validator.ContractError):
                    self.validate("release-package", workflow)

    def test_expression_internal_whitespace_remains_accepted(self):
        workflow = self.read_workflow("release-package")
        publish = workflow["jobs"]["publish"]["steps"][2]
        publish["env"]["GH_REPO"] = "${{    github.repository\n }}"
        self.validate("release-package", workflow)

    def test_every_security_or_functional_field_rejects_mutation(self):
        def leaves(value, path=()):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"name", "description"}:
                        continue
                    yield from leaves(item, (*path, key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    yield from leaves(item, (*path, index))
            else:
                yield path, value

        for name in self.workflows:
            workflow = self.read_workflow(name)
            for path, value in leaves(workflow):
                with self.subTest(workflow=name, path=path):
                    mutated = copy.deepcopy(workflow)
                    parent = mutated
                    for key in path[:-1]:
                        parent = parent[key]
                    parent[path[-1]] = (
                        not value if isinstance(value, bool) else "unsafe-drift"
                    )
                    with self.assertRaises(self.validator.ContractError):
                        self.validate(name, mutated)

    def test_equivalent_script_formatting_and_dependency_order_pass(self):
        for name in self.workflows:
            with self.subTest(workflow=name):
                workflow = self.read_workflow(name)
                for job in workflow["jobs"].values():
                    if "needs" in job:
                        needs = job["needs"]
                        job["needs"] = (
                            list(reversed(needs))
                            if isinstance(needs, list)
                            else [needs]
                        )
                    for step in job["steps"]:
                        if "run" not in step:
                            continue
                        continuation = "`" if step.get("shell") == "pwsh" else "\\"
                        script = re.sub(
                            re.escape(continuation) + r"\n[ \t]*", " ", step["run"]
                        )
                        # Python AST formatting and shell leading whitespace are independent.
                        if "<<'PY'" not in script:
                            script = "\n".join(
                                "  " + line.rstrip() + "  "
                                for line in script.splitlines()
                            )
                        step["run"] = "# harmless comment\n" + script + "\n\n"
                self.validate(name, workflow)

    def test_missing_extra_and_disabled_jobs_fail(self):
        for name in self.workflows:
            for operation in ("missing", "extra", "disabled"):
                with self.subTest(workflow=name, operation=operation):
                    workflow = self.read_workflow(name)
                    job_id = next(iter(workflow["jobs"]))
                    if operation == "missing":
                        del workflow["jobs"][job_id]
                    elif operation == "extra":
                        workflow["jobs"]["extra"] = copy.deepcopy(
                            workflow["jobs"][job_id]
                        )
                    else:
                        workflow["jobs"][job_id]["if"] = "false"
                    with self.assertRaises(self.validator.ContractError):
                        self.validate(name, workflow)

    def test_comments_cannot_substitute_for_executed_commands(self):
        for name in self.workflows:
            workflow = self.read_workflow(name)
            for job_id, job in workflow["jobs"].items():
                for index, step in enumerate(job["steps"]):
                    if "run" not in step:
                        continue
                    with self.subTest(workflow=name, job=job_id, step=index):
                        mutated = copy.deepcopy(workflow)
                        mutated["jobs"][job_id]["steps"][index]["run"] = "\n".join(
                            "# " + line for line in step["run"].splitlines()
                        )
                        with self.assertRaises(self.validator.ContractError):
                            self.validate(name, mutated)

    def test_removing_or_commenting_each_executable_line_fails(self):
        for name in self.workflows:
            workflow = self.read_workflow(name)
            for job_id, job in workflow["jobs"].items():
                for step_index, step in enumerate(job["steps"]):
                    if "run" not in step:
                        continue
                    lines = step["run"].splitlines()
                    for line_index, line in enumerate(lines):
                        if not line.strip() or line.lstrip().startswith("#"):
                            continue
                        for operation in ("remove", "comment"):
                            with self.subTest(
                                workflow=name,
                                job=job_id,
                                step=step_index,
                                line=line_index,
                                operation=operation,
                            ):
                                mutated = copy.deepcopy(workflow)
                                changed = list(lines)
                                if operation == "remove":
                                    del changed[line_index]
                                else:
                                    changed[line_index] = "# " + line
                                mutated["jobs"][job_id]["steps"][step_index]["run"] = (
                                    "\n".join(changed)
                                )
                                with self.assertRaises(self.validator.ContractError):
                                    self.validate(name, mutated)

    def test_continuations_do_not_change_quoted_data_or_command_tokens(self):
        cases = (
            ("release-package", "publish", "'%s  %s", "'%s\\\n %s"),
            ("release-package", "build", "'%s  %s", "'%s\\\n %s"),
            (
                "guarded-pull-request-merge",
                "guarded-merge",
                "python tools/",
                "python\\\ntools/",
            ),
            ("agent-rules-update", "prepare", "LANG=C.UTF-8", "LANG=C.\\\n UTF-8"),
        )
        for name, job_id, old, new in cases:
            with self.subTest(workflow=name, old=old):
                workflow = self.read_workflow(name)
                step = next(
                    step
                    for step in workflow["jobs"][job_id]["steps"]
                    if old in step.get("run", "")
                )
                step["run"] = step["run"].replace(old, new, 1)
                with self.assertRaises(self.validator.ContractError):
                    self.validate(name, workflow)

    def test_unquoted_on_is_an_event_key(self):
        name = "repository-audit"
        content = (
            (ROOT / f".github/workflows/{name}.yml").read_text().replace('"on":', "on:")
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "workflow.yml"
            path.write_text(content, encoding="utf-8")
            self.validate(name, self.validator.load_workflow(path))

    def test_added_job_and_step_privileges_and_skipping_fail(self):
        for name in self.workflows:
            for scope in ("workflow", "job", "step"):
                for field, value in (
                    ("permissions", {"contents": "write"}),
                    ("env", {"GH_TOKEN": "${{ github.token }}"}),
                    ("if", "false"),
                    ("continue-on-error", True),
                ):
                    with self.subTest(workflow=name, scope=scope, field=field):
                        workflow = self.read_workflow(name)
                        target = workflow
                        if scope != "workflow":
                            target = next(iter(workflow["jobs"].values()))
                        if scope == "step":
                            target = target["steps"][0]
                        target[field] = value
                        with self.assertRaises(self.validator.ContractError):
                            self.validate(name, workflow)

    def test_step_labels_cannot_smuggle_credential_expressions(self):
        for name in self.workflows:
            for label in (
                "${{ github.token }}",
                "${{ github['token'] }}",
                "${{ toJSON(github) }}",
                "${{ secrets.PRIVATE_KEY }}",
            ):
                with self.subTest(workflow=name, label=label):
                    workflow = self.read_workflow(name)
                    next(iter(workflow["jobs"].values()))["steps"][0]["name"] = label
                    with self.assertRaises(self.validator.ContractError):
                        self.validate(name, workflow)

    def test_step_removal_duplication_and_reordering_fail(self):
        for name in self.workflows:
            workflow = self.read_workflow(name)
            for job_id, job in workflow["jobs"].items():
                for index in range(len(job["steps"])):
                    for operation in ("remove", "duplicate", "swap"):
                        if operation == "swap" and index == 0:
                            continue
                        with self.subTest(
                            workflow=name, job=job_id, step=index, operation=operation
                        ):
                            mutated = copy.deepcopy(workflow)
                            steps = mutated["jobs"][job_id]["steps"]
                            if operation == "remove":
                                del steps[index]
                            elif operation == "duplicate":
                                steps.insert(index, copy.deepcopy(steps[index]))
                            else:
                                steps[index - 1], steps[index] = (
                                    steps[index],
                                    steps[index - 1],
                                )
                            with self.assertRaises(self.validator.ContractError):
                                self.validate(name, mutated)

    def test_duplicate_keys_and_unsafe_yaml_tags_fail(self):
        for content in (
            "jobs: {}\njobs: {}\n",
            "jobs:\n  build:\n    if: true\n    if: false\n",
            "!!python/object/apply:os.system [echo unsafe]",
            "[]",
            "jobs: [",
        ):
            with (
                self.subTest(content=content),
                tempfile.TemporaryDirectory() as temporary,
            ):
                path = Path(temporary) / "workflow.yml"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(self.validator.ContractError):
                    self.validator.load_workflow(path)

    def test_invalid_registry_unknown_workflow_and_job_types_fail(self):
        name = "repository-audit"
        workflow = self.read_workflow(name)
        for registry in ({}, {"policy": {"nodeCiVersion": "latest"}}):
            with self.subTest(registry=registry):
                with self.assertRaises(self.validator.ContractError):
                    self.validator.validate_workflow(name, workflow, registry)
        with self.assertRaises(self.validator.ContractError):
            self.validate("unknown", workflow)
        workflow["jobs"]["quality-linux"] = []
        with self.assertRaises(self.validator.ContractError):
            self.validate(name, workflow)

    def test_cli_reports_missing_file_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(VALIDATOR),
                    "--workflow",
                    "release-package",
                    "--path",
                    str(Path(temporary) / "missing.yml"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing.yml", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_embedded_python_and_broadened_dependencies_fail(self):
        workflow = self.read_workflow("release-package")
        verify = workflow["jobs"]["publish"]["steps"][1]
        verify["run"] = verify["run"].replace(
            "if len(entries)", "invalid syntax len(entries)"
        )
        with self.assertRaises(self.validator.ContractError):
            self.validate("release-package", workflow)
        workflow = self.read_workflow("release-package")
        workflow["jobs"]["publish"]["needs"] = [{"build": "success"}]
        with self.assertRaises(self.validator.ContractError):
            self.validate("release-package", workflow)

    def test_artifact_path_line_boundaries_are_semantic(self):
        for name, job_id in (
            ("release-package", "build"),
            ("agent-rules-update", "prepare"),
        ):
            with self.subTest(workflow=name):
                workflow = self.read_workflow(name)
                upload = workflow["jobs"][job_id]["steps"][-1]
                upload["with"]["path"] = upload["with"]["path"].replace("\n", " ")
                with self.assertRaises(self.validator.ContractError):
                    self.validate(name, workflow)

    def test_meaningful_run_mutations_fail(self):
        cases = (
            ("release-package", "publish", "len(entries) != 3", "len(entries) != 2"),
            (
                "release-package",
                "publish",
                "not stat.S_ISREG(mode)",
                "stat.S_ISREG(mode)",
            ),
            ("release-package", "publish", "if ! cmp", "if cmp"),
            (
                "release-package",
                "publish",
                "gh release upload",
                "gh release upload --clobber",
            ),
            ("release-package", "publish", '&& "$PRERELEASE"', '|| "$PRERELEASE"'),
            ("release-package", "release-checks", "--event release", "--event push"),
            (
                "release-package",
                "release-checks",
                "agent-rules-update.yml",
                "release-package.yml",
            ),
            ("release-package", "release-checks", '--sha "$RELEASE_SHA"', "--sha HEAD"),
            ("release-package", "release-checks", "SECONDS + 1800", "SECONDS + 3600"),
            ("release-package", "release-checks", "timeout 30s gh", "gh"),
            ("agent-rules-update", "prepare", "env -i", "env"),
            (
                "guarded-pull-request-merge",
                "guarded-merge",
                "--dry-run execute",
                "execute",
            ),
            ("repository-audit", "repository-audit", "&& test", "|| test"),
        )
        for name, job_id, old, new in cases:
            with self.subTest(workflow=name, old=old):
                workflow = self.read_workflow(name)
                step = next(
                    step
                    for step in workflow["jobs"][job_id]["steps"]
                    if old in step.get("run", "")
                )
                step["run"] = step["run"].replace(old, new)
                with self.assertRaises(self.validator.ContractError):
                    self.validate(name, workflow)


@unittest.skipUnless(
    (ROOT / "tools/starter-kit-manifest.py").is_file(),
    "consumer package does not ship the source manifest generator",
)
class ConsumerWorkflowContractTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "starter_kit_manifest", ROOT / "tools/starter-kit-manifest.py"
        )
        manifest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manifest)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.consumer = Path(temporary.name)
        # Copy the actual shipped inputs, using the package's exclusion policy.
        paths = (
            *(f".github/workflows/{name}.yml" for name in WORKFLOWS),
            "tools/repository-audit/workflow-contracts.py",
            "tools/quality/versions.json",
            "tests/test_workflow_contracts.py",
            "tools/build-release-package.ps1",
            "tools/starter-kit-manifest.py",
        )
        for relative in paths:
            if manifest.is_core_path(relative):
                destination = self.consumer / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)

    def run_validator(self, *arguments):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "tools/repository-audit/workflow-contracts.py",
                *arguments,
            ],
            cwd=self.consumer,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_default_validator_accepts_consumer_without_package_provenance(self):
        result = self.run_validator("--repository-root", ".")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_consumer_validator_runs_without_source_tests_and_blocks_invalid_jobs(self):
        self.assertFalse((self.consumer / "tests").exists())
        result = self.run_validator("--repository-root", ".")
        self.assertEqual(result.returncode, 0, result.stderr)
        workflow_path = self.consumer / ".github/workflows/repository-audit.yml"
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        del workflow["jobs"]["project-linux"]
        workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
        result = self.run_validator("--repository-root", ".")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("project-linux", result.stderr)

    def test_each_core_workflow_remains_mandatory_in_consumer(self):
        for name in (
            "agent-rules-update",
            "repository-audit",
            "guarded-pull-request-merge",
            "release-artifacts",
        ):
            with self.subTest(workflow=name):
                path = self.consumer / f".github/workflows/{name}.yml"
                content = path.read_bytes()
                path.unlink()
                result = self.run_validator()
                path.write_bytes(content)
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"{name}.yml", result.stderr)

    def test_source_tools_require_deleted_release_workflow(self):
        for relative in (
            "tools/build-release-package.ps1",
            "tools/starter-kit-manifest.py",
        ):
            with self.subTest(source_tool=relative):
                marker = self.consumer / relative
                shutil.copyfile(ROOT / relative, marker)
                result = self.run_validator()
                marker.unlink()
                self.assertEqual(result.returncode, 1)
                self.assertIn("release-package.yml", result.stderr)

    def test_explicit_release_selection_remains_strict_in_consumer(self):
        result = self.run_validator("--workflow", "release-package")
        self.assertEqual(result.returncode, 1)
        self.assertIn("release-package.yml", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_present_release_workflow_is_validated_without_source_tools(self):
        release = self.consumer / ".github/workflows/release-package.yml"
        shutil.copyfile(ROOT / ".github/workflows/release-package.yml", release)
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        release.write_text("jobs: {}\n", encoding="utf-8")
        result = self.run_validator()
        self.assertEqual(result.returncode, 1)
        self.assertIn("release-package", result.stderr)


if __name__ == "__main__":
    unittest.main()
