#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(git -C "${script_dir}" rev-parse --show-toplevel)"
transfer_cli="${source_root}/tools/repository-audit/agent-rules-transfer.sh"
test_temp="$(mktemp -d "${TMPDIR:-/tmp}/agent-rules-transfer-test.XXXXXX")"
publish_auth_marker=app-token-literal

cleanup_test() {
  case "${test_temp}" in
  "${TMPDIR:-/tmp}"/agent-rules-transfer-test.*)
    if ! rm -rf -- "${test_temp}"; then
      sleep 1
      rm -rf -- "${test_temp}"
    fi
    ;;
  *)
    printf 'Refusing to remove unexpected test path: %s\n' \
      "${test_temp}" >&2
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

assert_files_equal() {
  local expected_path="$1"
  local actual_path="$2"
  local diagnostic="$3"

  if ! cmp -s "${expected_path}" "${actual_path}"; then
    diff -u --label expected --label actual \
      "${expected_path}" "${actual_path}" >&2 || true
    fail "${diagnostic}"
  fi
}

expect_failure() {
  local case_name="$1"
  local expected_status="$2"
  local expected_diagnostic="$3"
  local actual_status
  shift 3

  if "$@" >"${test_temp}/${case_name}.out" \
    2>"${test_temp}/${case_name}.err"; then
    actual_status=0
  else
    actual_status=$?
  fi
  if ((actual_status == 0)); then
    fail "${case_name} unexpectedly succeeded"
  fi
  case "${actual_status}" in
  124 | 129 | 130 | 137 | 143)
    fail "${case_name} ended by timeout or signal (${actual_status})"
    ;;
  esac
  if ((actual_status != expected_status)); then
    fail \
      "${case_name} returned ${actual_status}, expected ${expected_status}"
  fi
  if ! grep -Fx -- "${expected_diagnostic}" \
    "${test_temp}/${case_name}.err" >/dev/null; then
    sed 's/^/  /' "${test_temp}/${case_name}.err" >&2
    fail "${case_name} did not emit its exact diagnostic"
  fi
}

git_fixture() {
  git \
    -c core.autocrlf=false \
    -c user.name=Fixture \
    -c user.email=fixture@example.invalid \
    -c commit.gpgSign=false \
    "$@"
}

write_source_stubs() {
  local stub_bin="$1"

  mkdir -p "${stub_bin}"
  cat >"${stub_bin}/gh" <<'GH_SOURCE_STUB'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-} ${2:-}" == 'api graphql' ]]; then
  printf '%s\n' "${TEST_BRANCH_RESPONSE:?}"
  exit 0
fi
if [[ "${1:-} ${2:-}" != 'api repos/asphyx0r/agent-coding-rules/releases/latest' ]]; then
  printf 'Unexpected gh command:' >&2
  printf ' %q' "$@" >&2
  printf '\n' >&2
  exit 91
fi
count=0
if [[ -f "${TEST_GH_COUNT:?}" ]]; then
  read -r count <"${TEST_GH_COUNT}"
fi
count=$((count + 1))
printf '%s\n' "${count}" >"${TEST_GH_COUNT}"
if ((count == 1)); then
  printf '%s\n' "${TEST_LATEST_FIRST:?}"
else
  printf '%s\n' "${TEST_LATEST_SECOND:-${TEST_LATEST_FIRST}}"
fi
GH_SOURCE_STUB
  cat >"${stub_bin}/timeout" <<'TIMEOUT_STUB'
#!/usr/bin/env bash
set -euo pipefail

printf '%s|%s|%s|%s\n' \
  "${1:-}" "${2:-}" "${3:-}" "${4:-}" >>"${TEST_TIMEOUT_TRACE:?}"
shift 2
exec "$@"
TIMEOUT_STUB
  cat >"${stub_bin}/git" <<'GIT_SOURCE_STUB'
#!/usr/bin/env bash
set -euo pipefail

arguments=("$@")
for index in "${!arguments[@]}"; do
  if [[ "${arguments[index]}" == \
    'https://github.com/asphyx0r/agent-coding-rules.git' ]]; then
    arguments[index]="${TEST_SOURCE_REMOTE:?}"
  fi
done

  if [[ " ${arguments[*]} " == *' ls-remote --tags --exit-code '* ]]; then
  count=0
  if [[ -f "${TEST_LS_REMOTE_COUNT:?}" ]]; then
    read -r count <"${TEST_LS_REMOTE_COUNT}"
  fi
    count=$((count + 1))
    printf '%s\n' "${count}" >"${TEST_LS_REMOTE_COUNT}"
    if ((count == 1)) && [[ -n "${TEST_FIRST_LS_REMOTE:-}" ]]; then
      printf '%b' "${TEST_FIRST_LS_REMOTE}"
      exit 0
    fi
  if ((count == 2)) && [[ -n "${TEST_SECOND_LS_REMOTE:-}" ]]; then
    printf '%b' "${TEST_SECOND_LS_REMOTE}"
    exit 0
  fi
fi

exec "${REAL_GIT:?}" "${arguments[@]}"
GIT_SOURCE_STUB
  chmod +x "${stub_bin}/gh" "${stub_bin}/git" "${stub_bin}/timeout"
}

assert_gh_api_timeouts() {
  local case_root="$1"
  local expected_count="$2"
  local timeout_trace="${case_root}/timeout.trace"

  if [[ ! -f "${timeout_trace}" ]]; then
    fail 'GitHub API calls were not bounded by the timeout wrapper'
  fi
  if [[ "$(wc -l <"${timeout_trace}")" != "${expected_count}" ]]; then
    sed 's/^/  /' "${timeout_trace}" >&2
    fail "expected ${expected_count} bounded GitHub API calls"
  fi
  if grep -Fvx -- '--kill-after=5s|30s|gh|api' \
    "${timeout_trace}" >/dev/null; then
    sed 's/^/  /' "${timeout_trace}" >&2
    fail 'GitHub API timeout arguments changed'
  fi
}

initialize_source_remote() {
  local case_root="$1"
  local tag_kind="$2"
  local object_format="${3:-sha1}"
  local path
  local source="${case_root}/source"
  local remote="${case_root}/source.git"

  git_fixture init -q --object-format="${object_format}" -b main "${source}"
  for path in \
    AGENTS.md \
    BRANCH_RULES.md \
    CODING_RULES.md \
    COMMIT_RULES.md \
    DOCUMENTATION_RULES.md \
    LANGUAGE_RULES.md \
    RELEASE_RULES.md; do
    printf 'updated %s\n' "${path}" >"${source}/${path}"
  done
  mkdir -p "${source}/tools"
  printf '%s\n' 'print("sync")' >"${source}/tools/agent-rules-sync.py"
  git_fixture -C "${source}" add -- .
  git_fixture -C "${source}" commit -q -m source
  case "${tag_kind}" in
  lightweight)
    git_fixture -C "${source}" tag v1.2.3
    git_fixture -C "${source}" tag -a -m alternate v9.9.9
    ;;
  annotated)
    git_fixture -C "${source}" tag -a -m release v1.2.3
    ;;
  blob)
    blob_oid="$(git_fixture -C "${source}" hash-object AGENTS.md)"
    git_fixture -C "${source}" tag -a -m invalid v1.2.3 "${blob_oid}"
    ;;
  *) fail "unknown source tag kind: ${tag_kind}" ;;
  esac
  git_fixture init -q --bare --object-format="${object_format}" "${remote}"
  git_fixture -C "${source}" remote add origin "${remote}"
  git_fixture -C "${source}" push -q origin main --tags
}

invoke_resolve() {
  local argument
  local case_root="$1"
  local latest_first=v1.2.3
  local target="$2"
  local stub_bin="${case_root}/bin"
  local -a extra_environment=()
  shift 2

  for argument in "$@"; do
    case "${argument}" in
    TEST_LATEST_FIRST=*) latest_first="${argument#*=}" ;;
    *) extra_environment+=("${argument}") ;;
    esac
  done

  write_source_stubs "${stub_bin}"
  (
    cd "${target}"
    timeout --kill-after=5s 30s env \
      PATH="${stub_bin}:${PATH}" \
      GH_TOKEN=CHANGE_ME \
      RUNNER_TEMP="${case_root}/runner" \
      GITHUB_OUTPUT="${case_root}/github-output" \
      RULES_REPOSITORY=asphyx0r/agent-coding-rules \
      TARGET_REPOSITORY=asphyx0r/git-starter-kit \
      TARGET_DEFAULT_BRANCH=main \
      SYNC_BRANCH=automation/agent-rules-update \
      REAL_GIT="$(command -v git)" \
      TEST_SOURCE_REMOTE="${case_root}/source.git" \
      TEST_GH_COUNT="${case_root}/gh.count" \
      TEST_TIMEOUT_TRACE="${case_root}/timeout.trace" \
      TEST_LS_REMOTE_COUNT="${case_root}/ls-remote.count" \
      TEST_LATEST_FIRST="${latest_first}" \
      "${extra_environment[@]}" bash "${transfer_cli}" resolve
  )
}

write_synced_rule_files() {
  local target="$1"
  local source_ref="$2"
  local source_commit="$3"
  local file_hashes=''
  local path

  for path in \
    AGENTS.md \
    BRANCH_RULES.md \
    CODING_RULES.md \
    COMMIT_RULES.md \
    DOCUMENTATION_RULES.md \
    LANGUAGE_RULES.md \
    RELEASE_RULES.md; do
    printf 'updated %s\n' "${path}" >"${target}/${path}"
    file_hashes+="$(
      printf '      \"%s\": \"%s\"' \
        "${path}" "$(sha256sum "${target}/${path}" | cut -d' ' -f1)"
    )"
    if [[ "${path}" != 'RELEASE_RULES.md' ]]; then
      file_hashes+=","
    fi
    file_hashes+=$'\n'
  done
  printf '%s\n' \
    '{' \
    '  "schemaVersion": 3,' \
    '  "agentRules": {' \
    '    "repository": "https://github.com/asphyx0r/agent-coding-rules",' \
    "    \"requestedRef\": \"${source_ref}\"," \
    "    \"ref\": \"${source_ref}\"," \
    "    \"commit\": \"${source_commit}\"," \
    '    "files": [' \
    '      "AGENTS.md",' \
    '      "BRANCH_RULES.md",' \
    '      "CODING_RULES.md",' \
    '      "COMMIT_RULES.md",' \
    '      "DOCUMENTATION_RULES.md",' \
    '      "LANGUAGE_RULES.md",' \
    '      "RELEASE_RULES.md"' \
    '    ],' \
    '    "fileHashes": {' \
    "${file_hashes%$'\n'}" \
    '    }' \
    '  }' \
    '}' >"${target}/_agent-rules-source.json"
}

refresh_rule_hash() {
  local metadata_path="$1"
  local rule_path="$2"

  python - "${metadata_path}" "${rule_path}" <<'PY'
import hashlib
import json
import pathlib
import sys

metadata_path = pathlib.Path(sys.argv[1])
rule_path = pathlib.Path(sys.argv[2])
with metadata_path.open(encoding="utf-8") as stream:
    metadata = json.load(stream)
metadata["agentRules"]["fileHashes"][rule_path.name] = hashlib.sha256(
    rule_path.read_bytes()
).hexdigest()
with metadata_path.open("w", encoding="utf-8", newline="\n") as stream:
    json.dump(metadata, stream, indent=2)
    stream.write("\n")
PY
}

write_canonical_transfer_checksums() {
  local artifact_root="$1"

  python - "${artifact_root}" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
names = ("agent-rules.patch", "agent-rules-plan.json", "source.json")
with (root / "SHA256SUMS").open("wb") as stream:
    for name in names:
        digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
        stream.write(f"{digest}  {name}\n".encode("ascii"))
PY
}

invoke_seal() {
  local case_root="$1"
  local target="$2"
  local target_base_commit="$3"
  local source_tag_oid="$4"
  local source_commit="$5"

  invoke_cli "${target}" "${case_root}/runner" \
    "${case_root}/github-output" env \
    TARGET_BASE_COMMIT="${target_base_commit}" \
    SOURCE_REF=v1.2.3 \
    SOURCE_TAG_OID="${source_tag_oid}" \
    SOURCE_COMMIT="${source_commit}" \
    bash "${transfer_cli}" seal
}

create_valid_transfer_fixture() {
  local case_root="$1"
  local target="${case_root}/target"

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  initialize_source_remote "${case_root}" annotated
  fixture_target_base_commit="$(git_fixture -C "${target}" rev-parse HEAD)"
  fixture_source_tag_oid="$(
    git_fixture --git-dir="${case_root}/source.git" \
      rev-parse refs/tags/v1.2.3
  )"
  fixture_source_commit="$(
    git_fixture --git-dir="${case_root}/source.git" \
      rev-parse 'refs/tags/v1.2.3^{commit}'
  )"
  write_synced_rule_files "${target}" v1.2.3 "${fixture_source_commit}"
  printf '%s\n' '{"actions":[]}' \
    >"${case_root}/runner/agent-rules-plan.json"
  invoke_seal "${case_root}" "${target}" \
    "${fixture_target_base_commit}" "${fixture_source_tag_oid}" \
    "${fixture_source_commit}"
  git_fixture -C "${target}" reset -q --hard "${fixture_target_base_commit}"
  rm -f -- "${case_root}/github-output"
}

invoke_prepare_publish() {
  local case_root="$1"
  local target="${case_root}/target"

  write_source_stubs "${case_root}/bin"
  (
    cd "${target}"
    timeout --kill-after=5s 60s env \
      PATH="${case_root}/bin:${PATH}" \
      GH_TOKEN=CHANGE_ME \
      RUNNER_TEMP="${case_root}/runner" \
      GITHUB_OUTPUT="${case_root}/github-output" \
      RULES_REPOSITORY=asphyx0r/agent-coding-rules \
      TARGET_REPOSITORY=asphyx0r/git-starter-kit \
      TARGET_DEFAULT_BRANCH=main \
      TARGET_BASE_COMMIT="${fixture_target_base_commit}" \
      SOURCE_REF=v1.2.3 \
      SOURCE_TAG_OID="${fixture_source_tag_oid}" \
      SOURCE_COMMIT="${fixture_source_commit}" \
      SYNC_BRANCH=automation/agent-rules-update \
      REAL_GIT="$(command -v git)" \
      TEST_SOURCE_REMOTE="${case_root}/source.git" \
      TEST_GH_COUNT="${case_root}/gh.count" \
      TEST_TIMEOUT_TRACE="${case_root}/timeout.trace" \
      TEST_LS_REMOTE_COUNT="${case_root}/ls-remote.count" \
      TEST_LATEST_FIRST=v1.2.3 \
      TEST_BRANCH_RESPONSE='{"data":{"repository":{"ref":null}}}' \
      TEST_HOOK_SENTINEL="${TEST_HOOK_SENTINEL:-${case_root}/hook.trace}" \
      bash "${transfer_cli}" prepare-publish
  )
}

initialize_target() {
  local target="$1"
  local object_format="${2:-sha1}"
  local path

  git_fixture init -q --object-format="${object_format}" -b main "${target}"
  git_fixture -C "${target}" config core.autocrlf false
  for path in \
    AGENTS.md \
    BRANCH_RULES.md \
    CODING_RULES.md \
    COMMIT_RULES.md \
    DOCUMENTATION_RULES.md \
    LANGUAGE_RULES.md \
    RELEASE_RULES.md \
    _agent-rules-source.json; do
    printf '%s\n' "${path}" >"${target}/${path}"
  done
  git_fixture -C "${target}" add -- .
  git_fixture -C "${target}" commit -q -m base
}

invoke_cli() {
  local target="$1"
  local runner_temp="$2"
  local output_path="$3"
  shift 3

  (
    cd "${target}"
    timeout --kill-after=5s 30s env \
      -u GH_TOKEN \
      -u GITHUB_TOKEN \
      RUNNER_TEMP="${runner_temp}" \
      GITHUB_OUTPUT="${output_path}" \
      RULES_REPOSITORY=asphyx0r/agent-coding-rules \
      TARGET_REPOSITORY=asphyx0r/git-starter-kit \
      TARGET_DEFAULT_BRANCH=main \
      SYNC_BRANCH=automation/agent-rules-update \
      "$@"
  )
}

test_cli_rejects_missing_subcommand() {
  local case_root="${test_temp}/missing-subcommand"
  local target="${case_root}/target"

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  expect_failure missing-subcommand 2 \
    'Usage: agent-rules-transfer.sh {resolve|seal|prepare-publish|publish}' \
    invoke_cli "${target}" "${case_root}/runner" \
    "${case_root}/github-output" bash "${transfer_cli}"
}

test_resolve_preserves_tag_object_and_commit_identity() {
  local case_root
  local direct_oid
  local source_commit
  local target
  local tag_kind

  for tag_kind in lightweight annotated; do
    case_root="${test_temp}/resolve-${tag_kind}"
    target="${case_root}/target"
    mkdir -p "${case_root}/runner"
    initialize_target "${target}"
    initialize_source_remote "${case_root}" "${tag_kind}"
    direct_oid="$(
      git_fixture --git-dir="${case_root}/source.git" \
        rev-parse refs/tags/v1.2.3
    )"
    source_commit="$(
      git_fixture --git-dir="${case_root}/source.git" \
        rev-parse 'refs/tags/v1.2.3^{commit}'
    )"

    invoke_resolve "${case_root}" "${target}"

    assert_gh_api_timeouts "${case_root}" 2

    assert_file_contains "${case_root}/github-output" 'source_ref=v1.2.3'
    assert_file_contains "${case_root}/github-output" \
      "source_tag_oid=${direct_oid}"
    assert_file_contains "${case_root}/github-output" \
      "source_commit=${source_commit}"
    if [[ "$(
      git_fixture -C "${case_root}/runner/agent-rules-source" rev-parse HEAD
    )" != "${source_commit}" ]]; then
      fail "${tag_kind} source checkout does not match the peeled commit"
    fi
  done
}

test_resolve_rejects_latest_and_ref_races() {
  local case_root="${test_temp}/resolve-races"
  local target="${case_root}/target"
  local ref_line

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  initialize_source_remote "${case_root}" lightweight

  expect_failure latest-race 1 \
    'Latest source release changed during resolution.' \
    invoke_resolve "${case_root}" "${target}" \
    TEST_LATEST_SECOND=v9.9.9

  rm -rf -- \
    "${case_root}/runner/agent-rules-source" \
    "${case_root}/gh.count" \
    "${case_root}/ls-remote.count" \
    "${case_root}/github-output"
  ref_line="$(
    git_fixture --git-dir="${case_root}/source.git" \
      rev-parse refs/tags/v9.9.9
  )"
  expect_failure ref-race 1 'Source tag changed during resolution.' \
    invoke_resolve "${case_root}" "${target}" \
    TEST_SECOND_LS_REMOTE="${ref_line}\trefs/tags/v1.2.3\n"
}

test_resolve_rejects_non_commit_peeled_object() {
  local case_root="${test_temp}/resolve-blob-tag"
  local target="${case_root}/target"

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  initialize_source_remote "${case_root}" blob
  expect_failure blob-tag 1 'Source tag does not peel to a commit.' \
    invoke_resolve "${case_root}" "${target}"
}

test_resolve_accepts_sha256_when_supported() {
  local case_root="${test_temp}/resolve-sha256"
  local target="${case_root}/target"

  if ! git_fixture init -q --bare --object-format=sha256 \
    "${case_root}-probe.git" >/dev/null 2>&1; then
    return 0
  fi
  rm -rf -- "${case_root}-probe.git"
  mkdir -p "${case_root}/runner"
  initialize_target "${target}" sha256
  initialize_source_remote "${case_root}" annotated sha256

  invoke_resolve "${case_root}" "${target}"

  if ! grep -Eq '^source_tag_oid=[0-9a-f]{64}$' \
    "${case_root}/github-output" ||
    ! grep -Eq '^source_commit=[0-9a-f]{64}$' \
      "${case_root}/github-output"; then
    fail 'SHA-256 source identities were not preserved.'
  fi
}

test_resolve_rejects_invalid_semver_and_mixed_oids() {
  local case_root="${test_temp}/resolve-validation"
  local direct_oid
  local target="${case_root}/target"

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  expect_failure invalid-semver 1 \
    'Invalid source release tag: v01.2.3' \
    invoke_resolve "${case_root}" "${target}" \
    TEST_LATEST_FIRST=v01.2.3

  rm -f -- \
    "${case_root}/gh.count" \
    "${case_root}/ls-remote.count" \
    "${case_root}/github-output"
  initialize_source_remote "${case_root}" lightweight
  direct_oid="$(
    git_fixture --git-dir="${case_root}/source.git" \
      rev-parse refs/tags/v1.2.3
  )"
  expect_failure mixed-oids 1 'Source tag object formats do not match.' \
    invoke_resolve "${case_root}" "${target}" \
    TEST_FIRST_LS_REMOTE="${direct_oid}\trefs/tags/v1.2.3\n$(
      printf 'f%.0s' {1..64}
    )\trefs/tags/v1.2.3^{}\n"
}

test_resolve_rejects_noncanonical_target_roots() {
  local case_root="${test_temp}/resolve-roots"
  local stub_bin="${case_root}/bin"
  local target="${case_root}/target"

  mkdir -p "${case_root}/runner" "${stub_bin}"
  initialize_target "${target}"
  mkdir "${target}/nested"
  expect_failure target-subdirectory 1 \
    'The target checkout must be the current top-level directory.' \
    invoke_cli "${target}/nested" "${case_root}/runner" \
    "${case_root}/github-output" env GH_TOKEN=CHANGE_ME \
    bash "${transfer_cli}" resolve

  cat >"${stub_bin}/git" <<'GIT_ROOT_STUB'
#!/usr/bin/env bash
set -euo pipefail

case " $* " in
*" rev-parse --show-toplevel "*) pwd ;;
*" rev-parse --git-dir "*) printf '%s\n' .git ;;
*" rev-parse --git-common-dir "*) printf '%s\n' ../shared.git ;;
*) printf 'Unexpected git command before common-dir rejection:' >&2
  printf ' %q' "$@" >&2
  printf '\n' >&2
  exit 92 ;;
esac
GIT_ROOT_STUB
  chmod +x "${stub_bin}/git"
  expect_failure target-common-dir 1 \
    'The target checkout must use its own .git common directory.' \
    invoke_cli "${target}" "${case_root}/runner" \
    "${case_root}/github-output" env \
    PATH="${stub_bin}:${PATH}" GH_TOKEN=CHANGE_ME \
    bash "${transfer_cli}" resolve
}

test_seal_rejects_path_outside_allowlist() {
  local case_root="${test_temp}/seal-extra-path"
  local target="${case_root}/target"
  local target_base_commit
  local oid="1111111111111111111111111111111111111111"

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  target_base_commit="$(git_fixture -C "${target}" rev-parse HEAD)"
  printf '%s\n' unexpected >"${target}/unexpected.txt"
  printf '%s\n' '{"actions":[]}' \
    >"${case_root}/runner/agent-rules-plan.json"

  expect_failure seal-extra-path 1 \
    "Unexpected changed path: unexpected.txt" \
    invoke_cli "${target}" "${case_root}/runner" \
    "${case_root}/github-output" env \
    TARGET_BASE_COMMIT="${target_base_commit}" \
    SOURCE_REF=v1.2.3 \
    SOURCE_TAG_OID="${oid}" \
    SOURCE_COMMIT="${oid}" \
    bash "${transfer_cli}" seal
}

test_seal_creates_exact_verified_artifact() {
  local actual_checksum_names
  local artifact
  local case_root="${test_temp}/seal-valid"
  local source_commit='2222222222222222222222222222222222222222'
  local source_tag_oid='1111111111111111111111111111111111111111'
  local target="${case_root}/target"
  local target_base_commit

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  target_base_commit="$(git_fixture -C "${target}" rev-parse HEAD)"
  write_synced_rule_files "${target}" v1.2.3 "${source_commit}"
  printf '%s\n' '{"actions":[]}' \
    >"${case_root}/runner/agent-rules-plan.json"

  invoke_seal "${case_root}" "${target}" "${target_base_commit}" \
    "${source_tag_oid}" "${source_commit}"

  assert_file_contains "${case_root}/github-output" 'changed=true'
  artifact="${case_root}/runner/agent-rules-transfer"
  printf '%s\n' \
    SHA256SUMS agent-rules-plan.json agent-rules.patch source.json |
    sort >"${case_root}/entries.expected"
  find "${artifact}" -mindepth 1 -maxdepth 1 -printf '%f\n' |
    sort >"${case_root}/entries.actual"
  if ! cmp -s "${case_root}/entries.expected" "${case_root}/entries.actual"; then
    diff -u "${case_root}/entries.expected" \
      "${case_root}/entries.actual" >&2 || true
    fail 'sealed artifact entries are not exact'
  fi
  if ! (cd "${artifact}" && sha256sum --check --strict SHA256SUMS); then
    fail 'sealed artifact checksums are invalid'
  fi
  if [[ "$(wc -l <"${artifact}/SHA256SUMS")" -ne 3 ]]; then
    fail 'SHA256SUMS does not cover exactly three payloads'
  fi
  actual_checksum_names="$(
    awk '{name = $2; sub(/^[*]/, "", name); print name}' \
      "${artifact}/SHA256SUMS"
  )"
  if [[ "${actual_checksum_names}" != $'agent-rules.patch\nagent-rules-plan.json\nsource.json' ]]; then
    printf 'Actual checksum payload order: %q\n' \
      "${actual_checksum_names}" >&2
    fail 'SHA256SUMS payload order changed'
  fi
  python - "${artifact}/source.json" "${target_base_commit}" \
    "${source_tag_oid}" "${source_commit}" <<'PY'
import json
import sys

path, base_commit, tag_oid, source_commit = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    actual = json.load(stream)
expected = {
    "version": 1,
    "source": {
        "repository": "asphyx0r/agent-coding-rules",
        "ref": "v1.2.3",
        "tag_oid": tag_oid,
        "commit": source_commit,
    },
    "target": {
        "repository": "asphyx0r/git-starter-kit",
        "default_branch": "main",
        "base_commit": base_commit,
    },
}
if actual != expected:
    raise SystemExit(f"unexpected source.json: {actual!r}")
PY
  for entry in agent-rules.patch agent-rules-plan.json source.json SHA256SUMS; do
    if [[ ! -f "${artifact}/${entry}" || -L "${artifact}/${entry}" ]]; then
      fail "artifact entry is not a regular file: ${entry}"
    fi
  done
}

test_seal_rejects_missing_nonregular_and_executable_rules() {
  local case_root="${test_temp}/seal-invalid-rules"
  local source_commit='2222222222222222222222222222222222222222'
  local source_tag_oid='1111111111111111111111111111111111111111'
  local target="${case_root}/target"
  local target_base_commit

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  target_base_commit="$(git_fixture -C "${target}" rev-parse HEAD)"
  printf '%s\n' '{"actions":[]}' \
    >"${case_root}/runner/agent-rules-plan.json"

  rm -- "${target}/AGENTS.md"
  expect_failure seal-missing-rule 1 \
    'Required agent rule is not a regular file: AGENTS.md' \
    invoke_seal "${case_root}" "${target}" "${target_base_commit}" \
    "${source_tag_oid}" "${source_commit}"
  git_fixture -C "${target}" restore -- AGENTS.md

  git_fixture -C "${target}" update-index --chmod=+x AGENTS.md
  expect_failure seal-executable-rule 1 \
    'Agent rule Git mode must be 100644: AGENTS.md' \
    invoke_seal "${case_root}" "${target}" "${target_base_commit}" \
    "${source_tag_oid}" "${source_commit}"
  git_fixture -C "${target}" reset -q --hard "${target_base_commit}"

  if ln -s BRANCH_RULES.md "${target}/AGENTS.md.link" 2>/dev/null &&
    [[ -L "${target}/AGENTS.md.link" ]]; then
    mv -f -- "${target}/AGENTS.md.link" "${target}/AGENTS.md"
    expect_failure seal-symlink-rule 1 \
      'Required agent rule is not a regular file: AGENTS.md' \
      invoke_seal "${case_root}" "${target}" "${target_base_commit}" \
      "${source_tag_oid}" "${source_commit}"
    rm -- "${target}/AGENTS.md"
    git_fixture -C "${target}" restore -- AGENTS.md
  fi
  if command -v mkfifo >/dev/null 2>&1; then
    rm -- "${target}/AGENTS.md"
    mkfifo "${target}/AGENTS.md"
    expect_failure seal-fifo-rule 1 \
      'Required agent rule is not a regular file: AGENTS.md' \
      invoke_seal "${case_root}" "${target}" "${target_base_commit}" \
      "${source_tag_oid}" "${source_commit}"
    rm -- "${target}/AGENTS.md"
    git_fixture -C "${target}" restore -- AGENTS.md
  fi
}

test_prepare_publish_rejects_extra_artifact_entry() {
  local artifact
  local case_root="${test_temp}/artifact-extra-entry"
  local target="${case_root}/target"
  local target_base_commit

  artifact="${case_root}/runner/agent-rules-transfer"
  mkdir -p "${artifact}"
  initialize_target "${target}"
  target_base_commit="$(git_fixture -C "${target}" rev-parse HEAD)"
  : >"${artifact}/agent-rules.patch"
  printf '%s\n' '{"actions":[]}' >"${artifact}/agent-rules-plan.json"
  printf '%s\n' '{}' >"${artifact}/source.json"
  : >"${artifact}/SHA256SUMS"
  : >"${artifact}/unexpected"

  expect_failure artifact-extra-entry 1 \
    "Unexpected transfer entry: unexpected" \
    invoke_cli "${target}" "${case_root}/runner" \
    "${case_root}/github-output" env \
    TARGET_BASE_COMMIT="${target_base_commit}" \
    bash "${transfer_cli}" prepare-publish
  rm -- "${artifact}/unexpected"

  if ln -s agent-rules-plan.json \
    "${artifact}/agent-rules.patch.link" 2>/dev/null &&
    [[ -L "${artifact}/agent-rules.patch.link" ]]; then
    rm -- "${artifact}/agent-rules.patch"
    mv -- "${artifact}/agent-rules.patch.link" \
      "${artifact}/agent-rules.patch"
    expect_failure artifact-symlink 1 \
      'Transfer entry is not a regular file: agent-rules.patch' \
      invoke_cli "${target}" "${case_root}/runner" \
      "${case_root}/github-output" env \
      TARGET_BASE_COMMIT="${target_base_commit}" \
      bash "${transfer_cli}" prepare-publish
    rm -- "${artifact}/agent-rules.patch"
    : >"${artifact}/agent-rules.patch"
  fi
  rm -f -- "${artifact}/agent-rules.patch.link"

  if command -v mkfifo >/dev/null 2>&1; then
    rm -- "${artifact}/agent-rules-plan.json"
    mkfifo "${artifact}/agent-rules-plan.json"
    expect_failure artifact-fifo 1 \
      'Transfer entry is not a regular file: agent-rules-plan.json' \
      invoke_cli "${target}" "${case_root}/runner" \
      "${case_root}/github-output" env \
      TARGET_BASE_COMMIT="${target_base_commit}" \
      bash "${transfer_cli}" prepare-publish
  fi
}

test_prepare_publish_rejects_integrity_and_base_mismatches() {
  local artifact
  local case_root="${test_temp}/prepare-invalid"
  local target="${case_root}/target"

  create_valid_transfer_fixture "${case_root}"
  artifact="${case_root}/runner/agent-rules-transfer"
  cp -- "${artifact}/agent-rules-plan.json" \
    "${case_root}/agent-rules-plan.original"
  cp -- "${artifact}/agent-rules.patch" "${case_root}/agent-rules.patch.original"
  cp -- "${artifact}/SHA256SUMS" "${case_root}/SHA256SUMS.original"
  printf '%s\n' tampered >>"${artifact}/agent-rules-plan.json"
  expect_failure prepare-tampered-plan 1 \
    'Transfer checksum verification failed.' \
    invoke_prepare_publish "${case_root}"
  cp -- "${case_root}/agent-rules-plan.original" \
    "${artifact}/agent-rules-plan.json"

  printf '%s\n' \
    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff  extra' \
    >>"${artifact}/SHA256SUMS"
  expect_failure prepare-extra-checksum 1 \
    'SHA256SUMS must contain three canonical lines.' \
    invoke_prepare_publish "${case_root}"
  cp -- "${case_root}/SHA256SUMS.original" "${artifact}/SHA256SUMS"

  printf '%s\n' '{"actions":"invalid"}' \
    >"${artifact}/agent-rules-plan.json"
  write_canonical_transfer_checksums "${artifact}"
  expect_failure prepare-invalid-plan 1 \
    'agent-rules-plan.json actions must be an array' \
    invoke_prepare_publish "${case_root}"
  cp -- "${case_root}/agent-rules-plan.original" \
    "${artifact}/agent-rules-plan.json"

  printf '%s\n' \
    'diff --git a/unexpected.txt b/unexpected.txt' \
    'new file mode 100644' \
    'index 0000000000000000000000000000000000000000..e54c9c382afe9e9a1b3d08f25b5109e01171c9c6' \
    '--- /dev/null' \
    '+++ b/unexpected.txt' \
    '@@ -0,0 +1 @@' \
    '+unexpected' >"${artifact}/agent-rules.patch"
  write_canonical_transfer_checksums "${artifact}"
  expect_failure prepare-patch-outside-allowlist 1 \
    'Unexpected patch path: unexpected.txt' \
    invoke_prepare_publish "${case_root}"
  cp -- "${case_root}/agent-rules.patch.original" \
    "${artifact}/agent-rules.patch"
  cp -- "${case_root}/SHA256SUMS.original" "${artifact}/SHA256SUMS"
  git_fixture -C "${target}" switch -q main
  printf '%s\n' advanced >"${target}/base.txt"
  git_fixture -C "${target}" add -- base.txt
  git_fixture -C "${target}" commit -q -m advanced
  expect_failure prepare-wrong-base 1 \
    'Target checkout does not match TARGET_BASE_COMMIT.' \
    invoke_prepare_publish "${case_root}"
}

test_prepare_publish_commits_with_hooks_disabled() {
  local actual_email
  local actual_name
  local case_root="${test_temp}/prepare-valid"
  local target="${case_root}/target"
  local target_commit

  create_valid_transfer_fixture "${case_root}"
  cat >"${target}/.git/hooks/prepare-commit-msg" <<'HOOK'
#!/usr/bin/env bash
printf '%s\n' hook-ran >"${TEST_HOOK_SENTINEL:?}"
exit 91
HOOK
  chmod +x "${target}/.git/hooks/prepare-commit-msg"

  TEST_HOOK_SENTINEL="${case_root}/hook.trace" \
    invoke_prepare_publish "${case_root}"

  assert_gh_api_timeouts "${case_root}" 2

  if [[ -e "${case_root}/hook.trace" ]]; then
    fail 'prepare-commit-msg hook ran during the trusted commit'
  fi
  target_commit="$(git_fixture -C "${target}" rev-parse HEAD)"
  if [[ "$(git_fixture -C "${target}" rev-parse HEAD^)" != "${fixture_target_base_commit}" ]]; then
    fail 'prepared commit parent is not the sealed base commit'
  fi
  if [[ "$(git_fixture -C "${target}" symbolic-ref --short HEAD)" != 'automation/agent-rules-update' ]]; then
    fail 'prepared commit is on the wrong branch'
  fi
  if [[ -n "$(git_fixture -C "${target}" status --porcelain)" ]]; then
    fail 'prepared commit did not leave a clean worktree and index'
  fi
  if [[ "$(git_fixture -C "${target}" log -1 --format=%s)" != 'chore(agents): sync agent rules to v1.2.3' ]]; then
    fail 'prepared commit subject changed'
  fi
  actual_name="$(git_fixture -C "${target}" log -1 --format=%an)"
  actual_email="$(git_fixture -C "${target}" log -1 --format=%ae)"
  actual_name="${actual_name%$'\r'}"
  actual_email="${actual_email%$'\r'}"
  if [[ "${actual_name}" != 'agent-rules-sync[bot]' ||
    "${actual_email}" != '41898282+github-actions[bot]@users.noreply.github.com' ]]; then
    printf 'Actual prepared commit identity: %q <%q>\n' \
      "${actual_name}" "${actual_email}" >&2
    fail 'prepared commit identity changed'
  fi
  if git_fixture -C "${target}" cat-file commit HEAD |
    grep -E '^gpgsig ' >/dev/null; then
    fail 'prepared commit was unexpectedly signed'
  fi
  assert_file_contains "${case_root}/github-output" \
    "target_commit=${target_commit}"
  assert_file_contains "${case_root}/github-output" \
    'expected_remote_oid=absent'
  assert_file_contains "${case_root}/github-output" 'push_required=true'
  if [[ ! -f "${case_root}/runner/agent-rules-pr-body.md" ]]; then
    fail 'prepare-publish did not create the pull request body'
  fi
  cat >"${case_root}/pr-body.expected" <<'PR_BODY_NONE'
Synchronizes rules from the canonical source.

Source release: `v1.2.3`

Customized files preserved:
None.

The repository validation workflow must pass before merge.

Automatic merge is intentionally disabled.
PR_BODY_NONE
  assert_files_equal \
    "${case_root}/pr-body.expected" \
    "${case_root}/runner/agent-rules-pr-body.md" \
    'pull request body without preserved files changed'
}

test_prepare_publish_rejects_self_attested_noncanonical_content() {
  local artifact
  local case_root="${test_temp}/prepare-source-mismatch"
  local target="${case_root}/target"

  create_valid_transfer_fixture "${case_root}"
  artifact="${case_root}/runner/agent-rules-transfer"
  rm -rf -- "${artifact}"
  write_synced_rule_files "${target}" v1.2.3 "${fixture_source_commit}"
  printf '%s\n' 'self-attested but not canonical' >"${target}/AGENTS.md"
  refresh_rule_hash \
    "${target}/_agent-rules-source.json" "${target}/AGENTS.md"
  invoke_seal "${case_root}" "${target}" \
    "${fixture_target_base_commit}" "${fixture_source_tag_oid}" \
    "${fixture_source_commit}"
  git_fixture -C "${target}" reset -q --hard \
    "${fixture_target_base_commit}"

  expect_failure prepare-source-mismatch 1 \
    'Agent rule does not match source or base: AGENTS.md' \
    invoke_prepare_publish "${case_root}"
}

test_prepare_publish_derives_preserved_content_from_base() {
  local artifact
  local case_root="${test_temp}/prepare-preserved-base"
  local target="${case_root}/target"

  create_valid_transfer_fixture "${case_root}"
  artifact="${case_root}/runner/agent-rules-transfer"
  rm -rf -- "${artifact}"
  write_synced_rule_files "${target}" v1.2.3 "${fixture_source_commit}"
  git_fixture -C "${target}" show \
    "${fixture_target_base_commit}:AGENTS.md" >"${target}/AGENTS.md"
  refresh_rule_hash \
    "${target}/_agent-rules-source.json" "${target}/AGENTS.md"
  printf '%s\n' \
    '{"actions":[{"action":"replaced","path":"AGENTS.md"}]}' \
    >"${case_root}/runner/agent-rules-plan.json"
  invoke_seal "${case_root}" "${target}" \
    "${fixture_target_base_commit}" "${fixture_source_tag_oid}" \
    "${fixture_source_commit}"
  git_fixture -C "${target}" reset -q --hard \
    "${fixture_target_base_commit}"

  invoke_prepare_publish "${case_root}"
  cat >"${case_root}/pr-body.expected" <<'PR_BODY_PRESERVED'
Synchronizes rules from the canonical source.

Source release: `v1.2.3`

Customized files preserved:
- `AGENTS.md`

The repository validation workflow must pass before merge.

Automatic merge is intentionally disabled.
PR_BODY_PRESERVED
  assert_files_equal \
    "${case_root}/pr-body.expected" \
    "${case_root}/runner/agent-rules-pr-body.md" \
    'pull request body with a preserved file changed'
}

test_seal_escapes_quoted_default_branch() {
  local artifact
  local case_root="${test_temp}/seal-quoted-branch"
  local source_commit='2222222222222222222222222222222222222222'
  local source_tag_oid='1111111111111111111111111111111111111111'
  local target="${case_root}/target"
  local target_base_commit

  mkdir -p "${case_root}/runner"
  initialize_target "${target}"
  git_fixture check-ref-format --branch 'main"quoted' >/dev/null
  target_base_commit="$(git_fixture -C "${target}" rev-parse HEAD)"
  write_synced_rule_files "${target}" v1.2.3 "${source_commit}"
  printf '%s\n' '{"actions":[]}' \
    >"${case_root}/runner/agent-rules-plan.json"

  invoke_cli "${target}" "${case_root}/runner" \
    "${case_root}/github-output" env \
    TARGET_DEFAULT_BRANCH='main"quoted' \
    TARGET_BASE_COMMIT="${target_base_commit}" \
    SOURCE_REF=v1.2.3 \
    SOURCE_TAG_OID="${source_tag_oid}" \
    SOURCE_COMMIT="${source_commit}" \
    bash "${transfer_cli}" seal
  artifact="${case_root}/runner/agent-rules-transfer"
  python - "${artifact}/source.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    source = json.load(stream)
if source["target"]["default_branch"] != 'main"quoted':
    raise SystemExit("quoted default branch was not preserved")
PY
}

test_prepare_publish_rejects_noncanonical_checksums() {
  local artifact
  local case_root="${test_temp}/prepare-checksum-format"

  create_valid_transfer_fixture "${case_root}"
  artifact="${case_root}/runner/agent-rules-transfer"
  cp -- "${artifact}/SHA256SUMS" \
    "${case_root}/SHA256SUMS.canonical"
  sed '1s/  / */' "${artifact}/SHA256SUMS" \
    >"${case_root}/SHA256SUMS.binary-marker"
  mv -- "${case_root}/SHA256SUMS.binary-marker" \
    "${artifact}/SHA256SUMS"
  expect_failure prepare-binary-checksum-marker 1 \
    'SHA256SUMS must contain three canonical lines.' \
    invoke_prepare_publish "${case_root}"

  cp -- "${case_root}/SHA256SUMS.canonical" \
    "${artifact}/SHA256SUMS"
  python - "${artifact}/SHA256SUMS" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_bytes(path.read_bytes().removesuffix(b"\n"))
PY
  expect_failure prepare-checksum-missing-lf 1 \
    'SHA256SUMS must contain three canonical lines.' \
    invoke_prepare_publish "${case_root}"
}

create_publish_fixture() {
  local case_root="$1"
  local forbidden_command
  local stub_bin="${case_root}/bin"

  mkdir -p "${stub_bin}" "${case_root}/runner" "${case_root}/target"
  printf '%s\n' 'Agent rules update.' \
    >"${case_root}/runner/agent-rules-pr-body.md"
  publish_target_commit="$(printf 'a%.0s' {1..40})"

  cat >"${stub_bin}/git" <<'GIT_STUB'
#!/usr/bin/env bash
set -euo pipefail

printf 'git' >>"${TEST_COMMAND_TRACE:?}"
printf ' %q' "$@" >>"${TEST_COMMAND_TRACE}"
printf '\n' >>"${TEST_COMMAND_TRACE}"
printf '%q ' "$@" >>"${TEST_GIT_TRACE:?}"
printf '\n' >>"${TEST_GIT_TRACE}"
case " $* " in
*" rev-parse --show-toplevel "*) pwd ;;
*" rev-parse --git-dir "*) printf '%s\n' .git ;;
*" rev-parse --git-common-dir "*) printf '%s\n' .git ;;
*" rev-parse HEAD "*) printf '%s\n' "${TEST_TARGET_COMMIT:?}" ;;
*" status --porcelain "*) ;;
*" symbolic-ref --short HEAD "*)
  printf '%s\n' automation/agent-rules-update
  ;;
*" remote get-url origin "*)
  printf '%s\n' https://github.com/asphyx0r/git-starter-kit.git
  ;;
*" ls-remote --exit-code --heads origin refs/heads/automation/agent-rules-update "*)
  printf '%s\n' "${GIT_ASKPASS:-}" >"${TEST_ASKPASS_TRACE:?}"
  if [[ "${TEST_REMOTE_OID:?}" == absent ]]; then
    exit 2
  fi
  printf '%s\t%s\n' "${TEST_REMOTE_OID}" \
    refs/heads/automation/agent-rules-update
  ;;
*" push "*)
  printf '%s\n' "${GIT_ASKPASS:-}" >"${TEST_ASKPASS_TRACE:?}"
  if [[ -z "${GIT_ASKPASS:-}" || ! -f "${GIT_ASKPASS}" ]]; then
    printf '%s\n' 'Missing ephemeral GIT_ASKPASS helper.' >&2
    exit 91
  fi
  if grep -F -- "${GH_TOKEN:?}" "${GIT_ASKPASS}" >/dev/null; then
    printf '%s\n' 'Token was written to the askpass helper.' >&2
    exit 92
  fi
  case "${TEST_PUSH_RESULT:?}" in
  success) ;;
  failure)
    printf '%s\n' 'lease rejected by remote' >&2
    exit 93
    ;;
  signal)
    kill -TERM "${PPID}"
    exit 143
    ;;
  *) exit 94 ;;
  esac
  ;;
*) ;;
esac
GIT_STUB
  cat >"${stub_bin}/gh" <<'GH_STUB'
#!/usr/bin/env bash
set -euo pipefail

printf 'gh' >>"${TEST_COMMAND_TRACE:?}"
printf ' %q' "$@" >>"${TEST_COMMAND_TRACE}"
printf '\n' >>"${TEST_COMMAND_TRACE}"
printf '%q ' "$@" >>"${TEST_GH_TRACE:?}"
printf '\n' >>"${TEST_GH_TRACE}"
if [[ "${1:-} ${2:-}" == "pr list" ]]; then
  printf '%b' "${TEST_PR_LIST:?}"
fi
GH_STUB
  chmod +x "${stub_bin}/git" "${stub_bin}/gh"
  cat >"${stub_bin}/forbidden-command" <<'FORBIDDEN_STUB'
#!/usr/bin/env bash
printf 'forbidden %q' "$0" >>"${TEST_COMMAND_TRACE:?}"
printf ' %q' "$@" >>"${TEST_COMMAND_TRACE}"
printf '\n' >>"${TEST_COMMAND_TRACE}"
exit 95
FORBIDDEN_STUB
  for forbidden_command in \
    python \
    python3 \
    ruff \
    mypy \
    coverage \
    yamllint \
    actionlint \
    shellcheck \
    shfmt \
    codespell \
    markdownlint-cli2 \
    pre-commit; do
    cp -- "${stub_bin}/forbidden-command" \
      "${stub_bin}/${forbidden_command}"
    chmod +x "${stub_bin}/${forbidden_command}"
  done
  rm -- "${stub_bin}/forbidden-command"
}

invoke_publish() {
  local case_root="$1"
  local expected_remote_oid="$2"
  local push_required="$3"
  local remote_oid="$4"
  local pr_list="$5"
  local push_result="${6:-success}"
  local stub_bin="${case_root}/bin"
  local target="${case_root}/target"

  (
    cd "${target}"
    timeout --kill-after=5s 20s env \
      PATH="${stub_bin}:${PATH}" \
      RUNNER_TEMP="${case_root}/runner" \
      GH_TOKEN="${publish_auth_marker}" \
      TARGET_REPOSITORY=asphyx0r/git-starter-kit \
      TARGET_DEFAULT_BRANCH=main \
      TARGET_COMMIT="${publish_target_commit}" \
      SOURCE_REF=v1.2.3 \
      EXPECTED_REMOTE_OID="${expected_remote_oid}" \
      PUSH_REQUIRED="${push_required}" \
      SYNC_BRANCH=automation/agent-rules-update \
      TEST_TARGET_COMMIT="${publish_target_commit}" \
      TEST_REMOTE_OID="${remote_oid}" \
      TEST_PR_LIST="${pr_list}" \
      TEST_PUSH_RESULT="${push_result}" \
      TEST_COMMAND_TRACE="${case_root}/commands.trace" \
      TEST_GIT_TRACE="${case_root}/git.trace" \
      TEST_GH_TRACE="${case_root}/gh.trace" \
      TEST_ASKPASS_TRACE="${case_root}/askpass.trace" \
      bash "${transfer_cli}" publish
  )
}

assert_publish_cleanup() {
  local askpass_path
  local case_root="$1"

  if [[ ! -f "${case_root}/askpass.trace" ]]; then
    fail "publication did not expose its askpass path to the Git stub"
  fi
  askpass_path="$(cat "${case_root}/askpass.trace")"
  if [[ -z "${askpass_path}" || -e "${askpass_path}" ]]; then
    fail "ephemeral askpass helper survived publication"
  fi
}

assert_no_pr_command() {
  local case_root="$1"

  if [[ -s "${case_root}/gh.trace" ]]; then
    sed 's/^/  /' "${case_root}/gh.trace" >&2
    fail 'publication failure was followed by a pull request command'
  fi
}

assert_no_forbidden_publish_command() {
  local case_root="$1"

  if grep -E \
    '(^|[[:space:]])(apply|add|commit|fetch|switch|checkout)([[:space:]]|$)|^gh auth|^forbidden ' \
    "${case_root}/commands.trace" >/dev/null; then
    sed 's/^/  /' "${case_root}/commands.trace" >&2
    fail 'an unsafe command ran after the App token was exposed'
  fi
}

test_publish_uses_absent_ref_lease_and_explicit_pr() {
  local case_root="${test_temp}/publish-absent-lease"

  create_publish_fixture "${case_root}"
  invoke_publish "${case_root}" absent true \
    "${publish_target_commit}" '[]\n'

  assert_file_contains "${case_root}/git.trace" \
    "--force-with-lease=refs/heads/automation/agent-rules-update:"
  assert_file_contains "${case_root}/gh.trace" \
    "--repo asphyx0r/git-starter-kit"
  assert_file_contains "${case_root}/gh.trace" \
    "--head automation/agent-rules-update"
  assert_file_contains "${case_root}/gh.trace" "--base main"
  if grep -F -- "${publish_auth_marker}" \
    "${case_root}/git.trace" "${case_root}/gh.trace" >/dev/null; then
    fail "App token leaked to a command argument"
  fi
  assert_publish_cleanup "${case_root}"
  assert_no_forbidden_publish_command "${case_root}"
}

test_publish_revalidates_no_push_ref_before_editing_pr() {
  local expected_oid
  local moved_oid
  local case_root="${test_temp}/publish-no-push"

  expected_oid="$(printf 'b%.0s' {1..40})"
  moved_oid="$(printf 'c%.0s' {1..40})"
  create_publish_fixture "${case_root}"
  expect_failure publish-no-push-race 1 \
    'Remote automation branch moved after preparation.' \
    invoke_publish "${case_root}" "${expected_oid}" false \
    "${moved_oid}" '42\n'
  assert_no_pr_command "${case_root}"
  assert_publish_cleanup "${case_root}"
  assert_no_forbidden_publish_command "${case_root}"

  rm -f -- "${case_root}/commands.trace" "${case_root}/git.trace" \
    "${case_root}/gh.trace" "${case_root}/askpass.trace"
  invoke_publish "${case_root}" "${expected_oid}" false \
    "${expected_oid}" '42\n'
  assert_file_contains "${case_root}/git.trace" \
    'ls-remote --exit-code --heads origin refs/heads/automation/agent-rules-update'
  assert_file_contains "${case_root}/gh.trace" 'pr edit 42'
  if grep -F -- ' push ' "${case_root}/git.trace" >/dev/null; then
    fail 'no-push publication unexpectedly pushed the branch'
  fi
  assert_publish_cleanup "${case_root}"
  assert_no_forbidden_publish_command "${case_root}"
}

test_publish_revalidates_pushed_commit_before_creating_pr() {
  local moved_oid
  local case_root="${test_temp}/publish-post-push-race"

  moved_oid="$(printf 'c%.0s' {1..40})"
  create_publish_fixture "${case_root}"
  expect_failure publish-post-push-race 1 \
    'Remote automation branch moved after publication.' \
    invoke_publish "${case_root}" absent true \
    "${moved_oid}" '[]\n'
  assert_no_pr_command "${case_root}"
  assert_publish_cleanup "${case_root}"
  assert_no_forbidden_publish_command "${case_root}"
}

test_publish_enforces_existing_lease_and_stops_before_pr_on_failure() {
  local expected_oid
  local case_root="${test_temp}/publish-existing-lease"

  expected_oid="$(printf 'b%.0s' {1..40})"
  create_publish_fixture "${case_root}"
  invoke_publish "${case_root}" "${expected_oid}" true \
    "${publish_target_commit}" '[]\n'
  assert_file_contains "${case_root}/git.trace" \
    "--force-with-lease=refs/heads/automation/agent-rules-update:${expected_oid}"
  assert_publish_cleanup "${case_root}"
  assert_no_forbidden_publish_command "${case_root}"

  rm -f -- "${case_root}/commands.trace" "${case_root}/git.trace" \
    "${case_root}/gh.trace" "${case_root}/askpass.trace"
  expect_failure publish-lease-race 93 'lease rejected by remote' \
    invoke_publish "${case_root}" "${expected_oid}" true \
    "${expected_oid}" '[]\n' failure
  assert_no_pr_command "${case_root}"
  assert_publish_cleanup "${case_root}"
  assert_no_forbidden_publish_command "${case_root}"
}

test_publish_rejects_multiple_prs_and_cleans_up_after_signal() {
  local case_root="${test_temp}/publish-pr-and-signal"
  local status

  create_publish_fixture "${case_root}"
  expect_failure publish-multiple-prs 1 \
    'Multiple open agent rules pull requests found.' \
    invoke_publish "${case_root}" absent true \
    "${publish_target_commit}" '12\n13\n'
  assert_publish_cleanup "${case_root}"
  assert_no_forbidden_publish_command "${case_root}"

  rm -f -- "${case_root}/commands.trace" "${case_root}/git.trace" \
    "${case_root}/gh.trace" "${case_root}/askpass.trace"
  set +e
  invoke_publish "${case_root}" absent true absent '[]\n' signal \
    >"${case_root}/signal.out" 2>"${case_root}/signal.err"
  status=$?
  set -e
  if ((status != 143)); then
    sed 's/^/  /' "${case_root}/signal.err" >&2
    fail "signal publication returned ${status}, expected 143"
  fi
  assert_no_pr_command "${case_root}"
  assert_publish_cleanup "${case_root}"
  assert_no_forbidden_publish_command "${case_root}"
}

run_core_tests() {
  test_cli_rejects_missing_subcommand
}

run_provenance_tests() {
  test_resolve_preserves_tag_object_and_commit_identity
  test_resolve_rejects_latest_and_ref_races
  test_resolve_rejects_non_commit_peeled_object
  test_resolve_accepts_sha256_when_supported
}

run_resolve_validation_tests() {
  test_resolve_rejects_invalid_semver_and_mixed_oids
  test_resolve_rejects_noncanonical_target_roots
}

run_seal_tests() {
  test_seal_rejects_path_outside_allowlist
  test_seal_creates_exact_verified_artifact
  test_seal_rejects_missing_nonregular_and_executable_rules
}

run_prepare_tests() {
  test_prepare_publish_rejects_extra_artifact_entry
  test_prepare_publish_rejects_integrity_and_base_mismatches
  test_prepare_publish_commits_with_hooks_disabled
}

run_provenance_content_tests() {
  test_prepare_publish_rejects_self_attested_noncanonical_content
  test_prepare_publish_derives_preserved_content_from_base
}

run_transport_tests() {
  test_seal_escapes_quoted_default_branch
  test_prepare_publish_rejects_noncanonical_checksums
}

run_publish_tests() {
  test_publish_uses_absent_ref_lease_and_explicit_pr
  test_publish_revalidates_no_push_ref_before_editing_pr
  test_publish_revalidates_pushed_commit_before_creating_pr
  test_publish_enforces_existing_lease_and_stops_before_pr_on_failure
  test_publish_rejects_multiple_prs_and_cleans_up_after_signal
}

main() {
  local group="${1:-all}"

  if [[ ! -f "${transfer_cli}" ]]; then
    fail \
      "Agent rules transfer CLI is missing: tools/repository-audit/agent-rules-transfer.sh"
  fi
  if ! command -v timeout >/dev/null 2>&1; then
    fail "required test command is missing: timeout"
  fi

  case "${group}" in
  all)
    run_core_tests
    run_provenance_tests
    run_resolve_validation_tests
    run_seal_tests
    run_prepare_tests
    run_provenance_content_tests
    run_transport_tests
    run_publish_tests
    ;;
  core) run_core_tests ;;
  provenance) run_provenance_tests ;;
  resolve-validation) run_resolve_validation_tests ;;
  seal) run_seal_tests ;;
  prepare) run_prepare_tests ;;
  prepare-invalid)
    test_prepare_publish_rejects_extra_artifact_entry
    test_prepare_publish_rejects_integrity_and_base_mismatches
    ;;
  prepare-nominal) test_prepare_publish_commits_with_hooks_disabled ;;
  provenance-content) run_provenance_content_tests ;;
  transport) run_transport_tests ;;
  transport-json) test_seal_escapes_quoted_default_branch ;;
  transport-checksum) test_prepare_publish_rejects_noncanonical_checksums ;;
  artifact-types) test_prepare_publish_rejects_extra_artifact_entry ;;
  publish) run_publish_tests ;;
  publish-post-push)
    test_publish_revalidates_pushed_commit_before_creating_pr
    ;;
  *) fail "unknown test group: ${group}" ;;
  esac
  printf '%s\n' 'PASS: agent rules transfer'
}

main "$@"
