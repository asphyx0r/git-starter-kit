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

assert_file_contains() {
  local file_path="$1"
  local expected="$2"

  if ! grep -F -- "${expected}" "${file_path}" >/dev/null; then
    sed 's/^/  /' "${file_path}" >&2
    fail "expected output not found: ${expected}"
  fi
}

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

  for mode in all full readonly markdown spelling static powershell-static; do
    printf '%s:' "${mode}"
    main "${mode}" | paste -sd, -
  done
) >"${route_output}"
cat >"${test_temp}/route.expected" <<'ROUTES'
all:static
full:static
readonly:readonly
markdown:markdown
spelling:spelling
static:static
powershell-static:powershell-static
ROUTES
if ! cmp -s "${test_temp}/route.expected" "${route_output}"; then
  diff -u "${test_temp}/route.expected" "${route_output}" >&2 || true
  fail "legacy mode routing changed"
fi

profile_bin="${test_temp}/profile-bin"
mkdir -p "${profile_bin}"
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
    if [[ "$#" -ne 3 || "$1" != "${source_root}" ||
      "$2" != "tools/build-release-package.ps1" ||
      "$3" != "tools/git-init.ps1" ]]; then
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

release_artifact_workflow_fixture="${test_temp}/release-artifacts-workflow.yml"
cat >"${release_artifact_workflow_fixture}" <<'RELEASE_ARTIFACT_WORKFLOW'
---
name: Release artifacts

"on":
  push:
    tags:
      - "v*"

permissions:
  contents: read

jobs:
  release-artifacts:
    name: Release artifacts
    runs-on: ubuntu-24.04
    timeout-minutes: 10

    steps:
      - name: Checkout tagged release
        # actions/checkout@v7.0.0
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          fetch-depth: 0
          persist-credentials: false

      - name: Set up Python
        # actions/setup-python@v7.0.0
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: "3.11"

      - name: Install manifest validator
        run: >-
          python -m pip install
          --disable-pip-version-check
          --no-input
          --require-hashes
          --requirement tools/release-artifacts-requirements.txt

      - name: Validate release identification
        env:
          RELEASE_REF: ${{ github.ref_name }}
          RELEASE_TREEISH: ${{ github.sha }}
        run: >-
          python3 tools/release-artifacts.py check
          --expected-ref "${RELEASE_REF}"
          --treeish "${RELEASE_TREEISH}"
          --repository-root .
RELEASE_ARTIFACT_WORKFLOW

assert_release_artifact_contract_rejects() {
  local case_name="$1"
  local fixture_path="$2"
  local expected_diagnostic="$3"
  local actual_status
  local expected_error="${test_temp}/${case_name}.expected.err"

  if (
    # shellcheck disable=SC1090
    source "${dispatcher}"
    repository_root="${source_root}"
    cd "${repository_root}"
    check_release_artifact_contract "${fixture_path}"
  ) >"${test_temp}/${case_name}.out" 2>"${test_temp}/${case_name}.err"; then
    actual_status=0
  else
    actual_status=$?
  fi
  if ((actual_status == 0)); then
    printf '  accepted invalid fixture: %s\n' "${case_name}" >&2
    return 1
  fi
  if ((actual_status != 1)); then
    printf '  fixture returned %s, expected 1: %s\n' \
      "${actual_status}" "${case_name}" >&2
    return 1
  fi
  printf '%s\n' "${expected_diagnostic}" >"${expected_error}"
  if ! cmp -s "${expected_error}" "${test_temp}/${case_name}.err"; then
    diff -u \
      "${expected_error}" "${test_temp}/${case_name}.err" >&2 || true
    printf '  fixture diagnostic changed: %s\n' "${case_name}" >&2
    return 1
  fi
}

if ! (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  check_release_artifact_contract "${release_artifact_workflow_fixture}"
) >"${test_temp}/release-artifacts-valid.out" \
  2>"${test_temp}/release-artifacts-valid.err"; then
  sed 's/^/  /' "${test_temp}/release-artifacts-valid.err" >&2
  fail "Release artifacts contract rejected the valid workflow fixture"
fi

release_artifact_contract_failures=0

missing_setup_python_fixture="${test_temp}/release-artifacts-missing-setup.yml"
sed '/      - name: Set up Python/,/          python-version: "3.11"/d' \
  "${release_artifact_workflow_fixture}" >"${missing_setup_python_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-missing-setup "${missing_setup_python_fixture}" \
  'Release artifacts workflow does not configure setup-python.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

wrong_setup_python_sha_fixture="${test_temp}/release-artifacts-wrong-setup-sha.yml"
sed \
  's/5fda3b95a4ea91299a34e894583c3862153e4b97/0000000000000000000000000000000000000000/' \
  "${release_artifact_workflow_fixture}" >"${wrong_setup_python_sha_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-wrong-setup-sha "${wrong_setup_python_sha_fixture}" \
  'Release artifacts workflow uses an unexpected setup-python revision.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

wrong_python_version_fixture="${test_temp}/release-artifacts-wrong-python.yml"
sed 's/python-version: "3.11"/python-version: "3.12"/' \
  "${release_artifact_workflow_fixture}" >"${wrong_python_version_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-wrong-python "${wrong_python_version_fixture}" \
  'Release artifacts workflow does not use Python 3.11.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

missing_no_input_fixture="${test_temp}/release-artifacts-missing-no-input.yml"
sed '/          --no-input/d' \
  "${release_artifact_workflow_fixture}" >"${missing_no_input_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-missing-no-input "${missing_no_input_fixture}" \
  'Release artifacts workflow pip install is missing --no-input.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

release_trigger_fixture="${test_temp}/release-artifacts-release-trigger.yml"
sed '/^  push:$/i\  release:\n    types: [published]' \
  "${release_artifact_workflow_fixture}" >"${release_trigger_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-release-trigger "${release_trigger_fixture}" \
  'Release artifacts workflow trigger boundary changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

write_permission_fixture="${test_temp}/release-artifacts-write-permission.yml"
sed 's/  contents: read/  contents: write/' \
  "${release_artifact_workflow_fixture}" >"${write_permission_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-write-permission "${write_permission_fixture}" \
  'Release artifacts workflow privilege boundary changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

missing_fetch_depth_fixture="${test_temp}/release-artifacts-missing-fetch-depth.yml"
sed '/          fetch-depth: 0/d' \
  "${release_artifact_workflow_fixture}" >"${missing_fetch_depth_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-missing-fetch-depth "${missing_fetch_depth_fixture}" \
  'Release artifacts workflow checkout contract changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

cache_fixture="${test_temp}/release-artifacts-cache.yml"
sed '/          python-version: "3.11"/a\          cache: pip' \
  "${release_artifact_workflow_fixture}" >"${cache_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-cache "${cache_fixture}" \
  'Release artifacts workflow runtime contract changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

environment_fixture="${test_temp}/release-artifacts-environment.yml"
sed '/    timeout-minutes: 10/a\    environment: release' \
  "${release_artifact_workflow_fixture}" >"${environment_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-environment "${environment_fixture}" \
  'Release artifacts workflow isolation contract changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

wrong_checkout_sha_fixture="${test_temp}/release-artifacts-wrong-checkout-sha.yml"
sed \
  's/9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0/0000000000000000000000000000000000000000/' \
  "${release_artifact_workflow_fixture}" >"${wrong_checkout_sha_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-wrong-checkout-sha "${wrong_checkout_sha_fixture}" \
  'Release artifacts workflow checkout contract changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

checkout_persistence_fixture="${test_temp}/release-artifacts-persist-credentials.yml"
sed 's/persist-credentials: false/persist-credentials: true/' \
  "${release_artifact_workflow_fixture}" >"${checkout_persistence_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-persist-credentials "${checkout_persistence_fixture}" \
  'Release artifacts workflow checkout contract changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

release_artifacts_timeout_fixture="${test_temp}/release-artifacts-timeout.yml"
sed 's/timeout-minutes: 10/timeout-minutes: 11/' \
  "${release_artifact_workflow_fixture}" >"${release_artifacts_timeout_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-timeout "${release_artifacts_timeout_fixture}" \
  'Release artifacts workflow job graph changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

release_artifacts_pointer_fixture="${test_temp}/release-artifacts-pointer.yml"
sed 's#tools/release-artifacts-requirements.txt#tools/quality/requirements.lock#' \
  "${release_artifact_workflow_fixture}" >"${release_artifacts_pointer_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-pointer "${release_artifacts_pointer_fixture}" \
  'Release artifacts workflow dependency contract changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

release_artifacts_ref_fixture="${test_temp}/release-artifacts-ref.yml"
sed 's/github.ref_name/github.ref/' \
  "${release_artifact_workflow_fixture}" >"${release_artifacts_ref_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-ref "${release_artifacts_ref_fixture}" \
  'Release artifacts workflow validation contract changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

release_artifacts_treeish_fixture="${test_temp}/release-artifacts-treeish.yml"
sed 's/github.sha/github.ref_name/' \
  "${release_artifact_workflow_fixture}" >"${release_artifacts_treeish_fixture}"
assert_release_artifact_contract_rejects \
  release-artifacts-treeish "${release_artifacts_treeish_fixture}" \
  'Release artifacts workflow validation contract changed.' ||
  release_artifact_contract_failures=$((release_artifact_contract_failures + 1))

if ((release_artifact_contract_failures > 0)); then
  fail "Release artifacts contract accepted ${release_artifact_contract_failures} invalid fixtures"
fi

replace_workflow_literal() {
  local source_path="$1"
  local destination_path="$2"
  local old_text="$3"
  local new_text="$4"

  "${quality_python_cmd}" - \
    "${source_path}" "${destination_path}" "${old_text}" "${new_text}" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
old = sys.argv[3]
if source.count(old) != 1:
    raise SystemExit(f"expected exactly one occurrence of {old!r}")
Path(sys.argv[2]).write_text(source.replace(old, sys.argv[4]), encoding="utf-8")
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

assert_release_package_contract_rejects() {
  local case_name="$1"
  local fixture_path="$2"
  local expected_diagnostic="$3"
  local actual_status
  local expected_error="${test_temp}/${case_name}.expected.err"

  if (
    # shellcheck disable=SC1090
    source "${dispatcher}"
    repository_root="${source_root}"
    cd "${repository_root}"
    check_release_package_portability "${fixture_path}"
  ) >"${test_temp}/${case_name}.out" 2>"${test_temp}/${case_name}.err"; then
    actual_status=0
  else
    actual_status=$?
  fi
  if ((actual_status == 0)); then
    printf '  accepted invalid fixture: %s\n' "${case_name}" >&2
    return 1
  fi
  if ((actual_status != 1)); then
    printf '  fixture returned %s, expected 1: %s\n' \
      "${actual_status}" "${case_name}" >&2
    return 1
  fi
  printf '%s\n' "${expected_diagnostic}" >"${expected_error}"
  if ! cmp -s "${expected_error}" "${test_temp}/${case_name}.err"; then
    diff -u \
      "${expected_error}" "${test_temp}/${case_name}.err" >&2 || true
    printf '  fixture diagnostic changed: %s\n' "${case_name}" >&2
    return 1
  fi
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

release_package_contract_failures=0
release_package_mutation_root="${test_temp}/release-package-mutations"
mkdir -p "${release_package_mutation_root}"

privilege_diagnostic='Release package workflow privilege boundary changed.'
graph_diagnostic='Release package workflow job graph changed.'
concurrency_diagnostic='Release package workflow concurrency changed.'
trigger_diagnostic='Release package workflow trigger contract changed.'
runtime_diagnostic='Release package workflow runtime setup changed.'
checkout_diagnostic='Release package workflow checkout boundary changed.'
transport_diagnostic='Release package workflow transport contract changed.'
publication_diagnostic='Release package workflow publication contract changed.'
# shellcheck disable=SC2016
declare -a release_package_mutations=(
  permissions 'contents: read' 'contents: write' "${privilege_diagnostic}"
  environment 'environment: release' 'environment: staging' "${privilege_diagnostic}"
  needs 'needs: build' 'needs: package' "${graph_diagnostic}"
  concurrency 'cancel-in-progress: false' 'cancel-in-progress: true'
  "${concurrency_diagnostic}"
  python-version 'python-version: "3.11"' 'python-version: "3.12"'
  "${runtime_diagnostic}"
  node-version 'node-version: "24.20.0"' 'node-version: "24.19.0"'
  "${runtime_diagnostic}"
  action-sha 820762786026740c76f36085b0efc47a31fe5020
  0000000000000000000000000000000000000000 "${runtime_diagnostic}"
  timeout 'timeout-minutes: 30' 'timeout-minutes: 31' "${graph_diagnostic}"
  trigger 'types: [published]' 'types: [released]' "${trigger_diagnostic}"
  upload-path 'release-package-transfer/SHA256SUMS'
  'release-package-transfer/unexpected.txt' "${transport_diagnostic}"
  checkout-credentials 'persist-credentials: false'
  'persist-credentials: true' "${checkout_diagnostic}"
  no-clobber 'gh release upload "$RELEASE_TAG"'
  'gh release upload "$RELEASE_TAG" --clobber' "${publication_diagnostic}"
)

for ((mutation_index = 0; mutation_index < ${#release_package_mutations[@]}; mutation_index += 4)); do
  case_name="${release_package_mutations[mutation_index]}"
  old_text="${release_package_mutations[mutation_index + 1]}"
  new_text="${release_package_mutations[mutation_index + 2]}"
  expected_diagnostic="${release_package_mutations[mutation_index + 3]}"
  mutation_path="${release_package_mutation_root}/${case_name}.yml"
  replace_workflow_literal \
    "${release_package_workflow}" "${mutation_path}" "${old_text}" "${new_text}"
  assert_release_package_contract_rejects \
    "release-package-${case_name}" "${mutation_path}" \
    "${expected_diagnostic}" ||
    release_package_contract_failures=$((release_package_contract_failures + 1))
done

tag_required_fixture="${release_package_mutation_root}/tag-required.yml"
replace_workflow_literal \
  "${release_package_workflow}" "${tag_required_fixture}" \
  $'      tag:\n        description: >-\n          Repository release tag whose package assets will be uploaded\n        required: true' \
  $'      tag:\n        description: >-\n          Repository release tag whose package assets will be uploaded\n        required: false'
assert_release_package_contract_rejects \
  release-package-tag-required "${tag_required_fixture}" \
  'Release package workflow trigger contract changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

agent_rules_required_fixture="${release_package_mutation_root}/agent-rules-required.yml"
replace_workflow_literal \
  "${release_package_workflow}" "${agent_rules_required_fixture}" \
  $'      agent_rules_ref:\n        description: agent-coding-rules latest release or SemVer tag\n        required: true' \
  $'      agent_rules_ref:\n        description: agent-coding-rules latest release or SemVer tag\n        required: false'
assert_release_package_contract_rejects \
  release-package-agent-rules-required "${agent_rules_required_fixture}" \
  'Release package workflow trigger contract changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

extra_job_fixture="${release_package_mutation_root}/extra-job.yml"
replace_workflow_literal \
  "${release_package_workflow}" "${extra_job_fixture}" \
  $'\n  publish:\n' \
  $'\n  unexpected:\n    runs-on: ubuntu-24.04\n    steps: []\n\n  publish:\n'
assert_release_package_contract_rejects \
  release-package-extra-job "${extra_job_fixture}" \
  'Release package workflow job graph changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

checkout_publish_fixture="${release_package_mutation_root}/checkout-publish.yml"
replace_workflow_literal \
  "${release_package_workflow}" "${checkout_publish_fixture}" \
  '      - name: Download sealed release payload' \
  $'      - name: Checkout in publish\n        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0\n\n      - name: Download sealed release payload'
assert_release_package_contract_rejects \
  release-package-checkout-publish "${checkout_publish_fixture}" \
  'Release package workflow job graph changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

unnamed_publish_step_fixture="${release_package_mutation_root}/unnamed-publish-step.yml"
replace_workflow_literal \
  "${release_package_workflow}" "${unnamed_publish_step_fixture}" \
  $'    steps:\n      - name: Download sealed release payload\n        # actions/download-artifact@v8.0.1' \
  $'    steps:\n      - run: echo unexpected\n\n      - name: Download sealed release payload\n        # actions/download-artifact@v8.0.1'
assert_release_package_contract_rejects \
  release-package-unnamed-publish-step "${unnamed_publish_step_fixture}" \
  'Release package workflow job graph changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

cache_install_fixture="${release_package_mutation_root}/cache.yml"
replace_workflow_literal \
  "${release_package_workflow}" "${cache_install_fixture}" \
  '          node-version: "24.20.0"' \
  $'          node-version: "24.20.0"\n          cache: npm'
assert_release_package_contract_rejects \
  release-package-cache "${cache_install_fixture}" \
  'Release package workflow runtime setup changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

duplicate_install_fixture="${release_package_mutation_root}/duplicate-install.yml"
replace_workflow_literal \
  "${release_package_workflow}" "${duplicate_install_fixture}" \
  '          npm ci --ignore-scripts --prefix tools/quality' \
  $'          npm ci --ignore-scripts --prefix tools/quality\n          npm ci --ignore-scripts --prefix tools/quality'
assert_release_package_contract_rejects \
  release-package-duplicate-install "${duplicate_install_fixture}" \
  'Release package workflow dependency installation changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

publish_without_step_auth_fixture="${release_package_mutation_root}/token-intermediate.yml"
job_auth_scope_fixture="${release_package_mutation_root}/token-scope.yml"
# shellcheck disable=SC2016
replace_workflow_literal \
  "${release_package_workflow}" "${publish_without_step_auth_fixture}" \
  '          GITHUB_TOKEN: ${{ github.token }}' ''
replace_workflow_literal \
  "${publish_without_step_auth_fixture}" "${job_auth_scope_fixture}" \
  '    timeout-minutes: 30' \
  $'    timeout-minutes: 30\n    env:\n      GITHUB_TOKEN: ${{ github.token }}'
assert_release_package_contract_rejects \
  release-package-token-scope "${job_auth_scope_fixture}" \
  'Release package workflow publication contract changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

executed_payload_fixture="${release_package_mutation_root}/executed-payload.yml"
replace_workflow_literal \
  "${release_package_workflow}" "${executed_payload_fixture}" \
  $'          python - "$TRANSFER_ROOT" \\\n            "$EXPECTED_PACKAGE_NAME" "$EXPECTED_TOOLKIT_NAME" <<\'PY\'' \
  $'          "$TRANSFER_ROOT/$EXPECTED_PACKAGE_NAME"\n          python - "$TRANSFER_ROOT" \\\n            "$EXPECTED_PACKAGE_NAME" "$EXPECTED_TOOLKIT_NAME" <<\'PY\''
assert_release_package_contract_rejects \
  release-package-executed-payload "${executed_payload_fixture}" \
  'Release package workflow transport contract changed.' ||
  release_package_contract_failures=$((release_package_contract_failures + 1))

if ((release_package_contract_failures > 0)); then
  fail "Release package contract accepted ${release_package_contract_failures} invalid fixtures"
fi

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
repository_audit_workflow_fixture="${test_temp}/repository-audit-workflow.yml"
cat >"${repository_audit_workflow_fixture}" <<'REPOSITORY_AUDIT_WORKFLOW'
---
name: Repository audit

"on":
  release:
    types: [published]
  push:
    branches: [master, "codex/release-preflight-*"]
    tags: ["v*"]
  pull_request:
    branches: [master]
  workflow_dispatch:

permissions:
  contents: read

env:
  NODE_VERSION: "24.20.0"

jobs:
  quality-linux:
    name: Quality - Ubuntu 24.04 / Python 3.11
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    steps:
      - name: Checkout repository
        # actions/checkout@v7.0.0
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          fetch-depth: 0
          persist-credentials: false
      - name: Set up Python
        # actions/setup-python@v7.0.0
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: "3.11"
      - name: Set up Node
        # actions/setup-node@v7.0.0
        uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020
        with:
          node-version: ${{ env.NODE_VERSION }}
      - name: Install locked language toolchains
        shell: bash
        run: |
          python -m pip install --disable-pip-version-check \
            --require-hashes \
            --requirement tools/quality/requirements.lock
          npm ci --ignore-scripts --prefix tools/quality
      - name: Install verified external tools
        shell: bash
        run: |
          python tools/quality/install-external-tools.py \
            --platform linux-x64 \
            --install-root "$RUNNER_TEMP/quality-tools"
          echo "$RUNNER_TEMP/quality-tools/bin" >> "$GITHUB_PATH"
          echo "PSModulePath=$RUNNER_TEMP/quality-tools/Modules:${PSModulePath:-}" \
            >> "$GITHUB_ENV"
      - name: Run the complete quality gate
        shell: bash
        env:
          AUDIT_COMMIT_SHA: >-
            ${{ github.event.pull_request.head.sha || github.sha }}
          BEFORE_SHA: >-
            ${{ github.event_name == 'release' &&
            '0000000000000000000000000000000000000000' ||
            github.event.before }}
          GIT_AUTHOR_NAME: Codex
          GIT_AUTHOR_EMAIL: codex@example.com
          GIT_COMMITTER_NAME: Codex
          GIT_COMMITTER_EMAIL: codex@example.com
        run: bash tools/repository-audit.sh full

  compatibility-windows:
    name: Compatibility - Windows 2025 / Python 3.14
    runs-on: windows-2025
    timeout-minutes: 25
    steps:
      - name: Checkout repository
        # actions/checkout@v7.0.0
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          fetch-depth: 0
          persist-credentials: false
      - name: Set up Python
        # actions/setup-python@v7.0.0
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: "3.14"
      - name: Set up Node
        # actions/setup-node@v7.0.0
        uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020
        with:
          node-version: ${{ env.NODE_VERSION }}
      - name: Install locked language toolchains
        shell: pwsh
        run: |
          python -m pip install --disable-pip-version-check `
            --require-hashes `
            --requirement tools/quality/requirements.lock
          npm ci --ignore-scripts --prefix tools/quality
      - name: Install verified PowerShell analyzer
        shell: pwsh
        run: |
          python tools/quality/install-external-tools.py `
            --platform windows-x64 `
            --tool PSScriptAnalyzer `
            --install-root "$env:RUNNER_TEMP/quality-tools"
          Add-Content $env:GITHUB_ENV `
            "PSModulePath=$env:RUNNER_TEMP/quality-tools/Modules$([IO.Path]::PathSeparator)$env:PSModulePath"
      - name: Run cross-platform compatibility checks
        shell: bash
        run: bash tools/repository-audit.sh fast
      - name: Run the complete Python suite on 3.14
        shell: pwsh
        run: python -m unittest discover -s tests -p 'test_*.py'
      - name: Analyze PowerShell on Windows
        shell: bash
        run: bash tools/repository-audit.sh powershell-static

  repository-audit:
    name: >-
      ${{ github.event_name == 'workflow_dispatch' &&
      'Repository audit (manual)' || 'Repository audit' }}
    needs: [quality-linux, compatibility-windows]
    if: ${{ always() }}
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - name: Require both supported environments
        env:
          LINUX_RESULT: ${{ needs.quality-linux.result }}
          WINDOWS_RESULT: ${{ needs.compatibility-windows.result }}
        run: |
          test "$LINUX_RESULT" = success && test "$WINDOWS_RESULT" = success
REPOSITORY_AUDIT_WORKFLOW

# shellcheck disable=SC1090
source "${dispatcher}"

replace_repository_audit_literal() {
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
    raise SystemExit(
        f"expected {expected_count} occurrence(s) of {old!r}, "
        f"found {source.count(old)}"
    )
Path(sys.argv[2]).write_bytes(source.replace(old, sys.argv[4]).encode("utf-8"))
PY
}

assert_repository_audit_contract_rejects() {
  local case_name="$1"
  local fixture_path="$2"
  local expected_diagnostic="$3"
  local actual_status
  local expected_error="${test_temp}/${case_name}.expected.err"

  if (
    repository_root="${source_root}"
    cd "${repository_root}"
    check_repository_audit_workflow_contract \
      "${fixture_path}" "${source_root}/tools/quality/versions.json"
  ) >"${test_temp}/${case_name}.out" 2>"${test_temp}/${case_name}.err"; then
    actual_status=0
  else
    actual_status=$?
  fi
  if ((actual_status == 0)); then
    printf '  accepted invalid fixture: %s\n' "${case_name}" >&2
    return 1
  fi
  if ((actual_status != 1)); then
    printf '  fixture returned %s, expected 1: %s\n' \
      "${actual_status}" "${case_name}" >&2
    return 1
  fi
  printf '%s\n' "${expected_diagnostic}" >"${expected_error}"
  if ! cmp -s "${expected_error}" "${test_temp}/${case_name}.err"; then
    diff -u \
      "${expected_error}" "${test_temp}/${case_name}.err" >&2 || true
    printf '  fixture diagnostic changed: %s\n' "${case_name}" >&2
    return 1
  fi
}

repository_audit_contract_failures=0
repository_audit_mutation_root="${test_temp}/repository-audit-mutations"
mkdir -p "${repository_audit_mutation_root}"

assert_repository_audit_mutation() {
  local case_name="$1"
  local old_text="$2"
  local new_text="$3"
  local expected_diagnostic="$4"
  local expected_count="${5:-1}"
  local mutation_path="${repository_audit_mutation_root}/${case_name}.yml"

  replace_repository_audit_literal \
    "${repository_audit_workflow_fixture}" "${mutation_path}" \
    "${old_text}" "${new_text}" "${expected_count}"
  assert_repository_audit_contract_rejects \
    "repository-audit-${case_name}" "${mutation_path}" \
    "${expected_diagnostic}" ||
    repository_audit_contract_failures=$((repository_audit_contract_failures + 1))
}

repository_trigger_diagnostic='Repository audit workflow trigger contract changed.'
repository_privilege_diagnostic='Repository audit workflow privilege boundary changed.'
repository_graph_diagnostic='Repository audit workflow job graph changed.'
repository_runner_diagnostic='Repository audit workflow runner or timeout contract changed.'
repository_action_diagnostic='Repository audit workflow action revision contract changed.'
repository_checkout_diagnostic='Repository audit workflow checkout boundary changed.'
repository_runtime_diagnostic='Repository audit workflow runtime setup changed.'
repository_dependency_diagnostic='Repository audit workflow dependency installation changed.'
repository_external_diagnostic='Repository audit workflow external tool setup changed.'
repository_route_diagnostic='Repository audit workflow audit routing changed.'
repository_range_diagnostic='Repository audit workflow commit range changed.'
repository_aggregate_diagnostic='Repository audit workflow aggregate contract changed.'

if ! (
  repository_root="${source_root}"
  cd "${repository_root}"
  check_repository_audit_workflow_contract \
    "${repository_audit_workflow_fixture}" \
    "${source_root}/tools/quality/versions.json"
) >"${test_temp}/repository-audit-valid.out" \
  2>"${test_temp}/repository-audit-valid.err"; then
  sed 's/^/  /' "${test_temp}/repository-audit-valid.err" >&2
  fail "Repository audit contract rejected its valid fixture"
fi

assert_repository_audit_mutation \
  release-event 'types: [published]' 'types: [edited]' \
  "${repository_trigger_diagnostic}"
assert_repository_audit_mutation \
  missing-pull-request $'  pull_request:\n    branches: [master]\n' '' \
  "${repository_trigger_diagnostic}"
assert_repository_audit_mutation \
  schedule $'  workflow_dispatch:\n' \
  $'  schedule:\n    - cron: "17 5 * * *"\n  workflow_dispatch:\n' \
  "${repository_trigger_diagnostic}"
assert_repository_audit_mutation \
  push-branch \
  $'    branches: [master, "codex/release-preflight-*"]' \
  $'    branches: [main, "codex/release-preflight-*"]' \
  "${repository_trigger_diagnostic}"
assert_repository_audit_mutation \
  missing-preflight \
  '    branches: [master, "codex/release-preflight-*"]' \
  '    branches: [master]' \
  "${repository_trigger_diagnostic}"
assert_repository_audit_mutation \
  broad-preflight \
  '    branches: [master, "codex/release-preflight-*"]' \
  '    branches: [master, "codex/*"]' \
  "${repository_trigger_diagnostic}"
assert_repository_audit_mutation \
  push-tags '    tags: ["v*"]' '    tags: ["release-*"]' \
  "${repository_trigger_diagnostic}"
assert_repository_audit_mutation \
  pull-request-branch \
  $'  pull_request:\n    branches: [master]' \
  $'  pull_request:\n    branches: [main]' \
  "${repository_trigger_diagnostic}"

assert_repository_audit_mutation \
  contents-write '  contents: read' '  contents: write' \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  write-all $'permissions:\n  contents: read' 'permissions: write-all' \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  id-token $'  contents: read\n' $'  contents: read\n  id-token: write\n' \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  token $'env:\n  NODE_VERSION: "24.20.0"' \
  $'env:\n  NODE_VERSION: "24.20.0"\n  GITHUB_TOKEN: '"\${{ github.token }}" \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  job-permissions \
  $'    name: Quality - Ubuntu 24.04 / Python 3.11\n    runs-on: ubuntu-24.04\n    timeout-minutes: 25' \
  $'    name: Quality - Ubuntu 24.04 / Python 3.11\n    runs-on: ubuntu-24.04\n    timeout-minutes: 25\n    permissions:\n      contents: read' \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  secret-context '          GIT_AUTHOR_NAME: Codex' \
  $'          AUDIT_SECRET: '"\${{ secrets.AUDIT_SECRET }}"$'\n          GIT_AUTHOR_NAME: Codex' \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  bare-secrets '          GIT_AUTHOR_NAME: Codex' \
  $'          AUDIT_SECRETS: '"\${{ toJSON(secrets) }}"$'\n          GIT_AUTHOR_NAME: Codex' \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  bracket-token '          GIT_AUTHOR_NAME: Codex' \
  $'          AUDIT_TOKEN: '"\${{ github['token'] }}"$'\n          GIT_AUTHOR_NAME: Codex' \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  github-context-object \
  $'      - name: Install locked language toolchains\n        shell: bash' \
  $'      - name: Install locked language toolchains\n        env:\n          GITHUB_CONTEXT: '"\${{ toJSON(github) }}"$'\n        shell: bash' \
  "${repository_privilege_diagnostic}"
assert_repository_audit_mutation \
  aggregate-job-continue-on-error \
  $'    timeout-minutes: 5\n    steps:' \
  $'    timeout-minutes: 5\n    continue-on-error: true\n    steps:' \
  "${repository_privilege_diagnostic}"

assert_repository_audit_mutation \
  renamed-job $'  quality-linux:\n' $'  quality-ubuntu:\n' \
  "${repository_graph_diagnostic}"
assert_repository_audit_mutation \
  fourth-job $'\n  repository-audit:\n' \
  $'\n  unexpected:\n    runs-on: ubuntu-24.04\n    steps: []\n\n  repository-audit:\n' \
  "${repository_graph_diagnostic}"
assert_repository_audit_mutation \
  matrix $'    timeout-minutes: 25\n    steps:\n' \
  $'    timeout-minutes: 25\n    strategy:\n      matrix:\n        python: ["3.11"]\n    steps:\n' \
  "${repository_graph_diagnostic}" 2

assert_repository_audit_mutation \
  linux-runner \
  $'    name: Quality - Ubuntu 24.04 / Python 3.11\n    runs-on: ubuntu-24.04' \
  $'    name: Quality - Ubuntu 24.04 / Python 3.11\n    runs-on: ubuntu-22.04' \
  "${repository_runner_diagnostic}"
assert_repository_audit_mutation \
  windows-runner '    runs-on: windows-2025' '    runs-on: windows-2022' \
  "${repository_runner_diagnostic}"
assert_repository_audit_mutation \
  aggregate-runner \
  $'    if: ${{ always() }}\n    runs-on: ubuntu-24.04' \
  $'    if: ${{ always() }}\n    runs-on: ubuntu-22.04' \
  "${repository_runner_diagnostic}"
assert_repository_audit_mutation \
  linux-timeout \
  $'    name: Quality - Ubuntu 24.04 / Python 3.11\n    runs-on: ubuntu-24.04\n    timeout-minutes: 25' \
  $'    name: Quality - Ubuntu 24.04 / Python 3.11\n    runs-on: ubuntu-24.04\n    timeout-minutes: 24' \
  "${repository_runner_diagnostic}"
assert_repository_audit_mutation \
  windows-timeout \
  $'    name: Compatibility - Windows 2025 / Python 3.14\n    runs-on: windows-2025\n    timeout-minutes: 25' \
  $'    name: Compatibility - Windows 2025 / Python 3.14\n    runs-on: windows-2025\n    timeout-minutes: 24' \
  "${repository_runner_diagnostic}"
assert_repository_audit_mutation \
  aggregate-timeout '    timeout-minutes: 5' '    timeout-minutes: 6' \
  "${repository_runner_diagnostic}"

assert_repository_audit_mutation \
  checkout-sha 9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 \
  0000000000000000000000000000000000000000 \
  "${repository_action_diagnostic}" 2
assert_repository_audit_mutation \
  setup-python-sha 5fda3b95a4ea91299a34e894583c3862153e4b97 \
  0000000000000000000000000000000000000000 \
  "${repository_action_diagnostic}" 2
assert_repository_audit_mutation \
  setup-node-sha 820762786026740c76f36085b0efc47a31fe5020 \
  0000000000000000000000000000000000000000 \
  "${repository_action_diagnostic}" 2
assert_repository_audit_mutation \
  action-comment \
  $'          python-version: "3.11"\n      - name: Set up Node\n        # actions/setup-node@v7.0.0' \
  $'          python-version: "3.11"\n      - name: Set up Node\n        # actions/setup-node@v6.3.0' \
  "${repository_action_diagnostic}"
assert_repository_audit_mutation \
  detached-action-comment \
  $'      - name: Checkout repository\n        # actions/checkout@v7.0.0\n        uses:' \
  $'        # actions/checkout@v7.0.0\n      - name: Checkout repository\n        uses:' \
  "${repository_action_diagnostic}" 2
assert_repository_audit_mutation \
  setup-go $'      - name: Install locked language toolchains\n' \
  $'      - name: Set up Go\n        uses: actions/setup-go@4a3601121dd01d1626a1e23e37211e3254c1c06c\n\n      - name: Install locked language toolchains\n' \
  "${repository_action_diagnostic}" 2

assert_repository_audit_mutation \
  persisted-checkout \
  $'          fetch-depth: 0\n          persist-credentials: false\n      - name: Set up Python\n        # actions/setup-python@v7.0.0\n        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97\n        with:\n          python-version: "3.11"' \
  $'          fetch-depth: 0\n          persist-credentials: true\n      - name: Set up Python\n        # actions/setup-python@v7.0.0\n        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97\n        with:\n          python-version: "3.11"' \
  "${repository_checkout_diagnostic}"
assert_repository_audit_mutation \
  shallow-checkout \
  $'          fetch-depth: 0\n          persist-credentials: false\n      - name: Set up Python\n        # actions/setup-python@v7.0.0\n        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97\n        with:\n          python-version: "3.14"' \
  $'          persist-credentials: false\n      - name: Set up Python\n        # actions/setup-python@v7.0.0\n        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97\n        with:\n          python-version: "3.14"' \
  "${repository_checkout_diagnostic}"
assert_repository_audit_mutation \
  forced-ref $'          fetch-depth: 0\n          persist-credentials: false' \
  $'          fetch-depth: 0\n          persist-credentials: false\n          ref: refs/heads/main' \
  "${repository_checkout_diagnostic}" 2

assert_repository_audit_mutation \
  python-linux '          python-version: "3.11"' \
  '          python-version: "3.12"' "${repository_runtime_diagnostic}"
assert_repository_audit_mutation \
  python-windows '          python-version: "3.14"' \
  '          python-version: "3.13"' "${repository_runtime_diagnostic}"
assert_repository_audit_mutation \
  node-registry '  NODE_VERSION: "24.20.0"' \
  '  NODE_VERSION: "24.19.0"' "${repository_runtime_diagnostic}"
assert_repository_audit_mutation \
  node-literal "          node-version: \${{ env.NODE_VERSION }}" \
  '          node-version: "24.20.0"' "${repository_runtime_diagnostic}" 2
assert_repository_audit_mutation \
  cache "          node-version: \${{ env.NODE_VERSION }}" \
  $'          node-version: ${{ env.NODE_VERSION }}\n          cache: npm' \
  "${repository_runtime_diagnostic}" 2

assert_repository_audit_mutation \
  require-hashes $'            --require-hashes \\\n' '' \
  "${repository_dependency_diagnostic}"
assert_repository_audit_mutation \
  dependency-lock '            --requirement tools/quality/requirements.lock' \
  '            --requirement tools/quality/requirements.txt' \
  "${repository_dependency_diagnostic}" 2
assert_repository_audit_mutation \
  npm-scripts 'npm ci --ignore-scripts --prefix tools/quality' \
  'npm ci --prefix tools/quality' "${repository_dependency_diagnostic}" 2
assert_repository_audit_mutation \
  duplicate-install 'npm ci --ignore-scripts --prefix tools/quality' \
  $'npm ci --ignore-scripts --prefix tools/quality\n          npm ci --ignore-scripts --prefix tools/quality' \
  "${repository_dependency_diagnostic}" 2
assert_repository_audit_mutation \
  linux-install-env \
  $'      - name: Install locked language toolchains\n        shell: bash' \
  $'      - name: Install locked language toolchains\n        env:\n          EXTRA_PATH: /tmp\n        shell: bash' \
  "${repository_dependency_diagnostic}"
assert_repository_audit_mutation \
  windows-install-command \
  $'          npm ci --ignore-scripts --prefix tools/quality\n      - name: Install verified PowerShell analyzer' \
  $'          npm ci --ignore-scripts --prefix tools/quality\n          Write-Output unexpected\n      - name: Install verified PowerShell analyzer' \
  "${repository_dependency_diagnostic}"

assert_repository_audit_mutation \
  linux-platform '--platform linux-x64' '--platform macos-x64' \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  linux-install-root \
  "--install-root \"\$RUNNER_TEMP/quality-tools\"" \
  "--install-root \"\$GITHUB_WORKSPACE/quality-tools\"" \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  linux-tool $'            --platform linux-x64 \\\n            --install-root' \
  $'            --platform linux-x64 \\\n            --tool PSScriptAnalyzer \\\n            --install-root' \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  windows-platform '--platform windows-x64' '--platform linux-x64' \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  windows-tool '--tool PSScriptAnalyzer' '--tool actionlint' \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  windows-second-tool \
  $'            --tool PSScriptAnalyzer `\n            --install-root' \
  $'            --tool PSScriptAnalyzer `\n            --tool actionlint `\n            --install-root' \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  windows-equals-second-tool \
  $'            --tool PSScriptAnalyzer `\n            --install-root' \
  $'            --tool PSScriptAnalyzer `\n            --tool=PSScriptAnalyzer `\n            --install-root' \
  "${repository_external_diagnostic}"
# shellcheck disable=SC2016
assert_repository_audit_mutation \
  windows-second-installer \
  '          Add-Content $env:GITHUB_ENV `' \
  $'          python tools/quality/install-external-tools.py `\n            --platform windows-x64 `\n            --install-root "$env:RUNNER_TEMP/quality-tools-extra"\n          Add-Content $env:GITHUB_ENV `' \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  missing-path \
  "          echo \"\$RUNNER_TEMP/quality-tools/bin\" >> \"\$GITHUB_PATH\"" \
  '' "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  missing-linux-module-path \
  "PSModulePath=\$RUNNER_TEMP/quality-tools/Modules:\${PSModulePath:-}" \
  "MODULE_PATH=\$RUNNER_TEMP/quality-tools/Modules:\${PSModulePath:-}" \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  missing-windows-module-path \
  "PSModulePath=\$env:RUNNER_TEMP/quality-tools/Modules\$([IO.Path]::PathSeparator)\$env:PSModulePath" \
  "MODULE_PATH=\$env:RUNNER_TEMP/quality-tools/Modules\$([IO.Path]::PathSeparator)\$env:PSModulePath" \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  windows-literal-separator \
  "PSModulePath=\$env:RUNNER_TEMP/quality-tools/Modules\$([IO.Path]::PathSeparator)\$env:PSModulePath" \
  "PSModulePath=\$env:RUNNER_TEMP/quality-tools/Modules;\$env:PSModulePath" \
  "${repository_external_diagnostic}"
assert_repository_audit_mutation \
  go-install \
  "          echo \"\$RUNNER_TEMP/quality-tools/bin\" >> \"\$GITHUB_PATH\"" \
  "          echo \"\$RUNNER_TEMP/quality-tools/bin\" >> \"\$GITHUB_PATH\"\n          go install \"mvdan.cc/sh/v3/cmd/shfmt@\${SHFMT_VERSION}\"" \
  "${repository_external_diagnostic}"

assert_repository_audit_mutation \
  linux-route 'bash tools/repository-audit.sh full' \
  'bash tools/repository-audit.sh static' "${repository_route_diagnostic}"
assert_repository_audit_mutation \
  linux-route-bypass '        run: bash tools/repository-audit.sh full' \
  '        run: bash tools/repository-audit.sh full || true' \
  "${repository_route_diagnostic}"
assert_repository_audit_mutation \
  linux-continue-on-error '        run: bash tools/repository-audit.sh full' \
  $'        continue-on-error: true\n        run: bash tools/repository-audit.sh full' \
  "${repository_route_diagnostic}"
assert_repository_audit_mutation \
  linux-step-if '        run: bash tools/repository-audit.sh full' \
  $'        if: '"\${{ always() }}"$'\n        run: bash tools/repository-audit.sh full' \
  "${repository_route_diagnostic}"
assert_repository_audit_mutation \
  windows-fast 'bash tools/repository-audit.sh fast' \
  'bash tools/repository-audit.sh full' "${repository_route_diagnostic}"
assert_repository_audit_mutation \
  windows-shell \
  $'      - name: Run cross-platform compatibility checks\n        shell: bash' \
  $'      - name: Run cross-platform compatibility checks\n        shell: pwsh' \
  "${repository_route_diagnostic}"
assert_repository_audit_mutation \
  windows-powershell 'bash tools/repository-audit.sh powershell-static' \
  'bash tools/repository-audit.sh fast' "${repository_route_diagnostic}"
assert_repository_audit_mutation \
  missing-unittest \
  $'      - name: Run the complete Python suite on 3.14\n        shell: pwsh\n        run: python -m unittest discover -s tests -p \'test_*.py\'\n' \
  '' "${repository_route_diagnostic}"

assert_repository_audit_mutation \
  audit-sha '          AUDIT_COMMIT_SHA: >-' '          AUDIT_SHA: >-' \
  "${repository_range_diagnostic}"
assert_repository_audit_mutation \
  release-zero 0000000000000000000000000000000000000000 \
  1111111111111111111111111111111111111111 \
  "${repository_range_diagnostic}"

assert_repository_audit_mutation \
  aggregate-needs '    needs: [quality-linux, compatibility-windows]' \
  '    needs: [quality-linux]' "${repository_aggregate_diagnostic}"
assert_repository_audit_mutation \
  aggregate-always "    if: \${{ always() }}" \
  "    if: \${{ success() }}" "${repository_aggregate_diagnostic}"
assert_repository_audit_mutation \
  aggregate-windows \
  "          WINDOWS_RESULT: \${{ needs.compatibility-windows.result }}" \
  "          WINDOWS_RESULT: \${{ needs.quality-linux.result }}" \
  "${repository_aggregate_diagnostic}"
assert_repository_audit_mutation \
  aggregate-operator \
  "          test \"\$LINUX_RESULT\" = success && test \"\$WINDOWS_RESULT\" = success" \
  "          test \"\$LINUX_RESULT\" = success || test \"\$WINDOWS_RESULT\" = success" \
  "${repository_aggregate_diagnostic}"
assert_repository_audit_mutation \
  aggregate-step-if \
  $'      - name: Require both supported environments\n        env:' \
  $'      - name: Require both supported environments\n        if: '"\${{ always() }}"$'\n        env:' \
  "${repository_aggregate_diagnostic}"

if ((repository_audit_contract_failures > 0)); then
  fail "Repository audit contract accepted ${repository_audit_contract_failures} invalid fixtures"
fi

repository_audit_workflow="${source_root}/.github/workflows/repository-audit.yml"
if ! (
  repository_root="${source_root}"
  cd "${repository_root}"
  check_repository_audit_workflow_contract \
    "${repository_audit_workflow}" "${source_root}/tools/quality/versions.json"
) >"${test_temp}/repository-audit-repository.out" \
  2>"${test_temp}/repository-audit-repository.err"; then
  sed 's/^/  /' "${test_temp}/repository-audit-repository.err" >&2
  fail "Repository audit contract rejected the repository workflow"
fi
# END REPOSITORY AUDIT WORKFLOW TESTS

# BEGIN RELEASE SKILL GUARD TESTS
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
    replace_repository_audit_literal \
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
    'le filtre `push.branches` couvre `codex/release-preflight-*`' \
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

agent_rules_workflow_fixture="${test_temp}/agent-rules-workflow.yml"
cat >"${agent_rules_workflow_fixture}" <<'AGENT_RULES_WORKFLOW'
---
name: Agent rules update

"on":
  release:
    types: [published]
  schedule:
    - cron: "17 5 * * *"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: agent-rules-update
  cancel-in-progress: false

env:
  RULES_REPOSITORY: asphyx0r/agent-coding-rules
  SYNC_BRANCH: automation/agent-rules-update

jobs:
  prepare:
    if: >-
      (
        github.event_name == 'release' ||
        vars.AGENT_RULES_SYNC_ENABLED != 'false'
      ) && (
        github.event_name != 'workflow_dispatch' ||
        github.ref_name == github.event.repository.default_branch
      )
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    permissions:
      contents: read
    outputs:
      changed: ${{ steps.seal.outputs.changed }}
      target_repository: ${{ steps.resolve.outputs.target_repository }}
      target_default_branch: ${{ steps.resolve.outputs.target_default_branch }}
      target_base_commit: ${{ steps.resolve.outputs.target_base_commit }}
      source_ref: ${{ steps.resolve.outputs.source_ref }}
      source_tag_oid: ${{ steps.resolve.outputs.source_tag_oid }}
      source_commit: ${{ steps.resolve.outputs.source_commit }}
    steps:
      - name: Check out target default branch without credentials
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          ref: ${{ github.event.repository.default_branch }}
          fetch-depth: 0
          persist-credentials: false
          path: target
      - name: Set up Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: "3.11"
      - name: Resolve source and target identities
        id: resolve
        working-directory: target
        env:
          GH_TOKEN: ${{ github.token }}
          TARGET_REPOSITORY: ${{ github.repository }}
          TARGET_DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
        run: bash tools/repository-audit/agent-rules-transfer.sh resolve
      - name: Run external synchronization without credentials
        id: external
        working-directory: target
        env:
          SOURCE_REF: ${{ steps.resolve.outputs.source_ref }}
          SOURCE_COMMIT: ${{ steps.resolve.outputs.source_commit }}
        run: |
          env -i PATH=/usr/bin:/bin HOME=/tmp/home TMPDIR=/tmp \
            python ../agent-rules-source/tools/agent-rules-sync.py plan
          env -i PATH=/usr/bin:/bin HOME=/tmp/home TMPDIR=/tmp \
            python ../agent-rules-source/tools/agent-rules-sync.py apply
          env -i PATH=/usr/bin:/bin HOME=/tmp/home TMPDIR=/tmp \
            python ../agent-rules-source/tools/agent-rules-sync.py check
      - name: Seal transfer
        id: seal
        working-directory: target
        env:
          TARGET_REPOSITORY: ${{ steps.resolve.outputs.target_repository }}
          TARGET_BASE_COMMIT: ${{ steps.resolve.outputs.target_base_commit }}
          SOURCE_TAG_OID: ${{ steps.resolve.outputs.source_tag_oid }}
        run: bash tools/repository-audit/agent-rules-transfer.sh seal
      - name: Upload sealed transfer
        if: steps.seal.outputs.changed == 'true'
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: agent-rules-update
          path: |
            ${{ runner.temp }}/agent-rules-transfer/agent-rules.patch
            ${{ runner.temp }}/agent-rules-transfer/agent-rules-plan.json
            ${{ runner.temp }}/agent-rules-transfer/source.json
            ${{ runner.temp }}/agent-rules-transfer/SHA256SUMS
          if-no-files-found: error

  publish:
    needs: prepare
    if: needs.prepare.outputs.changed == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    permissions:
      contents: read
    steps:
      - name: Check out sealed target commit without credentials
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          ref: ${{ needs.prepare.outputs.target_base_commit }}
          fetch-depth: 0
          persist-credentials: false
          path: target
      - name: Download sealed transfer
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c
        with:
          name: agent-rules-update
          path: ${{ runner.temp }}/agent-rules-transfer
      - name: Set up Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: "3.11"
      - name: Prepare and commit before authentication
        id: prepare-publish
        working-directory: target
        env:
          GH_TOKEN: ${{ github.token }}
          TARGET_BASE_COMMIT: ${{ needs.prepare.outputs.target_base_commit }}
          SOURCE_TAG_OID: ${{ needs.prepare.outputs.source_tag_oid }}
        run: bash tools/repository-audit/agent-rules-transfer.sh prepare-publish
      - name: Generate target repository token
        id: target-token
        uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1
        with:
          client-id: ${{ vars.AGENT_RULES_APP_CLIENT_ID }}
          private-key: ${{ secrets.AGENT_RULES_APP_PRIVATE_KEY }}
          owner: ${{ github.repository_owner }}
          repositories: ${{ github.event.repository.name }}
          permission-contents: write
          permission-pull-requests: write
      - name: Push branch and create or update pull request
        working-directory: target
        env:
          GH_TOKEN: ${{ steps.target-token.outputs.token }}
          TARGET_COMMIT: ${{ steps.prepare-publish.outputs.target_commit }}
          SOURCE_REF: ${{ needs.prepare.outputs.source_ref }}
          EXPECTED_REMOTE_OID: >-
            ${{ steps.prepare-publish.outputs.expected_remote_oid }}
          PUSH_REQUIRED: ${{ steps.prepare-publish.outputs.push_required }}
        run: bash tools/repository-audit/agent-rules-transfer.sh publish
AGENT_RULES_WORKFLOW

assert_agent_rules_contract_rejects() {
  local case_name="$1"
  local fixture_path="$2"
  local expected_diagnostic="$3"
  local actual_status

  if (
    # shellcheck disable=SC1090
    source "${dispatcher}"
    repository_root="${source_root}"
    cd "${repository_root}"
    check_agent_rules_update_workflow_contract "${fixture_path}"
  ) >"${test_temp}/${case_name}.out" 2>"${test_temp}/${case_name}.err"; then
    actual_status=0
  else
    actual_status=$?
  fi
  if ((actual_status == 0)); then
    printf '  accepted invalid fixture: %s\n' "${case_name}" >&2
    return 1
  fi
  case "${actual_status}" in
  124 | 129 | 130 | 137 | 143)
    printf '  fixture timed out or was signalled: %s (%s)\n' \
      "${case_name}" "${actual_status}" >&2
    return 1
    ;;
  esac
  if ((actual_status != 1)); then
    printf '  fixture returned %s, expected 1: %s\n' \
      "${actual_status}" "${case_name}" >&2
    return 1
  fi
  if ! grep -Fx -- "${expected_diagnostic}" \
    "${test_temp}/${case_name}.err" >/dev/null; then
    sed 's/^/  /' "${test_temp}/${case_name}.err" >&2
    printf '  fixture missed exact diagnostic: %s\n' \
      "${case_name}" >&2
    return 1
  fi
}

if ! (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  check_agent_rules_update_workflow_contract \
    "${agent_rules_workflow_fixture}"
) >"${test_temp}/agent-rules-valid.out" \
  2>"${test_temp}/agent-rules-valid.err"; then
  sed 's/^/  /' "${test_temp}/agent-rules-valid.err" >&2
  fail "Agent rules workflow contract rejected the valid two-job fixture"
fi

if ! (
  # shellcheck disable=SC1090
  source "${dispatcher}"
  repository_root="${source_root}"
  cd "${repository_root}"
  check_agent_rules_update_workflow_contract
) >"${test_temp}/agent-rules-current.out" \
  2>"${test_temp}/agent-rules-current.err"; then
  sed 's/^/  /' "${test_temp}/agent-rules-current.err" >&2
  fail "Agent rules workflow contract rejected the current workflow"
fi

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

agent_rules_contract_failures=0

sync_guard_fixture="${test_temp}/agent-rules-sync-guard.yml"
sed "s/vars.AGENT_RULES_SYNC_ENABLED != 'false'/true/" \
  "${agent_rules_workflow_fixture}" >"${sync_guard_fixture}"
assert_agent_rules_contract_rejects sync-guard "${sync_guard_fixture}" \
  'Agent rules workflow event guards are incomplete.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

dispatch_guard_fixture="${test_temp}/agent-rules-dispatch-guard.yml"
sed \
  's/github.ref_name == github.event.repository.default_branch/true/' \
  "${agent_rules_workflow_fixture}" >"${dispatch_guard_fixture}"
assert_agent_rules_contract_rejects dispatch-guard \
  "${dispatch_guard_fixture}" \
  'Agent rules workflow event guards are incomplete.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

single_job_fixture="${test_temp}/agent-rules-single-job.yml"
sed '/^  publish:/,$d' \
  "${agent_rules_workflow_fixture}" >"${single_job_fixture}"
assert_agent_rules_contract_rejects single-job "${single_job_fixture}" \
  'Agent rules workflow must contain ordered prepare and publish jobs.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

wrong_order_fixture="${test_temp}/agent-rules-wrong-order.yml"
sed \
  's/agent-rules-transfer\.sh prepare-publish/agent-rules-transfer.sh publish/' \
  "${agent_rules_workflow_fixture}" >"${wrong_order_fixture}"
assert_agent_rules_contract_rejects wrong-order "${wrong_order_fixture}" \
  'Agent rules workflow step order is unsafe.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

external_auth_fixture="${test_temp}/agent-rules-external-token.yml"
sed '/          SOURCE_COMMIT: .*steps.resolve.outputs.source_commit/a\
          GH_TOKEN: ${{ github.token }}' \
  "${agent_rules_workflow_fixture}" >"${external_auth_fixture}"
assert_agent_rules_contract_rejects external-token \
  "${external_auth_fixture}" \
  'Agent rules workflow exposes a token to an unsafe step.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

write_permission_fixture="${test_temp}/agent-rules-write-permission.yml"
sed '0,/  contents: read/s//  contents: write/' \
  "${agent_rules_workflow_fixture}" >"${write_permission_fixture}"
assert_agent_rules_contract_rejects write-permission \
  "${write_permission_fixture}" \
  'Agent rules workflow timeouts or permissions are not minimal.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

prepare_timeout_fixture="${test_temp}/agent-rules-prepare-timeout.yml"
sed '0,/    timeout-minutes: 15/{/    timeout-minutes: 15/d;}' \
  "${agent_rules_workflow_fixture}" >"${prepare_timeout_fixture}"
assert_agent_rules_contract_rejects prepare-timeout \
  "${prepare_timeout_fixture}" \
  'Agent rules workflow timeouts or permissions are not minimal.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

publish_timeout_fixture="${test_temp}/agent-rules-publish-timeout.yml"
sed '/    timeout-minutes: 10/d' \
  "${agent_rules_workflow_fixture}" >"${publish_timeout_fixture}"
assert_agent_rules_contract_rejects publish-timeout \
  "${publish_timeout_fixture}" \
  'Agent rules workflow timeouts or permissions are not minimal.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

agent_checkout_auth_fixture="${test_temp}/agent-rules-credential-checkout.yml"
sed '0,/persist-credentials: false/s//persist-credentials: true/' \
  "${agent_rules_workflow_fixture}" >"${agent_checkout_auth_fixture}"
assert_agent_rules_contract_rejects credential-checkout \
  "${agent_checkout_auth_fixture}" \
  'Agent rules workflow checkouts are not sealed and credential-free.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

moving_checkout_fixture="${test_temp}/agent-rules-moving-checkout.yml"
sed '0,/          ref: /s|          ref: .*|          ref: ${{ github.sha }}|' \
  "${agent_rules_workflow_fixture}" >"${moving_checkout_fixture}"
assert_agent_rules_contract_rejects moving-checkout \
  "${moving_checkout_fixture}" \
  'Agent rules workflow checkouts are not sealed and credential-free.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

unsealed_checkout_fixture="${test_temp}/agent-rules-unsealed-checkout.yml"
sed '0,/needs.prepare.outputs.target_base_commit/s//github.sha/' \
  "${agent_rules_workflow_fixture}" >"${unsealed_checkout_fixture}"
assert_agent_rules_contract_rejects unsealed-checkout \
  "${unsealed_checkout_fixture}" \
  'Agent rules workflow checkouts are not sealed and credential-free.' ||
  agent_rules_contract_failures=$((agent_rules_contract_failures + 1))

if ((agent_rules_contract_failures > 0)); then
  fail "Agent rules workflow contract accepted ${agent_rules_contract_failures} invalid fixtures"
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
if [[ -s "${failure_output}" || -s "${failure_error}" ]]; then
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
guarded_merge_workflow="${source_root}/.github/workflows/guarded-pull-request-merge.yml"
if ! (
  repository_root="${source_root}"
  cd "${repository_root}"
  check_guarded_pull_request_merge_workflow_contract \
    "${guarded_merge_workflow}"
) >"${test_temp}/guarded-merge-valid.out" \
  2>"${test_temp}/guarded-merge-valid.err"; then
  sed 's/^/  /' "${test_temp}/guarded-merge-valid.err" >&2
  fail "valid guarded merge workflow failed its contract"
fi

assert_guarded_merge_contract_rejects() {
  local case_name="$1"
  local fixture_path="$2"
  local expected_diagnostic="$3"
  local actual_status=0
  local expected_error="${test_temp}/${case_name}.expected.err"

  (
    repository_root="${source_root}"
    cd "${repository_root}"
    check_guarded_pull_request_merge_workflow_contract "${fixture_path}"
  ) >"${test_temp}/${case_name}.out" \
    2>"${test_temp}/${case_name}.err" || actual_status=$?
  if ((actual_status == 0)); then
    printf '  accepted invalid fixture: %s\n' "${case_name}" >&2
    return 1
  fi
  if ((actual_status != 1)); then
    printf '  fixture returned %s, expected 1: %s\n' \
      "${actual_status}" "${case_name}" >&2
    return 1
  fi
  printf '%s\n' "${expected_diagnostic}" >"${expected_error}"
  if ! cmp -s "${expected_error}" "${test_temp}/${case_name}.err"; then
    diff -u "${expected_error}" "${test_temp}/${case_name}.err" >&2 || true
    printf '  fixture diagnostic changed: %s\n' "${case_name}" >&2
    return 1
  fi
}

guarded_merge_mutation_root="${test_temp}/guarded-merge-mutations"
mkdir -p "${guarded_merge_mutation_root}"
guarded_merge_contract_failures=0

assert_guarded_merge_mutation() {
  local case_name="$1"
  local old_text="$2"
  local new_text="$3"
  local expected_diagnostic="$4"
  local mutation_path="${guarded_merge_mutation_root}/${case_name}.yml"

  replace_repository_audit_literal \
    "${guarded_merge_workflow}" "${mutation_path}" \
    "${old_text}" "${new_text}"
  assert_guarded_merge_contract_rejects \
    "guarded-merge-${case_name}" "${mutation_path}" \
    "${expected_diagnostic}" ||
    guarded_merge_contract_failures=$((guarded_merge_contract_failures + 1))
}

assert_guarded_merge_mutation \
  trigger-type \
  '    types: [guarded-squash-merge]' \
  '    types: [other]' \
  'Guarded merge workflow trigger contract changed.'
assert_guarded_merge_mutation \
  extra-workflow-dispatch \
  $'    types: [guarded-squash-merge]\n\npermissions:' \
  $'    types: [guarded-squash-merge]\n\n  workflow_dispatch:\n\npermissions:' \
  'Guarded merge workflow trigger contract changed.'
assert_guarded_merge_mutation \
  write-default-permission \
  '  contents: read' \
  '  contents: write' \
  'Guarded merge workflow privilege boundary changed.'
assert_guarded_merge_mutation \
  extra-actions-permission \
  $'  pull-requests: read\n\nconcurrency:' \
  $'  pull-requests: read\n\n  actions: write\n\nconcurrency:' \
  'Guarded merge workflow privilege boundary changed.'
assert_guarded_merge_mutation \
  quoted-job-permission \
  '    name: Validate and squash merge pull request' \
  $'    "permissions":\n      contents: write\n    name: Validate and squash merge pull request' \
  'Guarded merge workflow privilege boundary changed.'
assert_guarded_merge_mutation \
  quoted-on-key \
  $'env:\n  NODE_VERSION: "24.20.0"' \
  $'env:\n  "on": marker\n  NODE_VERSION: "24.20.0"' \
  'Guarded merge workflow trigger contract changed.'
assert_guarded_merge_mutation \
  run-name \
  "run-name: Guarded merge \${{ github.event.client_payload.request_id }}" \
  "run-name: Merge request \${{ github.event.client_payload.request_id }}" \
  'Guarded merge workflow correlation contract changed.'
assert_guarded_merge_mutation \
  cancel-in-progress \
  '  cancel-in-progress: false' \
  '  cancel-in-progress: true' \
  'Guarded merge workflow concurrency contract changed.'
assert_guarded_merge_mutation \
  untrusted-checkout \
  "          ref: \${{ github.sha }}" \
  "          ref: \${{ github.event.client_payload.expected_head_oid }}" \
  'Guarded merge workflow checkout boundary changed.'
assert_guarded_merge_mutation \
  credential-checkout \
  '          persist-credentials: false' \
  '          persist-credentials: true' \
  'Guarded merge workflow checkout boundary changed.'
assert_guarded_merge_mutation \
  install-continue-on-error \
  '      - name: Install locked Commitlint' \
  $'      - name: Install locked Commitlint\n        continue-on-error: true' \
  'Guarded merge workflow runtime contract changed.'
assert_guarded_merge_mutation \
  appended-install-command \
  '        run: npm ci --ignore-scripts --prefix tools/quality' \
  $'        run: |\n          npm ci --ignore-scripts --prefix tools/quality\n          printf unexpected >>tools/merge-pull-request.py' \
  'Guarded merge workflow runtime contract changed.'
assert_guarded_merge_mutation \
  skip-dry-validation \
  "          python tools/merge-pull-request.py --dry-run execute \\" \
  "          python tools/merge-pull-request.py execute \\" \
  'Guarded merge workflow validation order changed.'
assert_guarded_merge_mutation \
  secret-before-dry-validation \
  "          GH_TOKEN: \${{ github.token }}" \
  $'          GH_TOKEN: ${{ github.token }}\n          APP_PRIVATE_KEY: ${{ secrets.AGENT_RULES_APP_PRIVATE_KEY }}' \
  'Guarded merge workflow unprivileged validation changed.'
assert_guarded_merge_mutation \
  broad-app-token \
  '          permission-contents: write' \
  '          permission-contents: administration' \
  'Guarded merge workflow token boundary changed.'
assert_guarded_merge_mutation \
  no-privileged-execution \
  "          python tools/merge-pull-request.py execute \\" \
  "          python tools/merge-pull-request.py --dry-run execute \\" \
  'Guarded merge workflow validation order changed.'
assert_guarded_merge_mutation \
  extra-unnamed-step \
  '    steps:' \
  $'    steps:\n      - run: echo unexpected' \
  'Guarded merge workflow validation order changed.'
assert_guarded_merge_mutation \
  appended-privileged-command \
  $'          python tools/merge-pull-request.py execute \\\n            --event-file "$GITHUB_EVENT_PATH"' \
  $'          python tools/merge-pull-request.py execute \\\n            --event-file "$GITHUB_EVENT_PATH"\n          echo unexpected' \
  'Guarded merge workflow validation order changed.'
assert_guarded_merge_mutation \
  extra-token-repository \
  "            \${{ github.event.repository.name }}" \
  $'            ${{ github.event.repository.name }}\n            other-repository' \
  'Guarded merge workflow token boundary changed.'
assert_guarded_merge_mutation \
  extra-token-input \
  "          owner: \${{ github.repository_owner }}" \
  $'          owner: ${{ github.repository_owner }}\n          skip-token-revoke: true' \
  'Guarded merge workflow token boundary changed.'

if ((guarded_merge_contract_failures > 0)); then
  fail "Guarded merge contract accepted ${guarded_merge_contract_failures} invalid fixtures"
fi
# END GUARDED MERGE WORKFLOW TESTS

space_fixture_root="${test_temp}/copied repository with spaces"
space_tools="${space_fixture_root}/tools"
space_dispatcher="${space_tools}/repository-audit.sh"
mkdir -p "${space_tools}" "${space_fixture_root}/.githooks"
git init -q "${space_fixture_root}"
cp "${dispatcher}" "${space_dispatcher}"
cp -R "${source_root}/tools/repository-audit" \
  "${space_tools}/repository-audit"
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
if [[ "$(cat "${test_temp}/space-fast.out")" != "space-fast|strict" ]]; then
  sed 's/^/  /' "${test_temp}/space-fast.out" >&2
  fail "executed dispatcher did not enable strict mode before its profile"
fi
expected_space_fixture="${test_temp}/copied repository with spaces"
if [[ "${space_fixture_root}" != "${expected_space_fixture}" ]]; then
  fail "refusing to remove unexpected path-with-spaces fixture"
fi
rm -rf -- "${space_fixture_root}"
if [[ -e "${space_fixture_root}" ]]; then
  fail "path-with-spaces fixture cleanup failed"
fi

printf '%s\n' 'PASS: repository audit dispatcher and profiles'
