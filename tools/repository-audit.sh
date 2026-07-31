#!/usr/bin/env bash
set -euo pipefail

mode="${1:-all}"

if [ "$mode" = "readonly" ]; then
  export GIT_OPTIONAL_LOCKS=0
fi

repository_root="$(git rev-parse --show-toplevel)"
cd "$repository_root"

audit_temp=""
audit_temp_parent=""
audit_temp_parent_created="false"

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
    CYGWIN*|MINGW*|MSYS*)
      resolve_command powershell.exe pwsh.exe pwsh
      return
      ;;
  esac

  resolve_command pwsh pwsh.exe powershell.exe
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
    CYGWIN*|MINGW*|MSYS*)
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

  if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ]; then
    git diff --check "origin/$GITHUB_BASE_REF...HEAD"
  elif [ -n "${BEFORE_SHA:-}" ]; then
    if [ "$BEFORE_SHA" != "$zero_sha" ]; then
      git diff --check "$BEFORE_SHA..HEAD"
    else
      git diff-tree --check --root --no-commit-id -r HEAD
    fi
  else
    git diff --check
    git diff --cached --check
    git diff-tree --check --root --no-commit-id -r HEAD
  fi
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

function extractPythonPattern() {
  const content = readFile("tools/backup-target-directory.py");
  const block = content.match(
    /^SEMVER_TAG_PATTERN = re\.compile\(\n([\s\S]*?)^\)$/m
  );
  if (!block) {
    throw new Error("Unable to extract Python backup SemVer pattern.");
  }

  const parts = [];
  const expression = /^\s*r"([^"]*)"$/gm;
  let match = expression.exec(block[1]);
  while (match) {
    parts.push(match[1]);
    match = expression.exec(block[1]);
  }

  if (parts.length === 0) {
    throw new Error("Unable to extract Python backup SemVer fragments.");
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
    "tools/build-release-package.ps1",
    extractSingle(
      "tools/build-release-package.ps1",
      /^\$SemVerTagPattern = "([^"]+)"$/m,
      "release package SemVer pattern"
    ),
  ],
  ["tools/backup-target-directory.py", extractPythonPattern()],
  [".github/workflows/release-package.yml", extractWorkflowPattern()],
]);

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
}

run_commitlint() {
  require_command npx

  local zero_sha="0000000000000000000000000000000000000000"
  local from_ref=""
  local commit_count

  if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ] && [ -n "${GITHUB_BASE_REF:-}" ]; then
    from_ref="origin/$GITHUB_BASE_REF"
  elif [ -n "${BEFORE_SHA:-}" ] && [ "$BEFORE_SHA" != "$zero_sha" ]; then
    from_ref="$BEFORE_SHA"
  elif git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    from_ref="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')"
  fi

  if [ -n "$from_ref" ]; then
    commit_count="$(git rev-list --count "$from_ref..HEAD")"
    if [ "$commit_count" -eq 0 ]; then
      return
    fi

    NPM_CONFIG_IGNORE_SCRIPTS=true npx --yes @commitlint/cli@21.0.2 \
      --config commitlint.config.cjs \
      --from "$from_ref" \
      --to HEAD
  else
    git log -1 --format=%B HEAD | NPM_CONFIG_IGNORE_SCRIPTS=true \
      npx --yes @commitlint/cli@21.0.2 --config commitlint.config.cjs
  fi
}

run_markdown() {
  require_command npx
  NPM_CONFIG_IGNORE_SCRIPTS=true npx --yes markdownlint-cli2@0.22.1 "**/*.md"
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
  cat > "$parse_script" <<'PS'
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

  "$pwsh_cmd" -NoProfile -ExecutionPolicy Bypass -File \
    "$(to_pwsh_path "$parse_script")" \
    "$(to_pwsh_path "$repository_root/tools/build-release-package.ps1")" \
    "$(to_pwsh_path "$repository_root/tools/git-init.ps1")"
}

run_powershell_parse_readonly() {
  local pwsh_cmd
  local build_release_package_path
  local git_init_path
  pwsh_cmd="$(resolve_powershell_command)"
  build_release_package_path="$(
    to_pwsh_path "$repository_root/tools/build-release-package.ps1"
  )"
  git_init_path="$(to_pwsh_path "$repository_root/tools/git-init.ps1")"

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

  local zero_sha="0000000000000000000000000000000000000000"
  local from_ref=""
  local commit_count

  if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ] &&
    [ -n "${GITHUB_BASE_REF:-}" ]; then
    from_ref="origin/$GITHUB_BASE_REF"
  elif [ -n "${BEFORE_SHA:-}" ] && [ "$BEFORE_SHA" != "$zero_sha" ]; then
    from_ref="$BEFORE_SHA"
  elif git rev-parse --abbrev-ref --symbolic-full-name \
    '@{upstream}' >/dev/null 2>&1; then
    from_ref="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')"
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

run_script_smoke() {
  require_command bash
  require_command git
  local python_cmd
  local pwsh_cmd
  python_cmd="$(resolve_command python python3 python.exe)"
  pwsh_cmd="$(resolve_powershell_command)"

  ensure_audit_temp

  export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-Codex}"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-codex@example.com}"
  export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-Codex}"
  export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-codex@example.com}"

  "$python_cmd" -B -m unittest discover \
    -s tests \
    -p "test_*.py"

  local complex_semver_tag="v1.0.0-rc.1+build.1"
  local git_init_ps1
  local build_release_package_ps1
  git_init_ps1="$(to_pwsh_path "$repository_root/tools/git-init.ps1")"
  build_release_package_ps1="$(to_pwsh_path "$repository_root/tools/build-release-package.ps1")"

  bash tools/git-init.sh --help
  if bash tools/git-init.sh --path "$audit_temp" --tag invalid; then
    echo "Bash init accepted an invalid tag." >&2
    exit 1
  fi

  local bash_invalid_git_target="$audit_temp/git-init-bash-invalid-git"
  local bash_invalid_git_output="$audit_temp/git-init-bash-invalid-git.out"
  mkdir -p "$bash_invalid_git_target/.git"
  printf 'hello\n' > "$bash_invalid_git_target/README.md"
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
  printf 'hello\n' > "$bash_cancel_target/README.md"
  printf 'y\nn\n' | bash tools/git-init.sh \
    --path "$bash_cancel_target" \
    --tag v1.0.0
  if [ -e "$bash_cancel_target/.git" ]; then
    echo "Bash init created .git before commit confirmation." >&2
    exit 1
  fi

  local bash_target="$audit_temp/git-init-bash-smoke"
  local bash_verbose_output="$audit_temp/git-init-bash-smoke.out"
  local bash_verbose_error="$audit_temp/git-init-bash-smoke.err"
  mkdir -p "$bash_target"
  printf 'hello\n' > "$bash_target/README.md"
  printf 'hello spaces\n' > "$bash_target/notes with spaces.txt"
  printf 'y\ny\n' | bash tools/git-init.sh \
    --path "$bash_target" \
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
  if ! grep -Fx "git init $bash_target" "$bash_verbose_error" >/dev/null ||
    ! grep -Fx "git -C $bash_target add --all" "$bash_verbose_error" >/dev/null ||
    ! grep -Fx \
      "git -C $bash_target commit -m chore: initialize repository" \
      "$bash_verbose_error" >/dev/null; then
    echo "Bash verbose init did not expose init, add, and commit traces." >&2
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
  printf 'hello\n' > "$bash_semver_target/README.md"
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
  printf 'hello\n' > "$pwsh_invalid_git_target/README.md"
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
  printf 'hello\n' > "$pwsh_cancel_target/README.md"
  printf 'y\nn\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_cancel_target")" \
    --tag v1.0.0
  if [ -e "$pwsh_cancel_target/.git" ]; then
    echo "PowerShell init created .git before commit confirmation." >&2
    exit 1
  fi

  local pwsh_target="$audit_temp/git-init-pwsh-smoke"
  local pwsh_target_path
  local pwsh_verbose_output="$audit_temp/git-init-pwsh-smoke.out"
  local pwsh_verbose_error="$audit_temp/git-init-pwsh-smoke.err"
  mkdir -p "$pwsh_target"
  printf 'hello\n' > "$pwsh_target/README.md"
  printf 'hello spaces\n' > "$pwsh_target/notes with spaces.txt"
  pwsh_target_path="$(to_pwsh_path "$pwsh_target")"
  printf 'y\ny\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$pwsh_target_path" \
    --tag v1.0.0 \
    --verbose >"$pwsh_verbose_output" 2>"$pwsh_verbose_error"
  if ! tr -d '\r' < "$pwsh_verbose_output" |
    grep -E \
      '^git --git-dir=.* --work-tree=.* status --porcelain=v1 -z --untracked-files=all$' \
      >/dev/null; then
    echo "PowerShell verbose init did not expose a standalone status trace." >&2
    exit 1
  fi
  if ! tr -d '\r' < "$pwsh_verbose_output" |
    grep -Fx "  README.md" >/dev/null ||
    ! tr -d '\r' < "$pwsh_verbose_output" |
      grep -Fx "  notes with spaces.txt" >/dev/null; then
    echo "PowerShell verbose init corrupted the committable file preview." >&2
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
  printf 'hello\n' > "$pwsh_semver_target/README.md"
  printf 'y\ny\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_semver_target")" \
    --tag "$complex_semver_tag" \
    >"$pwsh_semver_output" 2>"$pwsh_semver_error"
  if tr -d '\r' < "$pwsh_semver_output" |
    grep -E '^git ' >/dev/null ||
    tr -d '\r' < "$pwsh_semver_error" |
      grep -E '^git ' >/dev/null; then
    echo "PowerShell init wrote Git traces without --verbose." >&2
    exit 1
  fi
  if [ -n "$(git -C "$pwsh_semver_target" status --short)" ]; then
    echo "PowerShell init SemVer smoke repository is not clean." >&2
    exit 1
  fi

  local release_output="$audit_temp/release-package-smoke"
  local latest_package="$release_output/latest-release-package.zip"
  "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRef local-test \
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
    names = {name for name in archive.namelist() if not name.endswith("/")}
    source = json.load(archive.open("_agent-rules-source.json"))
    files = json.load(archive.open("_starter-kit-files.json"))
    if source["schemaVersion"] != 3:
        raise SystemExit("Unexpected release provenance schema.")
    if source["repository"]["name"] != "git-starter-kit":
        raise SystemExit("Unexpected packaged repository name.")
    if files["schemaVersion"] != 2:
        raise SystemExit("Unexpected managed-file schema.")
    listed = set()
    strategies = {}
    for entry in files["files"]:
        path = entry["path"]
        listed.add(path)
        strategies[path] = entry["strategy"]
        if path not in names:
            raise SystemExit(f"Managed file missing from ZIP: {path}")
        digest = hashlib.sha256(archive.read(path)).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"Managed file digest mismatch: {path}")
        kind, canonical = canonical_digest(archive.read(path))
        if kind != entry["contentKind"] or canonical != entry["canonicalSha256"]:
            raise SystemExit(f"Managed file canonical digest mismatch: {path}")
        if entry["strategy"] not in {
            "agent-rules", "initialize-only", "merge", "replace"
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
    expected_strategies = {
        ".github/workflows/agent-rules-update.yml": "replace",
        "AGENTS.md": "agent-rules",
        "CODING_RULES.md": "agent-rules",
        "COMMIT_RULES.md": "agent-rules",
        "DOCUMENTATION_RULES.md": "agent-rules",
        "LANGUAGE_RULES.md": "agent-rules",
        "RELEASE_RULES.md": "agent-rules",
        "_agent-rules-source.json": "agent-rules",
        "docs/SKILLS.md": "initialize-only",
        "docs/release-package.md": "initialize-only",
        "docs/repository-files.md": "initialize-only",
        "docs/repository-migration.md": "initialize-only",
        "tools/README.md": "initialize-only",
        "tools/repository-audit.sh": "initialize-only",
    }
    for path, strategy in expected_strategies.items():
        if strategies.get(path) != strategy:
            raise SystemExit(f"Unexpected upgrade strategy for {path}.")
PY

  local downstream_root="$audit_temp/downstream-package-repository"
  local downstream_package="$release_output/downstream-release-package.zip"
  local starter_commit
  starter_commit="$(git rev-parse HEAD)"
  mkdir -p "$downstream_root"
  mkdir -p "$downstream_root/.github/workflows"
  cp \
    "$repository_root/.github/workflows/agent-rules-update.yml" \
    "$downstream_root/.github/workflows/agent-rules-update.yml"
  cp \
    "$repository_root/AGENTS.md" \
    "$repository_root/CODING_RULES.md" \
    "$repository_root/COMMIT_RULES.md" \
    "$repository_root/DOCUMENTATION_RULES.md" \
    "$repository_root/LANGUAGE_RULES.md" \
    "$repository_root/RELEASE_RULES.md" \
    "$repository_root/_agent-rules-source.json" \
    "$downstream_root/"
  printf '# Downstream repository\n' >"$downstream_root/README.md"
  "$python_cmd" - "$downstream_root" "$starter_commit" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
starter_commit = sys.argv[2]
provenance_path = root / "_agent-rules-source.json"
provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
provenance["starterKit"] = {
    "repository": "https://github.com/asphyx0r/git-starter-kit",
    "ref": "v0.0.0",
    "commit": starter_commit,
}
(root / "_agent-rules-source.json").write_text(
    json.dumps(provenance, indent=2) + "\n",
    encoding="utf-8",
)
(root / "_starter-kit-files.json").write_text(
    '{"stale": true}\n',
    encoding="utf-8",
)
PY
  git init -q "$downstream_root"
  git -C "$downstream_root" config user.name "Repository Audit"
  git -C "$downstream_root" config user.email "audit@example.com"
  git -C "$downstream_root" add --all
  git -C "$downstream_root" commit -q -m "chore: initialize fixture"

  "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRoot "$(to_pwsh_path "$downstream_root")" \
    -RepositoryRef v1.0.0 \
    -RepositorySlug example/downstream \
    -AgentRulesRef "$manifest_ref" \
    -OutputDirectory "$(to_pwsh_path "$release_output")" \
    -PackageName downstream-release-package.zip

  "$python_cmd" - "$downstream_package" <<'PY'
import json
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    names = {name for name in archive.namelist() if not name.endswith("/")}
    source = json.load(archive.open("_agent-rules-source.json"))
    files = json.load(archive.open("_starter-kit-files.json"))
    listed = {entry["path"] for entry in files["files"]}
    if source["repository"]["name"] != "downstream":
        raise SystemExit("Unexpected downstream repository name.")
    if "_starter-kit-files.json" in listed:
        raise SystemExit("Generated manifest listed its previous source copy.")
    names.remove("_starter-kit-files.json")
    if names != listed:
        raise SystemExit("Downstream managed-file coverage mismatch.")
PY

  if "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRef local-test \
    -AgentRulesRef invalid \
    -OutputDirectory "$(to_pwsh_path "$release_output")"; then
    echo "Release package accepted an invalid agent rules ref." >&2
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
  bash -n .githooks/pre-commit
  bash -n .githooks/commit-msg
  bash -n tools/git-init.sh
  shellcheck --version
  shellcheck .githooks/pre-commit
  shellcheck .githooks/commit-msg
  shellcheck tools/git-init.sh
  shfmt -d -i 2 tools/git-init.sh
  check_semver_pattern_drift "$node_cmd"
  check_release_package_portability
  run_powershell_parse
  run_script_smoke
  "$node_cmd" --check commitlint.config.cjs
  run_commitlint
}

run_readonly() {
  require_command git
  require_command bash

  local actionlint_cmd
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
  bash -n .githooks/pre-commit
  bash -n .githooks/commit-msg
  bash -n tools/git-init.sh
  "$shellcheck_cmd" --version
  "$shellcheck_cmd" .githooks/pre-commit
  "$shellcheck_cmd" .githooks/commit-msg
  "$shellcheck_cmd" tools/git-init.sh
  "$shfmt_cmd" -d -i 2 tools/git-init.sh
  check_semver_pattern_drift "$node_cmd"
  check_release_package_portability
  run_powershell_parse_readonly
  "$node_cmd" --check commitlint.config.cjs
  run_commitlint_readonly "$commitlint_cmd"
  "$gitleaks_cmd" git --redact --no-banner --no-color .
}

case "$mode" in
  readonly)
    run_readonly
    ;;
  full|all)
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
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
