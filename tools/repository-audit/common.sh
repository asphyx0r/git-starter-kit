#!/usr/bin/env bash
# Dispatcher globals are initialized before this module is sourced.
# shellcheck disable=SC2154

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
Usage: bash tools/repository-audit.sh [all|full|readonly|markdown|spelling|static|fast|powershell-static|hook-pre-commit|hook-commit-msg|hook-pre-push]

Runs the same repository audit rules locally and in GitHub Actions.
USAGE
}

initialize_repository_root() {
  repository_root="$(git -C "${audit_script_dir}" rev-parse --show-toplevel)"
  cd "${repository_root}" || return
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

resolve_audit_to_ref() {
  local to_ref="${AUDIT_COMMIT_SHA:-HEAD}"

  if ! git rev-parse --verify --quiet "${to_ref}^{commit}" >/dev/null; then
    printf 'Unable to resolve audit commit: %s\n' "$to_ref" >&2
    return 1
  fi

  printf '%s\n' "$to_ref"
}
