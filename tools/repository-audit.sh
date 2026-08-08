#!/usr/bin/env bash
set -euo pipefail

repository_root=""
audit_temp=""
audit_temp_parent=""
audit_temp_parent_created="false"
audit_all_commits_marker="__all_commits__"
stable_semver_tag_pattern='^v(0|[1-9][0-9]*)\.'
stable_semver_tag_pattern+='(0|[1-9][0-9]*)\.'
stable_semver_tag_pattern+='(0|[1-9][0-9]*)$'

cleanup() {
  if [ -n "$audit_temp" ] && [ -n "$audit_temp_parent" ]; then
    case "$audit_temp" in
    "$audit_temp_parent"/repository-audit.*)
      if [ -d "$audit_temp" ]; then
        rm -rf -- "$audit_temp"
      fi
      ;;
    *)
      echo "Refusing to remove unexpected audit path: $audit_temp" >&2
      return 1
      ;;
    esac
  fi

  if [ "$audit_temp_parent_created" = "true" ] &&
    [ -n "$audit_temp_parent" ] &&
    [ -d "$audit_temp_parent" ]; then
    rmdir "$audit_temp_parent" 2>/dev/null || true
  fi
}

usage() {
  cat <<'USAGE'
Usage: bash tools/repository-audit.sh [all|full|readonly|markdown|spelling|static]

Runs the same repository audit rules locally and in GitHub Actions.
USAGE
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

resolve_command() {
  local candidate
  for candidate in "$@"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done

  echo "Required command not found. Tried: $*" >&2
  exit 1
}

resolve_powershell_command() {
  if [ -n "${WSL_DISTRO_NAME:-}${WSL_INTEROP:-}" ] &&
    command -v powershell.exe >/dev/null 2>&1; then
    command -v powershell.exe
    return 0
  fi

  case "$(uname -s 2>/dev/null || true)" in
  CYGWIN* | MINGW* | MSYS*)
    resolve_command powershell.exe pwsh.exe pwsh
    return
    ;;
  esac

  resolve_command pwsh pwsh.exe powershell.exe
}

resolve_npx_command() {
  local platform="${1:-}"
  if [ -z "$platform" ]; then
    platform="$(uname -s 2>/dev/null || true)"
  fi

  case "$platform" in
  CYGWIN* | MINGW* | MSYS*)
    resolve_command npx.cmd
    ;;
  *)
    resolve_command npx
    ;;
  esac
}

ensure_audit_temp() {
  if [ -n "$audit_temp" ]; then
    return
  fi

  if [ -n "${WSL_DISTRO_NAME:-}${WSL_INTEROP:-}" ] &&
    command -v powershell.exe >/dev/null 2>&1; then
    audit_temp_parent="$repository_root/.tmp"
    if [ ! -d "$audit_temp_parent" ]; then
      mkdir -p "$audit_temp_parent"
      audit_temp_parent_created="true"
    fi

    audit_temp="$(mktemp -d "$audit_temp_parent/repository-audit.XXXXXX")"
    trap cleanup EXIT
    return
  fi

  audit_temp_parent="${TMPDIR:-/tmp}"
  audit_temp_parent="${audit_temp_parent%/}"
  audit_temp="$(mktemp -d "$audit_temp_parent/repository-audit.XXXXXX")"
  trap cleanup EXIT
}

to_pwsh_path() {
  case "$(uname -s 2>/dev/null || true)" in
  CYGWIN* | MINGW* | MSYS*)
    cygpath -w "$1"
    ;;
  *)
    if [ -n "${WSL_DISTRO_NAME:-}${WSL_INTEROP:-}" ] &&
      command -v wslpath >/dev/null 2>&1; then
      wslpath -w "$1"
      return
    fi

    printf '%s\n' "$1"
    ;;
  esac
}

check_git_whitespace() {
  local zero_sha="0000000000000000000000000000000000000000"
  local commit_sha
  local from_ref

  if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ]; then
    git diff --check "origin/$GITHUB_BASE_REF...HEAD"
  elif [ -n "${BEFORE_SHA:-}" ]; then
    if [ "$BEFORE_SHA" != "$zero_sha" ]; then
      git diff --check "$BEFORE_SHA..HEAD"
    else
      from_ref="$(resolve_audit_from_ref)"
      if [ "$from_ref" = "$audit_all_commits_marker" ]; then
        while IFS= read -r commit_sha; do
          git diff-tree --check --root --no-commit-id -r "$commit_sha"
        done < <(git rev-list --reverse HEAD)
      else
        git diff --check "$from_ref..HEAD"
      fi
    fi
  else
    git diff --check
    git diff --cached --check
    git diff-tree --check --root --no-commit-id -r HEAD
  fi
}

check_powershell_line_endings() {
  local node_cmd="$1"
  local powershell_path

  while IFS= read -r powershell_path; do
    POWERSHELL_PATH="$powershell_path" "$node_cmd" <<'JS'
const fs = require("fs");

const filePath = process.env.POWERSHELL_PATH;
const content = fs.readFileSync(filePath);
for (let index = 0; index < content.length; index += 1) {
  const byte = content[index];
  const previous = index > 0 ? content[index - 1] : -1;
  const next = index + 1 < content.length ? content[index + 1] : -1;
  if ((byte === 0x0a && previous !== 0x0d) ||
      (byte === 0x0d && next !== 0x0a)) {
    console.error(`PowerShell file does not use uniform CRLF: ${filePath}`);
    process.exit(1);
  }
}
JS
  done < <(git ls-files '*.ps1')
}

find_highest_reachable_stable_tag() {
  local excluded_tag="${1:-}"
  local tag

  while IFS= read -r tag; do
    if ! [[ "$tag" =~ $stable_semver_tag_pattern ]]; then
      continue
    fi

    if [ -n "$excluded_tag" ] && [ "$tag" = "$excluded_tag" ]; then
      continue
    fi

    printf '%s\n' "$tag"
    return 0
  done < <(
    git for-each-ref \
      --merged=HEAD \
      --sort=-version:refname \
      --format='%(refname:short)' \
      refs/tags
  )

  return 1
}

resolve_audit_from_ref() {
  local excluded_tag=""
  local stable_tag=""
  local zero_sha="0000000000000000000000000000000000000000"

  if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ] &&
    [ -n "${GITHUB_BASE_REF:-}" ]; then
    printf 'origin/%s\n' "$GITHUB_BASE_REF"
    return 0
  fi

  if [ -n "${BEFORE_SHA:-}" ]; then
    if [ "$BEFORE_SHA" != "$zero_sha" ]; then
      printf '%s\n' "$BEFORE_SHA"
      return 0
    fi

    if [ "${GITHUB_REF_TYPE:-}" = "tag" ]; then
      excluded_tag="${GITHUB_REF_NAME:-}"
    fi

    if stable_tag="$(find_highest_reachable_stable_tag "$excluded_tag")"; then
      printf '%s\n' "$stable_tag"
    else
      printf '%s\n' "$audit_all_commits_marker"
    fi
    return 0
  fi

  if git rev-parse --abbrev-ref --symbolic-full-name \
    '@{upstream}' >/dev/null 2>&1; then
    git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
    return 0
  fi

  return 1
}
check_semver_pattern_drift() {
  local node_cmd="$1"

  "$node_cmd" <<'JS'
const fs = require("fs");

function readFile(path) {
  return fs.readFileSync(path, "utf8").replace(/\r/g, "");
}

function extractSingle(path, pattern, label) {
  const match = readFile(path).match(pattern);
  if (!match) {
    throw new Error("Unable to extract " + label + ".");
  }

  return match[1];
}

function extractWorkflowPattern() {
  const parts = [];
  const expression = /^\s*semver_tag_pattern\+?='([^']+)'/gm;
  const content = readFile(".github/workflows/release-package.yml");
  let match = expression.exec(content);
  while (match) {
    parts.push(match[1]);
    match = expression.exec(content);
  }

  if (parts.length === 0) {
    throw new Error("Unable to extract release workflow SemVer pattern.");
  }

  return parts.join("");
}

function extractPythonPattern(path, label) {
  const content = readFile(path);
  const block = content.match(
    /^SEMVER_TAG_PATTERN = re\.compile\(\n([\s\S]*?)^\)$/m
  );
  if (!block) {
    throw new Error("Unable to extract " + label + " SemVer pattern.");
  }

  const parts = [];
  const expression = /^\s*r"([^"]*)"$/gm;
  let match = expression.exec(block[1]);
  while (match) {
    parts.push(match[1]);
    match = expression.exec(block[1]);
  }

  if (parts.length === 0) {
    throw new Error("Unable to extract " + label + " SemVer fragments.");
  }

  return parts.join("");
}

const patterns = new Map([
  [
    "tools/git-init.sh",
    extractSingle(
      "tools/git-init.sh",
      /^semver_tag_pattern='([^']+)'$/m,
      "Bash init SemVer pattern"
    ),
  ],
  [
    "tools/git-init.ps1",
    extractSingle(
      "tools/git-init.ps1",
      /^\$SemVerTagPattern = "([^"]+)"$/m,
      "PowerShell init SemVer pattern"
    ),
  ],
  [
    "tools/backup-target-directory.py",
    extractPythonPattern("tools/backup-target-directory.py", "Python backup"),
  ],
]);

patterns.set(
  "tools/starter-kit-manifest.py",
  extractPythonPattern(
    "tools/starter-kit-manifest.py",
    "starter manifest"
  )
);

if (fs.existsSync("tools/build-release-package.ps1")) {
  patterns.set(
    "tools/build-release-package.ps1",
    extractSingle(
      "tools/build-release-package.ps1",
      /^\$SemVerTagPattern = "([^"]+)"$/m,
      "release package SemVer pattern"
    )
  );
}
if (fs.existsSync(".github/workflows/release-package.yml")) {
  patterns.set(".github/workflows/release-package.yml", extractWorkflowPattern());
}

const expected = patterns.values().next().value;
for (const [source, pattern] of patterns) {
  if (pattern !== expected) {
    console.error("SemVer validation pattern drift in " + source + ".");
    process.exit(1);
  }
}
JS
}

check_release_package_portability() {
  # shellcheck disable=SC2016
  if grep -F \
    'toolkit_path="$RUNNER_TEMP/git-starter-kit-' \
    .github/workflows/release-package.yml >/dev/null; then
    echo "Release workflow hard-codes the starter-kit toolkit name." >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F \
    'repository_name="${GITHUB_REPOSITORY##*/}"' \
    .github/workflows/release-package.yml >/dev/null; then
    echo "Release workflow does not derive the packaged repository name." >&2
    exit 1
  fi

  if [ "$(grep -Fc "github.repository == 'asphyx0r/git-starter-kit'" \
    .github/workflows/release-package.yml)" -lt 4 ]; then
    echo "Release workflow does not guard canonical jobs and uploads." >&2
    exit 1
  fi

  if [ "$(grep -Fc '    timeout-minutes:' \
    .github/workflows/release-package.yml)" -lt 2 ]; then
    echo "Release workflow does not set a timeout on every job." >&2
    exit 1
  fi
}

check_agent_rules_update_workflow_contract() {
  local workflow_path=".github/workflows/agent-rules-update.yml"
  local sync_message="chore(agents): sync agent rules to \${RULES_REF}"

  if ! grep -F "  release:" "$workflow_path" >/dev/null ||
    ! grep -F "    types: [published]" "$workflow_path" >/dev/null ||
    ! grep -F "github.event_name == 'release' ||" \
      "$workflow_path" >/dev/null ||
    ! grep -F "vars.AGENT_RULES_SYNC_ENABLED != 'false'" \
      "$workflow_path" >/dev/null; then
    printf '%s\n' \
      "Agent rules workflow does not require synchronization on release." >&2
    exit 1
  fi

  if [ "$(grep -Fc '    timeout-minutes:' "$workflow_path")" -lt 1 ]; then
    printf '%s\n' "Agent rules workflow does not set a job timeout." >&2
    exit 1
  fi

  if [ "$(grep -Fc "${sync_message}" "$workflow_path")" -ne 2 ]; then
    printf '%s\n' \
      "Agent rules workflow does not use the accepted agents scope." >&2
    exit 1
  fi
}

check_repository_audit_workflow_contract() {
  local workflow_path=".github/workflows/repository-audit.yml"

  if ! grep -F "  release:" "$workflow_path" >/dev/null ||
    ! grep -F "    types: [published]" "$workflow_path" >/dev/null ||
    ! grep -F "github.event_name == 'release' &&" \
      "$workflow_path" >/dev/null ||
    ! grep -F "'0000000000000000000000000000000000000000' ||" \
      "$workflow_path" >/dev/null; then
    printf '%s\n' \
      "Repository audit workflow does not audit every published release." >&2
    exit 1
  fi

  if [ "$(grep -Fc '    timeout-minutes:' "$workflow_path")" -lt 4 ]; then
    printf '%s\n' \
      "Repository audit workflow does not set a timeout on every job." >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F "  repository-audit:" "$workflow_path" >/dev/null ||
    ! grep -F "'Repository audit (manual)' || 'Repository audit'" \
      "$workflow_path" >/dev/null ||
    ! grep -F 'if: ${{ always() }}' "$workflow_path" >/dev/null; then
    printf '%s\n' \
      "Repository audit workflow does not publish distinct aggregate checks." \
      >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F 'MARKDOWN_RESULT: ${{ needs.markdown.result }}' \
    "$workflow_path" >/dev/null ||
    ! grep -F 'SPELLING_RESULT: ${{ needs.spelling.result }}' \
      "$workflow_path" >/dev/null ||
    ! grep -F 'STATIC_RESULT: ${{ needs.static.result }}' \
      "$workflow_path" >/dev/null ||
    ! grep -F '[ "$STATIC_RESULT" != "success" ]' \
      "$workflow_path" >/dev/null; then
    printf '%s\n' \
      "Repository audit aggregate check does not require every child job." >&2
    exit 1
  fi
}

check_initializer_commit_contract() {
  local initializer

  for initializer in tools/git-init.sh tools/git-init.ps1; do
    if ! grep -F 'commitlint --edit' "$initializer" >/dev/null ||
      ! grep -F 'core.hooksPath=.githooks' "$initializer" >/dev/null ||
      ! grep -F -- '--file=' "$initializer" >/dev/null ||
      ! grep -F -- '--cleanup=verbatim' "$initializer" >/dev/null ||
      ! grep -F 'Recorded commit message differs' "$initializer" >/dev/null; then
      printf 'Initializer omits exact-file commit validation: %s\n' \
        "$initializer" >&2
      exit 1
    fi
  done

  if grep -F 'commit -m' tools/git-init.sh >/dev/null ||
    grep -F '"commit", "-m"' tools/git-init.ps1 >/dev/null; then
    printf '%s\n' \
      "Initializer still constructs its initial commit with -m." >&2
    exit 1
  fi
}

check_commit_documentation_contract() {
  # shellcheck disable=SC2016
  if ! grep -F 'commitlint --edit /path/to/commit-message.txt' \
    CONTRIBUTING.md >/dev/null ||
    ! grep -F 'git -c core.hooksPath=.githooks commit' \
      CONTRIBUTING.md >/dev/null ||
    ! grep -F 'Never use `-m` or `--no-verify`' \
      CONTRIBUTING.md >/dev/null; then
    printf '%s\n' \
      "Contributing guide omits blocking exact-file commit validation." >&2
    exit 1
  fi
}

check_release_guard_contract() {
  local reference_path=".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt"
  local release_reference_path=".agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt"
  local workflow_path=".github/workflows/release-package.yml"

  if [ ! -f "$release_reference_path" ]; then
    printf '%s\n' "Starter release guard extension is missing." >&2
    exit 1
  fi

  if grep -F "token d'installation de la GitHub App" \
    "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard requires obsolete GitHub App authentication." >&2
    exit 1
  fi

  if ! grep -F \
    "les tags historiques d'un autre type comme des exceptions" \
    "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not preserve historical tag exceptions." >&2
    exit 1
  fi

  if ! grep -F "identifie le plus grand tag SemVer stable" \
    "$reference_path" >/dev/null ||
    ! grep -F "présents localement ou sur \`origin\`" \
      "$reference_path" >/dev/null ||
    grep -F "Identifie le dernier tag stable au format SemVer" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not use the highest local or remote SemVer tag." >&2
    exit 1
  fi

  if ! grep -F "Il peut y avoir zéro, un ou plusieurs commits." \
    "$reference_path" >/dev/null ||
    ! grep -F "aucun nouveau commit n'est nécessaire" \
      "$reference_path" >/dev/null ||
    grep -F "aucun changement attendu n'est staged" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard still requires exactly one new commit." >&2
    exit 1
  fi

  if ! grep -F "crée un commit distinct de" \
    "$reference_path" >/dev/null ||
    ! grep -F "préparation du changelog en répétant" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not isolate changelog preparation." >&2
    exit 1
  fi

  if ! grep -F 'git fsck --full' "$reference_path" >/dev/null ||
    ! grep -F 'betterleaks git --staged --redact --no-banner' \
      "$reference_path" >/dev/null ||
    ! grep -F 'gitleaks protect --staged --redact --no-banner' \
      "$reference_path" >/dev/null ||
    ! grep -F 'commitlint --print-config json' \
      "$reference_path" >/dev/null ||
    ! grep -F 'commitlint --edit <fichier-temporaire>' \
      "$reference_path" >/dev/null ||
    grep -F 'git fsck --connectivity-only' \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard omits required commit or repository checks." >&2
    exit 1
  fi

  if ! grep -F 'git -c core.hooksPath=.githooks commit' \
    "$reference_path" >/dev/null ||
    ! grep -F -- '--file=<même-fichier-temporaire>' \
      "$reference_path" >/dev/null ||
    ! grep -F "N'utilise jamais \`git commit -m\`" \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      "Release guard does not commit the exact validated message through hooks." \
      >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F 'codex/release-preflight-<tag>-<sha-court>' \
    "$reference_path" >/dev/null ||
    ! grep -F 'tools/verify-repository-audit-runs.py' \
      "$reference_path" >/dev/null ||
    ! grep -F 'le check `Repository audit` fourni' \
      "$reference_path" >/dev/null ||
    ! grep -F 'REPOSITORY_AUDIT_STATUS=incomplete' \
      "$reference_path" >/dev/null ||
    ! grep -F 'Un autre run vert du même SHA ne compense jamais' \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      "Release guard omits remote preflight or all-run audit enforcement." >&2
    exit 1
  fi

  if ! grep -F "autant de fois que nécessaire" \
    "$reference_path" >/dev/null ||
    ! grep -F "immédiatement avant chaque commit" \
      "$reference_path" >/dev/null ||
    grep -F "Examine une seule fois l'état du working tree" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not recheck repository status." >&2
    exit 1
  fi

  if ! grep -F "Supprime chaque \`.gitkeep\` inutile" \
    "$reference_path" >/dev/null ||
    ! grep -F "inclus explicitement sa" \
      "$reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not remove useless .gitkeep files." >&2
    exit 1
  fi

  if ! grep -F "n'exige aucun token GitHub App" \
    "$release_reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not require public source access." >&2
    exit 1
  fi

  if ! grep -F 'starter-kit-manifest.py --dry-run prepare' \
    "$release_reference_path" >/dev/null ||
    ! grep -F 'starter-kit-manifest.py prepare' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'starter-kit-manifest.py check' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'starter-kit-state' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not prepare and verify the starter manifest." >&2
    exit 1
  fi

  if ! grep -F "contient exactement deux assets nommés" \
    "$release_reference_path" >/dev/null ||
    ! grep -F 'git-starter-kit-<tag>-with-agent-rules.zip' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'git-starter-kit-<tag>-upgrade-toolkit.zip' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not require both release assets." >&2
    exit 1
  fi

  if ! grep -F '.github/workflows/agent-rules-update.yml' \
    "$release_reference_path" >/dev/null ||
    ! grep -F '.github/workflows/repository-audit.yml' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'Après le succès des trois runs' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'du job agrégateur' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' \
      "Starter release guard does not require every release workflow." >&2
    exit 1
  fi

  if grep -F "actions/create-github-app-token" \
    "$workflow_path" >/dev/null; then
    printf '%s\n' "Release workflow uses obsolete GitHub App authentication." >&2
    exit 1
  fi

  if ! grep -F "name: Upload release package" \
    "$workflow_path" >/dev/null ||
    ! grep -F "name: Upload starter upgrade toolkit" \
      "$workflow_path" >/dev/null; then
    printf '%s\n' "Release workflow does not upload both release assets." >&2
    exit 1
  fi
}

run_commitlint() {
  local from_ref=""
  local root_commit=""
  local commit_count
  local npx_cmd
  npx_cmd="$(resolve_npx_command)"

  if ! from_ref="$(resolve_audit_from_ref)"; then
    from_ref=""
  fi

  if [ "$from_ref" = "$audit_all_commits_marker" ]; then
    root_commit="$(git rev-list --max-parents=0 --reverse HEAD | tail -n 1)"
    git log -1 --format=%B "$root_commit" | NPM_CONFIG_IGNORE_SCRIPTS=true \
      "$npx_cmd" --yes @commitlint/cli@21.0.2 --config commitlint.config.cjs
    from_ref="$root_commit"
  fi

  if [ -n "$from_ref" ]; then
    commit_count="$(git rev-list --count "$from_ref..HEAD")"
    if [ "$commit_count" -eq 0 ]; then
      return
    fi

    NPM_CONFIG_IGNORE_SCRIPTS=true "$npx_cmd" --yes @commitlint/cli@21.0.2 \
      --config commitlint.config.cjs \
      --from "$from_ref" \
      --to HEAD
  else
    git log -1 --format=%B HEAD | NPM_CONFIG_IGNORE_SCRIPTS=true \
      "$npx_cmd" --yes @commitlint/cli@21.0.2 --config commitlint.config.cjs
  fi
}

run_markdown() {
  local npx_cmd
  npx_cmd="$(resolve_npx_command)"
  NPM_CONFIG_IGNORE_SCRIPTS=true \
    "$npx_cmd" --yes markdownlint-cli2@0.22.1 "**/*.md"
}

run_spelling() {
  local python_cmd
  ensure_audit_temp

  python_cmd="$(resolve_command python python3 python.exe)"

  local codespell_target="$audit_temp/codespell-target"

  "$python_cmd" -m pip install \
    --disable-pip-version-check \
    --no-input \
    --target "$codespell_target" \
    codespell==2.4.2

  local codespell_cmd="$codespell_target/bin/codespell"
  if [ ! -x "$codespell_cmd" ] && [ -x "$codespell_target/Scripts/codespell.exe" ]; then
    codespell_cmd="$codespell_target/Scripts/codespell.exe"
  fi

  PYTHONPATH="$codespell_target" "$codespell_cmd" .
}

run_powershell_parse() {
  local pwsh_cmd
  pwsh_cmd="$(resolve_powershell_command)"
  ensure_audit_temp

  local parse_script="$audit_temp/powershell-parse.ps1"
  cat >"$parse_script" <<'PS'
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)

$ErrorActionPreference = "Stop"
$errors = @()
foreach ($path in $Paths) {
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
PS

  local parse_paths=("$(to_pwsh_path "$repository_root/tools/git-init.ps1")")
  if [ -f "$repository_root/tools/build-release-package.ps1" ]; then
    parse_paths+=(
      "$(to_pwsh_path "$repository_root/tools/build-release-package.ps1")"
    )
  fi

  "$pwsh_cmd" -NoProfile -ExecutionPolicy Bypass -File \
    "$(to_pwsh_path "$parse_script")" \
    "${parse_paths[@]}"
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
  local commit_count

  if ! from_ref="$(resolve_audit_from_ref)"; then
    from_ref=""
  fi

  if [ "$from_ref" = "$audit_all_commits_marker" ]; then
    root_commit="$(git rev-list --max-parents=0 --reverse HEAD | tail -n 1)"
    git log -1 --format=%B "$root_commit" |
      "$commitlint_cmd" --config commitlint.config.cjs
    from_ref="$root_commit"
  fi

  if [ -n "$from_ref" ]; then
    commit_count="$(git rev-list --count "$from_ref..HEAD")"
    if [ "$commit_count" -eq 0 ]; then
      return
    fi

    "$commitlint_cmd" \
      --config commitlint.config.cjs \
      --from "$from_ref" \
      --to HEAD
  else
    git log -1 --format=%B HEAD |
      "$commitlint_cmd" --config commitlint.config.cjs
  fi
}

prepare_initializer_validation_fixture() {
  local fixture_root="$1"
  local strict_header_length="${2:-false}"

  mkdir -p "$fixture_root/.githooks"
  cp .githooks/commit-msg "$fixture_root/.githooks/commit-msg"
  chmod +x "$fixture_root/.githooks/commit-msg"

  if [ "$strict_header_length" = "true" ]; then
    cat >"$fixture_root/commitlint.config.cjs" <<'COMMITLINT'
module.exports = {
  rules: {
    "header-max-length": [2, "always", 10],
  },
};
COMMITLINT
  else
    cp commitlint.config.cjs "$fixture_root/commitlint.config.cjs"
  fi
}

run_script_smoke() {
  require_command bash
  require_command git
  local npx_cmd
  local python_cmd
  local pwsh_cmd
  npx_cmd="$(resolve_npx_command)"
  python_cmd="$(resolve_command python python3 python.exe)"
  pwsh_cmd="$(resolve_powershell_command)"

  ensure_audit_temp

  local initializer_bin="$audit_temp/initializer-bin"
  mkdir -p "$initializer_bin"
  cat >"$initializer_bin/commitlint" <<'COMMITLINT'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$AUDIT_NPX_COMMAND" == *.cmd ]]; then
  npx_directory="$(dirname "$AUDIT_NPX_COMMAND")"
  node_executable="$npx_directory/node.exe"
  npx_cli="$npx_directory/node_modules/npm/bin/npx-cli.js"

  if [[ -x "$node_executable" && -f "$npx_cli" ]]; then
    NPM_CONFIG_IGNORE_SCRIPTS=true \
      "$node_executable" "$npx_cli" \
      --yes @commitlint/cli@21.0.2 "$@"
    exit
  fi
fi

NPM_CONFIG_IGNORE_SCRIPTS=true \
  "$AUDIT_NPX_COMMAND" --yes @commitlint/cli@21.0.2 "$@"
COMMITLINT
  chmod +x "$initializer_bin/commitlint"
  export AUDIT_NPX_COMMAND="$npx_cmd"
  export NPM_CONFIG_CACHE="$audit_temp/npm-cache"
  export PATH="$initializer_bin:$PATH"

  export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-Codex}"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-codex@example.com}"
  export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-Codex}"
  export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-codex@example.com}"

  "$python_cmd" -B -m unittest discover \
    -s tests \
    -p "test_*.py"

  "$python_cmd" tools/starter-kit-manifest.py --help
  "$python_cmd" tools/starter-kit-manifest.py --version
  "$python_cmd" tools/starter-kit-manifest.py check

  local complex_semver_tag="v1.0.0-rc.1+build.1"
  local git_init_ps1
  git_init_ps1="$(to_pwsh_path "$repository_root/tools/git-init.ps1")"
  local build_release_package_ps1=""
  if [ -f "$repository_root/tools/build-release-package.ps1" ]; then
    build_release_package_ps1="$(
      to_pwsh_path "$repository_root/tools/build-release-package.ps1"
    )"
  fi

  bash tools/git-init.sh --help
  if bash tools/git-init.sh --path "$audit_temp" --tag invalid; then
    echo "Bash init accepted an invalid tag." >&2
    exit 1
  fi

  local bash_invalid_git_target="$audit_temp/git-init-bash-invalid-git"
  local bash_invalid_git_output="$audit_temp/git-init-bash-invalid-git.out"
  mkdir -p "$bash_invalid_git_target/.git"
  printf 'hello\n' >"$bash_invalid_git_target/README.md"
  if printf 'y\n' | bash tools/git-init.sh \
    --path "$bash_invalid_git_target" \
    --tag v1.0.0 >"$bash_invalid_git_output" 2>&1; then
    echo "Bash init accepted invalid .git metadata." >&2
    exit 1
  fi
  if ! grep -F "Target contains .git metadata" "$bash_invalid_git_output" >/dev/null; then
    echo "Bash init did not explain invalid .git metadata." >&2
    exit 1
  fi

  local bash_cancel_target="$audit_temp/git-init-bash-cancel"
  mkdir -p "$bash_cancel_target"
  printf 'hello\n' >"$bash_cancel_target/README.md"
  printf 'y\nn\n' | bash tools/git-init.sh \
    --path "$bash_cancel_target" \
    --tag v1.0.0
  if [ -e "$bash_cancel_target/.git" ]; then
    echo "Bash init created .git before commit confirmation." >&2
    exit 1
  fi

  local bash_target="$audit_temp/git-init bash smoke"
  local bash_target_argument="$bash_target/"
  local bash_verbose_output="$audit_temp/git-init-bash-smoke.out"
  local bash_verbose_error="$audit_temp/git-init-bash-smoke.err"
  mkdir -p "$bash_target"
  prepare_initializer_validation_fixture "$bash_target"
  printf 'hello\n' >"$bash_target/README.md"
  printf 'hello spaces\n' >"$bash_target/notes with spaces.txt"
  printf 'y\ny\n' | bash tools/git-init.sh \
    --path "$bash_target_argument" \
    --tag v1.0.0 \
    --verbose >"$bash_verbose_output" 2>"$bash_verbose_error"
  if grep -F "git " "$bash_verbose_output" >/dev/null; then
    echo "Bash verbose init wrote Git traces to standard output." >&2
    exit 1
  fi
  if ! grep -Fx "  README.md" "$bash_verbose_output" >/dev/null ||
    ! grep -Fx "  notes with spaces.txt" "$bash_verbose_output" >/dev/null; then
    echo "Bash verbose init corrupted the committable file preview." >&2
    exit 1
  fi
  if ! grep -Fx "git init $bash_target_argument" "$bash_verbose_error" >/dev/null ||
    ! grep -Fx "git -C $bash_target_argument add --all" "$bash_verbose_error" >/dev/null ||
    ! grep -F "commitlint --edit " "$bash_verbose_error" >/dev/null ||
    ! grep -F \
      "git -C $bash_target_argument -c core.hooksPath=.githooks commit --file=" \
      "$bash_verbose_error" >/dev/null ||
    ! grep -F -- "--cleanup=verbatim" "$bash_verbose_error" >/dev/null; then
    echo "Bash verbose init omitted exact-file validation or commit traces." >&2
    exit 1
  fi
  if [ "$(git -C "$bash_target" log -1 --format=%B)" != \
    "chore(git): initialize repository" ]; then
    echo "Bash init did not preserve the validated commit message." >&2
    exit 1
  fi
  if [ -n "$(git -C "$bash_target" status --short)" ]; then
    echo "Bash init smoke repository is not clean." >&2
    exit 1
  fi

  local bash_semver_target="$audit_temp/git-init-bash-semver-smoke"
  local bash_semver_output="$audit_temp/git-init-bash-semver-smoke.out"
  local bash_semver_error="$audit_temp/git-init-bash-semver-smoke.err"
  mkdir -p "$bash_semver_target"
  prepare_initializer_validation_fixture "$bash_semver_target"
  printf 'hello\n' >"$bash_semver_target/README.md"
  printf 'y\ny\n' | bash tools/git-init.sh \
    --path "$bash_semver_target" \
    --tag "$complex_semver_tag" \
    >"$bash_semver_output" 2>"$bash_semver_error"
  if grep -h -E '^git ' "$bash_semver_output" "$bash_semver_error" >/dev/null; then
    echo "Bash init wrote Git traces without --verbose." >&2
    exit 1
  fi
  if [ -n "$(git -C "$bash_semver_target" status --short)" ]; then
    echo "Bash init SemVer smoke repository is not clean." >&2
    exit 1
  fi

  local bash_commitlint_failure_target="$audit_temp/git-init-bash-commitlint-failure"
  local bash_commitlint_failure_output="$audit_temp/git-init-bash-commitlint-failure.out"
  mkdir -p "$bash_commitlint_failure_target"
  prepare_initializer_validation_fixture \
    "$bash_commitlint_failure_target" true
  printf 'hello\n' >"$bash_commitlint_failure_target/README.md"
  if printf 'y\ny\n' | bash tools/git-init.sh \
    --path "$bash_commitlint_failure_target" \
    --tag v1.0.0 >"$bash_commitlint_failure_output" 2>&1; then
    echo "Bash init ignored a Commitlint failure." >&2
    exit 1
  fi
  if git -C "$bash_commitlint_failure_target" rev-parse --verify HEAD \
    >/dev/null 2>&1; then
    echo "Bash init created a commit after Commitlint failed." >&2
    exit 1
  fi
  if ! grep -F "Commitlint rejected the initial commit message" \
    "$bash_commitlint_failure_output" >/dev/null; then
    echo "Bash init did not explain the blocking Commitlint failure." >&2
    exit 1
  fi

  "$pwsh_cmd" -NoProfile -File "$git_init_ps1" --help
  if "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$audit_temp")" \
    --tag invalid; then
    echo "PowerShell init accepted an invalid tag." >&2
    exit 1
  fi

  local pwsh_invalid_git_target="$audit_temp/git-init-pwsh-invalid-git"
  local pwsh_invalid_git_output="$audit_temp/git-init-pwsh-invalid-git.out"
  mkdir -p "$pwsh_invalid_git_target/.git"
  printf 'hello\n' >"$pwsh_invalid_git_target/README.md"
  if printf 'y\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_invalid_git_target")" \
    --tag v1.0.0 >"$pwsh_invalid_git_output" 2>&1; then
    echo "PowerShell init accepted invalid .git metadata." >&2
    exit 1
  fi
  if ! grep -F "Target contains .git metadata" "$pwsh_invalid_git_output" >/dev/null; then
    echo "PowerShell init did not explain invalid .git metadata." >&2
    exit 1
  fi

  local pwsh_cancel_target="$audit_temp/git-init-pwsh-cancel"
  mkdir -p "$pwsh_cancel_target"
  printf 'hello\n' >"$pwsh_cancel_target/README.md"
  printf 'y\nn\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_cancel_target")" \
    --tag v1.0.0
  if [ -e "$pwsh_cancel_target/.git" ]; then
    echo "PowerShell init created .git before commit confirmation." >&2
    exit 1
  fi

  local pwsh_target="$audit_temp/git-init pwsh smoke"
  local pwsh_expected_target_path
  local pwsh_target_path
  local pwsh_verbose_output="$audit_temp/git-init-pwsh-smoke.out"
  local pwsh_verbose_error="$audit_temp/git-init-pwsh-smoke.err"
  mkdir -p "$pwsh_target"
  prepare_initializer_validation_fixture "$pwsh_target"
  printf 'hello\n' >"$pwsh_target/README.md"
  printf 'hello spaces\n' >"$pwsh_target/notes with spaces.txt"
  pwsh_expected_target_path="$(to_pwsh_path "$pwsh_target")"
  pwsh_target_path="$(to_pwsh_path "$pwsh_target/")"
  printf 'y\ny\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$pwsh_target_path" \
    --tag v1.0.0 \
    --verbose >"$pwsh_verbose_output" 2>"$pwsh_verbose_error"
  if ! tr -d '\r' <"$pwsh_verbose_output" |
    grep -E \
      '^git --git-dir=.* --work-tree=.* status --porcelain=v1 -z --untracked-files=all$' \
      >/dev/null; then
    echo "PowerShell verbose init did not expose a standalone status trace." >&2
    exit 1
  fi
  if ! tr -d '\r' <"$pwsh_verbose_output" |
    grep -Fx "Path: $pwsh_expected_target_path" >/dev/null; then
    echo "PowerShell init did not normalize the target path." >&2
    exit 1
  fi
  if ! tr -d '\r' <"$pwsh_verbose_output" |
    grep -Fx "  README.md" >/dev/null ||
    ! tr -d '\r' <"$pwsh_verbose_output" |
    grep -Fx "  notes with spaces.txt" >/dev/null; then
    echo "PowerShell verbose init corrupted the committable file preview." >&2
    exit 1
  fi
  if ! tr -d '\r' <"$pwsh_verbose_output" |
    grep -F "commitlint --edit " >/dev/null ||
    ! tr -d '\r' <"$pwsh_verbose_output" |
    grep -F \
      "git -C $pwsh_expected_target_path -c core.hooksPath=.githooks commit --file=" \
      >/dev/null ||
    ! tr -d '\r' <"$pwsh_verbose_output" |
    grep -F -- "--cleanup=verbatim" >/dev/null; then
    echo "PowerShell init omitted exact-file validation or commit traces." >&2
    exit 1
  fi
  if [ "$(git -C "$pwsh_target" log -1 --format=%B)" != \
    "chore(git): initialize repository" ]; then
    echo "PowerShell init did not preserve the validated commit message." >&2
    exit 1
  fi
  if [ -n "$(git -C "$pwsh_target" status --short)" ]; then
    echo "PowerShell init smoke repository is not clean." >&2
    exit 1
  fi

  local pwsh_semver_target="$audit_temp/git-init-pwsh-semver-smoke"
  local pwsh_semver_output="$audit_temp/git-init-pwsh-semver-smoke.out"
  local pwsh_semver_error="$audit_temp/git-init-pwsh-semver-smoke.err"
  mkdir -p "$pwsh_semver_target"
  prepare_initializer_validation_fixture "$pwsh_semver_target"
  printf 'hello\n' >"$pwsh_semver_target/README.md"
  printf 'y\ny\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_semver_target")" \
    --tag "$complex_semver_tag" \
    >"$pwsh_semver_output" 2>"$pwsh_semver_error"
  if tr -d '\r' <"$pwsh_semver_output" |
    grep -E '^git ' >/dev/null ||
    tr -d '\r' <"$pwsh_semver_error" |
    grep -E '^git ' >/dev/null; then
    echo "PowerShell init wrote Git traces without --verbose." >&2
    exit 1
  fi
  if [ -n "$(git -C "$pwsh_semver_target" status --short)" ]; then
    echo "PowerShell init SemVer smoke repository is not clean." >&2
    exit 1
  fi

  local pwsh_commitlint_failure_target="$audit_temp/git-init-pwsh-commitlint-failure"
  local pwsh_commitlint_failure_output="$audit_temp/git-init-pwsh-commitlint-failure.out"
  mkdir -p "$pwsh_commitlint_failure_target"
  prepare_initializer_validation_fixture \
    "$pwsh_commitlint_failure_target" true
  printf 'hello\n' >"$pwsh_commitlint_failure_target/README.md"
  if printf 'y\ny\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_commitlint_failure_target")" \
    --tag v1.0.0 >"$pwsh_commitlint_failure_output" 2>&1; then
    echo "PowerShell init ignored a Commitlint failure." >&2
    exit 1
  fi
  if git -C "$pwsh_commitlint_failure_target" rev-parse --verify HEAD \
    >/dev/null 2>&1; then
    echo "PowerShell init created a commit after Commitlint failed." >&2
    exit 1
  fi
  if ! grep -F "Commitlint rejected the initial commit message" \
    "$pwsh_commitlint_failure_output" >/dev/null; then
    sed 's/^/  /' "$pwsh_commitlint_failure_output" >&2
    echo "PowerShell init did not explain the blocking Commitlint failure." >&2
    exit 1
  fi

  if [ -z "$build_release_package_ps1" ]; then
    return 0
  fi

  local release_output="$audit_temp/release-package-smoke"
  local latest_package="$release_output/latest-release-package.zip"
  "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRef local-test \
    -RepositorySlug asphyx0r/git-starter-kit \
    -AgentRulesRef latest \
    -OutputDirectory "$(to_pwsh_path "$release_output")" \
    -PackageName latest-release-package.zip

  local manifest_ref
  manifest_ref="$(
    "$python_cmd" - "$latest_package" <<'PY'
import json
import sys
import zipfile

archive = zipfile.ZipFile(sys.argv[1])
manifest = json.load(archive.open("_agent-rules-source.json"))
print(manifest["agentRules"]["ref"])
PY
  )"

  local manifest_requested_ref
  manifest_requested_ref="$(
    "$python_cmd" - "$latest_package" <<'PY'
import json
import sys
import zipfile

archive = zipfile.ZipFile(sys.argv[1])
manifest = json.load(archive.open("_agent-rules-source.json"))
print(manifest["agentRules"]["requestedRef"])
PY
  )"

  if [ "$manifest_requested_ref" != "latest" ]; then
    echo "Release package did not record requested latest ref." >&2
    exit 1
  fi

  local semver_ref_pattern='^v(0|[1-9][0-9]*)\.'
  semver_ref_pattern+='(0|[1-9][0-9]*)\.'
  semver_ref_pattern+='(0|[1-9][0-9]*)'
  if ! [[ "$manifest_ref" =~ $semver_ref_pattern ]]; then
    echo "Release package latest did not resolve to a SemVer tag." >&2
    exit 1
  fi

  "$python_cmd" - "$latest_package" <<'PY'
import hashlib
import json
import sys
import zipfile

def canonical_digest(content):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", hashlib.sha256(content).hexdigest()
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    canonical = (normalized.rstrip("\n") + "\n").encode("utf-8") if normalized else b""
    return "text", hashlib.sha256(canonical).hexdigest()

with zipfile.ZipFile(sys.argv[1]) as archive:
    archive_names = {
        name.replace("\\", "/"): name
        for name in archive.namelist()
        if not name.endswith(("/", "\\"))
    }
    names = set(archive_names)
    forbidden = {
        ".agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt",
        ".github/workflows/release-package.yml",
        "docs/release-package.md",
        "docs/upgrade-toolkit.md",
        "tests/test_starter_kit_manifest.py",
        "tests/test_starter_kit_upgrade.py",
        "tools/build-release-package.ps1",
        "tools/starter-kit-manifest.py",
        "tools/starter-kit-upgrade.py",
    }
    present_forbidden = sorted(names & forbidden)
    if present_forbidden:
        raise SystemExit(
            "Starter-only files leaked into package: " + ", ".join(present_forbidden)
        )
    source = json.load(archive.open("_agent-rules-source.json"))
    files = json.load(archive.open("_starter-kit-files.json"))
    if source["schemaVersion"] != 3:
        raise SystemExit("Unexpected release provenance schema.")
    if source["repository"]["name"] != "git-starter-kit":
        raise SystemExit("Unexpected packaged repository name.")
    if files["schemaVersion"] != 3:
        raise SystemExit("Unexpected managed-file schema.")
    starter = json.load(archive.open("starter-kit-manifest.json"))
    if starter["schemaVersion"] != 1:
        raise SystemExit("Unexpected starter-kit manifest schema.")
    starter_strategies = {
        entry["path"]: entry["strategy"] for entry in starter["files"]
    }
    for release_name in ("source", "current"):
        release = starter[release_name]
        expected_url = (
            release["repository"].rstrip("/")
            + "/releases/tag/"
            + release["ref"]
        )
        if release["releaseUrl"] != expected_url:
            raise SystemExit(f"Unexpected {release_name} release URL.")
    listed = set()
    strategies = {}
    for entry in files["files"]:
        path = entry["path"]
        listed.add(path)
        strategies[path] = entry["strategy"]
        if path not in names:
            raise SystemExit(f"Managed file missing from ZIP: {path}")
        content = archive.read(archive_names[path])
        digest = hashlib.sha256(content).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"Managed file digest mismatch: {path}")
        kind, canonical = canonical_digest(content)
        if kind != entry["contentKind"] or canonical != entry["canonicalSha256"]:
            raise SystemExit(f"Managed file canonical digest mismatch: {path}")
        if entry["strategy"] not in {
            "agent-rules",
            "initialize-only",
            "merge",
            "replace",
            "starter-kit-state",
        }:
            raise SystemExit(f"Unexpected upgrade strategy: {path}")
    names.remove("_starter-kit-files.json")
    if names != listed:
        missing = ", ".join(sorted(names - listed))
        unexpected = ", ".join(sorted(listed - names))
        raise SystemExit(
            "Managed-file coverage mismatch. "
            f"Missing: {missing or '(none)'}. "
            f"Unexpected: {unexpected or '(none)'}."
        )
    missing_core = sorted(set(starter_strategies) - listed)
    if missing_core:
        raise SystemExit(
            "Starter core missing from package: " + ", ".join(missing_core)
        )
    for path, strategy in starter_strategies.items():
        if strategies.get(path) != strategy:
            raise SystemExit(f"Starter strategy mismatch for {path}.")
    expected_merge_paths = {
        ".codespellrc",
        ".editorconfig",
        ".gitattributes",
        ".gitignore",
        ".github/workflows/repository-audit.yml",
    }
    expected_merge_paths.update(
        path
        for path in {".betterleaks.toml", ".gitleaks.toml"}
        if path in names
    )
    expected_strategy_paths = {
        "agent-rules": {
            "AGENTS.md",
            "CODING_RULES.md",
            "COMMIT_RULES.md",
            "DOCUMENTATION_RULES.md",
            "LANGUAGE_RULES.md",
            "RELEASE_RULES.md",
            "_agent-rules-source.json",
        },
        "merge": expected_merge_paths,
        "initialize-only": {
            "CHANGELOG.md",
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "README.md",
            "SECURITY.md",
            "SUPPORT.md",
            "docs/SKILLS.md",
            "docs/repository-files.md",
            "docs/repository-migration.md",
            "tools/README.md",
            "tools/repository-audit.sh",
        },
        "starter-kit-state": {"starter-kit-manifest.json"},
    }
    for strategy, expected_paths in expected_strategy_paths.items():
        actual_paths = {
            path for path, actual_strategy in strategies.items()
            if actual_strategy == strategy
        }
        if actual_paths != expected_paths:
            raise SystemExit(f"Unexpected {strategy} perimeter.")
PY

  if "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRef local-test \
    -RepositorySlug example/downstream \
    -AgentRulesRef "$manifest_ref" \
    -OutputDirectory "$(to_pwsh_path "$release_output")" \
    -PackageName rejected-downstream-package.zip; then
    echo "Release package accepted a downstream repository slug." >&2
    exit 1
  fi

  local downstream_root="$audit_temp/downstream-package-repository"
  mkdir -p "$downstream_root"
  git init -q "$downstream_root"
  git -C "$downstream_root" remote add origin \
    https://github.com/example/downstream.git
  if "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRoot "$(to_pwsh_path "$downstream_root")" \
    -RepositoryRef local-test \
    -RepositorySlug asphyx0r/git-starter-kit \
    -AgentRulesRef "$manifest_ref" \
    -OutputDirectory "$(to_pwsh_path "$release_output")" \
    -PackageName rejected-downstream-origin-package.zip; then
    echo "Release package accepted a downstream repository origin." >&2
    exit 1
  fi

  if "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRef local-test \
    -RepositorySlug asphyx0r/git-starter-kit \
    -AgentRulesRef invalid \
    -OutputDirectory "$(to_pwsh_path "$release_output")"; then
    echo "Release package accepted an invalid agent rules ref." >&2
    exit 1
  fi
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

run_static() {
  require_command git
  require_command shellcheck
  require_command shfmt
  local node_cmd
  node_cmd="$(resolve_command node node.exe)"

  check_git_whitespace
  check_powershell_line_endings "$node_cmd"
  bash -n .githooks/pre-commit
  bash -n .githooks/commit-msg
  bash -n tests/test_commit_message_validation.sh
  bash -n tools/git-init.sh
  shellcheck --version
  shellcheck .githooks/pre-commit
  shellcheck .githooks/commit-msg
  shellcheck tests/test_commit_message_validation.sh
  shellcheck tools/git-init.sh
  shfmt -d -i 2 tests/test_commit_message_validation.sh
  shfmt -d -i 2 tools/git-init.sh
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
  if [ -f .github/workflows/release-package.yml ]; then
    check_release_package_portability
    check_release_guard_contract
  fi
  run_powershell_parse
  bash tests/test_commit_message_validation.sh
  run_script_smoke
  "$node_cmd" --check commitlint.config.cjs
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
  commitlint_cmd="$(resolve_command commitlint commitlint.cmd)"
  gitleaks_cmd="$(resolve_command gitleaks gitleaks.exe)"
  if command -v betterleaks >/dev/null 2>&1; then
    betterleaks_cmd="$(command -v betterleaks)"
  elif command -v betterleaks.exe >/dev/null 2>&1; then
    betterleaks_cmd="$(command -v betterleaks.exe)"
  fi
  markdownlint_cmd="$(
    resolve_command markdownlint-cli2 markdownlint-cli2.cmd
  )"
  node_cmd="$(resolve_command node node.exe)"
  shellcheck_cmd="$(resolve_command shellcheck shellcheck.exe)"
  shfmt_cmd="$(resolve_command shfmt shfmt.exe)"
  yamllint_cmd="$(resolve_command yamllint yamllint.exe)"

  "$markdownlint_cmd" "**/*.md"
  "$codespell_cmd" .
  "$yamllint_cmd" .
  "$actionlint_cmd"
  check_git_whitespace
  check_powershell_line_endings "$node_cmd"
  bash -n .githooks/pre-commit
  bash -n .githooks/commit-msg
  bash -n tests/test_commit_message_validation.sh
  bash -n tools/git-init.sh
  "$shellcheck_cmd" --version
  "$shellcheck_cmd" .githooks/pre-commit
  "$shellcheck_cmd" .githooks/commit-msg
  "$shellcheck_cmd" tests/test_commit_message_validation.sh
  "$shellcheck_cmd" tools/git-init.sh
  "$shfmt_cmd" -d -i 2 tests/test_commit_message_validation.sh
  "$shfmt_cmd" -d -i 2 tools/git-init.sh
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

main() {
  local mode="${1:-all}"

  if [ "$mode" = "readonly" ]; then
    export GIT_OPTIONAL_LOCKS=0
  fi

  repository_root="$(git rev-parse --show-toplevel)"
  cd "$repository_root"

  case "$mode" in
  readonly)
    run_readonly
    ;;
  full | all)
    run_markdown
    run_spelling
    run_static
    ;;
  markdown)
    run_markdown
    ;;
  spelling)
    run_spelling
    ;;
  static)
    run_static
    ;;
  -h | --help | help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
