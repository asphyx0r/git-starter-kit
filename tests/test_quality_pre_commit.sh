#!/usr/bin/env bash
# Test overrides are invoked indirectly by sourced hook functions.
# PATH changes in the focused subshell intentionally do not affect later cases.
# shellcheck disable=SC2329,SC2031
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(git -C "${script_dir}" rev-parse --show-toplevel)"
test_temp="$(mktemp -d "${TMPDIR:-/tmp}/quality-pre-commit.XXXXXX")"
test_temp_parent="${TMPDIR:-/tmp}"

cleanup_test() {
  case "${test_temp}" in
  "${test_temp_parent}"/quality-pre-commit.*)
    rm -rf -- "${test_temp}"
    ;;
  *)
    printf 'Refusing to remove unexpected test path: %s\n' "${test_temp}" >&2
    return 1
    ;;
  esac
}

trap cleanup_test EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

fixture="${test_temp}/repository"
git init -q "${fixture}"
git -C "${fixture}" config user.name "Pre-commit Test"
git -C "${fixture}" config user.email "pre-commit@example.com"
git -C "${fixture}" config core.autocrlf false
mkdir -p "${fixture}/tools"
mkdir -p "${fixture}/tools/quality"
find "${source_root}/tools/quality" -maxdepth 1 -type f \
  -exec cp -- {} "${fixture}/tools/quality/" \;
for generated_quality_path in node_modules __pycache__ .ruff_cache; do
  if [[ -e "${fixture}/tools/quality/${generated_quality_path}" ]]; then
    fail "pre-commit fixture copied generated ${generated_quality_path}"
  fi
done
cp "${source_root}/.codespellrc" "${fixture}/.codespellrc"
cp "${source_root}/.markdownlint-cli2.yaml" \
  "${fixture}/.markdownlint-cli2.yaml"
printf 'base\n' >"${fixture}/base.txt"
git -C "${fixture}" add .
git -C "${fixture}" commit -q -m "test: initialize pre-commit fixture"

# shellcheck disable=SC1090,SC1091
source "${source_root}/tools/repository-audit.sh"
repository_root="${fixture}"
cd "${repository_root}"

run_focused_pre_commit_checks() (
  mode="$1"
  fixture="${test_temp}/focused repository"
  git clone -q --no-hardlinks "${repository_root}" "${fixture}"
  git -C "${fixture}" config user.name 'Pre-commit Test'
  git -C "${fixture}" config user.email 'pre-commit@example.com'
  git -C "${fixture}" config core.autocrlf false
  # This fixture root intentionally stays inside the focused subshell.
  # shellcheck disable=SC2030
  repository_root="${fixture}"
  cd "${repository_root}"
  if [[ "${mode}" == --windows ]]; then
    run_hook_secret_scan() {
      [[ -f "$1/.gitleaks.toml" && -f "$1/tools/quality/versions.json" ]] ||
        fail 'scanner did not receive indexed policy and registry'
      printf '%s\n' "$1" >"${test_temp}/scanner-path"
    }
  fi
  cp "${source_root}/.gitleaks.toml" .gitleaks.toml
  git add .gitleaks.toml
  git commit -q -m 'test: add indexed scanner policy'
  mkdir -p "${test_temp}/hook temporary files"
  export TMPDIR="${test_temp}/hook temporary files"
  run_hook_markdown() {
    [[ "$(cat "$1/document with spaces.md")" == '# indexed content' ]] ||
      fail 'validator did not read indexed Markdown'
    [[ ! -e "$1/base.txt" ]] || fail 'Markdown exported unrelated index files'
    printf '%s\n' "$1" >"${test_temp}/snapshot-path"
    return "${fixture_validator_status:-0}"
  }
  printf '# indexed content\n' >'document with spaces.md'
  git add 'document with spaces.md'
  printf '# unstaged content\n' >'document with spaces.md'
  index_before="$(git hash-object "$(git rev-parse --git-path index)")"
  run_hook_pre_commit || fail 'safe partial index rejected'
  if [[ "${mode}" == --windows ]]; then
    cmp -s "${test_temp}/scanner-path" "${test_temp}/snapshot-path" ||
      fail 'scanner and validator did not receive the same indexed snapshot'
  fi
  [[ "$(git hash-object "$(git rev-parse --git-path index)")" == "${index_before}" ]] ||
    fail 'pre-commit changed the source index'
  [[ ! -e "$(cat "${test_temp}/snapshot-path")" ]] || fail 'success leaked snapshot'
  fixture_validator_status=47
  validator_status=0
  run_hook_pre_commit || validator_status=$?
  ((validator_status == 47)) || fail 'validator failure not preserved'
  [[ ! -e "$(cat "${test_temp}/snapshot-path")" ]] || fail 'failure leaked snapshot'
  fixture_validator_status=0
  git reset -q --hard HEAD
  if [[ "${mode}" != --windows ]]; then
    secret_name='API_TO'
    secret_name+='KEN'
    secret_value='abcd'
    secret_value+='efgh'
    secret_value+='1234'
    secret_value+='5678'
    printf '%s="%s"\n' "${secret_name}" "${secret_value}" >'secret with spaces.txt'
    git add 'secret with spaces.txt'
    printf 'safe working tree\n' >'secret with spaces.txt'
    scanner_cmd="$(resolve_pinned_gitleaks "${fixture}")"
    scanner_status=0
    "${scanner_cmd}" git --pre-commit --staged --config .gitleaks.toml \
      --redact --no-banner --no-color --report-format json \
      --report-path "${test_temp}/findings.json" . >/dev/null 2>&1 || scanner_status=$?
    ((scanner_status == 1)) || fail 'real scanner did not produce fixture finding'
    python -B -c 'import json, sys; print("\n".join(f["Fingerprint"] for f in json.load(open(sys.argv[1]))))' \
      "${test_temp}/findings.json" >.gitleaksignore
    printf '[allowlist]\nregexes = [".*"]\n' >.gitleaks.toml
    if run_hook_pre_commit >"${test_temp}/secret.out" 2>"${test_temp}/secret.err"; then
      fail 'staged secret accepted with safe worktree and unstaged policy'
    fi
    if grep -F "${secret_value}" "${test_temp}/secret.out" "${test_temp}/secret.err"; then
      fail 'scanner output disclosed fixture secret'
    fi
    git add 'secret with spaces.txt'
    printf '%s="%s"\n' "${secret_name}" "${secret_value}" >'secret with spaces.txt'
    run_hook_pre_commit || fail 'unstaged secret confused with safe index'
    [[ -z "$(find "${TMPDIR}" -mindepth 1 -print -quit)" ]] || fail 'scanner leaked temporary files'
    git reset -q --hard HEAD
  fi
  printf '#Bad heading\n' >'invalid staged.md'
  git add 'invalid staged.md'
  printf '# Safe heading\n' >'invalid staged.md'
  run_real_markdown_pre_commit() (
    # Restore the real validator after the controlled routing fixtures above.
    # shellcheck disable=SC1090,SC1091
    source "${source_root}/tools/repository-audit/hooks.sh"
    resolve_hook_node_tool() {
      printf '%s/tools/quality/node_modules/.bin/%s\n' "${source_root}" "$1"
    }
    run_hook_pre_commit
  )
  if run_real_markdown_pre_commit \
    >"${test_temp}/real-markdown.out" 2>"${test_temp}/real-markdown.err"; then
    fail 'real Markdownlint skipped invalid index under ignored temporary parent'
  fi
  grep -F MD018 "${test_temp}/real-markdown.err" >/dev/null || {
    cat "${test_temp}/real-markdown.out" "${test_temp}/real-markdown.err" >&2
    fail 'real Markdown validator did not inspect indexed content'
  }
  git reset -q --hard HEAD
  mkdir -p docs
  printf '{"MD013": false}\n' >docs/.markdownlint.json
  printf 'ignored.md\n' >docs/.gitignore
  git add docs/.markdownlint.json docs/.gitignore
  git commit -q -m 'test: add nested indexed Markdown policy'
  printf '# Nested document\n\n' >docs/example.md
  printf '%160s\n' '' | tr ' ' x >>docs/example.md
  printf '#Bad heading\n' >docs/ignored.md
  git add -f docs/example.md docs/ignored.md
  printf '{"MD013": true}\n' >docs/.markdownlint.json
  printf '' >docs/.gitignore
  run_real_markdown_pre_commit \
    >"${test_temp}/nested-markdown.out" 2>"${test_temp}/nested-markdown.err" || {
    cat "${test_temp}/nested-markdown.err" >&2
    fail 'nested indexed Markdown configuration or ignore file was omitted'
  }
  grep -F 'Linting: 1 file' "${test_temp}/nested-markdown.out" >/dev/null ||
    fail 'nested Markdown fixture did not lint exactly its selected nonignored file'
  git reset -q --hard HEAD
  printf 'MD013: false\n' >docs/.markdownlint.yaml
  printf '# Changed document\n' >docs/example.md
  git add docs/.markdownlint.yaml docs/example.md
  run_real_markdown_pre_commit \
    >"${test_temp}/changed-config.out" 2>"${test_temp}/changed-config.err" || {
    cat "${test_temp}/changed-config.err" >&2
    fail 'selected Markdown configuration was exported more than once'
  }
  [[ -z "$(find "${TMPDIR}" -mindepth 1 -print -quit)" ]] || fail 'real Markdown check leaked snapshots'
  printf '%s\n' 'PASS: focused staged content, spaces, indexed policy and cleanup'
)

if [[ "${1:-}" == --windows ]]; then
  run_focused_pre_commit_checks --windows
  exit 0
fi

run_indexed_workflow_checks() (
  fixture="${test_temp}/workflow repository"
  git clone -q --no-hardlinks "${repository_root}" "${fixture}"
  git -C "${fixture}" config user.name 'Pre-commit Test'
  git -C "${fixture}" config user.email 'pre-commit@example.com'
  git -C "${fixture}" config core.autocrlf false
  repository_root="${fixture}"
  cd "${repository_root}"
  mkdir -p .github/workflows tools/repository-audit
  # Isolate real Actionlint discovery from unrelated scanner/YAML/semantic checks.
  run_hook_secret_scan() { return 0; }
  run_hook_yaml() { return 0; }
  printf 'pass\n' >tools/repository-audit/workflow-contracts.py
  cat >"${test_temp}/safe-workflow.yaml" <<'YAML'
name: Snapshot fixture
on: push
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - run: echo safe
YAML
  cp "${test_temp}/safe-workflow.yaml" .github/workflows/snapshot.yaml
  git add .
  git commit -q -m 'test: add workflow discovery fixture'
  sed 's/ubuntu-latest/${{ imaginary.context }}/' "${test_temp}/safe-workflow.yaml" \
    >.github/workflows/snapshot.yaml
  git add .github/workflows/snapshot.yaml
  cp "${test_temp}/safe-workflow.yaml" .github/workflows/snapshot.yaml
  if run_hook_pre_commit >"${test_temp}/workflow.out" 2>"${test_temp}/workflow.err"; then
    fail 'real Actionlint accepted invalid indexed workflow with safe worktree'
  fi
  grep -F 'undefined variable "imaginary"' "${test_temp}/workflow.out" >/dev/null || {
    cat "${test_temp}/workflow.out" "${test_temp}/workflow.err" >&2
    fail 'real Actionlint did not report the indexed workflow error'
  }
  printf '\n' >>.github/workflows/snapshot.yaml
  git add .github/workflows/snapshot.yaml
  sed 's/ubuntu-latest/${{ imaginary.context }}/' "${test_temp}/safe-workflow.yaml" \
    >.github/workflows/snapshot.yaml
  run_hook_pre_commit || fail 'real Actionlint read invalid worktree over safe index'
  printf '%s\n' 'PASS: real Actionlint uses indexed workflows in both directions'
)

run_indexed_workflow_checks
run_focused_pre_commit_checks full
run_hook_secret_scan() { return 0; }

release_fixture="${test_temp}/release-artifact-repository"
release_metadata="${test_temp}/release-artifact-metadata.json"
git clone -q --no-hardlinks "${source_root}" "${release_fixture}"
git -C "${release_fixture}" config user.name "Pre-commit Test"
git -C "${release_fixture}" config user.email "pre-commit@example.com"
printf 'release candidate\n' >"${release_fixture}/release-candidate.txt"
git -C "${release_fixture}" add release-candidate.txt
git -C "${release_fixture}" commit -q -m "test: add release candidate"
release_date="$(
  python - "${release_fixture}/manifest.json" "${release_metadata}" <<'PYTHON'
import json
import sys

manifest_path, metadata_path = sys.argv[1:]
manifest = json.load(open(manifest_path, encoding="utf-8"))
metadata = {
    key: manifest[key]
    for key in (
        "program_id",
        "name",
        "channel",
        "critical_update",
        "release_notes",
        "update",
        "metadata",
    )
}
artifact = manifest["artifacts"][0]
metadata["artifact"] = {"id": artifact["id"], "target": artifact["target"]}
with open(metadata_path, "w", encoding="utf-8") as stream:
    json.dump(metadata, stream)
    stream.write("\n")
print(manifest["release_date"])
PYTHON
)"
release_ref="v$(tr -d '\r\n' <"${release_fixture}/VERSION")"
(
  cd "${release_fixture}"
  python tools/release-artifacts.py --force prepare \
    --release-ref "${release_ref}" \
    --release-date "${release_date}" \
    --metadata-file "${release_metadata}" >/dev/null
)
git -C "${release_fixture}" diff --quiet -- VERSION ||
  fail "release artifact preparation changed VERSION"
git -C "${release_fixture}" diff --quiet -- SHA256SUMS &&
  fail "release artifact preparation did not update SHA256SUMS"
git -C "${release_fixture}" diff --quiet -- manifest.json &&
  fail "release artifact preparation did not update manifest.json"
git -C "${release_fixture}" add SHA256SUMS manifest.json
printf '%s\n' SHA256SUMS manifest.json >"${test_temp}/release-paths.expected"
git -C "${release_fixture}" diff --cached --name-only \
  >"${test_temp}/release-paths.actual"
cmp -s "${test_temp}/release-paths.expected" \
  "${test_temp}/release-paths.actual" ||
  fail "release fixture did not stage only coherent artifact updates"
(
  cd "${release_fixture}"
  repository_root="${release_fixture}"
  run_hook_pre_commit
) || fail "pre-commit rejected coherent artifact updates with unchanged VERSION"

for failed_diff_position in 1 2 3; do
  git reset -q --hard HEAD
  diff_case_root="${test_temp}/diff-${failed_diff_position}"
  mkdir -p "${diff_case_root}"
  diff_count_file="${diff_case_root}/count"
  printf '%s\n' 0 >"${diff_count_file}"
  diff_status=0
  diff_failure_status=$((41 + failed_diff_position))
  if (
    git() {
      if [[ "${1:-}" == diff && "${2:-}" == --cached ]]; then
        local diff_count
        diff_count="$(cat "${diff_count_file}")"
        diff_count=$((diff_count + 1))
        printf '%s\n' "${diff_count}" >"${diff_count_file}"
        if ((diff_count == failed_diff_position)); then
          return "${diff_failure_status}"
        fi
      fi
      command git "$@"
    }
    TMPDIR="${diff_case_root}" run_hook_pre_commit
  ); then
    fail "pre-commit accepted git diff failure ${failed_diff_position}"
  else
    diff_status=$?
  fi
  if ((diff_status != diff_failure_status)); then
    fail "git diff failure ${failed_diff_position} returned ${diff_status} instead of ${diff_failure_status}"
  fi
  if find "${diff_case_root}" -mindepth 1 \
    ! -name count -print -quit | grep -q .; then
    fail "git diff failure ${failed_diff_position} leaked a staged checkout"
  fi
done

quality_bin="${test_temp}/bin"
mkdir -p "${quality_bin}"
export QUALITY_DECLARATION_REAL_PYTHON
QUALITY_DECLARATION_REAL_PYTHON="$(command -v python)"
cat >"${quality_bin}/python" <<'PYTHON'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == -B ]]; then
  exec "${QUALITY_DECLARATION_REAL_PYTHON}" "$@"
fi
printf '%s\n' "$@" >"${QUALITY_DECLARATION_TRACE}.arguments"
quality_root=""
while (($#)); do
  if [[ "$1" == --quality-root ]]; then
    quality_root="$2"
    break
  fi
  shift
done
[[ -n "${quality_root}" ]]
cat "${quality_root}/requirements.in" >"${QUALITY_DECLARATION_TRACE}.content"
PYTHON
chmod +x "${quality_bin}/python"

printf '\n# staged-quality-marker\n' >>tools/quality/requirements.in
git add tools/quality/requirements.in
printf '# unstaged-quality-marker\n' >>tools/quality/requirements.in
export QUALITY_DECLARATION_TRACE="${test_temp}/declarations"
PATH="${quality_bin}:${PATH}" run_hook_pre_commit
grep -Fx '# staged-quality-marker' "${QUALITY_DECLARATION_TRACE}.content" \
  >/dev/null || fail "quality checker did not read staged declarations"
if grep -F 'unstaged-quality-marker' "${QUALITY_DECLARATION_TRACE}.content" \
  >/dev/null; then
  fail "quality checker read unstaged declarations"
fi
grep -F -- '--quality-root' "${QUALITY_DECLARATION_TRACE}.arguments" \
  >/dev/null || fail "quality checker did not receive its staged root"

git reset -q --hard HEAD
cat >"${quality_bin}/codespell" <<'CODESPELL'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$PWD" >"${QUALITY_CODESPELL_TRACE}.cwd"
cat .codespellrc >"${QUALITY_CODESPELL_TRACE}.content"
CODESPELL
chmod +x "${quality_bin}/codespell"
printf '\n# staged-spelling-marker\n' >>.codespellrc
git add .codespellrc
printf '# unstaged-spelling-marker\n' >>.codespellrc
export QUALITY_CODESPELL_TRACE="${test_temp}/codespell"
PATH="${quality_bin}:${PATH}" run_hook_pre_commit
grep -Fx '# staged-spelling-marker' "${QUALITY_CODESPELL_TRACE}.content" \
  >/dev/null || fail "Codespell did not read the staged configuration"
if grep -F 'unstaged-spelling-marker' "${QUALITY_CODESPELL_TRACE}.content" \
  >/dev/null; then
  fail "Codespell read the unstaged configuration"
fi

for required_configuration in \
  tools/quality/PSScriptAnalyzerSettings.psd1 \
  tools/quality/yamllint.yaml \
  .markdownlint-cli2.yaml; do
  git reset -q --hard HEAD
  git rm -q -- "${required_configuration}"
  deleted_configuration_status=0
  if PATH="${quality_bin}:${PATH}" run_hook_pre_commit \
    >"${test_temp}/deleted-config.out" \
    2>"${test_temp}/deleted-config.err"; then
    fail "pre-commit accepted deleted ${required_configuration}"
  else
    deleted_configuration_status=$?
  fi
  if ((deleted_configuration_status == 0)); then
    fail "deleted ${required_configuration} returned success"
  fi
  grep -F -- "${required_configuration}" \
    "${test_temp}/deleted-config.err" >/dev/null ||
    fail "deleted configuration diagnostic omitted ${required_configuration}"
done

git reset -q --hard HEAD
git mv .markdownlint-cli2.yaml markdownlint-config-away.txt
rename_away_status=0
if PATH="${quality_bin}:${PATH}" run_hook_pre_commit \
  >"${test_temp}/rename-away.out" \
  2>"${test_temp}/rename-away.err"; then
  fail "pre-commit accepted a renamed-away Markdownlint configuration"
else
  rename_away_status=$?
fi
if ((rename_away_status == 0)); then
  fail "renamed-away Markdownlint configuration returned success"
fi
grep -F -- '.markdownlint-cli2.yaml' \
  "${test_temp}/rename-away.err" >/dev/null ||
  fail "rename-away diagnostic omitted .markdownlint-cli2.yaml"

invalid_configuration_paths=(
  tools/quality/PSScriptAnalyzerSettings.psd1
  tools/quality/yamllint.yaml
  .markdownlint-cli2.yaml
)
invalid_configuration_statuses=(51 52 53)
cat >"${quality_bin}/powershell.exe" <<'POWERSHELL_CONFIG'
#!/usr/bin/env bash
set -euo pipefail

[[ -z "${AUDIT_PS_PATH:-}" ]] || exit 54
[[ "${AUDIT_PS_SETTINGS}" == *PSScriptAnalyzerSettings.psd1 ]]
[[ "$*" == *'-ScriptDefinition'* ]] || exit 55
[[ "$*" == *'$ErrorActionPreference = "Stop"'* ]] || exit 56
exit 51
POWERSHELL_CONFIG
cp -- "${quality_bin}/powershell.exe" "${quality_bin}/pwsh"
cat >"${quality_bin}/yamllint" <<'YAMLLINT_CONFIG'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${*: -1}" == ./tools/quality/yamllint.yaml ]]; then
  grep -F 'invalid-configuration-marker' \
    tools/quality/yamllint.yaml >/dev/null
  exit 52
fi
exit 0
YAMLLINT_CONFIG
cat >"${quality_bin}/markdownlint-cli2" <<'MARKDOWNLINT_CONFIG'
#!/usr/bin/env bash
set -euo pipefail

config_path=''
saw_no_globs=false
saw_stdin=false
while (($#)); do
  case "$1" in
  --config)
    config_path="$2"
    shift 2
    ;;
  --no-globs)
    saw_no_globs=true
    shift
    ;;
  -)
    saw_stdin=true
    shift
    ;;
  *)
    shift
    ;;
  esac
done
[[ "${config_path}" == .markdownlint-cli2.yaml ]]
[[ "${saw_no_globs}" == true && "${saw_stdin}" == true ]]
cat >/dev/null
grep -F 'invalid-configuration-marker' "${config_path}" >/dev/null
exit 53
MARKDOWNLINT_CONFIG
chmod +x \
  "${quality_bin}/markdownlint-cli2" \
  "${quality_bin}/powershell.exe" \
  "${quality_bin}/pwsh" \
  "${quality_bin}/yamllint"
for configuration_index in 0 1 2; do
  git reset -q --hard HEAD
  invalid_configuration="${invalid_configuration_paths[configuration_index]}"
  printf '%s\n' '# invalid-configuration-marker' \
    >"${invalid_configuration}"
  git add -- "${invalid_configuration}"
  invalid_configuration_status=0
  (
    PATH="${quality_bin}:${PATH}" run_hook_pre_commit
  ) || invalid_configuration_status=$?
  if ((invalid_configuration_status != \
    invalid_configuration_statuses[configuration_index])); then
    fail "invalid ${invalid_configuration} returned ${invalid_configuration_status} instead of ${invalid_configuration_statuses[configuration_index]}"
  fi
done

git reset -q --hard HEAD
cat >"${quality_bin}/markdownlint-cli2" <<'MARKDOWNLINT'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$PWD" >"${QUALITY_SIGNAL_TRACE}"
while [[ ! -s "${QUALITY_SIGNAL_TARGET_FILE}" ]]; do
  sleep 0.05
done
kill -TERM "$(cat "${QUALITY_SIGNAL_TARGET_FILE}")"
MARKDOWNLINT
chmod +x "${quality_bin}/markdownlint-cli2"
printf '# signal\n' >signal.md
git add signal.md
export QUALITY_SIGNAL_TRACE="${test_temp}/signal-root"
export QUALITY_SIGNAL_TARGET_FILE="${test_temp}/signal-target"
PATH="${quality_bin}:${PATH}" run_hook_pre_commit >/dev/null 2>&1 &
signal_hook_pid=$!
printf '%s\n' "${signal_hook_pid}" >"${QUALITY_SIGNAL_TARGET_FILE}"
signal_status=0
if wait "${signal_hook_pid}"; then
  fail "pre-commit accepted a terminated staged check"
else
  signal_status=$?
fi
((signal_status == 143)) ||
  fail "pre-commit returned ${signal_status} instead of 143 after TERM"
signal_root="$(cat "${QUALITY_SIGNAL_TRACE}")"
for _ in {1..40}; do
  [[ ! -e "${signal_root}" ]] && break
  sleep 0.05
done
if [[ -e "${signal_root}" ]]; then
  fail "pre-commit leaked its staged checkout after TERM"
fi

printf '%s\n' 'PASS: staged quality selection and cleanup'
