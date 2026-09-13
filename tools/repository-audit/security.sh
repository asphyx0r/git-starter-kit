#!/usr/bin/env bash
# Common globals are initialized before this module is sourced.
# shellcheck disable=SC2154

resolve_pinned_gitleaks() {
  local config_root="$1"
  local scanner_cmd
  local python_cmd
  local expected_version
  local actual_version
  if [[ ! -f "${config_root}/tools/quality/versions.json" ||
    -L "${config_root}/tools/quality/versions.json" ]]; then
    printf '%s\n' 'Gitleaks requires a regular tools/quality/versions.json file.' >&2
    return 1
  fi
  scanner_cmd="$(resolve_hook_command registry gitleaks gitleaks.exe)" || return
  python_cmd="$(resolve_hook_python)" || return
  expected_version="$("${python_cmd}" -B -c \
    'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["external"]["gitleaks"]["version"])' \
    "${config_root}/tools/quality/versions.json")" || return
  actual_version="$("${scanner_cmd}" version)" || return
  if [[ "${actual_version%$'\r'}" != "${expected_version}" ]]; then
    printf 'Gitleaks version mismatch: expected %s, found %s.\n' \
      "${expected_version}" "${actual_version}" >&2
    print_external_quality_setup gitleaks
    return 1
  fi
  printf '%s\n' "${scanner_cmd}"
}

run_hook_secret_scan() {
  local indexed_root="$1"
  local scanner_cmd
  scanner_cmd="$(resolve_pinned_gitleaks "${indexed_root}")" || return
  if [[ ! -f "${indexed_root}/.gitleaks.toml" || -L "${indexed_root}/.gitleaks.toml" ]]; then
    printf '%s\n' 'pre-commit: indexed .gitleaks.toml is required.' >&2
    return 1
  fi
  local ignore_path="${indexed_root}/.gitleaksignore"
  if [[ -L "${ignore_path}" ]]; then
    printf '%s\n' 'pre-commit: indexed .gitleaksignore must be a regular file.' >&2
    return 1
  fi
  [[ -f "${ignore_path}" ]] || : >"${ignore_path}"
  local git_dir index_path
  git_dir="$(git rev-parse --absolute-git-dir)" || return
  index_path="$(git rev-parse --path-format=absolute --git-path index)" || return
  # Gitleaks also reads source/.gitleaksignore even with an explicit ignore
  # path. Point source at the snapshot, while Git reads the original index.
  GIT_DIR="$(to_hook_host_path "${git_dir}" "${scanner_cmd}")" \
  GIT_INDEX_FILE="$(to_hook_host_path "${index_path}" "${scanner_cmd}")" \
  GIT_WORK_TREE="$(to_hook_host_path "${indexed_root}" "${scanner_cmd}")" \
    "${scanner_cmd}" git --pre-commit --staged \
    --config "${indexed_root}/.gitleaks.toml" \
    --gitleaks-ignore-path "${ignore_path}" \
    --redact --no-banner --no-color --timeout 300 "${indexed_root}"
}

run_full_secret_scan() {
  local scanner_cmd
  scanner_cmd="$(resolve_pinned_gitleaks "${repository_root}")" || return
  "${scanner_cmd}" git --config "${repository_root}/.gitleaks.toml" \
    --gitleaks-ignore-path "${repository_root}/.gitleaksignore" \
    --redact --no-banner --no-color --log-opts=--all --timeout 300 \
    "${repository_root}"
}

check_secret_scanner_config_contract() {
  local betterleaks_config=".betterleaks.toml"
  local gitleaks_config=".gitleaks.toml"
  local path

  for path in "$betterleaks_config" "$gitleaks_config"; do
    if [ ! -f "$path" ]; then
      echo "Required secret scanner configuration is missing: $path" >&2
      exit 1
    fi
  done

  if [ "$(git hash-object "$betterleaks_config")" != \
    "$(git hash-object "$gitleaks_config")" ]; then
    echo "Betterleaks and Gitleaks configurations must be byte-identical." >&2
    exit 1
  fi

  if ! grep -Fx 'minVersion = "v8.25.0"' "$gitleaks_config" >/dev/null ||
    ! grep -Fx 'useDefault = true' "$gitleaks_config" >/dev/null; then
    echo "Secret scanner configuration omitted its compatibility or default-rule contract." >&2
    exit 1
  fi

  for rule_id in \
    strict-generic-credential-assignment \
    strict-authorization-header \
    strict-uri-credentials; do
    if ! grep -Fx "id = \"$rule_id\"" "$gitleaks_config" >/dev/null; then
      echo "Secret scanner configuration is missing rule: $rule_id" >&2
      exit 1
    fi
  done

  if grep -F 'disabledRules' "$gitleaks_config" >/dev/null; then
    echo "Strict secret scanner configuration must not disable inherited rules." >&2
    exit 1
  fi
}
expect_secret_scanner_finding() {
  local scanner_cmd="$1"
  local rule_id="$2"
  local sample="$3"
  local status

  if printf '%s\n' "$sample" |
    "$scanner_cmd" stdin \
      --enable-rule "$rule_id" \
      --exit-code 10 \
      --redact \
      --no-banner \
      --no-color >/dev/null; then
    status=0
  else
    status=$?
  fi

  if [ "$status" -ne 10 ]; then
    echo "Secret scanner did not detect the $rule_id fixture: $scanner_cmd" >&2
    exit 1
  fi
}

check_secret_scanner_behavior() {
  local scanner_cmd="$1"
  local credential_name="DB_PASS"
  local credential_value="abab"
  local authorization_value="abcdefgh"
  local uri_password="s3cret"
  local negative_sample

  credential_name+="WORD"
  credential_value+="abab"
  authorization_value+="12345678"
  uri_password+="Pass"

  expect_secret_scanner_finding \
    "$scanner_cmd" \
    strict-generic-credential-assignment \
    "$credential_name=\"$credential_value\""
  expect_secret_scanner_finding \
    "$scanner_cmd" \
    strict-authorization-header \
    "Authorization: Bearer $authorization_value"
  expect_secret_scanner_finding \
    "$scanner_cmd" \
    strict-uri-credentials \
    "postgres://service:$uri_password@db.example.test/app"

  negative_sample='APP_SECRET="__CHANGE_ME__"'
  negative_sample+=$'\nAPI_TOKEN="${API_TOKEN}"'
  negative_sample+=$'\nredis://:pass@host:6379/0'
  negative_sample+=$'\n`GITHUB_TOKEN`: optional environment variable'
  if ! printf '%s\n' "$negative_sample" |
    "$scanner_cmd" stdin \
      --exit-code 10 \
      --redact \
      --no-banner \
      --no-color >/dev/null; then
    echo "Secret scanner rejected an approved placeholder fixture: $scanner_cmd" >&2
    exit 1
  fi
}
