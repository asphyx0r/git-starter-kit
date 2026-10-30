import base64
import copy
import importlib.util
import io
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
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

    def draft_observation(self):
        return {
            "schemaVersion": 1,
            "repository": "asphyx0r/git-starter-kit",
            "method": "GET",
            "endpoint": "repos/asphyx0r/git-starter-kit/releases/383049548",
            "observedAt": "2026-10-30T10:00:00Z",
            "provenance": "operator-authenticated-get",
            "releaseBefore": {
                "id": 383049548,
                "tag_name": "v2.8.0",
                "draft": True,
                "prerelease": True,
                "published_at": None,
                "updated_at": "2026-09-24T22:21:37Z",
                "body": "Original operator-observed notes",
            },
            "assetsBefore": [],
        }

    def test_draft_observation_schema_is_closed_and_preserves_nullable_api_values(self):
        self.assertTrue(
            hasattr(self.driver, "validate_release_observation"),
            "closed observation validator is missing",
        )
        observation = self.draft_observation()
        self.driver.validate_release_observation(observation, "v2.8.0")
        nullable = copy.deepcopy(observation)
        nullable["releaseBefore"].update(
            {"body": None, "published_at": "2026-09-04T22:39:48Z"}
        )
        self.driver.validate_release_observation(nullable, "v2.8.0")
        self.assertIsNone(nullable["releaseBefore"]["body"])
        self.assertEqual(
            observation["releaseBefore"]["body"], "Original operator-observed notes"
        )
        invalid = []
        for changed in [
            {"schemaVersion": True},
            {"schemaVersion": 2},
            {"repository": "other/repo"},
            {"method": "POST"},
            {"endpoint": "repos/asphyx0r/git-starter-kit/releases/388017021"},
            {"provenance": "ci-live-get"},
            {"observedAt": "2026-02-30T10:00:00Z"},
            {"observedAt": "2026-10-30T10:00:00+01:00"},
            {"observedAt": None},
            {"assetsBefore": [{}]},
            {"assetsBefore": {}},
            {"unexpected": 1},
        ]:
            invalid.append({**copy.deepcopy(observation), **changed})
        missing = copy.deepcopy(observation)
        del missing["observedAt"]
        invalid.append(missing)
        for changed in [
            {"id": 388017021},
            {"id": True},
            {"tag_name": "v2.11.0"},
            {"draft": False},
            {"draft": 1},
            {"prerelease": 1},
            {"published_at": 1},
            {"updated_at": None},
            {"body": {}},
            {"unexpected": 1},
        ]:
            changed_observation = copy.deepcopy(observation)
            changed_observation["releaseBefore"].update(changed)
            invalid.append(changed_observation)
        for value in invalid + [None, [], {**observation, "releaseBefore": None}]:
            with (
                self.subTest(observation=value),
                self.assertRaises(self.driver.RepairError),
            ):
                self.driver.validate_release_observation(value, "v2.8.0")
        with self.assertRaises(self.driver.RepairError):
            self.driver.validate_release_observation(observation, "v2.11.0")

    def test_observe_draft_cli_captures_real_get_without_printing_body_or_overwriting(
        self,
    ):
        output = self.root / "draft.json"
        observation = self.draft_observation()
        release = {**observation["releaseBefore"], "assets": []}

        def network(command, **options):
            self.assertEqual(command[:4], ["gh", "api", "--method", "GET"])
            self.assertEqual(command[-1], observation["endpoint"])
            return subprocess.CompletedProcess(
                command, 0, json.dumps(release).encode(), b""
            )

        start = datetime.now(UTC).replace(microsecond=0)
        stdout = io.StringIO()
        with (
            patch.object(self.driver.subprocess, "run", side_effect=network),
            redirect_stdout(stdout),
        ):
            try:
                status = self.driver.main(
                    ["observe-draft", "--output-file", str(output)]
                )
            except SystemExit as error:
                self.fail(f"Draft capture CLI is missing: {error}")
        self.assertEqual(status, 0)
        captured = json.loads(output.read_bytes())
        self.assertEqual(set(captured), set(observation))
        self.assertEqual(captured["releaseBefore"], observation["releaseBefore"])
        self.assertEqual(captured["assetsBefore"], [])
        self.assertEqual(captured["provenance"], "operator-authenticated-get")
        self.assertTrue(
            start
            <= datetime.fromisoformat(captured["observedAt"].replace("Z", "+00:00"))
            <= datetime.now(UTC)
        )
        self.assertNotIn(release["body"], stdout.getvalue())
        before = output.read_bytes()
        with (
            patch.object(
                self.driver.subprocess,
                "run",
                side_effect=AssertionError("Existing output must not trigger network"),
            ),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                self.driver.main(["observe-draft", "--output-file", str(output)]), 1
            )
        self.assertEqual(output.read_bytes(), before)

    def test_draft_capture_preserves_http403_and_refuses_nonempty_or_published_state(
        self,
    ):
        self.assertTrue(
            hasattr(self.driver, "observe_draft"), "draft capture helper is missing"
        )
        output = self.root / "draft.json"
        denied = subprocess.CompletedProcess(
            ["gh"], 1, b"", b"HTTP 403: resource not accessible"
        )
        with patch.object(self.driver.subprocess, "run", return_value=denied):
            with self.assertRaisesRegex(self.driver.RepairError, "403"):
                self.driver.observe_draft(output)
        self.assertFalse(output.exists())
        observation = self.draft_observation()
        for release in [
            {**observation["releaseBefore"], "draft": False, "assets": []},
            {
                **observation["releaseBefore"],
                "assets": [
                    {
                        "id": 10,
                        "name": "existing.zip",
                        "size": 1,
                        "state": "uploaded",
                        "digest": None,
                    }
                ],
            },
        ]:
            with (
                self.subTest(release=release),
                self.assertRaises(self.driver.RepairError),
            ):
                self.driver.observe_draft(
                    output,
                    api=ReadOnlyAPI({observation["endpoint"]: release}, {10: b"x"}),
                )
            self.assertFalse(output.exists())

    def test_draft_observation_reader_rejects_duplicate_keys_at_both_levels(self):
        self.assertTrue(
            hasattr(self.driver, "read_release_observation"),
            "observation reader is missing",
        )
        output = self.root / "draft.json"
        content = json.dumps(self.draft_observation())
        for invalid in [
            content.replace(
                '"schemaVersion": 1', '"schemaVersion": 1, "schemaVersion": 1'
            ),
            content.replace('"draft": true', '"draft": true, "draft": true'),
        ]:
            output.write_text(invalid, encoding="utf-8")
            with self.assertRaisesRegex(self.driver.RepairError, "[Dd]uplicate"):
                self.driver.read_release_observation(output, "v2.8.0")

    def test_draft_capture_rejects_assets_before_any_download(self):
        self.assertTrue(
            hasattr(self.driver, "observe_draft"), "draft capture helper is missing"
        )
        observation = self.draft_observation()
        content = archive_bytes({"file": b"existing"})
        asset = {
            "id": 10,
            "name": "existing.zip",
            "size": len(content),
            "state": "uploaded",
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        }
        release = {**observation["releaseBefore"], "assets": [asset]}

        class MetadataOnlyAPI(ReadOnlyAPI):
            def download(self, asset_id):
                raise AssertionError("Draft capture must never download assets")

        output = self.root / "draft.json"
        with self.assertRaisesRegex(self.driver.RepairError, "empty draft"):
            self.driver.observe_draft(
                output,
                api=MetadataOnlyAPI({observation["endpoint"]: release}),
            )
        self.assertFalse(output.exists())

    def test_draft_capture_preserves_a_file_created_during_the_get(self):
        output = self.root / "draft.json"
        observation = self.draft_observation()
        release = {**observation["releaseBefore"], "assets": []}

        class RacingAPI(ReadOnlyAPI):
            def get(self, path):
                output.write_bytes(b"another writer owns this file")
                return super().get(path)

        with self.assertRaises(FileExistsError):
            self.driver.observe_draft(
                output, api=RacingAPI({observation["endpoint"]: release})
            )
        self.assertEqual(output.read_bytes(), b"another writer owns this file")

    def test_operator_observation_rejects_other_prepare_profiles(self):
        snapshot = self.root / "observation.json"
        snapshot.write_text(json.dumps(self.draft_observation()), encoding="utf-8")
        output = self.root / "forbidden"
        try:
            with self.assertRaises(self.driver.RepairError):
                self.driver.prepare(
                    SCRIPT.parents[1],
                    "v2.11.0",
                    output,
                    api=ReadOnlyAPI({}),
                    draft_release_snapshot=snapshot,
                )
        except TypeError as error:
            self.fail(f"Observation prepare interface is missing: {error}")
        self.assertFalse(output.exists())

    def test_verify_rejects_coerced_candidate_state_before_source_lookup(self):
        observation = self.draft_observation()
        candidate = {
            "schemaVersion": 1,
            "repository": self.driver.REPOSITORY,
            "tag": "v2.8.0",
            "releaseObservation": observation,
            "releaseBefore": copy.deepcopy(observation["releaseBefore"]),
            "assetsBefore": [],
        }
        path = self.root / "candidate.json"
        for field, value in [
            ("id", 383049548.0),
            ("draft", 1),
            ("prerelease", 1),
        ]:
            changed = copy.deepcopy(candidate)
            changed["releaseBefore"][field] = value
            path.write_text(json.dumps(changed), encoding="utf-8")
            with (
                self.subTest(field=field),
                patch.object(
                    self.driver,
                    "tag_identity",
                    side_effect=AssertionError(
                        "Observation mismatch must reject before source lookup"
                    ),
                ),
                self.assertRaisesRegex(self.driver.RepairError, "observation"),
            ):
                self.driver.verify(self.root, self.root, api=ReadOnlyAPI({}))

    def test_notes_use_the_sealed_preparation_timestamp_without_reading_the_clock(self):
        prepared_at = "2026-10-30T03:26:44Z"
        with patch.object(self.driver, "datetime", wraps=datetime) as clock:
            clock.now.side_effect = AssertionError(
                "Notes must use the sealed timestamp"
            )
            try:
                notes = self.driver.notes_body(
                    "v2.8.0",
                    "Original notes",
                    self.driver.asset_names("v2.8.0"),
                    prepared_at=prepared_at,
                )
            except TypeError as error:
                self.fail(f"Sealed preparation date interface is missing: {error}")
        self.assertIn("## Historical release repair\n\nPrepared: " + prepared_at, notes)
        self.assertTrue(notes.startswith("Original notes\n\n"))
        for invalid in (True, "2026-02-30T03:26:44Z", "2026-10-30"):
            with (
                self.subTest(timestamp=invalid),
                self.assertRaises(self.driver.RepairError),
            ):
                self.driver.notes_body(
                    "v2.8.0",
                    None,
                    self.driver.asset_names("v2.8.0"),
                    prepared_at=invalid,
                )

    def test_qualified_candidate_requires_preparation_timestamp_before_source_lookup(
        self,
    ):
        observation = self.draft_observation()
        candidate = {
            "schemaVersion": 1,
            "repository": self.driver.REPOSITORY,
            "tag": "v2.8.0",
            "releaseBefore": observation["releaseBefore"],
            "assetsBefore": [],
            "qualification": {
                "runId": 1,
                "runAttempt": 1,
                "sourceSha": "a" * 40,
            },
        }
        (self.root / "candidate.json").write_text(
            json.dumps(candidate), encoding="utf-8"
        )
        with (
            patch.object(
                self.driver,
                "tag_identity",
                side_effect=AssertionError(
                    "Missing timestamp must reject before source lookup"
                ),
            ),
            self.assertRaisesRegex(self.driver.RepairError, "preparation timestamp"),
        ):
            self.driver.verify(self.root, self.root, api=ReadOnlyAPI({}))

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

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
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
            prepared_at = candidate["preparedAt"]
            proof = json.loads((bundle / "payload" / self.driver.PROOF).read_bytes())
            self.assertEqual(proof["preparedAt"], prepared_at)
            self.assertIn(f"Prepared: {prepared_at}\n", candidate["notes"])
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
            with patch.object(self.driver, "datetime", wraps=datetime) as clock:
                clock.now.side_effect = AssertionError(
                    "Verification must not read the clock"
                )
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
