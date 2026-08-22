import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "starter-kit-manifest.py"
)
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
        (self.root / "BRANCH_RULES.md").write_text(
            "branch rules\n", encoding="utf-8"
        )
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

        self.assertEqual(
            (self.root / "starter-kit-manifest.json").read_bytes(), before
        )

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
        self.run_git("remote", "set-url", "origin", "https://github.com/example/fork.git")

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
                    ".github/workflows/release-package.yml",
                    "SHA256SUMS",
                    "VERSION",
                    "docs/release-package.md",
                    "docs/upgrade-toolkit.md",
                    "manifest.json",
                    "tests/test_starter_kit_manifest.py",
                    "tests/test_starter_kit_upgrade.py",
                    "tools/build-release-package.ps1",
                    "tools/starter-kit-manifest.py",
                    "tools/starter-kit-upgrade.py",
                }
            ),
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

    def test_version_is_exact(self):
        with self.assertRaises(SystemExit) as raised, redirect_stdout(
            io.StringIO()
        ) as output:
            MANIFEST.build_parser().parse_args(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), "v1.1.0\n")


if __name__ == "__main__":
    unittest.main()
