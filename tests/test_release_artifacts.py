import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "release-artifacts.py"
SOURCE_ROOT = SCRIPT_PATH.parents[1]
SPEC = importlib.util.spec_from_file_location("release_artifacts", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
ARTIFACTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACTS)


class ReleaseArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.run_git("init")
        self.run_git("config", "user.name", "Release Artifact Test")
        self.run_git("config", "user.email", "test@example.com")
        self.run_git("config", "core.autocrlf", "false")
        (self.root / "templates" / "release").mkdir(parents=True)
        for name in ("manifest.template.json", "manifest.schema.json"):
            shutil.copyfile(
                SOURCE_ROOT / "templates" / "release" / name,
                self.root / "templates" / "release" / name,
            )
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Example\n", encoding="utf-8")
        (self.root / "mixed.txt").write_bytes(b"one\r\ntwo\n")
        (self.root / "binary.bin").write_bytes(b"\x00\x01\x02")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "test: create fixture")
        (self.root / "ignored.txt").write_text("ignored\n", encoding="utf-8")
        (self.root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        self.metadata_path = Path(self.temporary.name) / "metadata.json"
        self.write_metadata()

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
            code = ARTIFACTS.main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def write_metadata(self, **changes):
        value = {
            "program_id": "example-app",
            "name": "Example App",
            "channel": "stable",
            "critical_update": False,
            "release_notes": ["Add release identification artifacts."],
            "update": {
                "min_source_version": "1.0.0",
                "strategy": "patch",
                "preserve_paths": ["config/local.json"],
                "remove_obsolete_files": True,
                "backup_required": True,
                "restart_required": False,
                "rollback_supported": True,
                "migrations": [],
            },
            "artifact": {
                "id": "source-tree",
                "target": {
                    "os": "any",
                    "arch": "any",
                    "min_os_version": "not-applicable",
                },
            },
            "metadata": {
                "author": "Example Maintainers",
                "license": "MIT",
                "support_url": "https://example.com/support",
            },
        }
        value.update(changes)
        self.metadata_path.write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )

    def prepare(self, ref="v1.2.3"):
        return self.run_main(
            "--force",
            "prepare",
            "--release-ref",
            ref,
            "--release-date",
            "2026-08-18T12:00:00Z",
            "--metadata-file",
            str(self.metadata_path),
            "--repository-root",
            str(self.root),
        )

    def test_prepare_writes_deterministic_release_identification(self):
        code, stdout, stderr = self.prepare()

        self.assertEqual(code, 0, stderr)
        self.assertEqual((self.root / "VERSION").read_bytes(), b"1.2.3\n")
        checksums = (self.root / "SHA256SUMS").read_text(encoding="utf-8")
        self.assertIn("  VERSION\n", checksums)
        self.assertNotIn("manifest.json", checksums)
        self.assertNotIn("SHA256SUMS", checksums)
        self.assertNotIn("ignored.txt", checksums)
        self.assertNotIn("untracked.txt", checksums)
        manifest = json.loads((self.root / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["version"], "1.2.3")
        self.assertEqual(manifest["artifacts"][0]["format"], "git-tree")
        paths = [
            item["relative_path"] for item in manifest["artifacts"][0]["files"]
        ]
        self.assertEqual(
            paths,
            sorted(paths, key=lambda path: path.encode("utf-8")),
        )
        self.assertIn("VERSION", paths)
        self.assertNotIn("manifest.json", paths)
        mixed = next(
            item
            for item in manifest["artifacts"][0]["files"]
            if item["relative_path"] == "mixed.txt"
        )
        binary = next(
            item
            for item in manifest["artifacts"][0]["files"]
            if item["relative_path"] == "binary.bin"
        )
        self.assertIsNone(mixed["line_ending"])
        self.assertEqual(binary["file_type"], "binary")
        self.assertIsNone(binary["encoding"])
        self.assertEqual(
            json.loads(stdout)["changed"],
            ["VERSION", "SHA256SUMS", "manifest.json"],
        )

    def test_dry_run_does_not_write(self):
        code, stdout, stderr = self.run_main(
            "--dry-run",
            "prepare",
            "--release-ref",
            "v1.2.3",
            "--release-date",
            "2026-08-18T12:00:00Z",
            "--metadata-file",
            str(self.metadata_path),
            "--repository-root",
            str(self.root),
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(json.loads(stdout)["changed"]), 3)
        for path in ("VERSION", "SHA256SUMS", "manifest.json"):
            self.assertFalse((self.root / path).exists())

    def test_prepare_requires_force_without_a_terminal(self):
        with patch.object(ARTIFACTS.sys.stdin, "isatty", return_value=False):
            code, _, stderr = self.run_main(
                "prepare",
                "--release-ref",
                "v1.2.3",
                "--release-date",
                "2026-08-18T12:00:00Z",
                "--metadata-file",
                str(self.metadata_path),
                "--repository-root",
                str(self.root),
            )

        self.assertEqual(code, 1)
        self.assertIn("--force", stderr)

    def test_prepare_rejects_unknown_metadata(self):
        self.write_metadata(channel="")

        code, _, stderr = self.prepare()

        self.assertEqual(code, 1)
        self.assertIn("schema", stderr.lower())
        self.assertFalse((self.root / "VERSION").exists())

    def test_check_validates_index_and_tag(self):
        self.assertEqual(self.prepare()[0], 0)
        self.run_git("add", "VERSION", "SHA256SUMS", "manifest.json")

        code, stdout, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["treeish"], "index")

        self.run_git("commit", "-m", "chore: prepare release artifacts")
        self.run_git("tag", "-a", "v1.2.3", "-m", "Release v1.2.3")
        code, stdout, stderr = self.run_main(
            "check",
            "--expected-ref",
            "v1.2.3",
            "--treeish",
            "v1.2.3",
            "--repository-root",
            str(self.root),
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["releaseRef"], "v1.2.3")

    def test_check_rejects_checksum_drift(self):
        self.assertEqual(self.prepare()[0], 0)
        (self.root / "SHA256SUMS").write_text(
            "0" * 64 + "  VERSION\n",
            encoding="utf-8",
        )
        self.run_git("add", "VERSION", "SHA256SUMS", "manifest.json")

        code, _, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )

        self.assertEqual(code, 1)
        self.assertIn("SHA256SUMS", stderr)

    def test_prepare_accepts_full_semver(self):
        code, _, stderr = self.prepare("v2.0.0-rc.1+build.7")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            (self.root / "VERSION").read_text(encoding="utf-8"),
            "2.0.0-rc.1+build.7\n",
        )

    def test_prepare_rejects_incomplete_nested_metadata(self):
        self.write_metadata(update={"strategy": "patch"})

        code, _, stderr = self.prepare()

        self.assertEqual(code, 1)
        self.assertIn("exact policy fields", stderr)

    def test_check_uses_template_and_schema_from_selected_git_content(self):
        self.assertEqual(self.prepare()[0], 0)
        self.run_git("add", "VERSION", "SHA256SUMS", "manifest.json")
        (self.root / "templates" / "release" / "manifest.template.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (self.root / "templates" / "release" / "manifest.schema.json").write_text(
            "{}\n",
            encoding="utf-8",
        )

        code, _, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )

        self.assertEqual(code, 0, stderr)

    def test_check_rejects_staged_template_drift(self):
        self.assertEqual(self.prepare()[0], 0)
        template_path = self.root / "templates" / "release" / "manifest.template.json"
        template_path.write_text("{}\n", encoding="utf-8")
        self.run_git(
            "add",
            "VERSION",
            "SHA256SUMS",
            "manifest.json",
            "templates/release/manifest.template.json",
        )

        code, _, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )

        self.assertEqual(code, 1)
        self.assertIn("SHA256SUMS", stderr)


if __name__ == "__main__":
    unittest.main()
