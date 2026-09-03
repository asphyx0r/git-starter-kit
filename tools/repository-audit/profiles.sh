#!/usr/bin/env bash
# Common globals are initialized before this module is sourced.
# shellcheck disable=SC2154

run_commitlint() {
  local from_ref=""
  local root_commit=""
  local to_ref=""
  local commit_count
  local commitlint_cmd
  commitlint_cmd="$(resolve_hook_node_tool commitlint)"

  to_ref="$(resolve_audit_to_ref)"

  if ! from_ref="$(resolve_audit_from_ref)"; then
    from_ref=""
  fi

  if [ "$from_ref" = "$audit_all_commits_marker" ]; then
    root_commit="$(git rev-list --max-parents=0 --reverse "$to_ref" | tail -n 1)"
    git log -1 --format=%B "$root_commit" |
      "$commitlint_cmd" --config commitlint.config.cjs
    from_ref="$root_commit"
  fi

  if [ -n "$from_ref" ]; then
    commit_count="$(git rev-list --count "$from_ref..$to_ref")"
    if [ "$commit_count" -eq 0 ]; then
      return
    fi

    "$commitlint_cmd" \
      --config commitlint.config.cjs \
      --from "$from_ref" \
      --to "$to_ref"
  else
    git log -1 --format=%B "$to_ref" |
      "$commitlint_cmd" --config commitlint.config.cjs
  fi
}

run_markdown() {
  local markdownlint_cmd
  markdownlint_cmd="$(resolve_hook_node_tool markdownlint-cli2)"
  "$markdownlint_cmd" --config .markdownlint-cli2.yaml "**/*.md"
}

run_spelling() {
  local codespell_cmd
  codespell_cmd="$(resolve_command codespell codespell.cmd codespell.exe)"
  "$codespell_cmd" --config .codespellrc .
}

run_yamllint() {
  local yamllint_cmd
  yamllint_cmd="$(resolve_hook_command python yamllint yamllint.exe)" || return
  "$yamllint_cmd" -c tools/quality/yamllint.yaml .
}

run_actionlint() {
  local actionlint_cmd
  actionlint_cmd="$(resolve_command actionlint actionlint.exe)"
  "$actionlint_cmd"
}

run_powershell_parse_readonly() {
  local pwsh_cmd
  local git_init_path
  pwsh_cmd="$(resolve_powershell_command)"
  git_init_path="$(to_pwsh_path "$repository_root/tools/git-init.ps1")"
  local build_release_package_path=""
  if [ -f "$repository_root/tools/build-release-package.ps1" ]; then
    build_release_package_path="$(
      to_pwsh_path "$repository_root/tools/build-release-package.ps1"
    )"
  fi

  if [ -n "${WSL_DISTRO_NAME:-}${WSL_INTEROP:-}" ]; then
    WSLENV="${WSLENV:+$WSLENV:}AUDIT_PS_PATH_1:AUDIT_PS_PATH_2"
    export WSLENV
  fi

  # PowerShell expands these variables after Bash passes the literal command.
  # shellcheck disable=SC2016
  AUDIT_PS_PATH_1="$build_release_package_path" \
    AUDIT_PS_PATH_2="$git_init_path" \
    "$pwsh_cmd" -NoProfile -Command '
$ErrorActionPreference = "Stop"
$errors = @()
foreach ($path in @($env:AUDIT_PS_PATH_1, $env:AUDIT_PS_PATH_2)) {
    if ([string]::IsNullOrWhiteSpace($path)) {
        continue
    }
    $tokens = $null
    $parseErrors = $null
    $source = Get-Content -LiteralPath $path -Raw
    [System.Management.Automation.Language.Parser]::ParseInput(
        $source,
        $path,
        [ref]$tokens,
        [ref]$parseErrors
    ) | Out-Null

    if ($parseErrors.Count -gt 0) {
        $errors += $parseErrors
    }
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}
'
}

run_commitlint_readonly() {
  local commitlint_cmd="$1"

  local from_ref=""
  local root_commit=""
  local to_ref=""
  local commit_count

  to_ref="$(resolve_audit_to_ref)"

  if ! from_ref="$(resolve_audit_from_ref)"; then
    from_ref=""
  fi

  if [ "$from_ref" = "$audit_all_commits_marker" ]; then
    root_commit="$(git rev-list --max-parents=0 --reverse "$to_ref" | tail -n 1)"
    git log -1 --format=%B "$root_commit" |
      "$commitlint_cmd" --config commitlint.config.cjs
    from_ref="$root_commit"
  fi

  if [ -n "$from_ref" ]; then
    commit_count="$(git rev-list --count "$from_ref..$to_ref")"
    if [ "$commit_count" -eq 0 ]; then
      return
    fi

    "$commitlint_cmd" \
      --config commitlint.config.cjs \
      --from "$from_ref" \
      --to "$to_ref"
  else
    git log -1 --format=%B "$to_ref" |
      "$commitlint_cmd" --config commitlint.config.cjs
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
    bash -n "${shell_path}"
  done
}

run_shellcheck_checks() {
  local shellcheck_cmd="$1"
  local shell_path

  "${shellcheck_cmd}" --version
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
    "${shellcheck_cmd}" "${shell_path}"
  done
}

run_shfmt_checks() {
  local shfmt_cmd="$1"

  "${shfmt_cmd}" -d -i 2 \
    tests/test_commit_message_validation.sh \
    tests/test_quality_hooks.sh \
    tests/test_quality_pre_commit.sh \
    tests/test_quality_pre_push.sh
  "${shfmt_cmd}" -d -i 2 tools/git-init.sh
  "${shfmt_cmd}" -d -i 2 \
    .githooks/commit-msg \
    .githooks/pre-commit \
    .githooks/pre-push
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
    tools/repository-audit/smoke.sh
}

run_python_coverage() {
  local coverage_cmd
  coverage_cmd="$(resolve_hook_command python coverage coverage.exe)" || return
  ensure_audit_temp

  COVERAGE_FILE="${audit_temp}/.coverage" \
    "${coverage_cmd}" run \
    --rcfile=tools/quality/pyproject.toml \
    -m unittest discover -s tests -p 'test_*.py'
  COVERAGE_FILE="${audit_temp}/.coverage" \
    "${coverage_cmd}" report --rcfile=tools/quality/pyproject.toml
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
  require_command git
  local powershell_path
  local powershell_paths=()

  while IFS= read -r -d '' powershell_path; do
    powershell_paths+=("${powershell_path}")
  done < <(git ls-files -z -- '*.ps1')

  if ((${#powershell_paths[@]} == 0)); then
    return
  fi
  run_hook_powershell_static \
    "${repository_root}" "${powershell_paths[@]}"
}

run_fast_checks() {
  require_command git
  require_command bash
  local version_arguments=("$@")
  local node_cmd
  local mypy_cmd
  local python_cmd
  local ruff_cmd
  node_cmd="$(resolve_command node node.exe)"
  mypy_cmd="$(resolve_hook_command python mypy mypy.exe)"
  python_cmd="$(resolve_command python python3 python.exe)"
  ruff_cmd="$(resolve_hook_command python ruff ruff.exe)"

  check_git_whitespace
  check_powershell_line_endings "${node_cmd}"
  run_shell_syntax_checks
  "${node_cmd}" --check commitlint.config.cjs
  "${python_cmd}" tools/quality/check-versions.py "${version_arguments[@]}"
  "${ruff_cmd}" check --config tools/quality/pyproject.toml tools tests
  "${ruff_cmd}" format --check \
    --config tools/quality/pyproject.toml tools tests
  "${mypy_cmd}" --config-file tools/quality/pyproject.toml
}

run_fast() {
  run_fast_checks
}

run_static() {
  local node_cmd
  local shellcheck_cmd
  local shfmt_cmd
  node_cmd="$(resolve_command node node.exe)"
  shellcheck_cmd="$(resolve_command shellcheck shellcheck.exe)"
  shfmt_cmd="$(resolve_command shfmt shfmt.exe)"

  run_fast_checks --runtime
  run_markdown
  run_spelling
  run_yamllint
  run_actionlint
  run_powershell_static
  run_shellcheck_checks "$shellcheck_cmd"
  run_shfmt_checks "$shfmt_cmd"
  check_semver_pattern_drift "$node_cmd"
  check_initializer_commit_contract
  check_commit_documentation_contract
  check_secret_scanner_config_contract
  if [ -f .github/workflows/agent-rules-update.yml ]; then
    check_agent_rules_update_workflow_contract
  fi
  if [ -f .github/workflows/repository-audit.yml ]; then
    check_repository_audit_workflow_contract
  fi
  check_release_artifact_contract
  check_release_skill_contract
  if [ -f .github/workflows/release-package.yml ]; then
    check_release_package_portability
    check_release_guard_contract
  fi
  run_python_coverage
  run_shell_behavior_tests
  run_script_smoke
  run_commitlint
}

run_readonly() {
  require_command git
  require_command bash

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
  actionlint_cmd="$(resolve_command actionlint actionlint.exe)"
  codespell_cmd="$(resolve_command codespell codespell.cmd codespell.exe)"
  commitlint_cmd="$(resolve_hook_node_tool commitlint)"
  gitleaks_cmd="$(resolve_command gitleaks gitleaks.exe)"
  if command -v betterleaks >/dev/null 2>&1; then
    betterleaks_cmd="$(command -v betterleaks)"
  elif command -v betterleaks.exe >/dev/null 2>&1; then
    betterleaks_cmd="$(command -v betterleaks.exe)"
  fi
  markdownlint_cmd="$(resolve_hook_node_tool markdownlint-cli2)"
  node_cmd="$(resolve_command node node.exe)"
  shellcheck_cmd="$(resolve_command shellcheck shellcheck.exe)"
  shfmt_cmd="$(resolve_command shfmt shfmt.exe)"
  yamllint_cmd="$(resolve_command yamllint yamllint.exe)"

  "$markdownlint_cmd" --config .markdownlint-cli2.yaml "**/*.md"
  "$codespell_cmd" --config .codespellrc .
  "$yamllint_cmd" -c tools/quality/yamllint.yaml .
  "$actionlint_cmd"
  check_git_whitespace
  check_powershell_line_endings "$node_cmd"
  run_shell_syntax_checks
  run_shellcheck_checks "$shellcheck_cmd"
  run_shfmt_checks "$shfmt_cmd"
  check_semver_pattern_drift "$node_cmd"
  check_initializer_commit_contract
  check_commit_documentation_contract
  check_secret_scanner_config_contract
  if [ -f .github/workflows/agent-rules-update.yml ]; then
    check_agent_rules_update_workflow_contract
  fi
  if [ -f .github/workflows/repository-audit.yml ]; then
    check_repository_audit_workflow_contract
  fi
  check_release_artifact_contract
  check_release_skill_contract
  if [ -f .github/workflows/release-package.yml ]; then
    check_release_package_portability
    check_release_guard_contract
  fi
  run_powershell_parse_readonly
  "$node_cmd" --check commitlint.config.cjs
  run_commitlint_readonly "$commitlint_cmd"
  check_secret_scanner_behavior "$gitleaks_cmd"
  if [ -n "$betterleaks_cmd" ]; then
    check_secret_scanner_behavior "$betterleaks_cmd"
  fi
  "$gitleaks_cmd" git --redact --no-banner --no-color .
}
