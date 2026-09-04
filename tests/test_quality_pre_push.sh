#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(git -C "${script_dir}" rev-parse --show-toplevel)"
test_temp="$(mktemp -d "${TMPDIR:-/tmp}/quality-pre-push.XXXXXX")"

cleanup_test() {
  case "${test_temp}" in
  "${TMPDIR:-/tmp}"/quality-pre-push.*)
    rm -rf -- "${test_temp}"
    ;;
  *)
    printf 'Refusing to remove unexpected test path: %s\n' "${test_temp}" >&2
    return 1
    ;;
  esac
}

trap cleanup_test EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

require_test_command() {
  command -v "$1" >/dev/null 2>&1 ||
    fail "required command not found: $1"
}

require_test_command git
require_test_command timeout
test_timeout_cmd="$(command -v timeout)"
integration_timeout_seconds=60

fixture="${test_temp}/source repository"
git init -q "${fixture}"
git -C "${fixture}" config user.name "Pre-push Test"
git -C "${fixture}" config user.email "pre-push@example.com"
git -C "${fixture}" config core.autocrlf false
mkdir -p "${fixture}/tests" "${fixture}/tools/quality"
cat >"${fixture}/tests/test_oid_marker.py" <<'PYTHON_TEST'
import os
import subprocess
import unittest


class PushedOidTest(unittest.TestCase):
    def test_runs_from_checked_out_oid(self):
        oid = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        with open(os.environ["QUALITY_PY_TRACE"], "a", encoding="utf-8") as stream:
            stream.write(f"{oid}\n")
PYTHON_TEST
for test_name in \
  test_repository_audit.sh \
  test_quality_hooks.sh \
  test_commit_message_validation.sh; do
  cat >"${fixture}/tests/${test_name}" <<'SHELL_TEST'
#!/usr/bin/env bash
set -euo pipefail

current_oid="$(git rev-parse HEAD)"
quality-local-probe
if [[ "${current_oid}" == "${QUALITY_POISON_OID:-}" && \
  "$(basename "$0")" == test_repository_audit.sh ]]; then
  git config core.worktree "${QUALITY_FIXTURE}"
fi
printf '%s|%s\n' "$(basename "$0")" "${current_oid}" \
  >>"${QUALITY_SHELL_TRACE}"
SHELL_TEST
  chmod +x "${fixture}/tests/${test_name}"
done
cat >"${fixture}/tools/release-artifacts.py" <<'RELEASE_TOOL'
# Fixture path consumed by the pre-push release validator.
RELEASE_TOOL
printf '%s\n' 'fixture==1.0' >"${fixture}/tools/quality/requirements.lock"
printf '%s\n' '{}' >"${fixture}/tools/quality/package-lock.json"
printf '%s\n' 'module.exports = {};' >"${fixture}/commitlint.config.cjs"
printf '%s\n' '[codespell]' >"${fixture}/.codespellrc"
printf 'base\n' >"${fixture}/base.txt"
git -C "${fixture}" add .
git -C "${fixture}" commit -q -m "test: initialize pushed oid fixture"
base_oid="$(git -C "${fixture}" rev-parse HEAD)"
git -C "${fixture}" branch -m main

git -C "${fixture}" switch -q -c python-branch
printf 'print("ancestor")\n' >"${fixture}/ancestor.py"
git -C "${fixture}" add ancestor.py
git -C "${fixture}" commit -q -m "test: add Python ancestor"
printf 'tip\n' >"${fixture}/tip.txt"
git -C "${fixture}" add tip.txt
git -C "${fixture}" commit -q -m "test: add Python branch tip"
python_oid="$(git -C "${fixture}" rev-parse HEAD)"

git -C "${fixture}" switch -q -c shell-branch "${base_oid}"
printf '#!/usr/bin/env bash\n:\n' >"${fixture}/candidate.sh"
git -C "${fixture}" add candidate.sh
git -C "${fixture}" commit -q -m "test: add shell candidate"
shell_oid="$(git -C "${fixture}" rev-parse HEAD)"

git -C "${fixture}" switch -q -c shell-clean-branch "${base_oid}"
printf '#!/usr/bin/env bash\n:\n' >"${fixture}/clean-candidate.sh"
git -C "${fixture}" add clean-candidate.sh
git -C "${fixture}" commit -q -m "test: add second shell candidate"
shell_clean_oid="$(git -C "${fixture}" rev-parse HEAD)"

git -C "${fixture}" switch -q -c rename-branch "${base_oid}"
printf 'print("rename")\n' >"${fixture}/renamed.py"
git -C "${fixture}" add renamed.py
git -C "${fixture}" commit -q -m "test: add rename source"
rename_base_oid="$(git -C "${fixture}" rev-parse HEAD)"
git -C "${fixture}" mv renamed.py renamed.txt
git -C "${fixture}" commit -q -m "test: rename Python away"
rename_oid="$(git -C "${fixture}" rev-parse HEAD)"

git -C "${fixture}" switch -q -c delete-branch "${base_oid}"
printf '#!/usr/bin/env bash\n:\n' >"${fixture}/deleted.sh"
git -C "${fixture}" add deleted.sh
git -C "${fixture}" commit -q -m "test: add deleted shell source"
delete_base_oid="$(git -C "${fixture}" rev-parse HEAD)"
git -C "${fixture}" rm -q deleted.sh
git -C "${fixture}" commit -q -m "test: delete shell source"
delete_oid="$(git -C "${fixture}" rev-parse HEAD)"

git -C "${fixture}" switch -q -c new-branch "${base_oid}"
printf '#!/usr/bin/env bash\n:\n' >"${fixture}/new-ancestor.sh"
git -C "${fixture}" add new-ancestor.sh
git -C "${fixture}" commit -q -m "test: add new branch ancestor"
printf 'tip\n' >"${fixture}/new-tip.txt"
git -C "${fixture}" add new-tip.txt
git -C "${fixture}" commit -q -m "test: add new branch tip"
new_oid="$(git -C "${fixture}" rev-parse HEAD)"

git -C "${fixture}" switch -q main

local_quality_bin="${fixture}/tools/quality/node_modules/.bin"
mkdir -p "${local_quality_bin}"
cat >"${local_quality_bin}/quality-local-probe" <<'LOCAL_PROBE'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' local >>"${QUALITY_LOCAL_DEPENDENCY_TRACE}"
LOCAL_PROBE
chmod +x "${local_quality_bin}/quality-local-probe"

runner="${test_temp}/run-pre-push.sh"
cat >"${runner}" <<'RUNNER'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${QUALITY_HARNESS_HANG:-false}" == true ]]; then
  sleep 30 &
  printf '%s\n' "$!" >"${QUALITY_HARNESS_CHILD_PID}"
  wait
fi

# shellcheck disable=SC1090
source "${QUALITY_DISPATCHER}"
repository_root="${QUALITY_FIXTURE}"
cd "${repository_root}"
if [[ -n "${QUALITY_DISCOVERY_STATUS:-}" ]]; then
  list_hook_push_changes() {
    return "${QUALITY_DISCOVERY_STATUS}"
  }
fi
if [[ "${QUALITY_STUB_AFFECTED_TESTS:-false}" == true ]]; then
  run_hook_affected_tests() {
    local pushed_oid
    pushed_oid="$(git -C "$1" rev-parse HEAD)"
    git -C "$1" remote get-url origin >>"${QUALITY_REMOTE_TRACE}"
    printf '%s|%s|%s\n' "$2" "$3" "${pushed_oid}" \
      >>"${QUALITY_AFFECTED_TRACE}"
    if [[ "$2" == true ]]; then
      printf '%s\n' "${pushed_oid}" >>"${QUALITY_PY_TRACE}"
    fi
    if [[ "$3" == true ]]; then
      if [[ "${QUALITY_REQUIRE_LOCAL_PROBE:-false}" == true ]]; then
        quality-local-probe || return
      fi
      for shell_test in \
        test_repository_audit.sh \
        test_quality_hooks.sh \
        test_commit_message_validation.sh; do
        printf '%s|%s\n' "${shell_test}" "${pushed_oid}" \
          >>"${QUALITY_SHELL_TRACE}"
      done
      if [[ "${pushed_oid}" == "${QUALITY_POISON_OID:-}" ]]; then
        git -C "$1" config core.worktree "${QUALITY_FIXTURE}"
      fi
    fi
  }
fi
run_hook_pre_push "$@"
RUNNER
chmod +x "${runner}"

run_pre_push_bounded() {
  local timeout_seconds="$1"
  local input_path="$2"
  shift 2
  local run_status=0
  (
    set -m
    "${test_timeout_cmd}" --kill-after=3s "${timeout_seconds}s" \
      bash "${runner}" "$@" <"${input_path}"
  ) || run_status=$?
  if ((run_status == 124 || run_status == 137)); then
    fail "pre-push invocation exceeded ${timeout_seconds} seconds"
  fi
  return "${run_status}"
}

git_bin="${test_temp}/git-bin"
mkdir -p "${git_bin}"
real_git="$(command -v git)"
cat >"${git_bin}/git" <<'GIT_WRAPPER'
#!/usr/bin/env bash
set -euo pipefail

for argument in "$@"; do
  if [[ "${argument}" == checkout ]]; then
    printf '%s\n' checkout >>"${QUALITY_CHECKOUT_TRACE}"
    [[ "$*" == *--git-dir=* && "$*" == *--work-tree=* ]] || exit 86
    break
  fi
done
if [[ "${1:-}" != clone ]]; then
  exec "${QUALITY_REAL_GIT}" "$@"
fi
printf '%s\n' clone >>"${QUALITY_CLONE_TRACE}"
printf '%s\n' "${@: -1}" >>"${QUALITY_CLONE_DESTINATION_TRACE}"
if [[ "${GIT_ALLOW_PROTOCOL:-}" != file ]]; then
  printf '%s\n' 'pre-push clone did not restrict Git to the file protocol' >&2
  exit 84
fi
has_local_flag=false
for argument in "$@"; do
  if [[ "${argument}" == --local ]]; then
    has_local_flag=true
    break
  fi
done
if [[ "${has_local_flag}" != true ]]; then
  printf '%s\n' 'pre-push clone was not explicitly local' >&2
  exit 85
fi
"${QUALITY_REAL_GIT}" "$@"
command_status=$?
if [[ "${QUALITY_REDIRECT_CLONE_GIT_DIR:-false}" == true ]] &&
  ((command_status == 0)); then
  clone_destination="${@: -1}"
  redirected_git_dir="${clone_destination}.redirected-git"
  mv "${clone_destination}/.git" "${redirected_git_dir}"
  printf 'gitdir: %s\n' "${redirected_git_dir}" \
    >"${clone_destination}/.git"
  printf '%s\n' "${redirected_git_dir}" \
    >>"${QUALITY_REDIRECTED_GIT_DIR_TRACE}"
fi
if [[ "${QUALITY_SIGNAL_ON_CLONE:-false}" == true ]] &&
  ((command_status == 0)); then
  kill -TERM "${PPID}"
fi
exit "${command_status}"
GIT_WRAPPER
chmod +x "${git_bin}/git"

export QUALITY_DISPATCHER="${source_root}/tools/repository-audit.sh"
export QUALITY_FIXTURE="${fixture}"
export QUALITY_PY_TRACE="${test_temp}/python.trace"
export QUALITY_SHELL_TRACE="${test_temp}/shell.trace"
export QUALITY_LOCAL_DEPENDENCY_TRACE="${test_temp}/local-dependency.trace"
export QUALITY_CLONE_TRACE="${test_temp}/clone.trace"
export QUALITY_CLONE_DESTINATION_TRACE="${test_temp}/clone-destination.trace"
export QUALITY_CHECKOUT_TRACE="${test_temp}/checkout.trace"
export QUALITY_REMOTE_TRACE="${test_temp}/remote.trace"
export QUALITY_REDIRECTED_GIT_DIR_TRACE="${test_temp}/redirected-git-dir.trace"
export QUALITY_REAL_GIT="${real_git}"
export QUALITY_POISON_OID="${shell_oid}"
export QUALITY_STUB_AFFECTED_TESTS=true
export QUALITY_AFFECTED_TRACE="${test_temp}/affected.trace"
export QUALITY_REQUIRE_LOCAL_PROBE=true
export PATH="${git_bin}:${PATH}"

git_reported_root="$(git -C "${fixture}" rev-parse --show-toplevel)"
git_reported_root_updates="${test_temp}/git-reported-root.updates"
printf 'refs/heads/shell-clean %s refs/heads/shell-clean %s\n' \
  "${shell_clean_oid}" "${base_oid}" >"${git_reported_root_updates}"
: >"${QUALITY_LOCAL_DEPENDENCY_TRACE}"
export QUALITY_FIXTURE="${git_reported_root}"
run_pre_push_bounded "${integration_timeout_seconds}" \
  "${git_reported_root_updates}" origin local ||
  fail "pre-push could not use local dependencies from Git-reported root"
export QUALITY_FIXTURE="${fixture}"
if [[ "$(cat "${QUALITY_LOCAL_DEPENDENCY_TRACE}")" != local ]]; then
  fail "Git-reported root did not resolve the source-local dependency"
fi
if [[ "${QUALITY_GIT_REPORTED_ROOT_ONLY:-false}" == true ]]; then
  printf '%s\n' 'PASS: Git-reported root resolves source-local dependencies'
  exit
fi

harness_child_pid_path="${test_temp}/harness-child.pid"
harness_timeout_status=0
(
  fail() {
    return 1
  }
  QUALITY_HARNESS_HANG=true \
    QUALITY_HARNESS_CHILD_PID="${harness_child_pid_path}" \
    run_pre_push_bounded 1 /dev/null origin local
) >"${test_temp}/harness-timeout.out" \
  2>"${test_temp}/harness-timeout.err" || harness_timeout_status=$?
if ((harness_timeout_status != 124)); then
  fail "bounded harness returned ${harness_timeout_status} instead of 124"
fi
harness_child_pid="$(cat "${harness_child_pid_path}")"
[[ "${harness_child_pid}" =~ ^[1-9][0-9]*$ ]] ||
  fail "bounded harness did not record a valid descendant PID"
harness_child_stopped=false
for _ in {1..20}; do
  if ! kill -0 "${harness_child_pid}" 2>/dev/null; then
    harness_child_stopped=true
    break
  fi
  sleep 0.1
done
if [[ "${harness_child_stopped}" != true ]]; then
  kill "${harness_child_pid}" 2>/dev/null || true
  fail "bounded harness left descendant ${harness_child_pid} running"
fi

source_sentinel="${fixture}/pre-push-source-sentinel.txt"
printf '%s\n' 'must survive poisoned clone configuration' >"${source_sentinel}"

combined_updates="${test_temp}/combined.updates"
{
  printf 'refs/heads/shell %s refs/heads/shell %s\n' \
    "${shell_oid}" "${base_oid}"
  printf 'refs/heads/shell-copy %s refs/heads/shell-copy %s\n' \
    "${shell_oid}" "${base_oid}"
  printf 'refs/heads/shell-clean %s refs/heads/shell-clean %s\n' \
    "${shell_clean_oid}" "${base_oid}"
  printf 'refs/heads/rename %s refs/heads/rename %s\n' \
    "${rename_oid}" "${rename_base_oid}"
  printf 'refs/heads/delete %s refs/heads/delete %s\n' \
    "${delete_oid}" "${delete_base_oid}"
  printf 'refs/heads/new %s refs/heads/new %s\n' \
    "${new_oid}" '0000000000000000000000000000000000000000'
} >"${combined_updates}"

source_status_before="$(git -C "${fixture}" status --porcelain --untracked-files=all)"
: >"${QUALITY_PY_TRACE}"
: >"${QUALITY_SHELL_TRACE}"
: >"${QUALITY_LOCAL_DEPENDENCY_TRACE}"
: >"${QUALITY_CLONE_TRACE}"
: >"${QUALITY_CLONE_DESTINATION_TRACE}"
: >"${QUALITY_CHECKOUT_TRACE}"
: >"${QUALITY_REMOTE_TRACE}"
: >"${QUALITY_AFFECTED_TRACE}"
run_pre_push_bounded 120 "${combined_updates}" origin local
source_status_after="$(git -C "${fixture}" status --porcelain --untracked-files=all)"
if [[ "${source_status_after}" != "${source_status_before}" ]]; then
  fail "pre-push mutated its source repository"
fi
if [[ "$(git -C "${fixture}" rev-parse HEAD)" != "${base_oid}" ]]; then
  fail "pre-push changed the source repository checkout"
fi
if [[ ! -f "${source_sentinel}" ]]; then
  fail "a poisoned clone configuration removed the source sentinel"
fi
if [[ "$(wc -l <"${QUALITY_CLONE_TRACE}" | tr -d ' ')" != 5 ]]; then
  fail "pre-push did not create one clone per distinct selected object ID"
fi
if [[ "$(wc -l <"${QUALITY_CHECKOUT_TRACE}" | tr -d ' ')" != 5 ]]; then
  fail "pre-push did not anchor checkout for every distinct selected object ID"
fi
if [[ "$(wc -l <"${QUALITY_REMOTE_TRACE}" | tr -d ' ')" != 5 ]] ||
  grep -Fvx 'local' "${QUALITY_REMOTE_TRACE}" >/dev/null; then
  fail "pre-push clone origin did not match the pushed remote URL"
fi
while IFS= read -r normal_clone_destination; do
  if [[ -e "${normal_clone_destination}" ]]; then
    fail "successful pre-push leaked a temporary clone"
  fi
done <"${QUALITY_CLONE_DESTINATION_TRACE}"

if [[ "$(grep -Fc "|${shell_oid}" "${QUALITY_SHELL_TRACE}")" != 3 ]]; then
  fail "duplicate refs executed the shell suite more than once for one OID"
fi

for expected_python_oid in \
  "${rename_oid}" \
  "${new_oid}"; do
  grep -Fx "${expected_python_oid}" "${QUALITY_PY_TRACE}" >/dev/null ||
    fail "Python suite omitted pushed OID ${expected_python_oid}"
done
for expected_shell_oid in \
  "${shell_oid}" \
  "${shell_clean_oid}" \
  "${delete_oid}" \
  "${new_oid}"; do
  grep -F "|${expected_shell_oid}" "${QUALITY_SHELL_TRACE}" >/dev/null ||
    fail "shell suite omitted pushed OID ${expected_shell_oid}"
done
grep -F "test_commit_message_validation.sh|${shell_oid}" \
  "${QUALITY_SHELL_TRACE}" >/dev/null ||
  fail "affected shell suite omitted commit-message integration"
if grep -F "|${rename_oid}" "${QUALITY_SHELL_TRACE}" >/dev/null; then
  fail "Python-only update ran the shell suite at ${rename_oid}"
fi
if [[ ! -s "${QUALITY_LOCAL_DEPENDENCY_TRACE}" ]]; then
  fail "pushed-OID shell tests could not use source-local dependencies"
fi
unset QUALITY_REQUIRE_LOCAL_PROBE

redirected_updates="${test_temp}/redirected.updates"
printf 'refs/heads/new %s refs/heads/new %s\n' \
  "${new_oid}" \
  '0000000000000000000000000000000000000000' \
  >"${redirected_updates}"
: >"${QUALITY_CLONE_TRACE}"
: >"${QUALITY_CLONE_DESTINATION_TRACE}"
: >"${QUALITY_REDIRECTED_GIT_DIR_TRACE}"
: >"${QUALITY_CHECKOUT_TRACE}"
: >"${QUALITY_PY_TRACE}"
: >"${QUALITY_SHELL_TRACE}"
export QUALITY_REDIRECT_CLONE_GIT_DIR=true
redirected_status=0
run_pre_push_bounded "${integration_timeout_seconds}" \
  "${redirected_updates}" origin local \
  >/dev/null 2>&1 || redirected_status=$?
unset QUALITY_REDIRECT_CLONE_GIT_DIR
if ((redirected_status == 0)); then
  fail "pre-push accepted a clone with a redirected Git directory"
fi
if [[ -s "${QUALITY_PY_TRACE}" || -s "${QUALITY_SHELL_TRACE}" ]]; then
  fail "pre-push ran tests before rejecting a redirected clone"
fi
if [[ -s "${QUALITY_CHECKOUT_TRACE}" ]]; then
  fail "pre-push checked out a redirected clone before rejecting it"
fi
while IFS= read -r redirected_path; do
  if [[ -e "${redirected_path}" ]]; then
    fail "redirected clone test leaked ${redirected_path}"
  fi
done < <(cat \
  "${QUALITY_CLONE_DESTINATION_TRACE}" \
  "${QUALITY_REDIRECTED_GIT_DIR_TRACE}")

sha256_fixture="${test_temp}/sha256 repository"
if git init -q --object-format=sha256 "${sha256_fixture}" \
  >/dev/null 2>&1; then
  git -C "${sha256_fixture}" config user.name "SHA-256 Hook Test"
  git -C "${sha256_fixture}" config user.email "sha256-hook@example.com"
  git -C "${sha256_fixture}" config core.autocrlf false
  printf 'print("sha256")\n' >"${sha256_fixture}/candidate.py"
  git -C "${sha256_fixture}" add candidate.py
  git -C "${sha256_fixture}" commit -q -m "test: add SHA-256 candidate"
  sha256_oid="$(git -C "${sha256_fixture}" rev-parse HEAD)"
  sha256_updates="${test_temp}/sha256.updates"
  printf 'refs/heads/main %s refs/heads/main %s\n' \
    "${sha256_oid}" \
    '0000000000000000000000000000000000000000000000000000000000000000' \
    >"${sha256_updates}"
  export QUALITY_FIXTURE="${sha256_fixture}"
  export QUALITY_AFFECTED_TRACE="${test_temp}/sha256-affected.trace"
  : >"${QUALITY_AFFECTED_TRACE}"
  run_pre_push_bounded "${integration_timeout_seconds}" \
    "${sha256_updates}" origin local
  unset QUALITY_AFFECTED_TRACE
  export QUALITY_FIXTURE="${fixture}"
  if [[ "$(cat "${test_temp}/sha256-affected.trace")" != "true|true|${sha256_oid}" ]]; then
    fail "SHA-256 new-ref sentinel did not select both affected suites"
  fi
fi

unset QUALITY_STUB_AFFECTED_TESTS
export QUALITY_AFFECTED_TRACE="${test_temp}/affected.trace"

timeout_bin="${test_temp}/timeout-bin"
mkdir -p "${timeout_bin}"
cat >"${timeout_bin}/timeout" <<'TIMEOUT'
#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$@" >"${QUALITY_TIMEOUT_TRACE}"
exit 124
TIMEOUT
chmod +x "${timeout_bin}/timeout"
timeout_updates="${test_temp}/timeout.updates"
printf 'refs/heads/python %s refs/heads/python %s\n' \
  "${python_oid}" "${base_oid}" >"${timeout_updates}"
export QUALITY_TIMEOUT_TRACE="${test_temp}/timeout.trace"
: >"${QUALITY_CLONE_TRACE}"
: >"${QUALITY_CLONE_DESTINATION_TRACE}"
timeout_status=0
PATH="${timeout_bin}:${PATH}" \
  "${test_timeout_cmd}" --kill-after=3s \
  "${integration_timeout_seconds}s" \
  bash "${runner}" origin local <"${timeout_updates}" \
  >"${test_temp}/timeout.out" 2>"${test_temp}/timeout.err" ||
  timeout_status=$?
if ((timeout_status != 124)); then
  fail "timed-out pre-push returned ${timeout_status} instead of 124"
fi
if ! grep -Fx \
  'pre-push: affected Python test family timed out after 180 seconds.' \
  "${test_temp}/timeout.err" >/dev/null; then
  fail "timed-out pre-push omitted its Python family diagnostic"
fi
if [[ "$(sed -n '1p' "${QUALITY_TIMEOUT_TRACE}")" != --kill-after=1s ]] ||
  [[ "$(sed -n '2p' "${QUALITY_TIMEOUT_TRACE}")" != 180s ]] ||
  [[ "$(sed -n '3p' "${QUALITY_TIMEOUT_TRACE}")" != bash ]]; then
  fail "pre-push did not invoke the portable 180-second timeout contract"
fi
timeout_clone_destination="$(cat "${QUALITY_CLONE_DESTINATION_TRACE}")"
if [[ -e "${timeout_clone_destination}" ]]; then
  fail "timed-out pre-push leaked its temporary clone"
fi
unset QUALITY_TIMEOUT_TRACE

missing_updates="${test_temp}/missing.updates"
printf 'refs/heads/missing %s refs/heads/missing %s\n' \
  "${python_oid}" '1111111111111111111111111111111111111111' \
  >"${missing_updates}"
if run_pre_push_bounded "${integration_timeout_seconds}" \
  "${missing_updates}" origin local \
  >/dev/null 2>&1; then
  fail "missing remote OID did not fail change discovery"
fi
printf 'refs/heads/missing %s refs/heads/missing %s\n' \
  '2222222222222222222222222222222222222222' "${base_oid}" \
  >"${missing_updates}"
if run_pre_push_bounded "${integration_timeout_seconds}" \
  "${missing_updates}" origin local \
  >/dev/null 2>&1; then
  fail "missing local OID did not fail change discovery"
fi

discovery_updates="${test_temp}/discovery.updates"
printf 'refs/heads/python %s refs/heads/python %s\n' \
  "${python_oid}" "${base_oid}" >"${discovery_updates}"
export QUALITY_DISCOVERY_STATUS=42
discovery_status=0
run_pre_push_bounded "${integration_timeout_seconds}" \
  "${discovery_updates}" origin local ||
  discovery_status=$?
unset QUALITY_DISCOVERY_STATUS
((discovery_status == 42)) ||
  fail "change-discovery returned ${discovery_status} instead of 42"

signal_updates="${test_temp}/signal.updates"
printf 'refs/heads/python %s refs/heads/python %s\n' \
  "${python_oid}" "${base_oid}" >"${signal_updates}"
: >"${QUALITY_CLONE_TRACE}"
: >"${QUALITY_CLONE_DESTINATION_TRACE}"
export QUALITY_SIGNAL_ON_CLONE=true
signal_status=0
run_pre_push_bounded "${integration_timeout_seconds}" \
  "${signal_updates}" origin local \
  >/dev/null 2>&1 || signal_status=$?
unset QUALITY_SIGNAL_ON_CLONE
((signal_status == 143)) ||
  fail "terminated pre-push returned ${signal_status} instead of 143"
clone_destination="$(cat "${QUALITY_CLONE_DESTINATION_TRACE}")"
if [[ -e "${clone_destination}" ]]; then
  fail "terminated pre-push leaked its temporary clone"
fi

git -C "${fixture}" tag v1.2.3 "${python_oid}"
git -C "${fixture}" tag -a v1.2.4 -m v1.2.4 "${shell_oid}"
lightweight_oid="$(git -C "${fixture}" rev-parse v1.2.3)"
annotated_oid="$(git -C "${fixture}" rev-parse v1.2.4)"
release_bin="${test_temp}/release-bin"
mkdir -p "${release_bin}"
cat >"${release_bin}/python" <<'RELEASE_PYTHON'
#!/usr/bin/env bash
set -euo pipefail

expected_ref=''
repository_root=''
treeish=''
shift
while (($#)); do
  case "$1" in
  --expected-ref)
    expected_ref="$2"
    shift 2
    ;;
  --treeish)
    treeish="$2"
    shift 2
    ;;
  --repository-root)
    repository_root="$2"
    shift 2
    ;;
  *)
    shift
    ;;
  esac
done
git -C "${repository_root}" cat-file -e "${treeish}"
printf '%s|%s\n' "${expected_ref}" "${treeish}" \
  >>"${QUALITY_RELEASE_TRACE}"
RELEASE_PYTHON
chmod +x "${release_bin}/python"
export QUALITY_RELEASE_TRACE="${test_temp}/release.trace"
release_updates="${test_temp}/release.updates"
{
  printf 'refs/tags/v1.2.3 %s refs/tags/v1.2.3 %s\n' \
    "${lightweight_oid}" '0000000000000000000000000000000000000000'
  printf 'refs/tags/v1.2.4 %s refs/tags/v1.2.4 %s\n' \
    "${annotated_oid}" '0000000000000000000000000000000000000000'
  printf '(delete) %s refs/tags/v1.2.2 %s\n' \
    '0000000000000000000000000000000000000000' "${lightweight_oid}"
  printf '(delete) %s refs/heads/old %s\n' \
    '0000000000000000000000000000000000000000' "${base_oid}"
} >"${release_updates}"
PATH="${release_bin}:${PATH}" \
  run_pre_push_bounded "${integration_timeout_seconds}" \
  "${release_updates}" origin local
cat >"${test_temp}/release.expected" <<EOF
v1.2.3|${lightweight_oid}^{commit}
v1.2.4|${annotated_oid}^{commit}
EOF
if ! cmp -s "${test_temp}/release.expected" "${QUALITY_RELEASE_TRACE}"; then
  diff -u "${test_temp}/release.expected" "${QUALITY_RELEASE_TRACE}" >&2 || true
  fail "lightweight or annotated tag validation changed"
fi

printf '%s\n' 'PASS: exact pushed OID hook behavior'
