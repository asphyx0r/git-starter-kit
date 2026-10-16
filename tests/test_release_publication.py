from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from test_workflow_contracts import BASH

ROOT = Path(__file__).resolve().parents[1]
CONFINED_BASH = (
    'stub_bin="$TEST_BIN"; '
    'if command -v cygpath >/dev/null 2>&1; then stub_bin="$(cygpath -u "$stub_bin")"; fi; '
    'export PATH="$stub_bin:$PATH"; '
    'test "$(command -v gh)" = "$stub_bin/gh" || exit 92; '
    'bash "$1"'
)


def isolated_environment(root):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("GH_", "GITHUB_"))
    }
    environment["GH_CONFIG_DIR"] = str(root / "empty-gh-config")
    return environment


API_RUNNER = r"""
import subprocess
import sys
import types
from pathlib import Path

native_run = subprocess.run
native_popen = subprocess.Popen
stub = Path(sys.argv[1]).resolve(strict=True)
script = Path(sys.argv[2]).read_text(encoding="utf-8")

def confined_command(command):
    if command[:4] != ["timeout", "30s", "gh", "api"]:
        raise RuntimeError("Unconfined external command refused")
    return [sys.executable, str(stub), *command[3:]]

def run(command, **options):
    return native_run(confined_command(command), **options)

def popen(command, **options):
    return native_popen(confined_command(command), **options)

facade = types.ModuleType("subprocess")
facade.run = run
facade.Popen = popen
facade.PIPE = subprocess.PIPE
sys.modules["subprocess"] = facade
exec(compile(script, "<actual release publication heredoc>", "exec"))
"""


def step_script(workflow, job, name):
    document = yaml.safe_load(
        (ROOT / f".github/workflows/{workflow}.yml").read_text(encoding="utf-8")
    )
    return next(
        step["run"]
        for step in document["jobs"][job]["steps"]
        if step.get("name") == name
    )


GH_STUB = r"""
import hashlib
import json
import os
import sys
from pathlib import Path

path = Path(os.environ["API_STATE"])
state = json.loads(path.read_text())
args = sys.argv[1:]
assert args[0] == "api", args
endpoint = args[1]
method = args[args.index("--method") + 1] if "--method" in args else "GET"
state["trace"].append([method, endpoint])
release = state["release"]
assets = state["assets"]
if method == "POST":
    assert endpoint.startswith("https://uploads.github.com/repos/fixture/repo/releases/42/assets?name="), endpoint
    name = endpoint.split("?name=")[1]
    if state.get("upload_failure_name") == name:
        state.pop("upload_failure_name")
        path.write_text(json.dumps(state))
        sys.exit(74)
    assert not any(asset["name"] == name for asset in assets)
    content = Path(args[args.index("--input") + 1]).read_bytes()
    assets.append({"id": max((asset["id"] for asset in assets), default=100) + 1, "name": name, "state": "uploaded",
                   "size": len(content), "digest": "sha256:" + hashlib.sha256(content).hexdigest()})
    response = assets[-1]
elif method == "DELETE":
    asset_id = int(endpoint.rsplit("/", 1)[1])
    asset = next(asset for asset in assets if asset["id"] == asset_id)
    assert asset["state"] == "starter" and asset["size"] == 0
    assets.remove(asset)
    response = None
elif method == "PATCH":
    assert endpoint == "repos/fixture/repo/releases/42"
    if state.get("promotion_failure"):
        state["promotion_failure"] = False
        path.write_text(json.dumps(state))
        sys.exit(73)
    assert args[args.index("-F") + 1] == "prerelease=false", args
    release["prerelease"] = False
    response = release
elif "/releases/assets/" in endpoint:
    asset_id = int(endpoint.rsplit("/", 1)[1])
    response = next(asset for asset in assets if asset["id"] == asset_id)
    if any("application/octet-stream" in argument for argument in args):
        path.write_text(json.dumps(state))
        sys.stdout.buffer.write(bytes.fromhex(state["content"][response["name"]]))
        sys.exit(0)
    if state.get("starter_changed"):
        response["state"] = "uploaded"
elif endpoint.endswith("/assets"):
    state["asset_reads"] = state.get("asset_reads", 0) + 1
    if state["asset_reads"] > 1 and state.get("asset_changed"):
        next(asset for asset in assets if asset["name"] == state["asset_changed"])["digest"] = "sha256:" + "0" * 64
    response = [assets]
else:
    assert endpoint in ("repos/fixture/repo/releases/tags/v1.2.3", "repos/fixture/repo/releases/42"), endpoint
    state["release_reads"] = state.get("release_reads", 0) + 1
    response = dict(release)
    if state["release_reads"] > state.get("release_changed_after", 1) and state.get("release_changed"):
        response.update(state["release_changed"])
path.write_text(json.dumps(state))
if response is not None:
    print(json.dumps(response))
"""


@unittest.skipUnless(
    (ROOT / ".github/workflows/release-package.yml").is_file(),
    "consumer package does not ship source publication",
)
class ReleasePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.event_name = "release"
        self.prerelease = "true"
        self.payload = self.root / "payload"
        self.payload.mkdir()
        self.content = {
            "package.zip": b"package\x00\xff",
            "toolkit.zip": b"toolkit\x00\xfe",
        }
        self.hashes = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in self.content.items()
        }
        self.content["SHA256SUMS"] = "".join(
            f"{digest}  {name}\n" for name, digest in self.hashes.items()
        ).encode()
        for name, content in self.content.items():
            (self.payload / name).write_bytes(content)
        self.state_path = self.root / "state.json"
        self.state = {
            "release": {
                "id": 42,
                "tag_name": "v1.2.3",
                "draft": False,
                "published_at": "2026-10-16T00:00:00Z",
                "prerelease": True,
            },
            "assets": [],
            "trace": [],
            "content": {name: content.hex() for name, content in self.content.items()},
        }
        (self.root / "gh-stub.py").write_text(GH_STUB, encoding="utf-8")
        stub = self.root / "gh"
        stub.write_text(
            '#!/usr/bin/env bash\nexec "$TEST_PYTHON" "$TEST_STUB" "$@"\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)

    def asset(self, asset_name, **changes):
        content = self.content[asset_name]
        return dict(
            {
                "id": list(self.content).index(asset_name) + 1,
                "name": asset_name,
                "state": "uploaded",
                "size": len(content),
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            },
            **changes,
        )

    def invoke(self):
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        script = self.root / "publish.py"
        actual = step_script("release-package", "publish", "Publish release assets")
        match = re.search(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", actual, re.DOTALL)
        self.assertIsNotNone(
            match, "Publication must execute the actual confined inline Python"
        )
        script.write_text(match[1], encoding="utf-8")
        runner = self.root / "runner.py"
        runner.write_text(API_RUNNER, encoding="utf-8")
        environment = dict(
            isolated_environment(self.root),
            API_STATE=str(self.state_path),
            GH_REPO="fixture/repo",
            RELEASE_TAG="v1.2.3",
            EVENT_NAME=self.event_name,
            PRERELEASE=self.prerelease,
            TRANSFER_ROOT=str(self.payload),
            PACKAGE_NAME="package.zip",
            TOOLKIT_NAME="toolkit.zip",
            EXPECTED_PACKAGE_SHA256=self.hashes["package.zip"],
            EXPECTED_TOOLKIT_SHA256=self.hashes["toolkit.zip"],
            TEST_PYTHON=sys.executable,
            TEST_STUB=str(self.root / "gh-stub.py"),
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(runner),
                str(self.root / "gh-stub.py"),
                str(script),
            ],
            env=environment,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.state = json.loads(self.state_path.read_text())
        self.assertTrue(
            self.state["trace"],
            f"API stub was not reached: {result.returncode}: {result.stderr}",
        )
        return result

    def mutations(self):
        return [entry for entry in self.state["trace"] if entry[0] != "GET"]

    def test_empty_partial_and_complete_payloads_resume(self):
        for existing in range(4):
            with self.subTest(existing=existing):
                self.state["assets"] = [
                    self.asset(name) for name in list(self.content)[:existing]
                ]
                self.state["trace"] = []
                self.state["release"]["prerelease"] = True
                result = self.invoke()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    sum(method == "POST" for method, _ in self.mutations()),
                    3 - existing,
                )
                self.assertEqual(
                    self.mutations()[-1], ["PATCH", "repos/fixture/repo/releases/42"]
                )

    def test_promotion_failure_reuses_all_assets_on_retry(self):
        self.state["promotion_failure"] = True
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(len(self.state["assets"]), 3)
        self.state["trace"] = []
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.mutations(), [["PATCH", "repos/fixture/repo/releases/42"]]
        )

    def test_partial_upload_failure_is_resumable_without_replacing_assets(self):
        self.state["upload_failure_name"] = "toolkit.zip"
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(
            [asset["name"] for asset in self.state["assets"]], ["package.zip"]
        )
        self.state["trace"] = []
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        uploads = [
            endpoint for method, endpoint in self.mutations() if method == "POST"
        ]
        self.assertEqual(len(uploads), 2)
        self.assertFalse(any("package.zip" in endpoint for endpoint in uploads))

    def test_absent_digest_streams_binary_by_asset_id(self):
        asset = self.asset("package.zip")
        del asset["digest"]
        self.state["assets"] = [asset]
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            ["GET", "repos/fixture/repo/releases/assets/1"], self.state["trace"]
        )
        self.assertEqual(len(list(self.payload.iterdir())), 3)

    def test_all_assets_are_classified_before_any_mutation(self):
        for changes in (
            {"digest": "sha256:broken"},
            {"digest": "sha256:" + "0" * 64},
            {"size": 99},
            {"state": "starter", "size": 1},
        ):
            with self.subTest(changes=changes):
                self.state["assets"] = [self.asset("toolkit.zip", **changes)]
                self.state["trace"] = []
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_absent_digest_mismatch_or_download_failure_refuses(self):
        for content in (b"wrong content", None):
            with self.subTest(content=content):
                asset = self.asset("package.zip")
                asset.pop("digest")
                self.state["assets"] = [asset]
                self.state["trace"] = []
                self.state["content"] = (
                    {} if content is None else {"package.zip": content.hex()}
                )
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_duplicate_and_unknown_assets_refuse_without_mutation(self):
        for assets in (
            [self.asset("package.zip"), self.asset("package.zip")],
            [self.asset("package.zip", name="unexpected.zip")],
        ):
            with self.subTest(assets=assets):
                self.state.update(assets=assets, trace=[])
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_empty_starter_requires_confirmation_and_only_its_id_is_deleted(self):
        self.state["assets"] = [self.asset("package.zip", state="starter", size=0)]
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.mutations()[0], ["DELETE", "repos/fixture/repo/releases/assets/1"]
        )
        self.assertIn(
            ["GET", "repos/fixture/repo/releases/assets/1"], self.state["trace"]
        )

    def test_changed_starter_is_never_deleted(self):
        self.state.update(
            assets=[self.asset("package.zip", state="starter", size=0)],
            starter_changed=True,
        )
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_remote_changes_prevent_promotion(self):
        for name in self.content:
            with self.subTest(asset=name):
                self.state.update(
                    assets=[self.asset(asset_name) for asset_name in self.content],
                    trace=[],
                    asset_reads=0,
                    asset_changed=name,
                )
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_exact_release_identity_and_published_status_are_revalidated(self):
        for changes in (
            {"id": 43},
            {"tag_name": "v9.9.9"},
            {"draft": True},
            {"published_at": None},
        ):
            with self.subTest(changes=changes):
                self.state.update(assets=[], trace=[], release_changed=changes)
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_stable_release_is_never_downgraded(self):
        self.state["release"]["prerelease"] = False
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(method == "PATCH" for method, _ in self.mutations()))

    def test_release_change_after_upload_prevents_promotion(self):
        self.state.update(
            release_changed={"tag_name": "v9.9.9"}, release_changed_after=2
        )
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(len(self.state["assets"]), 3)
        self.assertFalse(any(method == "PATCH" for method, _ in self.mutations()))

    def test_manual_or_initially_stable_event_does_not_promote(self):
        for event_name, prerelease in (
            ("workflow_dispatch", "true"),
            ("workflow_dispatch", "false"),
            ("release", "false"),
        ):
            with self.subTest(event=event_name, prerelease=prerelease):
                self.event_name, self.prerelease = event_name, prerelease
                self.state.update(assets=[], trace=[])
                self.assertEqual(self.invoke().returncode, 0)
                self.assertEqual(
                    self.mutations(),
                    [
                        [
                            "POST",
                            "https://uploads.github.com/repos/fixture/repo/releases/42"
                            f"/assets?name={name}",
                        ]
                        for name in self.content
                    ],
                )
                self.assertFalse(
                    any(method == "PATCH" for method, _ in self.mutations())
                )


class WindowsToolchainTests(unittest.TestCase):
    @unittest.skipUnless(
        os.name == "nt", "native .cmd toolchain fixtures require Windows"
    )
    def test_native_failures_stop_immediately_with_exact_code(self):
        for pip_status, npm_status, expected_calls, status in (
            (17, 0, ["pip"], 17),
            (0, 23, ["pip", "npm"], 23),
            (0, 0, ["pip", "npm", "patch"], 0),
        ):
            with (
                self.subTest(pip=pip_status, npm=npm_status),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                trace = root / "trace"
                native = root / "native.py"
                native.write_text(
                    "import os, sys\nfrom pathlib import Path\n"
                    'name = "npm" if sys.argv[1] == "npm" else ("pip" if "pip" in sys.argv else "patch")\n'
                    'with Path(os.environ["TRACE"]).open("a") as stream: stream.write(name + "\\n")\n'
                    'sys.exit(int(os.environ.get(name.upper() + "_STATUS", "0")))\n',
                    encoding="utf-8",
                )
                for command in ("python", "npm"):
                    (root / f"{command}.cmd").write_text(
                        f'@"{sys.executable}" "{native}" {command} %*\r\n@exit /b %errorlevel%\r\n',
                        encoding="utf-8",
                    )
                script = root / "install.ps1"
                script.write_text(
                    step_script(
                        "repository-audit",
                        "compatibility-windows",
                        "Install locked language toolchains",
                    ),
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [
                        shutil.which("pwsh") or "pwsh",
                        "-NoProfile",
                        "-File",
                        str(script),
                    ],
                    env=dict(
                        os.environ,
                        PATH=str(root) + os.pathsep + os.environ["PATH"],
                        TRACE=str(trace),
                        PIP_STATUS=str(pip_status),
                        NPM_STATUS=str(npm_status),
                    ),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(trace.read_text().splitlines(), expected_calls)


class PublicationConfinementTests(unittest.TestCase):
    def test_python_run_and_popen_refuse_unconfined_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canary = root / "canary"
            stub = root / "stub.py"
            stub.write_text(
                f"from pathlib import Path\nPath({str(canary)!r}).touch()\n",
                encoding="utf-8",
            )
            runner = root / "runner.py"
            runner.write_text(API_RUNNER, encoding="utf-8")
            script = root / "script.py"
            for operation in ("run", "Popen"):
                for command in (
                    ["gh", "api", "anything"],
                    ["timeout", "30s", "wrong-gh", "api"],
                ):
                    with self.subTest(operation=operation, command=command):
                        script.write_text(
                            f"import subprocess\nsubprocess.{operation}({command!r})\n",
                            encoding="utf-8",
                        )
                        result = subprocess.run(
                            [sys.executable, "-B", str(runner), str(stub), str(script)],
                            env=isolated_environment(root),
                            capture_output=True,
                            text=True,
                            timeout=10,
                            check=False,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(
                            "Unconfined external command refused", result.stderr
                        )
                        self.assertFalse(canary.exists())
            script.write_text(
                'import subprocess\nsubprocess.run(["timeout", "30s", "gh", "api", "local-canary"], check=True)\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, "-B", str(runner), str(stub), str(script)],
                env=isolated_environment(root),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(canary.is_file())

    def test_missing_or_incorrect_stub_stops_before_local_canary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canary = root / "canary"
            script = root / "canary.sh"
            script.write_text('printf reached > "$CANARY"\n', encoding="utf-8")
            for stub_path in (root / "missing", root / "wrong-path"):
                with self.subTest(stub=stub_path):
                    environment = dict(
                        isolated_environment(root),
                        TEST_BIN=str(stub_path),
                        CANARY=str(canary),
                    )
                    self.assertFalse(
                        any(
                            key.upper().startswith(("GH_", "GITHUB_"))
                            for key in environment
                            if key != "GH_CONFIG_DIR"
                        )
                    )
                    result = subprocess.run(
                        [BASH, "-c", CONFINED_BASH, "test", str(script)],
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 92, result.stderr)
                    self.assertFalse(canary.exists())
