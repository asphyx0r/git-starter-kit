from __future__ import annotations

import copy
import ast
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from test_release_publication import API_RUNNER, isolated_environment, step_script

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "asphyx0r/git-starter-kit"
COMMITS = {
    "v1.7.3": "7e964d89a9f1553e2575191f60ca333c2a15dc93",
    "v2.0.1": "4a8e45c0eaef3030e263a34d694b9b4d10d3af3b",
    "v2.1.0": "3db8add2135ec04fc70c59a635e9de3a4f7bc464",
    "v2.2.0": "c3f031e5cbe8a7d4fe6d571fb3935b97caf5f2b6",
    "v2.8.0": "00745498a7e6f00d2f10341e4ba493a69b6cefef",
    "v2.11.0": "4bd47329e6a989823472eb015c62e75bb7318bc3",
}
RELEASE_IDS = {
    "v2.0.1": 357402329,
    "v2.1.0": 362702751,
    "v2.8.0": 383049548,
    "v2.11.0": 388017021,
}

GH_STUB = r"""
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote

path = Path(os.environ["API_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
assert args[0] == "api", args
endpoint = args[1]
method = args[args.index("--method") + 1] if "--method" in args else "GET"
state["trace"].append([method, endpoint])
prefix = "repos/asphyx0r/git-starter-kit"
release = state["release"]
response = None
binary = None
status = 0
not_found = False
if method == "POST" and endpoint == prefix + "/releases":
    assert release is None, "must never create duplicate releases"
    fields = json.loads(sys.stdin.read())
    assert fields["make_latest"] == "false" and "target_commitish" not in fields
    assert fields["draft"] is False and fields["prerelease"] is False
    release = dict(fields, id=42, updated_at="created", published_at="published")
    state["release"] = release
    response = release
elif method == "POST":
    assert endpoint.startswith("https://uploads.github.com/" + prefix + f"/releases/{release['id']}/assets?name=")
    name = unquote(endpoint.split("?name=")[1])
    assert not any(asset["name"] == name for asset in state["assets"]), "overwrite forbidden"
    if state.get("fail_upload") == name:
        state.pop("fail_upload")
        status = 74
    else:
        content = Path(args[args.index("--input") + 1]).read_bytes()
        response = dict(id=max([a["id"] for a in state["assets"]] + [100]) + 1,
                        name=name, state="uploaded", size=len(content),
                        digest="sha256:" + hashlib.sha256(content).hexdigest())
        state["assets"].append(response)
        state["content"][name] = content.hex()
        if state.get("update_timestamp"):
            release["updated_at"] = "upload-" + str(len(state["assets"]))
elif method == "PATCH":
    assert endpoint == prefix + f"/releases/{release['id']}", "only release promotion allowed"
    fields = json.loads(sys.stdin.read())
    assert fields["make_latest"] == "false" and fields["draft"] is False
    assert fields["prerelease"] is False and "tag_name" not in fields
    if state.get("fail_patch"):
        state.pop("fail_patch")
        status = 75
    else:
        release.update(fields, updated_at="final")
        response = release
elif method != "GET":
    raise AssertionError("Unexpected mutation " + repr(args))
elif endpoint == prefix:
    response = state["repository"]
elif endpoint == prefix + "/branches/main":
    response = {"commit": {"sha": state["source_sha"]}}
elif "/actions/artifacts/" in endpoint:
    response = state["artifact"]
elif endpoint.startswith(prefix + "/git/ref/tags/"):
    response = {"ref": "refs/tags/" + state["tag"],
                "object": {"type": "tag", "sha": state["tag_object"]}}
elif endpoint.startswith(prefix + "/git/tags/"):
    response = {"sha": state["tag_object"], "tag": state["tag"],
                "object": {"type": "commit", "sha": state["commit"], "url": "https://api.github.com/object"}}
elif endpoint.startswith(prefix + "/git/commits/"):
    response = {"sha": state["commit"], "tree": {"sha": state["tree"]}}
elif endpoint == prefix + "/releases/latest":
    response = state["latest"]
elif endpoint.startswith(prefix + "/releases?per_page=100&page="):
    response = [release] if release is not None else []
elif "/actions/runs/" in endpoint:
    current = "/456/" in endpoint
    if endpoint.endswith("/jobs?per_page=100"):
        response = {"jobs": [state.get("current_job", state["qualification_job"]) if current
                             else state["qualification_job"]], "total_count": 1}
    else:
        response = dict(state["run"], id=456) if current else state["run"]
elif endpoint.endswith("/assets?per_page=100&page=1"):
    response = state["assets"]
elif endpoint.endswith("/assets?per_page=100&page=2"):
    response = []
elif "/releases/assets/" in endpoint:
    asset = next(a for a in state["assets"] if a["id"] == int(endpoint.rsplit("/", 1)[1]))
    binary = bytes.fromhex(state["content"][asset["name"]])
elif endpoint.startswith(prefix + "/releases/"):
    if "/releases/tags/" in endpoint:
        assert endpoint == prefix + "/releases/tags/" + state["tag"]
        not_found = release is None or release["draft"]
    else:
        assert release is not None and endpoint == prefix + f"/releases/{release['id']}"
    state["release_reads"] = state.get("release_reads", 0) + 1
    if state.get("deny_release_get"):
        path.write_text(json.dumps(state))
        sys.stderr.write("Resource not accessible by integration (HTTP 403)")
        sys.exit(1)
    if state.get("change_release_after") == state["release_reads"]:
        release["body"] = "concurrently changed"
    if release is None or not_found:
        status = 1
    else:
        response = release
else:
    raise AssertionError("Unexpected API endpoint " + repr(args))
path.write_text(json.dumps(state))
if status:
    sys.stderr.write("HTTP 404: Not Found" if release is None or not_found else "fixture interruption")
    sys.exit(status)
if binary is not None:
    sys.stdout.buffer.write(binary)
elif response is not None:
    print(json.dumps(response))
"""


@unittest.skipUnless(
    (ROOT / ".github/workflows/historical-release-repair.yml").is_file(),
    "consumer package does not ship historical publication",
)
class HistoricalPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.payload = self.bundle / "payload"
        self.payload.mkdir(parents=True)
        self.state_path = self.root / "state.json"
        self.current_run_id = "123"
        self.configure("v2.8.0")

    def configure(self, tag, absent=False):
        for path in self.payload.iterdir():
            path.rmdir() if path.is_dir() else path.unlink()
        self.proof = {
            "qualification": {"runId": 123, "runAttempt": 1, "sourceSha": "a" * 40},
        }
        self.content = {
            "historical-repair-proof.json": json.dumps(self.proof).encode(),
            f"git-starter-kit-{tag}-with-agent-rules.zip": b"zip\x00\xff",
        }
        for name, content in self.content.items():
            (self.payload / name).write_bytes(content)
        release = (
            None
            if absent
            else {
                "id": RELEASE_IDS[tag],
                "tag_name": tag,
                "name": tag,
                "body": "original notes",
                "draft": tag == "v2.8.0",
                "prerelease": tag in ("v2.0.1", "v2.11.0"),
                "updated_at": "original",
                "published_at": "original",
            }
        )
        self.state = {
            "repository": {"full_name": REPOSITORY, "default_branch": "main"},
            "source_sha": "a" * 40,
            "tag": tag,
            "tag_object": "b" * 40,
            "commit": COMMITS[tag],
            "tree": "c" * 40,
            "release": release,
            "assets": [],
            "latest": {"id": 999, "tag_name": "v3.0.1"},
            "qualification_job": {
                "name": "Qualify historical candidate",
                "conclusion": "success",
                "status": "completed",
            },
            "run": {
                "id": 123,
                "run_attempt": 1,
                "head_sha": "a" * 40,
                "event": "workflow_dispatch",
                "path": ".github/workflows/historical-release-repair.yml",
                "repository": {"full_name": REPOSITORY},
            },
            "trace": [],
            "content": {name: value.hex() for name, value in self.content.items()},
        }
        self.candidate = {
            "schemaVersion": 1,
            "repository": REPOSITORY,
            "tag": tag,
            "tagObject": "b" * 40,
            "commit": COMMITS[tag],
            "tree": "c" * 40,
            "releaseBefore": copy.deepcopy(release),
            "assetsBefore": [],
            "latestBefore": {"id": 999, "tag": "v3.0.1"},
            "notes": "original notes\nDated repair note",
            "qualification": copy.deepcopy(self.proof["qualification"]),
            "payload": [
                dict(
                    name=name,
                    size=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                )
                for name, content in self.content.items()
            ],
        }

    def asset(self, name, asset_id=10):
        return dict(
            id=asset_id,
            name=name,
            state="uploaded",
            size=len(self.content[name]),
            digest="sha256:" + hashlib.sha256(self.content[name]).hexdigest(),
        )

    def seal(self):
        path = self.bundle / "candidate.json"
        path.write_text(json.dumps(self.candidate), encoding="utf-8")
        self.candidate_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    def invoke(self, reseal=True):
        workflow = ROOT / ".github/workflows/historical-release-repair.yml"
        self.assertTrue(workflow.is_file(), "Historical repair publication is missing")
        if reseal:
            self.seal()
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        script = step_script(
            "historical-release-repair", "publish", "Publish historical repair"
        )
        (self.root / "publisher.py").write_text(script, encoding="utf-8")
        (self.root / "runner.py").write_text(API_RUNNER, encoding="utf-8")
        (self.root / "gh.py").write_text(GH_STUB, encoding="utf-8")
        environment = dict(
            isolated_environment(self.root),
            API_STATE=str(self.state_path),
            TRANSFER_ROOT=str(self.bundle),
            EXPECTED_CANDIDATE_SHA256=self.candidate_hash,
            RELEASE_TAG=self.candidate["tag"],
            GH_REPO=REPOSITORY,
            SOURCE_SHA="a" * 40,
            QUALIFICATION_RUN_ID="123",
            QUALIFICATION_RUN_ATTEMPT="1",
            CURRENT_RUN_ID=self.current_run_id,
            CURRENT_RUN_ATTEMPT="1",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(self.root / "runner.py"),
                str(self.root / "gh.py"),
                str(self.root / "publisher.py"),
            ],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.state = json.loads(self.state_path.read_text())
        return result

    def mutations(self):
        return [entry for entry in self.state["trace"] if entry[0] != "GET"]

    def observe_draft(self):
        self.candidate["releaseBefore"] = {
            key: self.candidate["releaseBefore"][key]
            for key in (
                "id",
                "tag_name",
                "draft",
                "prerelease",
                "published_at",
                "updated_at",
                "body",
            )
        }
        observation = {
            "schemaVersion": 1,
            "repository": REPOSITORY,
            "method": "GET",
            "endpoint": f"repos/{REPOSITORY}/releases/383049548",
            "observedAt": "2026-10-30T02:40:00Z",
            "provenance": "operator-authenticated-get",
            "releaseBefore": copy.deepcopy(self.candidate["releaseBefore"]),
            "assetsBefore": [],
        }
        self.candidate["releaseObservation"] = observation
        self.proof["releaseObservation"] = copy.deepcopy(observation)
        self.write_proof()

    def write_proof(self):
        content = json.dumps(self.proof).encode()
        (self.payload / "historical-repair-proof.json").write_bytes(content)
        record = next(
            entry
            for entry in self.candidate["payload"]
            if entry["name"] == "historical-repair-proof.json"
        )
        record.update(size=len(content), sha256=hashlib.sha256(content).hexdigest())

    def test_observation_and_proof_must_agree_before_publication(self):
        for change in (
            "changed",
            "missing",
            "missing_candidate",
            "snapshot",
            "schema_bool",
            "schema_float",
            "draft_number",
            "proof_float_id",
            "candidate_float_id",
            "prepared_date_changed",
            "prepared_date_missing_candidate",
            "prepared_date_missing_proof",
            "prepared_date_type",
        ):
            with self.subTest(change=change):
                self.configure("v2.8.0")
                self.observe_draft()
                self.candidate["preparedAt"] = "2026-10-30T03:26:44Z"
                self.proof["preparedAt"] = self.candidate["preparedAt"]
                if change == "changed":
                    self.proof["releaseObservation"]["observedAt"] = (
                        "2026-10-30T02:41:00Z"
                    )
                elif change == "missing":
                    del self.proof["releaseObservation"]
                elif change == "missing_candidate":
                    del self.candidate["releaseObservation"]
                elif change == "schema_bool":
                    self.proof["releaseObservation"]["schemaVersion"] = True
                elif change == "schema_float":
                    self.proof["releaseObservation"]["schemaVersion"] = 1.0
                elif change == "draft_number":
                    self.proof["releaseObservation"]["releaseBefore"]["draft"] = 1
                elif change == "proof_float_id":
                    self.proof["releaseObservation"]["releaseBefore"]["id"] = (
                        383049548.0
                    )
                elif change == "candidate_float_id":
                    self.candidate["releaseBefore"]["id"] = 383049548.0
                elif change == "prepared_date_changed":
                    self.proof["preparedAt"] = "2026-10-30T03:26:45Z"
                elif change == "prepared_date_missing_candidate":
                    del self.candidate["preparedAt"]
                elif change == "prepared_date_missing_proof":
                    del self.proof["preparedAt"]
                elif change == "prepared_date_type":
                    self.candidate["preparedAt"] = True
                    self.proof["preparedAt"] = True
                else:
                    self.proof["releaseObservation"]["releaseBefore"]["body"] = (
                        "different"
                    )
                    self.candidate["releaseObservation"] = copy.deepcopy(
                        self.proof["releaseObservation"]
                    )
                self.write_proof()
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_observation_never_replaces_live_release_get_or_second_check(self):
        for change in ("403", "body", "updated_at", "assets", "second_check", "valid"):
            with self.subTest(change=change):
                self.configure("v2.8.0")
                self.observe_draft()
                self.candidate["preparedAt"] = "2026-10-30T03:26:44Z"
                self.proof["preparedAt"] = self.candidate["preparedAt"]
                self.write_proof()
                if change == "403":
                    self.state["deny_release_get"] = True
                elif change in ("body", "updated_at"):
                    self.state["release"][change] = "changed"
                elif change == "assets":
                    self.state["assets"] = [self.asset(list(self.content)[1], 500)]
                    self.state["assets"][0]["name"] = "unexpected.zip"
                elif change == "second_check":
                    self.state["change_release_after"] = 2
                result = self.invoke()
                self.assertEqual(
                    result.returncode == 0, change == "valid", result.stderr
                )
                self.assertIn(
                    ["GET", f"repos/{REPOSITORY}/releases/383049548"],
                    self.state["trace"],
                )
                if change != "valid":
                    self.assertEqual(self.mutations(), [])

    def test_observation_input_is_data_and_restricted_to_readonly_v280(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/historical-release-repair.yml").read_text()
        )
        step = next(
            (
                step
                for step in workflow["jobs"]["qualification"]["steps"]
                if step.get("name") == "Validate repair inputs"
            ),
            None,
        )
        self.assertIsNotNone(
            step, "Workflow must validate the observation input before preparation"
        )
        self.observe_draft()
        observation = copy.deepcopy(self.candidate["releaseObservation"])
        observation["releaseBefore"]["body"] = (
            'literal $(touch owned) `touch owned`; "quoted"\nsecond line'
        )
        raw = json.dumps(observation, indent=2, ensure_ascii=False)
        cases = (
            ("v2.8.0", "false", "", False),
            ("v2.1.0", "false", raw, False),
            ("v2.8.0", "true", raw, False),
            ("v2.8.0", "false", '{"id":1,"id":2}', False),
            ("v2.8.0", "false", '{"releaseBefore":{"body":"a","body":"b"}}', False),
            ("v2.8.0", "false", "[]", False),
            ("v2.8.0", "false", "broken JSON", False),
            ("v2.1.0", "false", "", True),
            ("v2.8.0", "true", "", True),
            ("v2.8.0", "false", raw, True),
        )
        for tag, publish, content, expected in cases:
            with (
                self.subTest(tag=tag, publish=publish, content=content),
                tempfile.TemporaryDirectory(dir=self.root) as folder,
            ):
                directory = Path(folder)
                (directory / "input.py").write_text(step["run"], encoding="utf-8")
                (directory / "runner.py").write_text(API_RUNNER, encoding="utf-8")
                (directory / "gh.py").write_text(
                    "raise AssertionError('Input validation must not call API')",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(directory / "runner.py"),
                        str(directory / "gh.py"),
                        str(directory / "input.py"),
                    ],
                    env=dict(
                        isolated_environment(directory),
                        INPUT_TAG=tag,
                        INPUT_PUBLISH=publish,
                        DRAFT_RELEASE_SNAPSHOT=content,
                        RUNNER_TEMP=str(directory),
                        GITHUB_OUTPUT=str(directory / "outputs"),
                    ),
                    cwd=directory,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, expected, result.stderr)
                snapshot = directory / "historical-draft-release-observation.json"
                self.assertEqual(snapshot.exists(), expected and bool(content))
                if snapshot.exists():
                    self.assertEqual(snapshot.read_bytes(), content.encode("utf-8"))
                    self.assertIn(str(snapshot), (directory / "outputs").read_text())
                self.assertFalse((directory / "owned").exists())

    def test_draft_release_is_selected_by_original_id_when_tag_route_hides_it(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state["release"]["id"], 383049548)
        self.assertIn(
            ["GET", f"repos/{REPOSITORY}/releases/383049548"], self.state["trace"]
        )
        self.assertNotIn(
            ["GET", f"repos/{REPOSITORY}/releases/tags/v2.8.0"], self.state["trace"]
        )
        self.assertNotIn(["POST", f"repos/{REPOSITORY}/releases"], self.mutations())

    def test_closed_profiles_refuse_false_absence_or_an_unexpected_draft(self):
        self.candidate["releaseBefore"] = None
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.mutations(), [])
        self.configure("v1.7.3", absent=True)
        self.state["release"] = dict(
            id=777,
            tag_name="v1.7.3",
            name="v1.7.3",
            draft=True,
            prerelease=False,
            published_at=None,
            updated_at="unexpected",
            body="unexpected draft",
        )
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_reviewed_artifact_origin_must_match_receipt_run_and_attempt(self):
        self.seal()
        script = step_script(
            "historical-release-repair", "qualification", "Requalify reviewed candidate"
        )
        match = re.search(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", script, re.DOTALL)
        self.assertIsNotNone(
            match, "Requalification must execute actual artifact lineage preflight"
        )
        (self.root / "lineage.py").write_text(match[1], encoding="utf-8")
        (self.root / "runner.py").write_text(API_RUNNER, encoding="utf-8")
        (self.root / "gh.py").write_text(GH_STUB, encoding="utf-8")
        for run_id, artifact_name, expected in (
            ("456", "historical-repair-v2.8.0-456-1", False),
            ("123", "historical-repair-v2.8.0-123-2", False),
            ("123", "historical-repair-v2.1.0-123-1", False),
            ("123", "historical-repair-v2.8.0-123-1", True),
        ):
            with self.subTest(run_id=run_id, artifact_name=artifact_name):
                self.state["trace"] = []
                self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
                environment = dict(
                    isolated_environment(self.root),
                    API_STATE=str(self.state_path),
                    BUNDLE_DIR=str(self.bundle),
                    REVIEWED_RUN_ID=run_id,
                    REVIEWED_ARTIFACT_NAME=artifact_name,
                    SOURCE_SHA="a" * 40,
                    EXPECTED_HASH=self.candidate_hash,
                    RELEASE_TAG="v2.8.0",
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(self.root / "runner.py"),
                        str(self.root / "gh.py"),
                        str(self.root / "lineage.py"),
                    ],
                    env=environment,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, expected, result.stderr)
                self.assertEqual(json.loads(self.state_path.read_text())["trace"], [])

    def test_reviewed_candidate_keeps_original_receipt_and_requires_current_qualification(
        self,
    ):
        self.current_run_id = "456"
        self.seal()
        sealed = (self.bundle / "candidate.json").read_bytes()
        self.state["current_job"] = dict(
            self.state["qualification_job"], conclusion="failure"
        )
        self.assertNotEqual(self.invoke(reseal=False).returncode, 0)
        self.assertEqual(self.mutations(), [])
        self.state["current_job"]["conclusion"] = "success"
        self.state["trace"] = []
        result = self.invoke(reseal=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.bundle / "candidate.json").read_bytes(), sealed)
        self.assertEqual(self.proof["qualification"]["runId"], 123)

    def test_upload_timestamp_changes_resume_only_with_exact_approved_progress(self):
        self.state["update_timestamp"] = True
        self.state["fail_upload"] = list(self.content)[1]
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.state["release"]["updated_at"], "upload-1")
        self.state["trace"] = []
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.state["release"]["draft"])

    def test_existing_draft_and_prereleases_promote_after_verified_uploads(self):
        for tag in ("v2.8.0", "v2.0.1", "v2.11.0", "v2.1.0"):
            with self.subTest(tag=tag):
                self.configure(tag)
                result = self.invoke()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    self.mutations()[-1],
                    ["PATCH", f"repos/{REPOSITORY}/releases/{RELEASE_IDS[tag]}"],
                )
                self.assertEqual(len(self.state["assets"]), 2)
                self.assertFalse(self.state["release"]["draft"])
                self.assertFalse(self.state["release"]["prerelease"])
                self.assertEqual(self.state["release"]["body"], self.candidate["notes"])
                self.assertEqual(self.state["latest"]["id"], 999)

    def test_absent_releases_create_without_tags_or_latest_mutation(self):
        for tag in ("v1.7.3", "v2.2.0"):
            with self.subTest(tag=tag):
                self.configure(tag, absent=True)
                result = self.invoke()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    self.mutations()[0], ["POST", f"repos/{REPOSITORY}/releases"]
                )
                self.assertEqual(self.state["release"]["tag_name"], tag)
                self.assertFalse(
                    any("/git/" in endpoint for _, endpoint in self.mutations())
                )

    def test_absent_release_created_before_interruption_resumes_without_duplicate(self):
        self.configure("v1.7.3", absent=True)
        self.state["fail_upload"] = list(self.content)[1]
        self.assertNotEqual(self.invoke().returncode, 0)
        self.state["trace"] = []
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(["POST", f"repos/{REPOSITORY}/releases"], self.mutations())
        self.assertEqual(self.state["release"]["id"], 42)

    def test_stable_v210_adds_only_sidecar_preserving_both_existing_archives(self):
        self.configure("v2.1.0")
        package = list(self.content)[1]
        toolkit = "git-starter-kit-v2.1.0-upgrade-toolkit.zip"
        self.content[toolkit] = b"original toolkit bytes"
        self.state["content"][toolkit] = self.content[toolkit].hex()
        self.state["assets"] = [self.asset(package, 10), self.asset(toolkit, 11)]
        originals = copy.deepcopy(self.state["assets"])
        self.candidate["assetsBefore"] = [
            dict(
                id=a["id"],
                name=a["name"],
                state=a["state"],
                size=a["size"],
                sha256=a["digest"][7:],
            )
            for a in originals
        ]
        self.candidate["payload"] = self.candidate["payload"][:1]
        (self.payload / package).unlink()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state["assets"][:2], originals)
        uploads = [
            endpoint for method, endpoint in self.mutations() if method == "POST"
        ]
        self.assertEqual(len(uploads), 1)
        self.assertTrue(uploads[0].endswith("?name=historical-repair-proof.json"))

    def test_reviewed_artifact_resolution_rejects_untrusted_source_and_invalid_inputs(
        self,
    ):
        self.state["artifact"] = {
            "id": 555,
            "name": "historical-repair-v2.8.0-123-1",
            "expired": False,
            "workflow_run": {"id": 123, "head_sha": "a" * 40},
        }
        script = step_script(
            "historical-release-repair", "qualification", "Resolve reviewed artifact"
        )
        actual = script
        (self.root / "resolve.py").write_text(actual, encoding="utf-8")
        (self.root / "runner.py").write_text(API_RUNNER, encoding="utf-8")
        (self.root / "gh.py").write_text(GH_STUB, encoding="utf-8")
        for artifact_id, digest, change in (
            ("../555", "a" * 64, None),
            ("555", "bad hash", None),
            ("555", "a" * 64, {"expired": True}),
            ("555", "a" * 64, {"workflow_run": {"id": 123, "head_sha": "b" * 40}}),
            ("555", "a" * 64, None),
        ):
            with self.subTest(artifact_id=artifact_id, change=change):
                self.state["artifact"].update(
                    expired=False, workflow_run={"id": 123, "head_sha": "a" * 40}
                )
                if change:
                    self.state["artifact"].update(change)
                self.state["trace"] = []
                self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
                environment = dict(
                    isolated_environment(self.root),
                    API_STATE=str(self.state_path),
                    REVIEWED_ARTIFACT_ID=artifact_id,
                    EXPECTED_HASH=digest,
                    SOURCE_SHA="a" * 40,
                    GITHUB_OUTPUT=str(self.root / "output"),
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(self.root / "runner.py"),
                        str(self.root / "gh.py"),
                        str(self.root / "resolve.py"),
                    ],
                    env=environment,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                valid = artifact_id == "555" and digest == "a" * 64 and change is None
                self.assertEqual(result.returncode == 0, valid, result.stderr)
                state = json.loads(self.state_path.read_text())
                self.assertTrue(all(method == "GET" for method, _ in state["trace"]))
                if valid:
                    self.assertEqual(
                        (self.root / "output").read_text(),
                        "run_id=123\nartifact_name=historical-repair-v2.8.0-123-1\n",
                    )

    def test_partial_upload_and_final_patch_interruptions_resume_exact_candidate(self):
        for interruption in ("upload", "patch"):
            with self.subTest(interruption=interruption):
                self.configure("v2.8.0")
                if interruption == "upload":
                    self.state["fail_upload"] = list(self.content)[1]
                else:
                    self.state["fail_patch"] = True
                self.assertNotEqual(self.invoke().returncode, 0)
                ids = {asset["id"] for asset in self.state["assets"]}
                self.state["trace"] = []
                result = self.invoke()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(
                    ids.issubset({asset["id"] for asset in self.state["assets"]})
                )
                self.state["trace"] = []
                result = self.invoke()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mutations(), [])

    def test_existing_snapshot_assets_keep_identity_and_bytes(self):
        name = list(self.content)[1]
        original = self.asset(name)
        self.state["assets"] = [original]
        self.candidate["assetsBefore"] = [
            dict(
                id=10,
                name=name,
                state="uploaded",
                size=original["size"],
                sha256=original["digest"][7:],
            )
        ]
        self.candidate["payload"] = self.candidate["payload"][:1]
        (self.payload / name).unlink()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state["assets"][0], original)

    def test_stale_identity_or_unfinished_qualification_blocks_before_writes(self):
        changes = (
            ("tag_object", "d" * 40),
            ("commit", "d" * 40),
            ("tree", "d" * 40),
            ("source_sha", "d" * 40),
            ("release", {"id": 43}),
            ("release", {"body": "changed"}),
            ("release", {"updated_at": "changed"}),
            ("release", {"draft": False}),
            ("latest", {"id": 998}),
            ("qualification_job", {"conclusion": None, "status": "in_progress"}),
            ("run", {"head_sha": "d" * 40}),
        )
        for field, value in changes:
            with self.subTest(field=field, value=value):
                self.configure("v2.8.0")
                if isinstance(value, dict):
                    self.state[field].update(value)
                else:
                    self.state[field] = value
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_missing_changed_duplicate_or_unknown_remote_assets_block(self):
        name = list(self.content)[1]
        for change in (
            "size",
            "digest",
            "id",
            "missing",
            "duplicate",
            "unknown",
            "bytes",
        ):
            with self.subTest(change=change):
                self.configure("v2.8.0")
                asset = self.asset(name)
                self.candidate["assetsBefore"] = [
                    dict(
                        id=10,
                        name=name,
                        state="uploaded",
                        size=asset["size"],
                        sha256=asset["digest"][7:],
                    )
                ]
                self.state["assets"] = [asset]
                if change in ("size", "id"):
                    asset[change] += 1
                elif change == "digest":
                    asset["digest"] = "sha256:" + "0" * 64
                elif change == "missing":
                    self.state["assets"] = []
                elif change == "duplicate":
                    self.state["assets"].append(self.asset(name, 11))
                elif change == "unknown":
                    asset["name"] = "unknown.zip"
                else:
                    self.state["content"][name] = b"corrupted".hex()
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_unsealed_payloads_and_extra_paths_never_reach_write_api(self):
        for change in ("candidate", "payload", "extra", "nested", "unsafe", "proof"):
            with self.subTest(change=change):
                self.configure("v2.8.0")
                extra = None
                if change == "payload":
                    next(self.payload.iterdir()).write_bytes(b"tampered")
                elif change == "extra":
                    extra = self.bundle / "extra"
                    extra.touch()
                elif change == "nested":
                    extra = self.payload / "nested"
                    extra.mkdir()
                elif change == "unsafe":
                    self.candidate["payload"][0]["name"] = "../candidate.json"
                elif change == "proof":
                    self.proof["qualification"]["sourceSha"] = "0" * 40
                    proof = json.dumps(self.proof).encode()
                    (self.payload / "historical-repair-proof.json").write_bytes(proof)
                    self.candidate["payload"][0].update(
                        size=len(proof), sha256=hashlib.sha256(proof).hexdigest()
                    )
                self.seal()
                if change == "candidate":
                    (self.bundle / "candidate.json").write_text("{}")
                self.assertNotEqual(self.invoke(reseal=False).returncode, 0)
                self.assertEqual(self.mutations(), [])
                if extra:
                    extra.rmdir() if extra.is_dir() else extra.unlink()

    def test_changed_release_during_upload_prevents_final_promotion(self):
        self.state["change_release_after"] = 2
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(any(method == "PATCH" for method, _ in self.mutations()))

    def test_symlink_payload_is_rejected_before_remote_mutations(self):
        target = self.root / "outside"
        target.write_bytes(self.content["historical-repair-proof.json"])
        proof = self.payload / "historical-repair-proof.json"
        proof.unlink()
        try:
            proof.symlink_to(target)
        except OSError as error:
            self.skipTest(f"Host cannot create symlink fixtures: {error}")
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.mutations(), [])


@unittest.skipUnless(
    (ROOT / ".github/workflows/historical-release-repair.yml").is_file(),
    "consumer package does not ship historical publication",
)
class HistoricalWorkflowTests(unittest.TestCase):
    def test_python_only_steps_use_native_python_shell(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/historical-release-repair.yml").read_text(
                encoding="utf-8"
            )
        )
        for job, name in (
            ("qualification", "Resolve reviewed artifact"),
            ("publish", "Publish historical repair"),
        ):
            step = next(
                step
                for step in workflow["jobs"][job]["steps"]
                if step.get("name") == name
            )
            self.assertEqual(step["shell"], "python")
            ast.parse(step["run"])

    def test_closed_workflow_separates_credentials_and_downloads_exact_artifact(self):
        path = ROOT / ".github/workflows/historical-release-repair.yml"
        self.assertTrue(path.exists(), "Closed manual historical workflow is missing")
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        inputs = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs["tag"]["options"]), set(COMMITS))
        self.assertIs(inputs["publish"]["default"], False)
        self.assertEqual(
            workflow["concurrency"]["group"], "release-package-${{ inputs.tag }}"
        )
        publish = workflow["jobs"]["publish"]
        self.assertEqual(publish["environment"], "release")
        self.assertEqual(
            publish["permissions"], {"contents": "write", "actions": "read"}
        )
        for step in publish["steps"]:
            self.assertNotIn("checkout", step.get("uses", ""))
            if "GH_TOKEN" in step.get("env", {}):
                self.assertIs(step, publish["steps"][-1])
            if "run" in step:
                self.assertNotIn("${{", step["run"])
                self.assertNotRegex(
                    step["run"], r"python[^\n]*(?:tools/|TRANSFER_ROOT.*\.py)"
                )
        download = publish["steps"][0]
        self.assertIn("artifact-ids", download["with"])
        self.assertNotIn("name", download["with"])
        self.assertIn("qualification", publish["needs"])
        self.assertEqual(
            workflow["permissions"], {"contents": "read", "actions": "read"}
        )
