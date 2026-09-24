#!/usr/bin/env bash
# Test overrides are invoked indirectly by sourced dispatcher functions.
# shellcheck disable=SC2329
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(git -C "${script_dir}" rev-parse --show-toplevel)"
dispatcher="${source_root}/tools/repository-audit.sh"
test_temp="$(mktemp -d "${TMPDIR:-/tmp}/repository-audit-test.XXXXXX")"

cleanup_test() {
  case "$(basename "${test_temp}")" in
  repository-audit-test.*)
    rm -rf -- "${test_temp}"
    ;;
  *)
    printf 'Refusing to remove unexpected test path: %s\n' "${test_temp}" >&2
    return 1
    ;;
  esac
}

trap cleanup_test EXIT

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

run_nested_failure_checks() (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  initialize_repository_root
  local trace="${test_temp}/nested.trace" status=0
  (
    unset GITHUB_EVENT_NAME GITHUB_BASE_REF BEFORE_SHA
    git() {
      printf 'git\n' >>"${trace}"
      return 23
    }
    check_git_whitespace || status=$?
    ((status == 23)) || fail 'actual whitespace helper ignored its first Git failure'
    [[ "$(wc -l <"${trace}")" == 1 ]] || fail 'whitespace helper continued after failure'
  )
  : >"${trace}"
  (
    git() { printf '%s\n' first.ps1 second.ps1; }
    failing_node() {
      printf 'node\n' >>"${trace}"
      return 23
    }
    check_powershell_line_endings failing_node || status=$?
    ((status == 23)) || fail 'actual line-ending helper ignored its intermediate Node failure'
    [[ "$(wc -l <"${trace}")" == 1 ]] || fail 'line-ending helper continued after failure'
  )
  (
    resolve_command() { return 23; }
    check_workflow_contract repository-audit .github/workflows/repository-audit.yml || status=$?
    ((status == 23)) || fail 'workflow helper ignored its Python resolution failure'
  )
  (
    resolve_hook_command() { printf '%s\n' coverage_stage; }
    resolve_hook_python() { printf '%s\n' coverage_python; }
    ensure_audit_temp() { audit_temp="${test_temp}"; }
    coverage_python() { return 0; }
    coverage_stage() { [[ "$1" != "${failed_coverage_stage}" ]] || return 23; }
    local failed_coverage_stage
    for failed_coverage_stage in run json report; do
      status=0
      run_python_coverage || status=$?
      ((status == 23)) || fail "coverage orchestration swallowed ${failed_coverage_stage} failure"
    done
  )
  (
    git() { return 23; }
    local helper
    for helper in run_powershell_static run_powershell_parse_readonly; do
      status=0
      "${helper}" || status=$?
      ((status == 23)) || fail "${helper} ignored its Git path listing failure"
    done
  )
  : >"${trace}"
  (
    require_command() { return 0; }
    resolve_command() { printf '%s\n' smoke_python; }
    resolve_hook_node_tool() { printf '%s\n' true; }
    resolve_powershell_command() { printf '%s\n' true; }
    ensure_audit_temp() {
      audit_temp="${test_temp}/smoke-stage"
      mkdir -p "${audit_temp}"
    }
    smoke_python() {
      printf '%s\n' "$*" >>"${trace}"
      [[ "$*" != 'tools/starter-kit-manifest.py --version' ]] || return 23
    }
    run_script_smoke || status=$?
    ((status == 23)) || fail 'actual smoke orchestration swallowed intermediate CLI failure'
    [[ "$(tail -n 1 "${trace}")" == 'tools/starter-kit-manifest.py --version' ]] || fail 'smoke continued after failed CLI'
  )
  printf '%s\n' 'PASS: actual nested whitespace, line-ending, workflow, coverage and smoke failure propagation'
)

run_profile_failure_checks() (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  initialize_repository_root
  resolve_validation_scope() { printf '%s\n' source; }
  profile_stage() {
    printf '%s\n' "$1" >>"${profile_trace}"
    [[ "$1" != "${failed_profile_stage}" ]] || return 23
  }
  require_command() { profile_stage "require-$1"; }
  resolve_command() {
    profile_stage "resolve-$1" || return
    printf 'profile_%s\n' "$1"
  }
  resolve_hook_command() { resolve_command "$2"; }
  resolve_hook_python() { resolve_command python; }
  resolve_hook_node_tool() {
    profile_stage "resolve-$1" || return
    case "$1" in
    markdownlint-cli2) printf '%s\n' profile_markdown ;;
    *) printf 'profile_%s\n' "$1" ;;
    esac
  }
  profile_node() { profile_stage node; }
  profile_python() { profile_stage versions; }
  profile_ruff() { profile_stage "ruff-$1"; }
  profile_mypy() { profile_stage mypy; }
  profile_markdown() { profile_stage markdown; }
  profile_codespell() { profile_stage spelling; }
  profile_yamllint() { profile_stage yaml; }
  profile_actionlint() { profile_stage actionlint; }
  profile_gitleaks() { profile_stage gitleaks; }
  profile_shellcheck() { profile_stage "shellcheck-$1"; }
  profile_shfmt() { profile_stage "shfmt-${4:-version}"; }
  profile_commitlint() {
    if (($# == 2)); then cat >/dev/null; fi
    profile_stage "commitlint-${3:-root}"
  }
  resolve_audit_to_ref() { printf '%s\n' HEAD; }
  # The marker is initialized by sourced common.sh.
  # shellcheck disable=SC2154
  resolve_audit_from_ref() { printf '%s\n' "${audit_all_commits_marker}"; }
  check_git_whitespace() { profile_stage whitespace; }
  check_powershell_line_endings() { profile_stage powershell-eol; }
  bash() { profile_stage "bash-${2:-$1}"; }
  run_markdown() { profile_stage markdown; }
  run_spelling() { profile_stage spelling; }
  run_yamllint() { profile_stage yaml; }
  run_actionlint() { profile_stage actionlint; }
  run_powershell_static() { profile_stage powershell-static; }
  check_semver_pattern_drift() { profile_stage semver; }
  check_initializer_commit_contract() { profile_stage initializer; }
  check_commit_documentation_contract() { profile_stage commit-contract; }
  check_secret_scanner_config_contract() { profile_stage scanner-contract; }
  run_full_secret_scan() { profile_stage security; }
  check_agent_rules_update_workflow_contract() { profile_stage workflow; }
  check_repository_audit_workflow_contract() { profile_stage workflow; }
  check_guarded_pull_request_merge_workflow_contract() { profile_stage workflow; }
  check_release_artifact_contract() { profile_stage artifacts; }
  check_release_skill_contract() { profile_stage release-skill; }
  check_release_package_portability() { profile_stage portability; }
  check_release_guard_contract() { profile_stage release-guard; }
  run_python_coverage() { profile_stage coverage; }
  run_script_smoke() { profile_stage smoke; }
  run_powershell_parse_readonly() { profile_stage powershell-parse; }
  check_secret_scanner_behavior() { profile_stage scanner-behavior; }
  run_project_checks() { profile_stage project-plan; }

  local mode stage profile_status
  for mode in fast static full all readonly; do
    local -a stages=(require-git resolve-node whitespace powershell-eol bash-.githooks/pre-commit node)
    if [[ "${mode}" != readonly ]]; then
      stages+=(versions ruff-check ruff-format mypy)
    fi
    if [[ "${mode}" != fast ]]; then
      stages+=(markdown shellcheck-.githooks/pre-commit shfmt-tests/test_commit_message_validation.sh semver workflow artifacts commitlint-root)
      if [[ "${mode}" != readonly ]]; then
        stages+=(coverage bash-tests/test_repository_audit.sh smoke)
      else
        stages+=(powershell-parse scanner-behavior security)
      fi
    fi
    for stage in "${stages[@]}"; do
      profile_trace="${test_temp}/profile-${mode}-${stage//\//-}.trace"
      failed_profile_stage="${stage}"
      profile_status=0
      main "${mode}" >"${test_temp}/profile-failure.out" 2>"${test_temp}/profile-failure.err" || profile_status=$?
      if ((profile_status != 23)); then
        cat "${test_temp}/profile-failure.out" "${test_temp}/profile-failure.err" >&2
        fail "actual ${mode} orchestration ignored ${stage}: status ${profile_status}"
      fi
      [[ "$(tail -n 1 "${profile_trace}")" == "${stage}" ]] || fail "${mode} continued after ${stage}"
      if grep -F 'Core validation: passed' "${test_temp}/profile-failure.out" >/dev/null ||
        grep -Fx project-plan "${profile_trace}" >/dev/null; then
        fail "${mode} reported passing validation after ${stage}"
      fi
    done
    profile_trace="${test_temp}/profile-${mode}-success.trace"
    failed_profile_stage=''
    main "${mode}" >"${test_temp}/profile-success.out" || {
      cat "${profile_trace}" >&2
      fail "${mode} success composition failed"
    }
    [[ "$(tail -n 1 "${profile_trace}")" == project-plan ]] || fail "${mode} omitted its final project plan"
    grep -F 'Core validation: passed' "${test_temp}/profile-success.out" >/dev/null || fail "${mode} omitted passing core state"
  done
  printf '%s\n' 'PASS: actual source profile failure propagation and successful composition'
)

run_manifest_smoke_checks() (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  local python_cmd historical_tag='' tag
  python_cmd="$(resolve_command python python3 python.exe)"
  while IFS= read -r tag; do
    if git -C "${source_root}" cat-file -e "${tag}:starter-kit-manifest.json" 2>/dev/null; then
      historical_tag="${tag}"
      break
    fi
  done < <(git -C "${source_root}" for-each-ref --sort=-version:refname --format='%(refname)' refs/tags)
  [[ -n "${historical_tag}" ]] || fail 'manifest smoke requires a released manifest fixture'
  repository_root="${test_temp}/manifest source with spaces"
  git clone --quiet --local --no-hardlinks --no-checkout -- "${source_root}" "${repository_root}"
  git -C "${repository_root}" -c core.autocrlf=false checkout --quiet --detach "${historical_tag}"
  git -C "${repository_root}" config core.autocrlf false
  git -C "${repository_root}" remote set-url origin https://github.com/asphyx0r/git-starter-kit.git
  cp "${source_root}/tools/starter-kit-manifest.py" "${source_root}/tools/git_objects.py" \
    "${source_root}/tools/process_runner.py" "${repository_root}/tools/"
  cd "${repository_root}"
  audit_temp="${test_temp}/manifest-valid"
  mkdir -p "${audit_temp}"
  run_starter_manifest_smoke "${python_cmd}" >"${test_temp}/manifest-valid.out" || fail 'historical manifest failed its release policy'
  "${python_cmd}" -B - <<'PY'
import json
from pathlib import Path

path = Path("starter-kit-manifest.json")
value = json.loads(path.read_text(encoding="utf-8"))
value["files"][0]["sha256"] = "0" * 64
path.write_text(json.dumps(value), encoding="utf-8")
PY
  audit_temp="${test_temp}/manifest-altered"
  mkdir -p "${audit_temp}"
  if run_starter_manifest_smoke "${python_cmd}" >"${test_temp}/manifest-altered.out" 2>&1; then
    fail 'historical smoke accepted altered source JSON'
  fi
  grep -F 'does not match its release tag' "${test_temp}/manifest-altered.out" >/dev/null || fail 'altered manifest lost authentication diagnostic'
  [[ ! -e "${audit_temp}/starter-manifest-release" ]] || fail 'altered manifest reached release execution'
  git -C "${repository_root}" add -- tools/starter-kit-manifest.py tools/git_objects.py tools/process_runner.py
  local candidate_ref="v0.0.0-manifest-smoke.${BASHPID}"
  "${python_cmd}" -B tools/starter-kit-manifest.py prepare --release-ref "${candidate_ref}" >/dev/null
  audit_temp="${test_temp}/manifest-candidate"
  mkdir -p "${audit_temp}"
  run_starter_manifest_smoke "${python_cmd}" >"${test_temp}/manifest-candidate.out" || fail 'untagged candidate failed current strict check'
  [[ ! -e "${audit_temp}/starter-manifest-release" ]] || fail 'untagged candidate executed historical policy'
  printf '# Changed candidate\n' >README.md
  git -C "${repository_root}" add -- README.md
  if run_starter_manifest_smoke "${python_cmd}" >"${test_temp}/manifest-candidate-drift.out" 2>&1; then
    fail 'untagged candidate accepted indexed inventory drift'
  fi
  grep -F 'inventory does not match' "${test_temp}/manifest-candidate-drift.out" >/dev/null || fail 'candidate lost strict inventory diagnostic'
  printf '%s\n' 'PASS: historical manifest authentication and release policy; strict untagged candidate'
)

if [[ "${1:-}" == --manifest-smoke ]]; then
  run_manifest_smoke_checks
  exit
fi

if [[ "${1:-}" == --profile-failures ]]; then
  run_nested_failure_checks
  run_profile_failure_checks
  exit
fi

run_manifest_smoke_checks

run_powershell_host_checks() (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  initialize_repository_root
  (
    uname() { printf '%s\n' Linux; }
    wslpath() { printf 'windows:%s\n' "$2"; }
    export WSL_DISTRO_NAME=regression
    local path='/tmp/path with spaces/valid.ps1'
    [[ "$(to_pwsh_path "${path}" /opt/pwsh)" == "${path}" ]] || fail 'native pwsh path was converted to Windows'
    [[ "$(to_hook_host_path "${path}" /opt/pwsh)" == "${path}" ]] || fail 'native analyzer path was converted to Windows'
    [[ "$(to_pwsh_path "${path}" /mnt/c/pwsh.exe)" == "windows:${path}" ]] || fail 'Windows pwsh path was not converted'
    [[ "$(to_hook_host_path "${path}" /mnt/c/pwsh.exe)" == "windows:${path}" ]] || fail 'Windows analyzer path was not converted'
    [[ "$(to_pwsh_path "${path}")" == "windows:${path}" ]] || fail 'legacy converter behavior changed'
  )
  local fixture="${test_temp}/PowerShell host fixture"
  mkdir -p "${fixture}/tools/quality"
  # This writes literal PowerShell source.
  # shellcheck disable=SC2016
  printf '$null = "valid"\n' >"${fixture}/valid.ps1"
  printf 'function Broken {\n' >"${fixture}/invalid.psm1"
  printf '@{ Rules = @{} }\n' >"${fixture}/tools/quality/PSScriptAnalyzerSettings.psd1"
  repository_root="${fixture}"
  run_powershell_parse_paths valid.ps1 tools/quality/PSScriptAnalyzerSettings.psd1 || fail 'native valid PowerShell parsing failed'
  if run_powershell_parse_paths invalid.psm1 >"${test_temp}/ps-invalid.out" 2>&1; then fail 'invalid PowerShell parsed successfully'; fi
  if run_powershell_parse_paths missing.ps1 >"${test_temp}/ps-missing.out" 2>&1; then fail 'missing PowerShell parsed successfully'; fi
  run_hook_powershell_static "${fixture}" valid.ps1 || fail 'native analyzer rejected valid input/settings'
  run_hook_powershell_settings "${fixture}" || fail 'native analyzer settings failed'
  printf '@{}\n' >"${fixture}/tools/quality/PSScriptAnalyzerSettings.psd1"
  run_hook_powershell_static "${fixture}" tools/quality/PSScriptAnalyzerSettings.psd1 || fail 'settings data was treated as a module manifest'
  rm "${fixture}/invalid.psm1"
  git init -q "${fixture}"
  cp "${source_root}/.gitattributes" "${fixture}/.gitattributes"
  git -C "${fixture}" add valid.ps1 tools/quality/PSScriptAnalyzerSettings.psd1
  git -C "${fixture}" check-attr eol -- valid.ps1 tools/quality/PSScriptAnalyzerSettings.psd1 >"${test_temp}/ps-real-attributes.out"
  grep -F 'valid.ps1: eol: crlf' "${test_temp}/ps-real-attributes.out" >/dev/null || fail 'real Git attributes did not select CRLF for ps1'
  grep -F 'PSScriptAnalyzerSettings.psd1: eol: lf' "${test_temp}/ps-real-attributes.out" >/dev/null || fail 'real Git attributes did not preserve LF settings'
  # These variables contain literal PowerShell source.
  # shellcheck disable=SC2016
  local valid_powershell='$null = "valid"' mixed_powershell='$null = "mixed"'
  printf '%s\r\n' "${valid_powershell}" >"${fixture}/valid.ps1"
  (
    cd "${fixture}"
    check_powershell_line_endings "$(command -v node)"
  ) || fail 'CRLF ps1 and LF settings did not pass'
  printf '%s\n' "${valid_powershell}" >"${fixture}/valid.ps1"
  if (
    cd "${fixture}"
    check_powershell_line_endings "$(command -v node)"
  ) >"${test_temp}/ps-lf.out" 2>&1; then fail 'LF ps1 passed CRLF guard'; fi
  printf '%s\r\n%s\n' "${valid_powershell}" "${mixed_powershell}" >"${fixture}/valid.ps1"
  if (
    cd "${fixture}"
    check_powershell_line_endings "$(command -v node)"
  ) >"${test_temp}/ps-mixed.out" 2>&1; then fail 'mixed ps1 passed CRLF guard'; fi
  printf '%s\r\n' "${valid_powershell}" >"${fixture}/valid.ps1"
  [[ "$(git -C "${fixture}" hash-object tools/quality/PSScriptAnalyzerSettings.psd1)" == "$(git -C "${fixture}" rev-parse :tools/quality/PSScriptAnalyzerSettings.psd1)" ]] || fail 'settings LF bytes changed during line-ending checks'
  (
    cd "${fixture}"
    run_powershell_static
  ) || fail 'full source analyzer rejected settings data'
  printf '@{}\n' >"${fixture}/invalid-manifest.psd1"
  if run_hook_powershell_static "${fixture}" invalid-manifest.psd1 >"${test_temp}/ps-invalid-manifest.out" 2>&1; then fail 'analyzer accepted a real invalid manifest'; fi
  grep -F PSMissingModuleManifestField "${test_temp}/ps-invalid-manifest.out" >/dev/null || fail 'invalid manifest lost its analyzer diagnostic'
  git -C "${fixture}" add invalid-manifest.psd1
  if (
    cd "${fixture}"
    run_powershell_static
  ) >"${test_temp}/ps-invalid-manifest-full.out" 2>&1; then fail 'full source analyzer accepted a real invalid manifest'; fi
  git -C "${fixture}" rm -q --cached invalid-manifest.psd1
  rm "${fixture}/invalid-manifest.psd1"
  if run_hook_powershell_static "${fixture}" missing.ps1 >"${test_temp}/ps-analyzer-missing.out" 2>&1; then fail 'analyzer accepted missing input'; fi
  printf 'Write-Host "finding"\n' >"${fixture}/finding.ps1"
  printf "@{ IncludeRules = @('PSAvoidUsingWriteHost') }\n" >"${fixture}/tools/quality/PSScriptAnalyzerSettings.psd1"
  if run_hook_powershell_static "${fixture}" finding.ps1 >"${test_temp}/ps-analyzer-finding.out" 2>&1; then fail 'analyzer findings passed'; fi
  printf '@{ invalid\n' >"${fixture}/tools/quality/PSScriptAnalyzerSettings.psd1"
  if run_hook_powershell_static "${fixture}" tools/quality/PSScriptAnalyzerSettings.psd1 >"${test_temp}/ps-malformed-settings-route.out" 2>&1; then fail 'routed analyzer accepted malformed settings'; fi
  if (
    cd "${fixture}"
    run_powershell_static
  ) >"${test_temp}/ps-malformed-settings-full.out" 2>&1; then fail 'full source analyzer accepted malformed settings'; fi
  if run_hook_powershell_static "${fixture}" valid.ps1 >"${test_temp}/ps-malformed-settings.out" 2>&1; then fail 'analyzer accepted malformed settings'; fi
  rm "${fixture}/tools/quality/PSScriptAnalyzerSettings.psd1"
  if run_hook_powershell_static "${fixture}" valid.ps1 >"${test_temp}/ps-analyzer-settings.out" 2>&1; then fail 'analyzer accepted missing settings'; fi
  if run_hook_powershell_settings "${fixture}" >"${test_temp}/ps-settings-missing.out" 2>&1; then fail 'settings validator accepted missing settings'; fi
  printf '@{ Rules = @{} }\n' >"${fixture}/tools/quality/PSScriptAnalyzerSettings.psd1"
  local analyzer_host
  analyzer_host="$(resolve_powershell_command)" || fail 'actual analyzer host unavailable'
  (
    export PSModulePath="${test_temp}/no-analyzer-module"
    # PowerShell adds default module paths during startup; isolate after startup.
    unavailable_analyzer_host() {
      # PowerShell evaluates the environment variables after startup.
      # shellcheck disable=SC2016
      "${analyzer_host}" -NoProfile -Command '$env:PSModulePath = $env:AUDIT_NO_MODULE_PATH;' "$3"
    }
    resolve_powershell_command() { printf '%s\n' unavailable_analyzer_host; }
    export AUDIT_NO_MODULE_PATH="${PSModulePath}"
    if run_hook_powershell_static "${fixture}" valid.ps1 >"${test_temp}/ps-analyzer-module.out" 2>&1; then fail 'unavailable analyzer passed'; fi
  )
  printf '%s\n' 'PASS: actual PowerShell parsing, analyzer failure propagation and executable host paths'
)

if [[ "${1:-}" == --powershell-host ]]; then
  run_powershell_host_checks
  exit
fi

assert_file_contains() {
  local file_path="$1"
  local expected="$2"

  if ! grep -F -- "${expected}" "${file_path}" >/dev/null; then
    sed 's/^/  /' "${file_path}" >&2
    fail "expected output not found: ${expected}"
  fi
}

run_nested_failure_checks
run_profile_failure_checks

quality_python_cmd=""
for quality_python_candidate in python python3 python.exe; do
  if command -v "${quality_python_candidate}" >/dev/null 2>&1; then
    quality_python_cmd="$(command -v "${quality_python_candidate}")"
    break
  fi
done
if [[ -z "${quality_python_cmd}" ]]; then
  fail "Python is required to validate the quality configuration"
fi

if ! "${quality_python_cmd}" - \
  "${source_root}/tools/quality/pyproject.toml" <<'PYPROJECT_CONTRACT'
import sys
import tomllib
from pathlib import Path

configuration = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
mypy_files = configuration["tool"]["mypy"]["files"]
required_mypy_files = {
    "tools/merge-pull-request.py",
    "tools/quality/install-external-tools.py",
}
missing = sorted(required_mypy_files - set(mypy_files))
if missing:
    raise SystemExit(f"Mypy omits required files: {missing}")
PYPROJECT_CONTRACT
then

  fail "Mypy does not cover every required Python tool"
fi

outside_root="${test_temp}/outside"
mkdir -p "${outside_root}"
help_output="${test_temp}/help.out"
help_error="${test_temp}/help.err"
(
  cd "${outside_root}"
  bash "${dispatcher}" --help >"${help_output}" 2>"${help_error}"
)
if [[ -s "${help_error}" ]]; then
  sed 's/^/  /' "${help_error}" >&2
  fail "help wrote diagnostics to standard error"
fi
assert_file_contains "${help_output}" "Usage: bash tools/repository-audit.sh"
for profile in fast powershell-static \
  hook-pre-commit hook-commit-msg hook-pre-push; do
  assert_file_contains "${help_output}" "${profile}"
done

unknown_output="${test_temp}/unknown.out"
unknown_error="${test_temp}/unknown.err"
if (
  cd "${outside_root}"
  bash "${dispatcher}" unknown >"${unknown_output}" 2>"${unknown_error}"
); then
  fail "unknown mode returned success"
fi
if [[ -s "${unknown_output}" ]]; then
  sed 's/^/  /' "${unknown_output}" >&2
  fail "unknown mode wrote usage to standard output"
fi
assert_file_contains "${unknown_error}" "Usage: bash tools/repository-audit.sh"

source_state="${test_temp}/source-state"
mkdir -p "${source_state}"
(
  set +e
  set +u
  set +o pipefail
  trap ':' EXIT HUP INT TERM ERR RETURN
  cd "${outside_root}"
  set +o >"${source_state}/options.before"
  trap -p EXIT HUP INT TERM ERR RETURN >"${source_state}/traps.before"
  pwd -P >"${source_state}/cwd.before"
  # shellcheck disable=SC1090
  source "${dispatcher}" \
    >"${source_state}/source.out" \
    2>"${source_state}/source.err"
  source_status=$?
  set +o >"${source_state}/options.after"
  trap -p EXIT HUP INT TERM ERR RETURN >"${source_state}/traps.after"
  pwd -P >"${source_state}/cwd.after"

  if ((source_status != 0)); then
    fail "sourcing the dispatcher returned ${source_status}"
  fi
  if [[ -s "${source_state}/source.out" || -s "${source_state}/source.err" ]]; then
    sed 's/^/  /' "${source_state}/source.out" >&2
    sed 's/^/  /' "${source_state}/source.err" >&2
    fail "sourcing the dispatcher emitted output"
  fi
  if ! cmp -s "${source_state}/options.before" "${source_state}/options.after"; then
    diff -u \
      "${source_state}/options.before" \
      "${source_state}/options.after" >&2 || true
    fail "sourcing the dispatcher changed caller shell options"
  fi
  if ! cmp -s "${source_state}/traps.before" "${source_state}/traps.after"; then
    diff -u \
      "${source_state}/traps.before" \
      "${source_state}/traps.after" >&2 || true
    fail "sourcing the dispatcher changed caller traps"
  fi
  if ! cmp -s "${source_state}/cwd.before" "${source_state}/cwd.after"; then
    diff -u \
      "${source_state}/cwd.before" \
      "${source_state}/cwd.after" >&2 || true
    fail "sourcing the dispatcher changed caller working directory"
  fi
)

route_output="${test_temp}/route.out"
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  run_markdown() { printf '%s\n' markdown; }
  run_spelling() { printf '%s\n' spelling; }
  run_static() { printf '%s\n' static; }
  run_powershell_static() { printf '%s\n' powershell-static; }
  run_readonly() { printf '%s\n' readonly; }
  run_project_checks() { printf '%s\n' project-plan; }

  for mode in all full readonly markdown spelling static powershell-static; do
    printf '%s:' "${mode}"
    main "${mode}" | paste -sd, -
  done
) >"${route_output}"
cat >"${test_temp}/route.expected" <<'ROUTES'
all:Core validation scope: source,static,Core validation: passed (all source scope).,project-plan
full:Core validation scope: source,static,Core validation: passed (full source scope).,project-plan
readonly:Core validation scope: source,readonly,Core validation: passed (readonly source scope).,project-plan
markdown:Core validation scope: source,markdown,Core validation: passed (markdown source scope).,project-plan
spelling:Core validation scope: source,spelling,Core validation: passed (spelling source scope).,project-plan
static:Core validation scope: source,static,Core validation: passed (static source scope).,project-plan
powershell-static:Core validation scope: source,powershell-static,Core validation: passed (powershell-static source scope).,project-plan
ROUTES
if ! cmp -s "${test_temp}/route.expected" "${route_output}"; then
  diff -u "${test_temp}/route.expected" "${route_output}" >&2 || true
  fail "legacy mode routing changed"
fi

profile_bin="${test_temp}/profile-bin"
mkdir -p "${profile_bin}"
export QUALITY_PROFILE_REAL_PYTHON="${quality_python_cmd}"
cat >"${profile_bin}/node" <<'PROFILE_NODE'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 || "$1" != "--check" || \
  "$2" != "commitlint.config.cjs" ]]; then
  printf 'Unexpected Node arguments: %s\n' "$*" >&2
  exit 1
fi
printf '%s\n' node-syntax >>"${QUALITY_PROFILE_TRACE}"
PROFILE_NODE
cat >"${profile_bin}/python" <<'PROFILE_PYTHON'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == -B ]]; then
  exec "${QUALITY_PROFILE_REAL_PYTHON}" "$@"
fi

if [[ "$#" -eq 1 && "$1" == "tools/quality/check-versions.py" ]]; then
  printf '%s\n' versions:declarations >>"${QUALITY_PROFILE_TRACE}"
elif [[ "$#" -eq 2 && "$1" == "tools/quality/check-versions.py" && \
  "$2" == "--runtime" ]]; then
  printf '%s\n' versions:runtime >>"${QUALITY_PROFILE_TRACE}"
else
  printf 'Unexpected Python arguments: %s\n' "$*" >&2
  exit 1
fi
PROFILE_PYTHON
cat >"${profile_bin}/ruff" <<'PROFILE_RUFF'
#!/usr/bin/env bash
set -euo pipefail

case "$*" in
"check --config tools/quality/pyproject.toml tools tests")
  printf '%s\n' ruff-check >>"${QUALITY_PROFILE_TRACE}"
  ;;
"format --check --config tools/quality/pyproject.toml tools tests")
  printf '%s\n' ruff-format >>"${QUALITY_PROFILE_TRACE}"
  ;;
*)
  printf 'Unexpected Ruff arguments: %s\n' "$*" >&2
  exit 1
  ;;
esac
PROFILE_RUFF
cat >"${profile_bin}/mypy" <<'PROFILE_MYPY'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$*" != "--config-file tools/quality/pyproject.toml" ]]; then
  printf 'Unexpected Mypy arguments: %s\n' "$*" >&2
  exit 1
fi
printf '%s\n' mypy >>"${QUALITY_PROFILE_TRACE}"
PROFILE_MYPY
chmod +x \
  "${profile_bin}/node" \
  "${profile_bin}/python" \
  "${profile_bin}/ruff" \
  "${profile_bin}/mypy"

runtime_fast_trace="${test_temp}/runtime-fast.trace"
declaration_fast_trace="${test_temp}/declaration-fast.trace"
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  require_command() { :; }
  resolve_command() {
    case "$1" in
    node) printf '%s\n' "${profile_bin}/node" ;;
    python) printf '%s\n' "${profile_bin}/python" ;;
    *) return 1 ;;
    esac
  }
  resolve_hook_command() {
    case "$2" in
    mypy) printf '%s\n' "${profile_bin}/mypy" ;;
    ruff) printf '%s\n' "${profile_bin}/ruff" ;;
    *) return 1 ;;
    esac
  }
  check_git_whitespace() {
    printf '%s\n' whitespace >>"${QUALITY_PROFILE_TRACE}"
  }
  check_powershell_line_endings() {
    if [[ "$1" != "${profile_bin}/node" ]]; then
      fail "fast passed an unexpected Node command to the EOL check"
    fi
    printf '%s\n' powershell-eol >>"${QUALITY_PROFILE_TRACE}"
  }
  run_shell_syntax_checks() {
    printf '%s\n' shell-syntax >>"${QUALITY_PROFILE_TRACE}"
  }

  QUALITY_PROFILE_TRACE="${runtime_fast_trace}" run_fast_checks --runtime
  QUALITY_PROFILE_TRACE="${declaration_fast_trace}" run_fast
)
cat >"${test_temp}/runtime-fast.expected" <<'RUNTIME_FAST'
whitespace
powershell-eol
shell-syntax
node-syntax
versions:runtime
ruff-check
ruff-format
mypy
RUNTIME_FAST
cat >"${test_temp}/declaration-fast.expected" <<'DECLARATION_FAST'
whitespace
powershell-eol
shell-syntax
node-syntax
versions:declarations
ruff-check
ruff-format
mypy
DECLARATION_FAST
if ! cmp -s "${test_temp}/runtime-fast.expected" "${runtime_fast_trace}"; then
  diff -u \
    "${test_temp}/runtime-fast.expected" "${runtime_fast_trace}" >&2 || true
  fail "runtime fast checks changed composition or repeated a guard"
fi
if ! cmp -s \
  "${test_temp}/declaration-fast.expected" \
  "${declaration_fast_trace}"; then
  diff -u \
    "${test_temp}/declaration-fast.expected" \
    "${declaration_fast_trace}" >&2 || true
  fail "fast changed composition or invoked a runtime-only guard"
fi

powershell_static_trace="${test_temp}/powershell-static.trace"
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  run_hook_powershell_static() {
    if [[ "$#" -ne 4 || "$1" != "${source_root}" ||
      "$2" != "tools/build-release-package.ps1" ||
      "$3" != "tools/git-init.ps1" ||
      "$4" != "tools/quality/PSScriptAnalyzerSettings.psd1" ]]; then
      printf 'Unexpected PowerShell static arguments: %s\n' "$*" >&2
      return 1
    fi
    printf '%s\n' powershell-static >>"${powershell_static_trace}"
  }
  run_powershell_static
)
if [[ "$(cat "${powershell_static_trace}")" != "powershell-static" ]]; then
  fail "PowerShell static did not share the hook analyzer exactly once"
fi

shell_behavior_trace="${test_temp}/shell-behavior.trace"
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  bash() {
    printf '%s\n' "$1" >>"${shell_behavior_trace}"
  }
  run_shell_behavior_tests
)
cat >"${test_temp}/shell-behavior.expected" <<'SHELL_BEHAVIOR'
tests/test_repository_audit.sh
tests/test_agent_rules_transfer.sh
tests/test_quality_hooks.sh
tests/test_quality_pre_commit.sh
tests/test_commit_message_validation.sh
tests/test_quality_pre_push.sh
SHELL_BEHAVIOR
if ! cmp -s \
  "${test_temp}/shell-behavior.expected" "${shell_behavior_trace}"; then
  diff -u \
    "${test_temp}/shell-behavior.expected" "${shell_behavior_trace}" \
    >&2 || true
  fail "Shell behavior test entry point changed"
fi

cat >"${profile_bin}/markdownlint-cli2" <<'PROFILE_MARKDOWN'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$*" != '--config .markdownlint-cli2.yaml **/*.md' ]]; then
  printf 'Unexpected Markdown arguments: %s\n' "$*" >&2
  exit 1
fi
printf '%s\n' markdown >>"${QUALITY_PROFILE_TRACE}"
PROFILE_MARKDOWN
cat >"${profile_bin}/codespell" <<'PROFILE_CODESPELL'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$*" != "--config .codespellrc ." ]]; then
  printf 'Unexpected Codespell arguments: %s\n' "$*" >&2
  exit 1
fi
printf '%s\n' spelling >>"${QUALITY_PROFILE_TRACE}"
PROFILE_CODESPELL
cat >"${profile_bin}/yamllint" <<'PROFILE_YAMLLINT'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$*" != "-c tools/quality/yamllint.yaml ." ]]; then
  printf 'Unexpected Yamllint arguments: %s\n' "$*" >&2
  exit 1
fi
printf '%s\n' yamllint >>"${QUALITY_PROFILE_TRACE}"
PROFILE_YAMLLINT
cat >"${profile_bin}/actionlint" <<'PROFILE_ACTIONLINT'
#!/usr/bin/env bash
set -euo pipefail

if (($# != 0)); then
  printf 'Unexpected Actionlint arguments: %s\n' "$*" >&2
  exit 1
fi
printf '%s\n' actionlint >>"${QUALITY_PROFILE_TRACE}"
PROFILE_ACTIONLINT
chmod +x \
  "${profile_bin}/markdownlint-cli2" \
  "${profile_bin}/codespell" \
  "${profile_bin}/yamllint" \
  "${profile_bin}/actionlint"

static_behavior_trace="${test_temp}/static-behavior.trace"
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  require_command() { :; }
  resolve_command() {
    case "$1" in
    actionlint | codespell | node | python)
      printf '%s\n' "${profile_bin}/$1"
      ;;
    shellcheck | shfmt)
      printf '%s\n' "${profile_bin}/$1"
      ;;
    *) return 1 ;;
    esac
  }
  resolve_hook_command() {
    case "$2" in
    mypy | ruff | yamllint) printf '%s\n' "${profile_bin}/$2" ;;
    *) return 1 ;;
    esac
  }
  resolve_hook_node_tool() {
    if [[ "$1" != "markdownlint-cli2" ]]; then
      return 1
    fi
    printf '%s\n' "${profile_bin}/markdownlint-cli2"
  }
  check_git_whitespace() {
    printf '%s\n' whitespace >>"${QUALITY_PROFILE_TRACE}"
  }
  check_powershell_line_endings() {
    printf '%s\n' powershell-eol >>"${QUALITY_PROFILE_TRACE}"
  }
  run_shell_syntax_checks() {
    printf '%s\n' shell-syntax >>"${QUALITY_PROFILE_TRACE}"
  }
  run_shellcheck_checks() {
    printf '%s\n' shellcheck >>"${QUALITY_PROFILE_TRACE}"
  }
  run_shfmt_checks() {
    printf '%s\n' shfmt >>"${QUALITY_PROFILE_TRACE}"
  }
  run_hook_powershell_static() {
    printf '%s\n' powershell-static >>"${QUALITY_PROFILE_TRACE}"
  }
  check_semver_pattern_drift() {
    printf '%s\n' semver-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  check_initializer_commit_contract() {
    printf '%s\n' initializer-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  check_commit_documentation_contract() {
    printf '%s\n' commit-documentation-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  check_secret_scanner_config_contract() {
    printf '%s\n' secret-config-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  run_full_secret_scan() {
    printf '%s\n' full-history-secret-scan >>"${QUALITY_PROFILE_TRACE}"
  }
  check_agent_rules_update_workflow_contract() {
    printf '%s\n' agent-rules-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  check_repository_audit_workflow_contract() {
    printf '%s\n' repository-audit-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  check_guarded_pull_request_merge_workflow_contract() {
    printf '%s\n' guarded-merge-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  check_release_artifact_contract() {
    printf '%s\n' release-artifact-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  check_release_skill_contract() {
    printf '%s\n' release-skill-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  check_release_package_portability() {
    printf '%s\n' release-package-portability >>"${QUALITY_PROFILE_TRACE}"
  }
  check_release_guard_contract() {
    printf '%s\n' release-guard-contract >>"${QUALITY_PROFILE_TRACE}"
  }
  run_python_coverage() {
    printf '%s\n' coverage >>"${QUALITY_PROFILE_TRACE}"
  }
  run_powershell_parse() {
    printf '%s\n' powershell-parse >>"${QUALITY_PROFILE_TRACE}"
  }
  run_shell_behavior_tests() {
    printf '%s\n' shell-behavior >>"${QUALITY_PROFILE_TRACE}"
  }
  run_script_smoke() {
    printf '%s\n' smoke >>"${QUALITY_PROFILE_TRACE}"
  }
  run_commitlint() {
    printf '%s\n' commitlint >>"${QUALITY_PROFILE_TRACE}"
  }

  cd "${source_root}"
  export QUALITY_PROFILE_TRACE="${static_behavior_trace}"
  run_static
  export QUALITY_PROFILE_TRACE="${static_behavior_trace}.failure"
  run_full_secret_scan() { return 43; }
  scan_status=0
  run_static || scan_status=$?
  ((scan_status == 43)) || fail 'static swallowed mandatory secret scanner failure'
  if grep -Fx coverage "${QUALITY_PROFILE_TRACE}" >/dev/null; then
    fail 'static continued after secret scanner failure'
  fi
)
cat >"${test_temp}/static-behavior.expected" <<'STATIC_BEHAVIOR'
whitespace
powershell-eol
shell-syntax
node-syntax
versions:runtime
ruff-check
ruff-format
mypy
markdown
spelling
yamllint
actionlint
powershell-static
shellcheck
shfmt
semver-contract
initializer-contract
commit-documentation-contract
secret-config-contract
full-history-secret-scan
agent-rules-contract
repository-audit-contract
guarded-merge-contract
release-artifact-contract
release-skill-contract
release-package-portability
release-guard-contract
coverage
shell-behavior
smoke
commitlint
STATIC_BEHAVIOR
if ! cmp -s \
  "${test_temp}/static-behavior.expected" "${static_behavior_trace}"; then
  diff -u \
    "${test_temp}/static-behavior.expected" \
    "${static_behavior_trace}" >&2 || true
  fail "static changed composition or repeated a quality guard"
fi

coverage_bin="${test_temp}/coverage-bin"
coverage_trace="${test_temp}/coverage.trace"
coverage_data="${test_temp}/coverage-data"
mkdir -p "${coverage_bin}" "${coverage_data}"
cat >"${coverage_bin}/coverage" <<'COVERAGE'
#!/usr/bin/env bash
set -euo pipefail

printf '%s|%s\n' "${COVERAGE_FILE}" "$*" >>"${QUALITY_COVERAGE_TRACE}"
if [[ "$1" == json ]]; then
  printf '%s\n' '{"meta":{"branch_coverage":true},"totals":{"num_statements":100,"covered_lines":100,"num_branches":20,"covered_branches":20}}' >"${COVERAGE_FILE%/.coverage}/coverage.json"
fi
if [[ "$1" == run ]]; then
  exit "${QUALITY_COVERAGE_RUN_STATUS:-0}"
fi
COVERAGE
chmod +x "${coverage_bin}/coverage"
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  # Read by run_python_coverage from the sourced dispatcher.
  # shellcheck disable=SC2034
  audit_temp="${coverage_data}"
  cd "${repository_root}"
  PATH="${coverage_bin}:${PATH}" \
    QUALITY_COVERAGE_TRACE="${coverage_trace}" \
    run_python_coverage
)
assert_file_contains "${coverage_trace}" \
  "${coverage_data}/.coverage|run --rcfile=tools/quality/pyproject.toml"
assert_file_contains "${coverage_trace}" \
  "${coverage_data}/.coverage|report --rcfile=tools/quality/pyproject.toml"
assert_file_contains "${coverage_trace}" \
  "${coverage_data}/.coverage|json --rcfile=tools/quality/pyproject.toml --fail-under=0"

coverage_failure_trace="${test_temp}/coverage-failure.trace"
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  # Read by run_python_coverage from the sourced dispatcher.
  # shellcheck disable=SC2034
  audit_temp="${coverage_data}"
  cd "${repository_root}"
  if PATH="${coverage_bin}:${PATH}" \
    QUALITY_COVERAGE_TRACE="${coverage_failure_trace}" \
    QUALITY_COVERAGE_RUN_STATUS=7 run_python_coverage; then
    fail "coverage reports masked a failing Python suite in a conditional call"
  else
    coverage_status=$?
  fi
  if ((coverage_status != 7)); then
    fail "coverage returned ${coverage_status}, expected the suite status 7"
  fi
)
assert_file_contains "${coverage_failure_trace}" \
  "${coverage_data}/.coverage|report --rcfile=tools/quality/pyproject.toml"
assert_file_contains "${coverage_failure_trace}" \
  "${coverage_data}/.coverage|json --rcfile=tools/quality/pyproject.toml --fail-under=0"

smoke_python="${test_temp}/smoke-python"
cat >"${smoke_python}" <<'SMOKE_PYTHON'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -eq 2 && "$1" == "-c" && \
  "$2" == "from jsonschema import Draft202012Validator, FormatChecker" ]]; then
  printf '%s\n' dependency-probe >>"${QUALITY_SMOKE_TRACE}"
  exit "${QUALITY_SMOKE_IMPORT_STATUS:-0}"
fi
if [[ "$#" -ge 3 && "$1" == "-m" && "$2" == "pip" && \
  "$3" == "install" ]]; then
  printf '%s\n' pip-install >>"${QUALITY_SMOKE_TRACE}"
  exit 97
fi
if [[ "$#" -ge 3 && "$1" == "-B" && "$2" == "-m" && \
  "$3" == "unittest" ]]; then
  printf '%s\n' unittest-discover >>"${QUALITY_SMOKE_TRACE}"
  exit 98
fi
printf 'python:%s\n' "$*" >>"${QUALITY_SMOKE_TRACE}"
exit 99
SMOKE_PYTHON
chmod +x "${smoke_python}"

run_bounded_smoke_setup() {
  local import_status="$1"
  local trace_path="$2"
  local output_path="$3"
  local error_path="$4"

  # The isolated Bash expands variables inside its single-quoted script.
  # shellcheck disable=SC2016
  BASH_ENV='' QUALITY_SMOKE_IMPORT_STATUS="${import_status}" \
    QUALITY_SMOKE_TRACE="${trace_path}" \
    "${BASH}" --noprofile --norc -euo pipefail -c '
      dispatcher="$1"
      repository_root_argument="$2"
      audit_temp_argument="$3"
      smoke_python_argument="$4"
      # shellcheck disable=SC1090
      source "${dispatcher}"
      repository_root="${repository_root_argument}"
      audit_temp="${audit_temp_argument}"
      smoke_python="${smoke_python_argument}"
      require_command() { :; }
      resolve_command() {
        if [[ "$1" == "python" ]]; then
          printf "%s\n" "${smoke_python}"
        else
          printf "%s\n" /usr/bin/true
        fi
      }
      resolve_hook_node_tool() { printf "%s\n" /usr/bin/true; }
      resolve_powershell_command() { printf "%s\n" /usr/bin/true; }
      ensure_audit_temp() {
        printf "%s\n" fixture-created >>"${QUALITY_SMOKE_TRACE}"
      }
      run_script_smoke
    ' repository-audit-smoke \
    "${dispatcher}" \
    "${source_root}" \
    "${test_temp}/smoke-fixture" \
    "${smoke_python}" \
    >"${output_path}" 2>"${error_path}"
}

mkdir -p "${test_temp}/smoke-fixture"
smoke_setup_trace="${test_temp}/smoke-setup.trace"
if run_bounded_smoke_setup \
  0 \
  "${smoke_setup_trace}" \
  "${test_temp}/smoke-setup.out" \
  "${test_temp}/smoke-setup.err"; then
  fail "smoke setup unexpectedly completed every CLI check"
else
  smoke_setup_status=$?
fi
if ((smoke_setup_status != 99)); then
  sed 's/^/  /' "${test_temp}/smoke-setup.err" >&2
  fail "smoke setup returned ${smoke_setup_status} instead of first-CLI status 99"
fi
cat >"${test_temp}/smoke-setup.expected" <<'SMOKE_SETUP'
dependency-probe
fixture-created
python:tools/starter-kit-manifest.py --help
SMOKE_SETUP
if ! cmp -s "${test_temp}/smoke-setup.expected" "${smoke_setup_trace}"; then
  diff -u \
    "${test_temp}/smoke-setup.expected" "${smoke_setup_trace}" >&2 || true
  fail "smoke setup installed dependencies or repeated the Python suite"
fi

missing_smoke_trace="${test_temp}/smoke-missing.trace"
if run_bounded_smoke_setup \
  42 \
  "${missing_smoke_trace}" \
  "${test_temp}/smoke-missing.out" \
  "${test_temp}/smoke-missing.err"; then
  fail "smoke accepted missing locked Python dependencies"
else
  missing_smoke_status=$?
fi
if ((missing_smoke_status != 1)); then
  sed 's/^/  /' "${test_temp}/smoke-missing.err" >&2
  fail "missing smoke dependencies returned ${missing_smoke_status} instead of 1"
fi
if [[ "$(cat "${missing_smoke_trace}")" != "dependency-probe" ]]; then
  fail "smoke created fixtures after its dependency probe failed"
fi
assert_file_contains "${test_temp}/smoke-missing.err" \
  "Repository audit smoke requires locked Python quality dependencies."
assert_file_contains "${test_temp}/smoke-missing.err" \
  "python -m pip install --disable-pip-version-check --no-input --require-hashes --requirement tools/quality/requirements.lock"

# BEGIN RELEASE WORKFLOW TESTS
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  check_semver_pattern_drift "$(resolve_command node node.exe)"
  check_release_artifact_contract
)

replace_literal() {
  local source_path="$1"
  local destination_path="$2"
  local old_text="$3"
  local new_text="$4"
  local expected_count="${5:-1}"

  "${quality_python_cmd}" - \
    "${source_path}" "${destination_path}" "${old_text}" "${new_text}" \
    "${expected_count}" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
old = sys.argv[3]
expected_count = int(sys.argv[5])
if source.count(old) != expected_count:
    raise SystemExit(f"expected {expected_count} occurrences of {old!r}")
Path(sys.argv[2]).write_bytes(source.replace(old, sys.argv[4]).encode("utf-8"))
PY
}

extract_workflow_run_script() {
  local workflow_path="$1"
  local step_id="$2"
  local output_path="$3"

  "${quality_python_cmd}" - \
    "${workflow_path}" "${step_id}" "${output_path}" <<'PY'
import re
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
step_id = sys.argv[2]
id_pattern = re.compile(rf"^(\s*)id:\s*{re.escape(step_id)}\s*$")
for index, line in enumerate(lines):
    match = id_pattern.match(line)
    if match is None:
        continue
    step_indent = len(match.group(1))
    for run_index in range(index + 1, len(lines)):
        run_match = re.match(r"^(\s*)run:\s*\|\s*$", lines[run_index])
        if run_match is None:
            if lines[run_index].strip() and len(lines[run_index]) - len(
                lines[run_index].lstrip()
            ) < step_indent:
                break
            continue
        run_indent = len(run_match.group(1))
        body = []
        for body_line in lines[run_index + 1 :]:
            if body_line.strip():
                indent = len(body_line) - len(body_line.lstrip())
                if indent <= run_indent:
                    break
                body.append(body_line[run_indent + 2 :])
            else:
                body.append("")
        Path(sys.argv[3]).write_bytes(("\n".join(body) + "\n").encode("utf-8"))
        raise SystemExit(0)
raise SystemExit(f"workflow step id {step_id!r} with a literal run block is missing")
PY
}

release_package_workflow="${source_root}/.github/workflows/release-package.yml"
if ! (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  check_release_package_portability "${release_package_workflow}"
) >"${test_temp}/release-package-valid.out" \
  2>"${test_temp}/release-package-valid.err"; then
  sed 's/^/  /' "${test_temp}/release-package-valid.err" >&2
  fail "Release package contract rejected the repository workflow"
fi

release_script_root="${test_temp}/release-package-scripts"
mkdir -p "${release_script_root}"
seal_script="${release_script_root}/seal.sh"
verify_script="${release_script_root}/verify.sh"
publish_script="${release_script_root}/publish.sh"
extract_workflow_run_script "${release_package_workflow}" seal "${seal_script}"
extract_workflow_run_script "${release_package_workflow}" verify "${verify_script}"
extract_workflow_run_script "${release_package_workflow}" publish "${publish_script}"

release_tag='v1.2.3-rc.1+build.5'
package_name="git-starter-kit-${release_tag}-with-agent-rules.zip"
toolkit_name="git-starter-kit-${release_tag}-upgrade-toolkit.zip"
release_payload_source="${test_temp}/release-package-source"
release_transfer_root="${test_temp}/release-package-transfer"
release_expected_sums="${test_temp}/release-package-expected-sha256s"
release_outputs="${test_temp}/release-package-outputs"
mkdir -p "${release_payload_source}"
printf '%s\n' 'composed package payload' >"${release_payload_source}/${package_name}"
printf '%s\n' 'upgrade toolkit payload' >"${release_payload_source}/${toolkit_name}"
: >"${release_outputs}"

PACKAGE_PATH="${release_payload_source}/${package_name}" \
  TOOLKIT_PATH="${release_payload_source}/${toolkit_name}" \
  RELEASE_TAG="${release_tag}" \
  TRANSFER_ROOT="${release_transfer_root}" \
  EXPECTED_SUMS_PATH="${release_expected_sums}" \
  GITHUB_OUTPUT="${release_outputs}" \
  bash "${seal_script}"

for release_output in package_name toolkit_name package_sha256 toolkit_sha256; do
  assert_file_contains "${release_outputs}" "${release_output}="
done
if [[ ! -f "${release_transfer_root}/${package_name}" || ! -f "${release_transfer_root}/${toolkit_name}" || ! -f "${release_transfer_root}/SHA256SUMS" ]]; then
  fail "Release package sealing did not preserve the exact SemVer-derived names"
fi

package_sha256="$(sha256sum "${release_transfer_root}/${package_name}" | cut -d' ' -f1)"
toolkit_sha256="$(sha256sum "${release_transfer_root}/${toolkit_name}" | cut -d' ' -f1)"

release_stub_bin="${test_temp}/release-package-bin"
release_gh_log="${test_temp}/release-package-gh.jsonl"
mkdir -p "${release_stub_bin}"
apply_stub_path="${release_stub_bin}/gh"
cat >"${apply_stub_path}" <<'GH_STUB'
#!/usr/bin/env bash
set -euo pipefail

"${QUALITY_PYTHON}" - "${GH_CALL_LOG}" "$@" <<'PY'
import json
import sys
from pathlib import Path

with Path(sys.argv[1]).open("a", encoding="utf-8", newline="\n") as stream:
    stream.write(json.dumps(sys.argv[2:]) + "\n")
PY
GH_STUB
chmod +x "${apply_stub_path}"

run_release_verification() {
  local payload_root="$1"
  local expected_path="$2"

  TRANSFER_ROOT="${payload_root}" \
    EXPECTED_PACKAGE_NAME="${package_name}" \
    EXPECTED_TOOLKIT_NAME="${toolkit_name}" \
    EXPECTED_PACKAGE_SHA256="${package_sha256}" \
    EXPECTED_TOOLKIT_SHA256="${toolkit_sha256}" \
    EXPECTED_SUMS_PATH="${expected_path}" \
    bash "${verify_script}"
}

run_release_publication() {
  local payload_root="$1"
  local event_name="$2"
  local prerelease="$3"

  PATH="${release_stub_bin}:${PATH}" \
    QUALITY_PYTHON="${quality_python_cmd}" \
    GH_CALL_LOG="${release_gh_log}" \
    GH_TOKEN=CHANGE_ME \
    GH_REPO='asphyx0r/git-starter-kit' \
    RELEASE_TAG="${release_tag}" \
    EVENT_NAME="${event_name}" \
    PRERELEASE="${prerelease}" \
    TRANSFER_ROOT="${payload_root}" \
    PACKAGE_NAME="${package_name}" \
    TOOLKIT_NAME="${toolkit_name}" \
    bash "${publish_script}"
}

assert_invalid_release_payload() {
  local case_name="$1"
  local payload_root="$2"
  local expected_path="${test_temp}/${case_name}-expected-sha256s"

  : >"${release_gh_log}"
  if (
    cd "${outside_root}"
    run_release_verification "${payload_root}" "${expected_path}" &&
      run_release_publication "${payload_root}" workflow_dispatch false
  ) >"${test_temp}/${case_name}.out" 2>"${test_temp}/${case_name}.err"; then
    fail "Release publication accepted invalid payload: ${case_name}"
  fi
  if [[ -s "${release_gh_log}" ]]; then
    fail "Release publication invoked gh for invalid payload: ${case_name}"
  fi
}

make_release_payload_copy() {
  local destination="$1"

  rm -rf -- "${destination}"
  mkdir -p "${destination}"
  cp "${release_transfer_root}/${package_name}" "${destination}/${package_name}"
  cp "${release_transfer_root}/${toolkit_name}" "${destination}/${toolkit_name}"
  cp "${release_transfer_root}/SHA256SUMS" "${destination}/SHA256SUMS"
}

invalid_payload_root="${test_temp}/release-package-invalid"
make_release_payload_copy "${invalid_payload_root}"
printf '%s\n' 'tampered' >>"${invalid_payload_root}/${package_name}"
assert_invalid_release_payload package-tampered "${invalid_payload_root}"

make_release_payload_copy "${invalid_payload_root}"
printf '%s\n' 'tampered' >>"${invalid_payload_root}/${toolkit_name}"
assert_invalid_release_payload toolkit-tampered "${invalid_payload_root}"

make_release_payload_copy "${invalid_payload_root}"
printf '%s\n' 'tampered checksums' >"${invalid_payload_root}/SHA256SUMS"
assert_invalid_release_payload sums-tampered "${invalid_payload_root}"

make_release_payload_copy "${invalid_payload_root}"
printf '%s\n' 'unexpected' >"${invalid_payload_root}/unexpected.txt"
assert_invalid_release_payload extra-file "${invalid_payload_root}"

make_release_payload_copy "${invalid_payload_root}"
mkdir "${invalid_payload_root}/nested"
printf '%s\n' 'unexpected' >"${invalid_payload_root}/nested/unexpected.txt"
assert_invalid_release_payload extra-directory "${invalid_payload_root}"

make_release_payload_copy "${invalid_payload_root}"
rm "${invalid_payload_root}/${package_name}"
if ln -s "${release_transfer_root}/${package_name}" \
  "${invalid_payload_root}/${package_name}" 2>/dev/null &&
  [[ -L "${invalid_payload_root}/${package_name}" ]]; then
  assert_invalid_release_payload symlink "${invalid_payload_root}"
fi

make_release_payload_copy "${invalid_payload_root}"
rm "${invalid_payload_root}/${package_name}"
if mkfifo "${invalid_payload_root}/${package_name}" 2>/dev/null &&
  [[ -p "${invalid_payload_root}/${package_name}" ]]; then
  assert_invalid_release_payload fifo "${invalid_payload_root}"
fi

: >"${release_gh_log}"
(
  cd "${outside_root}"
  run_release_verification \
    "${release_transfer_root}" "${test_temp}/valid-manual-expected-sha256s"
  run_release_publication "${release_transfer_root}" workflow_dispatch false
)
"${quality_python_cmd}" - \
  "${release_gh_log}" "${release_tag}" "${release_transfer_root}" \
  "${package_name}" "${toolkit_name}" <<'PY'
import json
import sys
from pathlib import Path

calls = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
root = sys.argv[3].replace("\\", "/").rstrip("/")
expected = [[
    "release", "upload", sys.argv[2],
    f"{root}/{sys.argv[4]}",
    f"{root}/{sys.argv[5]}",
    f"{root}/SHA256SUMS",
    "--repo", "asphyx0r/git-starter-kit",
]]
if calls != expected:
    raise SystemExit(f"unexpected manual publication calls: {calls!r}")
PY

: >"${release_gh_log}"
(
  cd "${outside_root}"
  run_release_verification \
    "${release_transfer_root}" "${test_temp}/valid-stable-expected-sha256s"
  run_release_publication "${release_transfer_root}" release false
)
"${quality_python_cmd}" - \
  "${release_gh_log}" "${release_tag}" "${release_transfer_root}" \
  "${package_name}" "${toolkit_name}" <<'PY'
import json
import sys
from pathlib import Path

calls = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
root = sys.argv[3].replace("\\", "/").rstrip("/")
expected = [[
    "release", "upload", sys.argv[2],
    f"{root}/{sys.argv[4]}",
    f"{root}/{sys.argv[5]}",
    f"{root}/SHA256SUMS",
    "--repo", "asphyx0r/git-starter-kit",
]]
if calls != expected:
    raise SystemExit(f"unexpected stable publication calls: {calls!r}")
PY

: >"${release_gh_log}"
(
  cd "${outside_root}"
  run_release_verification \
    "${release_transfer_root}" "${test_temp}/valid-release-expected-sha256s"
  run_release_publication "${release_transfer_root}" release true
)
"${quality_python_cmd}" - \
  "${release_gh_log}" "${release_tag}" "${release_transfer_root}" \
  "${package_name}" "${toolkit_name}" <<'PY'
import json
import sys
from pathlib import Path

calls = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
root = sys.argv[3].replace("\\", "/").rstrip("/")
expected = [
    [
        "release", "upload", sys.argv[2],
        f"{root}/{sys.argv[4]}",
        f"{root}/{sys.argv[5]}",
        f"{root}/SHA256SUMS",
        "--repo", "asphyx0r/git-starter-kit",
    ],
    [
        "release", "edit", sys.argv[2],
        "--repo", "asphyx0r/git-starter-kit",
        "--prerelease=false", "--latest",
    ],
]
if calls != expected:
    raise SystemExit(f"unexpected release publication calls: {calls!r}")
PY
# END RELEASE WORKFLOW TESTS

# BEGIN REPOSITORY AUDIT WORKFLOW TESTS
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  check_repository_audit_workflow_contract
)
# END REPOSITORY AUDIT WORKFLOW TESTS

# BEGIN RELEASE SKILL GUARD TESTS
# shellcheck disable=SC1090
source "${dispatcher}"

if [ -f "${source_root}/.github/workflows/release-package.yml" ]; then
  release_skill_fixture_root="${test_temp}/release-skill-guard"
  release_skill_reference_dir=".agents/skills/git-commit-push-tag/references"
  mkdir -p "${release_skill_fixture_root}/${release_skill_reference_dir}"

  assert_release_skill_guard_mutation() {
    local case_name="$1"
    local reference_name="$2"
    local old_text="$3"
    local new_text="$4"
    local expected_diagnostic="$5"
    local expected_count="${6:-1}"
    local actual_status

    cp "${source_root}/${release_skill_reference_dir}/"*.txt \
      "${release_skill_fixture_root}/${release_skill_reference_dir}/"
    replace_literal \
      "${source_root}/${release_skill_reference_dir}/${reference_name}" \
      "${release_skill_fixture_root}/${release_skill_reference_dir}/${reference_name}" \
      "${old_text}" "${new_text}" "${expected_count}"
    if (
      cd "${release_skill_fixture_root}"
      check_release_guard_contract
    ) >"${test_temp}/skill-${case_name}.out" \
      2>"${test_temp}/skill-${case_name}.err"; then
      fail "Release guard accepted ${case_name}"
    else
      actual_status=$?
    fi
    if ((actual_status != 1)); then
      fail "Release guard returned unexpected status for ${case_name}"
    fi
    assert_file_contains "${test_temp}/skill-${case_name}.err" \
      "${expected_diagnostic}"
  }

  release_main_reference="git-commit-push-tag.txt"
  release_package_reference="git-starter-kit-release-package.txt"
  release_branch_diagnostic='Release guard omits protected-branch integration gates.'
  release_payload_diagnostic='Release guard omits the sealed publication boundary.'
  release_activation_diagnostic='Universal release guard omits common provisioning or completion gates.'
  # codespell:ignore-next-line branche
  release_trusted_activation_phrase='snapshot immuable de la branche par défaut'
  # codespell:ignore-next-line branche
  release_untrusted_activation_phrase='snapshot immuable de la branche cible'
  # codespell:ignore-next-line branche
  release_target_tag_audit_phrase='Exige sans condition que le workflow audite les pushes de la branche cible et du tag prévu.'
  assert_file_contains "${source_root}/${release_skill_reference_dir}/${release_main_reference}" \
    "${release_trusted_activation_phrase}"
  assert_file_contains "${source_root}/${release_skill_reference_dir}/${release_main_reference}" \
    "${release_target_tag_audit_phrase}"
  # shellcheck disable=SC2016
  assert_release_skill_guard_mutation \
    missing-trusted-activation "${release_main_reference}" \
    "${release_trusted_activation_phrase}" "${release_untrusted_activation_phrase}" \
    "${release_activation_diagnostic}"
  # shellcheck disable=SC2016
  assert_release_skill_guard_mutation \
    missing-target-release-authority "${release_main_reference}" \
    'snapshot immuable de la cible pour `releaseKind`' 'Use default-branch release metadata' \
    "${release_activation_diagnostic}"
  assert_release_skill_guard_mutation \
    target-flags-activation "${release_main_reference}" \
    'Les flags de la cible ne sélectionnent aucun automatisme.' 'Use target flags for automation.' \
    "${release_activation_diagnostic}"
  assert_release_skill_guard_mutation \
    stale-release-authorities "${release_main_reference}" \
    'validation avant chaque opération dépendante' 'validation only at the beginning' \
    "${release_activation_diagnostic}"
  assert_release_skill_guard_mutation \
    conditional-target-tag-audit "${release_main_reference}" \
    "${release_target_tag_audit_phrase}" \
    'When preflight is enabled, require target/tag push audits.' \
    "${release_activation_diagnostic}"
  # shellcheck disable=SC2016
  assert_release_skill_guard_mutation \
    forced-guarded-automation "${release_main_reference}" \
    'Lorsque `guardedMerge=false`' 'Always require App credentials' \
    "${release_activation_diagnostic}" 2
  # shellcheck disable=SC2016
  assert_release_skill_guard_mutation \
    forced-preflight-automation "${release_main_reference}" \
    'Lorsque `releasePreflight=false`' 'Always dispatch preflight' \
    "${release_activation_diagnostic}"
  # shellcheck disable=SC2016
  assert_release_skill_guard_mutation \
    forced-deployment-metadata "${release_main_reference}" \
    'Pour `releaseKind=repository`' 'Always require deployment metadata' \
    "${release_activation_diagnostic}" 2
  assert_release_skill_guard_mutation \
    missing-repository-dry-run-kind "${release_main_reference}" \
    '--dry-run prepare --kind repository' '--dry-run prepare' \
    "${release_activation_diagnostic}"
  assert_release_skill_guard_mutation \
    missing-repository-apply-kind "${release_main_reference}" \
    '--force prepare --kind repository' '--force prepare' \
    "${release_activation_diagnostic}"
  assert_release_skill_guard_mutation \
    multi-commit-pr "${release_main_reference}" \
    'Limite chaque PR à un commit candidat' \
    'Allow multiple candidate commits in each PR' "${release_branch_diagnostic}"
  assert_release_skill_guard_mutation \
    rebuilt-merge-message "${release_main_reference}" \
    '--message-file <même-fichier-temporaire>' \
    '--message-file <rebuilt-message>' "${release_branch_diagnostic}" 2
  assert_release_skill_guard_mutation \
    missing-target-audit "${release_main_reference}" \
    'au SHA exact du squash et après cet horodatage' \
    'at any previously successful commit' "${release_branch_diagnostic}"
  assert_release_skill_guard_mutation \
    premature-changelog "${release_main_reference}" \
    'contrôles du changelog seulement après sa préparation pour la release' \
    'Always validate the changelog before it is prepared' \
    "${release_branch_diagnostic}"
  assert_release_skill_guard_mutation \
    shared-direct-write "${release_main_reference}" \
    "et non partagée lorsque les instructions du repository l'autorisent." \
    'including protected or shared targets.' "${release_branch_diagnostic}"
  assert_release_skill_guard_mutation \
    mutable-target "${release_main_reference}" \
    'branche cible de release immuable' 'branche courante variable' \
    "${release_branch_diagnostic}"
  assert_release_skill_guard_mutation \
    unchecked-merge "${release_main_reference}" \
    'python tools/merge-pull-request.py request --force' \
    'gh pr merge --squash' "${release_branch_diagnostic}"
  assert_release_skill_guard_mutation \
    missing-merged-tree-check "${release_main_reference}" \
    'revalide les artefacts contre le véritable arbre fusionné' \
    'reuse task-branch artifacts' \
    "${release_branch_diagnostic}"
  # shellcheck disable=SC2016
  assert_release_skill_guard_mutation \
    missing-preflight-trigger "${release_main_reference}" \
    'la couverture effective de `push` inclut `codex/release-preflight-*`' \
    'le workflow écoute seulement les pushes de master' \
    "${release_branch_diagnostic}"
  assert_release_skill_guard_mutation \
    two-assets "${release_package_reference}" \
    'contient exactement trois assets nommés' \
    'contient exactement deux assets nommés' \
    'Release guard does not require all three release assets.'
  assert_release_skill_guard_mutation \
    missing-checksum-validation "${release_package_reference}" \
    'octet pour octet les deux lignes attendues' \
    'uniquement la présence du fichier' "${release_payload_diagnostic}"
  # shellcheck disable=SC2016
  assert_release_skill_guard_mutation \
    writable-build "${release_package_reference}" \
    'un job `build` limité à `contents: read`' \
    'un job `build` avec `contents: write`' "${release_payload_diagnostic}"
  # shellcheck disable=SC2016
  assert_release_skill_guard_mutation \
    overwrite-assets "${release_package_reference}" \
    'sans `--clobber`' 'avec `--clobber`' "${release_payload_diagnostic}"
fi
# END RELEASE SKILL GUARD TESTS

fast_missing_error="${test_temp}/fast-missing.err"
if (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  require_command() { :; }
  resolve_command() { printf '%s\n' /bin/true; }
  PATH="${test_temp}/empty-path" run_fast
) >"${test_temp}/fast-missing.out" 2>"${fast_missing_error}"; then
  fail "fast accepted missing locked Python quality dependencies"
fi
assert_file_contains "${fast_missing_error}" \
  "python -m pip install --require-hashes --requirement tools/quality/requirements.lock"

(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  check_agent_rules_update_workflow_contract
)

external_case="${test_temp}/agent-rules-external"
external_run="${external_case}/external-run.sh"
external_stub_bin="${external_case}/bin"
external_runner="${external_case}/runner"
external_target="${external_case}/target"
mkdir -p \
  "${external_stub_bin}" \
  "${external_runner}/agent-rules-source/tools" \
  "${external_target}"
awk '
  $0 == "      - name: Run external synchronization without credentials" {
    step = 1
    next
  }
  step && $0 == "        run: |" {
    run = 1
    next
  }
  run && $0 ~ /^      - name:/ { exit }
  run {
    sub(/^          /, "")
    print
  }
' "${source_root}/.github/workflows/agent-rules-update.yml" \
  >"${external_run}"
if ! grep -F -- 'env -i' "${external_run}" >/dev/null; then
  fail "external synchronization block extraction failed"
fi
cat >"${external_stub_bin}/python" <<'PYTHON_STUB'
#!/usr/bin/env bash
set -euo pipefail

case_root="${0%/bin/python}"
expected_script="${case_root}/runner/agent-rules-source/tools/agent-rules-sync.py"
expected_source="${case_root}/runner/agent-rules-source"
expected_home="${case_root}/runner/agent-rules-external/home"
expected_tmpdir="${case_root}/runner/agent-rules-external/tmp"
expected_backup="${case_root}/runner/agent-rules-external/backup"
expected_path="${case_root}/bin:/usr/bin:/bin"
for forbidden in \
  GH_TOKEN \
  GITHUB_OUTPUT \
  GITHUB_ENV \
  GITHUB_PATH \
  GITHUB_STATE; do
  if [[ -v "${forbidden}" ]]; then
    printf 'Forbidden variable reached external code: %s\n' \
      "${forbidden}" >&2
    exit 91
  fi
done
if [[ "${HOME:-}" != "${expected_home}" ]]; then
  printf 'External HOME was not isolated: %s\n' "${HOME:-missing}" >&2
  exit 92
fi
if [[ "${PATH:-}" != "${expected_path}" || \
  "${TMPDIR:-}" != "${expected_tmpdir}" || \
  "${PYTHONNOUSERSITE:-}" != 1 || \
  "${LANG:-}" != C.UTF-8 || "${LC_ALL:-}" != C.UTF-8 ]]; then
  printf 'External environment changed.\n' >&2
  exit 93
fi
command_name="${2:-}"
actual_arguments=("$@")
case "${command_name}" in
plan | check)
  expected_arguments=(
    "${expected_script}" "${command_name}"
    --source "${expected_source}"
    --target .
  )
  ;;
apply)
  expected_arguments=(
    "${expected_script}" apply
    --source "${expected_source}"
    --target .
    --backup-directory "${expected_backup}"
  )
  ;;
*) exit 94 ;;
esac
if (($# != ${#expected_arguments[@]})); then
  printf 'External argv count changed for %s.\n' "${command_name}" >&2
  exit 95
fi
for index in "${!expected_arguments[@]}"; do
  if [[ "${actual_arguments[index]}" != \
    "${expected_arguments[index]}" ]]; then
    printf 'External argv changed for %s at %s.\n' \
      "${command_name}" "${index}" >&2
    exit 96
  fi
done
printf '%s\n' "${command_name}" >>"${case_root}/external.trace"
if [[ "${command_name}" == plan ]]; then
  printf '%s\n' '{"actions":[]}'
fi
PYTHON_STUB
chmod +x "${external_stub_bin}/python"
printf '%s\n' '# external sync fixture' \
  >"${external_runner}/agent-rules-source/tools/agent-rules-sync.py"
(
  cd "${external_target}"
  PATH="${external_stub_bin}:${PATH}" \
    RUNNER_TEMP="${external_runner}" \
    GH_TOKEN=CHANGE_ME \
    GITHUB_OUTPUT="${external_case}/real-output" \
    GITHUB_ENV="${external_case}/real-env" \
    GITHUB_PATH="${external_case}/real-path" \
    GITHUB_STATE="${external_case}/real-state" \
    HOME="${external_case}/real-home" \
    timeout --kill-after=5s 30s bash "${external_run}"
)
cat >"${external_case}/external.expected" <<'EXTERNAL_EXPECTED'
plan
apply
check
EXTERNAL_EXPECTED
if ! cmp -s \
  "${external_case}/external.expected" \
  "${external_case}/external.trace"; then
  diff -u \
    "${external_case}/external.expected" \
    "${external_case}/external.trace" >&2 || true
  fail "external synchronization block did not run plan/apply/check in order"
fi

failure_trace="${test_temp}/route-failure.trace"
failure_output="${test_temp}/route-failure.out"
failure_error="${test_temp}/route-failure.err"
if bash -c '
  set -euo pipefail
  dispatcher="$1"
  failure_trace="$2"
  # shellcheck disable=SC1090
  source "${dispatcher}"
  run_markdown() { printf "%s\n" markdown >>"${failure_trace}"; }
  run_spelling() { printf "%s\n" spelling >>"${failure_trace}"; }
  run_static() {
    printf "%s\n" static >>"${failure_trace}"
    return 23
  }
  main all
' _ "${dispatcher}" "${failure_trace}" \
  >"${failure_output}" 2>"${failure_error}"; then
  fail "legacy all mode ignored the first failing stage"
else
  failure_status=$?
fi
if ((failure_status != 23)); then
  sed 's/^/  /' "${failure_error}" >&2
  fail "legacy all mode returned ${failure_status} instead of 23"
fi
if [[ "$(cat "${failure_output}")" != 'Core validation scope: source' || -s "${failure_error}" ]]; then
  sed 's/^/  /' "${failure_output}" >&2
  sed 's/^/  /' "${failure_error}" >&2
  fail "mocked legacy failure emitted unexpected output"
fi
printf '%s\n' static >"${test_temp}/route-failure.expected"
if ! cmp -s "${test_temp}/route-failure.expected" "${failure_trace}"; then
  diff -u \
    "${test_temp}/route-failure.expected" \
    "${failure_trace}" >&2 || true
  fail "all did not propagate the single static-stage failure"
fi

(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  resolve_command() { printf '%s\n' /bin/true; }
  resolve_hook_command() { printf '%s\n' /bin/true; }
  check_git_whitespace() { :; }
  check_powershell_line_endings() { :; }
  ensure_audit_temp() { fail "fast created an audit fixture"; }
  run_markdown() { fail "fast invoked network-backed Markdown tooling"; }
  run_spelling() { fail "fast invoked install-backed spelling tooling"; }
  run_script_smoke() { fail "fast invoked smoke fixtures"; }
  check_secret_scanner_behavior() { fail "fast invoked security fixtures"; }
  run_commitlint() { fail "fast invoked network-backed Commitlint"; }
  run_fast
)

hook_output="${test_temp}/hook.out"
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  run_hook_pre_commit() {
    printf 'pre-commit|%s|%s|%s\n' "$#" "${1:-}" "${2:-}"
  }
  run_hook_commit_msg() {
    printf 'commit-msg|%s|%s|%s\n' "$#" "${1:-}" "${2:-}"
  }
  run_hook_pre_push() {
    printf 'pre-push|%s|%s|%s\n' "$#" "${1:-}" "${2:-}"
  }
  main hook-pre-commit "value with spaces" second
  main hook-commit-msg "value with spaces" second
  main hook-pre-push "value with spaces" second
) >"${hook_output}"
cat >"${test_temp}/hook.expected" <<'HOOKS'
pre-commit|2|value with spaces|second
commit-msg|2|value with spaces|second
pre-push|2|value with spaces|second
HOOKS
if ! cmp -s "${test_temp}/hook.expected" "${hook_output}"; then
  diff -u "${test_temp}/hook.expected" "${hook_output}" >&2 || true
  fail "hook profile arguments were not forwarded exactly"
fi

missing_fixture="${test_temp}/module-missing/tools"
mkdir -p "${missing_fixture}"
cp "${dispatcher}" "${missing_fixture}/repository-audit.sh"
if bash "${missing_fixture}/repository-audit.sh" --help \
  >"${test_temp}/missing.out" 2>"${test_temp}/missing.err"; then
  fail "dispatcher accepted a missing module directory"
fi
assert_file_contains "${test_temp}/missing.err" \
  "Repository audit module not found: common.sh"

contract_fixture="${test_temp}/module-contract/tools"
mkdir -p "${contract_fixture}"
cp "${dispatcher}" "${contract_fixture}/repository-audit.sh"
cp -R "${source_root}/tools/repository-audit" "${contract_fixture}/repository-audit"
printf ':\n' >"${contract_fixture}/repository-audit/common.sh"
if bash "${contract_fixture}/repository-audit.sh" --help \
  >"${test_temp}/contract.out" 2>"${test_temp}/contract.err"; then
  fail "dispatcher accepted a module that violated its function contract"
fi
assert_file_contains "${test_temp}/contract.err" \
  "Repository audit module contract missing function: usage (common.sh)"

source_failure_fixture="${test_temp}/module-source-failure/tools"
source_failure_module_dir="${source_failure_fixture}/repository-audit"
source_failure_dispatcher="${source_failure_fixture}/repository-audit.sh"
source_failure_marker="${source_failure_module_dir}/later-module-loaded"
mkdir -p "${source_failure_fixture}"
cp "${dispatcher}" "${source_failure_dispatcher}"
cp -R "${source_root}/tools/repository-audit" \
  "${source_failure_module_dir}"
cat >"${source_failure_module_dir}/common.sh" <<'FAILING_MODULE'
#!/usr/bin/env bash

usage() { :; }

if [[ "${BASH_SOURCE[1]:-}" == "$0" ]] &&
  [[ $- != *e* || ! -o nounset || ! -o pipefail ]]; then
  return 36
fi

return 37
FAILING_MODULE
cat >"${source_failure_module_dir}/contracts.sh" <<'LATER_MODULE'
#!/usr/bin/env bash

: >"${audit_module_dir}/later-module-loaded"
check_semver_pattern_drift() { :; }
LATER_MODULE

source_failure_state="${test_temp}/module-source-failure-state"
source_failure_source_output="${source_failure_state}/source.out"
source_failure_source_error="${source_failure_state}/source.err"
source_failure_source_later="${source_failure_state}/source.later"
source_failure_exec_later="${source_failure_state}/exec.later"
mkdir -p "${source_failure_state}"
(
  set +e
  set +u
  set +o pipefail
  trap ':' EXIT HUP INT TERM ERR RETURN
  cd "${outside_root}"
  set +o >"${source_failure_state}/options.before"
  trap -p EXIT HUP INT TERM ERR RETURN \
    >"${source_failure_state}/traps.before"
  pwd -P >"${source_failure_state}/cwd.before"
  # shellcheck disable=SC1090
  source "${source_failure_dispatcher}" \
    >"${source_failure_source_output}" \
    2>"${source_failure_source_error}"
  printf '%s\n' "$?" >"${source_failure_state}/source.status"
  set +o >"${source_failure_state}/options.after"
  trap -p EXIT HUP INT TERM ERR RETURN \
    >"${source_failure_state}/traps.after"
  pwd -P >"${source_failure_state}/cwd.after"
  if [[ -e "${source_failure_marker}" ]]; then
    printf '%s\n' loaded >"${source_failure_source_later}"
    rm -f -- "${source_failure_marker}"
  fi
)

source_failure_output="${test_temp}/module-source-failure-exec.out"
source_failure_error="${test_temp}/module-source-failure-exec.err"
if bash "${source_failure_dispatcher}" --help \
  >"${source_failure_output}" 2>"${source_failure_error}"; then
  source_failure_exec_status=0
else
  source_failure_exec_status=$?
fi
if [[ -e "${source_failure_marker}" ]]; then
  printf '%s\n' loaded >"${source_failure_exec_later}"
fi

source_failure_status="$(cat "${source_failure_state}/source.status")"
if [[ "${source_failure_status}" != 37 ]]; then
  fail "sourced dispatcher returned ${source_failure_status} for module status 37"
fi
if ((source_failure_exec_status != 37)); then
  fail "executed dispatcher accepted a module whose source returned nonzero"
fi
printf '%s\n' 'Repository audit module failed to load: common.sh' \
  >"${source_failure_state}/diagnostic.expected"
for failure_diagnostic in \
  "${source_failure_source_error}" \
  "${source_failure_error}"; do
  if ! cmp -s \
    "${source_failure_state}/diagnostic.expected" \
    "${failure_diagnostic}"; then
    diff -u \
      "${source_failure_state}/diagnostic.expected" \
      "${failure_diagnostic}" >&2 || true
    fail "module source failure diagnostic changed"
  fi
done
if [[ -s "${source_failure_source_output}" || -s "${source_failure_output}" ]]; then
  fail "module source failure emitted standard output"
fi
for state_name in options traps cwd; do
  if ! cmp -s \
    "${source_failure_state}/${state_name}.before" \
    "${source_failure_state}/${state_name}.after"; then
    diff -u \
      "${source_failure_state}/${state_name}.before" \
      "${source_failure_state}/${state_name}.after" >&2 || true
    fail "failed sourced dispatcher changed caller ${state_name}"
  fi
done
if [[ -e "${source_failure_source_later}" || -e "${source_failure_exec_later}" ]]; then
  fail "dispatcher loaded a later module after a module source failure"
fi

errexit_fixture="${test_temp}/module-errexit-failure/tools"
errexit_module_dir="${errexit_fixture}/repository-audit"
errexit_dispatcher="${errexit_fixture}/repository-audit.sh"
errexit_later_marker="${errexit_module_dir}/later-module-loaded"
errexit_main_marker="${errexit_module_dir}/main-reached"
mkdir -p "${errexit_fixture}"
cp "${dispatcher}" "${errexit_dispatcher}"
cp -R "${source_root}/tools/repository-audit" "${errexit_module_dir}"
cat >"${errexit_module_dir}/common.sh" <<'ERREXIT_MODULE'
#!/usr/bin/env bash

usage() { : >"${audit_module_dir}/main-reached"; }

false
:
ERREXIT_MODULE
cat >"${errexit_module_dir}/contracts.sh" <<'ERREXIT_LATER_MODULE'
#!/usr/bin/env bash

: >"${audit_module_dir}/later-module-loaded"
check_semver_pattern_drift() { :; }
ERREXIT_LATER_MODULE

errexit_state="${test_temp}/module-errexit-failure-state"
mkdir -p "${errexit_state}"
(
  set +e
  set +u
  set +o pipefail
  trap ':' EXIT HUP INT TERM ERR RETURN
  cd "${outside_root}"
  set +o >"${errexit_state}/options.before"
  trap -p EXIT HUP INT TERM ERR RETURN >"${errexit_state}/traps.before"
  pwd -P >"${errexit_state}/cwd.before"
  # shellcheck disable=SC1090
  source "${errexit_dispatcher}" \
    >"${errexit_state}/source.out" \
    2>"${errexit_state}/source.err"
  errexit_source_status=$?
  printf '%s\n' "${errexit_source_status}" >"${errexit_state}/source.status"
  if ((errexit_source_status == 0)) && declare -F main >/dev/null; then
    main --help >/dev/null 2>&1
  fi
  set +o >"${errexit_state}/options.after"
  trap -p EXIT HUP INT TERM ERR RETURN >"${errexit_state}/traps.after"
  pwd -P >"${errexit_state}/cwd.after"
)

errexit_exec_output="${test_temp}/module-errexit-failure-exec.out"
errexit_exec_error="${test_temp}/module-errexit-failure-exec.err"
if bash "${errexit_dispatcher}" --help \
  >"${errexit_exec_output}" 2>"${errexit_exec_error}"; then
  errexit_exec_status=0
else
  errexit_exec_status=$?
fi

if [[ "$(cat "${errexit_state}/source.status")" != 1 ]]; then
  fail "sourced dispatcher ignored an unguarded failing module command"
fi
if ((errexit_exec_status != 1)); then
  fail "executed dispatcher ignored an unguarded failing module command"
fi
for state_name in options traps cwd; do
  if ! cmp -s \
    "${errexit_state}/${state_name}.before" \
    "${errexit_state}/${state_name}.after"; then
    diff -u \
      "${errexit_state}/${state_name}.before" \
      "${errexit_state}/${state_name}.after" >&2 || true
    fail "failed strict preflight changed caller ${state_name}"
  fi
done
for errexit_diagnostic in \
  "${errexit_state}/source.err" \
  "${errexit_exec_error}"; do
  if ! cmp -s \
    "${source_failure_state}/diagnostic.expected" \
    "${errexit_diagnostic}"; then
    diff -u \
      "${source_failure_state}/diagnostic.expected" \
      "${errexit_diagnostic}" >&2 || true
    fail "unguarded module failure diagnostic changed"
  fi
done
if [[ -s "${errexit_state}/source.out" || -s "${errexit_exec_output}" ]]; then
  fail "unguarded module failure emitted standard output"
fi
if [[ -e "${errexit_later_marker}" || -e "${errexit_main_marker}" ]]; then
  fail "unguarded module failure reached a later module or main"
fi

# BEGIN GUARDED MERGE WORKFLOW TESTS
(
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  check_guarded_pull_request_merge_workflow_contract
)
# END GUARDED MERGE WORKFLOW TESTS

space_fixture_root="${test_temp}/copied repository with spaces"
space_tools="${space_fixture_root}/tools"
space_dispatcher="${space_tools}/repository-audit.sh"
mkdir -p "${space_tools}" "${space_fixture_root}/.githooks"
git init -q "${space_fixture_root}"
cp "${dispatcher}" "${space_dispatcher}"
cp -R "${source_root}/tools/repository-audit" \
  "${space_tools}/repository-audit"
cp "${source_root}/tools/project_config.py" \
  "${source_root}/tools/project_validation.py" \
  "${source_root}/tools/process_runner.py" "${space_tools}/"
cat >>"${space_tools}/repository-audit/profiles.sh" <<'SPACE_PROFILE'

run_fast() {
  if [[ $- != *e* || ! -o nounset || ! -o pipefail ]]; then
    printf '%s\n' 'space-fast: dispatcher strict mode is not active.' >&2
    return 1
  fi
  printf '%s\n' 'space-fast|strict'
}
SPACE_PROFILE
cat >>"${space_tools}/repository-audit/hooks.sh" <<'SPACE_HOOK'

run_hook_pre_commit() {
  printf 'space-hook|%s|%s|%s\n' "$#" "${1:-}" "${2:-}"
}
SPACE_HOOK
for module_name in common contracts hooks profiles security smoke; do
  if [[ ! -f "${space_tools}/repository-audit/${module_name}.sh" ]]; then
    fail "copied path-with-spaces fixture is missing ${module_name}.sh"
  fi
done
(
  cd "${outside_root}"
  bash "${space_dispatcher}" --help \
    >"${test_temp}/space-help.out" \
    2>"${test_temp}/space-help.err"
  bash "${space_dispatcher}" hook-pre-commit "value with spaces" second \
    >"${test_temp}/space-profile.out" \
    2>"${test_temp}/space-profile.err"
  bash "${space_dispatcher}" fast \
    >"${test_temp}/space-fast.out" \
    2>"${test_temp}/space-fast.err"
)
for space_error in \
  "${test_temp}/space-help.err" \
  "${test_temp}/space-profile.err" \
  "${test_temp}/space-fast.err"; do
  if [[ -s "${space_error}" ]]; then
    sed 's/^/  /' "${space_error}" >&2
    fail "path-with-spaces fixture emitted diagnostics"
  fi
done
assert_file_contains "${test_temp}/space-help.out" \
  "Usage: bash tools/repository-audit.sh"
space_profile_actual="$(cat "${test_temp}/space-profile.out")"
space_profile_expected="space-hook|2|value with spaces|second"
if [[ "${space_profile_actual}" != "${space_profile_expected}" ]]; then
  sed 's/^/  /' "${test_temp}/space-profile.out" >&2
  fail "path-with-spaces profile did not preserve arguments"
fi
assert_file_contains "${test_temp}/space-fast.out" 'space-fast|strict'
assert_file_contains "${test_temp}/space-fast.out" 'Core validation scope: source'
assert_file_contains "${test_temp}/space-fast.out" 'Project validation WARNING:'
expected_space_fixture="${test_temp}/copied repository with spaces"
if [[ "${space_fixture_root}" != "${expected_space_fixture}" ]]; then
  fail "refusing to remove unexpected path-with-spaces fixture"
fi
rm -rf -- "${space_fixture_root}"
if [[ -e "${space_fixture_root}" ]]; then
  fail "path-with-spaces fixture cleanup failed"
fi

printf '%s\n' 'PASS: repository audit dispatcher and profiles'
