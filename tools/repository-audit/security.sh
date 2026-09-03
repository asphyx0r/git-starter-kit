#!/usr/bin/env bash

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
