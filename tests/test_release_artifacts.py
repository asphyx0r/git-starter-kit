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

    def test_rejects_unsafe_inputs_and_malformed_git_protocol_records(self):
        invalid_paths = ("", "../escape", "/absolute", "bad\\path", "bad\npath")
        for value in invalid_paths:
            with (
                self.subTest(path=value),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.validate_relative_path(value)

        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.require_repository_root(Path(self.temporary.name) / "missing")
        nested = self.root / "nested"
        nested.mkdir()
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.require_repository_root(nested)

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
                patch.object(ARTIFACTS.subprocess, "run", return_value=result),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.read_blobs(self.root, [("file", "100644", "abc")])
        self.assertEqual(ARTIFACTS.read_blobs(self.root, []), {})

        invalid_index_records = (
            b"100644 abc 1\tfile\0",
            b"100600 abc 0\tfile\0",
            b"100644 abc 0\t\xff\0",
        )
        for output in invalid_index_records:
            with (
                self.subTest(index=output),
                patch.object(ARTIFACTS, "run_git", return_value=output),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.index_records(self.root)
        with patch.object(
            ARTIFACTS,
            "run_git",
            return_value=b"160000 abc 0\tsubmodule\0",
        ):
            self.assertEqual(ARTIFACTS.index_records(self.root), [])

        invalid_tree_records = (
            b"100600 blob abc\tfile\0",
            b"100644 blob abc\t\xff\0",
        )
        for output in invalid_tree_records:
            with (
                self.subTest(tree=output),
                patch.object(ARTIFACTS, "run_git", return_value=output),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.tree_records(self.root, "HEAD")
        with patch.object(
            ARTIFACTS,
            "run_git",
            return_value=b"160000 commit abc\tsubmodule\0",
        ):
            self.assertEqual(ARTIFACTS.tree_records(self.root, "HEAD"), [])

    def test_validates_release_metadata_and_template_boundaries(self):
        self.assertEqual(ARTIFACTS.line_ending("one\r\ntwo\r\n"), "CRLF")
        self.assertEqual(ARTIFACTS.line_ending("one\ntwo\n"), "LF")
        self.assertEqual(ARTIFACTS.line_ending("one\rtwo\r"), "CR")
        self.assertIsNone(ARTIFACTS.line_ending("one\r\ntwo\n"))
        self.assertIsNone(ARTIFACTS.line_ending("one"))
        self.assertEqual(
            ARTIFACTS.file_record("binary", "120000", b"\xff")["file_type"],
            "binary",
        )
        self.assertEqual(
            ARTIFACTS.file_record("nul", "100644", b"a\0b")["file_type"],
            "binary",
        )

        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.release_payload({}, "1.2.3", False)
        files, checksums = ARTIFACTS.release_payload({}, "1.2.3", True)
        self.assertEqual(files[0]["relative_path"], "VERSION")
        self.assertIn(b"  VERSION\n", checksums)

        invalid_dates = ("2026-08-18", "2026-02-30T12:00:00Z")
        for value in invalid_dates:
            with (
                self.subTest(date=value),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.parse_release_date(value)
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.version_from_ref("1.2.3")

        invalid_json = (b"\xff", b"{", b"[]")
        for content in invalid_json:
            with (
                self.subTest(json=content),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.parse_json_object(content, "test JSON")
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.load_json_object(
                Path(self.temporary.name) / "missing.json", "test JSON"
            )
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.load_metadata(self.root, self.root / "metadata.json")

        invalid_metadata = (
            {"unexpected": True},
            {**json.loads(self.metadata_path.read_text("utf-8")), "update": {}},
            {**json.loads(self.metadata_path.read_text("utf-8")), "artifact": {}},
            {
                **json.loads(self.metadata_path.read_text("utf-8")),
                "artifact": {"id": "source", "target": {}},
            },
            {**json.loads(self.metadata_path.read_text("utf-8")), "metadata": {}},
        )
        for index, value in enumerate(invalid_metadata):
            candidate = Path(self.temporary.name) / f"invalid-{index}.json"
            candidate.write_text(json.dumps(value), encoding="utf-8")
            with (
                self.subTest(metadata=index),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.load_metadata(self.root, candidate)

        for content in (b"{", b"[]"):
            with (
                self.subTest(template=content),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.parse_template(content, "test template")
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.load_template(Path(self.temporary.name) / "missing-template")
        self.assertEqual(
            ARTIFACTS.render_value({"nested": ["{{value}}", 3]}, {"value": "resolved"}),
            {"nested": ["resolved", 3]},
        )
        with self.assertRaises(ARTIFACTS.ReleaseArtifactError):
            ARTIFACTS.render_value("{{missing}}", {})

        metadata = json.loads(self.metadata_path.read_text("utf-8"))
        invalid_templates = (
            b'{"artifacts": []}',
            b'{"artifacts": ["invalid"]}',
            b'{"artifacts": [{"files": []}]}',
        )
        for content in invalid_templates:
            with (
                self.subTest(build_template=content),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.build_manifest(
                    self.root,
                    metadata,
                    "1.2.3",
                    "2026-08-18T12:00:00Z",
                    [],
                    b"",
                    content,
                )

    def test_confirmation_and_template_rendering_fail_closed(self):
        with (
            patch.object(ARTIFACTS.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="yes"),
        ):
            ARTIFACTS.confirm_write(False)
        with (
            patch.object(ARTIFACTS.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="no"),
            self.assertRaises(ARTIFACTS.ReleaseArtifactError),
        ):
            ARTIFACTS.confirm_write(False)

        metadata = json.loads(self.metadata_path.read_text("utf-8"))
        invalid_render_templates = (
            b'{"artifacts": [{"files": ["{{file-relative-path}}"]}]}',
            b'{"unresolved": "prefix {{unknown}}", "artifacts": [{"files": [{}]}]}',
        )
        file_record = ARTIFACTS.file_record("VERSION", "100644", b"1.2.3\n")
        for content in invalid_render_templates:
            with (
                self.subTest(render_template=content),
                self.assertRaises(ARTIFACTS.ReleaseArtifactError),
            ):
                ARTIFACTS.build_manifest(
                    self.root,
                    metadata,
                    "1.2.3",
                    "2026-08-18T12:00:00Z",
                    [file_record],
                    b"checksum",
                    content,
                )

        for returncode, expected in ((0, True), (1, False)):
            result = subprocess.CompletedProcess([], returncode, b"", b"")
            with (
                self.subTest(returncode=returncode),
                patch.object(ARTIFACTS.subprocess, "run", return_value=result),
            ):
                self.assertEqual(
                    ARTIFACTS.ref_exists(self.root, "refs/tags/v1.2.3"), expected
                )

    def test_cli_reports_missing_content_and_preserves_verbose_failures(self):
        code, _, stderr = self.run_main(
            "check", "--index", "--repository-root", str(self.root)
        )
        self.assertEqual(code, 1)
        self.assertIn("does not contain manifest.json", stderr)

        with (
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
            self.assertRaises(ARTIFACTS.ReleaseArtifactError),
        ):
            ARTIFACTS.main(
                [
                    "--verbose",
                    "--force",
                    "prepare",
                    "--release-ref",
                    "invalid",
                    "--release-date",
                    "2026-08-18T12:00:00Z",
                    "--metadata-file",
                    str(self.metadata_path),
                    "--repository-root",
                    str(self.root),
                ]
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
        paths = [item["relative_path"] for item in manifest["artifacts"][0]["files"]]
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
