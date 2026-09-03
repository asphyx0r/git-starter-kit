#!/usr/bin/env bash
# Test overrides are invoked indirectly by sourced hook functions.
# shellcheck disable=SC2329
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(git -C "${script_dir}" rev-parse --show-toplevel)"
dispatcher="${source_root}/tools/repository-audit.sh"
test_temp="$(mktemp -d "${TMPDIR:-/tmp}/quality-hooks-test.XXXXXX")"

cleanup_test() {
  case "$(basename "${test_temp}")" in
  quality-hooks-test.*)
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

initialize_fixture() {
  local fixture_root="$1"

  git init -q "${fixture_root}"
  git -C "${fixture_root}" config user.name "Quality Hook Test"
  git -C "${fixture_root}" config user.email "quality-hook@example.com"
  git -C "${fixture_root}" config core.autocrlf false
}

wrapper_fixture="${test_temp}/wrapper fixture"
mkdir -p "${wrapper_fixture}/.githooks" "${wrapper_fixture}/tools"
initialize_fixture "${wrapper_fixture}"
cp "${source_root}/.githooks/pre-commit" "${wrapper_fixture}/.githooks/pre-commit"
cp "${source_root}/.githooks/commit-msg" "${wrapper_fixture}/.githooks/commit-msg"
cp "${source_root}/.githooks/pre-push" "${wrapper_fixture}/.githooks/pre-push"
cat >"${wrapper_fixture}/tools/repository-audit.sh" <<'DISPATCHER'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$#" >"${QUALITY_WRAPPER_TRACE}.count"
printf '%s\n' "$@" >"${QUALITY_WRAPPER_TRACE}.arguments"
cat >"${QUALITY_WRAPPER_TRACE}.stdin"
exit "${QUALITY_WRAPPER_STATUS}"
DISPATCHER
chmod +x "${wrapper_fixture}/tools/repository-audit.sh"
printf 'test: wrapper\n' >"${wrapper_fixture}/message.txt"

run_wrapper_failure() {
  local hook_name="$1"
  local trace_path="$2"
  shift 2
  local wrapper_status=0

  if (
    cd "${wrapper_fixture}"
    QUALITY_WRAPPER_TRACE="${trace_path}" \
      QUALITY_WRAPPER_STATUS=37 \
      bash ".githooks/${hook_name}" "$@"
  ); then
    fail "${hook_name} wrapper ignored dispatcher failure"
  else
    wrapper_status=$?
  fi
  if ((wrapper_status != 37)); then
    fail "${hook_name} wrapper returned ${wrapper_status} instead of 37"
  fi
}

run_wrapper_failure pre-commit "${test_temp}/pre-commit" "value with spaces"
printf '%s\n' 2 >"${test_temp}/pre-commit.expected-count"
printf '%s\n' hook-pre-commit "value with spaces" \
  >"${test_temp}/pre-commit.expected-arguments"

run_wrapper_failure commit-msg "${test_temp}/commit-msg" \
  "${wrapper_fixture}/message.txt" "value with spaces"
printf '%s\n' 3 >"${test_temp}/commit-msg.expected-count"
printf '%s\n' hook-commit-msg "${wrapper_fixture}/message.txt" \
  "value with spaces" >"${test_temp}/commit-msg.expected-arguments"

pre_push_status=0
if printf '%s\n' 'local-ref local-id remote-ref remote-id' | (
  cd "${wrapper_fixture}"
  QUALITY_WRAPPER_TRACE="${test_temp}/pre-push" \
    QUALITY_WRAPPER_STATUS=37 \
    bash .githooks/pre-push origin "https://example.com/value with spaces"
); then
  fail "pre-push wrapper ignored dispatcher failure"
else
  pre_push_status=$?
fi
if ((pre_push_status != 37)); then
  fail "pre-push wrapper returned ${pre_push_status} instead of 37"
fi
printf '%s\n' 3 >"${test_temp}/pre-push.expected-count"
printf '%s\n' hook-pre-push origin "https://example.com/value with spaces" \
  >"${test_temp}/pre-push.expected-arguments"
printf '%s\n' 'local-ref local-id remote-ref remote-id' \
  >"${test_temp}/pre-push.expected-stdin"

for hook_name in pre-commit commit-msg pre-push; do
  if ! cmp -s \
    "${test_temp}/${hook_name}.expected-count" \
    "${test_temp}/${hook_name}.count"; then
    fail "${hook_name} wrapper changed argument count"
  fi
  if ! cmp -s \
    "${test_temp}/${hook_name}.expected-arguments" \
    "${test_temp}/${hook_name}.arguments"; then
    fail "${hook_name} wrapper changed arguments"
  fi
done
if ! cmp -s \
  "${test_temp}/pre-push.expected-stdin" \
  "${test_temp}/pre-push.stdin"; then
  fail "pre-push wrapper did not forward standard input"
fi

# shellcheck disable=SC1090
source "${dispatcher}"
for hook_function in \
  run_hook_pre_commit \
  run_hook_commit_msg \
  run_hook_pre_push; do
  if ! declare -F "${hook_function}" >/dev/null; then
    fail "shared hook function is missing: ${hook_function}"
  fi
done

trap -p EXIT HUP INT TERM >"${test_temp}/caller-traps.before"
run_hook_pre_commit
run_hook_pre_push </dev/null
trap -p EXIT HUP INT TERM >"${test_temp}/caller-traps.after"
if ! cmp -s \
  "${test_temp}/caller-traps.before" \
  "${test_temp}/caller-traps.after"; then
  fail "hook functions changed caller signal or cleanup traps"
fi

other_hook_timeout_trace="${test_temp}/other-hook-timeout.trace"
: >"${other_hook_timeout_trace}"
printf '%s\n' 'test(hooks): validate message' \
  >"${test_temp}/valid-message.txt"
other_hook_status=0
(
  timeout() {
    printf '%s\n' called >>"${other_hook_timeout_trace}"
    return 99
  }
  run_hook_commitlint() {
    return
  }
  run_hook_pre_commit
  run_hook_commit_msg "${test_temp}/valid-message.txt"
  run_hook_pre_push </dev/null
) || other_hook_status=$?
if ((other_hook_status != 0)); then
  fail "an unrelated hook returned ${other_hook_status} with timeout stubbed"
fi
if [[ -s "${other_hook_timeout_trace}" ]]; then
  fail "pre-commit, commit-msg, or an unaffected pre-push invoked timeout"
fi

affected_root="${test_temp}/affected-root"
affected_bin="${test_temp}/affected-bin"
mkdir -p "${affected_root}/tests" "${affected_bin}"
cat >"${affected_bin}/python" <<'PYTHON'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' python >>"${QUALITY_PY_TRACE}"
exit "${QUALITY_PY_STATUS:-0}"
PYTHON
chmod +x "${affected_bin}/python"
for shell_test in \
  test_repository_audit.sh \
  test_quality_hooks.sh \
  test_commit_message_validation.sh; do
  cat >"${affected_root}/tests/${shell_test}" <<'SHELL_TEST'
#!/usr/bin/env bash
set -euo pipefail

test_name="$(basename "$0")"
printf '%s\n' "${test_name}" >>"${QUALITY_SHELL_TRACE}"
if [[ "${test_name}" == "${QUALITY_FAIL_SHELL_TEST:-}" ]]; then
  exit "${QUALITY_SHELL_STATUS}"
fi
SHELL_TEST
  chmod +x "${affected_root}/tests/${shell_test}"
done

family_timeout_trace="${test_temp}/family-timeout.trace"
export QUALITY_PY_TRACE="${test_temp}/family-python.trace"
export QUALITY_SHELL_TRACE="${test_temp}/family-shell.trace"
: >"${family_timeout_trace}"
: >"${QUALITY_PY_TRACE}"
: >"${QUALITY_SHELL_TRACE}"
(
  timeout() {
    printf '%s|%s|%s\n' "$1" "$2" "$3" >>"${family_timeout_trace}"
    shift 2
    "$@"
  }
  PATH="${affected_bin}:${PATH}" \
    run_hook_affected_tests "${affected_root}" true true
)
cat >"${test_temp}/family-timeout.expected" <<'EOF'
--kill-after=1s|180s|bash
--kill-after=1s|180s|bash
EOF
if ! cmp -s \
  "${test_temp}/family-timeout.expected" \
  "${family_timeout_trace}"; then
  fail "affected Python and shell families did not receive separate 180-second timeouts"
fi

for timed_out_family in python shell; do
  timeout_status=0
  timeout_error="${test_temp}/${timed_out_family}-timeout.err"
  (
    timeout() {
      return 124
    }
    if [[ "${timed_out_family}" == python ]]; then
      PATH="${affected_bin}:${PATH}" \
        run_hook_affected_tests "${affected_root}" true false
    else
      run_hook_affected_tests "${affected_root}" false true
    fi
  ) >"${test_temp}/${timed_out_family}-timeout.out" \
    2>"${timeout_error}" || timeout_status=$?
  if ((timeout_status != 124)); then
    fail "${timed_out_family} timeout returned ${timeout_status} instead of 124"
  fi
  expected_family="${timed_out_family^}"
  assert_file_contains "${timeout_error}" \
    "pre-push: affected ${expected_family} test family timed out after 180 seconds."
done

timeout_137_status=0
(
  timeout() {
    return 137
  }
  run_hook_test_family Python true
) >"${test_temp}/python-timeout-137.out" \
  2>"${test_temp}/python-timeout-137.err" || timeout_137_status=$?
if ((timeout_137_status != 124)); then
  fail "timeout status 137 returned ${timeout_137_status} instead of 124"
fi
assert_file_contains "${test_temp}/python-timeout-137.err" \
  "pre-push: affected Python test family timed out after 180 seconds."

python_timeout_trace="${test_temp}/python-timeout.trace"
: >"${python_timeout_trace}"
: >"${QUALITY_SHELL_TRACE}"
python_timeout_status=0
(
  timeout() {
    printf '%s\n' called >>"${python_timeout_trace}"
    return 124
  }
  PATH="${affected_bin}:${PATH}" \
    run_hook_affected_tests "${affected_root}" true true
) >"${test_temp}/python-timeout.out" \
  2>"${test_temp}/python-timeout.err" || python_timeout_status=$?
if ((python_timeout_status != 124)); then
  fail "Python timeout returned ${python_timeout_status} instead of 124"
fi
if [[ "$(wc -l <"${python_timeout_trace}" | tr -d ' ')" != 1 ]] ||
  [[ -s "${QUALITY_SHELL_TRACE}" ]]; then
  fail "shell family ran after the selected Python family timed out"
fi

missing_timeout_path="${test_temp}/missing-timeout-path"
mkdir -p "${missing_timeout_path}"
missing_timeout_status=0
PATH="${missing_timeout_path}" \
  run_hook_test_family Python true \
  >"${test_temp}/missing-timeout.out" \
  2>"${test_temp}/missing-timeout.err" || missing_timeout_status=$?
if ((missing_timeout_status != 1)); then
  fail "missing timeout command returned ${missing_timeout_status} instead of 1"
fi
assert_file_contains "${test_temp}/missing-timeout.err" \
  "hook: required command not found: timeout"
assert_file_contains "${test_temp}/missing-timeout.err" \
  "Install required timeout and ensure it is on PATH."

for failed_shell_position in 1 2 3; do
  shell_call_trace="${test_temp}/shell-${failed_shell_position}.trace"
  : >"${shell_call_trace}"
  shell_failure_status=$((46 + failed_shell_position))
  failed_shell_test="$(
    sed -n "${failed_shell_position}p" <<'EOF'
test_repository_audit.sh
test_quality_hooks.sh
test_commit_message_validation.sh
EOF
  )"
  affected_shell_status=0
  (
    timeout() {
      shift 2
      "$@"
    }
    QUALITY_SHELL_TRACE="${shell_call_trace}" \
      QUALITY_FAIL_SHELL_TEST="${failed_shell_test}" \
      QUALITY_SHELL_STATUS="${shell_failure_status}" \
      run_hook_affected_tests "${affected_root}" false true
  ) || affected_shell_status=$?
  if ((affected_shell_status != shell_failure_status)); then
    fail "shell test ${failed_shell_position} returned ${affected_shell_status} instead of ${shell_failure_status}"
  fi
  if [[ "$(wc -l <"${shell_call_trace}" | tr -d ' ')" != "${failed_shell_position}" ]]; then
    fail "shell test ${failed_shell_position} did not short-circuit"
  fi
done

for zero_object_id in \
  0000000000000000000000000000000000000000 \
  0000000000000000000000000000000000000000000000000000000000000000; do
  if ! is_hook_zero_object_id "${zero_object_id}"; then
    fail "all-zero object ID was not recognized: ${zero_object_id}"
  fi
done
for nonzero_object_id in '' 0000000000000000000000000000000000000001; do
  if is_hook_zero_object_id "${nonzero_object_id}"; then
    fail "non-zero object ID was treated as the zero sentinel"
  fi
done

test_object_ids=()
test_python_flags=()
test_shell_flags=()
merge_hook_test_update abc123 true false
merge_hook_test_update abc123 true false
if ((${#test_object_ids[@]} != 1)) ||
  [[ "${test_python_flags[0]}" != true ]] ||
  [[ "${test_shell_flags[0]}" != false ]]; then
  fail "identical object ID flags were not deduplicated"
fi
merge_hook_test_update abc123 false true
if ((${#test_object_ids[@]} != 1)) ||
  [[ "${test_python_flags[0]}" != true ]] ||
  [[ "${test_shell_flags[0]}" != true ]]; then
  fail "complementary object ID flags were not merged"
fi

assert_hook_path_flags() {
  local path="$1"
  local expected_python="$2"
  local expected_shell="$3"
  local run_python=false
  local run_shell=false

  classify_hook_push_path "${path}"
  if [[ "${run_python}" != "${expected_python}" ||
    "${run_shell}" != "${expected_shell}" ]]; then
    fail "unexpected affected-test flags for ${path}: ${run_python}/${run_shell}"
  fi
}

assert_hook_path_flags 'space file.py' true false
assert_hook_path_flags tools/quality/requirements.lock true false
assert_hook_path_flags tools/quality/PSScriptAnalyzerSettings.psd1 true false
assert_hook_path_flags tools/quality/yamllint.yaml true false
assert_hook_path_flags tools/quality/package-lock.json true true
assert_hook_path_flags .codespellrc true false
assert_hook_path_flags commitlint.config.cjs false true
assert_hook_path_flags .markdownlint-cli2.yaml false true
assert_hook_path_flags candidate.txt false false

if grep -E 'git .*clean|git -C .*clean' \
  "${source_root}/tools/repository-audit/hooks.sh" >/dev/null; then
  fail "pre-push still uses git clean"
fi

missing_command_path="${test_temp}/missing-command-path"
mkdir -p "${missing_command_path}"
if PATH="${missing_command_path}" resolve_hook_command system node node.exe \
  >"${test_temp}/missing-node.out" 2>"${test_temp}/missing-node.err"; then
  fail "node resolver accepted a missing command"
fi
assert_file_contains "${test_temp}/missing-node.err" \
  "Install required node and ensure it is on PATH."
if grep -F "pinned node" "${test_temp}/missing-node.err" >/dev/null; then
  fail "node diagnostic incorrectly described Node as registry-pinned"
fi
if PATH="${missing_command_path}" \
  resolve_hook_command system shellcheck shellcheck.exe \
  >"${test_temp}/missing-shellcheck.out" \
  2>"${test_temp}/missing-shellcheck.err"; then
  fail "ShellCheck resolver accepted a missing command"
fi
assert_file_contains "${test_temp}/missing-shellcheck.err" \
  "Install required shellcheck and ensure it is on PATH."
if grep -F "pinned shellcheck" \
  "${test_temp}/missing-shellcheck.err" >/dev/null; then
  fail "ShellCheck diagnostic incorrectly described it as registry-pinned"
fi
if PATH="${missing_command_path}" resolve_hook_command python ruff ruff.exe \
  >"${test_temp}/missing-ruff.out" 2>"${test_temp}/missing-ruff.err"; then
  fail "Ruff resolver accepted a missing command"
fi
assert_file_contains "${test_temp}/missing-ruff.err" \
  "python -m pip install --require-hashes --requirement tools/quality/requirements.lock"
if PATH="${missing_command_path}" resolve_hook_command registry shfmt shfmt.exe \
  >"${test_temp}/missing-shfmt.out" 2>"${test_temp}/missing-shfmt.err"; then
  fail "shfmt resolver accepted a missing command"
fi
assert_file_contains "${test_temp}/missing-shfmt.err" \
  "Install the pinned shfmt version declared in tools/quality/versions.json."

staged_fixture="${test_temp}/staged fixture"
mkdir -p "${staged_fixture}"
initialize_fixture "${staged_fixture}"
mkdir -p "${staged_fixture}/tools/quality"
cp "${source_root}/commitlint.config.cjs" \
  "${staged_fixture}/commitlint.config.cjs"
printf '%s\n' '# fixture quality checker' \
  >"${staged_fixture}/tools/quality/check-versions.py"
printf '%s\n' 'fixture==1.0' \
  >"${staged_fixture}/tools/quality/requirements.lock"
printf 'base\n' >"${staged_fixture}/base.txt"
git -C "${staged_fixture}" add base.txt
git -C "${staged_fixture}" add commitlint.config.cjs tools/quality
git -C "${staged_fixture}" commit -q -m "test: initialize fixture"

initialize_repository_root() {
  repository_root="${staged_fixture}"
  cd "${repository_root}"
}
initialize_repository_root

empty_output="${test_temp}/empty.out"
empty_error="${test_temp}/empty.err"
if ! run_hook_pre_commit >"${empty_output}" 2>"${empty_error}"; then
  fail "pre-commit no-change fast path failed"
fi
if [[ -s "${empty_output}" || -s "${empty_error}" ]]; then
  fail "pre-commit no-change fast path emitted output"
fi

quality_bin="${test_temp}/quality-bin"
mkdir -p "${quality_bin}"
cat >"${quality_bin}/markdownlint-cli2" <<'MARKDOWNLINT'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$@" >"${QUALITY_MARKDOWN_TRACE}.arguments"
cat -- "${@: -1}" >"${QUALITY_MARKDOWN_TRACE}.content"
MARKDOWNLINT
chmod +x "${quality_bin}/markdownlint-cli2"

printf 'staged value\n' >"${staged_fixture}/document.md"
git -C "${staged_fixture}" add document.md
printf 'unstaged value\n' >"${staged_fixture}/document.md"
before_hash="$(git -C "${staged_fixture}" hash-object document.md)"
PATH="${quality_bin}:${PATH}" \
  QUALITY_MARKDOWN_TRACE="${test_temp}/markdown" \
  run_hook_pre_commit
after_hash="$(git -C "${staged_fixture}" hash-object document.md)"
if [[ "${before_hash}" != "${after_hash}" ]]; then
  fail "pre-commit modified the working tree"
fi
printf 'staged value\n' >"${test_temp}/markdown.expected-content"
if ! cmp -s \
  "${test_temp}/markdown.expected-content" \
  "${test_temp}/markdown.content"; then
  fail "pre-commit linted working-tree content instead of staged content"
fi
assert_file_contains "${test_temp}/markdown.arguments" "./document.md"

git -C "${staged_fixture}" reset -q --hard HEAD
cat >"${quality_bin}/ruff" <<'RUFF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${QUALITY_RUFF_TRACE}"
RUFF
cat >"${quality_bin}/mypy" <<'MYPY'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >"${QUALITY_MYPY_TRACE}"
MYPY
chmod +x "${quality_bin}/ruff" "${quality_bin}/mypy"
printf 'print("candidate")\n' >"${staged_fixture}/tools/candidate.py"
git -C "${staged_fixture}" add tools/candidate.py
export QUALITY_RUFF_TRACE="${test_temp}/ruff.arguments"
export QUALITY_MYPY_TRACE="${test_temp}/mypy.arguments"
PATH="${quality_bin}:${PATH}" run_hook_pre_commit
cat >"${test_temp}/ruff.expected" <<'RUFF_EXPECTED'
check --config tools/quality/pyproject.toml ./tools/candidate.py
format --check --config tools/quality/pyproject.toml ./tools/candidate.py
RUFF_EXPECTED
if ! cmp -s "${test_temp}/ruff.expected" "${QUALITY_RUFF_TRACE}"; then
  diff -u "${test_temp}/ruff.expected" "${QUALITY_RUFF_TRACE}" >&2 || true
  fail "pre-commit Python format or lint arguments changed"
fi
assert_file_contains "${QUALITY_MYPY_TRACE}" \
  "--config-file tools/quality/pyproject.toml ./tools/candidate.py"

git -C "${staged_fixture}" reset -q --hard HEAD
printf 'staged value\n' >"${staged_fixture}/document.md"
git -C "${staged_fixture}" add document.md
minimal_path="$(dirname "$(command -v git)"):/usr/bin:/bin"
missing_error="${test_temp}/missing.err"
if PATH="${minimal_path}" run_hook_pre_commit \
  >"${test_temp}/missing.out" 2>"${missing_error}"; then
  fail "pre-commit accepted a staged Markdown file without locked tooling"
fi
assert_file_contains "${missing_error}" \
  "npm ci --ignore-scripts --prefix tools/quality"

git -C "${staged_fixture}" reset -q --hard HEAD
cat >"${quality_bin}/node" <<'NODE'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == --check ]]
NODE
cat >"${quality_bin}/commitlint" <<'COMMITLINT'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >"${QUALITY_COMMITLINT_TRACE}.arguments"
config_path=''
while (($#)); do
  if [[ "$1" == --config ]]; then
    config_path="$2"
    break
  fi
  shift
done
[[ -n "${config_path}" ]]
cat "${config_path}" >"${QUALITY_COMMITLINT_TRACE}.content"
COMMITLINT
chmod +x "${quality_bin}/node" "${quality_bin}/commitlint"
printf '\n// staged-commitlint-marker\n' \
  >>"${staged_fixture}/commitlint.config.cjs"
git -C "${staged_fixture}" add commitlint.config.cjs
printf '// unstaged-commitlint-marker\n' \
  >>"${staged_fixture}/commitlint.config.cjs"
export QUALITY_COMMITLINT_TRACE="${test_temp}/commitlint"
PATH="${quality_bin}:${PATH}" run_hook_pre_commit
grep -Fx '// staged-commitlint-marker' \
  "${QUALITY_COMMITLINT_TRACE}.content" >/dev/null ||
  fail "Commitlint did not read the staged configuration"
if grep -F 'unstaged-commitlint-marker' \
  "${QUALITY_COMMITLINT_TRACE}.content" >/dev/null; then
  fail "Commitlint read the unstaged configuration"
fi
assert_file_contains "${QUALITY_COMMITLINT_TRACE}.arguments" \
  "--print-config"
assert_file_contains "${QUALITY_COMMITLINT_TRACE}.arguments" \
  "--cwd"

git -C "${staged_fixture}" reset -q --hard HEAD
cat >"${quality_bin}/python" <<'PYTHON'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >"${QUALITY_DECLARATION_TRACE}.arguments"
PYTHON
chmod +x "${quality_bin}/python"
git -C "${staged_fixture}" rm -q tools/quality/requirements.lock
export QUALITY_DECLARATION_TRACE="${test_temp}/declarations"
PATH="${quality_bin}:${PATH}" run_hook_pre_commit
if [[ ! -s "${QUALITY_DECLARATION_TRACE}.arguments" ]]; then
  fail "quality declaration deletion did not run the staged checker"
fi

git -C "${staged_fixture}" reset -q --hard HEAD
printf 'candidate\n' >"${staged_fixture}/notes.txt"
git -C "${staged_fixture}" add notes.txt
git -C "${staged_fixture}" commit -q -m "test: add unaffected file"
local_object_id="$(git -C "${staged_fixture}" rev-parse HEAD)"
remote_object_id="$(git -C "${staged_fixture}" rev-parse HEAD^)"
if ! printf 'refs/heads/main %s refs/heads/main %s\n' \
  "${local_object_id}" "${remote_object_id}" | run_hook_pre_push origin example \
  >"${test_temp}/push-no-change.out" 2>"${test_temp}/push-no-change.err"; then
  fail "pre-push no-change fast path failed"
fi
[[ ! -s "${test_temp}/push-no-change.out" ]] ||
  fail "pre-push no-change fast path emitted stdout"
[[ ! -s "${test_temp}/push-no-change.err" ]] ||
  fail "pre-push no-change fast path emitted stderr"

printf 'print("candidate")\n' >"${staged_fixture}/candidate.py"
git -C "${staged_fixture}" add candidate.py
git -C "${staged_fixture}" commit -q -m "test: add Python file"
python_object_id="$(git -C "${staged_fixture}" rev-parse HEAD)"
python_parent_id="$(git -C "${staged_fixture}" rev-parse HEAD^)"
cat >"${quality_bin}/python" <<'PYTHON'
#!/usr/bin/env bash
exit 41
PYTHON
chmod +x "${quality_bin}/python"
push_failure_status=0
if printf 'refs/heads/main %s refs/heads/main %s\n' \
  "${python_object_id}" "${python_parent_id}" |
  PATH="${quality_bin}:${PATH}" run_hook_pre_push origin example \
    >"${test_temp}/push-failure.out" 2>"${test_temp}/push-failure.err"; then
  fail "pre-push ignored an affected Python test failure"
else
  push_failure_status=$?
fi
if ((push_failure_status != 41)); then
  fail "pre-push returned ${push_failure_status} instead of 41"
fi

printf '%s\n' 'PASS: locked quality hook behavior'
