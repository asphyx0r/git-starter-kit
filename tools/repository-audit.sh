#!/usr/bin/env bash

audit_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
audit_module_dir="${audit_script_dir}/repository-audit"
audit_is_executed=false

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  audit_is_executed=true
fi

require_audit_module_file() {
  local module_name="$1"
  local module_path="$2"

  if [[ ! -f "${module_path}" ]]; then
    printf 'Repository audit module not found: %s\n' "${module_name}" >&2
    return 1
  fi
}

report_audit_module_failure() {
  printf 'Repository audit module failed to load: %s\n' "$1" >&2
}

check_audit_module_contract() {
  local module_name="$1"
  local required_function="$2"

  if ! declare -F "${required_function}" >/dev/null; then
    printf 'Repository audit module contract missing function: %s (%s)\n' \
      "${required_function}" "${module_name}" >&2
    return 1
  fi
}

load_audit_module_executed() {
  local module_name="$1"
  local required_function="$2"
  local module_path="${audit_module_dir}/${module_name}"
  local source_status=0

  require_audit_module_file "${module_name}" "${module_path}"
  trap 'source_status=$?; report_audit_module_failure "${module_name}"; exit "${source_status}"' ERR
  # shellcheck disable=SC1090
  source "${module_path}"
  trap - ERR
  check_audit_module_contract "${module_name}" "${required_function}"
}

load_audit_module_sourced() {
  local module_name="$1"
  local required_function="$2"
  local module_path="${audit_module_dir}/${module_name}"
  local source_status=0

  require_audit_module_file "${module_name}" "${module_path}" || return
  # shellcheck disable=SC2016
  if BASH_ENV='' "${BASH}" --noprofile --norc -euo pipefail \
    -c 'source "$1"' repository-audit-preflight "${module_path}" \
    >/dev/null 2>&1; then
    :
  else
    source_status=$?
    report_audit_module_failure "${module_name}"
    return "${source_status}"
  fi

  # The isolated strict preflight rejects failures that the caller's shell
  # options might otherwise ignore. This is the single real source pass.
  # shellcheck disable=SC1090
  source "${module_path}"
  source_status=$?
  if ((source_status != 0)); then
    report_audit_module_failure "${module_name}"
    return "${source_status}"
  fi
  check_audit_module_contract "${module_name}" "${required_function}"
}

load_audit_modules() {
  local load_mode="$1"
  shift

  while (($# > 0)); do
    if [[ "${load_mode}" == executed ]]; then
      load_audit_module_executed "$1" "$2"
    else
      load_audit_module_sourced "$1" "$2" || return
    fi
    shift 2
  done
}

audit_module_contracts=(
  common.sh usage
  contracts.sh check_semver_pattern_drift
  hooks.sh run_hook_pre_commit
  smoke.sh run_script_smoke
  security.sh check_secret_scanner_behavior
  profiles.sh run_readonly
)

if [[ "${audit_is_executed}" == true ]]; then
  load_audit_modules executed "${audit_module_contracts[@]}"
else
  audit_module_status=0
  load_audit_modules sourced "${audit_module_contracts[@]}" ||
    audit_module_status=$?
  if ((audit_module_status != 0)); then
    return "${audit_module_status}"
  fi
fi

main() {
  local mode="${1:-all}"
  if (($# > 0)); then
    shift
  fi

  case "${mode}" in
  -h | --help | help)
    usage
    return
    ;;
  all | full | readonly | markdown | spelling | static | fast | \
    powershell-static | \
    hook-pre-commit | hook-commit-msg | hook-pre-push) ;;

  *)
    usage >&2
    return 1
    ;;
  esac

  if [[ "${mode}" == "readonly" ]]; then
    export GIT_OPTIONAL_LOCKS=0
  fi

  initialize_repository_root

  case "${mode}" in
  readonly)
    run_readonly
    ;;
  full | all | static)
    run_static
    ;;
  markdown)
    run_markdown
    ;;
  spelling)
    run_spelling
    ;;
  fast)
    run_fast
    ;;
  powershell-static)
    run_powershell_static
    ;;
  hook-pre-commit)
    run_hook_pre_commit "$@"
    ;;
  hook-commit-msg)
    run_hook_commit_msg "$@"
    ;;
  hook-pre-push)
    run_hook_pre_push "$@"
    ;;
  esac
}

if [[ "${audit_is_executed}" == true ]]; then
  main "$@"
fi
