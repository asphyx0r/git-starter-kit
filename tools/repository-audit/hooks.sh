#!/usr/bin/env bash
# Common globals are initialized before this module is sourced.
# shellcheck disable=SC2154

hook_semver_tag_pattern='^v(0|[1-9][0-9]*)\.'
hook_semver_tag_pattern+='(0|[1-9][0-9]*)\.'
hook_semver_tag_pattern+='(0|[1-9][0-9]*)'
hook_semver_tag_pattern+='(-((0|[1-9][0-9]*|[0-9A-Za-z-]*'
hook_semver_tag_pattern+='[A-Za-z-][0-9A-Za-z-]*)'
hook_semver_tag_pattern+='(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*'
hook_semver_tag_pattern+='[A-Za-z-][0-9A-Za-z-]*))*))?'
hook_semver_tag_pattern+='(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$'
hook_test_timeout_seconds=180

is_hook_zero_object_id() {
  local object_id="${1:-}"
  [[ -n "${object_id}" && "${object_id}" != *[!0]* ]]
}

print_python_quality_setup() {
  printf '%s\n' \
    'Install locked Python quality dependencies:' \
    '  python -m pip install --require-hashes --requirement tools/quality/requirements.lock' \
    >&2
}

print_node_quality_setup() {
  printf '%s\n' \
    'Install locked Node quality dependencies:' \
    '  npm ci --ignore-scripts --prefix tools/quality' \
    >&2
}

print_external_quality_setup() {
  printf 'Install the pinned %s version declared in tools/quality/versions.json.\n' \
    "$1" >&2
}

print_system_quality_setup() {
  printf 'Install required %s and ensure it is on PATH.\n' "$1" >&2
}

resolve_hook_command() {
  local setup_kind="$1"
  shift
  local candidate

  for candidate in "$@"; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      command -v "${candidate}"
      return
    fi
  done

  printf 'hook: required command not found: %s\n' "$1" >&2
  case "${setup_kind}" in
  node)
    print_node_quality_setup
    ;;
  python)
    print_python_quality_setup
    ;;
  registry)
    print_external_quality_setup "$1"
    ;;
  *)
    print_system_quality_setup "$1"
    ;;
  esac
  return 1
}

resolve_hook_node_tool() {
  local tool_name="$1"
  local local_command="${repository_root}/tools/quality/node_modules/.bin/${tool_name}"

  if [[ -x "${local_command}" || -f "${local_command}" ]]; then
    printf '%s\n' "${local_command}"
    return
  fi
  if [[ -f "${local_command}.cmd" ]]; then
    printf '%s\n' "${local_command}.cmd"
    return
  fi
  resolve_hook_command node "${tool_name}" "${tool_name}.cmd"
}

resolve_hook_python() {
  resolve_hook_command python python python3 python.exe
}

to_hook_host_path() {
  local file_path="$1"

  if [[ "${file_path}" != /* ]]; then
    printf '%s\n' "${file_path}"
    return
  fi
  if command -v wslpath >/dev/null 2>&1; then
    wslpath -w "${file_path}"
    return
  fi
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "${file_path}"
    return
  fi
  printf '%s\n' "${file_path}"
}

run_hook_markdown() {
  local staged_root="$1"
  shift
  local markdownlint_cmd
  markdownlint_cmd="$(resolve_hook_node_tool markdownlint-cli2)" || return
  (
    cd "${staged_root}" || return
    "${markdownlint_cmd}" --config .markdownlint-cli2.yaml "$@"
  )
}

run_hook_yaml() {
  local staged_root="$1"
  shift
  local yamllint_cmd
  yamllint_cmd="$(resolve_hook_command python yamllint yamllint.exe)" || return
  (
    cd "${staged_root}" || return
    "${yamllint_cmd}" -c tools/quality/yamllint.yaml "$@"
  )
}

run_hook_python_static() {
  local staged_root="$1"
  shift
  local mypy_cmd
  local ruff_cmd
  ruff_cmd="$(resolve_hook_command python ruff ruff.exe)" || return
  (
    cd "${staged_root}" || return
    "${ruff_cmd}" check --config tools/quality/pyproject.toml "$@" &&
      "${ruff_cmd}" format --check \
        --config tools/quality/pyproject.toml "$@"
  ) || return

  local -a production_paths=()
  local file_path
  for file_path in "$@"; do
    if [[ "${file_path}" == ./tools/* ]]; then
      production_paths+=("${file_path}")
    fi
  done
  if ((${#production_paths[@]} == 0)); then
    return
  fi
  mypy_cmd="$(resolve_hook_command python mypy mypy.exe)" || return
  (
    cd "${staged_root}" || return
    "${mypy_cmd}" --config-file tools/quality/pyproject.toml \
      "${production_paths[@]}"
  )
}

run_hook_shell_static() {
  local staged_root="$1"
  shift
  local shellcheck_cmd
  local shfmt_cmd
  shellcheck_cmd="$(resolve_hook_command system shellcheck shellcheck.exe)" || return
  shfmt_cmd="$(resolve_hook_command registry shfmt shfmt.exe)" || return
  (
    cd "${staged_root}" || return
    "${shellcheck_cmd}" "$@" && "${shfmt_cmd}" -d -i 2 "$@"
  )
}

run_hook_javascript_static() {
  local staged_root="$1"
  shift
  local node_cmd
  local file_path
  node_cmd="$(resolve_hook_command system node node.exe)" || return
  for file_path in "$@"; do
    "${node_cmd}" --check "${staged_root}/${file_path#./}" || return
  done
}

run_hook_powershell_static() {
  local staged_root="$1"
  shift
  local pwsh_cmd
  pwsh_cmd="$(resolve_powershell_command)" || return
  local settings_path
  settings_path="$(to_hook_host_path "${staged_root}/tools/quality/PSScriptAnalyzerSettings.psd1")"
  local file_path
  for file_path in "$@"; do
    local host_path
    host_path="$(to_hook_host_path "${staged_root}/${file_path#./}")"
    # PowerShell expands its environment variables in the single-quoted script.
    # shellcheck disable=SC2016
    AUDIT_PS_PATH="${host_path}" AUDIT_PS_SETTINGS="${settings_path}" \
      "${pwsh_cmd}" -NoProfile -Command '
$findings = Invoke-ScriptAnalyzer `
    -Path $env:AUDIT_PS_PATH `
    -Settings $env:AUDIT_PS_SETTINGS
if ($findings) {
    $findings | Format-Table -AutoSize | Out-String | Write-Error
    exit 1
}
' || return
  done
}

run_hook_powershell_settings() {
  local staged_root="$1"
  local pwsh_cmd
  pwsh_cmd="$(resolve_powershell_command)" || return
  local settings_path
  settings_path="$(to_hook_host_path "${staged_root}/tools/quality/PSScriptAnalyzerSettings.psd1")"
  # PowerShell expands its environment variables in the single-quoted script.
  # shellcheck disable=SC2016
  AUDIT_PS_SETTINGS="${settings_path}" \
    "${pwsh_cmd}" -NoProfile -Command '
$ErrorActionPreference = "Stop"
$null = Invoke-ScriptAnalyzer `
    -ScriptDefinition "`$null = `$null" `
    -Settings $env:AUDIT_PS_SETTINGS
'
}

run_hook_release_artifacts() {
  local staged_root="$1"
  local python_cmd
  python_cmd="$(resolve_hook_python)" || return
  local tool_path="${staged_root}/tools/release-artifacts.py"
  if [[ ! -f "${tool_path}" ]]; then
    printf '%s\n' \
      'pre-commit: staged release artifacts require tools/release-artifacts.py.' \
      >&2
    return 1
  fi
  "${python_cmd}" "${tool_path}" check \
    --index \
    --repository-root "${repository_root}"
}

run_hook_quality_declarations() {
  local staged_root="$1"
  local python_cmd
  python_cmd="$(resolve_hook_python)" || return
  "${python_cmd}" "${staged_root}/tools/quality/check-versions.py" \
    --quality-root "${staged_root}/tools/quality"
}

run_hook_spelling_configuration() {
  local staged_root="$1"
  local codespell_cmd
  codespell_cmd="$(resolve_hook_command python codespell codespell.exe)" || return
  (
    cd "${staged_root}" || return
    "${codespell_cmd}" --config .codespellrc .
  )
}

run_hook_commitlint_configuration() {
  local staged_root="$1"
  local commitlint_cmd
  commitlint_cmd="$(resolve_hook_node_tool commitlint)" || return
  if [[ ! -f "${staged_root}/commitlint.config.cjs" ]]; then
    printf '%s\n' \
      'pre-commit: staged commitlint.config.cjs is required.' >&2
    return 1
  fi
  (
    cd "${staged_root}" || return
    "${commitlint_cmd}" \
      --print-config json \
      --cwd . \
      --config commitlint.config.cjs \
      >/dev/null
  )
}

run_hook_markdown_configuration() {
  local staged_root="$1"
  local markdownlint_cmd
  markdownlint_cmd="$(resolve_hook_node_tool markdownlint-cli2)" || return
  (
    cd "${staged_root}" || return
    printf '%s\n' '# Markdownlint configuration probe' |
      "${markdownlint_cmd}" \
        --config .markdownlint-cli2.yaml \
        --no-globs \
        -
  )
}

run_hook_pre_commit() (
  local staged_file
  local hook_temp
  hook_temp="$(mktemp -d "${TMPDIR:-/tmp}/pre-commit-staged.XXXXXX")"
  # Invoked by the scoped EXIT trap.
  # shellcheck disable=SC2329
  cleanup_hook_pre_commit() {
    case "${hook_temp}" in
    "${TMPDIR:-/tmp}"/pre-commit-staged.*)
      rm -rf -- "${hook_temp}"
      ;;
    *)
      printf 'Refusing to remove unexpected pre-commit path: %s\n' \
        "${hook_temp}" >&2
      return 1
      ;;
    esac
  }
  trap cleanup_hook_pre_commit EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  local -a markdown_paths=()
  local -a yaml_paths=()
  local -a python_paths=()
  local -a shell_paths=()
  local -a javascript_paths=()
  local -a powershell_paths=()
  local -a release_paths=()
  local run_commitlint_configuration=false
  local run_markdown_configuration=false
  local run_powershell_settings=false
  local run_quality_declarations=false
  local run_spelling_configuration=false
  local -a required_configuration_paths=()
  local staged_names="${hook_temp}/staged.names"
  local configuration_names="${hook_temp}/configuration.names"
  local release_names="${hook_temp}/release.names"

  git diff --cached --name-only -z --diff-filter=ACMR \
    >"${staged_names}" || return $?
  while IFS= read -r -d '' staged_file; do
    case "${staged_file}" in
    *.md)
      markdown_paths+=("./${staged_file}")
      ;;
    *.yaml | *.yml)
      yaml_paths+=("./${staged_file}")
      ;;
    *.py)
      python_paths+=("./${staged_file}")
      ;;
    *.sh | .githooks/*)
      shell_paths+=("./${staged_file}")
      ;;
    *.js | *.cjs | *.mjs)
      javascript_paths+=("./${staged_file}")
      ;;
    tools/quality/PSScriptAnalyzerSettings.psd1)
      run_powershell_settings=true
      ;;
    *.ps1 | *.psd1 | *.psm1)
      powershell_paths+=("./${staged_file}")
      ;;
    esac
  done <"${staged_names}"

  git diff --cached --no-renames --name-only -z --diff-filter=ACDMR -- \
    tools/quality .codespellrc commitlint.config.cjs \
    .markdownlint-cli2.yaml >"${configuration_names}" || return $?
  while IFS= read -r -d '' staged_file; do
    case "${staged_file}" in
    tools/quality/PSScriptAnalyzerSettings.psd1 | tools/quality/yamllint.yaml)
      required_configuration_paths+=("${staged_file}")
      run_quality_declarations=true
      ;;
    tools/quality/*)
      run_quality_declarations=true
      ;;
    .codespellrc)
      run_spelling_configuration=true
      ;;
    commitlint.config.cjs)
      run_commitlint_configuration=true
      ;;
    .markdownlint-cli2.yaml)
      required_configuration_paths+=("${staged_file}")
      run_markdown_configuration=true
      ;;
    esac
  done <"${configuration_names}"

  git diff --cached --name-only -z --diff-filter=ACDMR -- \
    VERSION SHA256SUMS manifest.json >"${release_names}" || return $?
  while IFS= read -r -d '' staged_file; do
    release_paths+=("${staged_file}")
  done <"${release_names}"
  if ((${#release_paths[@]} != 0 && ${#release_paths[@]} != 3)); then
    printf '%s\n' \
      'pre-commit: VERSION, SHA256SUMS, and manifest.json must be staged together.' \
      >&2
    return 1
  fi

  if ((${#markdown_paths[@]} == 0 && \
    ${#yaml_paths[@]} == 0 && \
    ${#python_paths[@]} == 0 && \
    ${#shell_paths[@]} == 0 && \
    ${#javascript_paths[@]} == 0 && \
    ${#powershell_paths[@]} == 0 && \
    ${#release_paths[@]} == 0)) &&
      [[ "${run_commitlint_configuration}" == false ]] &&
      [[ "${run_markdown_configuration}" == false ]] &&
      [[ "${run_powershell_settings}" == false ]] &&
      [[ "${run_quality_declarations}" == false ]] &&
      [[ "${run_spelling_configuration}" == false ]]; then
    return
  fi

  local staged_root="${hook_temp}/index"
  mkdir -p "${staged_root}"
  local check_status=0
  git checkout-index -a --prefix="${staged_root}/" || check_status=$?
  if ((check_status == 0)); then
    for staged_file in "${required_configuration_paths[@]}"; do
      if [[ ! -f "${staged_root}/${staged_file}" ]]; then
        printf 'pre-commit: staged %s is required.\n' \
          "${staged_file}" >&2
        check_status=1
        break
      fi
    done
  fi
  if ((check_status == 0)) && [[ "${run_quality_declarations}" == true ]]; then
    run_hook_quality_declarations "${staged_root}" || check_status=$?
  fi
  if ((check_status == 0)) && [[ "${run_spelling_configuration}" == true ]]; then
    run_hook_spelling_configuration "${staged_root}" || check_status=$?
  fi
  if ((check_status == 0)) &&
    [[ "${run_commitlint_configuration}" == true ]]; then
    run_hook_commitlint_configuration "${staged_root}" || check_status=$?
  fi
  if ((check_status == 0)) &&
    [[ "${run_markdown_configuration}" == true ]]; then
    run_hook_markdown_configuration "${staged_root}" || check_status=$?
  fi
  if ((check_status == 0 && ${#markdown_paths[@]} > 0)); then
    run_hook_markdown "${staged_root}" "${markdown_paths[@]}" || check_status=$?
  fi
  if ((check_status == 0 && ${#yaml_paths[@]} > 0)); then
    run_hook_yaml "${staged_root}" "${yaml_paths[@]}" || check_status=$?
  fi
  if ((check_status == 0 && ${#python_paths[@]} > 0)); then
    run_hook_python_static "${staged_root}" "${python_paths[@]}" || check_status=$?
  fi
  if ((check_status == 0 && ${#shell_paths[@]} > 0)); then
    run_hook_shell_static "${staged_root}" "${shell_paths[@]}" || check_status=$?
  fi
  if ((check_status == 0 && ${#javascript_paths[@]} > 0)); then
    run_hook_javascript_static "${staged_root}" "${javascript_paths[@]}" || check_status=$?
  fi
  if ((check_status == 0)) && [[ "${run_powershell_settings}" == true ]]; then
    run_hook_powershell_settings "${staged_root}" || check_status=$?
  fi
  if ((check_status == 0 && ${#powershell_paths[@]} > 0)); then
    run_hook_powershell_static "${staged_root}" "${powershell_paths[@]}" || check_status=$?
  fi
  if ((check_status == 0 && ${#release_paths[@]} > 0)); then
    run_hook_release_artifacts "${staged_root}" || check_status=$?
  fi
  return "${check_status}"
)

require_commit_message_file() {
  local commit_message_file="$1"
  if [[ -z "${commit_message_file}" ]]; then
    printf '%s\n' 'commit-msg: commit message file path is required.' >&2
    return 1
  fi
  if [[ ! -f "${commit_message_file}" ]]; then
    printf 'commit-msg: commit message file does not exist: %s\n' \
      "${commit_message_file}" >&2
    return 1
  fi
}

run_hook_commitlint() {
  local commit_message_file="$1"
  local commitlint_cmd
  commitlint_cmd="$(resolve_hook_node_tool commitlint)" || return
  local commitlint_config="${repository_root}/commitlint.config.cjs"
  if [[ ! -f "${commitlint_config}" ]]; then
    printf 'commit-msg: commitlint config does not exist: %s\n' \
      "${commitlint_config}" >&2
    return 1
  fi
  printf '%s\n' 'commit-msg: running commitlint on commit message.'
  "${commitlint_cmd}" \
    --edit "${commit_message_file}" \
    --config "${commitlint_config}"
}

run_hook_commit_msg() {
  local commit_message_file="${1:-}"
  require_commit_message_file "${commit_message_file}" || return
  run_hook_commitlint "${commit_message_file}"
}

list_hook_push_changes() {
  local local_object_id="$1"
  local remote_object_id="$2"
  git diff --no-renames --name-only -z \
    "${remote_object_id}..${local_object_id}" --
}

classify_hook_push_path() {
  local changed_path="$1"
  case "${changed_path}" in
  *.py | *.ps1 | *.psd1 | *.psm1 | .codespellrc | \
    tools/quality/* | tools/release-artifacts-requirements.txt)
    run_python=true
    ;;
  esac
  case "${changed_path}" in
  *.sh | .githooks/* | tools/repository-audit/* | \
    commitlint.config.cjs | .markdownlint-cli2.yaml | \
    tools/quality/package.json | tools/quality/package-lock.json)
    run_shell=true
    ;;
  esac
}

merge_hook_test_update() {
  local object_id="$1"
  local run_python_for_object="$2"
  local run_shell_for_object="$3"
  local object_index

  for ((object_index = 0; object_index < ${#test_object_ids[@]}; object_index += 1)); do
    if [[ "${test_object_ids[object_index]}" == "${object_id}" ]]; then
      if [[ "${run_python_for_object}" == true ]]; then
        test_python_flags[object_index]=true
      fi
      if [[ "${run_shell_for_object}" == true ]]; then
        test_shell_flags[object_index]=true
      fi
      return
    fi
  done

  test_object_ids+=("${object_id}")
  test_python_flags+=("${run_python_for_object}")
  test_shell_flags+=("${run_shell_for_object}")
}

canonical_hook_directory() (
  local directory_path="$1"
  if [[ ! -d "${directory_path}" || -L "${directory_path}" ]]; then
    return 1
  fi
  cd -- "${directory_path}" || return
  pwd -P
)

validate_hook_clone() {
  local clone_root="$1"
  local expected_parent="$2"
  local expected_root
  local expected_git_dir
  local actual_top_level
  local actual_git_dir
  local actual_common_dir

  expected_parent="$(canonical_hook_directory "${expected_parent}")" || return
  expected_root="$(canonical_hook_directory "${clone_root}")" || return
  if [[ "$(dirname "${expected_root}")" != "${expected_parent}" ]]; then
    printf 'pre-push: clone escaped its temporary parent: %s\n' \
      "${expected_root}" >&2
    return 1
  fi
  expected_git_dir="$(canonical_hook_directory "${expected_root}/.git")" || {
    printf 'pre-push: clone Git directory is not local: %s\n' \
      "${expected_root}/.git" >&2
    return 1
  }
  actual_top_level="$(
    unset GIT_COMMON_DIR GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
    git -C "${expected_root}" rev-parse --path-format=absolute --show-toplevel
  )" || return
  actual_top_level="$(canonical_hook_directory "${actual_top_level}")" || return
  actual_git_dir="$(
    unset GIT_COMMON_DIR GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
    git -C "${expected_root}" rev-parse --path-format=absolute --absolute-git-dir
  )" || return
  actual_git_dir="$(canonical_hook_directory "${actual_git_dir}")" || return
  actual_common_dir="$(
    unset GIT_COMMON_DIR GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
    git -C "${expected_root}" rev-parse --path-format=absolute --git-common-dir
  )" || return
  actual_common_dir="$(canonical_hook_directory "${actual_common_dir}")" || return

  if [[ "${actual_top_level}" != "${expected_root}" ||
    "${actual_git_dir}" != "${expected_git_dir}" ||
    "${actual_common_dir}" != "${expected_git_dir}" ]]; then
    printf '%s\n' \
      'pre-push: refusing clone with redirected repository paths.' >&2
    return 1
  fi

  validated_hook_root="${expected_root}"
  validated_hook_git_dir="${expected_git_dir}"
}

run_hook_affected_tests() {
  local pushed_root="$1"
  local run_python="$2"
  local run_shell="$3"
  local python_cmd
  if [[ "${run_python}" == true ]]; then
    python_cmd="$(resolve_hook_python)" || return
    printf '%s\n' 'pre-push: running affected Python tests.'
    # The child Bash expands its positional arguments.
    # shellcheck disable=SC2016
    run_hook_test_family Python bash -c '
      cd -- "$1" || exit
      exec "$2" -m unittest discover -s tests -p "test_*.py"
    ' hook-python-family "${pushed_root}" "${python_cmd}" || return
  fi
  if [[ "${run_shell}" == true ]]; then
    printf '%s\n' 'pre-push: running affected shell tests.'
    # The child Bash expands its positional arguments.
    # shellcheck disable=SC2016
    run_hook_test_family Shell bash -c '
      cd -- "$1" || exit
      shift
      for shell_test in "$@"; do
        bash "${shell_test}" || exit $?
      done
    ' hook-shell-family "${pushed_root}" \
      tests/test_quality_hooks.sh \
      tests/test_commit_message_validation.sh || return $?
  fi
}

run_hook_release_check() {
  local local_ref="$1"
  local remote_ref="$2"
  local tag_name="${remote_ref#refs/tags/}"
  if [[ ! "${tag_name}" =~ ${hook_semver_tag_pattern} ]]; then
    printf 'pre-push: refusing non-SemVer release tag: %s\n' \
      "${tag_name}" >&2
    return 1
  fi
  local python_cmd
  python_cmd="$(resolve_hook_python)" || return
  printf 'pre-push: validating release artifacts for %s.\n' "${tag_name}"
  "${python_cmd}" "${repository_root}/tools/release-artifacts.py" check \
    --expected-ref "${tag_name}" \
    --treeish "${local_ref}^{commit}" \
    --repository-root "${repository_root}"
}

run_hook_test_family() {
  local family_name="$1"
  shift
  local suite_status=0
  local timeout_cmd
  timeout_cmd="$(resolve_hook_command system timeout)" || return

  "${timeout_cmd}" --kill-after=1s "${hook_test_timeout_seconds}s" "$@" ||
    suite_status=$?
  if ((suite_status == 124 || suite_status == 137)); then
    printf 'pre-push: affected %s test family timed out after %s seconds.\n' \
      "${family_name}" "${hook_test_timeout_seconds}" >&2
    return 124
  fi
  return "${suite_status}"
}

run_hook_pre_push() (
  local remote_url="${2:-}"
  local local_ref
  local local_object_id
  local remote_ref
  local remote_object_id
  local changed_path
  local change_status
  local update_index=0
  local hook_temp
  local hook_temp_parent
  hook_temp_parent="$(canonical_hook_directory "${TMPDIR:-/tmp}")" || return
  hook_temp="$(mktemp -d "${hook_temp_parent}/pre-push-oid.XXXXXX")" || return
  hook_temp="$(canonical_hook_directory "${hook_temp}")" || return
  if [[ "$(dirname "${hook_temp}")" != "${hook_temp_parent}" ||
  "$(basename "${hook_temp}")" != pre-push-oid.* ]]; then
    printf 'pre-push: invalid temporary directory: %s\n' "${hook_temp}" >&2
    return 1
  fi
  # Invoked by the scoped EXIT trap.
  # shellcheck disable=SC2329
  cleanup_hook_pre_push() {
    local cleanup_root
    cleanup_root="$(canonical_hook_directory "${hook_temp}")" || {
      printf 'Refusing to remove unexpected pre-push path: %s\n' \
        "${hook_temp}" >&2
      return 1
    }
    if [[ "${cleanup_root}" != "${hook_temp}" ||
      "$(dirname "${cleanup_root}")" != "${hook_temp_parent}" ||
      "$(basename "${cleanup_root}")" != pre-push-oid.* ]]; then
      printf 'Refusing to remove unexpected pre-push path: %s\n' \
        "${cleanup_root}" >&2
      return 1
    fi
    rm -rf -- "${cleanup_root}"
  }
  trap cleanup_hook_pre_push EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  local -a test_object_ids=()
  local -a test_python_flags=()
  local -a test_shell_flags=()
  local -a release_updates=()

  while read -r local_ref local_object_id remote_ref remote_object_id; do
    if [[ -z "${local_ref:-}" ]] ||
      is_hook_zero_object_id "${local_object_id}"; then
      continue
    fi
    if [[ "${remote_ref}" == refs/tags/v* ]]; then
      release_updates+=("${local_object_id}" "${remote_ref}")
      continue
    fi
    local run_python=false
    local run_shell=false
    if is_hook_zero_object_id "${remote_object_id}"; then
      run_python=true
      run_shell=true
    else
      local changes_path="${hook_temp}/changes.${update_index}"
      if list_hook_push_changes \
        "${local_object_id}" "${remote_object_id}" >"${changes_path}"; then
        :
      else
        change_status=$?
        return "${change_status}"
      fi
      while IFS= read -r -d '' changed_path; do
        classify_hook_push_path "${changed_path}"
      done <"${changes_path}"
    fi
    if [[ "${run_python}" == true || "${run_shell}" == true ]]; then
      merge_hook_test_update \
        "${local_object_id}" "${run_python}" "${run_shell}"
    fi
    update_index=$((update_index + 1))
  done

  if ((${#test_object_ids[@]} > 0)); then
    local source_node_bin="${repository_root}/tools/quality/node_modules/.bin"
    export PATH="${source_node_bin}:${PATH}"
    for ((update_index = 0; update_index < ${#test_object_ids[@]}; update_index += 1)); do
      local pushed_root="${hook_temp}/repository.${update_index}"
      if env GIT_ALLOW_PROTOCOL=file git clone \
        --quiet --local --no-hardlinks --no-checkout -- \
        "${repository_root}" "${pushed_root}"; then
        :
      else
        change_status=$?
        return "${change_status}"
      fi
      local validated_hook_root=''
      local validated_hook_git_dir=''
      validate_hook_clone "${pushed_root}" "${hook_temp}" || return
      if git \
        --git-dir="${validated_hook_git_dir}" \
        --work-tree="${validated_hook_root}" \
        checkout --quiet --detach --force \
        "${test_object_ids[update_index]}"; then
        :
      else
        change_status=$?
        return "${change_status}"
      fi
      if git \
        --git-dir="${validated_hook_git_dir}" \
        --work-tree="${validated_hook_root}" \
        remote set-url origin "${remote_url}"; then
        :
      else
        change_status=$?
        return "${change_status}"
      fi
      run_hook_affected_tests \
        "${validated_hook_root}" \
        "${test_python_flags[update_index]}" \
        "${test_shell_flags[update_index]}" || return
    done
  fi

  for ((update_index = 0; update_index < ${#release_updates[@]}; update_index += 2)); do
    run_hook_release_check \
      "${release_updates[update_index]}" \
      "${release_updates[update_index + 1]}" || return
  done
)
