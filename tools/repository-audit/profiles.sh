#!/usr/bin/env bash
# Common globals are initialized before this module is sourced.
# shellcheck disable=SC2154

run_commitlint() {
  local from_ref=""
  local root_commit=""
  local to_ref=""
  local commit_count
  local commitlint_cmd
  commitlint_cmd="$(resolve_hook_node_tool commitlint)" || return

  to_ref="$(resolve_audit_to_ref)" || return

  if ! from_ref="$(resolve_audit_from_ref)"; then
    from_ref=""
  fi

  if [ "$from_ref" = "$audit_all_commits_marker" ]; then
    root_commit="$(git rev-list --max-parents=0 --reverse "$to_ref" | tail -n 1)" || return
    git log -1 --format=%B "$root_commit" |
      "$commitlint_cmd" --config commitlint.config.cjs || return
    from_ref="$root_commit"
  fi

  if [ -n "$from_ref" ]; then
    commit_count="$(git rev-list --count "$from_ref..$to_ref")" || return
    if [ "$commit_count" -eq 0 ]; then
      return
    fi

    "$commitlint_cmd" \
      --config commitlint.config.cjs \
      --from "$from_ref" \
      --to "$to_ref" || return
  else
    git log -1 --format=%B "$to_ref" |
      "$commitlint_cmd" --config commitlint.config.cjs || return
  fi
}

run_markdown() {
  local markdownlint_cmd
  markdownlint_cmd="$(resolve_hook_node_tool markdownlint-cli2)" || return
  "$markdownlint_cmd" --config .markdownlint-cli2.yaml "**/*.md" || return
}

run_spelling() {
  local codespell_cmd
  codespell_cmd="$(resolve_command codespell codespell.cmd codespell.exe)" || return
  "$codespell_cmd" --config .codespellrc . || return
}

run_yamllint() {
  local yamllint_cmd
  yamllint_cmd="$(resolve_hook_command python yamllint yamllint.exe)" || return
  "$yamllint_cmd" -c tools/quality/yamllint.yaml . || return
}

run_actionlint() {
  local actionlint_cmd
  actionlint_cmd="$(resolve_command actionlint actionlint.exe)" || return
  "$actionlint_cmd" || return
}

run_powershell_parse_readonly() {
  local path paths_fd paths_pid
  local -a paths=()
  exec {paths_fd}< <(git ls-files -z -- '*.ps1' '*.psm1' '*.psd1') || return
  paths_pid=$!
  while IFS= read -r -d '' path; do paths+=("${path}"); done <&"${paths_fd}"
  exec {paths_fd}<&- || return
  wait "${paths_pid}" || return
  run_powershell_parse_paths "${paths[@]}" || return
}

run_powershell_parse_paths() {
  (($# > 0)) || return 0
  local pwsh_cmd
  local path host_path
  pwsh_cmd="$(resolve_powershell_command)" || return
  for path in "$@"; do
    host_path="$(to_pwsh_path "${repository_root}/${path#./}" "${pwsh_cmd}")" || return
    if [ -n "${WSL_DISTRO_NAME:-}${WSL_INTEROP:-}" ]; then
      WSLENV="${WSLENV:+$WSLENV:}AUDIT_PS_PATH"
      export WSLENV
    fi
    # PowerShell expands the environment variable after Bash passes it.
    # shellcheck disable=SC2016
    AUDIT_PS_PATH="${host_path}" "$pwsh_cmd" -NoProfile -Command '
$ErrorActionPreference = "Stop"
$null = Get-Content -LiteralPath $env:AUDIT_PS_PATH -Raw
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $env:AUDIT_PS_PATH, [ref]$tokens, [ref]$errors
) | Out-Null
if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}
' || return
  done
}

run_commitlint_readonly() {
  local commitlint_cmd="$1"

  local from_ref=""
  local root_commit=""
  local to_ref=""
  local commit_count

  to_ref="$(resolve_audit_to_ref)" || return

  if ! from_ref="$(resolve_audit_from_ref)"; then
    from_ref=""
  fi

  if [ "$from_ref" = "$audit_all_commits_marker" ]; then
    root_commit="$(git rev-list --max-parents=0 --reverse "$to_ref" | tail -n 1)" || return
    git log -1 --format=%B "$root_commit" |
      "$commitlint_cmd" --config commitlint.config.cjs || return
    from_ref="$root_commit"
  fi

  if [ -n "$from_ref" ]; then
    commit_count="$(git rev-list --count "$from_ref..$to_ref")" || return
    if [ "$commit_count" -eq 0 ]; then
      return
    fi

    "$commitlint_cmd" \
      --config commitlint.config.cjs \
      --from "$from_ref" \
      --to "$to_ref" || return
  else
    git log -1 --format=%B "$to_ref" |
      "$commitlint_cmd" --config commitlint.config.cjs || return
  fi
}

run_shell_syntax_checks() {
  local shell_path

  for shell_path in \
    .githooks/pre-commit \
    .githooks/pre-push \
    .githooks/commit-msg \
    tests/test_commit_message_validation.sh \
    tests/test_quality_hooks.sh \
    tests/test_quality_pre_commit.sh \
    tests/test_quality_pre_push.sh \
    tests/test_agent_rules_transfer.sh \
    tests/test_repository_audit.sh \
    tools/git-init.sh \
    tools/repository-audit.sh \
    tools/repository-audit/common.sh \
    tools/repository-audit/agent-rules-transfer.sh \
    tools/repository-audit/contracts.sh \
    tools/repository-audit/hooks.sh \
    tools/repository-audit/profiles.sh \
    tools/repository-audit/security.sh \
    tools/repository-audit/smoke.sh; do
    bash -n "${shell_path}" || return
  done
}

run_shellcheck_checks() {
  local shellcheck_cmd="$1"
  local shell_path

  "${shellcheck_cmd}" --version || return
  for shell_path in \
    .githooks/pre-commit \
    .githooks/pre-push \
    .githooks/commit-msg \
    tests/test_commit_message_validation.sh \
    tests/test_quality_hooks.sh \
    tests/test_quality_pre_commit.sh \
    tests/test_quality_pre_push.sh \
    tests/test_agent_rules_transfer.sh \
    tests/test_repository_audit.sh \
    tools/git-init.sh \
    tools/repository-audit.sh \
    tools/repository-audit/common.sh \
    tools/repository-audit/agent-rules-transfer.sh \
    tools/repository-audit/contracts.sh \
    tools/repository-audit/hooks.sh \
    tools/repository-audit/profiles.sh \
    tools/repository-audit/security.sh \
    tools/repository-audit/smoke.sh; do
    "${shellcheck_cmd}" "${shell_path}" || return
  done
}

run_shfmt_checks() {
  local shfmt_cmd="$1"

  "${shfmt_cmd}" -d -i 2 \
    tests/test_commit_message_validation.sh \
    tests/test_quality_hooks.sh \
    tests/test_quality_pre_commit.sh \
    tests/test_quality_pre_push.sh || return
  "${shfmt_cmd}" -d -i 2 tools/git-init.sh || return
  "${shfmt_cmd}" -d -i 2 \
    .githooks/commit-msg \
    .githooks/pre-commit \
    .githooks/pre-push || return
  "${shfmt_cmd}" -d -i 2 \
    tests/test_agent_rules_transfer.sh \
    tests/test_repository_audit.sh \
    tools/repository-audit.sh \
    tools/repository-audit/agent-rules-transfer.sh \
    tools/repository-audit/common.sh \
    tools/repository-audit/contracts.sh \
    tools/repository-audit/hooks.sh \
    tools/repository-audit/profiles.sh \
    tools/repository-audit/security.sh \
    tools/repository-audit/smoke.sh || return
}

run_python_coverage() {
  local coverage_cmd
  local python_cmd
  local coverage_status=0
  coverage_cmd="$(resolve_hook_command python coverage coverage.exe)" || return
  python_cmd="$(resolve_hook_python)" || return
  ensure_audit_temp || return

  COVERAGE_FILE="${audit_temp}/.coverage" \
    "${coverage_cmd}" run \
    --rcfile=tools/quality/pyproject.toml \
    -m unittest discover -s tests -p 'test_*.py' || coverage_status=$?
  COVERAGE_FILE="${audit_temp}/.coverage" \
    "${coverage_cmd}" json --rcfile=tools/quality/pyproject.toml \
    --fail-under=0 -o "${audit_temp}/coverage.json" || return $?
  COVERAGE_FILE="${audit_temp}/.coverage" \
    "${coverage_cmd}" report --rcfile=tools/quality/pyproject.toml || coverage_status=$?
  "${python_cmd}" tools/quality/check-coverage.py \
    "${audit_temp}/coverage.json" || coverage_status=1
  return "${coverage_status}"
}

run_shell_behavior_tests() {
  local shell_test

  for shell_test in \
    tests/test_repository_audit.sh \
    tests/test_agent_rules_transfer.sh \
    tests/test_quality_hooks.sh \
    tests/test_quality_pre_commit.sh \
    tests/test_commit_message_validation.sh \
    tests/test_quality_pre_push.sh; do
    bash "${shell_test}" || return $?
  done
}

run_powershell_static() {
  require_command git || return
  local powershell_path paths_fd paths_pid
  local powershell_paths=()

  exec {paths_fd}< <(git ls-files -z -- '*.ps1' '*.psm1' '*.psd1') || return
  paths_pid=$!
  while IFS= read -r -d '' powershell_path; do
    powershell_paths+=("${powershell_path}")
  done <&"${paths_fd}"
  exec {paths_fd}<&- || return
  wait "${paths_pid}" || return

  if ((${#powershell_paths[@]} == 0)); then
    return
  fi
  run_hook_powershell_static \
    "${repository_root}" "${powershell_paths[@]}" || return
}

run_consumer_core() {
  local mode="$1"
  local path python_cmd node_cmd
  local -a markdown=() yaml=() python=() shell=() javascript=() powershell=()
  local owned_names
  ensure_audit_temp || return
  owned_names="${audit_temp}/core.names"
  list_core_paths >"${owned_names}" || return
  while IFS= read -r -d '' path; do
    case "${path}" in
    *.md) markdown+=("./${path}") ;;
    *.yaml | *.yml) yaml+=("./${path}") ;;
    *.py) python+=("./${path}") ;;
    *.sh | .githooks/*) shell+=("./${path}") ;;
    *.js | *.cjs | *.mjs) javascript+=("./${path}") ;;
    *.ps1 | *.psm1 | *.psd1) powershell+=("./${path}") ;;
    esac
  done <"${owned_names}"
  if [[ "${mode}" == markdown ]]; then
    ((${#markdown[@]} == 0)) || run_hook_markdown "${repository_root}" "${markdown[@]}"
    return
  fi
  if [[ "${mode}" == spelling ]]; then
    local codespell_cmd
    codespell_cmd="$(resolve_command codespell codespell.cmd codespell.exe)" || return
    local -a paths=()
    while IFS= read -r -d '' path; do paths+=("./${path}"); done <"${owned_names}"
    ((${#paths[@]} == 0)) || "${codespell_cmd}" --config .codespellrc "${paths[@]}"
    return
  fi
  if [[ "${mode}" == powershell-static ]]; then
    ((${#powershell[@]} == 0)) || run_hook_powershell_static "${repository_root}" "${powershell[@]}"
    return
  fi
  ((${#python[@]} == 0)) || run_hook_python_static "${repository_root}" "${python[@]}" || return
  ((${#shell[@]} == 0)) || run_hook_shell_static "${repository_root}" "${shell[@]}" || return
  ((${#javascript[@]} == 0)) || run_hook_javascript_static "${repository_root}" "${javascript[@]}" || return
  if [[ "${mode}" != fast ]]; then
    ((${#markdown[@]} == 0)) || run_hook_markdown "${repository_root}" "${markdown[@]}" || return
    ((${#yaml[@]} == 0)) || run_hook_yaml "${repository_root}" "${yaml[@]}" || return
    if [[ "${mode}" == readonly ]]; then
      run_powershell_parse_paths "${powershell[@]}" || return
    else
      ((${#powershell[@]} == 0)) || run_hook_powershell_static "${repository_root}" "${powershell[@]}" || return
    fi
    node_cmd="$(resolve_command node node.exe)" || return
    check_semver_pattern_drift "${node_cmd}" || return
    check_initializer_commit_contract || return
    check_commit_documentation_contract || return
    run_commitlint || return
    run_full_secret_scan || return
  fi
  python_cmd="$(resolve_hook_python)" || return
  "${python_cmd}" -B tools/release-artifacts.py --help >/dev/null || return
  printf '%s\n' 'Core validation: passed (managed paths; no source maintenance tests).'
}

run_fast_checks() {
  require_command git || return
  require_command bash || return
  local version_arguments=("$@")
  local node_cmd
  local mypy_cmd
  local python_cmd
  local ruff_cmd
  node_cmd="$(resolve_command node node.exe)" || return
  mypy_cmd="$(resolve_hook_command python mypy mypy.exe)" || return
  python_cmd="$(resolve_command python python3 python.exe)" || return
  ruff_cmd="$(resolve_hook_command python ruff ruff.exe)" || return

  check_git_whitespace || return
  check_powershell_line_endings "${node_cmd}" || return
  run_shell_syntax_checks || return
  "${node_cmd}" --check commitlint.config.cjs || return
  "${python_cmd}" tools/quality/check-versions.py "${version_arguments[@]}" || return
  "${ruff_cmd}" check --config tools/quality/pyproject.toml tools tests || return
  "${ruff_cmd}" format --check \
    --config tools/quality/pyproject.toml tools tests || return
  "${mypy_cmd}" --config-file tools/quality/pyproject.toml || return
}

run_fast() {
  run_fast_checks || return
}

run_static() {
  local node_cmd
  local shellcheck_cmd
  local shfmt_cmd
  node_cmd="$(resolve_command node node.exe)" || return
  shellcheck_cmd="$(resolve_command shellcheck shellcheck.exe)" || return
  shfmt_cmd="$(resolve_command shfmt shfmt.exe)" || return

  run_fast_checks --runtime || return
  run_markdown || return
  run_spelling || return
  run_yamllint || return
  run_actionlint || return
  run_powershell_static || return
  run_shellcheck_checks "$shellcheck_cmd" || return
  run_shfmt_checks "$shfmt_cmd" || return
  check_semver_pattern_drift "$node_cmd" || return
  check_initializer_commit_contract || return
  check_commit_documentation_contract || return
  check_secret_scanner_config_contract || return
  run_full_secret_scan || return
  if [ -f .github/workflows/agent-rules-update.yml ]; then
    check_agent_rules_update_workflow_contract || return
  fi
  if [ -f .github/workflows/repository-audit.yml ]; then
    check_repository_audit_workflow_contract || return
  fi
  if [ -f .github/workflows/guarded-pull-request-merge.yml ]; then
    check_guarded_pull_request_merge_workflow_contract || return
  fi
  check_release_artifact_contract || return
  check_release_skill_contract || return
  if [ -f .github/workflows/release-package.yml ]; then
    check_release_package_portability || return
    check_release_guard_contract || return
  fi
  run_python_coverage || return
  run_shell_behavior_tests || return
  run_script_smoke || return
  run_commitlint || return
}

run_readonly() {
  require_command git || return
  require_command bash || return

  local actionlint_cmd
  local betterleaks_cmd=""
  local codespell_cmd
  local commitlint_cmd
  local gitleaks_cmd
  local markdownlint_cmd
  local node_cmd
  local shellcheck_cmd
  local shfmt_cmd
  local yamllint_cmd
  actionlint_cmd="$(resolve_command actionlint actionlint.exe)" || return
  codespell_cmd="$(resolve_command codespell codespell.cmd codespell.exe)" || return
  commitlint_cmd="$(resolve_hook_node_tool commitlint)" || return
  gitleaks_cmd="$(resolve_command gitleaks gitleaks.exe)" || return
  if command -v betterleaks >/dev/null 2>&1; then
    betterleaks_cmd="$(command -v betterleaks)" || return
  elif command -v betterleaks.exe >/dev/null 2>&1; then
    betterleaks_cmd="$(command -v betterleaks.exe)" || return
  fi
  markdownlint_cmd="$(resolve_hook_node_tool markdownlint-cli2)" || return
  node_cmd="$(resolve_command node node.exe)" || return
  shellcheck_cmd="$(resolve_command shellcheck shellcheck.exe)" || return
  shfmt_cmd="$(resolve_command shfmt shfmt.exe)" || return
  yamllint_cmd="$(resolve_command yamllint yamllint.exe)" || return

  "$markdownlint_cmd" --config .markdownlint-cli2.yaml "**/*.md" || return
  "$codespell_cmd" --config .codespellrc . || return
  "$yamllint_cmd" -c tools/quality/yamllint.yaml . || return
  "$actionlint_cmd" || return
  check_git_whitespace || return
  check_powershell_line_endings "$node_cmd" || return
  run_shell_syntax_checks || return
  run_shellcheck_checks "$shellcheck_cmd" || return
  run_shfmt_checks "$shfmt_cmd" || return
  check_semver_pattern_drift "$node_cmd" || return
  check_initializer_commit_contract || return
  check_commit_documentation_contract || return
  check_secret_scanner_config_contract || return
  if [ -f .github/workflows/agent-rules-update.yml ]; then
    check_agent_rules_update_workflow_contract || return
  fi
  if [ -f .github/workflows/repository-audit.yml ]; then
    check_repository_audit_workflow_contract || return
  fi
  if [ -f .github/workflows/guarded-pull-request-merge.yml ]; then
    check_guarded_pull_request_merge_workflow_contract || return
  fi
  check_release_artifact_contract || return
  check_release_skill_contract || return
  if [ -f .github/workflows/release-package.yml ]; then
    check_release_package_portability || return
    check_release_guard_contract || return
  fi
  run_powershell_parse_readonly || return
  "$node_cmd" --check commitlint.config.cjs || return
  run_commitlint_readonly "$commitlint_cmd" || return
  check_secret_scanner_behavior "$gitleaks_cmd" || return
  if [ -n "$betterleaks_cmd" ]; then
    check_secret_scanner_behavior "$betterleaks_cmd" || return
  fi
  run_full_secret_scan || return
}
