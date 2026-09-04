#!/usr/bin/env bash

check_semver_pattern_drift() {
  local node_cmd="$1"

  "$node_cmd" <<'JS'
const fs = require("fs");

function readFile(path) {
  return fs.readFileSync(path, "utf8").replace(/\r/g, "");
}
function extractSingle(path, pattern, label) {
  const match = readFile(path).match(pattern);
  if (!match) {
    throw new Error("Unable to extract " + label + ".");
  }

  return match[1];
}

function extractFragmentedShellPattern(path, label, variable = "semver_tag_pattern") {
  const parts = [];
  const expression = new RegExp(
    "^\\s*" + variable + "\\+?='([^']+)'",
    "gm"
  );
  const content = readFile(path);
  let match = expression.exec(content);
  while (match) {
    parts.push(match[1]);
    match = expression.exec(content);
  }

  if (parts.length === 0) {
    throw new Error("Unable to extract " + label + " SemVer pattern.");
  }

  return parts.join("");
}

function extractPythonPattern(path, label) {
  const content = readFile(path);
  const block = content.match(
    /^SEMVER_TAG_PATTERN = re\.compile\(\n([\s\S]*?)^\)$/m
  );
  if (!block) {
    throw new Error("Unable to extract " + label + " SemVer pattern.");
  }

  const parts = [];
  const expression = /^\s*r"([^"]*)"$/gm;
  let match = expression.exec(block[1]);
  while (match) {
    parts.push(match[1]);
    match = expression.exec(block[1]);
  }

  if (parts.length === 0) {
    throw new Error("Unable to extract " + label + " SemVer fragments.");
  }

  return parts.join("");
}

const patterns = new Map([
  [
    "tools/git-init.sh",
    extractSingle(
      "tools/git-init.sh",
      /^semver_tag_pattern='([^']+)'$/m,
      "Bash init SemVer pattern"
    ),
  ],
  [
    "tools/git-init.ps1",
    extractSingle(
      "tools/git-init.ps1",
      /^\$SemVerTagPattern = "([^"]+)"$/m,
      "PowerShell init SemVer pattern"
    ),
  ],
  [
    "tools/backup-target-directory.py",
    extractPythonPattern("tools/backup-target-directory.py", "Python backup"),
  ],
]);

patterns.set(
  "tools/starter-kit-manifest.py",
  extractPythonPattern(
    "tools/starter-kit-manifest.py",
    "starter manifest"
  )
);
patterns.set(
  "tools/release-artifacts.py",
  extractPythonPattern("tools/release-artifacts.py", "release artifacts")
);
patterns.set(
  "tools/repository-audit/hooks.sh",
  extractFragmentedShellPattern(
    "tools/repository-audit/hooks.sh",
    "pre-push hook",
    "hook_semver_tag_pattern"
  )
);

if (fs.existsSync("tools/build-release-package.ps1")) {
  patterns.set(
    "tools/build-release-package.ps1",
    extractSingle(
      "tools/build-release-package.ps1",
      /^\$SemVerTagPattern = "([^"]+)"$/m,
      "release package SemVer pattern"
    )
  );
}
if (fs.existsSync(".github/workflows/release-package.yml")) {
  patterns.set(
    ".github/workflows/release-package.yml",
    extractFragmentedShellPattern(
      ".github/workflows/release-package.yml",
      "release workflow"
    )
  );
}

const expected = patterns.values().next().value;
for (const [source, pattern] of patterns) {
  if (pattern !== expected) {
    console.error("SemVer validation pattern drift in " + source + ".");
    process.exit(1);
  }
}
JS
}

check_release_package_portability() {
  local workflow_path="${1:-.github/workflows/release-package.yml}"
  local python_cmd

  if [ ! -f "$workflow_path" ]; then
    printf 'Release package workflow is missing: %s\n' "$workflow_path" >&2
    return 1
  fi

  python_cmd="$(resolve_command python python3 python.exe)"
  if ! "$python_cmd" - "$workflow_path" <<'PY'
import re
import sys
from pathlib import Path

workflow_path = Path(sys.argv[1])
text = workflow_path.read_text(encoding="utf-8").replace("\r\n", "\n")
lines = text.splitlines(keepends=True)


def reject(message: str) -> None:
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    raise SystemExit(1)


try:
    jobs_index = lines.index("jobs:\n")
except ValueError:
    reject("Release package workflow job graph changed.")

top_level = "".join(lines[:jobs_index])
job_headers = [
    (index, match.group(1))
    for index, line in enumerate(lines[jobs_index + 1 :], jobs_index + 1)
    if (match := re.fullmatch(r"  ([A-Za-z0-9_-]+):\n", line))
]
job_names = [name for _, name in job_headers]
if job_names != ["build", "publish"]:
    reject("Release package workflow job graph changed.")

job_blocks: dict[str, str] = {}
for position, (start, name) in enumerate(job_headers):
    end = job_headers[position + 1][0] if position + 1 < len(job_headers) else len(lines)
    job_blocks[name] = "".join(lines[start:end])

build = job_blocks["build"]
publish = job_blocks["publish"]

try:
    on_start = top_level.index('"on":\n')
    permissions_start = top_level.index("permissions:\n")
except ValueError:
    reject("Release package workflow trigger contract changed.")
on_block = top_level[on_start:permissions_start]
event_names = re.findall(r"(?m)^  ([A-Za-z0-9_-]+):", on_block)
if event_names != ["release", "workflow_dispatch"]:
    reject("Release package workflow trigger contract changed.")
if "    types: [published]\n" not in on_block:
    reject("Release package workflow trigger contract changed.")
input_names = re.findall(r"(?m)^      ([A-Za-z0-9_-]+):\n", on_block)
if input_names != ["tag", "agent_rules_ref"]:
    reject("Release package workflow trigger contract changed.")
for position, input_name in enumerate(input_names):
    start = on_block.index(f"      {input_name}:\n")
    if position + 1 < len(input_names):
        end = on_block.index(f"      {input_names[position + 1]}:\n")
    else:
        end = len(on_block)
    input_block = on_block[start:end]
    if "        required: true\n" not in input_block:
        reject("Release package workflow trigger contract changed.")
    if "        type: string\n" not in input_block:
        reject("Release package workflow trigger contract changed.")


def parse_steps(job: str) -> list[tuple[str, str]]:
    job_lines = job.splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(job_lines)
        if re.match(r"^      - ", line)
    ]
    steps = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(job_lines)
        block = "".join(job_lines[start:end])
        name_match = re.match(r"^      - name: ([^\n]+)\n", block)
        steps.append((name_match.group(1) if name_match else "", block))
    return steps


build_steps = parse_steps(build)
publish_steps = parse_steps(publish)
if [name for name, _ in build_steps] != [
    "Checkout release tag",
    "Set up Python",
    "Set up Node.js",
    "Install locked quality dependencies",
    "Resolve release inputs",
    "Build package",
    "Validate composed package",
    "Build upgrade toolkit",
    "Seal release payload",
    "Upload sealed release payload",
]:
    reject("Release package workflow job graph changed.")
if [name for name, _ in publish_steps] != [
    "Download sealed release payload",
    "Verify sealed release payload",
    "Publish release assets",
]:
    reject("Release package workflow job graph changed.")
build_step_blocks = dict(build_steps)
publish_step_blocks = dict(publish_steps)

if not re.search(r"(?m)^permissions:\n  contents: read\n(?:\n|$)", top_level):
    reject("Release package workflow privilege boundary changed.")
if text.count("contents: write") != 1 or "    contents: write\n" not in publish:
    reject("Release package workflow privilege boundary changed.")
if "contents: write" in build:
    reject("Release package workflow privilege boundary changed.")
if text.count("environment: release") != 1 or "    environment: release\n" not in publish:
    reject("Release package workflow privilege boundary changed.")
if "environment:" in build:
    reject("Release package workflow privilege boundary changed.")

if "    needs: build\n" not in publish:
    reject("Release package workflow job graph changed.")
canonical_guard = "github.repository == 'asphyx0r/git-starter-kit'"
if build.count(canonical_guard) != 1 or publish.count(canonical_guard) != 1:
    reject("Release package workflow job graph changed.")
if "    runs-on: ubuntu-24.04\n" not in build or "    runs-on: ubuntu-24.04\n" not in publish:
    reject("Release package workflow job graph changed.")
if "    timeout-minutes: 30\n" not in build or "    timeout-minutes: 5\n" not in publish:
    reject("Release package workflow job graph changed.")
expected_concurrency = (
    "concurrency:\n"
    "  group: release-package-${{ github.event_name == 'release' && "
    "github.event.release.tag_name || inputs.tag }}\n"
    "  cancel-in-progress: false\n"
)
if expected_concurrency not in top_level:
    reject("Release package workflow concurrency changed.")

action_revisions = {
    "checkout": "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "setup-python": "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
    "setup-node": "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
    "upload-artifact": "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "download-artifact": "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
}
for action, revision in action_revisions.items():
    if text.count(revision) != 1:
        reject("Release package workflow runtime setup changed.")
    if re.search(
        rf"(?m)^\s+uses: actions/{re.escape(action)}@"
        rf"(?!{revision.split('@', 1)[1]})",
        text,
    ):
        reject("Release package workflow runtime setup changed.")
if "          python-version: \"3.11\"\n" not in build:
    reject("Release package workflow runtime setup changed.")
if "          node-version: \"24.20.0\"\n" not in build:
    reject("Release package workflow runtime setup changed.")
if re.search(r"(?m)^\s+cache:", text):
    reject("Release package workflow runtime setup changed.")
if action_revisions["checkout"] in publish:
    reject("Release package workflow runtime setup changed.")

if "          fetch-depth: 0\n" not in build or "          persist-credentials: false\n" not in build:
    reject("Release package workflow checkout boundary changed.")
if "persist-credentials: true" in text:
    reject("Release package workflow checkout boundary changed.")

if build.count("python -m pip install") != 1 or build.count("npm ci") != 1:
    reject("Release package workflow dependency installation changed.")
for required_install_fragment in (
    "--disable-pip-version-check",
    "--no-input",
    "--require-hashes",
    "-r tools/quality/requirements.lock",
    "npm ci --ignore-scripts --prefix tools/quality",
    "tools/quality/node_modules/.bin/markdownlint-cli2",
    "python -m codespell --config .codespellrc .",
):
    if required_install_fragment not in build:
        reject("Release package workflow dependency installation changed.")
if "npx --yes" in build or "codespell==" in build:
    reject("Release package workflow dependency installation changed.")

outputs_match = re.search(r"(?m)^    outputs:\n((?:^      [^\n]+\n)+)", build)
if outputs_match is None:
    reject("Release package workflow transport contract changed.")
output_lines = [line.strip() for line in outputs_match.group(1).splitlines()]
expected_outputs = {
    "release_tag: ${{ steps.refs.outputs.starter_ref }}",
    "package_name: ${{ steps.seal.outputs.package_name }}",
    "toolkit_name: ${{ steps.seal.outputs.toolkit_name }}",
    "package_sha256: ${{ steps.seal.outputs.package_sha256 }}",
    "toolkit_sha256: ${{ steps.seal.outputs.toolkit_sha256 }}",
}
if set(output_lines) != expected_outputs or len(output_lines) != len(expected_outputs):
    reject("Release package workflow transport contract changed.")

for step_id in ("seal", "verify", "publish"):
    if text.count(f"        id: {step_id}\n") != 1:
        reject("Release package workflow transport contract changed.")
for fragment in (
    "os.scandir",
    "stat.S_ISREG",
    "is_symlink()",
    "cmp -s",
    "sha256sum --check --strict",
):
    if text.count(fragment) < 2:
        reject("Release package workflow transport contract changed.")
if text.count("sha256sum --check --strict") != 2:
    reject("Release package workflow transport contract changed.")

upload_block_match = re.search(
    rf"(?ms)^      - name: Upload sealed release payload\n.*?"
    rf"uses: {re.escape(action_revisions['upload-artifact'])}\n(.*?)(?=^  publish:)",
    text,
)
if upload_block_match is None:
    reject("Release package workflow transport contract changed.")
upload_block = upload_block_match.group(1)
path_match = re.search(r"(?m)^          path: \|\n((?:^            [^\n]+\n)+)", upload_block)
if path_match is None:
    reject("Release package workflow transport contract changed.")
upload_paths = [line.strip() for line in path_match.group(1).splitlines()]
expected_paths = [
    "${{ runner.temp }}/release-package-transfer/${{ steps.seal.outputs.package_name }}",
    "${{ runner.temp }}/release-package-transfer/${{ steps.seal.outputs.toolkit_name }}",
    "${{ runner.temp }}/release-package-transfer/SHA256SUMS",
]
if upload_paths != expected_paths or any("*" in path for path in upload_paths):
    reject("Release package workflow transport contract changed.")
if "          if-no-files-found: error\n" not in upload_block:
    reject("Release package workflow transport contract changed.")
if "name: release-package-${{ steps.refs.outputs.starter_ref }}" not in upload_block:
    reject("Release package workflow transport contract changed.")
if "name: release-package-${{ needs.build.outputs.release_tag }}" not in publish:
    reject("Release package workflow transport contract changed.")
if "path: ${{ runner.temp }}/release-package-publish" not in publish:
    reject("Release package workflow transport contract changed.")
if "zipfile" in publish or re.search(r"(?m)^\s+(?:unzip|source|bash|python\s+[^-])", publish):
    reject("Release package workflow transport contract changed.")

auth_env_lines = re.findall(r"(?m)^\s+(?:GITHUB_TOKEN|GH_TOKEN):.*$", text)
if auth_env_lines != [
    "          GITHUB_TOKEN: ${{ github.token }}",
    "          GH_TOKEN: ${{ github.token }}",
]:
    reject("Release package workflow publication contract changed.")
if "          GH_REPO: ${{ github.repository }}\n" not in publish:
    reject("Release package workflow publication contract changed.")
if "GITHUB_TOKEN:" in publish or "GH_TOKEN:" not in publish:
    reject("Release package workflow publication contract changed.")
if "GITHUB_TOKEN:" not in build or "GH_TOKEN:" in build:
    reject("Release package workflow publication contract changed.")
build_package_step = build_step_blocks["Build package"]
publish_assets_step = publish_step_blocks["Publish release assets"]
if build_package_step.count("GITHUB_TOKEN: ${{ github.token }}") != 1:
    reject("Release package workflow publication contract changed.")
if "GH_TOKEN:" in build_package_step or "GH_REPO:" in build_package_step:
    reject("Release package workflow publication contract changed.")
if publish_assets_step.count("GH_TOKEN: ${{ github.token }}") != 1:
    reject("Release package workflow publication contract changed.")
if publish_assets_step.count("GH_REPO: ${{ github.repository }}") != 1:
    reject("Release package workflow publication contract changed.")
for step_name, step_block in build_steps + publish_steps:
    if step_name not in {"Build package", "Publish release assets"} and re.search(
        r"(?m)^\s+(?:GITHUB_TOKEN|GH_TOKEN|GH_REPO):",
        step_block,
    ):
        reject("Release package workflow publication contract changed.")
if "--clobber" in text:
    reject("Release package workflow publication contract changed.")
if publish.count('gh release upload "$RELEASE_TAG"') != 1:
    reject("Release package workflow publication contract changed.")
if publish.count('gh release edit "$RELEASE_TAG"') != 1:
    reject("Release package workflow publication contract changed.")
if publish.count('--repo "$GH_REPO"') != 2:
    reject("Release package workflow publication contract changed.")
promotion_guard = '[[ "$EVENT_NAME" = "release" && "$PRERELEASE" = "true" ]]'
if promotion_guard not in publish:
    reject("Release package workflow publication contract changed.")
if publish.index('gh release upload "$RELEASE_TAG"') > publish.index('gh release edit "$RELEASE_TAG"'):
    reject("Release package workflow publication contract changed.")
if not publish.rstrip().endswith('fi'):
    reject("Release package workflow publication contract changed.")

download_step = publish_step_blocks["Download sealed release payload"]
verify_step = publish_step_blocks["Verify sealed release payload"]
if "run:" in download_step or "        id:" in download_step:
    reject("Release package workflow transport contract changed.")
if verify_step.count("        run: |\n") != 1 or verify_step.count("python - ") != 1:
    reject("Release package workflow transport contract changed.")
if publish_assets_step.count("        run: |\n") != 1:
    reject("Release package workflow transport contract changed.")
if len(re.findall(r"(?m)^        run:", publish)) != 2:
    reject("Release package workflow transport contract changed.")
if len(re.findall(r"(?m)^        uses:", publish)) != 1:
    reject("Release package workflow transport contract changed.")
for forbidden_command in (
    "unzip ",
    "tar -",
    "python -m zipfile",
    "chmod ",
    "source ",
    "eval ",
    "exec ",
):
    if forbidden_command in publish:
        reject("Release package workflow transport contract changed.")
if re.search(
    r"(?m)^\s*(?:bash|sh|zsh|pwsh|powershell|node|ruby|perl)\s+"
    r"[\"']?\$TRANSFER_ROOT",
    publish,
):
    reject("Release package workflow transport contract changed.")
publish_lines = publish.splitlines()
for index, line in enumerate(publish_lines):
    if not re.match(
        r"^\s*[\"']?\$(?:\{TRANSFER_ROOT\}|TRANSFER_ROOT)/",
        line,
    ):
        continue
    if index == 0 or not publish_lines[index - 1].rstrip().endswith("\\"):
        reject("Release package workflow transport contract changed.")

ordered_fragments = [
    action_revisions["checkout"],
    action_revisions["setup-python"],
    action_revisions["setup-node"],
    "python -m pip install",
    "npm ci --ignore-scripts --prefix tools/quality",
    "        id: refs",
    "        id: package",
    "Validate composed package",
    "        id: toolkit",
    "        id: seal",
    action_revisions["upload-artifact"],
]
positions = [build.find(fragment) for fragment in ordered_fragments]
if any(position < 0 for position in positions) or positions != sorted(positions):
    reject("Release package workflow job graph changed.")
PY
  then

    return 1
  fi
}

check_agent_rules_update_workflow_contract() {
  local workflow_path="${1:-.github/workflows/agent-rules-update.yml}"

  if [ ! -f "$workflow_path" ]; then
    printf 'Agent rules workflow is missing: %s\n' "$workflow_path" >&2
    return 1
  fi

  awk '
    function fail(message) {
      print message > "/dev/stderr"
      failed = 1
    }

    function has(text, fragment) {
      return index(text, fragment) > 0
    }

    {
      line = $0
      sub(/\r$/, "", line)
      workflow = workflow line "\n"

      if (line == "jobs:") {
        in_jobs = 1
      } else if ( \
        in_jobs && \
        line ~ /^  [[:alnum:]_-]+:$/ \
      ) {
        job_count++
        job = line
        sub(/^  /, "", job)
        sub(/:$/, "", job)
      }

      if (job == "prepare") {
        prepare = prepare line "\n"
      } else if (job == "publish") {
        publish = publish line "\n"
      }

      if (line ~ /^[[:space:]]+contents: read[[:space:]]*$/) {
        contents_read++
      }
      if (line ~ /^[[:space:]]+contents: write[[:space:]]*$/) {
        contents_write++
      }
      if (line == "          fetch-depth: 0") {
        fetch_depth++
      }
      if (line == "          persist-credentials: false") {
        credentials_disabled++
      }
      if (line ~ /^[[:space:]]+token:[[:space:]]*/) {
        checkout_token++
      }
      if (line == "          python-version: \"3.11\"") {
        python_version++
      }

      if (has(line, "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5")) {
        checkout_count++
        checkout_line[checkout_count] = NR
      }
      if (has(line, "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97")) {
        setup_python++
      }
      if (has(line, "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a")) {
        upload_count++
        upload_line = NR
      }
      if (has(line, "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c")) {
        download_count++
        download_line = NR
      }
      if (has(line, "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1")) {
        app_token_count++
        token_line = NR
      }

      if (has(line, "agent-rules-transfer.sh prepare-publish")) {
        prepare_publish_line = NR
      } else if (has(line, "agent-rules-transfer.sh publish")) {
        publish_line = NR
      } else if (has(line, "agent-rules-transfer.sh resolve")) {
        resolve_line = NR
      } else if (has(line, "agent-rules-transfer.sh seal")) {
        seal_line = NR
      }
      if (!external_line && has(line, "agent-rules-sync.py")) {
        external_line = NR
      }

      if (line ~ /^      - name:/) {
        external_step = has(line, "external synchronization")
      } else if ( \
        external_step && \
        line ~ /(GH_TOKEN|GITHUB_TOKEN|GITHUB_OUTPUT|GITHUB_ENV|GITHUB_PATH|GITHUB_STATE)/ \
      ) {
        external_forbidden = 1
      }

      if (upload_paths) {
        if (line ~ /^            /) {
          upload_entries++
          if ( \
            line == "            ${{ runner.temp }}/agent-rules-transfer/agent-rules.patch" || \
            line == "            ${{ runner.temp }}/agent-rules-transfer/agent-rules-plan.json" || \
            line == "            ${{ runner.temp }}/agent-rules-transfer/source.json" || \
            line == "            ${{ runner.temp }}/agent-rules-transfer/SHA256SUMS" \
          ) {
            allowed_upload_entries++
          }
        } else {
          upload_paths = 0
        }
      }
      if (job == "prepare" && line == "          path: |") {
        upload_paths = 1
      }

      if (has(line, "GH_TOKEN: ${{ github.token }}")) {
        readonly_token++
      }
      if (has(line, "private-key: ${{ secrets.AGENT_RULES_APP_PRIVATE_KEY }}")) {
        private_key++
      }
      if (has(line, "GH_TOKEN: ${{ steps.target-token.outputs.token }}")) {
        app_step_token++
      }

      if (line == "  group: agent-rules-update") {
        concurrency_group++
      }
      if (line == "  cancel-in-progress: false") {
        concurrency_cancel++
      }

      if (has(line, "${{ runner.temp }}/agent-rules-transfer/agent-rules.patch")) {
        artifact_patch++
      }
      if (has(line, "${{ runner.temp }}/agent-rules-transfer/agent-rules-plan.json")) {
        artifact_plan++
      }
      if (has(line, "${{ runner.temp }}/agent-rules-transfer/source.json")) {
        artifact_source++
      }
      if (has(line, "${{ runner.temp }}/agent-rules-transfer/SHA256SUMS")) {
        artifact_sums++
      }
    }

    END {
      sq = sprintf("%c", 39)
      guard =         "    if: >-\n"         "      (\n"         "        github.event_name == " sq "release" sq " ||\n"         "        vars.AGENT_RULES_SYNC_ENABLED != " sq "false" sq "\n"         "      ) && (\n"         "        github.event_name != " sq "workflow_dispatch" sq " ||\n"         "        github.ref_name == github.event.repository.default_branch\n"         "      )\n"
      outputs =         "      changed: ${{ steps.seal.outputs.changed }}\n"         "      target_repository: ${{ steps.resolve.outputs.target_repository }}\n"         "      target_default_branch: ${{ steps.resolve.outputs.target_default_branch }}\n"         "      target_base_commit: ${{ steps.resolve.outputs.target_base_commit }}\n"         "      source_ref: ${{ steps.resolve.outputs.source_ref }}\n"         "      source_tag_oid: ${{ steps.resolve.outputs.source_tag_oid }}\n"         "      source_commit: ${{ steps.resolve.outputs.source_commit }}\n"

      if ( \
        !has(workflow, "  release:\n") || \
        !has(workflow, "    types: [published]\n") || \
        !has(workflow, "  schedule:\n") || \
        !has(workflow, "  workflow_dispatch:\n") || \
        !has(prepare, guard) \
      ) {
        fail("Agent rules workflow event guards are incomplete.")
      }
      if ( \
        job_count != 2 || \
        !has(workflow, "  prepare:\n") || \
        !has(workflow, "  publish:\n") || \
        !has(publish, "    needs: prepare\n") || \
        !has( \
          publish, \
          "    if: needs.prepare.outputs.changed == " sq "true" sq "\n" \
        ) \
      ) {
        fail("Agent rules workflow must contain ordered prepare and publish jobs.")
      }
      if ( \
        !has(prepare, "    timeout-minutes: 15\n") || \
        !has(publish, "    timeout-minutes: 10\n") || \
        contents_read != 3 || \
        contents_write != 0 \
      ) {
        fail("Agent rules workflow timeouts or permissions are not minimal.")
      }
      if ( \
        checkout_count != 2 || \
        fetch_depth != 2 || \
        credentials_disabled != 2 || \
        checkout_token != 0 || \
        !has( \
          prepare, \
          "          ref: ${{ github.event.repository.default_branch }}\n" \
        ) || \
        !has( \
          publish, \
          "          ref: ${{ needs.prepare.outputs.target_base_commit }}\n" \
        ) \
      ) {
        fail("Agent rules workflow checkouts are not sealed and credential-free.")
      }
      if (!has(prepare, outputs)) {
        fail("Agent rules workflow outputs are missing or miswired.")
      }
      if ( \
        setup_python != 2 || \
        python_version != 2 || \
        upload_count != 1 || \
        download_count != 1 || \
        app_token_count != 1 \
      ) {
        fail("Agent rules workflow action pins are incomplete.")
      }
      if ( \
        !checkout_line[1] || \
        !resolve_line || \
        !external_line || \
        !seal_line || \
        !upload_line || \
        !checkout_line[2] || \
        !download_line || \
        !prepare_publish_line || \
        !token_line || \
        !publish_line || \
        checkout_line[1] >= resolve_line || \
        resolve_line >= external_line || \
        external_line >= seal_line || \
        seal_line >= upload_line || \
        checkout_line[2] >= download_line || \
        download_line >= prepare_publish_line || \
        prepare_publish_line >= token_line || \
        token_line >= publish_line \
      ) {
        fail("Agent rules workflow step order is unsafe.")
      }
      if ( \
        readonly_token != 2 || \
        private_key != 1 || \
        app_step_token != 1 || \
        external_forbidden \
      ) {
        fail("Agent rules workflow exposes a token to an unsafe step.")
      }
      if ( \
        upload_entries != 4 || \
        allowed_upload_entries != 4 || \
        artifact_patch != 1 || \
        artifact_plan != 1 || \
        artifact_source != 1 || \
        artifact_sums != 1 \
      ) {
        fail("Agent rules workflow artifact allowlist is incomplete.")
      }
      if (concurrency_group != 1 || concurrency_cancel != 1) {
        fail("Agent rules workflow concurrency contract changed.")
      }
      if ( \
        !has(prepare, "          TARGET_REPOSITORY: ${{ github.repository }}\n") || \
        !has( \
          prepare, \
          "          TARGET_DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}\n" \
        ) || \
        !has( \
          prepare, \
          "          TARGET_BASE_COMMIT: ${{ steps.resolve.outputs.target_base_commit }}\n" \
        ) || \
        !has( \
          prepare, \
          "          SOURCE_TAG_OID: ${{ steps.resolve.outputs.source_tag_oid }}\n" \
        ) || \
        !has( \
          publish, \
          "          TARGET_BASE_COMMIT: ${{ needs.prepare.outputs.target_base_commit }}\n" \
        ) || \
        !has( \
          publish, \
          "          SOURCE_TAG_OID: ${{ needs.prepare.outputs.source_tag_oid }}\n" \
        ) || \
        !has( \
          publish, \
          "          TARGET_COMMIT: ${{ steps.prepare-publish.outputs.target_commit }}\n" \
        ) || \
        !has( \
          publish, \
          "          SOURCE_REF: ${{ needs.prepare.outputs.source_ref }}\n" \
        ) || \
        !has( \
          publish, \
          "            ${{ steps.prepare-publish.outputs.expected_remote_oid }}\n" \
        ) || \
        !has( \
          publish, \
          "          PUSH_REQUIRED: ${{ steps.prepare-publish.outputs.push_required }}\n" \
        ) \
      ) {
        fail("Agent rules workflow identity wiring is incomplete.")
      }

      exit (failed ? 1 : 0)
    }
  ' "$workflow_path"
}
check_repository_audit_workflow_contract() {
  local python_cmd
  local versions_path="${2:-tools/quality/versions.json}"
  local workflow_path="${1:-.github/workflows/repository-audit.yml}"

  if [ ! -f "$workflow_path" ]; then
    printf 'Repository audit workflow is missing: %s\n' "$workflow_path" >&2
    return 1
  fi
  if [ ! -f "$versions_path" ]; then
    printf 'Quality version registry is missing: %s\n' "$versions_path" >&2
    return 1
  fi

  python_cmd="$(resolve_command python python3 python.exe)"
  if ! "$python_cmd" - "$workflow_path" "$versions_path" <<'PY'
import json
import re
import sys
from pathlib import Path

workflow_path = Path(sys.argv[1])
versions_path = Path(sys.argv[2])
text = workflow_path.read_text(encoding="utf-8").replace("\r\n", "\n")
lines = text.splitlines(keepends=True)


def reject(message: str) -> None:
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    raise SystemExit(1)


try:
    jobs_index = lines.index("jobs:\n")
except ValueError:
    reject("Repository audit workflow job graph changed.")

top_level = "".join(lines[:jobs_index])
job_headers = [
    (index, match.group(1))
    for index, line in enumerate(lines[jobs_index + 1 :], jobs_index + 1)
    if (match := re.fullmatch(r"  ([A-Za-z0-9_-]+):\n", line))
]
job_names = [name for _, name in job_headers]

try:
    on_start = top_level.index('"on":\n')
    env_start = top_level.index("env:\n")
except ValueError:
    reject("Repository audit workflow trigger contract changed.")
permissions_match = re.search(r"(?m)^permissions(?::[^\n]*)?\n", top_level)
if permissions_match is None:
    reject("Repository audit workflow privilege boundary changed.")
permissions_start = permissions_match.start()
if not on_start < permissions_start < env_start:
    reject("Repository audit workflow trigger contract changed.")

on_block = top_level[on_start:permissions_start]
expected_on_block = (
    '"on":\n'
    "  release:\n"
    "    types: [published]\n"
    "  push:\n"
    "    branches: [master]\n"
    '    tags: ["v*"]\n'
    "  pull_request:\n"
    "    branches: [master]\n"
    "  workflow_dispatch:\n"
    "\n"
)
if on_block != expected_on_block:
    reject("Repository audit workflow trigger contract changed.")

permissions_block = top_level[permissions_start:env_start].strip()
if permissions_block != "permissions:\n  contents: read":
    reject("Repository audit workflow privilege boundary changed.")
privileged_fragments = (
    "contents: write",
    "id-token:",
    "pull-requests: write",
    "GITHUB_TOKEN:",
    "GH_TOKEN:",
)
github_auth_context = re.compile(
    r"\bgithub\s*(?:\.\s*token|\[\s*['\"]token['\"]\s*\])"
)
github_context_object = re.compile(
    r"\btojson\s*\(\s*github\s*\)", re.IGNORECASE
)
sensitive_context = re.compile(r"\bsecrets\b")
jobs_text = "".join(lines[jobs_index + 1 :])
if (
    any(fragment in text for fragment in privileged_fragments)
    or github_auth_context.search(text)
    or github_context_object.search(text)
    or sensitive_context.search(text)
    or re.search(r"(?m)^    permissions(?::[^\n]*)?", jobs_text)
    or re.search(r"(?m)^    continue-on-error:", jobs_text)
):
    reject("Repository audit workflow privilege boundary changed.")

if job_names != ["quality-linux", "compatibility-windows", "repository-audit"]:
    reject("Repository audit workflow job graph changed.")
if re.search(r"(?m)^\s+(?:strategy|matrix):", text):
    reject("Repository audit workflow job graph changed.")

job_blocks: dict[str, str] = {}
for position, (start, name) in enumerate(job_headers):
    end = job_headers[position + 1][0] if position + 1 < len(job_headers) else len(lines)
    job_blocks[name] = "".join(lines[start:end])

quality_linux = job_blocks["quality-linux"]
compatibility_windows = job_blocks["compatibility-windows"]
aggregate = job_blocks["repository-audit"]

runner_contract = (
    (
        quality_linux,
        "    name: Quality - Ubuntu 24.04 / Python 3.11\n",
        "    runs-on: ubuntu-24.04\n",
        "    timeout-minutes: 25\n",
    ),
    (
        compatibility_windows,
        "    name: Compatibility - Windows 2025 / Python 3.14\n",
        "    runs-on: windows-2025\n",
        "    timeout-minutes: 25\n",
    ),
    (
        aggregate,
        "      'Repository audit (manual)' || 'Repository audit' }}\n",
        "    runs-on: ubuntu-24.04\n",
        "    timeout-minutes: 5\n",
    ),
)
for job, expected_name, runner, timeout in runner_contract:
    if expected_name not in job or job.count(runner) != 1 or job.count(timeout) != 1:
        reject("Repository audit workflow runner or timeout contract changed.")
if text.count("    timeout-minutes:") != 3:
    reject("Repository audit workflow runner or timeout contract changed.")

expected_actions = [
    "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
    "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
]
used_actions = re.findall(r"(?m)^\s+uses: ([^\n]+)$", text)
if used_actions != expected_actions:
    reject("Repository audit workflow action revision contract changed.")
expected_action_comments = [
    "actions/checkout@v7.0.0",
    "actions/setup-python@v7.0.0",
    "actions/setup-node@v7.0.0",
    "actions/checkout@v7.0.0",
    "actions/setup-python@v7.0.0",
    "actions/setup-node@v7.0.0",
]
action_comments = re.findall(r"(?m)^\s+# (actions/[^\n]+)$", text)
action_pairs = re.findall(
    r"(?m)^        # (actions/[^\n]+)\n        uses: ([^\n]+)$", text
)
if (
    action_comments != expected_action_comments
    or action_pairs != list(zip(expected_action_comments, expected_actions))
):
    reject("Repository audit workflow action revision contract changed.")


def parse_steps(job: str) -> list[tuple[str, str]]:
    job_lines = job.splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(job_lines)
        if re.match(r"^      - ", line)
    ]
    steps = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(job_lines)
        block = "".join(job_lines[start:end])
        name_match = re.match(r"^      - name: ([^\n]+)\n", block)
        steps.append((name_match.group(1) if name_match else "", block))
    return steps


linux_steps = parse_steps(quality_linux)
windows_steps = parse_steps(compatibility_windows)
aggregate_steps = parse_steps(aggregate)
all_steps = linux_steps + windows_steps + aggregate_steps

checkout_revision = expected_actions[0]
checkout_steps = [block for _, block in all_steps if checkout_revision in block]
if len(checkout_steps) != 2:
    reject("Repository audit workflow checkout boundary changed.")
for checkout in checkout_steps:
    if checkout.count("          fetch-depth: 0\n") != 1:
        reject("Repository audit workflow checkout boundary changed.")
    if checkout.count("          persist-credentials: false\n") != 1:
        reject("Repository audit workflow checkout boundary changed.")
    if re.search(r"(?m)^\s+ref:", checkout):
        reject("Repository audit workflow checkout boundary changed.")
if "persist-credentials: true" in text:
    reject("Repository audit workflow checkout boundary changed.")

try:
    registry = json.loads(versions_path.read_text(encoding="utf-8"))
    node_version = registry["policy"]["nodeCiVersion"]
except (KeyError, TypeError, json.JSONDecodeError, UnicodeError):
    reject("Repository audit workflow runtime setup changed.")
if not isinstance(node_version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", node_version):
    reject("Repository audit workflow runtime setup changed.")
expected_env = f'env:\n  NODE_VERSION: "{node_version}"'
if top_level[env_start:].strip() != expected_env:
    reject("Repository audit workflow runtime setup changed.")
if text.count(node_version) != 1 or text.count("NODE_VERSION") != 3:
    reject("Repository audit workflow runtime setup changed.")

linux_step_blocks = dict(linux_steps)
windows_step_blocks = dict(windows_steps)
try:
    linux_python = linux_step_blocks["Set up Python"]
    windows_python = windows_step_blocks["Set up Python"]
    linux_node = linux_step_blocks["Set up Node"]
    windows_node = windows_step_blocks["Set up Node"]
except KeyError:
    reject("Repository audit workflow runtime setup changed.")
if "          python-version: \"3.11\"\n" not in linux_python:
    reject("Repository audit workflow runtime setup changed.")
if "          python-version: \"3.14\"\n" not in windows_python:
    reject("Repository audit workflow runtime setup changed.")
for node_step in (linux_node, windows_node):
    if "          node-version: ${{ env.NODE_VERSION }}\n" not in node_step:
        reject("Repository audit workflow runtime setup changed.")
if re.search(r"(?m)^\s+cache:", text):
    reject("Repository audit workflow runtime setup changed.")

try:
    linux_install = linux_step_blocks["Install locked language toolchains"]
    windows_install = windows_step_blocks["Install locked language toolchains"]
except KeyError:
    reject("Repository audit workflow dependency installation changed.")
for install in (linux_install, windows_install):
    required_fragments = (
        "python -m pip install --disable-pip-version-check",
        "--require-hashes",
        "--requirement tools/quality/requirements.lock",
        "npm ci --ignore-scripts --prefix tools/quality",
    )
    if any(install.count(fragment) != 1 for fragment in required_fragments):
        reject("Repository audit workflow dependency installation changed.")
    if install.count("python -m pip install") != 1 or install.count("npm ci") != 1:
        reject("Repository audit workflow dependency installation changed.")
if text.count("tools/quality/requirements.lock") != 2:
    reject("Repository audit workflow dependency installation changed.")
expected_linux_install = (
    "      - name: Install locked language toolchains\n"
    "        shell: bash\n"
    "        run: |\n"
    "          python -m pip install --disable-pip-version-check \\\n"
    "            --require-hashes \\\n"
    "            --requirement tools/quality/requirements.lock\n"
    "          npm ci --ignore-scripts --prefix tools/quality\n"
)
expected_windows_install = (
    "      - name: Install locked language toolchains\n"
    "        shell: pwsh\n"
    "        run: |\n"
    "          python -m pip install --disable-pip-version-check `\n"
    "            --require-hashes `\n"
    "            --requirement tools/quality/requirements.lock\n"
    "          npm ci --ignore-scripts --prefix tools/quality\n"
)
if (
    linux_install.rstrip() != expected_linux_install.rstrip()
    or windows_install.rstrip() != expected_windows_install.rstrip()
):
    reject("Repository audit workflow dependency installation changed.")

try:
    linux_external = linux_step_blocks["Install verified external tools"]
    windows_external = windows_step_blocks["Install verified PowerShell analyzer"]
except KeyError:
    reject("Repository audit workflow external tool setup changed.")
linux_external_fragments = (
    "python tools/quality/install-external-tools.py",
    "--platform linux-x64",
    '--install-root "$RUNNER_TEMP/quality-tools"',
    'echo "$RUNNER_TEMP/quality-tools/bin" >> "$GITHUB_PATH"',
    "PSModulePath=$RUNNER_TEMP/quality-tools/Modules:${PSModulePath:-}",
    '>> "$GITHUB_ENV"',
)
if any(fragment not in linux_external for fragment in linux_external_fragments):
    reject("Repository audit workflow external tool setup changed.")
if "--tool " in linux_external:
    reject("Repository audit workflow external tool setup changed.")
windows_external_fragments = (
    "python tools/quality/install-external-tools.py",
    "--platform windows-x64",
    "--tool PSScriptAnalyzer",
    '--install-root "$env:RUNNER_TEMP/quality-tools"',
    "Add-Content $env:GITHUB_ENV",
    "PSModulePath=$env:RUNNER_TEMP/quality-tools/Modules"
    "$([IO.Path]::PathSeparator)$env:PSModulePath",
)
if any(fragment not in windows_external for fragment in windows_external_fragments):
    reject("Repository audit workflow external tool setup changed.")
if windows_external.count("--tool ") != 1 or windows_external.count(
    "--tool PSScriptAnalyzer"
) != 1:
    reject("Repository audit workflow external tool setup changed.")
if "GITHUB_PATH" in windows_external or "go install" in text or "setup-go" in text:
    reject("Repository audit workflow external tool setup changed.")
expected_linux_external = (
    "      - name: Install verified external tools\n"
    "        shell: bash\n"
    "        run: |\n"
    "          python tools/quality/install-external-tools.py \\\n"
    "            --platform linux-x64 \\\n"
    '            --install-root "$RUNNER_TEMP/quality-tools"\n'
    '          echo "$RUNNER_TEMP/quality-tools/bin" >> "$GITHUB_PATH"\n'
    '          echo "PSModulePath=$RUNNER_TEMP/quality-tools/Modules:'
    '${PSModulePath:-}" \\\n'
    '            >> "$GITHUB_ENV"\n'
)
expected_windows_external = (
    "      - name: Install verified PowerShell analyzer\n"
    "        shell: pwsh\n"
    "        run: |\n"
    "          python tools/quality/install-external-tools.py `\n"
    "            --platform windows-x64 `\n"
    "            --tool PSScriptAnalyzer `\n"
    '            --install-root "$env:RUNNER_TEMP/quality-tools"\n'
    "          Add-Content $env:GITHUB_ENV `\n"
    '            "PSModulePath=$env:RUNNER_TEMP/quality-tools/Modules'
    '$([IO.Path]::PathSeparator)$env:PSModulePath"\n'
)
if (
    linux_external.rstrip() != expected_linux_external.rstrip()
    or windows_external.rstrip() != expected_windows_external.rstrip()
):
    reject("Repository audit workflow external tool setup changed.")

try:
    linux_gate = linux_step_blocks["Run the complete quality gate"]
    windows_fast = windows_step_blocks["Run cross-platform compatibility checks"]
    windows_unittest = windows_step_blocks["Run the complete Python suite on 3.14"]
    windows_powershell = windows_step_blocks["Analyze PowerShell on Windows"]
    aggregate_gate = dict(aggregate_steps)["Require both supported environments"]
except KeyError:
    reject("Repository audit workflow audit routing changed.")

def step_fields(step: str) -> list[str]:
    return re.findall(r"(?m)^        ([A-Za-z0-9_-]+):", step)


if step_fields(linux_gate) != ["shell", "env", "run"] or re.findall(
    r"(?m)^        run:.*\n", linux_gate
) != ["        run: bash tools/repository-audit.sh full\n"]:
    reject("Repository audit workflow audit routing changed.")
expected_windows_sensitive_steps = (
    (
        windows_fast,
        "      - name: Run cross-platform compatibility checks\n"
        "        shell: bash\n"
        "        run: bash tools/repository-audit.sh fast\n",
    ),
    (
        windows_unittest,
        "      - name: Run the complete Python suite on 3.14\n"
        "        shell: pwsh\n"
        "        run: python -m unittest discover -s tests -p 'test_*.py'\n",
    ),
    (
        windows_powershell,
        "      - name: Analyze PowerShell on Windows\n"
        "        shell: bash\n"
        "        run: bash tools/repository-audit.sh powershell-static\n",
    ),
)
if any(
    step.rstrip() != expected.rstrip()
    for step, expected in expected_windows_sensitive_steps
):
    reject("Repository audit workflow audit routing changed.")
if text.count("bash tools/repository-audit.sh ") != 3:
    reject("Repository audit workflow audit routing changed.")

expected_linux_gate = (
    "      - name: Run the complete quality gate\n"
    "        shell: bash\n"
    "        env:\n"
    "          AUDIT_COMMIT_SHA: >-\n"
    "            ${{ github.event.pull_request.head.sha || github.sha }}\n"
    "          BEFORE_SHA: >-\n"
    "            ${{ github.event_name == 'release' &&\n"
    "            '0000000000000000000000000000000000000000' ||\n"
    "            github.event.before }}\n"
    "          GIT_AUTHOR_NAME: Codex\n"
    "          GIT_AUTHOR_EMAIL: codex@example.com\n"
    "          GIT_COMMITTER_NAME: Codex\n"
    "          GIT_COMMITTER_EMAIL: codex@example.com\n"
    "        run: bash tools/repository-audit.sh full\n"
)
if linux_gate.rstrip() != expected_linux_gate.rstrip():
    reject("Repository audit workflow commit range changed.")
if "AUDIT_SHA:" in text or text.count("0000000000000000000000000000000000000000") != 1:
    reject("Repository audit workflow commit range changed.")
if "AUDIT_COMMIT_SHA:" in compatibility_windows:
    reject("Repository audit workflow commit range changed.")

if aggregate.count("    needs: [quality-linux, compatibility-windows]\n") != 1:
    reject("Repository audit workflow aggregate contract changed.")
if re.findall(r"(?m)^    if: .*\n", aggregate) != [
    "    if: ${{ always() }}\n"
]:
    reject("Repository audit workflow aggregate contract changed.")
expected_aggregate_gate = (
    "      - name: Require both supported environments\n"
    "        env:\n"
    "          LINUX_RESULT: ${{ needs.quality-linux.result }}\n"
    "          WINDOWS_RESULT: ${{ needs.compatibility-windows.result }}\n"
    "        run: |\n"
    '          test "$LINUX_RESULT" = success && '
    'test "$WINDOWS_RESULT" = success\n'
)
if step_fields(aggregate_gate) != ["env", "run"]:
    reject("Repository audit workflow aggregate contract changed.")
if aggregate_gate.rstrip() != expected_aggregate_gate.rstrip():
    reject("Repository audit workflow aggregate contract changed.")

if [name for name, _ in linux_steps] != [
    "Checkout repository",
    "Set up Python",
    "Set up Node",
    "Install locked language toolchains",
    "Install verified external tools",
    "Run the complete quality gate",
]:
    reject("Repository audit workflow job graph changed.")
if [name for name, _ in windows_steps] != [
    "Checkout repository",
    "Set up Python",
    "Set up Node",
    "Install locked language toolchains",
    "Install verified PowerShell analyzer",
    "Run cross-platform compatibility checks",
    "Run the complete Python suite on 3.14",
    "Analyze PowerShell on Windows",
]:
    reject("Repository audit workflow job graph changed.")
if [name for name, _ in aggregate_steps] != ["Require both supported environments"]:
    reject("Repository audit workflow job graph changed.")
PY
  then
    return 1
  fi
}

check_release_artifact_contract() {
  local main_reference_path=".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt"
  local python_cmd
  local release_reference_path=".agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt"
  local required_path
  local workflow_path="${1:-.github/workflows/release-artifacts.yml}"

  for required_path in \
    .githooks/pre-push \
    .github/workflows/release-artifacts.yml \
    templates/release/manifest.template.json \
    templates/release/manifest.schema.json \
    tests/test_release_artifacts.py \
    tools/release-artifacts-requirements.txt \
    tools/release-artifacts.py \
    tools/repository-audit/hooks.sh; do
    if [ ! -f "$required_path" ]; then
      printf 'Release artifact component is missing: %s\n' "$required_path" >&2
      exit 1
    fi
  done

  if git ls-files --error-unmatch .githooks/pre-push >/dev/null 2>&1 &&
    [ "$(git ls-files --stage .githooks/pre-push | cut -d ' ' -f 1)" != \
      "100755" ]; then
    printf '%s\n' 'The tracked pre-push hook must use Git mode 100755.' >&2
    exit 1
  fi

  if ! grep -F 'name: Release artifacts' "$workflow_path" >/dev/null ||
    ! grep -F '      - "v*"' "$workflow_path" >/dev/null; then
    printf '%s\n' \
      'Release artifacts workflow does not validate every SemVer tag.' >&2
    exit 1
  fi

  if [ "$(grep -Fc 'tools/release-artifacts-requirements.txt' \
    "$workflow_path")" -ne 1 ] ||
    ! grep -F -- '--require-hashes' "$workflow_path" >/dev/null; then
    printf '%s\n' \
      'Release artifacts workflow dependency contract changed.' >&2
    exit 1
  fi

  if [ "$(grep -Fc 'tools/release-artifacts.py check' \
    "$workflow_path")" -ne 1 ]; then
    printf '%s\n' \
      'Release artifacts workflow validation contract changed.' >&2
    exit 1
  fi

  if ! grep -E '^        uses: actions/setup-python@' \
    "$workflow_path" >/dev/null; then
    printf '%s\n' \
      'Release artifacts workflow does not configure setup-python.' >&2
    exit 1
  fi

  if ! grep -Fx \
    '        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97' \
    "$workflow_path" >/dev/null; then
    printf '%s\n' \
      'Release artifacts workflow uses an unexpected setup-python revision.' \
      >&2
    exit 1
  fi

  if ! grep -Fx '          python-version: "3.11"' \
    "$workflow_path" >/dev/null; then
    printf '%s\n' \
      'Release artifacts workflow does not use Python 3.11.' >&2
    exit 1
  fi

  if ! grep -Fx -- '          --no-input' "$workflow_path" >/dev/null; then
    printf '%s\n' \
      'Release artifacts workflow pip install is missing --no-input.' >&2
    exit 1
  fi

  if ! grep -Fx '          python -m pip install' \
    "$workflow_path" >/dev/null ||
    ! grep -Fx -- '          --disable-pip-version-check' \
      "$workflow_path" >/dev/null; then
    printf '%s\n' \
      'Release artifacts workflow dependency installation command changed.' \
      >&2
    exit 1
  fi

  python_cmd="$(resolve_command python python3 python.exe)"
  if ! "$python_cmd" - "$workflow_path" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8").replace("\r\n", "\n")
lines = text.splitlines(keepends=True)


def reject(message: str) -> None:
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    raise SystemExit(1)


try:
    jobs_index = lines.index("jobs:\n")
except ValueError:
    reject("Release artifacts workflow job graph changed.")

top_level = "".join(lines[:jobs_index])
expected_trigger = (
    '"on":\n'
    "  push:\n"
    "    tags:\n"
    '      - "v*"\n'
)
if expected_trigger not in top_level:
    reject("Release artifacts workflow trigger boundary changed.")
for forbidden_trigger in ("  release:", "  workflow_dispatch:", "  schedule:"):
    if forbidden_trigger in top_level:
        reject("Release artifacts workflow trigger boundary changed.")
if "concurrency:" in top_level:
    reject("Release artifacts workflow isolation contract changed.")

if not re.search(r"(?m)^permissions:\n  contents: read\n(?:\n|$)", top_level):
    reject("Release artifacts workflow privilege boundary changed.")
if "contents: write" in text or "GH_TOKEN:" in text or "GITHUB_TOKEN:" in text:
    reject("Release artifacts workflow privilege boundary changed.")

job_headers = [
    match.group(1)
    for line in lines[jobs_index + 1 :]
    if (match := re.fullmatch(r"  ([A-Za-z0-9_-]+):\n", line))
]
if job_headers != ["release-artifacts"]:
    reject("Release artifacts workflow job graph changed.")
job_text = "".join(lines[jobs_index + 1 :])
if "    runs-on: ubuntu-24.04\n" not in job_text or "    timeout-minutes: 10\n" not in job_text:
    reject("Release artifacts workflow job graph changed.")
if "environment:" in text:
    reject("Release artifacts workflow isolation contract changed.")
step_names = re.findall(r"(?m)^      - name: ([^\n]+)$", job_text)
if step_names != [
    "Checkout tagged release",
    "Set up Python",
    "Install manifest validator",
    "Validate release identification",
]:
    reject("Release artifacts workflow job graph changed.")
if len(re.findall(r"(?m)^      - ", job_text)) != 4:
    reject("Release artifacts workflow job graph changed.")

checkout_revision = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
if text.count(checkout_revision) != 1:
    reject("Release artifacts workflow checkout contract changed.")
if "          fetch-depth: 0\n" not in text or "          persist-credentials: false\n" not in text:
    reject("Release artifacts workflow checkout contract changed.")
if re.search(r"(?m)^\s+ref:", text):
    reject("Release artifacts workflow checkout contract changed.")

if re.search(r"(?m)^\s+cache:", text):
    reject("Release artifacts workflow runtime contract changed.")
for forbidden_runtime in (
    "actions/setup-node@",
    "npm ci",
    "actions/upload-artifact@",
    "actions/download-artifact@",
):
    if forbidden_runtime in text:
        reject("Release artifacts workflow runtime contract changed.")
if text.count("python -m pip install") != 1:
    reject("Release artifacts workflow runtime contract changed.")
if text.count("tools/release-artifacts.py check") != 1:
    reject("Release artifacts workflow runtime contract changed.")
for dependency_fragment in (
    "--disable-pip-version-check",
    "--no-input",
    "--require-hashes",
    "--requirement tools/release-artifacts-requirements.txt",
):
    if text.count(dependency_fragment) != 1:
        reject("Release artifacts workflow dependency contract changed.")

for fragment in (
    "          RELEASE_REF: ${{ github.ref_name }}\n",
    "          RELEASE_TREEISH: ${{ github.sha }}\n",
    '--expected-ref "${RELEASE_REF}"',
    '--treeish "${RELEASE_TREEISH}"',
    "--repository-root .",
):
    if fragment not in text:
        reject("Release artifacts workflow validation contract changed.")
PY
  then

    return 1
  fi

  if ! grep -F \
    'VERSION, SHA256SUMS, and manifest.json must be staged together.' \
    tools/repository-audit/hooks.sh >/dev/null ||
    ! grep -F 'tools/release-artifacts.py' \
      tools/repository-audit/hooks.sh >/dev/null ||
    ! grep -F -- '--expected-ref' \
      tools/repository-audit/hooks.sh >/dev/null; then
    printf '%s\n' 'Release artifact hooks are incomplete.' >&2
    exit 1
  fi

  if ! grep -F "PRÉPARATION DES ARTEFACTS D'IDENTIFICATION DE RELEASE" \
    "$main_reference_path" >/dev/null ||
    ! grep -F 'RELEASE_ARTIFACTS_STATUS=complete' \
      "$main_reference_path" >/dev/null ||
    ! grep -F 'git -c core.hooksPath=.githooks push --atomic' \
      "$main_reference_path" >/dev/null; then
    printf '%s\n' 'Release guard omits release artifact preparation.' >&2
    exit 1
  fi

  if [ -f "$release_reference_path" ] &&
    ! grep -F "inventorieront le \`starter-kit-manifest.json\` final" \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' \
      'Starter release guard omits the final starter manifest.' >&2
    exit 1
  fi
}

check_release_skill_contract() {
  local skill_path=".agents/skills/git-commit-push-tag/SKILL.md"
  local metadata_path=".agents/skills/git-commit-push-tag/agents/openai.yaml"
  local reference_path=".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt"
  local expected_steps
  local metadata_resolution_line
  local metadata_validation_line
  local phase_two_line
  local preconditions_line
  local release_metadata_line
  local steps

  for required_path in "$skill_path" "$metadata_path" "$reference_path"; do
    if [ ! -f "$required_path" ] ||
      ! git ls-files --error-unmatch "$required_path" >/dev/null 2>&1; then
      printf 'Release skill component is missing or untracked: %s\n' \
        "$required_path" >&2
      exit 1
    fi
  done

  # shellcheck disable=SC2016
  if ! grep -F \
    '[`references/git-commit-push-tag.txt`](references/git-commit-push-tag.txt)' \
    "$skill_path" >/dev/null ||
    ! grep -F 'Treat it as the sole behavioral' "$skill_path" >/dev/null ||
    ! grep -F 'allow_implicit_invocation: false' "$metadata_path" >/dev/null; then
    printf '%s\n' \
      'Release skill does not delegate exclusively to the canonical reference.' \
      >&2
    exit 1
  fi

  expected_steps="$(seq -s, 1 41)"
  steps="$(
    grep -E '^[0-9]+\.' "$reference_path" |
      sed 's/\..*$//' |
      paste -sd, -
  )"
  if [ "$steps" != "$expected_steps" ]; then
    printf '%s\n' 'Release guard steps are not contiguous from 1 through 41.' >&2
    exit 1
  fi

  preconditions_line="$(
    grep -n -m 1 -F 'PRÉCONDITIONS AVANT TOUTE MUTATION' \
      "$reference_path" | cut -d: -f1
  )"
  phase_two_line="$(
    grep -n -m 1 -F 'PHASE 2 — PRÉPARATION DU COMMIT' \
      "$reference_path" | cut -d: -f1
  )"
  # shellcheck disable=SC2016
  release_metadata_line="$(
    grep -n -m 1 -F 'program_id`, `name`, `channel`' \
      "$reference_path" | cut -d: -f1
  )"
  metadata_resolution_line="$(
    grep -n -m 1 -F 'Pour chaque valeur, utilise exclusivement' \
      "$reference_path" | cut -d: -f1
  )"
  metadata_validation_line="$(
    grep -n -m 1 -F 'Lorsque toutes les valeurs sont résolues' \
      "$reference_path" | cut -d: -f1
  )"
  if [ -z "$preconditions_line" ] || [ -z "$phase_two_line" ] ||
    [ -z "$release_metadata_line" ] ||
    [ -z "$metadata_resolution_line" ] ||
    [ -z "$metadata_validation_line" ] ||
    [ "$preconditions_line" -ge "$phase_two_line" ] ||
    [ "$release_metadata_line" -ge "$metadata_resolution_line" ] ||
    [ "$metadata_resolution_line" -ge "$metadata_validation_line" ] ||
    [ "$metadata_validation_line" -ge "$phase_two_line" ]; then
    printf '%s\n' \
      'Release prerequisites and metadata are not validated before mutation.' >&2
    exit 1
  fi

  if grep -F 'sans les déduire du repository' "$reference_path" >/dev/null ||
    ! grep -F "une source d'autorité actuelle du repository" \
      "$reference_path" >/dev/null ||
    ! grep -F "le \`manifest.json\` du plus grand tag SemVer stable" \
      "$reference_path" >/dev/null ||
    ! grep -F 'demande uniquement' "$reference_path" >/dev/null ||
    ! grep -F "N'utilise jamais \`null\`" "$reference_path" >/dev/null ||
    ! grep -F 'provenance concise par valeur' "$reference_path" >/dev/null ||
    ! grep -F 'Après validation, enregistre exactement le JSON validé' \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      'Release metadata is not resolved from evidence before user validation.' \
      >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F 'le fichier frère `git-starter-kit-release-package.txt`' \
    "$reference_path" >/dev/null ||
    ! grep -F 'AGENT_RULES_APP_CLIENT_ID' "$reference_path" >/dev/null ||
    ! grep -F 'AGENT_RULES_APP_PRIVATE_KEY' "$reference_path" >/dev/null ||
    ! grep -F 'Elle contient toujours `Agent rules update` et `Repository audit`' \
      "$reference_path" >/dev/null ||
    ! grep -F 'Fixe `RELEASE_STATUS=complete` uniquement après la réussite' \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      'Universal release guard omits common provisioning or completion gates.' \
      >&2
    exit 1
  fi
}

check_initializer_commit_contract() {
  local initializer

  for initializer in tools/git-init.sh tools/git-init.ps1; do
    if ! grep -F 'commitlint --edit' "$initializer" >/dev/null ||
      ! grep -F 'core.hooksPath=.githooks' "$initializer" >/dev/null ||
      ! grep -F -- '--file=' "$initializer" >/dev/null ||
      ! grep -F -- '--cleanup=verbatim' "$initializer" >/dev/null ||
      ! grep -F 'Recorded commit message differs' "$initializer" >/dev/null; then
      printf 'Initializer omits exact-file commit validation: %s\n' \
        "$initializer" >&2
      exit 1
    fi
  done

  if grep -F 'commit -m' tools/git-init.sh >/dev/null ||
    grep -F '"commit", "-m"' tools/git-init.ps1 >/dev/null; then
    printf '%s\n' \
      "Initializer still constructs its initial commit with -m." >&2
    exit 1
  fi
}

check_commit_documentation_contract() {
  # shellcheck disable=SC2016
  if ! grep -F 'commitlint --edit /path/to/commit-message.txt' \
    CONTRIBUTING.md >/dev/null ||
    ! grep -F 'git -c core.hooksPath=.githooks commit' \
      CONTRIBUTING.md >/dev/null ||
    ! grep -F 'Never use `-m` or `--no-verify`' \
      CONTRIBUTING.md >/dev/null; then
    printf '%s\n' \
      "Contributing guide omits blocking exact-file commit validation." >&2
    exit 1
  fi
}

check_release_guard_contract() {
  local reference_path=".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt"
  local release_reference_path=".agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt"

  if [ ! -f "$release_reference_path" ]; then
    printf '%s\n' "Starter release guard extension is missing." >&2
    exit 1
  fi

  if grep -F "token d'installation de la GitHub App" \
    "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard requires obsolete GitHub App authentication." >&2
    exit 1
  fi

  if ! grep -F \
    "les tags historiques d'un autre type comme des exceptions" \
    "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not preserve historical tag exceptions." >&2
    exit 1
  fi

  if ! grep -F "identifie le plus grand tag SemVer stable" \
    "$reference_path" >/dev/null ||
    ! grep -F "présents localement ou sur \`origin\`" \
      "$reference_path" >/dev/null ||
    grep -F "Identifie le dernier tag stable au format SemVer" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not use the highest local or remote SemVer tag." >&2
    exit 1
  fi

  if ! grep -F "Il peut y avoir zéro, un ou plusieurs commits." \
    "$reference_path" >/dev/null ||
    ! grep -F "aucun nouveau commit n'est nécessaire" \
      "$reference_path" >/dev/null ||
    grep -F "aucun changement attendu n'est staged" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard still requires exactly one new commit." >&2
    exit 1
  fi

  if ! grep -F "crée un commit distinct de" \
    "$reference_path" >/dev/null ||
    ! grep -F "préparation du changelog en répétant" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not isolate changelog preparation." >&2
    exit 1
  fi

  if ! grep -F 'git fsck --full' "$reference_path" >/dev/null ||
    ! grep -F 'betterleaks git --staged --redact --no-banner' \
      "$reference_path" >/dev/null ||
    ! grep -F 'gitleaks protect --staged --redact --no-banner' \
      "$reference_path" >/dev/null ||
    ! grep -F 'commitlint --print-config json' \
      "$reference_path" >/dev/null ||
    ! grep -F 'commitlint --edit <fichier-temporaire>' \
      "$reference_path" >/dev/null ||
    grep -F 'git fsck --connectivity-only' \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard omits required commit or repository checks." >&2
    exit 1
  fi

  if ! grep -F 'git -c core.hooksPath=.githooks commit' \
    "$reference_path" >/dev/null ||
    ! grep -F -- '--file=<même-fichier-temporaire>' \
      "$reference_path" >/dev/null ||
    ! grep -F "N'utilise jamais \`git commit -m\`" \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      "Release guard does not commit the exact validated message through hooks." \
      >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F 'codex/release-preflight-<tag>-<sha-court>' \
    "$reference_path" >/dev/null ||
    ! grep -F 'tools/verify-repository-audit-runs.py' \
      "$reference_path" >/dev/null ||
    ! grep -F 'le check `Repository audit` fourni' \
      "$reference_path" >/dev/null ||
    ! grep -F 'REPOSITORY_AUDIT_STATUS=incomplete' \
      "$reference_path" >/dev/null ||
    ! grep -F 'Un autre run vert du même SHA ne compense jamais' \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      "Release guard omits remote preflight or all-run audit enforcement." >&2
    exit 1
  fi

  if ! grep -F "autant de fois que nécessaire" \
    "$reference_path" >/dev/null ||
    ! grep -F "immédiatement avant chaque commit" \
      "$reference_path" >/dev/null ||
    grep -F "Examine une seule fois l'état du working tree" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not recheck repository status." >&2
    exit 1
  fi

  if ! grep -F "Supprime chaque \`.gitkeep\` inutile" \
    "$reference_path" >/dev/null ||
    ! grep -F "inclus explicitement sa" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not remove useless .gitkeep files." >&2
    exit 1
  fi

  if ! grep -F "n'exige aucun token GitHub App" \
    "$release_reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not require public source access." >&2
    exit 1
  fi

  if ! grep -F 'starter-kit-manifest.py --dry-run prepare' \
    "$release_reference_path" >/dev/null ||
    ! grep -F 'starter-kit-manifest.py prepare' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'starter-kit-manifest.py check' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'starter-kit-state' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not prepare and verify the starter manifest." >&2
    exit 1
  fi

  if ! grep -F "contient exactement deux assets nommés" \
    "$release_reference_path" >/dev/null ||
    ! grep -F 'git-starter-kit-<tag>-with-agent-rules.zip' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'git-starter-kit-<tag>-upgrade-toolkit.zip' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not require both release assets." >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F \
    'Enregistre `Release package` comme workflow de release obligatoire' \
    "$release_reference_path" >/dev/null ||
    ! grep -F "Résous avec l'API GitHub l'identité exacte" \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'y ajoute `Release package`' "$reference_path" >/dev/null ||
    grep -F '.github/workflows/agent-rules-update.yml' \
      "$release_reference_path" >/dev/null ||
    grep -F '.github/workflows/repository-audit.yml' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' \
      "Starter release guard duplicates or omits the package-only workflow." >&2
    exit 1
  fi

}
