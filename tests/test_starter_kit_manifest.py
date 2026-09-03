import copy
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SOURCE_ROOT / "tools" / "starter-kit-manifest.py"
CODEOWNERS_PATH = SOURCE_ROOT / ".github" / "CODEOWNERS"
DEPENDABOT_PATH = SOURCE_ROOT / ".github" / "dependabot.yml"
SPEC = importlib.util.spec_from_file_location("starter_kit_manifest", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MANIFEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANIFEST)


class StarterKitManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_git("init")
        self.run_git("config", "user.name", "Manifest Test")
        self.run_git("config", "user.email", "test@example.com")
        self.run_git(
            "remote",
            "add",
            "origin",
            "https://github.com/asphyx0r/git-starter-kit.git",
        )
        (self.root / "a.txt").write_text("alpha\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Example\n", encoding="utf-8")
        (self.root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
        (self.root / "BRANCH_RULES.md").write_text("branch rules\n", encoding="utf-8")
        source_only = self.root / "tools" / "starter-kit-manifest.py"
        source_only.parent.mkdir()
        source_only.write_text("source only\n", encoding="utf-8")
        (self.root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        (self.root / "SHA256SUMS").write_text("release state\n", encoding="utf-8")
        (self.root / "manifest.json").write_text("{}\n", encoding="utf-8")
        (self.root / "tools" / "release-artifacts.py").write_text(
            "distributed tool\n",
            encoding="utf-8",
        )
        self.run_git("add", "--all")
        self.run_git("commit", "-m", "test: create fixture")

    def tearDown(self):
        self.temporary.cleanup()

    def run_git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def run_main(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = MANIFEST.main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def prepare(self, *extra):
        return self.run_main(
            "prepare",
            "--release-ref",
            "v1.2.3",
            "--repository-root",
            str(self.root),
            *extra,
        )

    def test_rejects_unsafe_manifest_paths_and_malformed_git_protocol(self):
        with self.assertRaises(MANIFEST.ManifestError):
            MANIFEST.require_repository_root(Path(self.temporary.name) / "missing")
        nested = self.root / "nested"
        nested.mkdir()
        with self.assertRaises(MANIFEST.ManifestError):
            MANIFEST.require_repository_root(nested)

        for value in ("", "../escape", "/absolute", "bad\\path"):
            with self.subTest(path=value), self.assertRaises(MANIFEST.ManifestError):
                MANIFEST.validate_relative_path(value)

        text_kind, text_digest = MANIFEST.content_metadata(b"one\r\ntwo\r")
        self.assertEqual(text_kind, "text")
        self.assertEqual(text_digest, MANIFEST.sha256_bytes(b"one\ntwo\n"))
        binary_kind, binary_digest = MANIFEST.content_metadata(b"\xff")
        self.assertEqual(binary_kind, "binary")
        self.assertEqual(binary_digest, MANIFEST.sha256_bytes(b"\xff"))

        self.assertEqual(MANIFEST.read_blobs(self.root, []), [])
        protocol_results = (
            subprocess.CompletedProcess([], 1, b"", b"failure"),
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, b"def blob 1\nx\n", b""),
            subprocess.CompletedProcess([], 0, b"abc blob 1\nx", b""),
            subprocess.CompletedProcess([], 0, b"abc blob 1\nx\nextra", b""),
        )
        for result in protocol_results:
            with (
                self.subTest(stdout=result.stdout),
                patch.object(MANIFEST.subprocess, "run", return_value=result),
                self.assertRaises(MANIFEST.ManifestError),
            ):
                MANIFEST.read_blobs(self.root, ["abc"])

        invalid_index_records = (
            b"100644 abc 1\tfile\0",
            b"100600 abc 0\tfile\0",
        )
        for output in invalid_index_records:
            with (
                self.subTest(index=output),
                patch.object(MANIFEST, "run_git", return_value=output),
                self.assertRaises(MANIFEST.ManifestError),
            ):
                MANIFEST.index_entries(self.root)

        invalid_tree_records = (b"100600 blob abc\tfile\0",)
        for output in invalid_tree_records:
            with (
                self.subTest(tree=output),
                patch.object(MANIFEST, "run_git", return_value=output),
                self.assertRaises(MANIFEST.ManifestError),
            ):
                MANIFEST.tree_entries(self.root, "HEAD")
        with patch.object(
            MANIFEST,
            "run_git",
            return_value=b"100644 commit abc\tfile\0",
        ):
            self.assertEqual(MANIFEST.tree_entries(self.root, "HEAD"), [])

    def test_prepare_writes_exact_release_and_core_inventory(self):
        code, _, stderr = self.prepare()

        self.assertEqual(code, 0, stderr)
        value = json.loads(
            (self.root / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(value["schemaVersion"], 1)
        self.assertEqual(value["source"], value["current"])
        self.assertEqual(value["current"]["ref"], "v1.2.3")
        self.assertEqual(
            value["current"]["releaseUrl"],
            "https://github.com/asphyx0r/git-starter-kit/releases/tag/v1.2.3",
        )
        entries = {entry["path"]: entry for entry in value["files"]}
        self.assertEqual(
            set(entries),
            {"README.md", "a.txt", "tools/release-artifacts.py"},
        )
        self.assertEqual(entries["README.md"]["strategy"], "initialize-only")
        self.assertEqual(entries["a.txt"]["strategy"], "replace")

    def test_prepare_is_idempotent(self):
        self.assertEqual(self.prepare()[0], 0)
        before = (self.root / "starter-kit-manifest.json").read_bytes()

        self.assertEqual(self.prepare()[0], 0)

        self.assertEqual((self.root / "starter-kit-manifest.json").read_bytes(), before)

    def test_prepare_classifies_audit_modules_as_initialize_only(self):
        audit_directory = self.root / "tools" / "repository-audit"
        audit_directory.mkdir()
        module_paths = {
            audit_directory / name
            for name in (
                "agent-rules-transfer.sh",
                "common.sh",
                "contracts.sh",
                "hooks.sh",
                "profiles.sh",
                "security.sh",
                "smoke.sh",
            )
        }
        for module_path in module_paths:
            module_path.write_text(":\n", encoding="utf-8")
        transfer_test = self.root / "tests" / "test_agent_rules_transfer.sh"
        transfer_test.parent.mkdir()
        transfer_test.write_text(":\n", encoding="utf-8")
        self.run_git(
            "add",
            "tools/repository-audit",
            "tests/test_agent_rules_transfer.sh",
        )
        self.run_git("commit", "-m", "test: add audit modules")

        code, _, stderr = self.prepare()

        self.assertEqual(code, 0, stderr)
        value = json.loads(
            (self.root / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        strategies = {entry["path"]: entry["strategy"] for entry in value["files"]}
        expected_paths = {
            module_path.relative_to(self.root).as_posix()
            for module_path in module_paths
        }
        self.assertEqual(
            {path for path in strategies if path.startswith("tools/repository-audit/")},
            expected_paths,
        )
        self.assertTrue(
            all(strategies[path] == "initialize-only" for path in expected_paths)
        )
        self.assertEqual(
            strategies["tests/test_agent_rules_transfer.sh"],
            "replace",
        )

    def test_prepare_classifies_quality_configuration_as_replace(self):
        quality_directory = self.root / "tools" / "quality"
        quality_directory.mkdir()
        quality_paths = {
            quality_directory / "check-versions.py",
            quality_directory / "install-external-tools.py",
            quality_directory / "package-lock.json",
            quality_directory / "package.json",
            quality_directory / "PSScriptAnalyzerSettings.psd1",
            quality_directory / "pyproject.toml",
            quality_directory / "requirements.in",
            quality_directory / "requirements.lock",
            quality_directory / "versions.json",
            quality_directory / "yamllint.yaml",
        }
        for quality_path in quality_paths:
            quality_path.write_text("quality\n", encoding="utf-8")
        self.run_git("add", "tools/quality")
        self.run_git("commit", "-m", "test: add quality configuration")

        code, _, stderr = self.prepare()

        self.assertEqual(code, 0, stderr)
        value = json.loads(
            (self.root / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        strategies = {entry["path"]: entry["strategy"] for entry in value["files"]}
        expected_paths = {
            quality_path.relative_to(self.root).as_posix()
            for quality_path in quality_paths
        }
        self.assertEqual(
            {path: strategies[path] for path in expected_paths},
            {path: "replace" for path in expected_paths},
        )
        self.assertEqual(
            {path for path in strategies if path.startswith("tools/quality/")},
            expected_paths,
        )

    def test_prepare_keeps_future_upgrade_modules_source_only(self):
        future_module = self.root / "tools" / "starter_kit_upgrade" / "future.py"
        future_module.parent.mkdir()
        future_module.write_text("future = True\n", encoding="utf-8")
        self.run_git("add", future_module.relative_to(self.root).as_posix())
        self.run_git("commit", "-m", "test: add future upgrade module")

        code, _, stderr = self.prepare()

        self.assertEqual(code, 0, stderr)
        value = json.loads(
            (self.root / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        paths = {entry["path"] for entry in value["files"]}
        self.assertNotIn("tools/starter_kit_upgrade/future.py", paths)

    def test_governance_files_are_exact(self):
        self.assertEqual(CODEOWNERS_PATH.read_text(encoding="utf-8"), "* @asphyx0r\n")
        self.assertEqual(
            DEPENDABOT_PATH.read_text(encoding="utf-8"),
            "version: 2\n"
            "updates:\n"
            '  - package-ecosystem: "github-actions"\n'
            '    directory: "/"\n'
            "    schedule:\n"
            '      interval: "weekly"\n'
            '  - package-ecosystem: "pip"\n'
            '    directory: "/tools/quality"\n'
            "    schedule:\n"
            '      interval: "weekly"\n'
            '  - package-ecosystem: "npm"\n'
            '    directory: "/tools/quality"\n'
            "    schedule:\n"
            '      interval: "weekly"\n',
        )

    def test_prepare_applies_governance_distribution_policy(self):
        github_directory = self.root / ".github"
        github_directory.mkdir()
        (github_directory / "CODEOWNERS").write_text("* @owner\n", encoding="utf-8")
        (github_directory / "dependabot.yml").write_text(
            "version: 2\n", encoding="utf-8"
        )
        builder_test = self.root / "tests" / "test_build_release_package.py"
        builder_test.parent.mkdir()
        builder_test.write_text("source only\n", encoding="utf-8")
        self.run_git("add", ".github", "tests/test_build_release_package.py")
        self.run_git("commit", "-m", "test: add governance files")

        code, _, stderr = self.prepare()

        self.assertEqual(code, 0, stderr)
        value = json.loads(
            (self.root / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        strategies = {entry["path"]: entry["strategy"] for entry in value["files"]}
        self.assertNotIn(".github/CODEOWNERS", strategies)
        self.assertNotIn("tests/test_build_release_package.py", strategies)
        self.assertEqual(strategies[".github/dependabot.yml"], "merge")

    def test_dry_run_reports_without_writing(self):
        code, stdout, stderr = self.run_main(
            "--dry-run",
            "prepare",
            "--release-ref",
            "v1.2.3",
            "--repository-root",
            str(self.root),
        )

        self.assertEqual(code, 0, stderr)
        self.assertTrue(json.loads(stdout)["wouldWrite"])
        self.assertFalse((self.root / "starter-kit-manifest.json").exists())

    def test_prepare_rejects_noncanonical_origin(self):
        self.run_git(
            "remote", "set-url", "origin", "https://github.com/example/fork.git"
        )

        code, _, stderr = self.prepare()

        self.assertEqual(code, 1)
        self.assertIn("canonical", stderr)
        self.assertFalse((self.root / "starter-kit-manifest.json").exists())

    def test_check_uses_existing_release_tag(self):
        self.run_git("tag", "v1.2.3")
        self.assertEqual(self.prepare("--treeish", "v1.2.3")[0], 0)
        self.run_git("add", "starter-kit-manifest.json")
        self.run_git("commit", "-m", "test: add manifest")
        (self.root / "a.txt").write_text("unreleased\n", encoding="utf-8")

        code, stdout, stderr = self.run_main(
            "check", "--repository-root", str(self.root)
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["treeish"], "v1.2.3")

    def test_check_detects_inventory_drift(self):
        self.assertEqual(self.prepare()[0], 0)
        value = json.loads(
            (self.root / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )
        value["files"][0]["sha256"] = "0" * 64
        (self.root / "starter-kit-manifest.json").write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )

        code, _, stderr = self.run_main(
            "check", "--repository-root", str(self.root), "--treeish", "HEAD"
        )

        self.assertEqual(code, 1)
        self.assertIn("inventory", stderr)

    def test_git_and_json_boundaries_report_invalid_inputs(self):
        for binary, stderr in ((False, "denied"), (True, b"denied")):
            completed = subprocess.CompletedProcess(
                [], 1, b"" if binary else "", stderr
            )
            with (
                self.subTest(binary=binary),
                patch.object(MANIFEST.subprocess, "run", return_value=completed),
                self.assertRaisesRegex(
                    MANIFEST.ManifestError, "git status failed: denied"
                ),
            ):
                MANIFEST.run_git(self.root, "status", binary=binary)

        invalid_manifest = self.root / "invalid-manifest.json"
        invalid_manifest.write_text("not json\n", encoding="utf-8")
        with self.assertRaisesRegex(MANIFEST.ManifestError, "Invalid JSON manifest"):
            MANIFEST.read_manifest(invalid_manifest)
        invalid_manifest.write_text("[]\n", encoding="utf-8")
        with self.assertRaisesRegex(MANIFEST.ManifestError, "JSON object"):
            MANIFEST.read_manifest(invalid_manifest)
        with self.assertRaisesRegex(MANIFEST.ManifestError, "SemVer tag"):
            MANIFEST.release_descriptor("1.2.3", "2026-01-01T00:00:00Z")

    def test_manifest_validation_rejects_each_contract_mutation(self):
        code, _, stderr = self.prepare()
        self.assertEqual(code, 0, stderr)
        baseline = json.loads(
            (self.root / "starter-kit-manifest.json").read_text(encoding="utf-8")
        )

        cases = (
            (
                "top-level field",
                lambda value: value.__setitem__("unexpected", True),
                "unsupported top-level fields",
            ),
            (
                "schema",
                lambda value: value.__setitem__("schemaVersion", 2),
                "Unsupported starter-kit manifest schema",
            ),
            (
                "release fields",
                lambda value: value["source"].pop("repository"),
                "exact release fields",
            ),
            (
                "release identity",
                lambda value: value["source"].__setitem__(
                    "repository", "https://github.com/example/fork"
                ),
                "canonical release",
            ),
            (
                "timestamp syntax",
                lambda value: value["source"].__setitem__("generatedAt", "invalid"),
                "RFC 3339 UTC",
            ),
            (
                "timestamp timezone",
                lambda value: value["source"].__setitem__(
                    "generatedAt", "2026-01-01T01:00:00+01:00"
                ),
                "RFC 3339 UTC",
            ),
            (
                "files type",
                lambda value: value.__setitem__("files", {}),
                "JSON array",
            ),
            (
                "entry fields",
                lambda value: value["files"][0].pop("mode"),
                "exact file fields",
            ),
            (
                "duplicate path",
                lambda value: value["files"].append(copy.deepcopy(value["files"][0])),
                "Invalid or duplicate core path",
            ),
            (
                "sha256",
                lambda value: value["files"][0].__setitem__("sha256", "invalid"),
                "Invalid SHA-256",
            ),
            (
                "canonical sha256",
                lambda value: value["files"][0].__setitem__(
                    "canonicalSha256", "invalid"
                ),
                "Invalid canonical SHA-256",
            ),
            (
                "content kind",
                lambda value: value["files"][0].__setitem__("contentKind", "archive"),
                "Invalid content kind",
            ),
            (
                "mode",
                lambda value: value["files"][0].__setitem__("mode", "100600"),
                "Invalid Git mode",
            ),
            (
                "strategy",
                lambda value: value["files"][0].__setitem__("strategy", "delete"),
                "Invalid strategy",
            ),
            (
                "sort order",
                lambda value: value["files"].reverse(),
                "sorted by path",
            ),
        )
        for name, mutate, diagnostic in cases:
            value = copy.deepcopy(baseline)
            mutate(value)
            with (
                self.subTest(case=name),
                self.assertRaisesRegex(MANIFEST.ManifestError, diagnostic),
            ):
                MANIFEST.validate_manifest(value)

    def test_upgrade_policy_perimeters_are_exact(self):
        self.assertEqual(
            MANIFEST.MERGE_PATHS,
            frozenset(
                {
                    ".betterleaks.toml",
                    ".codespellrc",
                    ".editorconfig",
                    ".gitattributes",
                    ".gitleaks.toml",
                    ".gitignore",
                    ".github/dependabot.yml",
                    ".github/workflows/repository-audit.yml",
                }
            ),
        )
        self.assertEqual(
            MANIFEST.SOURCE_ONLY_PATHS,
            frozenset(
                {
                    (
                        ".agents/skills/git-commit-push-tag/references/"
                        "git-starter-kit-release-package.txt"
                    ),
                    ".github/CODEOWNERS",
                    ".github/workflows/release-package.yml",
                    "SHA256SUMS",
                    "VERSION",
                    "docs/release-package.md",
                    "docs/upgrade-toolkit.md",
                    "manifest.json",
                    "tests/test_build_release_package.py",
                    "tests/test_starter_kit_manifest.py",
                    "tests/test_starter_kit_upgrade.py",
                    "tools/build-release-package.ps1",
                    "tools/starter-kit-manifest.py",
                    "tools/starter-kit-upgrade.py",
                    "tools/starter_kit_upgrade/__init__.py",
                    "tools/starter_kit_upgrade/application.py",
                    "tools/starter_kit_upgrade/archive.py",
                    "tools/starter_kit_upgrade/cli.py",
                    "tools/starter_kit_upgrade/common.py",
                    "tools/starter_kit_upgrade/planning.py",
                }
            ),
        )
        self.assertEqual(
            MANIFEST.SOURCE_ONLY_PREFIXES,
            ("tools/starter_kit_upgrade/",),
        )
        self.assertEqual(
            MANIFEST.AGENT_RULE_PATHS,
            frozenset(
                {
                    "AGENTS.md",
                    "BRANCH_RULES.md",
                    "CODING_RULES.md",
                    "COMMIT_RULES.md",
                    "DOCUMENTATION_RULES.md",
                    "LANGUAGE_RULES.md",
                    "RELEASE_RULES.md",
                    "_agent-rules-source.json",
                }
            ),
        )
        self.assertEqual(
            MANIFEST.INITIALIZE_ONLY_PATHS,
            frozenset(
                {
                    "CHANGELOG.md",
                    "CODE_OF_CONDUCT.md",
                    "CONTRIBUTING.md",
                    "LICENSE",
                    "README.md",
                    "SECURITY.md",
                    "SUPPORT.md",
                    "docs/SKILLS.md",
                    "docs/repository-files.md",
                    "docs/repository-migration.md",
                    "tools/README.md",
                    "tools/repository-audit.sh",
                }
            ),
        )
        self.assertEqual(MANIFEST.REPLACE_PREFIXES, ("tools/quality/",))

    def test_version_is_exact(self):
        with (
            self.assertRaises(SystemExit) as raised,
            redirect_stdout(io.StringIO()) as output,
        ):
            MANIFEST.build_parser().parse_args(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), "v1.1.0\n")


if __name__ == "__main__":
    unittest.main()
