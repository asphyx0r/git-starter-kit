#!/usr/bin/env bash
set -euo pipefail

readonly source_repository_default='asphyx0r/agent-coding-rules'
readonly sync_branch_default='automation/agent-rules-update'
readonly semver_tag_pattern='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$'
readonly -a agent_rule_paths=(
  AGENTS.md
  BRANCH_RULES.md
  CODING_RULES.md
  COMMIT_RULES.md
  DOCUMENTATION_RULES.md
  LANGUAGE_RULES.md
  RELEASE_RULES.md
  _agent-rules-source.json
)

fail() {
  printf '%s\n' "$1" >&2
  return 1
}

run_gh_api() {
  timeout --kill-after=5s 30s gh api "$@"
}

require_value() {
  local name="$1"
  local value="${!name:-}"

  if [[ -z "${value}" || "${value}" == *$'\r'* || "${value}" == *$'\n'* ]]; then
    fail "Missing or invalid ${name}."
  fi
}

require_oid() {
  local name="$1"
  local value="${!name:-}"

  require_value "${name}"
  if [[ ! "${value}" =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]]; then
    fail "Invalid ${name}: ${value}"
  fi
}

require_target_checkout() {
  local common_dir
  local git_dir
  local top_level

  top_level="$(git rev-parse --show-toplevel)"
  if [[ "$(cd "${top_level}" && pwd -P)" != "$(pwd -P)" ]]; then
    fail 'The target checkout must be the current top-level directory.'
  fi
  git_dir="$(git rev-parse --git-dir)"
  if [[ "${git_dir}" != '.git' ]]; then
    fail 'The target checkout must use its own .git directory.'
  fi
  common_dir="$(git rev-parse --git-common-dir)"
  if [[ "${common_dir}" != '.git' ]]; then
    fail 'The target checkout must use its own .git common directory.'
  fi
}

is_agent_rule_path() {
  local candidate="$1"
  local allowed

  for allowed in "${agent_rule_paths[@]}"; do
    if [[ "${candidate}" == "${allowed}" ]]; then
      return 0
    fi
  done
  return 1
}

read_remote_source_tag() {
  local source_ref="$1"
  local source_url="$2"
  local line
  local oid
  local ref
  local output
  remote_source_tag_oid=''
  remote_source_commit=''

  output="$(
    GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never \
      git -c credential.helper= -c core.askPass=/bin/false \
      ls-remote --tags --exit-code "${source_url}" \
      "refs/tags/${source_ref}" "refs/tags/${source_ref}^{}"
  )"
  while IFS=$'\t' read -r oid ref; do
    [[ -n "${oid}" ]] || continue
    case "${ref}" in
    "refs/tags/${source_ref}")
      if [[ -n "${remote_source_tag_oid}" ]]; then
        fail 'Source tag query returned duplicate direct objects.'
      fi
      remote_source_tag_oid="${oid}"
      ;;
    "refs/tags/${source_ref}^{}")
      if [[ -n "${remote_source_commit}" ]]; then
        fail 'Source tag query returned duplicate peeled objects.'
      fi
      remote_source_commit="${oid}"
      ;;
    *) fail "Unexpected source ref returned: ${ref}" ;;
    esac
  done <<<"${output}"
  if [[ -z "${remote_source_tag_oid}" ]]; then
    fail "Source tag was not found: ${source_ref}"
  fi
  if [[ -z "${remote_source_commit}" ]]; then
    remote_source_commit="${remote_source_tag_oid}"
  fi
  require_oid remote_source_tag_oid
  require_oid remote_source_commit
  if ((${#remote_source_tag_oid} != ${#remote_source_commit})); then
    fail 'Source tag object formats do not match.'
  fi
}

write_github_output() {
  local name="$1"
  local value="$2"

  if [[ ! "${name}" =~ ^[a-z_]+$ ]]; then
    fail "Invalid output name: ${name}"
  fi
  if [[ -z "${value}" || "${value}" == *$'\r'* || "${value}" == *$'\n'* ]]; then
    fail "Invalid output value: ${name}"
  fi
  printf '%s=%s\n' "${name}" "${value}" >>"${GITHUB_OUTPUT:?}"
}

resolve_transfer() {
  local first_source_commit
  local first_source_tag_oid
  local latest_again
  local local_source_commit
  local local_source_tag_oid
  local source_checkout="${RUNNER_TEMP:?}/agent-rules-source"
  local source_object_format
  local source_ref
  local source_repository="${RULES_REPOSITORY:-${source_repository_default}}"
  local source_url
  local target_base_commit

  require_target_checkout
  require_value GH_TOKEN
  require_value TARGET_REPOSITORY
  require_value TARGET_DEFAULT_BRANCH
  require_value source_repository
  if [[ ! "${source_repository}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    fail "Invalid RULES_REPOSITORY: ${source_repository}"
  fi
  # TARGET_REPOSITORY is validated indirectly by require_value above.
  # shellcheck disable=SC2153
  if [[ ! "${TARGET_REPOSITORY}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    fail "Invalid TARGET_REPOSITORY: ${TARGET_REPOSITORY}"
  fi
  if ! git check-ref-format --branch "${TARGET_DEFAULT_BRANCH}" >/dev/null; then
    fail "Invalid TARGET_DEFAULT_BRANCH: ${TARGET_DEFAULT_BRANCH}"
  fi
  if [[ "$(git symbolic-ref --short HEAD)" != "${TARGET_DEFAULT_BRANCH}" ]]; then
    fail 'Target checkout is not on its declared default branch.'
  fi
  target_base_commit="$(git rev-parse HEAD)"
  TARGET_BASE_COMMIT="${target_base_commit}"
  require_oid TARGET_BASE_COMMIT

  source_ref="$(
    run_gh_api "repos/${source_repository}/releases/latest" --jq '.tag_name'
  )"
  if [[ ! "${source_ref}" =~ ${semver_tag_pattern} ]]; then
    fail "Invalid source release tag: ${source_ref}"
  fi
  source_url="https://github.com/${source_repository}.git"
  read_remote_source_tag "${source_ref}" "${source_url}"
  first_source_tag_oid="${remote_source_tag_oid}"
  first_source_commit="${remote_source_commit}"
  if ((${#first_source_tag_oid} == 64)); then
    source_object_format=sha256
  else
    source_object_format=sha1
  fi

  if [[ -e "${source_checkout}" ]]; then
    fail "Source checkout path already exists: ${source_checkout}"
  fi
  git init -q --object-format="${source_object_format}" "${source_checkout}"
  git -C "${source_checkout}" remote add origin "${source_url}"
  GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never \
    git -C "${source_checkout}" \
    -c credential.helper= -c core.askPass=/bin/false \
    fetch --no-tags --depth=1 origin \
    "+refs/tags/${source_ref}:refs/tags/${source_ref}"
  local_source_tag_oid="$(
    git -C "${source_checkout}" rev-parse "refs/tags/${source_ref}"
  )"
  if ! local_source_commit="$(
    git -C "${source_checkout}" \
      rev-parse "refs/tags/${source_ref}^{commit}" 2>/dev/null
  )"; then
    fail 'Source tag does not peel to a commit.'
  fi
  if [[ "$(git -C "${source_checkout}" cat-file -t \
    "${local_source_commit}")" != 'commit' ]]; then
    fail 'Source tag does not peel to a commit.'
  fi
  if [[ "${local_source_tag_oid}" != "${first_source_tag_oid}" ||
    "${local_source_commit}" != "${first_source_commit}" ]]; then
    fail 'Fetched source tag identity differs from the remote query.'
  fi
  git -C "${source_checkout}" checkout -q --detach "${local_source_commit}"

  latest_again="$(
    run_gh_api "repos/${source_repository}/releases/latest" --jq '.tag_name'
  )"
  if [[ "${latest_again}" != "${source_ref}" ]]; then
    fail 'Latest source release changed during resolution.'
  fi
  read_remote_source_tag "${source_ref}" "${source_url}"
  if [[ "${remote_source_tag_oid}" != "${first_source_tag_oid}" ||
    "${remote_source_commit}" != "${first_source_commit}" ]]; then
    fail 'Source tag changed during resolution.'
  fi

  write_github_output target_repository "${TARGET_REPOSITORY}"
  write_github_output target_default_branch "${TARGET_DEFAULT_BRANCH}"
  write_github_output target_base_commit "${target_base_commit}"
  write_github_output source_ref "${source_ref}"
  write_github_output source_tag_oid "${first_source_tag_oid}"
  write_github_output source_commit "${first_source_commit}"
}

seal_transfer() {
  local artifact_root="${RUNNER_TEMP:?}/agent-rules-transfer"
  local changed_path
  local git_mode
  local path
  local plan_path="${RUNNER_TEMP:?}/agent-rules-plan.json"
  local python_cmd
  local source_repository="${RULES_REPOSITORY:-${source_repository_default}}"

  require_target_checkout
  require_oid TARGET_BASE_COMMIT
  require_value SOURCE_REF
  require_oid SOURCE_TAG_OID
  require_oid SOURCE_COMMIT
  require_value TARGET_REPOSITORY
  require_value TARGET_DEFAULT_BRANCH
  if [[ ! "${source_repository}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ || ! "${TARGET_REPOSITORY}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    fail 'Source or target repository slug is invalid.'
  fi
  # SOURCE_REF is validated indirectly by require_value above.
  # shellcheck disable=SC2153
  if [[ ! "${SOURCE_REF}" =~ ${semver_tag_pattern} ]]; then
    fail "Invalid source release tag: ${SOURCE_REF}"
  fi

  if [[ "$(git rev-parse HEAD)" != "${TARGET_BASE_COMMIT}" ]]; then
    fail 'Target checkout does not match TARGET_BASE_COMMIT.'
  fi

  for path in "${agent_rule_paths[@]}"; do
    if [[ ! -f "${path}" || -L "${path}" ]]; then
      fail "Required agent rule is not a regular file: ${path}"
    fi
  done

  git add -A
  while IFS= read -r -d '' changed_path; do
    if ! is_agent_rule_path "${changed_path}"; then
      fail "Unexpected changed path: ${changed_path}"
    fi
  done < <(
    git diff --cached --name-only -z --no-renames \
      "${TARGET_BASE_COMMIT}" --
  )

  for path in "${agent_rule_paths[@]}"; do
    git_mode="$(git ls-files -s -- "${path}")"
    git_mode="${git_mode%% *}"
    if [[ "${git_mode}" != '100644' ]]; then
      fail "Agent rule Git mode must be 100644: ${path}"
    fi
  done
  if ! git diff --cached --check; then
    fail 'Agent rules update contains whitespace errors.'
  fi
  if git diff --cached --quiet "${TARGET_BASE_COMMIT}" --; then
    write_github_output changed false
    return 0
  fi
  if [[ ! -f "${plan_path}" || -L "${plan_path}" ]]; then
    fail "Agent rules plan is not a regular file: ${plan_path}"
  fi
  if [[ -e "${artifact_root}" ]]; then
    fail "Transfer artifact path already exists: ${artifact_root}"
  fi

  python_cmd="$(command -v python || command -v python3)"
  (umask 077 && mkdir "${artifact_root}")
  git diff --cached --binary --full-index --no-renames \
    "${TARGET_BASE_COMMIT}" -- "${agent_rule_paths[@]}" \
    >"${artifact_root}/agent-rules.patch"
  cp -- "${plan_path}" "${artifact_root}/agent-rules-plan.json"
  "${python_cmd}" - \
    "${artifact_root}/source.json" \
    "${source_repository}" \
    "${SOURCE_REF}" \
    "${SOURCE_TAG_OID}" \
    "${SOURCE_COMMIT}" \
    "${TARGET_REPOSITORY}" \
    "${TARGET_DEFAULT_BRANCH}" \
    "${TARGET_BASE_COMMIT}" <<'PY'
import json
import pathlib
import sys

(
    output_path,
    source_repository,
    source_ref,
    source_tag_oid,
    source_commit,
    target_repository,
    target_default_branch,
    target_base_commit,
) = sys.argv[1:]
payload = {
    "version": 1,
    "source": {
        "repository": source_repository,
        "ref": source_ref,
        "tag_oid": source_tag_oid,
        "commit": source_commit,
    },
    "target": {
        "repository": target_repository,
        "default_branch": target_default_branch,
        "base_commit": target_base_commit,
    },
}
with pathlib.Path(output_path).open("w", encoding="utf-8", newline="\n") as stream:
    json.dump(payload, stream, indent=2)
    stream.write("\n")
PY
  "${python_cmd}" - "${artifact_root}" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
names = ("agent-rules.patch", "agent-rules-plan.json", "source.json")
lines = [f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}" for name in names]
(root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
PY
  write_github_output changed true
}

prepare_publish() {
  local artifact_root="${RUNNER_TEMP:?}/agent-rules-transfer"
  local base_blob_oid
  local base_snapshot_root="${RUNNER_TEMP:?}/agent-rules-base-files"
  local branch_json
  local branch_json_path="${RUNNER_TEMP:?}/agent-rules-branch.json"
  local branch_oid
  local branch_state
  local branch_tree
  local expected_remote_oid
  local entry
  local entry_name
  local git_mode
  local latest_ref
  local owner
  local path
  local patch_path="${artifact_root}/agent-rules.patch"
  local patch_paths="${RUNNER_TEMP:?}/agent-rules-patch-paths"
  local preserved_file="${RUNNER_TEMP:?}/agent-rules-preserved.md"
  local pr_body="${RUNNER_TEMP:?}/agent-rules-pr-body.md"
  local python_cmd
  local repository_name
  local source_checkout="${RUNNER_TEMP:?}/agent-rules-verified-source"
  local source_commit_local
  local source_git_mode
  local source_object_format
  local source_repository="${RULES_REPOSITORY:-${source_repository_default}}"
  local source_snapshot_root="${RUNNER_TEMP:?}/agent-rules-source-files"
  local source_tag_oid_local
  local staged_path
  local sync_branch="${SYNC_BRANCH:-${sync_branch_default}}"
  local target_commit
  local target_tree

  require_target_checkout
  if [[ ! -d "${artifact_root}" ]]; then
    fail "Transfer artifact is missing: ${artifact_root}"
  fi

  while IFS= read -r -d '' entry; do
    entry_name="${entry##*/}"
    case "${entry_name}" in
    agent-rules.patch | agent-rules-plan.json | source.json | SHA256SUMS) ;;
    *) fail "Unexpected transfer entry: ${entry_name}" ;;
    esac
  done < <(find "${artifact_root}" -mindepth 1 -maxdepth 1 -print0)

  for entry_name in \
    agent-rules.patch \
    agent-rules-plan.json \
    source.json \
    SHA256SUMS; do
    entry="${artifact_root}/${entry_name}"
    if [[ ! -f "${entry}" || -L "${entry}" ]]; then
      fail "Transfer entry is not a regular file: ${entry_name}"
    fi
  done

  require_value GH_TOKEN
  require_value TARGET_REPOSITORY
  require_value TARGET_DEFAULT_BRANCH
  require_oid TARGET_BASE_COMMIT
  require_value SOURCE_REF
  require_oid SOURCE_TAG_OID
  require_oid SOURCE_COMMIT
  if [[ ! "${source_repository}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ || ! "${TARGET_REPOSITORY}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    fail 'Source or target repository slug is invalid.'
  fi
  if [[ ! "${SOURCE_REF}" =~ ${semver_tag_pattern} ]]; then
    fail "Invalid source release tag: ${SOURCE_REF}"
  fi

  python_cmd="$(command -v python || command -v python3)"
  "${python_cmd}" - "${artifact_root}/SHA256SUMS" <<'PY'
import pathlib
import re
import sys

data = pathlib.Path(sys.argv[1]).read_bytes()
names = (b"agent-rules.patch", b"agent-rules-plan.json", b"source.json")
lines = data.splitlines(keepends=True)
if len(lines) != len(names) or any(
    re.fullmatch(rb"[0-9a-f]{64}  " + re.escape(name) + rb"\n", line) is None
    for line, name in zip(lines, names)
):
    raise SystemExit("SHA256SUMS must contain three canonical lines.")
PY
  if ! (cd "${artifact_root}" &&
    sha256sum --check --strict SHA256SUMS >/dev/null); then
    fail 'Transfer checksum verification failed.'
  fi

  "${python_cmd}" - \
    "${artifact_root}/source.json" \
    "${source_repository}" \
    "${SOURCE_REF}" \
    "${SOURCE_TAG_OID}" \
    "${SOURCE_COMMIT}" \
    "${TARGET_REPOSITORY}" \
    "${TARGET_DEFAULT_BRANCH}" \
    "${TARGET_BASE_COMMIT}" <<'PY'
import json
import sys

(
    path,
    source_repository,
    source_ref,
    source_tag_oid,
    source_commit,
    target_repository,
    target_default_branch,
    target_base_commit,
) = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    actual = json.load(stream)
expected = {
    "version": 1,
    "source": {
        "repository": source_repository,
        "ref": source_ref,
        "tag_oid": source_tag_oid,
        "commit": source_commit,
    },
    "target": {
        "repository": target_repository,
        "default_branch": target_default_branch,
        "base_commit": target_base_commit,
    },
}
if actual != expected:
    raise SystemExit("source.json does not match the sealed identities")
PY
  "${python_cmd}" - "${artifact_root}/agent-rules-plan.json" <<'PY'
import json
import sys

plan_path = sys.argv[1]
allowed_paths = {
    "AGENTS.md",
    "BRANCH_RULES.md",
    "CODING_RULES.md",
    "COMMIT_RULES.md",
    "DOCUMENTATION_RULES.md",
    "LANGUAGE_RULES.md",
    "RELEASE_RULES.md",
    "_agent-rules-source.json",
}
with open(plan_path, encoding="utf-8") as stream:
    plan = json.load(stream)
if not isinstance(plan, dict) or not isinstance(plan.get("actions"), list):
    raise SystemExit("agent-rules-plan.json actions must be an array")
for item in plan["actions"]:
    if not isinstance(item, dict):
        raise SystemExit("agent-rules-plan.json action must be an object")
    action = item.get("action")
    path = item.get("path")
    if not isinstance(action, str) or not isinstance(path, str):
        raise SystemExit("agent-rules-plan.json action and path must be strings")
    if any(ord(character) < 32 or ord(character) == 127 for character in action + path):
        raise SystemExit("agent-rules-plan.json contains a control character")
    if path not in allowed_paths:
        raise SystemExit(f"agent-rules-plan.json path is not allowed: {path}")
PY

  if [[ "$(git rev-parse HEAD)" != "${TARGET_BASE_COMMIT}" ]]; then
    fail 'Target checkout does not match TARGET_BASE_COMMIT.'
  fi
  latest_ref="$(
    run_gh_api "repos/${source_repository}/releases/latest" --jq '.tag_name'
  )"
  if [[ "${latest_ref}" != "${SOURCE_REF}" ]]; then
    fail 'Latest source release differs from the sealed release.'
  fi
  read_remote_source_tag "${SOURCE_REF}" \
    "https://github.com/${source_repository}.git"
  if [[ "${remote_source_tag_oid}" != "${SOURCE_TAG_OID}" ||
    "${remote_source_commit}" != "${SOURCE_COMMIT}" ]]; then
    fail 'Source tag differs from the sealed identities.'
  fi
  if ((${#SOURCE_COMMIT} == 64)); then
    source_object_format=sha256
  else
    source_object_format=sha1
  fi
  if [[ -e "${source_checkout}" || -e "${source_snapshot_root}" || -e "${base_snapshot_root}" ]]; then
    fail 'Source verification path already exists.'
  fi
  mkdir "${source_snapshot_root}" "${base_snapshot_root}"
  git init -q --object-format="${source_object_format}" "${source_checkout}"
  git -C "${source_checkout}" remote add origin \
    "https://github.com/${source_repository}.git"
  GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never \
    git -c credential.helper= -c core.askPass=/bin/false \
    -C "${source_checkout}" fetch --no-tags --depth=1 origin \
    "refs/tags/${SOURCE_REF}:refs/tags/${SOURCE_REF}"
  source_tag_oid_local="$(
    git -C "${source_checkout}" rev-parse "refs/tags/${SOURCE_REF}"
  )"
  source_commit_local="$(
    git -C "${source_checkout}" rev-parse "refs/tags/${SOURCE_REF}^{commit}"
  )"
  if [[ "${source_tag_oid_local}" != "${SOURCE_TAG_OID}" ||
    "${source_commit_local}" != "${SOURCE_COMMIT}" ]]; then
    fail 'Fetched source tag differs from the sealed identities.'
  fi
  if [[ "$(
    git -C "${source_checkout}" cat-file -t "${source_commit_local}"
  )" != 'commit' ]]; then
    fail 'Fetched source tag does not peel to a commit.'
  fi
  git -C "${source_checkout}" checkout -q --detach "${SOURCE_COMMIT}"
  for path in "${agent_rule_paths[@]}"; do
    if [[ "${path}" == '_agent-rules-source.json' ]]; then
      continue
    fi
    source_git_mode="$(
      git -C "${source_checkout}" ls-tree "${SOURCE_COMMIT}" -- "${path}"
    )"
    source_git_mode="${source_git_mode%% *}"
    if [[ "${source_git_mode}" != '100644' ]]; then
      fail "Source agent rule Git mode must be 100644: ${path}"
    fi
    git -C "${source_checkout}" show \
      "${SOURCE_COMMIT}:${path}" >"${source_snapshot_root}/${path}"
    if base_blob_oid="$(
      git rev-parse "${TARGET_BASE_COMMIT}:${path}" 2>/dev/null
    )"; then
      if [[ "$(git cat-file -t "${base_blob_oid}")" != 'blob' ]]; then
        fail "Base agent rule is not a blob: ${path}"
      fi
      git show "${TARGET_BASE_COMMIT}:${path}" \
        >"${base_snapshot_root}/${path}"
    fi
  done

  if ! git apply --numstat -z "${patch_path}" >"${patch_paths}"; then
    fail 'Agent rules patch is invalid.'
  fi
  while IFS= read -r -d '' staged_path; do
    staged_path="${staged_path#*$'\t'}"
    staged_path="${staged_path#*$'\t'}"
    if [[ "${staged_path}" == /* ||
      "/${staged_path}/" == *'/../'* ]] ||
      ! is_agent_rule_path "${staged_path}"; then
      fail "Unexpected patch path: ${staged_path}"
    fi
  done <"${patch_paths}"
  while IFS= read -r line; do
    case "${line}" in
    'deleted file mode '* | 'new mode '* | 'new file mode '*)
      if [[ "${line##* }" != '100644' ]]; then
        fail "Unexpected patch mode: ${line}"
      fi
      if [[ "${line}" == 'deleted file mode '* ]]; then
        fail "Unexpected patch deletion: ${line}"
      fi
      ;;
    esac
  done <"${patch_path}"
  if ! git apply --check --index --whitespace=error-all "${patch_path}"; then
    fail 'Agent rules patch cannot be applied cleanly.'
  fi
  git apply --index --whitespace=error-all "${patch_path}"

  while IFS= read -r -d '' staged_path; do
    if ! is_agent_rule_path "${staged_path}"; then
      fail "Unexpected staged path: ${staged_path}"
    fi
  done < <(
    git diff --cached --name-only -z --no-renames \
      "${TARGET_BASE_COMMIT}" --
  )
  for path in "${agent_rule_paths[@]}"; do
    if [[ ! -f "${path}" || -L "${path}" ]]; then
      fail "Required agent rule is not a regular file: ${path}"
    fi
    git_mode="$(git ls-files -s -- "${path}")"
    git_mode="${git_mode%% *}"
    if [[ "${git_mode}" != '100644' ]]; then
      fail "Agent rule Git mode must be 100644: ${path}"
    fi
  done
  : >"${preserved_file}"
  for path in "${agent_rule_paths[@]}"; do
    if [[ "${path}" == '_agent-rules-source.json' ]]; then
      continue
    fi
    if cmp -s "${path}" "${source_snapshot_root}/${path}"; then
      continue
    fi
    if [[ -f "${base_snapshot_root}/${path}" ]] &&
      cmp -s "${path}" "${base_snapshot_root}/${path}"; then
      printf -- "- \`%s\`\n" "${path}" >>"${preserved_file}"
      continue
    fi
    fail "Agent rule does not match source or base: ${path}"
  done
  if [[ ! -s "${preserved_file}" ]]; then
    printf '%s\n' 'None.' >"${preserved_file}"
  fi
  "${python_cmd}" - "${source_repository}" "${SOURCE_REF}" \
    "${SOURCE_COMMIT}" <<'PY'
import hashlib
import json
import pathlib
import sys

source_repository, source_ref, source_commit = sys.argv[1:]
rule_paths = [
    "AGENTS.md",
    "BRANCH_RULES.md",
    "CODING_RULES.md",
    "COMMIT_RULES.md",
    "DOCUMENTATION_RULES.md",
    "LANGUAGE_RULES.md",
    "RELEASE_RULES.md",
]
with open("_agent-rules-source.json", encoding="utf-8") as stream:
    actual = json.load(stream)
expected = {
    "schemaVersion": 3,
    "agentRules": {
        "repository": f"https://github.com/{source_repository}",
        "requestedRef": source_ref,
        "ref": source_ref,
        "commit": source_commit,
        "files": rule_paths,
        "fileHashes": {
            path: hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
            for path in rule_paths
        },
    },
}
if actual != expected:
    raise SystemExit("_agent-rules-source.json provenance is invalid")
PY
  if ! git diff --cached --check; then
    fail 'Applied agent rules update contains whitespace errors.'
  fi
  if ! git diff --quiet ||
    [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    fail 'Target checkout contains residue outside the staged patch.'
  fi

  git switch --create "${sync_branch}"
  git \
    -c user.name='agent-rules-sync[bot]' \
    -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
    -c core.hooksPath=/dev/null \
    commit --no-verify --no-gpg-sign \
    -m "chore(agents): sync agent rules to ${SOURCE_REF}"
  if [[ -n "$(git status --porcelain)" ]]; then
    fail 'Prepared commit did not leave a clean checkout.'
  fi
  target_commit="$(git rev-parse HEAD)"
  target_tree="$(git rev-parse 'HEAD^{tree}')"

  owner="${TARGET_REPOSITORY%%/*}"
  repository_name="${TARGET_REPOSITORY#*/}"
  # The GraphQL dollar-prefixed names are literal query variables.
  # shellcheck disable=SC2016
  branch_json="$(
    run_gh_api graphql \
      -f query='query($owner:String!,$name:String!,$qualifiedName:String!){repository(owner:$owner,name:$name){ref(qualifiedName:$qualifiedName){target{oid ... on Commit{tree{oid}}}}}}' \
      -F owner="${owner}" \
      -F name="${repository_name}" \
      -F qualifiedName="refs/heads/${sync_branch}"
  )"
  printf '%s\n' "${branch_json}" >"${branch_json_path}"
  branch_state="$(
    "${python_cmd}" - "${branch_json_path}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
if payload.get("errors"):
    raise SystemExit("GraphQL branch query returned errors")
try:
    ref = payload["data"]["repository"]["ref"]
except (KeyError, TypeError) as error:
    raise SystemExit("GraphQL branch query shape is invalid") from error
if ref is None:
    print("absent")
else:
    target = ref.get("target")
    if not isinstance(target, dict):
        raise SystemExit("GraphQL branch target is invalid")
    oid = target.get("oid")
    tree = target.get("tree")
    tree_oid = tree.get("oid") if isinstance(tree, dict) else None
    if not isinstance(oid, str) or not isinstance(tree_oid, str):
        raise SystemExit("GraphQL branch identity is invalid")
    print(f"present\t{oid}\t{tree_oid}")
PY
  )"
  if [[ "${branch_state}" == 'absent' ]]; then
    expected_remote_oid=absent
    push_required=true
  else
    IFS=$'\t' read -r state branch_oid branch_tree <<<"${branch_state}"
    if [[ "${state}" != 'present' ]]; then
      fail 'Target branch query result is invalid.'
    fi
    EXPECTED_REMOTE_OID="${branch_oid}"
    require_oid EXPECTED_REMOTE_OID
    if ((${#branch_oid} != ${#target_commit} || ${#branch_tree} != ${#target_tree})); then
      fail 'Target branch object formats do not match the checkout.'
    fi
    expected_remote_oid="${branch_oid}"
    if [[ "${branch_tree}" == "${target_tree}" ]]; then
      push_required=false
    else
      push_required=true
    fi
  fi

  {
    printf '%s\n\n%s\n\n%s\n' \
      'Synchronizes rules from the canonical source.' \
      "Source release: \`${SOURCE_REF}\`" \
      'Customized files preserved:'
    cat "${preserved_file}"
    printf '\n%s\n\n%s\n' \
      'The repository validation workflow must pass before merge.' \
      'Automatic merge is intentionally disabled.'
  } >"${pr_body}"
  write_github_output target_commit "${target_commit}"
  write_github_output expected_remote_oid "${expected_remote_oid}"
  write_github_output push_required "${push_required}"
}

cleanup_publish_temp() {
  if [[ -z "${publish_temp:-}" ]]; then
    return 0
  fi
  case "${publish_temp}" in
  "${RUNNER_TEMP:?}"/agent-rules-publish.*)
    rm -rf -- "${publish_temp}"
    ;;
  *)
    fail "Refusing to remove unexpected publish path: ${publish_temp}"
    ;;
  esac
}

publish_transfer() {
  local askpass
  local expected_remote_oid
  local pr_numbers
  local revalidation_diagnostic
  local remote_branch_identity
  local required_remote_oid
  local remote_url
  local sync_branch="${SYNC_BRANCH:-${sync_branch_default}}"
  local target_repository
  local title
  local body_file="${RUNNER_TEMP:?}/agent-rules-pr-body.md"
  publish_temp=''

  require_target_checkout
  require_value GH_TOKEN
  require_value TARGET_REPOSITORY
  require_value TARGET_DEFAULT_BRANCH
  require_oid TARGET_COMMIT
  require_value SOURCE_REF
  require_value EXPECTED_REMOTE_OID
  require_value PUSH_REQUIRED

  target_repository="${TARGET_REPOSITORY}"
  if [[ "$(git status --porcelain)" != '' ]]; then
    fail 'Target worktree is not clean.'
  fi
  # TARGET_COMMIT is validated indirectly by require_oid above.
  # shellcheck disable=SC2153
  if [[ "$(git rev-parse HEAD)" != "${TARGET_COMMIT}" ]]; then
    fail 'Target checkout does not match TARGET_COMMIT.'
  fi
  if [[ "$(git symbolic-ref --short HEAD)" != "${sync_branch}" ]]; then
    fail "Target checkout is not on ${sync_branch}."
  fi
  remote_url="$(git remote get-url origin)"
  if [[ "${remote_url%.git}" != "https://github.com/${target_repository}" ]]; then
    fail 'Target remote URL is unexpected.'
  fi
  if [[ ! -f "${body_file}" ]]; then
    fail "Pull request body is missing: ${body_file}"
  fi

  case "${EXPECTED_REMOTE_OID}" in
  absent) expected_remote_oid='' ;;
  *)
    require_oid EXPECTED_REMOTE_OID
    expected_remote_oid="${EXPECTED_REMOTE_OID}"
    ;;
  esac
  # PUSH_REQUIRED is validated indirectly by require_value above.
  # shellcheck disable=SC2153
  if [[ "${PUSH_REQUIRED}" != 'true' && "${PUSH_REQUIRED}" != 'false' ]]; then
    fail "Invalid PUSH_REQUIRED: ${PUSH_REQUIRED}"
  fi
  if [[ "${PUSH_REQUIRED}" == 'false' && -z "${expected_remote_oid}" ]]; then
    fail 'A no-push publication requires an existing remote branch.'
  fi
  if [[ ! "${SOURCE_REF}" =~ ${semver_tag_pattern} ]]; then
    fail "Invalid source release tag: ${SOURCE_REF}"
  fi

  umask 077
  publish_temp="$(mktemp -d \
    "${RUNNER_TEMP:?}/agent-rules-publish.XXXXXX")"
  trap cleanup_publish_temp EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  askpass="${publish_temp}/askpass.sh"
  cat >"${askpass}" <<'ASKPASS'
#!/usr/bin/env bash
case "${1:-}" in
*Username*) printf '%s\n' 'x-access-token' ;;
*Password*) printf '%s\n' "${GH_TOKEN:?}" ;;
*) exit 1 ;;
esac
ASKPASS
  chmod 0700 "${askpass}"

  if [[ "${PUSH_REQUIRED}" == 'true' ]]; then
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="${askpass}" \
      git -c credential.helper= -c core.askPass="${askpass}" \
      push \
      "--force-with-lease=refs/heads/${sync_branch}:${expected_remote_oid}" \
      origin "HEAD:refs/heads/${sync_branch}"
    required_remote_oid="${TARGET_COMMIT}"
    revalidation_diagnostic='Remote automation branch moved after publication.'
  else
    required_remote_oid="${expected_remote_oid}"
    revalidation_diagnostic='Remote automation branch moved after preparation.'
  fi
  remote_branch_identity="$(
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="${askpass}" \
      git -c credential.helper= -c core.askPass="${askpass}" \
      ls-remote --exit-code --heads origin \
      "refs/heads/${sync_branch}"
  )" || fail "${revalidation_diagnostic}"
  if [[ "${remote_branch_identity}" != "${required_remote_oid}"$'\t'"refs/heads/${sync_branch}" ]]; then
    fail "${revalidation_diagnostic}"
  fi

  pr_numbers="$(
    gh pr list \
      --repo "${target_repository}" \
      --head "${sync_branch}" \
      --base "${TARGET_DEFAULT_BRANCH}" \
      --state open \
      --json number \
      --jq '.[].number'
  )"
  title="chore(agents): sync agent rules to ${SOURCE_REF}"
  case "${pr_numbers}" in
  '' | '[]')
    gh pr create \
      --repo "${target_repository}" \
      --base "${TARGET_DEFAULT_BRANCH}" \
      --head "${sync_branch}" \
      --title "${title}" \
      --body-file "${body_file}"
    ;;
  *$'\n'*) fail 'Multiple open agent rules pull requests found.' ;;
  *[!0-9]*) fail 'Invalid pull request query response.' ;;
  *)
    gh pr edit "${pr_numbers}" \
      --repo "${target_repository}" \
      --base "${TARGET_DEFAULT_BRANCH}" \
      --title "${title}" \
      --body-file "${body_file}"
    ;;
  esac
}

usage() {
  printf '%s\n' \
    'Usage: agent-rules-transfer.sh {resolve|seal|prepare-publish|publish}' >&2
}

main() {
  if (($# != 1)); then
    usage
    return 2
  fi

  case "$1" in
  resolve) resolve_transfer ;;
  seal) seal_transfer ;;
  prepare-publish) prepare_publish ;;
  publish) publish_transfer ;;
  *)
    usage
    return 2
    ;;
  esac
}

main "$@"
