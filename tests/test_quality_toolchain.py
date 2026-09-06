from __future__ import annotations

import copy
import hashlib
import http.client
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock


SOURCE_ROOT = Path(__file__).resolve().parents[1]
QUALITY_ROOT = SOURCE_ROOT / "tools" / "quality"
INSTALLER_PATH = QUALITY_ROOT / "install-external-tools.py"
EXPECTED_PYTHON_REQUIREMENTS = {
    "codespell": "2.4.2",
    "coverage": "7.16.0",
    "jsonschema[format]": "4.26.0",
    "mypy": "2.3.1",
    "ruff": "0.16.5",
    "yamllint": "1.38.0",
}
EXPECTED_NODE_REQUIREMENTS = {
    "@commitlint/cli": "21.2.2",
    "markdownlint-cli2": "0.23.2",
}
EXPECTED_NODE_MINIMUM = "22.12.0"
EXPECTED_NODE_CI_VERSION = "24.20.0"
EXPECTED_EXTERNAL_TOOLS = {
    "actionlint": {
        "version": "1.7.12",
        "platforms": ["linux-x64"],
        "url": (
            "https://github.com/rhysd/actionlint/releases/download/v1.7.12/"
            "actionlint_1.7.12_linux_amd64.tar.gz"
        ),
        "sha256": "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
        "artifactType": "tar.gz",
        "install": {
            "kind": "executable",
            "target": "bin/actionlint",
            "memberBasename": "actionlint",
        },
        "probe": {"arguments": ["-version"], "expectedLine": "1.7.12"},
    },
    "shfmt": {
        "version": "3.14.0",
        "platforms": ["linux-x64"],
        "url": (
            "https://github.com/mvdan/sh/releases/download/v3.14.0/"
            "shfmt_v3.14.0_linux_amd64"
        ),
        "sha256": "fe42021c7272ef2d67ea36cbc3031683c625d0badec733ef3a57b567246a0b66",
        "artifactType": "binary",
        "install": {"kind": "executable", "target": "bin/shfmt"},
        "probe": {"arguments": ["--version"], "expectedLine": "v3.14.0"},
    },
    "PSScriptAnalyzer": {
        "version": "1.25.0",
        "platforms": ["linux-x64", "windows-x64"],
        "url": (
            "https://www.powershellgallery.com/api/v2/package/PSScriptAnalyzer/1.25.0"
        ),
        "sha256": "14e634c828eb98efb9f40b2918ba90f139ed5eccdf663a2a747736d996995d60",
        "artifactType": "zip",
        "install": {
            "kind": "powershell-module",
            "target": "Modules/PSScriptAnalyzer/1.25.0",
            "requiredEntries": [
                "PSScriptAnalyzer.psd1",
                "PSScriptAnalyzer.psm1",
            ],
        },
        "probe": {"expectedLine": "1.25.0"},
    },
    "shellcheck": {
        "version": "0.11.0",
        "platforms": ["linux-x64"],
        "url": (
            "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/"
            "shellcheck-v0.11.0.linux.x86_64.tar.xz"
        ),
        "sha256": "8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198",
        "artifactType": "tar.xz",
        "install": {
            "kind": "executable",
            "target": "bin/shellcheck",
            "member": "shellcheck-v0.11.0/shellcheck",
        },
        "probe": {
            "arguments": ["--version"],
            "expectedLine": "version: 0.11.0",
        },
    },
}


class FakeResponse(io.BytesIO):
    def __init__(self, content: bytes, final_url: str) -> None:
        super().__init__(content)
        self._final_url = final_url

    def geturl(self) -> str:
        return self._final_url

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *unused_arguments: object) -> None:
        self.close()


def load_script_module(path: Path, name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_quality_configuration(destination: Path) -> None:
    """Copy tracked quality inputs without local runtime installations."""
    shutil.copytree(
        QUALITY_ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".mypy_cache", ".ruff_cache", "__pycache__", "node_modules"
        ),
    )


def make_tar(
    artifact_type: str,
    entries: list[tuple[str, bytes, bytes | None]],
) -> bytes:
    stream = io.BytesIO()
    mode = "w:gz" if artifact_type == "tar.gz" else "w:xz"
    with tarfile.open(fileobj=stream, mode=mode) as archive:
        for name, content, member_type in entries:
            member = tarfile.TarInfo(name)
            member.type = member_type or tarfile.REGTYPE
            if member.isfile():
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            else:
                archive.addfile(member)
    return stream.getvalue()


def make_zip_members(
    entries: list[tuple[str | zipfile.ZipInfo, bytes]],
) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for member, content in entries:
            archive.writestr(member, content)
    return stream.getvalue()


def make_zip(entries: dict[str, bytes]) -> bytes:
    return make_zip_members(list(entries.items()))


def mark_first_zip_member_encrypted(content: bytes) -> bytes:
    mutated = bytearray(content)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        header = mutated.find(signature)
        if header < 0:
            raise AssertionError(f"ZIP header not found: {signature!r}")
        offset = header + flag_offset
        flags = int.from_bytes(mutated[offset : offset + 2], "little") | 1
        mutated[offset : offset + 2] = flags.to_bytes(2, "little")
    return bytes(mutated)


def requirement_blocks(content: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            if current:
                blocks.append("\n".join(current))
            current = [stripped]
        else:
            current.append(stripped)
    if current:
        blocks.append("\n".join(current))
    return blocks


class QualityToolchainTests(unittest.TestCase):
    def run_checker(self, quality_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(QUALITY_ROOT / "check-versions.py"),
                "--quality-root",
                str(quality_root),
            ],
            cwd=SOURCE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def check_mutated_quality(
        self, mutation: callable, expected_diagnostic: str
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            quality_copy = Path(temporary_directory) / "quality"
            copy_quality_configuration(quality_copy)
            mutation(quality_copy)
            result = self.run_checker(quality_copy)
        self.assertEqual(result.returncode, 1)
        self.assertIn(expected_diagnostic, result.stderr)

    def test_declaration_checker_accepts_exact_locked_versions(self) -> None:
        result = subprocess.run(
            [sys.executable, str(QUALITY_ROOT / "check-versions.py")],
            cwd=SOURCE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("quality versions: declarations match", result.stdout)

    def test_declaration_checker_rejects_version_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            quality_copy = Path(temporary_directory) / "quality"
            copy_quality_configuration(quality_copy)
            package_path = quality_copy / "package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["devDependencies"]["markdownlint-cli2"] = "0.22.0"
            package_path.write_text(
                json.dumps(package, indent=2) + "\n", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(QUALITY_ROOT / "check-versions.py"),
                    "--quality-root",
                    str(quality_copy),
                ],
                cwd=SOURCE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("markdownlint-cli2", result.stderr)
        self.assertIn("expected 0.23.2", result.stderr)

    def test_declaration_checker_rejects_node_runtime_drift(self) -> None:
        def mutate_engine(quality_root: Path) -> None:
            package_path = quality_root / "package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["engines"]["node"] = ">=22.11.0"
            package_path.write_text(
                json.dumps(package, indent=2) + "\n", encoding="utf-8"
            )

        self.check_mutated_quality(
            mutate_engine,
            "package.json: node engine expected >=22.12.0",
        )

    def test_declaration_checker_rejects_lock_and_policy_mutations(self) -> None:
        def mutate_lock(field: str, value: object) -> callable:
            def mutation(quality_root: Path) -> None:
                lock_path = quality_root / "package-lock.json"
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                package = lock["packages"]["node_modules/ansi-regex"]
                if value is None:
                    package.pop(field, None)
                else:
                    package[field] = value
                lock_path.write_text(
                    json.dumps(lock, indent=2) + "\n", encoding="utf-8"
                )

            return mutation

        cases = (
            (mutate_lock("version", None), "ansi-regex has no version"),
            (mutate_lock("integrity", None), "ansi-regex has no integrity digest"),
            (
                mutate_lock("resolved", "http://registry.npmjs.org/ansi-regex.tgz"),
                "ansi-regex has non-registry resolved URL",
            ),
            (mutate_lock("hasInstallScript", True), "ansi-regex hasInstallScript"),
        )
        for mutation, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                self.check_mutated_quality(mutation, diagnostic)

        def mutate_policy(quality_root: Path, name: str, value: object = False) -> None:
            registry_path = quality_root / "versions.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["policy"][name] = value
            registry_path.write_text(
                json.dumps(registry, indent=2) + "\n", encoding="utf-8"
            )

        for policy_name in ("npmIgnoreScripts", "pythonRequireHashes"):
            with self.subTest(policy=policy_name):
                self.check_mutated_quality(
                    lambda root, name=policy_name: mutate_policy(root, name),
                    f"versions.json: policy {policy_name} must be true",
                )

        invalid_policy_types = (
            (
                "coverageFailUnder",
                85.0,
                "versions.json: policy: invalid coverageFailUnder",
            ),
            (
                "npmIgnoreScripts",
                1,
                "versions.json: policy: invalid npmIgnoreScripts",
            ),
            (
                "pythonRequireHashes",
                "true",
                "versions.json: policy: invalid pythonRequireHashes",
            ),
        )
        for name, value, diagnostic in invalid_policy_types:
            with self.subTest(policy_type=name):
                self.check_mutated_quality(
                    lambda root, key=name, invalid=value: mutate_policy(
                        root, key, invalid
                    ),
                    diagnostic,
                )

    def test_declaration_checker_preserves_jsonschema_format_extra(self) -> None:
        def mutation(quality_root: Path) -> None:
            requirements_path = quality_root / "requirements.in"
            requirements_path.write_text(
                requirements_path.read_text(encoding="utf-8").replace(
                    "jsonschema[format]==", "jsonschema=="
                ),
                encoding="utf-8",
            )

        self.check_mutated_quality(
            mutation, "requirements.in: expected direct requirement jsonschema[format]"
        )

    def test_runtime_probe_has_timeout_stderr_and_external_coverage(self) -> None:
        module_path = QUALITY_ROOT / "check-versions.py"
        spec = importlib.util.spec_from_file_location("quality_versions", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        completed = subprocess.CompletedProcess(
            ["tool", "--version"], 0, stdout="", stderr="tool 1.2.3\n"
        )
        with (
            mock.patch.object(module.shutil, "which", return_value="tool"),
            mock.patch.object(
                module.subprocess, "run", return_value=completed
            ) as run_mock,
        ):
            result = module.command_version(["tool", "--version"])
        self.assertEqual(result.version, "1.2.3")
        self.assertGreater(run_mock.call_args.kwargs["timeout"], 0)

        with (
            mock.patch.object(module.shutil, "which", return_value="tool"),
            mock.patch.object(
                module.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["tool"], 1),
            ),
        ):
            timeout_result = module.command_version(["tool", "--version"])
        self.assertEqual(timeout_result.diagnostic, "timed out")

        commands = module.external_commands(EXPECTED_EXTERNAL_TOOLS)
        self.assertEqual(set(commands), set(EXPECTED_EXTERNAL_TOOLS))
        self.assertEqual(commands["actionlint"], ["actionlint", "-version"])
        self.assertEqual(commands["shfmt"], ["shfmt", "--version"])
        self.assertEqual(commands["shellcheck"], ["shellcheck", "--version"])
        self.assertEqual(
            commands["PSScriptAnalyzer"][:4],
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command"],
        )
        self.assertIn("-RequiredVersion 1.25.0", commands["PSScriptAnalyzer"][-1])
        self.assertIn("ModuleBase", commands["PSScriptAnalyzer"][-1])
        self.assertIn("Invoke-ScriptAnalyzer", commands["PSScriptAnalyzer"][-1])

        with tempfile.TemporaryDirectory() as temporary_directory:
            quality_copy = Path(temporary_directory) / "quality"
            copy_quality_configuration(quality_copy)
            for name, version in EXPECTED_NODE_REQUIREMENTS.items():
                package_path = quality_copy / "node_modules" / name / "package.json"
                package_path.parent.mkdir(parents=True)
                package_path.write_text(
                    json.dumps({"version": version}) + "\n", encoding="utf-8"
                )

            python_versions = {
                module.normalize_name(name): version
                for name, version in EXPECTED_PYTHON_REQUIREMENTS.items()
            }
            line_versions = {
                record["probe"]["expectedLine"]: record["version"]
                for record in EXPECTED_EXTERNAL_TOOLS.values()
            }

            def probe_version(
                command: list[str], expected_line: str | None = None
            ) -> object:
                if command == ["node", "--version"]:
                    return module.VersionProbe("24.20.0", "matched")
                assert expected_line is not None
                return module.VersionProbe(line_versions[expected_line], "matched")

            with (
                mock.patch.object(
                    module.importlib.metadata,
                    "version",
                    side_effect=lambda name: python_versions[name],
                ),
                mock.patch.object(
                    module, "command_version", side_effect=probe_version
                ) as version_mock,
            ):
                runtime_errors = module.check_runtime(quality_copy)

            def old_node_version(
                command: list[str], expected_line: str | None = None
            ) -> object:
                if command == ["node", "--version"]:
                    return module.VersionProbe("22.11.0", "matched")
                assert expected_line is not None
                return module.VersionProbe(line_versions[expected_line], "matched")

            with (
                mock.patch.object(
                    module.importlib.metadata,
                    "version",
                    side_effect=lambda name: python_versions[name],
                ),
                mock.patch.object(
                    module, "command_version", side_effect=old_node_version
                ),
            ):
                old_node_errors = module.check_runtime(quality_copy)
        self.assertEqual(runtime_errors, [])
        self.assertEqual(
            old_node_errors,
            ["runtime: node expected >=22.12.0, found 22.11.0 (matched)"],
        )
        self.assertEqual(version_mock.call_count, 5)
        self.assertEqual(
            [call.args for call in version_mock.call_args_list],
            [
                (["node", "--version"],),
                *[
                    (
                        commands[name],
                        EXPECTED_EXTERNAL_TOOLS[name]["probe"]["expectedLine"],
                    )
                    for name in EXPECTED_EXTERNAL_TOOLS
                ],
            ],
        )

    def test_runtime_probe_allows_a_cold_start_within_its_budget(self) -> None:
        module_path = QUALITY_ROOT / "check-versions.py"
        spec = importlib.util.spec_from_file_location(
            "quality_versions_cold", module_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def complete_after_cold_start(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            timeout = kwargs["timeout"]
            self.assertIsInstance(timeout, int)
            if timeout < 10:
                raise subprocess.TimeoutExpired(command, timeout)
            return subprocess.CompletedProcess(
                command, 0, stdout="tool 1.2.3\n", stderr=""
            )

        with (
            mock.patch.object(module.shutil, "which", return_value="tool"),
            mock.patch.object(
                module.subprocess, "run", side_effect=complete_after_cold_start
            ),
        ):
            result = module.command_version(["tool", "--version"])

        self.assertEqual(result, module.VersionProbe("1.2.3", "matched"))

    def test_declaration_checker_rejects_external_registry_mutations(self) -> None:
        def mutate_registry(quality_root: Path, mutation: callable) -> None:
            registry_path = quality_root / "versions.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            mutation(registry)
            registry_path.write_text(
                json.dumps(registry, indent=2) + "\n", encoding="utf-8"
            )

        cases = (
            (
                lambda value: value.__setitem__("schemaVersion", 1),
                "schemaVersion must be 2",
            ),
            (
                lambda value: value["external"].pop("shellcheck"),
                "external tools must be exactly",
            ),
            (
                lambda value: value["external"]["actionlint"].__setitem__(
                    "url", "http://example.test/actionlint"
                ),
                "actionlint: unsafe URL",
            ),
            (
                lambda value: value["external"]["shfmt"].__setitem__(
                    "probe", {"arguments": [], "expectedLine": "v3.14.0"}
                ),
                "shfmt: invalid probe arguments",
            ),
        )
        for mutation, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                self.check_mutated_quality(
                    lambda root, change=mutation: mutate_registry(root, change),
                    diagnostic,
                )

    def test_declaration_checker_reports_every_manifest_drift(self) -> None:
        checker = load_script_module(
            QUALITY_ROOT / "check-versions.py",
            "quality_versions_manifest_drift",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            quality_copy = Path(temporary_directory) / "quality"
            copy_quality_configuration(quality_copy)

            requirements_path = quality_copy / "requirements.in"
            requirements = requirements_path.read_text(encoding="utf-8")
            requirements_path.write_text(
                requirements.replace("ruff==0.16.5\n", "") + "unexpected==9.9.9\n",
                encoding="utf-8",
            )

            lock_path = quality_copy / "package-lock.json"
            package_lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_root = package_lock["packages"][""]
            lock_root["engines"] = {"node": ">=0.0.0"}
            lock_root["devDependencies"]["markdownlint-cli2"] = "0.0.0"
            package_lock["packages"]["node_modules/markdownlint-cli2"]["version"] = (
                "0.0.0"
            )
            lock_path.write_text(
                json.dumps(package_lock, indent=2) + "\n",
                encoding="utf-8",
            )

            pyproject_path = quality_copy / "pyproject.toml"
            pyproject_path.write_text(
                pyproject_path.read_text(encoding="utf-8").replace(
                    "fail_under = 85",
                    "fail_under = 84",
                ),
                encoding="utf-8",
            )

            errors = checker.check_declarations(quality_copy)

        self.assertEqual(
            errors,
            [
                "requirements.in: expected direct requirement ruff==0.16.5",
                "requirements.in: unexpected direct requirement unexpected",
                "requirements.in: ruff expected 0.16.5, found None",
                "requirements.in: unexpected expected None, found 9.9.9",
                "package-lock.json: node engine expected >=22.12.0",
                "package-lock.json: root dependencies differ from versions.json",
                ("package-lock.json: markdownlint-cli2 expected 0.23.2, found 0.0.0"),
                "pyproject.toml: coverage threshold expected 85, found 84",
            ],
        )

    def test_declaration_checker_rejects_an_unhashed_lock_block(self) -> None:
        checker = load_script_module(
            QUALITY_ROOT / "check-versions.py",
            "quality_versions_unhashed_lock",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            quality_copy = Path(temporary_directory) / "quality"
            copy_quality_configuration(quality_copy)
            (quality_copy / "requirements.lock").write_text(
                "codespell==2.4.2\n"
                "coverage==7.16.0 --hash=sha256:0\n"
                "jsonschema==4.26.0 --hash=sha256:0\n"
                "mypy==2.3.1 --hash=sha256:0\n"
                "ruff==0.16.5 --hash=sha256:0\n"
                "yamllint==1.38.0 --hash=sha256:0\n",
                encoding="utf-8",
            )

            errors = checker.check_declarations(quality_copy)

        self.assertEqual(
            errors,
            ["requirements.lock: unhashed block: codespell==2.4.2"],
        )

    def test_command_version_distinguishes_probe_failure_modes(self) -> None:
        checker = load_script_module(
            QUALITY_ROOT / "check-versions.py",
            "quality_versions_probe_failures",
        )
        with mock.patch.object(checker.shutil, "which", return_value=None):
            missing = checker.command_version(["missing-tool", "--version"])
        self.assertEqual(
            missing,
            checker.VersionProbe(None, "command not found"),
        )

        cases = (
            (
                subprocess.CompletedProcess(
                    ["tool", "--version"],
                    2,
                    stdout="partial",
                    stderr="failure",
                ),
                None,
                "exited 2: partial\nfailure",
            ),
            (
                subprocess.CompletedProcess(
                    ["tool", "--version"],
                    0,
                    stdout="tool 1.2.3",
                    stderr="",
                ),
                "required 1.2.3",
                "unexpected output: tool 1.2.3",
            ),
            (
                subprocess.CompletedProcess(
                    ["tool", "--version"],
                    0,
                    stdout="tool version unknown",
                    stderr="",
                ),
                None,
                "unparsable output: tool version unknown",
            ),
        )
        for completed, expected_line, diagnostic in cases:
            with (
                self.subTest(diagnostic=diagnostic),
                mock.patch.object(checker.shutil, "which", return_value="tool"),
                mock.patch.object(
                    checker.subprocess,
                    "run",
                    return_value=completed,
                ),
            ):
                result = checker.command_version(
                    ["tool", "--version"],
                    expected_line,
                )
            self.assertEqual(result, checker.VersionProbe(None, diagnostic))

    def test_runtime_checker_reports_each_missing_or_mismatched_family(self) -> None:
        checker = load_script_module(
            QUALITY_ROOT / "check-versions.py",
            "quality_versions_runtime_failures",
        )
        python_versions = {
            checker.normalize_name(name): version
            for name, version in EXPECTED_PYTHON_REQUIREMENTS.items()
        }
        external_versions = {
            record["probe"]["expectedLine"]: record["version"]
            for record in EXPECTED_EXTERNAL_TOOLS.values()
        }

        def installed_python_version(name: str) -> str:
            if name == "codespell":
                raise checker.importlib.metadata.PackageNotFoundError(name)
            return python_versions[name]

        def probe_version(
            command: list[str], expected_line: str | None = None
        ) -> object:
            if command == ["node", "--version"]:
                return checker.VersionProbe(None, "command not found")
            assert expected_line is not None
            version = external_versions[expected_line]
            if expected_line == "1.7.12":
                version = "0.0.0"
            return checker.VersionProbe(version, "matched")

        with tempfile.TemporaryDirectory() as temporary_directory:
            quality_copy = Path(temporary_directory) / "quality"
            copy_quality_configuration(quality_copy)
            markdownlint_package = (
                quality_copy / "node_modules" / "markdownlint-cli2" / "package.json"
            )
            markdownlint_package.parent.mkdir(parents=True)
            markdownlint_package.write_text(
                '{"version": "0.0.0"}\n',
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    checker.importlib.metadata,
                    "version",
                    side_effect=installed_python_version,
                ),
                mock.patch.object(
                    checker,
                    "command_version",
                    side_effect=probe_version,
                ),
            ):
                errors = checker.check_runtime(quality_copy)

        self.assertEqual(
            errors,
            [
                ("runtime: node expected >=22.12.0, found None (command not found)"),
                "runtime: codespell expected 2.4.2, found None",
                "runtime: @commitlint/cli expected 21.2.2, found None",
                "runtime: markdownlint-cli2 expected 0.23.2, found 0.0.0",
                "runtime: actionlint expected 1.7.12, found 0.0.0 (matched)",
            ],
        )

    def test_semver_parser_rejects_ambiguous_runtime_versions(self) -> None:
        checker = load_script_module(
            QUALITY_ROOT / "check-versions.py",
            "quality_versions_semver",
        )
        self.assertEqual(checker.semver_tuple("0.12.3"), (0, 12, 3))
        for value in ("1.2", "01.2.3", "1.2.3rc1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    f"invalid semantic version: {re.escape(value)}",
                ):
                    checker.semver_tuple(value)

    def test_main_reports_runtime_success_after_all_checks_pass(self) -> None:
        checker = load_script_module(
            QUALITY_ROOT / "check-versions.py",
            "quality_versions_main_success",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(checker, "check_declarations", return_value=[]),
            mock.patch.object(checker, "check_runtime", return_value=[]),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(sys, "stderr", stderr),
        ):
            result = checker.main(["--quality-root", str(QUALITY_ROOT), "--runtime"])

        self.assertEqual(result, 0)
        self.assertEqual(
            stdout.getvalue(),
            "quality versions: declarations match\nquality versions: runtimes match\n",
        )
        self.assertEqual(stderr.getvalue(), "")

    def test_main_prints_all_diagnostics_and_returns_failure(self) -> None:
        checker = load_script_module(
            QUALITY_ROOT / "check-versions.py",
            "quality_versions_main_failure",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                checker,
                "check_declarations",
                return_value=["declaration drift"],
            ),
            mock.patch.object(
                checker,
                "check_runtime",
                return_value=["runtime drift"],
            ),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(sys, "stderr", stderr),
        ):
            result = checker.main(["--quality-root", str(QUALITY_ROOT), "--runtime"])

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "declaration drift\nruntime drift\n")

    def test_main_turns_invalid_json_shape_into_a_diagnostic(self) -> None:
        checker = load_script_module(
            QUALITY_ROOT / "check-versions.py",
            "quality_versions_main_invalid_json",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary_directory:
            quality_root = Path(temporary_directory) / "quality"
            quality_root.mkdir()
            registry_path = quality_root / "versions.json"
            registry_path.write_text("[]\n", encoding="utf-8")
            resolved_registry_path = registry_path.resolve(strict=True)

            with (
                mock.patch.object(sys, "stdout", stdout),
                mock.patch.object(sys, "stderr", stderr),
            ):
                result = checker.main(["--quality-root", str(quality_root)])

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            f"quality versions: expected a JSON object: {resolved_registry_path}\n",
        )

    def test_direct_python_requirements_are_exact_and_lock_is_hashed(self) -> None:
        direct_lines = {
            line.strip()
            for line in (QUALITY_ROOT / "requirements.in")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertEqual(
            direct_lines,
            {
                f"{name}=={version}"
                for name, version in EXPECTED_PYTHON_REQUIREMENTS.items()
            },
        )

        lock_content = (QUALITY_ROOT / "requirements.lock").read_text(encoding="utf-8")
        blocks = requirement_blocks(lock_content)
        self.assertGreater(len(blocks), len(EXPECTED_PYTHON_REQUIREMENTS))
        for block in blocks:
            self.assertRegex(block, r"^[A-Za-z0-9_.\[\]-]+==[^\s\\]+")
            self.assertIn("--hash=sha256:", block)
        for name, version in EXPECTED_PYTHON_REQUIREMENTS.items():
            normalized = re.escape(name.split("[", 1)[0].lower().replace("_", "-"))
            self.assertRegex(
                lock_content.lower().replace("_", "-"),
                rf"(?m)^{normalized}=={re.escape(version)}(?:\s|\\)",
            )

    def test_node_lock_declares_only_exact_quality_dependencies(self) -> None:
        package = json.loads(
            (QUALITY_ROOT / "package.json").read_text(encoding="utf-8")
        )
        self.assertTrue(package["private"])
        self.assertEqual(package["devDependencies"], EXPECTED_NODE_REQUIREMENTS)
        self.assertEqual(package["engines"], {"node": f">={EXPECTED_NODE_MINIMUM}"})
        self.assertNotIn("scripts", package)

        lock = json.loads(
            (QUALITY_ROOT / "package-lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            lock["packages"][""]["devDependencies"], EXPECTED_NODE_REQUIREMENTS
        )
        self.assertEqual(
            lock["packages"][""]["engines"],
            {"node": f">={EXPECTED_NODE_MINIMUM}"},
        )
        for name, version in EXPECTED_NODE_REQUIREMENTS.items():
            self.assertEqual(
                lock["packages"][f"node_modules/{name}"]["version"], version
            )
            self.assertIn("integrity", lock["packages"][f"node_modules/{name}"])

    def test_registry_includes_external_tools_and_exact_coverage_policy(self) -> None:
        registry = json.loads(
            (QUALITY_ROOT / "versions.json").read_text(encoding="utf-8")
        )
        self.assertEqual(registry["schemaVersion"], 2)
        self.assertEqual(registry["external"], EXPECTED_EXTERNAL_TOOLS)
        self.assertEqual(registry["policy"]["nodeMinimum"], EXPECTED_NODE_MINIMUM)
        self.assertEqual(registry["policy"]["nodeCiVersion"], EXPECTED_NODE_CI_VERSION)

        pyproject = tomllib.loads(
            (QUALITY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertTrue(pyproject["tool"]["coverage"]["run"]["branch"])
        self.assertEqual(pyproject["tool"]["coverage"]["report"]["fail_under"], 85)
        self.assertGreaterEqual(pyproject["tool"]["coverage"]["report"]["precision"], 2)
        self.assertNotIn("omit", pyproject["tool"]["coverage"]["run"])
        self.assertEqual(pyproject["tool"]["coverage"]["run"]["source"], ["tools"])
        self.assertIn("files", pyproject["tool"]["mypy"])
        self.assertNotIn("exclude", pyproject["tool"]["mypy"])
        self.assertNotIn("ignore_missing_imports", pyproject["tool"]["mypy"])

    def test_coverage_threshold_fails_below_85_and_accepts_85_or_more(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            sample_path = temporary_root / "sample.py"
            data_path = temporary_root / ".coverage"
            sample_path.write_text(
                """def covered(value: bool) -> int:
    if value:
        return 1
    return 0


def missed(value: bool) -> int:
    if value:
        return 2
    return 3


covered(True)
""",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["COVERAGE_FILE"] = str(data_path)
            subprocess.run(
                [sys.executable, "-m", "coverage", "run", "--branch", str(sample_path)],
                cwd=temporary_root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            below = subprocess.run(
                [sys.executable, "-m", "coverage", "report", "--fail-under=85"],
                cwd=temporary_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(below.returncode, 0, below.stdout)

            sample_path.write_text(
                sample_path.read_text(encoding="utf-8").replace(
                    "covered(True)\n",
                    "covered(True)\ncovered(False)\nmissed(True)\nmissed(False)\n",
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, "-m", "coverage", "erase"],
                cwd=temporary_root,
                env=environment,
                check=True,
            )
            subprocess.run(
                [sys.executable, "-m", "coverage", "run", "--branch", str(sample_path)],
                cwd=temporary_root,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            above = subprocess.run(
                [sys.executable, "-m", "coverage", "report", "--fail-under=85"],
                cwd=temporary_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(above.returncode, 0, above.stdout + above.stderr)

    def test_yamllint_ignores_only_generated_dependency_trees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_yaml = temporary_root / "repository.yml"
            generated_yaml = (
                temporary_root / ".tmp" / "generated.yml",
                temporary_root
                / "tools"
                / "quality"
                / "node_modules"
                / "dependency.yml",
            )
            repository_yaml.write_text("---\nvalid: true\n", encoding="utf-8")
            for generated_path in generated_yaml:
                generated_path.parent.mkdir(parents=True, exist_ok=True)
                generated_path.write_text("---\ngenerated: true\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "yamllint",
                    "-c",
                    str(QUALITY_ROOT / "yamllint.yaml"),
                    "--list-files",
                    ".",
                ],
                cwd=temporary_root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            listed_paths = {
                (temporary_root / line).resolve()
                for line in result.stdout.splitlines()
                if line
            }
            self.assertEqual(listed_paths, {repository_yaml.resolve()})

    def test_markdownlint_honors_repository_gitignore_files(self) -> None:
        node_command = shutil.which("node")
        if node_command is None:
            self.fail("node is required for the locked Markdownlint test")
        markdownlint_entry = (
            QUALITY_ROOT
            / "node_modules"
            / "markdownlint-cli2"
            / "markdownlint-cli2-bin.mjs"
        )
        if markdownlint_entry.is_file():
            markdownlint_command = [node_command, str(markdownlint_entry)]
        else:
            markdownlint_executable = shutil.which("markdownlint-cli2")
            if markdownlint_executable is None:
                self.fail("the locked Markdownlint command is required")
            markdownlint_command = [markdownlint_executable]
        version_result = subprocess.run(
            [*markdownlint_command, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            version_result.returncode,
            0,
            version_result.stdout + version_result.stderr,
        )
        version_lines = version_result.stdout.splitlines()
        self.assertTrue(version_lines)
        version_fields = version_lines[0].split()
        self.assertGreaterEqual(len(version_fields), 2)
        self.assertEqual(version_fields[0], "markdownlint-cli2")
        self.assertEqual(
            version_fields[1],
            f"v{EXPECTED_NODE_REQUIREMENTS['markdownlint-cli2']}",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            shutil.copy2(
                SOURCE_ROOT / ".markdownlint-cli2.yaml",
                temporary_root / ".markdownlint-cli2.yaml",
            )
            (temporary_root / ".gitignore").write_text(
                ".tmp/\nnode_modules/\n", encoding="utf-8"
            )
            nested_ignore = temporary_root / ".superpowers" / "sdd" / ".gitignore"
            nested_ignore.parent.mkdir(parents=True)
            nested_ignore.write_text("*\n", encoding="utf-8")
            (temporary_root / "README.md").write_text("# Valid\n", encoding="utf-8")
            generated_markdown = (
                temporary_root / ".tmp" / "generated.md",
                temporary_root / "tools" / "quality" / "node_modules" / "dependency.md",
                temporary_root / ".superpowers" / "sdd" / "plan.md",
            )
            for generated_path in generated_markdown:
                generated_path.parent.mkdir(parents=True, exist_ok=True)
                generated_path.write_text("not a heading\n", encoding="utf-8")

            result = subprocess.run(
                [
                    *markdownlint_command,
                    "--config",
                    ".markdownlint-cli2.yaml",
                    "**/*.md",
                ],
                cwd=temporary_root,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_codespell_skips_generated_trees_but_checks_repository_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            shutil.copy2(SOURCE_ROOT / ".codespellrc", temporary_root / ".codespellrc")
            repository_file = temporary_root / "README.md"
            repository_file.write_text("correct spelling\n", encoding="utf-8")
            generated_files = (
                temporary_root / ".tmp" / "generated.txt",
                temporary_root
                / "tools"
                / "quality"
                / "node_modules"
                / "dependency.txt",
                temporary_root / ".superpowers" / "sdd" / "plan.txt",
            )
            for generated_file in generated_files:
                generated_file.parent.mkdir(parents=True, exist_ok=True)
                generated_file.write_text("t" + "eh typo\n", encoding="utf-8")

            generated_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "codespell_lib",
                    "--config",
                    ".codespellrc",
                    ".",
                ],
                cwd=temporary_root,
                check=False,
                capture_output=True,
                text=True,
            )
            repository_file.write_text("t" + "eh typo\n", encoding="utf-8")
            repository_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "codespell_lib",
                    "--config",
                    ".codespellrc",
                    ".",
                ],
                cwd=temporary_root,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            generated_result.returncode,
            0,
            generated_result.stdout + generated_result.stderr,
        )
        self.assertNotEqual(repository_result.returncode, 0)
        self.assertIn("README.md", repository_result.stdout)


class ExternalInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installer = load_script_module(
            INSTALLER_PATH, "quality_external_installer"
        )
        self.registry = {
            "schemaVersion": 2,
            "python": copy.deepcopy(EXPECTED_PYTHON_REQUIREMENTS),
            "node": copy.deepcopy(EXPECTED_NODE_REQUIREMENTS),
            "external": copy.deepcopy(EXPECTED_EXTERNAL_TOOLS),
            "policy": {
                "coverageFailUnder": 85,
                "nodeCiVersion": EXPECTED_NODE_CI_VERSION,
                "nodeMinimum": EXPECTED_NODE_MINIMUM,
                "npmIgnoreScripts": True,
                "pythonRequireHashes": True,
            },
        }

    def artifact_for(self, tool_name: str) -> tuple[bytes, bytes, str]:
        if tool_name == "actionlint":
            content = b"actionlint executable\n"
            artifact = make_tar(
                "tar.gz",
                [
                    ("licenses/LICENSE", b"license\n", None),
                    ("release/actionlint", content, None),
                ],
            )
            return artifact, content, "bin/actionlint"
        if tool_name == "shfmt":
            content = b"shfmt executable\n"
            return content, content, "bin/shfmt"
        if tool_name == "PSScriptAnalyzer":
            artifact = make_zip(
                {
                    "PSScriptAnalyzer.psd1": b"@{}\n",
                    "PSScriptAnalyzer.psm1": b"# module\n",
                    "en-US/about_PSScriptAnalyzer.help.txt": b"help\n",
                }
            )
            return (
                artifact,
                b"@{}\n",
                ("Modules/PSScriptAnalyzer/1.25.0/PSScriptAnalyzer.psd1"),
            )
        if tool_name == "shellcheck":
            content = b"shellcheck executable\n"
            artifact = make_tar(
                "tar.xz",
                [("shellcheck-v0.11.0/shellcheck", content, None)],
            )
            return artifact, content, "bin/shellcheck"
        raise AssertionError(f"Unexpected tool {tool_name}")

    def opener_for(
        self,
        artifacts: dict[str, bytes],
        *,
        final_url: str | None = None,
        calls: list[tuple[str, float, str]] | None = None,
    ) -> callable:
        def open_url(request: object, *, timeout: float) -> FakeResponse:
            request_url = request.full_url
            if calls is not None:
                calls.append(
                    (
                        request_url,
                        timeout,
                        request.get_header("User-agent"),
                    )
                )
            return FakeResponse(
                artifacts[request_url], final_url if final_url else request_url
            )

        return open_url

    def successful_runner(
        self,
        calls: list[tuple[list[str], dict[str, object]]] | None = None,
    ) -> callable:
        expected_output = {
            "actionlint": "1.7.12\n",
            "shfmt": "v3.14.0\n",
            "shellcheck": "version: 0.11.0\n",
            "pwsh": "1.25.0\n",
        }

        def run_command(
            command: list[str], **options: object
        ) -> subprocess.CompletedProcess[str]:
            if calls is not None:
                calls.append((command, options))
            command_name = Path(command[0]).name.lower().removesuffix(".exe")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=expected_output[command_name],
                stderr="",
            )

        return run_command

    def install_one(
        self,
        tool_name: str,
        runner_temp: Path,
        *,
        platform_name: str = "linux-x64",
        run_command: callable | None = None,
        open_url: callable | None = None,
    ) -> Path:
        artifact, _, _ = self.artifact_for(tool_name)
        record = self.registry["external"][tool_name]
        record["sha256"] = hashlib.sha256(artifact).hexdigest()
        install_root = runner_temp / f"{tool_name}-tools"
        self.installer.install_tools(
            self.registry,
            platform_name=platform_name,
            install_root=install_root,
            runner_temp=runner_temp,
            tool_names=[tool_name],
            open_url=open_url or self.opener_for({record["url"]: artifact}),
            run_command=run_command or self.successful_runner(),
        )
        return install_root

    def test_registry_validation_rejects_malformed_external_contract(self) -> None:
        cases: list[tuple[str, callable, str]] = [
            (
                "schema",
                lambda value: value.__setitem__("schemaVersion", 1),
                "schemaVersion must be 2",
            ),
            (
                "schema type",
                lambda value: value.__setitem__("schemaVersion", 2.0),
                "schemaVersion must be 2",
            ),
            (
                "top-level key",
                lambda value: value.__setitem__("unknown", True),
                "versions.json: unexpected key",
            ),
            (
                "policy key",
                lambda value: value["policy"].__setitem__("unknown", True),
                "versions.json: policy: unexpected key",
            ),
            (
                "policy missing key",
                lambda value: value["policy"].pop("npmIgnoreScripts"),
                "versions.json: policy: missing key npmIgnoreScripts",
            ),
            (
                "invalid Node CI version",
                lambda value: value["policy"].__setitem__("nodeCiVersion", "lts/*"),
                "versions.json: policy: invalid nodeCiVersion",
            ),
            (
                "Node CI below minimum",
                lambda value: value["policy"].__setitem__("nodeCiVersion", "22.11.0"),
                "versions.json: policy: nodeCiVersion is below nodeMinimum",
            ),
            (
                "section type",
                lambda value: value.__setitem__("python", []),
                "versions.json: python must be an object",
            ),
            (
                "Python version type",
                lambda value: value["python"].__setitem__("codespell", 2.4),
                "versions.json: python: invalid version for codespell",
            ),
            (
                "Node version range",
                lambda value: value["node"].__setitem__("markdownlint-cli2", "^0.23.2"),
                "versions.json: node: invalid version for markdownlint-cli2",
            ),
            (
                "coverage type",
                lambda value: value["policy"].__setitem__("coverageFailUnder", 85.0),
                "versions.json: policy: invalid coverageFailUnder",
            ),
            (
                "npm policy type",
                lambda value: value["policy"].__setitem__("npmIgnoreScripts", 1),
                "versions.json: policy: invalid npmIgnoreScripts",
            ),
            (
                "Python hash policy type",
                lambda value: value["policy"].__setitem__(
                    "pythonRequireHashes", "true"
                ),
                "versions.json: policy: invalid pythonRequireHashes",
            ),
            (
                "tool set",
                lambda value: value["external"].pop("shellcheck"),
                "external tools must be exactly",
            ),
            (
                "external type",
                lambda value: value.__setitem__("external", []),
                "external tools must be exactly",
            ),
            (
                "extra tool",
                lambda value: value["external"].__setitem__(
                    "unexpected", copy.deepcopy(value["external"]["shfmt"])
                ),
                "external tools must be exactly",
            ),
            (
                "missing record key",
                lambda value: value["external"]["actionlint"].pop("version"),
                "actionlint: missing key version",
            ),
            (
                "record type",
                lambda value: value["external"].__setitem__("actionlint", []),
                "actionlint: expected an object",
            ),
            (
                "record key",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "unknown", True
                ),
                "actionlint: unexpected key",
            ),
            (
                "platform",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "platforms", ["macos-x64"]
                ),
                "actionlint: invalid platforms",
            ),
            (
                "platform list type",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "platforms", "linux-x64"
                ),
                "actionlint: invalid platforms",
            ),
            (
                "empty platforms",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "platforms", []
                ),
                r"^actionlint: invalid platforms$",
            ),
            (
                "duplicate platform",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "platforms", ["linux-x64", "linux-x64"]
                ),
                "actionlint: invalid platforms",
            ),
            (
                "HTTP URL",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "url", "http://example.test/actionlint"
                ),
                "actionlint: unsafe URL",
            ),
            (
                "URL credential",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "url", "https://user@example.test/actionlint"
                ),
                "actionlint: unsafe URL",
            ),
            (
                "URL fragment",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "url", "https://example.test/actionlint#fragment"
                ),
                "actionlint: unsafe URL",
            ),
            (
                "URL type",
                lambda value: value["external"]["actionlint"].__setitem__("url", 1),
                "actionlint: unsafe URL",
            ),
            (
                "digest",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "sha256", "A" * 64
                ),
                "actionlint: invalid sha256",
            ),
            (
                "artifact type",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "artifactType", "tar"
                ),
                "actionlint: invalid artifactType",
            ),
            (
                "artifact type value type",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "artifactType", []
                ),
                "actionlint: invalid artifactType",
            ),
            (
                "destination",
                lambda value: value["external"]["actionlint"]["install"].__setitem__(
                    "target", "../actionlint"
                ),
                "actionlint: invalid install target",
            ),
            (
                "install type",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "install", []
                ),
                "actionlint: install: expected an object",
            ),
            (
                "install nested key",
                lambda value: value["external"]["actionlint"]["install"].__setitem__(
                    "unknown", True
                ),
                "actionlint: install: unexpected key unknown",
            ),
            (
                "install kind type",
                lambda value: value["external"]["actionlint"]["install"].__setitem__(
                    "kind", True
                ),
                "actionlint: invalid install kind",
            ),
            (
                "required entries type",
                lambda value: value["external"]["PSScriptAnalyzer"][
                    "install"
                ].__setitem__("requiredEntries", "PSScriptAnalyzer.psd1"),
                "PSScriptAnalyzer: invalid requiredEntries",
            ),
            (
                "probe",
                lambda value: value["external"]["actionlint"].__setitem__(
                    "probe", {"arguments": "-version", "expectedLine": "1.7.12"}
                ),
                "actionlint: invalid probe arguments",
            ),
            (
                "probe nested key",
                lambda value: value["external"]["actionlint"]["probe"].__setitem__(
                    "unknown", True
                ),
                "actionlint: probe: unexpected key unknown",
            ),
            (
                "expected line type",
                lambda value: value["external"]["actionlint"]["probe"].__setitem__(
                    "expectedLine", ["1.7.12"]
                ),
                "actionlint: invalid expectedLine",
            ),
            (
                "probe argument type",
                lambda value: value["external"]["actionlint"]["probe"].__setitem__(
                    "arguments", [1]
                ),
                "actionlint: invalid probe arguments",
            ),
            (
                "duplicate target",
                lambda value: value["external"]["shfmt"]["install"].__setitem__(
                    "target", "bin/actionlint"
                ),
                "shfmt: duplicate install target",
            ),
        ]
        for label, mutate, diagnostic in cases:
            with self.subTest(label=label):
                registry = copy.deepcopy(self.registry)
                mutate(registry)
                with self.assertRaisesRegex(self.installer.InstallerError, diagnostic):
                    self.installer.validate_registry(registry)

    def test_redirect_handler_rejects_each_unsafe_redirect_target(self) -> None:
        handler = self.installer.SafeRedirectHandler()
        request = self.installer.urllib.request.Request("https://example.test/source")
        targets = (
            "http://example.test/asset",
            "https://user@example.test/asset",
            "https://example.test/asset#fragment",
        )
        for target in targets:
            with (
                self.subTest(target=target),
                self.assertRaisesRegex(
                    self.installer.urllib.error.URLError, "unsafe URL"
                ),
            ):
                handler.redirect_request(request, None, 302, "Found", {}, target)

    def test_tool_selection_rejects_duplicates_and_platform_mismatch(self) -> None:
        self.assertEqual(
            self.installer._selected_tools(
                self.registry, "linux-x64", ["shellcheck", "shfmt"]
            ),
            ["shfmt", "shellcheck"],
        )
        self.assertEqual(
            self.installer._selected_tools(self.registry, "windows-x64", None),
            ["PSScriptAnalyzer"],
        )
        cases = (
            (["shfmt", "shfmt"], "linux-x64", "duplicate --tool"),
            (["actionlint"], "windows-x64", "unavailable for windows-x64"),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            for index, (tools, platform_name, diagnostic) in enumerate(cases):
                with (
                    self.subTest(tools=tools),
                    self.assertRaisesRegex(self.installer.InstallerError, diagnostic),
                ):
                    self.installer.install_tools(
                        self.registry,
                        platform_name=platform_name,
                        install_root=runner_temp / f"tools-{index}",
                        runner_temp=runner_temp,
                        tool_names=tools,
                        open_url=mock.Mock(),
                        run_command=mock.Mock(),
                    )

    def test_download_rejects_unsafe_redirect_and_network_failure(self) -> None:
        artifact, _, _ = self.artifact_for("shfmt")
        record = self.registry["external"]["shfmt"]
        record["sha256"] = hashlib.sha256(artifact).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            with self.assertRaisesRegex(
                self.installer.InstallerError, "download failed: unsafe URL"
            ):
                self.installer.install_tools(
                    self.registry,
                    platform_name="linux-x64",
                    install_root=runner_temp / "redirected",
                    runner_temp=runner_temp,
                    tool_names=["shfmt"],
                    open_url=self.opener_for(
                        {record["url"]: artifact},
                        final_url="http://cdn.example.test/shfmt",
                    ),
                    run_command=self.successful_runner(),
                )

            def fail_download(
                *unused_arguments: object, **unused_options: object
            ) -> None:
                raise TimeoutError("simulated timeout")

            with self.assertRaisesRegex(
                self.installer.InstallerError,
                "shfmt: download failed: simulated timeout",
            ):
                self.installer.install_tools(
                    self.registry,
                    platform_name="linux-x64",
                    install_root=runner_temp / "timeout",
                    runner_temp=runner_temp,
                    tool_names=["shfmt"],
                    open_url=fail_download,
                    run_command=self.successful_runner(),
                )
            self.assertEqual(list(runner_temp.iterdir()), [])

    def test_incomplete_http_body_is_reported_and_cleaned(self) -> None:
        class IncompleteResponse(FakeResponse):
            def read(self, *unused_arguments: object) -> bytes:
                raise http.client.IncompleteRead(b"partial", 10)

        artifact, _, _ = self.artifact_for("shfmt")
        record = self.registry["external"]["shfmt"]
        record["sha256"] = hashlib.sha256(artifact).hexdigest()
        probe = mock.Mock()

        def open_url(request: object, *, timeout: float) -> IncompleteResponse:
            return IncompleteResponse(artifact, request.full_url)

        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            install_root = runner_temp / "quality-tools"
            with self.assertRaisesRegex(
                self.installer.InstallerError,
                r"shfmt: download failed: IncompleteRead",
            ):
                self.installer.install_tools(
                    self.registry,
                    platform_name="linux-x64",
                    install_root=install_root,
                    runner_temp=runner_temp,
                    tool_names=["shfmt"],
                    open_url=open_url,
                    run_command=probe,
                )
            probe.assert_not_called()
            self.assertFalse(install_root.exists())
            self.assertEqual(list(runner_temp.iterdir()), [])

    def test_default_download_opener_uses_safe_redirect_handler(self) -> None:
        artifact, _, _ = self.artifact_for("shfmt")
        record = self.registry["external"]["shfmt"]
        record["sha256"] = hashlib.sha256(artifact).hexdigest()
        opener = mock.Mock()
        opener.open.return_value = FakeResponse(artifact, record["url"])
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            mock.patch.object(
                self.installer.urllib.request,
                "build_opener",
                return_value=opener,
            ) as build_opener,
        ):
            runner_temp = Path(temporary_directory)
            self.installer.install_tools(
                self.registry,
                platform_name="linux-x64",
                install_root=runner_temp / "quality-tools",
                runner_temp=runner_temp,
                tool_names=["shfmt"],
                run_command=self.successful_runner(),
            )

        build_opener.assert_called_once()
        self.assertEqual(len(build_opener.call_args.args), 1)
        self.assertIsInstance(
            build_opener.call_args.args[0], self.installer.SafeRedirectHandler
        )
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, record["url"])
        self.assertEqual(
            opener.open.call_args.kwargs,
            {"timeout": self.installer.DOWNLOAD_TIMEOUT_SECONDS},
        )

    def test_digest_is_verified_before_archive_or_probe(self) -> None:
        record = self.registry["external"]["actionlint"]
        record["sha256"] = "0" * 64
        probe = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            with mock.patch.object(self.installer.tarfile, "open") as tar_open:
                with self.assertRaisesRegex(
                    self.installer.InstallerError,
                    "actionlint: digest mismatch",
                ):
                    self.installer.install_tools(
                        self.registry,
                        platform_name="linux-x64",
                        install_root=runner_temp / "quality-tools",
                        runner_temp=runner_temp,
                        tool_names=["actionlint"],
                        open_url=self.opener_for(
                            {record["url"]: b"not the expected artifact"}
                        ),
                        run_command=probe,
                    )
            tar_open.assert_not_called()
            probe.assert_not_called()
            self.assertEqual(list(runner_temp.iterdir()), [])

    def test_offline_install_succeeds_for_all_four_artifact_forms(self) -> None:
        for tool_name in EXPECTED_EXTERNAL_TOOLS:
            with self.subTest(tool=tool_name), tempfile.TemporaryDirectory() as temp:
                runner_temp = Path(temp)
                calls: list[tuple[str, float, str]] = []
                run_calls: list[tuple[list[str], dict[str, object]]] = []
                artifact, expected_content, target = self.artifact_for(tool_name)
                record = self.registry["external"][tool_name]
                record["sha256"] = hashlib.sha256(artifact).hexdigest()
                install_root = runner_temp / "quality-tools"
                self.installer.install_tools(
                    self.registry,
                    platform_name="linux-x64",
                    install_root=install_root,
                    runner_temp=runner_temp,
                    tool_names=[tool_name],
                    open_url=self.opener_for({record["url"]: artifact}, calls=calls),
                    run_command=self.successful_runner(run_calls),
                )
                installed = install_root / target
                self.assertEqual(installed.read_bytes(), expected_content)
                if record["install"]["kind"] == "executable" and os.name != "nt":
                    self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o755)
                self.assertEqual(calls, [(record["url"], 60, "quality-tools/1")])
                self.assertEqual(set(runner_temp.iterdir()), {install_root})
                self.assertEqual(len(run_calls), 1)
                self.assertFalse(run_calls[0][1]["shell"])
                self.assertEqual(run_calls[0][1]["timeout"], 15)

    def test_executable_probe_uses_installed_path_and_exact_options(self) -> None:
        observed: list[tuple[list[str], dict[str, object]]] = []

        def run_command(
            command: list[str], **options: object
        ) -> subprocess.CompletedProcess[str]:
            staging_root = Path(options["cwd"])
            installed_path = staging_root / "bin" / "shfmt"
            self.assertEqual(command, [str(installed_path), "--version"])
            self.assertTrue(installed_path.is_file())
            self.assertEqual(
                options,
                {
                    "check": False,
                    "capture_output": True,
                    "text": True,
                    "timeout": 15,
                    "shell": False,
                    "cwd": staging_root,
                    "env": None,
                },
            )
            observed.append((command, options))
            return subprocess.CompletedProcess(
                command, 0, stdout="v3.14.0\n", stderr=""
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            install_root = self.install_one(
                "shfmt", Path(temporary_directory), run_command=run_command
            )
            self.assertEqual(
                (install_root / "bin" / "shfmt").read_bytes(),
                b"shfmt executable\n",
            )
        self.assertEqual(len(observed), 1)

    def test_archive_names_and_member_types_are_strictly_validated(self) -> None:
        unsafe_names = (
            "../escape",
            "/absolute",
            "C:/drive",
            "directory\\file",
            "nul\0name",
            "",
        )
        for name in unsafe_names:
            with (
                self.subTest(name=repr(name)),
                self.assertRaisesRegex(
                    self.installer.InstallerError, "unsafe archive entry"
                ),
            ):
                self.installer._validate_member_names([name])
        for names in (("same", "same"), ("File", "file")):
            with (
                self.subTest(names=names),
                self.assertRaisesRegex(
                    self.installer.InstallerError, "unsafe archive entry"
                ),
            ):
                self.installer._validate_member_names(names)
        with self.assertRaisesRegex(self.installer.InstallerError, "file is a parent"):
            self.installer._validate_member_names(("parent", "parent/child"))

        for member_type in (
            tarfile.SYMTYPE,
            tarfile.LNKTYPE,
            tarfile.FIFOTYPE,
            tarfile.CHRTYPE,
            tarfile.BLKTYPE,
            b"Z",
        ):
            with self.subTest(member_type=member_type):
                artifact = make_tar(
                    "tar.gz", [("release/actionlint", b"", member_type)]
                )
                record = self.registry["external"]["actionlint"]
                record["sha256"] = hashlib.sha256(artifact).hexdigest()
                with tempfile.TemporaryDirectory() as temporary_directory:
                    runner_temp = Path(temporary_directory)
                    with self.assertRaisesRegex(
                        self.installer.InstallerError, "unsafe archive entry"
                    ):
                        self.installer.install_tools(
                            self.registry,
                            platform_name="linux-x64",
                            install_root=runner_temp / "quality-tools",
                            runner_temp=runner_temp,
                            tool_names=["actionlint"],
                            open_url=self.opener_for({record["url"]: artifact}),
                            run_command=self.successful_runner(),
                        )

        encrypted = zipfile.ZipInfo("PSScriptAnalyzer.psd1")
        encrypted.flag_bits |= 1
        symlink = zipfile.ZipInfo("PSScriptAnalyzer.psd1")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        fifo = zipfile.ZipInfo("PSScriptAnalyzer.psd1")
        fifo.create_system = 3
        fifo.external_attr = (stat.S_IFIFO | 0o644) << 16
        for member in (encrypted, symlink, fifo):
            with (
                self.subTest(zip_member=member.external_attr),
                self.assertRaisesRegex(
                    self.installer.InstallerError, "unsafe archive entry"
                ),
            ):
                self.installer._validate_zip_members([member])

    def test_dangerous_archives_fail_through_public_installation(self) -> None:
        symlink = zipfile.ZipInfo("PSScriptAnalyzer.psd1")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        fifo = zipfile.ZipInfo("PSScriptAnalyzer.psd1")
        fifo.create_system = 3
        fifo.external_attr = (stat.S_IFIFO | 0o644) << 16
        safe_module_entry = ("PSScriptAnalyzer.psm1", b"# module\n")
        encrypted = mark_first_zip_member_encrypted(
            make_zip_members(
                [
                    ("PSScriptAnalyzer.psd1", b"@{}\n"),
                    safe_module_entry,
                ]
            )
        )
        cases = (
            (
                "tar traversal",
                "actionlint",
                make_tar("tar.gz", [("../actionlint", b"bad", None)]),
            ),
            (
                "tar case collision",
                "actionlint",
                make_tar(
                    "tar.gz",
                    [
                        ("One/actionlint", b"one", None),
                        ("one/ACTIONLINT", b"two", None),
                    ],
                ),
            ),
            (
                "tar file parent",
                "actionlint",
                make_tar(
                    "tar.gz",
                    [
                        ("release", b"parent", None),
                        ("release/actionlint", b"child", None),
                    ],
                ),
            ),
            (
                "ZIP traversal",
                "PSScriptAnalyzer",
                make_zip_members(
                    [
                        ("../PSScriptAnalyzer.psd1", b"@{}\n"),
                        safe_module_entry,
                    ]
                ),
            ),
            (
                "ZIP symlink",
                "PSScriptAnalyzer",
                make_zip_members([(symlink, b"target"), safe_module_entry]),
            ),
            (
                "ZIP FIFO",
                "PSScriptAnalyzer",
                make_zip_members([(fifo, b""), safe_module_entry]),
            ),
            ("ZIP encrypted", "PSScriptAnalyzer", encrypted),
        )
        for label, tool_name, artifact in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                runner_temp = Path(temp)
                install_root = runner_temp / "quality-tools"
                record = self.registry["external"][tool_name]
                record["sha256"] = hashlib.sha256(artifact).hexdigest()
                probe = mock.Mock()
                with self.assertRaisesRegex(
                    self.installer.InstallerError,
                    f"{tool_name}: unsafe archive entry",
                ):
                    self.installer.install_tools(
                        self.registry,
                        platform_name="linux-x64",
                        install_root=install_root,
                        runner_temp=runner_temp,
                        tool_names=[tool_name],
                        open_url=self.opener_for({record["url"]: artifact}),
                        run_command=probe,
                    )
                probe.assert_not_called()
                self.assertFalse(install_root.exists())
                self.assertEqual(list(runner_temp.iterdir()), [])

    def test_required_archive_members_are_enforced(self) -> None:
        cases = {
            "missing executable": make_tar(
                "tar.gz", [("release/not-actionlint", b"other", None)]
            ),
            "multiple executables": make_tar(
                "tar.gz",
                [
                    ("one/actionlint", b"one", None),
                    ("two/actionlint", b"two", None),
                ],
            ),
        }
        for label, artifact in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                runner_temp = Path(temp)
                record = self.registry["external"]["actionlint"]
                record["sha256"] = hashlib.sha256(artifact).hexdigest()
                with self.assertRaisesRegex(
                    self.installer.InstallerError,
                    "actionlint: required member not found",
                ):
                    self.installer.install_tools(
                        self.registry,
                        platform_name="linux-x64",
                        install_root=runner_temp / "quality-tools",
                        runner_temp=runner_temp,
                        tool_names=["actionlint"],
                        open_url=self.opener_for({record["url"]: artifact}),
                        run_command=self.successful_runner(),
                    )

        artifact = make_zip({"PSScriptAnalyzer.psd1": b"@{}\n"})
        record = self.registry["external"]["PSScriptAnalyzer"]
        record["sha256"] = hashlib.sha256(artifact).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            with self.assertRaisesRegex(
                self.installer.InstallerError,
                "PSScriptAnalyzer: required member not found",
            ):
                self.installer.install_tools(
                    self.registry,
                    platform_name="linux-x64",
                    install_root=runner_temp / "quality-tools",
                    runner_temp=runner_temp,
                    tool_names=["PSScriptAnalyzer"],
                    open_url=self.opener_for({record["url"]: artifact}),
                    run_command=self.successful_runner(),
                )

    def test_powershell_module_preserves_exact_regular_zip_entries(self) -> None:
        expected_files = {
            "PSScriptAnalyzer.psd1": b"@{}\n",
            "PSScriptAnalyzer.psm1": b"# module\n",
            "en-US/about_PSScriptAnalyzer.help.txt": b"help\n",
        }
        artifact = make_zip_members(
            [
                ("en-US/", b""),
                *list(expected_files.items()),
            ]
        )
        record = self.registry["external"]["PSScriptAnalyzer"]
        record["sha256"] = hashlib.sha256(artifact).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            install_root = runner_temp / "quality-tools"
            self.installer.install_tools(
                self.registry,
                platform_name="linux-x64",
                install_root=install_root,
                runner_temp=runner_temp,
                tool_names=["PSScriptAnalyzer"],
                open_url=self.opener_for({record["url"]: artifact}),
                run_command=self.successful_runner(),
            )
            module_root = install_root / record["install"]["target"]
            actual_files = {
                path.relative_to(module_root).as_posix(): path.read_bytes()
                for path in module_root.rglob("*")
                if path.is_file()
            }
            actual_directories = {
                path.relative_to(module_root).as_posix()
                for path in module_root.rglob("*")
                if path.is_dir()
            }
        self.assertEqual(actual_files, expected_files)
        self.assertEqual(actual_directories, {"en-US"})

    def test_install_root_must_be_new_safe_and_under_runner_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            outside = runner_temp.parent / "outside-quality-tools"
            existing = runner_temp / "existing"
            existing.mkdir()
            cases = (
                (runner_temp, "must be strictly under RUNNER_TEMP"),
                (outside, "must be strictly under RUNNER_TEMP"),
                (existing, "must not already exist"),
            )
            for install_root, diagnostic in cases:
                with (
                    self.subTest(root=install_root),
                    self.assertRaisesRegex(self.installer.InstallerError, diagnostic),
                ):
                    self.installer.validate_install_root(install_root, runner_temp)
            missing_runner = runner_temp / "missing"
            with self.assertRaisesRegex(
                self.installer.InstallerError, "RUNNER_TEMP must exist"
            ):
                self.installer.validate_install_root(
                    missing_runner / "tools", missing_runner
                )

            link = runner_temp / "broken-link"
            path_type = type(link)
            original_exists = path_type.exists
            original_is_symlink = path_type.is_symlink
            with (
                mock.patch.object(
                    path_type,
                    "exists",
                    autospec=True,
                    side_effect=lambda path: (
                        False if path == link else original_exists(path)
                    ),
                ),
                mock.patch.object(
                    path_type,
                    "is_symlink",
                    autospec=True,
                    side_effect=lambda path: (
                        True if path == link else original_is_symlink(path)
                    ),
                ),
                self.assertRaisesRegex(self.installer.InstallerError, "symlink"),
            ):
                self.installer.validate_install_root(link / "tools", runner_temp)

    def test_real_symlink_roots_are_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            runner_temp = test_root / "runner"
            runner_temp.mkdir()
            runner_link = test_root / "runner-link"
            try:
                runner_link.symlink_to(runner_temp, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            real_parent = runner_temp / "real-parent"
            real_parent.mkdir()
            parent_link = runner_temp / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            existing_target = runner_temp / "existing-target"
            existing_target.mkdir()
            root_link = runner_temp / "root-link"
            root_link.symlink_to(existing_target, target_is_directory=True)

            cases = (
                (runner_link / "tools", runner_link),
                (parent_link / "tools", runner_temp),
                (root_link, runner_temp),
            )
            for install_root, runner in cases:
                with (
                    self.subTest(root=install_root),
                    self.assertRaisesRegex(self.installer.InstallerError, "symlink"),
                ):
                    self.installer.validate_install_root(install_root, runner)

    def test_probe_errors_include_bounded_stdout_and_stderr(self) -> None:
        artifact, _, _ = self.artifact_for("shfmt")
        record = self.registry["external"]["shfmt"]
        record["sha256"] = hashlib.sha256(artifact).hexdigest()
        cases: list[tuple[str, object, str]] = [
            (
                "wrong version",
                subprocess.CompletedProcess(
                    ["shfmt"], 0, stdout="v0.0.0\n", stderr="warning\n"
                ),
                "unexpected output.*stdout: v0.0.0.*stderr: warning",
            ),
            (
                "bounded output",
                subprocess.CompletedProcess(
                    ["shfmt"], 0, stdout="x" * 3_000, stderr="y" * 3_000
                ),
                (
                    r"unexpected output.*stdout: x{2000}\.\.\.; "
                    r"stderr: y{2000}\.\.\."
                ),
            ),
            (
                "nonzero",
                subprocess.CompletedProcess(
                    ["shfmt"], 7, stdout="out\n", stderr="err\n"
                ),
                "exited 7.*stdout: out.*stderr: err",
            ),
            (
                "timeout",
                subprocess.TimeoutExpired(
                    ["shfmt"], 5, output="partial out", stderr="partial err"
                ),
                "timed out.*stdout: partial out.*stderr: partial err",
            ),
        ]
        for label, outcome, diagnostic in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                runner_temp = Path(temp)

                def run_command(
                    *unused_arguments: object, **unused_options: object
                ) -> subprocess.CompletedProcess[str]:
                    if isinstance(outcome, BaseException):
                        raise outcome
                    return outcome

                with self.assertRaisesRegex(
                    self.installer.InstallerError,
                    f"shfmt: version probe failed: {diagnostic}",
                ):
                    self.installer.install_tools(
                        self.registry,
                        platform_name="linux-x64",
                        install_root=runner_temp / "quality-tools",
                        runner_temp=runner_temp,
                        tool_names=["shfmt"],
                        open_url=self.opener_for({record["url"]: artifact}),
                        run_command=run_command,
                    )
                self.assertEqual(list(runner_temp.iterdir()), [])

    def test_last_probe_failure_does_not_publish_partial_install(self) -> None:
        artifacts: dict[str, bytes] = {}
        for tool_name in ("shfmt", "shellcheck"):
            artifact, _, _ = self.artifact_for(tool_name)
            record = self.registry["external"][tool_name]
            record["sha256"] = hashlib.sha256(artifact).hexdigest()
            artifacts[record["url"]] = artifact

        def fail_shellcheck(
            command: list[str], **unused_options: object
        ) -> subprocess.CompletedProcess[str]:
            name = Path(command[0]).name.lower().removesuffix(".exe")
            output = "v3.14.0\n" if name == "shfmt" else "wrong\n"
            return subprocess.CompletedProcess(command, 0, output, "")

        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            install_root = runner_temp / "quality-tools"
            with self.assertRaisesRegex(
                self.installer.InstallerError,
                "shellcheck: version probe failed",
            ):
                self.installer.install_tools(
                    self.registry,
                    platform_name="linux-x64",
                    install_root=install_root,
                    runner_temp=runner_temp,
                    tool_names=["shfmt", "shellcheck"],
                    open_url=self.opener_for(artifacts),
                    run_command=fail_shellcheck,
                )
            self.assertFalse(install_root.exists())
            self.assertEqual(list(runner_temp.iterdir()), [])

    def test_powershell_probe_uses_exact_staged_module_on_both_platforms(self) -> None:
        for platform_name in ("linux-x64", "windows-x64"):
            with (
                self.subTest(platform=platform_name),
                tempfile.TemporaryDirectory() as temp,
            ):
                calls: list[tuple[list[str], dict[str, object]]] = []
                install_root = self.install_one(
                    "PSScriptAnalyzer",
                    Path(temp),
                    platform_name=platform_name,
                    run_command=self.successful_runner(calls),
                )
                command, options = calls[0]
                self.assertEqual(
                    command[:4],
                    [
                        "pwsh",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                    ],
                )
                self.assertIn("-RequiredVersion 1.25.0", command[4])
                self.assertIn("Invoke-ScriptAnalyzer", command[4])
                self.assertIn("QUALITY_PSSA_MODULE_PATH", command[4])
                environment = options["env"]
                module_path = Path(environment["QUALITY_PSSA_MODULE_PATH"])
                self.assertEqual(module_path.name, "1.25.0")
                self.assertEqual(
                    environment["PSModulePath"].split(os.pathsep)[0],
                    str(module_path.parents[1]),
                )
                self.assertTrue(install_root.is_dir())

                script = command[4]
                required_fragments = (
                    "if ($PSVersionTable.PSVersion -lt [version]'7.4.6')",
                    (
                        "Import-Module $manifestPath -RequiredVersion 1.25.0 "
                        "-Force -ErrorAction Stop"
                    ),
                    ("if ([IO.Path]::GetFullPath($module.ModuleBase) -ne $modulePath)"),
                    (
                        "$null = Invoke-ScriptAnalyzer -ScriptDefinition "
                        "'$value = 1' -ErrorAction Stop"
                    ),
                )
                positions = [script.index(fragment) for fragment in required_fragments]
                self.assertEqual(positions, sorted(positions))

        artifact, _, _ = self.artifact_for("PSScriptAnalyzer")
        record = self.registry["external"]["PSScriptAnalyzer"]
        record["sha256"] = hashlib.sha256(artifact).hexdigest()
        failure_diagnostics = (
            "PowerShell 7.4.6 or newer is required.",
            "PSScriptAnalyzer was imported outside the staging root.",
        )
        for diagnostic in failure_diagnostics:
            with (
                self.subTest(diagnostic=diagnostic),
                tempfile.TemporaryDirectory() as temp,
            ):
                runner_temp = Path(temp)
                install_root = runner_temp / "quality-tools"

                def fail_probe(
                    command: list[str], **unused_options: object
                ) -> subprocess.CompletedProcess[str]:
                    return subprocess.CompletedProcess(
                        command, 1, stdout="", stderr=diagnostic + "\n"
                    )

                with self.assertRaisesRegex(
                    self.installer.InstallerError,
                    re.escape(diagnostic),
                ):
                    self.installer.install_tools(
                        self.registry,
                        platform_name="linux-x64",
                        install_root=install_root,
                        runner_temp=runner_temp,
                        tool_names=["PSScriptAnalyzer"],
                        open_url=self.opener_for({record["url"]: artifact}),
                        run_command=fail_probe,
                    )
                self.assertFalse(install_root.exists())
                self.assertEqual(list(runner_temp.iterdir()), [])

    def test_cli_reports_root_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runner_temp = Path(temporary_directory)
            environment = os.environ.copy()
            environment["RUNNER_TEMP"] = str(runner_temp)
            result = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER_PATH),
                    "--platform",
                    "linux-x64",
                    "--install-root",
                    str(runner_temp),
                ],
                cwd=SOURCE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("external tools: install root", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
