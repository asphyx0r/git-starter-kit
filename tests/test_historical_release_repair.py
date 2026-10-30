import base64
import copy
import importlib.util
import io
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "tools/historical-release-repair.py"


def archive_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content)
    return output.getvalue()


class ReadOnlyAPI:
    def __init__(self, responses, downloads=None):
        self.responses = responses
        self.downloads = downloads or {}

    def get(self, path):
        if path not in self.responses:
            raise AssertionError(f"Unexpected API request: {path}")
        return copy.deepcopy(self.responses[path])

    def download(self, asset_id):
        if asset_id not in self.downloads:
            raise AssertionError(f"Unexpected asset download: {asset_id}")
        return self.downloads[asset_id]


class HistoricalRepairTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "historical repair driver is missing")
        spec = importlib.util.spec_from_file_location("historical_repair", SCRIPT)
        self.driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.driver)
        self.temporary = tempfile.TemporaryDirectory(prefix="repair-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def make_source(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "hello.txt").write_bytes(b"hello\n")
        (self.root / ".gitattributes").write_bytes(b"*.txt text eol=crlf\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.git("tag", "-a", "v2.0.1", "-m", "fixture tag")
        return self.git("rev-parse", "HEAD")

    def public_rules_fixture(self):
        self.make_source()
        (self.root / "AGENTS.md").write_bytes(b"# Official rules\n")
        self.git("add", "AGENTS.md")
        self.git("commit", "-qm", "official rule fixture")
        self.git("tag", "-a", "v1.42.0", "-m", "official rules")
        commit = self.git("rev-parse", "HEAD")
        tag_object = self.git("rev-parse", "v1.42.0")
        tree = self.git("rev-parse", "HEAD^{tree}")
        blob = self.git("rev-parse", "HEAD:AGENTS.md")
        tree_entries = []
        for line in self.git("ls-tree", "HEAD").splitlines():
            metadata, path = line.split("\t")
            mode, kind, object_id = metadata.split()
            tree_entries.append(
                {"path": path, "mode": mode, "type": kind, "sha": object_id}
            )
        prefix = "repos/asphyx0r/agent-coding-rules/git"
        responses = {
            f"{prefix}/ref/tags/v1.42.0": {
                "ref": "refs/tags/v1.42.0",
                "object": {"type": "tag", "sha": tag_object},
            },
            f"{prefix}/tags/{tag_object}": {
                "sha": tag_object,
                "object": {"type": "commit", "sha": commit},
            },
            f"{prefix}/commits/{commit}": {"sha": commit, "tree": {"sha": tree}},
            f"{prefix}/trees/{tree}": {
                "sha": tree,
                "truncated": False,
                "tree": tree_entries,
            },
            f"{prefix}/blobs/{blob}": {
                "sha": blob,
                "encoding": "base64",
                "content": base64.b64encode(b"# Official rules\n").decode(),
            },
        }
        return responses, commit, tag_object, tree, blob

    def test_public_rule_pin_follows_real_annotated_objects_and_rejects_tampering(self):
        responses, commit, tag_object, tree, blob = self.public_rules_fixture()
        metadata, files = self.driver.public_rules(
            ReadOnlyAPI(responses), "v1.42.0", commit, ["AGENTS.md"]
        )
        self.assertEqual(files, {"AGENTS.md": b"# Official rules\n"})
        self.assertEqual(metadata["tagObject"], tag_object)
        self.assertEqual(metadata["commit"], commit)
        prefix = "repos/asphyx0r/agent-coding-rules/git"
        rule_entry = next(
            entry
            for entry in responses[f"{prefix}/trees/{tree}"]["tree"]
            if entry["path"] == "AGENTS.md"
        )
        cases = [
            (f"{prefix}/ref/tags/v1.42.0", {"ref": "refs/tags/other"}),
            (f"{prefix}/tags/{tag_object}", {"sha": "0" * 40}),
            (
                f"{prefix}/tags/{tag_object}",
                {"object": {"type": "tag", "sha": tag_object}},
            ),
            (
                f"{prefix}/tags/{tag_object}",
                {"object": {"type": "commit", "sha": "0" * 40}},
            ),
            (f"{prefix}/commits/{commit}", {"sha": "0" * 40}),
            (f"{prefix}/trees/{tree}", {"sha": "0" * 40}),
            (f"{prefix}/trees/{tree}", {"truncated": True}),
            (f"{prefix}/trees/{tree}", {"tree": [rule_entry, rule_entry]}),
            (f"{prefix}/trees/{tree}", {"tree": [{**rule_entry, "mode": "120000"}]}),
            (f"{prefix}/blobs/{blob}", {"sha": "0" * 40}),
            (f"{prefix}/blobs/{blob}", {"encoding": "utf-8"}),
        ]
        for path, changed in cases:
            with self.subTest(path=path, change=changed):
                corrupted = copy.deepcopy(responses)
                corrupted[path].update(changed)
                with self.assertRaises(self.driver.RepairError):
                    self.driver.public_rules(
                        ReadOnlyAPI(corrupted), "v1.42.0", commit, ["AGENTS.md"]
                    )

    def test_public_rule_selection_rejects_unpinned_refs_and_unexpected_paths(self):
        for ref, commit, names in [
            ("latest", "a" * 40, ["AGENTS.md"]),
            ("v1.42.0", "moving-branch", ["AGENTS.md"]),
            ("v1.42.0", "a" * 40, []),
            ("v1.42.0", "a" * 40, ["AGENTS.md", "AGENTS.md"]),
            ("v1.42.0", "a" * 40, ["../AGENTS.md"]),
        ]:
            with (
                self.subTest(ref=ref, names=names),
                self.assertRaises(self.driver.RepairError),
            ):
                self.driver.public_rules(ReadOnlyAPI({}), ref, commit, names)

    def test_release_snapshot_rejects_corrupt_downloads_and_incomplete_reuse(self):
        name = "git-starter-kit-v2.0.1-with-agent-rules.zip"
        archive = archive_bytes({"hello": b"original bytes"})
        asset = {
            "id": 10,
            "name": name,
            "size": len(archive),
            "state": "uploaded",
            "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
        }
        release = {
            "id": 357402329,
            "tag_name": "v2.0.1",
            "draft": False,
            "prerelease": True,
            "published_at": "2026-01-01",
            "updated_at": "2026-01-02",
            "body": "Original notes",
            "assets": [asset],
        }
        endpoint = "repos/asphyx0r/git-starter-kit/releases/357402329"
        snapshot, assets, retained = self.driver.release_snapshot(
            ReadOnlyAPI({endpoint: release}, {10: archive}), "v2.0.1"
        )
        self.assertEqual(snapshot["body"], "Original notes")
        self.assertEqual(retained, {name: archive})
        self.assertEqual(assets[0]["sha256"], hashlib.sha256(archive).hexdigest())
        corruptions = [
            [],
            [asset, asset],
            [{**asset, "size": len(archive) + 1}],
            [{**asset, "digest": "sha256:" + "0" * 64}],
            [{**asset, "name": "sub/file.zip"}],
            [{**asset, "state": "new"}],
        ]
        for entries in corruptions:
            with (
                self.subTest(assets=entries),
                self.assertRaises(self.driver.RepairError),
            ):
                self.driver.release_snapshot(
                    ReadOnlyAPI(
                        {endpoint: {**release, "assets": entries}}, {10: archive}
                    ),
                    "v2.0.1",
                )
        for fields in [
            {"id": 1},
            {"tag_name": "v2.1.0"},
            {"draft": "false"},
            {"prerelease": "true"},
        ]:
            with (
                self.subTest(fields=fields),
                self.assertRaisesRegex(self.driver.RepairError, "identity"),
            ):
                self.driver.release_snapshot(
                    ReadOnlyAPI({endpoint: {**release, **fields}}), "v2.0.1"
                )

    def test_absence_verification_rejects_malformed_and_repeated_release_pages(self):
        endpoint = "repos/asphyx0r/git-starter-kit/releases?per_page=100&page=1"
        for records in [
            {"message": "forbidden"},
            [{"id": 1, "tag_name": "other"}] * 101,
            [{"id": 1, "tag_name": "other"}, {"id": 1, "tag_name": "other"}],
        ]:
            with (
                self.subTest(records=records),
                self.assertRaises(self.driver.RepairError),
            ):
                self.driver.release_snapshot(ReadOnlyAPI({endpoint: records}), "v1.7.3")
        self.assertEqual(
            self.driver.release_snapshot(ReadOnlyAPI({endpoint: []}), "v1.7.3"),
            (None, [], {}),
        )

    def test_archive_limits_and_entry_types_reject_hostile_packages(self):
        with self.assertRaises(self.driver.RepairError):
            self.driver.read_archive(b"not a ZIP")
        with self.assertRaisesRegex(self.driver.RepairError, "path collision"):
            self.driver.read_archive(archive_bytes({"file": b"x", "file/child": b"y"}))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, "../outside")
        with self.assertRaisesRegex(self.driver.RepairError, "Unsupported"):
            self.driver.read_archive(output.getvalue())
        compressed = io.BytesIO()
        with zipfile.ZipFile(
            compressed, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr("large", b"a" * 4096)
        with patch.object(
            self.driver, "MAX_ARCHIVE_BYTES", len(compressed.getvalue()) + 1
        ):
            with self.assertRaisesRegex(self.driver.RepairError, "Expanded"):
                self.driver.read_archive(compressed.getvalue())
            with self.assertRaisesRegex(self.driver.RepairError, "Archive exceeds"):
                self.driver.read_archive(b"x" * (len(compressed.getvalue()) + 2))

    def test_archive_directory_records_are_checked_without_entering_file_inventory(
        self,
    ):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("folder/", b"")
            archive.writestr("folder/file", b"contents")
        self.assertEqual(
            self.driver.read_archive(output.getvalue()), {"folder/file": b"contents"}
        )

    def test_tag_boundary_refuses_unallowlisted_and_lightweight_tags(self):
        with self.assertRaisesRegex(self.driver.RepairError, "allowlist"):
            self.driver.tag_identity(self.root, "v999.0.0")
        commit = self.make_source()
        self.git("tag", "-d", "v2.0.1")
        self.git("tag", "v2.0.1", commit)
        with patch.dict(self.driver.TAGS, {"v2.0.1": commit}):
            with self.assertRaisesRegex(self.driver.RepairError, "annotated"):
                self.driver.tag_identity(self.root, "v2.0.1")

    def test_native_command_failures_are_reported_without_usable_stdout(self):
        with self.assertRaisesRegex(self.driver.RepairError, "failed"):
            self.driver.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "import sys; print('incomplete'); sys.exit(4)",
                ]
            )
        with self.assertRaisesRegex(self.driver.RepairError, "Unable to run"):
            self.driver.run([str(self.root / "missing-native-command")])

    def test_read_only_api_preserves_binary_assets_and_checks_http_failures(self):
        binary = archive_bytes({"payload": b"\0\xff\0"})

        def network(command, **options):
            self.assertEqual(command[:4], ["gh", "api", "--method", "GET"])
            if command[-1] == "repos/asphyx0r/git-starter-kit/releases/latest":
                return subprocess.CompletedProcess(
                    command, 0, b'{"id":100,"tag_name":"v3.0.0"}', b""
                )
            if command[-1] == "repos/asphyx0r/git-starter-kit/releases/assets/10":
                self.assertIn("Accept: application/octet-stream", command)
                return subprocess.CompletedProcess(command, 0, binary, b"")
            return subprocess.CompletedProcess(command, 1, b"", b"HTTP 403: forbidden")

        with patch.object(self.driver.subprocess, "run", side_effect=network):
            api = self.driver.PublicAPI()
            self.assertEqual(
                api.get("repos/asphyx0r/git-starter-kit/releases/latest"),
                {"id": 100, "tag_name": "v3.0.0"},
            )
            self.assertEqual(api.download(10), binary)
            with self.assertRaisesRegex(self.driver.RepairError, "403"):
                api.get("repos/asphyx0r/git-starter-kit/releases/forbidden")

    def test_rejects_unsafe_and_duplicate_archive_paths(self):
        for name in ["../escape", "/absolute", "a//b", "a/./b", "C:/drive"]:
            with self.subTest(name=name), self.assertRaises(self.driver.RepairError):
                self.driver.read_archive(archive_bytes({name: b"x"}))
        with self.assertRaises(self.driver.RepairError):
            self.driver.read_archive(
                archive_bytes({"a/b": b"x"}).replace(b"a/b", b"a\\b")
            )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("A.txt", b"a")
            archive.writestr("a.txt", b"b")
        with self.assertRaisesRegex(self.driver.RepairError, "duplicate|collision"):
            self.driver.read_archive(output.getvalue())

    def test_tag_identity_uses_annotated_object_and_refuses_changed_commit(self):
        commit = self.make_source()
        with patch.dict(self.driver.TAGS, {"v2.0.1": commit}):
            identity = self.driver.tag_identity(self.root, "v2.0.1")
            self.assertEqual(identity["commit"], commit)
            self.assertEqual(identity["tagObject"], self.git("rev-parse", "v2.0.1"))
            self.assertNotEqual(identity["tagObject"], commit)
            (self.root / "hello.txt").write_bytes(b"changed\n")
            self.git("add", ".")
            self.git("commit", "-qm", "changed")
            self.git("tag", "-fa", "v2.0.1", "-m", "changed tag")
            with self.assertRaisesRegex(self.driver.RepairError, "commit"):
                self.driver.tag_identity(self.root, "v2.0.1")

    def test_source_mapping_applies_git_eol_and_rejects_missing_extra_and_changed(self):
        commit = self.make_source()
        expected = self.driver.source_files(self.root, commit)
        self.assertEqual(expected["hello.txt"][1], b"hello\r\n")
        actual = {path: content for path, (_, content) in expected.items()}
        records = self.driver.map_source_files(actual, expected, {})
        self.assertEqual({row["path"] for row in records}, set(actual))
        for changed in [
            {"hello.txt": b"hello\r\n"},
            {**actual, "extra.txt": b"extra"},
            {**actual, "hello.txt": b"wrong"},
        ]:
            with (
                self.subTest(files=set(changed)),
                self.assertRaises(self.driver.RepairError),
            ):
                self.driver.map_source_files(changed, expected, {})

    def test_internal_manifest_validates_entries_before_v210_hidden_supplement(self):
        files = {"normal.txt": b"normal", ".hidden": b"hidden"}
        files["_starter-kit-files.json"] = json.dumps(
            {
                "files": [
                    {
                        "path": "normal.txt",
                        "sha256": self.driver.digest(b"normal"),
                        "mode": "100644",
                    }
                ]
            }
        ).encode()
        self.assertEqual(self.driver.validate_inventory(files, "v2.1.0"), [".hidden"])
        with self.assertRaisesRegex(self.driver.RepairError, "coverage|missing"):
            self.driver.validate_inventory(files, "v2.2.0")
        files["normal.txt"] = b"tampered"
        with self.assertRaisesRegex(self.driver.RepairError, "digest"):
            self.driver.validate_inventory(files, "v2.1.0")
        files["normal.txt"] = b"normal"
        files["other.txt"] = b"unexplained omission"
        with self.assertRaisesRegex(self.driver.RepairError, "hidden|omission"):
            self.driver.validate_inventory(files, "v2.1.0")

    def test_checksums_require_exact_archive_coverage(self):
        archives = {"one.zip": b"one", "two.zip": b"two"}
        sums = b"".join(
            f"{self.driver.digest(content)}  {name}\n".encode()
            for name, content in sorted(archives.items())
        )
        self.driver.validate_checksums(sums, archives)
        for broken in [
            sums.splitlines(keepends=True)[0],
            sums + sums,
            sums.replace(b"one.zip", b"bad.zip"),
        ]:
            with self.assertRaises(self.driver.RepairError):
                self.driver.validate_checksums(broken, archives)

    def test_generated_repository_document_validates_paths_independently_of_locale_sort(
        self,
    ):
        files = {"A": b"a", "b": b"b", "docs/repository-files.md": b""}
        header = "# Inventory"
        for paths in [
            ["b", "A", "docs/repository-files.md"],
            ["A", "b", "docs/repository-files.md"],
        ]:
            files["docs/repository-files.md"] = (
                header + "\n\n```text\n" + "\n".join(paths) + "\n```\n"
            ).encode()
            self.driver.validate_inventory_document(files, header)
        for paths in [
            ["A", "b"],
            ["A", "A", "b", "docs/repository-files.md"],
            ["A", "b", "unexpected"],
        ]:
            files["docs/repository-files.md"] = (
                header + "\n\n```text\n" + "\n".join(paths) + "\n```\n"
            ).encode()
            with self.assertRaises(self.driver.RepairError):
                self.driver.validate_inventory_document(files, header)

    def test_consumer_state_requires_complete_unique_paths_and_correct_metadata(self):
        record = {
            "path": "hook",
            "sha256": hashlib.sha256(b"hook\n").hexdigest(),
            "canonicalSha256": hashlib.sha256(b"hook\n").hexdigest(),
            "contentKind": "text",
            "mode": "100755",
        }
        state = {
            "source": {"ref": "v2.8.0"},
            "current": {"ref": "v2.8.0"},
            "files": [record],
        }
        files = {
            "hook": b"hook\n",
            "starter-kit-manifest.json": json.dumps(state).encode(),
        }
        self.driver.validate_consumer_inventory(files, "v2.8.0", {"hook": "100755"})
        for records in [
            [],
            [record, record],
            [{**record, "mode": "100644"}],
            [{**record, "canonicalSha256": "0" * 64}],
        ]:
            with self.subTest(records=records):
                state["files"] = records
                files["starter-kit-manifest.json"] = json.dumps(state).encode()
                with self.assertRaises(self.driver.RepairError):
                    self.driver.validate_consumer_inventory(
                        files, "v2.8.0", {"hook": "100755"}
                    )

    def test_qualification_is_identity_only_and_local_is_unqualified(self):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GITHUB_")
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertIsNone(self.driver.qualification())
        with patch.dict(
            os.environ,
            {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": "a" * 40},
        ):
            self.assertEqual(
                self.driver.qualification(),
                {"runId": 123, "runAttempt": 2, "sourceSha": "a" * 40},
            )

    def test_historical_process_environment_has_no_credentials_or_private_config(self):
        with patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "__CHANGE_ME__",
                "GH_TOKEN": "__CHANGE_ME__",
                "GH_CONFIG_DIR": "private-config",
                "GIT_CONFIG_COUNT": "1",
                "ACTIONS_RUNTIME_TOKEN": "__CHANGE_ME__",
                "OTHER_SECRET": "__CHANGE_ME__",
            },
        ):
            environment = self.driver.tokenless_environment(self.root)
        for name in (
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "ACTIONS_RUNTIME_TOKEN",
            "OTHER_SECRET",
        ):
            self.assertNotIn(name, environment)
        self.assertNotIn("GIT_CONFIG_COUNT", environment)
        self.assertEqual(Path(environment["GH_CONFIG_DIR"]).parent, self.root / "home")

    def test_prepare_refuses_preexisting_output_without_any_source_or_network_change(
        self,
    ):
        output = self.root / "existing"
        output.mkdir()
        marker = output / "keep"
        marker.write_bytes(b"keep")
        with self.assertRaisesRegex(self.driver.RepairError, "preexisting"):
            self.driver.prepare(self.root, "v2.0.1", output)
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_historical_recipe_temp_stays_short_when_bundle_path_is_deep(self):
        self.make_source()
        tools = self.root / "tools"
        tools.mkdir()
        (tools / "build-release-package.ps1").write_text(
            "param($RepositoryRoot,$OutputDirectory,$PackageName,$RepositoryRef,$RepositorySlug,"
            "$StarterKitRef,$StarterKitCommit,$AgentRulesRef)\n"
            '[IO.File]::WriteAllText((Join-Path $OutputDirectory "probe.json"),'
            "(@{temp=$env:TEMP; checkout=$RepositoryRoot} | ConvertTo-Json))\n"
            'throw "intentional probe completion"\n',
            encoding="utf-8",
        )
        self.git("add", ".")
        self.git("commit", "-qm", "probe recipe")
        commit = self.git("rev-parse", "HEAD")
        output = self.root / "deep" / ("long-output-" * 8)
        output.mkdir(parents=True)
        with patch.dict(self.driver.TAGS, {"v2.8.0": commit}):
            with self.assertRaisesRegex(self.driver.RepairError, "intentional probe"):
                self.driver.build_archives(self.root, "v2.8.0", output, {}, {})
        probe = json.loads((output / "probe.json").read_bytes())
        work = Path(probe["temp"])
        self.assertEqual(work.parent, self.root)
        self.assertLessEqual(len(work.name), 16)
        self.assertFalse(
            work.exists(),
            "historical work directory must be removed after recipe failure",
        )

    def test_new_package_rejects_zip_that_loses_source_executable_mode(self):
        self.make_source()
        hook = self.root / ".githooks" / "pre-commit"
        hook.parent.mkdir()
        hook.write_bytes(b"#!/bin/sh\nexit 0\n")
        rules = {name: f"# {name}\n".encode() for name in self.driver.RULE_FILES}
        for name, content in rules.items():
            (self.root / name).write_bytes(content)
        self.git("add", ".")
        self.git("update-index", "--chmod=+x", ".githooks/pre-commit")
        self.git("commit", "-qm", "executable hook")
        commit = self.git("rev-parse", "HEAD")
        self.git("tag", "-a", "v1.7.3", "-m", "fixture")
        files = {
            name: content
            for name, (_, content) in self.driver.source_files(
                self.root, commit
            ).items()
        }
        files[self.driver.PROVENANCE] = json.dumps(
            {
                "starterKit": {"ref": "v1.7.3", "commit": commit},
                "agentRules": {
                    "repository": self.driver.RULES_REPOSITORY,
                    "ref": "v1.42.0",
                    "commit": "a" * 40,
                    "files": list(rules),
                },
            }
        ).encode()
        upstream = {
            "ref": "v1.42.0",
            "commit": "a" * 40,
            "blobs": {name: "b" * 40 for name in rules},
        }
        with patch.dict(self.driver.TAGS, {"v1.7.3": commit}):
            with self.assertRaisesRegex(self.driver.RepairError, "mode"):
                self.driver.inspect_package(
                    self.root, "v1.7.3", archive_bytes(files), rules, upstream
                )

    def test_v211_toolkit_requires_shared_process_runner_even_when_archive_omits_it(
        self,
    ):
        files = self.toolkit_fixture("v2.11.0")
        del files["process_runner.py"]
        with self.assertRaisesRegex(self.driver.RepairError, "process_runner.py"):
            self.driver.inspect_toolkit(
                SCRIPT.parents[1],
                "v2.11.0",
                archive_bytes(files),
                "nested.zip",
                b"nested content",
            )

    def toolkit_fixture(self, tag):
        source = self.driver.source_files(SCRIPT.parents[1], self.driver.TAGS[tag])
        files = {"starter-kit-upgrade.py": source["tools/starter-kit-upgrade.py"][1]}
        files.update(
            {
                path.removeprefix("tools/"): content
                for path, (_, content) in source.items()
                if path.startswith("tools/starter_kit_upgrade/")
                and path.endswith(".py")
            }
        )
        members = "- `starter-kit-upgrade.py`, the cumulative upgrade builder and guarded applier;\n"
        journal = ""
        plan_option = ""
        if tag in {"v2.8.0", "v2.11.0"}:
            members = (
                "- `starter-kit-upgrade.py`, the executable compatibility facade;\n"
                "- `starter_kit_upgrade/`, the updater implementation package;\n"
            )
            journal = (
                "\nEvery non-dry-run command writes a detailed execution journal below `logs/` in\n"
                "the current directory. The log filename identifies the target release and run\n"
                "timestamp. Dry-run, help, version, and argument-parser exits do not write logs.\n"
            )
        if tag == "v2.11.0":
            members += (
                "- `process_runner.py`, the shared bounded native-process helper;\n"
            )
            files["process_runner.py"] = source["tools/process_runner.py"][1]
            plan_option = "--dry-run "
        files["packages/nested.zip"] = b"nested content"
        files["README.md"] = (
            "# Starter Kit Upgrade Toolkit\n\nThis toolkit contains:\n\n"
            + members
            + "- `packages/nested.zip`, the new complete starter-kit package.\n\n"
            "Build a cumulative package by supplying the exact full package used to\n"
            "initialize the target:\n\n```text\n"
            "python starter-kit-upgrade.py build --base-package BASE.zip --new-package packages/nested.zip --output UPGRADE.zip\n"
            "```\n\nInspect a target before writing:\n\n```text\n"
            f"python starter-kit-upgrade.py {plan_option}plan --upgrade-package UPGRADE.zip --target REPOSITORY\n"
            "```\n\nApplication additionally requires a clean repository, valid provenance, no\n"
            "conflicts, and an existing backup directory outside the target.\n"
            + journal
        ).encode()
        return files

    def test_toolkit_accepts_exact_historical_readme_profiles(self):
        for tag in ["v2.1.0", "v2.2.0", "v2.8.0", "v2.11.0"]:
            with self.subTest(tag=tag):
                result = self.driver.inspect_toolkit(
                    SCRIPT.parents[1],
                    tag,
                    archive_bytes(self.toolkit_fixture(tag)),
                    "nested.zip",
                    b"nested content",
                )
                readme = next(
                    row for row in result["files"] if row["path"] == "README.md"
                )
                recipe = (
                    "tools/starter-kit-upgrade.py"
                    if tag in {"v2.1.0", "v2.2.0"}
                    else "tools/starter_kit_upgrade/archive.py"
                )
                self.assertEqual(readme["source"]["recipe"], recipe)

    def test_toolkit_rejects_truncated_or_changed_historical_readme(self):
        for tag in ["v2.1.0", "v2.2.0", "v2.8.0", "v2.11.0"]:
            files = self.toolkit_fixture(tag)
            readme = files["README.md"]
            for invalid in [
                b"nested.zip\n",
                readme.replace(b"--target REPOSITORY", b"--target OTHER"),
                readme.replace(b"\n", b"\r\n"),
            ]:
                with (
                    self.subTest(tag=tag, readme=invalid),
                    self.assertRaisesRegex(self.driver.RepairError, "README"),
                ):
                    self.driver.inspect_toolkit(
                        SCRIPT.parents[1],
                        tag,
                        archive_bytes({**files, "README.md": invalid}),
                        "nested.zip",
                        b"nested content",
                    )

    def test_upstream_rejects_blob_bytes_not_matching_public_object(self):
        class PublicAPI:
            def get(self, path):
                if "/git/ref/" in path:
                    return {
                        "ref": "refs/tags/v1.42.0",
                        "object": {"type": "commit", "sha": "a" * 40},
                    }
                if "/git/commits/" in path:
                    return {"sha": "a" * 40, "tree": {"sha": "b" * 40}}
                if "/git/trees/" in path:
                    return {
                        "sha": "b" * 40,
                        "truncated": False,
                        "tree": [
                            {
                                "path": "AGENTS.md",
                                "type": "blob",
                                "mode": "100644",
                                "sha": "c" * 40,
                            }
                        ],
                    }
                return {"sha": "c" * 40, "encoding": "base64", "content": "d3Jvbmc="}

        with self.assertRaisesRegex(self.driver.RepairError, "blob"):
            self.driver.public_rules(PublicAPI(), "v1.42.0", "a" * 40, ["AGENTS.md"])

    def test_draft_release_is_resolved_by_known_id_even_when_tag_lookup_returns_404(
        self,
    ):
        driver = self.driver
        draft = {
            "id": 383049548,
            "tag_name": "v2.8.0",
            "draft": True,
            "prerelease": True,
            "published_at": "2026-09-04",
            "updated_at": "2026-09-24",
            "body": "Original draft notes",
            "assets": [],
        }

        class DraftAPI(driver.PublicAPI):
            def get(self, path, **kwargs):
                if "/releases/tags/" in path:
                    return None
                if path.endswith("/releases/383049548"):
                    return draft
                raise AssertionError(path)

        snapshot, assets, content = driver.release_snapshot(DraftAPI(), "v2.8.0")
        self.assertIsNotNone(
            snapshot, "draft 404 by tag must never mean absent release"
        )
        self.assertEqual(snapshot["id"], 383049548)
        self.assertEqual(snapshot["body"], "Original draft notes")
        self.assertTrue(snapshot["draft"])
        self.assertEqual(assets, [])
        self.assertEqual(content, {})

    def test_absent_release_profile_checks_all_pages_for_unexpected_draft(self):
        driver = self.driver

        class DraftAPI(driver.PublicAPI):
            def get(self, path, **kwargs):
                if "/releases/tags/" in path:
                    return None
                if path.endswith("page=1"):
                    return [{"id": value, "tag_name": "other"} for value in range(100)]
                if path.endswith("page=2"):
                    return [{"id": 123, "tag_name": "v1.7.3", "draft": True}]
                raise AssertionError(path)

        with self.assertRaisesRegex(driver.RepairError, "already|[Uu]nexpected"):
            driver.release_snapshot(DraftAPI(), "v1.7.3")

    def test_verify_rejects_absent_baseline_for_known_draft_before_source_reads(self):
        (self.root / "candidate.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "repository": self.driver.REPOSITORY,
                    "tag": "v2.8.0",
                    "releaseBefore": None,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(self.driver.RepairError, "release ID"):
            self.driver.verify(self.root, self.root)

    def test_prepare_reuses_existing_zip_and_verify_detects_changes_without_writes(
        self,
    ):
        self.make_source()
        rule_names = [
            name for name in self.driver.RULE_FILES if name != "BRANCH_RULES.md"
        ]
        blobs = {}
        for name in rule_names:
            content = f"# {name}\n".encode()
            (self.root / name).write_bytes(content)
            object_id = hashlib.sha1(
                f"blob {len(content)}\0".encode() + content
            ).hexdigest()
            blobs[object_id] = content
        provenance = {
            "starterKit": {"ref": "v2.0.1", "commit": None},
            "agentRules": {
                "repository": "https://github.com/asphyx0r/agent-coding-rules",
                "ref": "v1.42.0",
                "commit": "a" * 40,
                "files": rule_names,
            },
        }
        self.git("add", ".")
        self.git("commit", "-qm", "rules")
        commit = self.git("rev-parse", "HEAD")
        self.git("tag", "-fa", "v2.0.1", "-m", "fixture")
        provenance["starterKit"]["commit"] = commit
        files = {
            path: content
            for path, (_, content) in self.driver.source_files(
                self.root, commit
            ).items()
        }
        files[self.driver.PROVENANCE] = json.dumps(provenance).encode()
        zip_content = archive_bytes(files)
        release = {
            "id": 357402329,
            "tag_name": "v2.0.1",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-01-01",
            "updated_at": "2026-01-02",
            "body": "Original notes",
            "assets": [
                {
                    "id": 10,
                    "name": "git-starter-kit-v2.0.1-with-agent-rules.zip",
                    "size": len(zip_content),
                    "state": "uploaded",
                    "digest": None,
                }
            ],
        }

        class PublicAPI:
            def get(self, path):
                if path.endswith("releases/latest"):
                    return {"id": 100, "tag_name": "v3.0.0"}
                if "/releases/tags/" in path or path.endswith("/releases/357402329"):
                    return release
                if "/git/ref/" in path:
                    return {
                        "ref": "refs/tags/v1.42.0",
                        "object": {"type": "commit", "sha": "a" * 40},
                    }
                if "/git/commits/" in path:
                    return {"sha": "a" * 40, "tree": {"sha": "b" * 40}}
                if "/git/trees/" in path:
                    return {
                        "sha": "b" * 40,
                        "truncated": False,
                        "tree": [
                            {
                                "path": name,
                                "type": "blob",
                                "mode": "100644",
                                "sha": object_id,
                            }
                            for name, object_id in zip(rule_names, blobs, strict=True)
                        ],
                    }
                object_id = path.rsplit("/", 1)[-1]
                import base64

                return {
                    "sha": object_id,
                    "encoding": "base64",
                    "content": base64.b64encode(blobs[object_id]).decode(),
                }

            def download(self, asset_id):
                return zip_content

        bundle = self.root / "bundle"
        with patch.dict(self.driver.TAGS, {"v2.0.1": commit}):
            candidate = self.driver.prepare(
                self.root, "v2.0.1", bundle, api=PublicAPI()
            )
            self.assertEqual(
                [row["name"] for row in candidate["payload"]],
                ["historical-repair-proof.json"],
            )
            self.assertEqual(candidate["assetsBefore"][0]["id"], 10)
            self.assertEqual(
                (bundle / "retained" / release["assets"][0]["name"]).read_bytes(),
                zip_content,
            )
            before = {
                path.relative_to(bundle): path.read_bytes()
                for path in bundle.rglob("*")
                if path.is_file()
            }
            self.driver.verify(self.root, bundle, api=PublicAPI())
            self.assertEqual(
                before,
                {
                    path.relative_to(bundle): path.read_bytes()
                    for path in bundle.rglob("*")
                    if path.is_file()
                },
            )
            retained = bundle / "retained" / release["assets"][0]["name"]
            retained.unlink()
            retained.parent.rmdir()
            self.driver.verify(self.root, bundle, api=PublicAPI())
            self.assertFalse(retained.parent.exists())
            unexpected = bundle / "payload" / "unexpected"
            unexpected.write_bytes(b"unexpected")
            with self.assertRaisesRegex(self.driver.RepairError, "coverage"):
                self.driver.verify(self.root, bundle, api=PublicAPI())
            unexpected.unlink()
            proof = bundle / "payload" / "historical-repair-proof.json"
            proof_before = proof.read_bytes()
            candidate_path = bundle / "candidate.json"
            candidate_before = candidate_path.read_bytes()
            forged = json.loads(proof_before)
            forged["transformations"] = [{"operation": "invented transformation"}]
            proof.write_bytes(json.dumps(forged).encode())
            forged_candidate = json.loads(candidate_before)
            forged_candidate["payload"][0].update(
                {
                    "sha256": self.driver.digest(proof.read_bytes()),
                    "size": proof.stat().st_size,
                }
            )
            candidate_path.write_bytes(json.dumps(forged_candidate).encode())
            with self.assertRaisesRegex(self.driver.RepairError, "transformation"):
                self.driver.verify(self.root, bundle, api=PublicAPI())
            proof.write_bytes(proof_before)
            candidate_path.write_bytes(candidate_before)
            proof.write_bytes(proof.read_bytes() + b" ")
            with self.assertRaisesRegex(self.driver.RepairError, "payload|digest"):
                self.driver.verify(self.root, bundle, api=PublicAPI())


if __name__ == "__main__":
    unittest.main()
