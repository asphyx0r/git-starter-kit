from __future__ import annotations

import base64
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SOURCE_ROOT / "tools" / "build-release-package.ps1"
BASE_COMMIT = "ee1d79e1c0516ced2a5171e65e14bc0fef762ce5"
ARCHIVE_PREPARATION = "Add-Type -AssemblyName System.IO.Compression.FileSystem"
POST_BUILD_VALIDATION = "if ($zipEntries -notcontains $requiredFile) {"
REPLACEMENT = """[System.IO.File]::Replace(
            $temporaryPackagePath,
            $packagePath,
            $temporaryBackupPath
        )"""
PACKAGE_FIXTURE_PATHS = (
    ".github/workflows/agent-rules-update.yml",
    "_agent-rules-source.json",
    "starter-kit-manifest.json",
    "AGENTS.md",
    "BRANCH_RULES.md",
    "CODING_RULES.md",
    "COMMIT_RULES.md",
    "DOCUMENTATION_RULES.md",
    "LANGUAGE_RULES.md",
    "RELEASE_RULES.md",
    "tools/project_config.py",
    "tools/project_validation.py",
    "tools/automation_config.py",
    "tools/initialize-repository.py",
    "tools/git-inventory-context/HEAD",
    "tools/git-inventory-context/objects/.gitkeep",
    "tools/git-inventory-context/refs/.gitkeep",
    "tools/release-artifacts.py",
    "tools/git_objects.py",
    "tools/process_runner.py",
    "templates/release/repository-manifest.schema.json",
    "templates/GITHUB_RELEASE_NOTES.md",
    "tools/quality/requirements.in",
    "tools/quality/requirements.lock",
    "tools/repository-audit.sh",
    *tuple(
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in (SOURCE_ROOT / "tools/repository-audit").iterdir()
        if path.is_file()
    ),
    ".githooks/commit-msg",
    ".gitattributes",
    "LICENSE",
    "SECURITY.md",
    "CHANGELOG.md",
    ".agents/skills/git-commit-push-tag/SKILL.md",
    ".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt",
    "docs/guarded-pull-request-merges.md",
    *tuple(
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in (SOURCE_ROOT / "templates/project").rglob("*")
        if path.is_file()
    ),
)


class BuildReleasePackageTests(unittest.TestCase):
    _immutable_composed_package_bytes: bytes | None = None

    def test_content_hash_accepts_empty_bytes_but_rejects_null(self):
        definitions = SCRIPT_PATH.read_text(encoding="utf-8").split(
            "$repoRoot = (Resolve-Path", 1
        )[0]
        hosts = [host for host in ("pwsh", "powershell.exe") if shutil.which(host)]
        if not hosts:
            self.skipTest("PowerShell is required")
        for host in hosts:
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "empty").write_bytes(b"")
                (root / "nonempty").write_bytes(b"abc\n")
                script = self.write_script(
                    root,
                    definitions
                    + """
$emptyPath = Join-Path $PSScriptRoot 'empty'
$empty = [IO.File]::ReadAllBytes($emptyPath)
if ($null -eq $empty -or $empty.GetType() -ne [byte[]] -or $empty.Length -ne 0) {
    throw 'Expected an actual empty byte array.'
}
$metadata = Get-ContentMetadataRecord -Path $emptyPath
$nullRejected = $false
try { Get-Sha256ByteArray -Content $null | Out-Null }
catch {
    if ($_.FullyQualifiedErrorId -notlike 'ParameterArgumentValidationErrorNullNotAllowed,*') { throw }
    $nullRejected = $true
}
[ordered]@{
    empty = Get-Sha256ByteArray -Content $empty
    emptyCanonical = $metadata.canonicalSha256
    emptyKind = $metadata.contentKind
    nonempty = Get-Sha256ByteArray -Content ([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'nonempty')))
    nullRejected = $nullRejected
} | ConvertTo-Json -Compress
""",
                )
                result = subprocess.run(
                    [host, "-NoProfile", "-File", str(script)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout),
                    {
                        "empty": hashlib.sha256(b"").hexdigest(),
                        "emptyCanonical": hashlib.sha256(b"").hexdigest(),
                        "emptyKind": "text",
                        "nonempty": hashlib.sha256(b"abc\n").hexdigest(),
                        "nullRejected": True,
                    },
                )

    def test_composed_state_serializer_preserves_unicode_and_final_lf(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        serializer = source.split("    $starterStateSerializer = @'\n", 1)[1].split(
            "\n'@\n", 1
        )[0]
        definitions = source.split("$repoRoot = (Resolve-Path", 1)[0]
        value = {
            "source": "original",
            "current": "target",
            "files": [{"path": "tools/qualité-漢字.py"}],
        }
        hosts = [host for host in ("pwsh", "powershell.exe") if shutil.which(host)]
        if not hosts:
            self.skipTest("PowerShell is required")
        for host in hosts:
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                state_path = root / "state.json"
                state_path.write_text(
                    json.dumps(value, ensure_ascii=False), encoding="utf-8"
                )
                script = self.write_script(
                    root,
                    definitions
                    + "\n$starterStatePath = $env:QUALIFICATION_STATE_PATH\n"
                    + "$state = Get-Content -LiteralPath $starterStatePath -Raw -Encoding UTF8 | ConvertFrom-Json\n"
                    + "Write-Utf8NoBomFile -Path $starterStatePath -Content ($state | ConvertTo-Json -Depth 8)\n"
                    + "$starterStateSerializer = @'\n"
                    + serializer
                    + "\n'@\n"
                    + "$starterStateSerializer | & python -B - $starterStatePath\n"
                    + "if ($LASTEXITCODE -ne 0) { exit 1 }\n",
                )
                environment = os.environ.copy()
                environment["QUALIFICATION_STATE_PATH"] = str(state_path)
                result = subprocess.run(
                    [host, "-NoProfile", "-File", str(script)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    state_path.read_bytes(),
                    (json.dumps(value, indent=2, sort_keys=False) + "\n").encode(
                        "utf-8"
                    ),
                )

    @unittest.skipIf(os.name == "nt", "Unix setsid prerequisite")
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_missing_setsid_fails_before_launching_git(self):
        definitions = SCRIPT_PATH.read_text(encoding="utf-8").split(
            "$repoRoot = (Resolve-Path", 1
        )[0]
        harness = (
            definitions
            + """
function Get-Command {
    param([string]$Name)
    if ($Name -eq 'git') { [pscustomobject]@{ Source = '/not-started/git' } }
}
try {
    Invoke-GitLine -Arguments @('--version')
    throw 'missing prerequisite accepted'
}
catch {
    if ($_.Exception.Message -notmatch 'setsid .*required') { throw }
}
"""
        )
        with tempfile.TemporaryDirectory() as temporary:
            script = self.write_script(Path(temporary), harness)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script)],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_deadline_includes_pipes_inherited_by_a_started_descendant(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        definitions = source.split("$repoRoot = (Resolve-Path", 1)[0]
        # Native process startup precedes the execution and cleanup budget.
        self.assertEqual(definitions.count("$watch.Restart()"), 1)
        definitions = definitions.replace(
            "$watch.Restart()",
            "$watch.Restart()\n        $script:deadlineWatch.Restart()",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "descendant.pid"
            child_code = (
                "import os,pathlib,time; "
                f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
                "time.sleep(6)"
            )
            parent = root / "parent.py"
            parent.write_text(
                "import pathlib,subprocess,sys,time\n"
                f"subprocess.Popen([sys.executable,'-B','-c',{child_code!r}])\n"
                f"marker = pathlib.Path({str(marker)!r})\n"
                "while not (marker.exists() and marker.stat().st_size): time.sleep(0.01)\n",
                encoding="utf-8",
            )

            def literal(value):
                return "'" + str(value).replace("'", "''") + "'"

            harness = (
                definitions
                + f"""
function Get-Command {{
    param([string]$Name)
    if ($Name -eq 'git') {{ [pscustomobject]@{{ Source = {literal(sys.executable)} }} }}
    else {{ Microsoft.PowerShell.Core\\Get-Command $Name }}
}}
$deadlineWatch = [Diagnostics.Stopwatch]::new()
try {{
    Invoke-GitLine -Arguments @({literal(parent)}) -TimeoutSeconds 3
    throw 'deadline missing'
}}
catch {{
    if ($_.Exception.Message -notmatch 'timed out') {{ throw }}
}}
if (-not $deadlineWatch.IsRunning -or $deadlineWatch.Elapsed.TotalSeconds -ge 4) {{
    throw 'inherited pipes exceeded deadline'
}}
if (-not (Test-Path -LiteralPath {literal(marker)})) {{ throw 'descendant never started' }}
$childId = [int](Get-Content -LiteralPath {literal(marker)})
if ($childId -le 0) {{ throw 'descendant PID missing' }}
$child = Get-Process -Id $childId -ErrorAction SilentlyContinue
if ($null -ne $child -and -not $child.WaitForExit(1000)) {{ throw 'descendant survived cleanup' }}
"""
            )
            script = self.write_script(root, harness)
            for executable in ("pwsh", "powershell"):
                if not shutil.which(executable):
                    continue
                marker.unlink(missing_ok=True)
                result = subprocess.run(
                    [executable, "-NoProfile", "-File", str(script)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,  # Shell startup and Add-Type are outside the deadline.
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_latest_release_http_request_has_a_contextual_deadline(self):
        class SlowResponse(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(2)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *arguments):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), SlowResponse) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                source = SCRIPT_PATH.read_text(encoding="utf-8")
                definitions = source.split("$repoRoot = (Resolve-Path", 1)[0]
                definitions = definitions.replace(
                    "https://api.github.com", f"http://127.0.0.1:{server.server_port}"
                )
                harness = (
                    definitions
                    + """
$HttpTimeoutSeconds = 1
try {
    Get-GitHubLatestRelease -Repository 'test/repository'
    throw 'HTTP deadline missing'
}
catch {
    if ($_.Exception.Message -notmatch 'Unable to resolve latest agent rules release') { throw }
    $_.Exception.Message
}
"""
                )
                with tempfile.TemporaryDirectory() as temporary:
                    script = self.write_script(Path(temporary), harness)
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-File", str(script)],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=15,
                    )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("127.0.0.1", result.stdout)
            finally:
                server.shutdown()
                worker.join()

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_git_deadline_terminates_child_and_preserves_arguments(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        definitions = source.split("$repoRoot = (Resolve-Path", 1)[0]
        with tempfile.TemporaryDirectory(prefix="package process ") as temporary:
            root = Path(temporary)
            child = root / "native child.py"
            marker = root / "late-output.txt"
            child.write_text(
                "import json, pathlib, sys, time\n"
                "if sys.argv[1] == 'block':\n"
                "    time.sleep(2)\n"
                "    pathlib.Path(sys.argv[2]).write_text('alive')\n"
                "else:\n"
                "    print(json.dumps(sys.argv[1:]))\n"
                "    print('second line')\n",
                encoding="utf-8",
            )

            def literal(value):
                return "'" + str(value).replace("'", "''") + "'"

            harness = (
                definitions
                + f"""
function Get-Command {{
    param([string]$Name)
    if ($Name -eq 'git') {{ [pscustomobject]@{{ Source = {literal(sys.executable)} }} }}
    else {{ Microsoft.PowerShell.Core\\Get-Command $Name }}
}}
$lines = @(Invoke-GitLine -Arguments @({literal(child)}, 'space value', 'quote"value', 'tail\\'))
if ($lines.Count -ne 2) {{ throw 'stdout line semantics lost' }}
$lines[0]
try {{
    Invoke-GitLine -Arguments @({literal(child)}, 'block', {literal(marker)}) -TimeoutSeconds 0.1
    throw 'timeout was not raised'
}}
catch {{
    if ($_.Exception.Message -notmatch 'timed out') {{ throw }}
    'timed out'
}}
Start-Sleep -Seconds 3
if (Test-Path -LiteralPath {literal(marker)}) {{ throw 'child survived deadline' }}
"""
            )
            script = self.write_script(root, harness)
            for executable in ("pwsh", "powershell"):
                if not shutil.which(executable):
                    continue
                result = subprocess.run(
                    [executable, "-NoProfile", "-File", str(script)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(
                    json.loads(lines[0]), ["space value", 'quote"value', "tail\\"]
                )
                self.assertIn("timed out", lines)
            self.assertFalse(marker.exists())

    @classmethod
    def setUpClass(cls) -> None:
        cls._immutable_composed_package_bytes = None
        cls.base_script = subprocess.run(
            [
                "git",
                "show",
                f"{BASE_COMMIT}:tools/build-release-package.ps1",
            ],
            cwd=SOURCE_ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout

    def write_immutable_composed_package(self, root: Path) -> Path:
        package_bytes = type(self)._immutable_composed_package_bytes
        if package_bytes is None:
            with tempfile.TemporaryDirectory() as temporary:
                manufacturing = Path(temporary)
                result = self.run_package(SCRIPT_PATH, manufacturing)
                self.assertEqual(result.returncode, 0, result.stderr)
                package_bytes = (manufacturing / "existing.zip").read_bytes()
                type(self)._immutable_composed_package_bytes = package_bytes
        package = root / "existing.zip"
        package.write_bytes(package_bytes)
        return package

    def run_package(
        self,
        script_path: Path,
        output_directory: Path,
        environment: dict[str, str] | None = None,
        repository_root: Path = SOURCE_ROOT,
        powershell_executable: str = "pwsh",
        agent_rules_ref: str = "v1.42.0",
        upstream_override: str = "",
        starter_ref: str = "",
        repository_ref: str = "audit-remediation",
    ) -> subprocess.CompletedProcess[str]:
        output_directory.mkdir(parents=True, exist_ok=True)
        if repository_root == SOURCE_ROOT:
            environment = (environment or os.environ).copy()
            if "GIT_INDEX_FILE" not in environment:
                index_path = subprocess.run(
                    ["git", "rev-parse", "--git-path", "index"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                objects_path = subprocess.run(
                    ["git", "rev-parse", "--git-path", "objects"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                isolated_index = output_directory / "candidate-index"
                isolated_objects = output_directory / "candidate-objects"
                isolated_objects.mkdir()
                shutil.copyfile(SOURCE_ROOT / index_path, isolated_index)
                environment["GIT_INDEX_FILE"] = str(isolated_index)
                environment["GIT_OBJECT_DIRECTORY"] = str(isolated_objects)
                environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(
                    (SOURCE_ROOT / objects_path).resolve()
                )
            subprocess.run(
                [
                    "git",
                    "add",
                    "--",
                    "tools/initialize-repository.py",
                    "tools/project_config.py",
                    "tools/project_validation.py",
                    "tools/automation_config.py",
                    "templates/release/repository-manifest.schema.json",
                ],
                cwd=SOURCE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
        content = script_path.read_text(encoding="utf-8")
        if "function Resolve-AgentRulesRelease" in content:
            overrides = self.upstream_fixture(repository_root) + upstream_override
            content = content.replace(
                "$repoRoot = (Resolve-Path",
                overrides + "\n$repoRoot = (Resolve-Path",
                1,
            )
            script_path = self.write_script(output_directory, content)
        return subprocess.run(
            [
                powershell_executable,
                "-NoProfile",
                "-File",
                str(script_path),
                "-RepositoryRoot",
                str(repository_root),
                "-OutputDirectory",
                str(output_directory),
                "-PackageName",
                "existing.zip",
                "-RepositorySlug",
                "asphyx0r/git-starter-kit",
                "-RepositoryRef",
                repository_ref,
                "-AgentRulesRef",
                agent_rules_ref,
                *(
                    ["-StarterKitRef", starter_ref, "-StarterKitCommit", "a" * 40]
                    if starter_ref
                    else []
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    def upstream_fixture(self, repository_root: Path = SOURCE_ROOT) -> str:
        provenance = json.loads((SOURCE_ROOT / "_agent-rules-source.json").read_bytes())
        rules = provenance["agentRules"]
        files = "\n".join(
            f"$files['{name}'] = [Convert]::FromBase64String('{base64.b64encode((SOURCE_ROOT / name).read_bytes().replace(bytes([13, 10]), bytes([10]))).decode()}')"
            for name in rules["files"]
        )
        return f"""
function Get-GitHubLatestRelease {{
    $script:latestCalls += 1
    if ($script:latestCalls -gt 1) {{ throw "latest metadata requested more than once" }}
    [pscustomobject]@{{tag_name='{rules["ref"]}'; html_url='https://github.com/asphyx0r/agent-coding-rules/releases/tag/{rules["ref"]}'; published_at='2026-08-21T20:11:11Z'}}
}}
function Get-GitHubImmutableAgentRuleSet {{
    param($Repository, $Reference)
    $files = @{{}}
    {files}
    [ordered]@{{ Commit='{rules["commit"]}'; Files=$files }}
}}
$script:latestCalls = 0
"""

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_explicit_stale_rules_ref_is_rejected_after_one_latest_resolution(self):
        definitions = SCRIPT_PATH.read_text().split("$repoRoot = (Resolve-Path", 1)[0]
        harness = (
            definitions
            + self.upstream_fixture()
            + """
try {
    Resolve-AgentRulesRelease -RequestedRef 'v1.0.0' -Repository 'asphyx0r/agent-coding-rules'
    throw 'stale explicit rules accepted'
}
catch {
    if ($_.Exception.Message -notmatch 'latest published') { throw }
}
if ($latestCalls -ne 1) { throw 'latest must resolve exactly once' }
"""
        )
        with tempfile.TemporaryDirectory() as temporary:
            script = self.write_script(Path(temporary), harness)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_composed_project_configuration_and_final_file_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_immutable_composed_package(root)
            with zipfile.ZipFile(root / "existing.zip") as archive:
                config = json.loads(archive.read(".starter-kit-project.json"))
                self.assertEqual(config["repositoryRole"], "project")
                self.assertEqual(config["releaseKind"], "repository")
                self.assertTrue(
                    all(flag is False for flag in config["automations"].values())
                )
                self.assertEqual(config["checks"], [])
                self.assertFalse(
                    any(
                        name.startswith(
                            ("tests/", "docs/superpowers/", "templates/project/")
                        )
                        for name in archive.namelist()
                    )
                )
                import importlib.util

                spec = importlib.util.spec_from_file_location(
                    "package_manifest", SOURCE_ROOT / "tools/starter-kit-manifest.py"
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                state = json.loads(archive.read("starter-kit-manifest.json"))
                self.assertEqual(
                    archive.read("starter-kit-manifest.json"),
                    (json.dumps(state, indent=2, sort_keys=False) + "\n").encode(
                        "utf-8"
                    ),
                )
                module.validate_manifest(state)
                entries = json.loads(archive.read("_starter-kit-files.json"))["files"]
                for name in ("HEAD", "objects/.gitkeep", "refs/.gitkeep"):
                    relative = "tools/git-inventory-context/" + name
                    entry = next(item for item in entries if item["path"] == relative)
                    self.assertEqual(
                        (entry["mode"], entry["strategy"]), ("100644", "replace")
                    )
                    self.assertEqual(
                        archive.read(relative), (SOURCE_ROOT / relative).read_bytes()
                    )
                state_paths = {entry["path"] for entry in state["files"]}
                self.assertEqual(
                    state_paths,
                    {
                        entry["path"]
                        for entry in entries
                        if entry["strategy"] not in {"agent-rules", "starter-kit-state"}
                    },
                )
                self.assertEqual(
                    {entry["path"] for entry in entries},
                    {name for name in archive.namelist() if not name.endswith("/")}
                    - {"_starter-kit-files.json"},
                )
                for entry in entries:
                    self.assertEqual(
                        hashlib.sha256(archive.read(entry["path"])).hexdigest(),
                        entry["sha256"],
                    )
                    self.assertEqual(
                        module.content_metadata(archive.read(entry["path"])),
                        (entry["contentKind"], entry["canonicalSha256"]),
                    )
                    expected_mode = 0o100755 if entry["mode"] == "100755" else 0o100644
                    self.assertEqual(
                        archive.getinfo(entry["path"]).external_attr >> 16,
                        expected_mode,
                    )
                self.assertEqual(
                    next(
                        entry["strategy"]
                        for entry in entries
                        if entry["path"] == ".starter-kit-project.json"
                    ),
                    "initialize-only",
                )
                config_js = archive.read("commitlint.config.cjs").decode()
                self.assertNotIn('"scope-enum"', config_js)
                for name in (
                    "README.md",
                    "CONTRIBUTING.md",
                    "SECURITY.md",
                    "CODE_OF_CONDUCT.md",
                    "SUPPORT.md",
                    "tools/README.md",
                ):
                    self.assertNotIn("C:\\codex", archive.read(name).decode())
                for name in archive.namelist():
                    if name.endswith(".md") and name not in {
                        "AGENTS.md",
                        "CODING_RULES.md",
                        "COMMIT_RULES.md",
                        "DOCUMENTATION_RULES.md",
                        "LANGUAGE_RULES.md",
                        "BRANCH_RULES.md",
                        "RELEASE_RULES.md",
                    }:
                        for target in re.findall(
                            r"\[[^\]]*\]\(([^)]+)\)", archive.read(name).decode()
                        ):
                            if ":" not in target and not target.startswith("#"):
                                resolved = os.path.normpath(
                                    str(Path(name).parent / target.split("#")[0])
                                ).replace("\\", "/")
                                self.assertIn(
                                    resolved, archive.namelist(), f"{name}: {target}"
                                )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_unverifiable_latest_and_stale_canonical_provenance_refuse_publication(
        self,
    ):
        cases = (
            (
                "unavailable",
                "function Get-GitHubLatestRelease { throw 'upstream unavailable' }",
                "upstream unavailable",
            ),
            (
                "wrong commit",
                "function Get-GitHubImmutableAgentRuleSet { [ordered]@{Commit=('a' * 40); Files=@{}} }",
                "commit differs",
            ),
            ("stale source", "", "does not match requested ref"),
            ("modified rule", "", "differs from immutable upstream"),
            ("preserved customization", "", "differs from immutable upstream"),
            ("forged provenance hash", "", "provenance hash differs"),
            ("extra trailing newline", "", "differs from immutable upstream"),
        )
        for label, override, diagnostic in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repository = self.create_package_repository(root)
                provenance_path = repository / "_agent-rules-source.json"
                provenance = json.loads(provenance_path.read_bytes())
                if label == "stale source":
                    provenance["agentRules"]["ref"] = "v1.0.0"
                if label in {
                    "modified rule",
                    "preserved customization",
                    "extra trailing newline",
                }:
                    rule = repository / "AGENTS.md"
                    rule.write_bytes(
                        rule.read_bytes()
                        + (
                            b"\n"
                            if label == "extra trailing newline"
                            else b"\ncustom instructions\n"
                        )
                    )
                    if label == "preserved customization":
                        provenance["preservedFiles"] = [
                            {
                                "path": "AGENTS.md",
                                "canonicalSha256": hashlib.sha256(
                                    rule.read_bytes()
                                    .replace(b"\r\n", b"\n")
                                    .rstrip(b"\n")
                                    + b"\n"
                                ).hexdigest(),
                            }
                        ]
                if label == "forged provenance hash":
                    provenance["agentRules"]["fileHashes"]["AGENTS.md"] = "f" * 64
                provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
                destination = root / "existing.zip"
                destination.write_bytes(b"previous package")
                result = self.run_package(
                    SCRIPT_PATH,
                    root,
                    repository_root=repository,
                    upstream_override=override,
                )
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual(destination.read_bytes(), b"previous package")
                self.assert_no_temporary_archive(root)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_latest_rule_bytes_and_composed_commit_policy_are_authentic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.create_package_repository(root)
            # The declared Markdown checkout contract permits CRLF, but the ZIP keeps raw upstream LF blobs.
            for name in json.loads(
                (SOURCE_ROOT / "_agent-rules-source.json").read_bytes()
            )["agentRules"]["files"]:
                path = repository / name
                path.write_bytes(
                    path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                )
            result = self.run_package(
                SCRIPT_PATH, root, repository_root=repository, agent_rules_ref="latest"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(root / "existing.zip") as archive:
                provenance = json.loads(archive.read("_agent-rules-source.json"))
                self.assertEqual(provenance["agentRules"]["requestedRef"], "latest")
                for name in provenance["agentRules"]["files"]:
                    self.assertEqual(
                        archive.read(name),
                        (SOURCE_ROOT / name).read_bytes().replace(b"\r\n", b"\n"),
                    )
                config = root / "project-commitlint.config.cjs"
                config.write_bytes(archive.read("commitlint.config.cjs"))
            node = shutil.which("node") or "node"
            commitlint_cli = subprocess.check_output(
                [
                    node,
                    "-p",
                    "require.resolve('@commitlint/cli/cli.js', {paths: "
                    "[process.argv[1], ...process.env.PATH.split(require('node:path').delimiter)]})",
                    str(SOURCE_ROOT / "tools/quality"),
                ],
                text=True,
            ).strip()
            command = [
                node,
                commitlint_cli,
                "--config",
                str(config),
            ]
            policy_check = subprocess.run(
                [
                    command[0],
                    "-e",
                    "const assert = require('node:assert/strict'); "
                    "const source = require(process.argv[1]); "
                    "const project = require(process.argv[2]); "
                    "delete source.rules['scope-enum']; "
                    "assert.deepEqual(project, source);",
                    str(SOURCE_ROOT / "commitlint.config.cjs"),
                    str(config),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(policy_check.returncode, 0, policy_check.stderr)
            for message in (
                "feat(api): add health endpoint",
                "fix(auth): reject expired tokens",
                "chore(git): initialize repository",
                "docs(readme): document setup",
            ):
                result = subprocess.run(
                    command, input=message, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            for message in (
                "feat: missing scope",
                "feat(api) missing colon",
                "feat(api): " + "a" * 60,
                "unknown(api): invalid type",
                "feat(api): Invalid sentence",
            ):
                result = subprocess.run(
                    command, input=message, text=True, capture_output=True
                )
                self.assertNotEqual(result.returncode, 0, message)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_companion_toolkit_embeds_exact_composed_zip_and_legacy_config_is_reviewed(
        self,
    ):
        sys.path.insert(0, str(SOURCE_ROOT / "tools"))
        from starter_kit_upgrade.archive import (
            build_toolkit,
            build_upgrade,
            read_archive,
            load_upgrade,
        )
        from starter_kit_upgrade.planning import evaluate_target
        import argparse

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.run_package(SCRIPT_PATH, root, starter_ref="v9.0.0")
            self.assertEqual(result.returncode, 0, result.stderr)
            package = root / "existing.zip"
            toolkit = root / "toolkit.zip"
            build_toolkit(
                argparse.Namespace(new_package=package, output=toolkit, dry_run=False)
            )
            members = read_archive(toolkit)
            self.assertEqual(members["packages/existing.zip"], package.read_bytes())
            self.assertIn(
                b"python starter-kit-upgrade.py --dry-run plan", members["README.md"]
            )
            self.assertEqual(
                members["process_runner.py"],
                (SOURCE_ROOT / "tools/process_runner.py").read_bytes(),
            )
            files = read_archive(package)
            target = root / "legacy"
            target.mkdir()
            subprocess.run(["git", "init", "--quiet", str(target)], check=True)
            for name, content in files.items():
                if name != ".starter-kit-project.json":
                    path = target / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            base = root / "base.zip"
            with zipfile.ZipFile(base, "w") as archive:
                for name, content in files.items():
                    if name != ".starter-kit-project.json":
                        archive.writestr(name, content)
            patch = root / "upgrade.zip"
            build_upgrade(
                argparse.Namespace(
                    base_package=base, new_package=package, output=patch, dry_run=False
                )
            )
            manifest, payload = load_upgrade(patch)
            plan = evaluate_target(manifest, payload, target)
            entry = next(
                entry
                for entry in plan["actions"]
                if entry["path"] == ".starter-kit-project.json"
            )
            self.assertEqual(entry["action"], "review-initialize-only")
            self.assertFalse((target / ".starter-kit-project.json").exists())
            (target / ".starter-kit-project.json").write_text('{"project": "owned"}')
            plan = evaluate_target(manifest, payload, target)
            entry = next(
                entry
                for entry in plan["actions"]
                if entry["path"] == ".starter-kit-project.json"
            )
            self.assertEqual(entry["action"], "review-initialize-only")
            customized_policy = (
                files["commitlint.config.cjs"] + b"\n// project-owned policy\n"
            )
            policy = target / "commitlint.config.cjs"
            policy.write_bytes(customized_policy)
            plan = evaluate_target(manifest, payload, target)
            entry = next(
                entry
                for entry in plan["actions"]
                if entry["path"] == "commitlint.config.cjs"
            )
            self.assertEqual(entry["strategy"], "replace")
            self.assertEqual(entry["action"], "conflict-modified")
            self.assertEqual(policy.read_bytes(), customized_policy)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_immutable_upstream_reader_verifies_ref_commit_tree_and_raw_blob_identity(
        self,
    ):
        definitions = SCRIPT_PATH.read_text().split("$repoRoot = (Resolve-Path", 1)[0]
        rules = json.loads((SOURCE_ROOT / "_agent-rules-source.json").read_bytes())[
            "agentRules"
        ]["files"]
        content = b"immutable upstream instructions\n"
        blob_sha = hashlib.sha1(
            b"blob " + str(len(content)).encode() + b"\0" + content
        ).hexdigest()
        responses = {
            "repos/test/rules/git/ref/tags/v1.0.0": {
                "ref": "refs/tags/v1.0.0",
                "object": {"type": "tag", "sha": "c" * 40},
            },
            "repos/test/rules/git/tags/" + "c" * 40: {
                "sha": "c" * 40,
                "object": {"type": "commit", "sha": "a" * 40},
            },
            "repos/test/rules/git/commits/" + "a" * 40: {
                "sha": "a" * 40,
                "tree": {"sha": "b" * 40},
            },
            "repos/test/rules/git/trees/" + "b" * 40: {
                "sha": "b" * 40,
                "truncated": False,
                "tree": [
                    {"path": name, "mode": "100644", "type": "blob", "sha": blob_sha}
                    for name in rules
                ],
            },
            "repos/test/rules/git/blobs/" + blob_sha: {
                "sha": blob_sha,
                "encoding": "base64",
                "content": base64.b64encode(content).decode(),
            },
        }
        serialized = json.dumps(responses).replace("'", "''")
        harness = (
            definitions
            + f"""
$responses = ConvertFrom-Json '{serialized}'
function Get-GitHubApiResponse {{
    param($ApiPath)
    $property = $responses.PSObject.Properties[$ApiPath]
    if ($null -eq $property) {{ throw "unexpected API path: $ApiPath" }}
    $property.Value
}}
$value = Get-GitHubImmutableAgentRuleSet -Repository test/rules -Reference v1.0.0
if ($value.Commit -cne ('a' * 40) -or $value.Files.Count -ne 7) {{ throw 'immutable reader returned wrong snapshot' }}
if ([Convert]::ToBase64String($value.Files['AGENTS.md']) -cne '{base64.b64encode(content).decode()}') {{ throw 'rule bytes changed' }}
$blob = $responses.PSObject.Properties['repos/test/rules/git/blobs/{blob_sha}'].Value
$blob.content = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('forged bytes'))
try {{ Get-GitHubImmutableAgentRuleSet -Repository test/rules -Reference v1.0.0; throw 'forged blob accepted' }}
catch {{ if ($_.Exception.Message -notmatch 'blob digest mismatch') {{ throw }} }}
$blob.content = '{base64.b64encode(content).decode()}'
$commit = $responses.PSObject.Properties['repos/test/rules/git/commits/' + ('a' * 40)].Value
$commit.sha = 'd' * 40
try {{ Get-GitHubImmutableAgentRuleSet -Repository test/rules -Reference v1.0.0; throw 'wrong commit accepted' }}
catch {{ if ($_.Exception.Message -notmatch 'commit identity mismatch') {{ throw }} }}
"""
        )
        with tempfile.TemporaryDirectory() as temporary:
            script = self.write_script(Path(temporary), harness)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_distributed_runtime_imports_without_source_tests_or_manufacturing_helpers(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_immutable_composed_package(root)
            extracted = root / "consumer"
            with zipfile.ZipFile(root / "existing.zip") as archive:
                archive.extractall(extracted)
            self.assertFalse((extracted / "tests").exists())
            self.assertFalse((extracted / "tools/starter-kit-manifest.py").exists())
            self.assertFalse((extracted / "tools/starter-kit-upgrade.py").exists())
            code = """
import importlib.util, pathlib, sys
sys.path.insert(0, str(pathlib.Path('tools').resolve()))
import process_runner, git_objects, project_config, project_validation, automation_config
for name in ('initialize-repository.py', 'release-artifacts.py', 'repository-audit/workflow-contracts.py'):
    path = pathlib.Path('tools') / name
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
"""
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", code],
                cwd=extracted,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "bash"
            result = subprocess.run(
                [
                    bash,
                    "-c",
                    "source tools/repository-audit.sh; declare -F run_consumer_core run_project_checks check_workflow_contract",
                ],
                cwd=extracted,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_archive_byte_corruption_is_rejected_without_replacing_previous_package(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "existing.zip"
            destination.write_bytes(b"previous package")
            source = SCRIPT_PATH.read_text()
            marker = "    $zip = [System.IO.Compression.ZipFile]::OpenRead($temporaryPackagePath)"
            tamper = """
    $tampered = [IO.Compression.ZipFile]::Open($temporaryPackagePath, [IO.Compression.ZipArchiveMode]::Update)
    try {
        $tampered.GetEntry('README.md').Delete()
        $entry = $tampered.CreateEntry('README.md')
        $stream = $entry.Open()
        try { $stream.WriteByte(1) } finally { $stream.Dispose() }
    } finally { $tampered.Dispose() }
"""
            script = self.write_script(root, source.replace(marker, tamper + marker, 1))
            result = self.run_package(script, root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Composed archive byte mismatch: README.md", result.stderr)
            self.assertEqual(destination.read_bytes(), b"previous package")
            self.assert_no_temporary_archive(root)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_semver_missing_tracked_consumer_template_preserves_previous_zip(self):
        executables = ["pwsh"]
        if shutil.which("powershell.exe"):
            executables.append("powershell.exe")
        for executable in executables:
            for name in ("SECURITY.md", "CHANGELOG.md"):
                with self.subTest(executable=executable, template=name):
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        repository = self.create_package_repository(root)
                        tool = repository / "tools/starter-kit-manifest.py"
                        shutil.copyfile(
                            SOURCE_ROOT / "tools/starter-kit-manifest.py", tool
                        )
                        subprocess.run(
                            [
                                sys.executable,
                                "-B",
                                str(tool),
                                "prepare",
                                "--repository-root",
                                str(repository),
                                "--release-ref",
                                "v9.0.0",
                            ],
                            check=True,
                            capture_output=True,
                        )
                        subprocess.run(
                            ["git", "add", "--all"],
                            cwd=repository,
                            check=True,
                            capture_output=True,
                        )
                        subprocess.run(
                            [
                                "git",
                                "-c",
                                "user.name=Package Test",
                                "-c",
                                "user.email=test@example.com",
                                "commit",
                                "--quiet",
                                "-m",
                                "test: prepare release fixture",
                            ],
                            cwd=repository,
                            check=True,
                            capture_output=True,
                        )
                        subprocess.run(
                            ["git", "tag", "v9.0.0"], cwd=repository, check=True
                        )
                        if name == "SECURITY.md":
                            complete = root / "complete"
                            result = self.run_package(
                                SCRIPT_PATH,
                                complete,
                                repository_root=repository,
                                repository_ref="v9.0.0",
                                powershell_executable=executable,
                            )
                            self.assertEqual(result.returncode, 0, result.stderr)
                            with zipfile.ZipFile(complete / "existing.zip") as archive:
                                for document in ("SECURITY.md", "CHANGELOG.md"):
                                    self.assertEqual(
                                        archive.read(document),
                                        (
                                            repository / "templates/project" / document
                                        ).read_bytes(),
                                    )
                                self.assertIn(
                                    "templates/GITHUB_RELEASE_NOTES.md",
                                    archive.namelist(),
                                )
                        (repository / "templates/project" / name).unlink()
                        if executable == "pwsh" and name == "SECURITY.md":
                            # Missing templates reject before costly content authentication.
                            tracked_runtime = repository / "tools/project_validation.py"
                            tracked_runtime.write_bytes(
                                tracked_runtime.read_bytes() + b"\n# Modified fixture\n"
                            )
                        destination = root / "existing.zip"
                        destination.write_bytes(b"previous package")
                        result = self.run_package(
                            SCRIPT_PATH,
                            root,
                            repository_root=repository,
                            repository_ref="v9.0.0",
                            powershell_executable=executable,
                        )
                        self.assertNotEqual(result.returncode, 0, result.stdout)
                        self.assertIn(
                            "Tracked composed template is missing", result.stderr
                        )
                        self.assertEqual(destination.read_bytes(), b"previous package")
                        self.assert_no_temporary_archive(root)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_consumer_skill_and_initializer_dependencies_are_closed(self):
        import shlex
        import venv

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self.create_package_repository(root)
            result = self.run_package(SCRIPT_PATH, root, repository_root=repository)
            self.assertEqual(result.returncode, 0, result.stderr)
            consumer = root / "consumer"
            with zipfile.ZipFile(root / "existing.zip") as archive:
                self.assertEqual(
                    archive.read("templates/GITHUB_RELEASE_NOTES.md"),
                    (SOURCE_ROOT / "templates/GITHUB_RELEASE_NOTES.md").read_bytes(),
                )
                archive.extractall(consumer)
            readme = (consumer / "README.md").read_text()
            bootstrap = next(
                (
                    line
                    for line in readme.splitlines()
                    if line.startswith("python -m pip install ")
                ),
                "",
            )
            command = shlex.split(bootstrap)
            self.assertEqual(command[:4], ["python", "-m", "pip", "install"])
            self.assertIn("--require-hashes", command)
            self.assertEqual(command[-1], "tools/quality/requirements.lock")
            self.assertEqual(
                (consumer / command[-1]).read_bytes(),
                (SOURCE_ROOT / command[-1]).read_bytes(),
            )
            clean = root / "clean-python"
            venv.EnvBuilder(with_pip=False).create(clean)
            clean_python = clean / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            validation = [
                "-B",
                str(consumer / "tools/initialize-repository.py"),
                "validate",
                "--path",
                str(consumer),
            ]
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            result = subprocess.run(
                [str(clean_python), *validation],
                cwd=consumer,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("No module named 'jsonschema'", result.stderr)
            result = subprocess.run(
                [sys.executable, *validation],
                cwd=consumer,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_composed_zip_passes_source_smoke_distribution_contract(self):
        smoke = (SOURCE_ROOT / "tools/repository-audit/smoke.sh").read_text()
        marker = (
            '  "$python_cmd" - "$latest_package" <<\'PY\' || return\nimport hashlib'
        )
        code = "import hashlib" + smoke.split(marker, 1)[1].split("\nPY\n", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self.write_immutable_composed_package(root)
            result = subprocess.run(
                [sys.executable, "-B", "-c", code, str(package)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(package) as archive:
                members = {name: archive.read(name) for name in archive.namelist()}

            def wrong_strategy(data):
                inventory = json.loads(data["_starter-kit-files.json"])
                entry = next(
                    entry
                    for entry in inventory["files"]
                    if entry["path"] == "docs/project-configuration.md"
                )
                entry["strategy"] = "initialize-only"
                data["_starter-kit-files.json"] = json.dumps(inventory).encode()

            for name, mutation, expected in (
                (
                    "source-test",
                    lambda data: data.update({"tests/application.py": b"application"}),
                    "Starter-only files leaked",
                ),
                (
                    "missing-runtime",
                    lambda data: data.pop("tools/project_config.py"),
                    "Managed file missing",
                ),
                (
                    "digest",
                    lambda data: data.update({"README.md": b"tampered"}),
                    "digest mismatch",
                ),
                (
                    "strategy",
                    wrong_strategy,
                    "Required consumer runtime/resource must use replace",
                ),
            ):
                with self.subTest(mutation=name):
                    changed = members.copy()
                    mutation(changed)
                    damaged = root / f"{name}.zip"
                    with zipfile.ZipFile(damaged, "w") as archive:
                        for path, content in changed.items():
                            archive.writestr(path, content)
                    result = subprocess.run(
                        [sys.executable, "-B", "-c", code, str(damaged)],
                        text=True,
                        capture_output=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)

    def create_package_repository(self, parent: Path) -> Path:
        repository_root = parent / "git-starter-kit"
        repository_root.mkdir()
        for relative_path in PACKAGE_FIXTURE_PATHS:
            destination = repository_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE_ROOT / relative_path, destination)
        future_module = repository_root / "tools" / "starter_kit_upgrade" / "future.py"
        future_module.parent.mkdir(parents=True)
        future_module.write_text("future = True\n", encoding="utf-8")
        subprocess.run(
            ["git", "init", "--quiet"],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "https://github.com/asphyx0r/git-starter-kit.git",
            ],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
        )
        subprocess.run(
            ["git", "add", "--all"],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
        )
        if os.name != "nt":
            for name in (".githooks/commit-msg", "tools/repository-audit.sh"):
                (repository_root / name).chmod(0o755)
        subprocess.run(
            [
                "git",
                "update-index",
                "--chmod=+x",
                ".githooks/commit-msg",
                "tools/repository-audit.sh",
            ],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Package Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--quiet",
                "-m",
                "test: create package fixture",
            ],
            cwd=repository_root,
            capture_output=True,
            check=True,
            text=True,
        )
        return repository_root

    def write_script(self, directory: Path, content: str) -> Path:
        script_path = directory / "build-release-package.ps1"
        script_path.write_text(content, encoding="utf-8", newline="\n")
        return script_path

    def assert_no_temporary_archive(self, directory: Path) -> None:
        self.assertEqual(list(directory.glob(".existing.*.zip.tmp")), [])
        self.assertEqual(list(directory.glob(".existing.*.zip.bak")), [])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_full_package_applies_source_only_and_merge_policy(self) -> None:
        upgrade_module_paths = {
            "tools/starter_kit_upgrade/__init__.py",
            "tools/starter_kit_upgrade/application.py",
            "tools/starter_kit_upgrade/archive.py",
            "tools/starter_kit_upgrade/cli.py",
            "tools/starter_kit_upgrade/common.py",
            "tools/starter_kit_upgrade/planning.py",
        }
        source_only_paths = {
            ".github/CODEOWNERS",
            "tests/test_build_release_package.py",
            *upgrade_module_paths,
        }
        actual_upgrade_module_paths = {
            path.relative_to(SOURCE_ROOT).as_posix()
            for path in (SOURCE_ROOT / "tools" / "starter_kit_upgrade").iterdir()
            if path.is_file()
        }
        self.assertEqual(actual_upgrade_module_paths, upgrade_module_paths)
        merge_path = ".github/dependabot.yml"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            alternate_index = temporary_path / "index"
            alternate_objects = temporary_path / "objects"
            alternate_objects.mkdir()
            git_index = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "index"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            git_objects = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "objects"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            if not git_index.is_absolute():
                git_index = SOURCE_ROOT / git_index
            if not git_objects.is_absolute():
                git_objects = SOURCE_ROOT / git_objects
            shutil.copyfile(git_index, alternate_index)
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(alternate_index)
            environment["GIT_OBJECT_DIRECTORY"] = str(alternate_objects)
            environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(git_objects)
            subprocess.run(
                [
                    "git",
                    "add",
                    "--",
                    ".github/CODEOWNERS",
                    ".github/dependabot.yml",
                    "tests/test_build_release_package.py",
                    "tools/starter_kit_upgrade",
                ],
                cwd=SOURCE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            result = self.run_package(
                SCRIPT_PATH,
                temporary_path,
                environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(temporary_path / "existing.zip") as archive:
                archive_names = set(archive.namelist())
                self.assertTrue(source_only_paths.isdisjoint(archive_names))
                self.assertFalse(
                    any(
                        path.startswith("tools/starter_kit_upgrade/")
                        for path in archive_names
                    )
                )
                self.assertIn(merge_path, archive_names)
                file_manifest = json.load(archive.open("_starter-kit-files.json"))
            strategies = {
                entry["path"]: entry["strategy"] for entry in file_manifest["files"]
            }
            self.assertEqual(strategies[merge_path], "merge")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_full_package_excludes_future_upgrade_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repository_root = self.create_package_repository(temporary_path)
            output_directory = temporary_path / "output"

            result = self.run_package(
                SCRIPT_PATH,
                output_directory,
                repository_root=repository_root,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output_directory / "existing.zip") as archive:
                self.assertNotIn(
                    "tools/starter_kit_upgrade/future.py",
                    archive.namelist(),
                )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_full_package_replaces_complete_audit_runtime(self) -> None:
        audit_paths = {"tools/repository-audit.sh"} | {
            f"tools/repository-audit/{name}"
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
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            alternate_index = temporary_path / "index"
            alternate_objects = temporary_path / "objects"
            alternate_objects.mkdir()
            git_index = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "index"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            git_objects = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "objects"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            if not git_index.is_absolute():
                git_index = SOURCE_ROOT / git_index
            if not git_objects.is_absolute():
                git_objects = SOURCE_ROOT / git_objects
            shutil.copyfile(git_index, alternate_index)
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(alternate_index)
            environment["GIT_OBJECT_DIRECTORY"] = str(alternate_objects)
            environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(git_objects)
            subprocess.run(
                [
                    "git",
                    "add",
                    "--",
                    "tools/repository-audit",
                    "tests/test_agent_rules_transfer.sh",
                ],
                cwd=SOURCE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )

            result = self.run_package(SCRIPT_PATH, temporary_path, environment)

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(temporary_path / "existing.zip") as archive:
                self.assertTrue(audit_paths.issubset(archive.namelist()))
                file_manifest = json.load(archive.open("_starter-kit-files.json"))
            strategies = {
                entry["path"]: entry["strategy"] for entry in file_manifest["files"]
            }
            self.assertEqual(
                {path: strategies[path] for path in audit_paths},
                {path: "replace" for path in audit_paths},
            )
            self.assertNotIn("tests/test_agent_rules_transfer.sh", strategies)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_full_package_replaces_quality_configuration(self) -> None:
        quality_paths = {
            "tools/quality/check-versions.py",
            "tools/quality/install-external-tools.py",
            "tools/quality/package-lock.json",
            "tools/quality/package.json",
            "tools/quality/PSScriptAnalyzerSettings.psd1",
            "tools/quality/pyproject.toml",
            "tools/quality/requirements.in",
            "tools/quality/requirements.lock",
            "tools/quality/versions.json",
            "tools/quality/yamllint.yaml",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            alternate_index = temporary_path / "index"
            alternate_objects = temporary_path / "objects"
            alternate_objects.mkdir()
            git_index = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "index"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            git_objects = Path(
                subprocess.run(
                    ["git", "rev-parse", "--git-path", "objects"],
                    cwd=SOURCE_ROOT,
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            if not git_index.is_absolute():
                git_index = SOURCE_ROOT / git_index
            if not git_objects.is_absolute():
                git_objects = SOURCE_ROOT / git_objects
            shutil.copyfile(git_index, alternate_index)
            environment = os.environ.copy()
            environment["GIT_INDEX_FILE"] = str(alternate_index)
            environment["GIT_OBJECT_DIRECTORY"] = str(alternate_objects)
            environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(git_objects)
            subprocess.run(
                ["git", "add", "--", *sorted(quality_paths)],
                cwd=SOURCE_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )

            result = self.run_package(SCRIPT_PATH, temporary_path, environment)

            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(temporary_path / "existing.zip") as archive:
                self.assertEqual(
                    {
                        path
                        for path in archive.namelist()
                        if path.startswith("tools/quality/")
                    },
                    quality_paths,
                )
                file_manifest = json.load(archive.open("_starter-kit-files.json"))
            strategies = {
                entry["path"]: entry["strategy"] for entry in file_manifest["files"]
            }
            self.assertEqual(
                {path: strategies[path] for path in quality_paths},
                {path: "replace" for path in quality_paths},
            )
            self.assertEqual(
                {path for path in strategies if path.startswith("tools/quality/")},
                quality_paths,
            )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_base_archive_preparation_failure_deletes_existing_destination(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")
            historical_repository = temporary_path / "historical-source"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    SOURCE_ROOT,
                    historical_repository,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            subprocess.run(
                [
                    "git",
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/asphyx0r/git-starter-kit.git",
                ],
                cwd=historical_repository,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            # The unchanged historical builder predates the static Git context.
            context_paths = (
                "tools/git-inventory-context/HEAD",
                "tools/git-inventory-context/objects/.gitkeep",
                "tools/git-inventory-context/refs/.gitkeep",
            )
            subprocess.run(
                ["git", "rm", "--", *context_paths],
                cwd=historical_repository,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            self.assertTrue(
                all(
                    not (historical_repository / path).exists()
                    for path in context_paths
                )
            )
            tracked = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=historical_repository,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            ).stdout.split("\0")
            self.assertTrue(set(context_paths).isdisjoint(tracked))
            base_script = self.write_script(
                temporary_path,
                self.base_script.replace(
                    ARCHIVE_PREPARATION,
                    'throw "simulated archive preparation failure"',
                    1,
                ),
            )

            result = self.run_package(
                base_script, temporary_path, repository_root=historical_repository
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("simulated archive preparation failure", result.stderr)
            self.assertFalse(existing_archive.exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_archive_preparation_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")
            script_path = self.write_script(
                temporary_path,
                SCRIPT_PATH.read_text(encoding="utf-8").replace(
                    ARCHIVE_PREPARATION,
                    'throw "simulated archive preparation failure"',
                    1,
                ),
            )

            result = self.run_package(script_path, temporary_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("simulated archive preparation failure", result.stderr)
            self.assertEqual(existing_archive.read_bytes(), b"previous release package")
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_post_build_validation_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")
            script_content = SCRIPT_PATH.read_text(encoding="utf-8")
            self.assertIn(POST_BUILD_VALIDATION, script_content)
            script_path = self.write_script(
                temporary_path,
                script_content.replace(POST_BUILD_VALIDATION, "if ($true) {", 1),
            )

            result = self.run_package(script_path, temporary_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Release package archive is missing required file", result.stderr
            )
            self.assertEqual(existing_archive.read_bytes(), b"previous release package")
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_successful_build_replaces_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")

            result = self.run_package(SCRIPT_PATH, temporary_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(
                existing_archive.read_bytes(), b"previous release package"
            )
            with zipfile.ZipFile(existing_archive) as archive:
                self.assertIsNone(archive.testzip())
                state = json.loads(archive.read("starter-kit-manifest.json"))
                self.assertEqual(
                    archive.read("starter-kit-manifest.json"),
                    (json.dumps(state, indent=2, sort_keys=False) + "\n").encode(
                        "utf-8"
                    ),
                )
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is required.",
    )
    def test_successful_build_replaces_destination_with_windows_powershell_5_1(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")

            result = self.run_package(
                SCRIPT_PATH,
                temporary_path,
                powershell_executable="powershell.exe",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(
                existing_archive.read_bytes(), b"previous release package"
            )
            with zipfile.ZipFile(existing_archive) as archive:
                self.assertIsNone(archive.testzip())
                state = json.loads(archive.read("starter-kit-manifest.json"))
                self.assertEqual(
                    archive.read("starter-kit-manifest.json"),
                    (json.dumps(state, indent=2, sort_keys=False) + "\n").encode(
                        "utf-8"
                    ),
                )
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_successful_build_publishes_when_destination_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)

            result = self.run_package(SCRIPT_PATH, temporary_path)

            archive_path = temporary_path / "existing.zip"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
            self.assert_no_temporary_archive(temporary_path)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required.")
    def test_replacement_failure_preserves_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            existing_archive = temporary_path / "existing.zip"
            existing_archive.write_bytes(b"previous release package")
            script_content = SCRIPT_PATH.read_text(encoding="utf-8")
            self.assertIn(REPLACEMENT, script_content)
            script_path = self.write_script(
                temporary_path,
                script_content.replace(
                    REPLACEMENT,
                    'throw "simulated replacement failure"',
                    1,
                ),
            )

            result = self.run_package(script_path, temporary_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("simulated replacement failure", result.stderr)
            self.assertEqual(existing_archive.read_bytes(), b"previous release package")
            self.assert_no_temporary_archive(temporary_path)


if __name__ == "__main__":
    unittest.main()
