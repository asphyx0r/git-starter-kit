#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(git -C "$script_dir" rev-parse --show-toplevel)"

# shellcheck disable=SC1091
source "$source_root/tools/repository-audit.sh"
audit_all_commits_marker="${audit_all_commits_marker:-__all_commits__}"

test_temp="$(mktemp -d "${TMPDIR:-/tmp}/commit-message-validation.XXXXXX")"

cleanup_test() {
  case "$(basename "$test_temp")" in
  commit-message-validation.*)
    rm -rf -- "$test_temp"
    ;;
  *)
    printf 'Refusing to remove unexpected test path: %s\n' "$test_temp" >&2
    return 1
    ;;
  esac
}

trap cleanup_test EXIT

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

require_test_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "required command not found: $1"
  fi
}

initialize_fixture() {
  local fixture_root="$1"

  git init -q "$fixture_root"
  git -C "$fixture_root" branch -m main
  git -C "$fixture_root" config user.name "Commit Validation Test"
  git -C "$fixture_root" config user.email "commit-validation@example.com"
  git -C "$fixture_root" config core.autocrlf false
  mkdir -p "$fixture_root/.githooks" "$fixture_root/.disabled-hooks"
  cp "$source_root/.githooks/commit-msg" "$fixture_root/.githooks/commit-msg"
  cp "$source_root/commitlint.config.cjs" "$fixture_root/commitlint.config.cjs"
  chmod +x "$fixture_root/.githooks/commit-msg"
}

commit_without_repository_hooks() {
  local fixture_root="$1"
  local message_file="$2"

  git -c core.hooksPath="$fixture_root/.disabled-hooks" \
    -C "$fixture_root" commit \
    --file="$message_file" \
    --cleanup=verbatim \
    --quiet
}

write_initial_message() {
  printf '%s\n' 'chore(config): initialize fixture' >"$1"
}

write_invalid_message() {
  {
    printf '%s\n\n' 'feat(agents): use canonical rule source'
    printf '%s\n' 'Adopt the universal repository-owned update workflow, preserve local rule customizations, and validate release packages from tracked rules.'
  } >"$1"
}

write_valid_message() {
  {
    printf '%s\n\n' 'feat(agents): use canonical rule source'
    printf '%s\n' 'Adopt the universal repository-owned update workflow, preserve local'
    printf '%s\n' 'rule customizations, and validate release packages from tracked rules.'
  } >"$1"
}

require_test_command git
npx_command="$(resolve_npx_command)"

resolver_bin="$test_temp/resolver-bin"
mkdir -p "$resolver_bin"
printf '#!/usr/bin/env bash\n' >"$resolver_bin/npx"
printf '#!/usr/bin/env bash\n' >"$resolver_bin/npx.cmd"
chmod +x "$resolver_bin/npx" "$resolver_bin/npx.cmd"
original_path="$PATH"
PATH="$resolver_bin:$PATH"
if [ "$(resolve_npx_command Linux)" != "$resolver_bin/npx" ]; then
  fail "POSIX npx resolution did not select npx"
fi
if [ "$(resolve_npx_command MSYS_NT-10.0)" != "$resolver_bin/npx.cmd" ]; then
  fail "MSYS npx resolution did not select npx.cmd"
fi
PATH="$original_path"

test_bin="$test_temp/bin"
mkdir -p "$test_bin"
export NPM_CONFIG_CACHE="$test_temp/npm-cache"
cat >"$test_bin/commitlint" <<'COMMITLINT'
#!/usr/bin/env bash
set -euo pipefail
NPM_CONFIG_IGNORE_SCRIPTS=true \
  "$AUDIT_NPX_COMMAND" --yes @commitlint/cli@21.0.2 "$@"
COMMITLINT
chmod +x "$test_bin/commitlint"
export AUDIT_NPX_COMMAND="$npx_command"
export PATH="$test_bin:$PATH"
commitlint_command="$test_bin/commitlint"
unset AUDIT_COMMIT_SHA

range_fixture="$test_temp/range-fixture"
initialize_fixture "$range_fixture"

initial_message="$test_temp/initial-message.txt"
invalid_message="$test_temp/invalid-message.txt"
valid_message="$test_temp/valid-message.txt"
write_initial_message "$initial_message"
write_invalid_message "$invalid_message"
write_valid_message "$valid_message"

printf 'base\n' >"$range_fixture/tracked.txt"
git -C "$range_fixture" add tracked.txt
commit_without_repository_hooks "$range_fixture" "$initial_message"
git -C "$range_fixture" tag -a v1.0.0 -m 'Release v1.0.0'

printf 'invalid\n' >>"$range_fixture/tracked.txt"
git -C "$range_fixture" add tracked.txt
commit_without_repository_hooks "$range_fixture" "$invalid_message"
invalid_commit="$(git -C "$range_fixture" rev-parse HEAD)"

printf 'valid\n' >>"$range_fixture/tracked.txt"
git -C "$range_fixture" add tracked.txt
commit_without_repository_hooks "$range_fixture" "$valid_message"

zero_sha="0000000000000000000000000000000000000000"
export GITHUB_EVENT_NAME=push
export GITHUB_REF_TYPE=branch
export GITHUB_REF_NAME=codex/release-preflight-v1.1.0
export BEFORE_SHA="$zero_sha"

cd "$range_fixture"
resolved_base="$(resolve_audit_from_ref)"
if [ "$resolved_base" != "v1.0.0" ]; then
  fail "preflight range did not resolve the previous stable tag"
fi

if ! git rev-list "$resolved_base..HEAD" | grep -Fx "$invalid_commit" >/dev/null; then
  fail "preflight range omitted the invalid intermediate commit"
fi

range_failure_output="$test_temp/range-failure.out"
if run_commitlint_readonly "$commitlint_command" \
  >"$range_failure_output" 2>&1; then
  fail "release range accepted the invalid intermediate commit"
fi
if ! grep -F 'body-max-line-length' "$range_failure_output" >/dev/null; then
  sed 's/^/  /' "$range_failure_output" >&2
  fail "release range failure did not report body-max-line-length"
fi

git tag -a v1.1.0 -m 'Release v1.1.0'
export GITHUB_EVENT_NAME=release
export GITHUB_REF_TYPE=tag
export GITHUB_REF_NAME=v1.1.0
resolved_base="$(resolve_audit_from_ref)"
if [ "$resolved_base" != "v1.0.0" ]; then
  fail "release range did not exclude the tag being audited"
fi

printf 'future\n' >>tracked.txt
git add tracked.txt
commit_without_repository_hooks "$range_fixture" "$valid_message"
export GITHUB_REF_NAME=v1.1.1
resolved_base="$(resolve_audit_from_ref)"
if [ "$resolved_base" != "v1.1.0" ]; then
  fail "future release did not use the immediately previous stable tag"
fi
run_commitlint_readonly "$commitlint_command" >/dev/null

pull_request_fixture="$test_temp/pull-request-fixture"
initialize_fixture "$pull_request_fixture"
printf 'base\n' >"$pull_request_fixture/tracked.txt"
git -C "$pull_request_fixture" add tracked.txt
commit_without_repository_hooks "$pull_request_fixture" "$initial_message"
git -C "$pull_request_fixture" checkout -q -b feature
printf 'feature\n' >>"$pull_request_fixture/tracked.txt"
git -C "$pull_request_fixture" add tracked.txt
commit_without_repository_hooks "$pull_request_fixture" "$valid_message"
pull_request_head="$(git -C "$pull_request_fixture" rev-parse HEAD)"
git -C "$pull_request_fixture" checkout -q main
printf 'base change\n' >"$pull_request_fixture/base.txt"
git -C "$pull_request_fixture" add base.txt
commit_without_repository_hooks "$pull_request_fixture" "$valid_message"
pull_request_base="$(git -C "$pull_request_fixture" rev-parse HEAD)"
git -C "$pull_request_fixture" update-ref \
  refs/remotes/origin/main "$pull_request_base"
git -c core.hooksPath="$pull_request_fixture/.disabled-hooks" \
  -C "$pull_request_fixture" merge --no-ff feature \
  -m 'Merge feature into main' --quiet
pull_request_merge="$(git -C "$pull_request_fixture" rev-parse HEAD)"

cd "$pull_request_fixture"
export GITHUB_EVENT_NAME=pull_request
export GITHUB_BASE_REF=main
export AUDIT_COMMIT_SHA="$pull_request_head"
if [ "$pull_request_merge" = "$AUDIT_COMMIT_SHA" ]; then
  fail "pull request fixture did not retain the synthetic merge checkout"
fi
run_commitlint_readonly "$commitlint_command" >/dev/null

unset AUDIT_COMMIT_SHA
if run_commitlint_readonly "$commitlint_command" >/dev/null 2>&1; then
  fail "pull request merge message was unexpectedly accepted"
fi
unset GITHUB_BASE_REF

first_release_fixture="$test_temp/first-release-fixture"
initialize_fixture "$first_release_fixture"
printf 'first\n' >"$first_release_fixture/tracked.txt"
git -C "$first_release_fixture" add tracked.txt
commit_without_repository_hooks "$first_release_fixture" "$initial_message"
cd "$first_release_fixture"
export GITHUB_REF_TYPE=branch
export GITHUB_REF_NAME=codex/release-preflight-v1.0.0
resolved_base="$(resolve_audit_from_ref)"
if [ "$resolved_base" != "$audit_all_commits_marker" ]; then
  fail "first release did not select all reachable commits"
fi
run_commitlint_readonly "$commitlint_command" >/dev/null

hook_fixture="$test_temp/hook-fixture"
initialize_fixture "$hook_fixture"
printf 'base\n' >"$hook_fixture/tracked.txt"
git -C "$hook_fixture" add tracked.txt
commit_without_repository_hooks "$hook_fixture" "$initial_message"

if git -C "$hook_fixture" config --local --get core.hooksPath >/dev/null; then
  fail "hook fixture unexpectedly configured core.hooksPath"
fi

printf 'candidate\n' >>"$hook_fixture/tracked.txt"
git -C "$hook_fixture" add tracked.txt
head_before="$(git -C "$hook_fixture" rev-parse HEAD)"
hook_failure_output="$test_temp/hook-failure.out"
if git -c core.hooksPath=.githooks -C "$hook_fixture" commit \
  --file="$invalid_message" \
  --cleanup=verbatim >"$hook_failure_output" 2>&1; then
  fail "forced commit-msg hook accepted the invalid message"
fi
if ! grep -F 'body-max-line-length' "$hook_failure_output" >/dev/null; then
  sed 's/^/  /' "$hook_failure_output" >&2
  fail "forced hook failure did not report body-max-line-length"
fi
if [ "$(git -C "$hook_fixture" rev-parse HEAD)" != "$head_before" ]; then
  fail "failed commit moved HEAD"
fi

git -c core.hooksPath=.githooks -C "$hook_fixture" commit \
  --file="$valid_message" \
  --cleanup=verbatim \
  --quiet

expected_message="$(tr -d '\r' <"$valid_message")"
actual_message="$(git -C "$hook_fixture" log -1 --format=%B | tr -d '\r')"
if [ "$actual_message" != "$expected_message" ]; then
  fail "committed message differs from the validated file"
fi

printf '%s\n' 'PASS: commit message and release range validation'
