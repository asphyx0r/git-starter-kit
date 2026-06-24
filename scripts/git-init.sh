#!/usr/bin/env bash
set -euo pipefail

script_version="1.0.0"
default_tag="v1.0.0"
commit_message="chore: initialize repository"
tag_message="Initial version/First commit"
# Keep this pattern aligned with repository-audit SemVer smoke tests.
semver_tag_pattern='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$'

show_help=0
show_version=0
verbose_mode=0
target_path=""
remote=""
tag="$default_tag"

usage() {
    cat <<EOF
git-init.sh $script_version

Usage:
  bash scripts/git-init.sh -p <path> [-t <tag>] [-r <remote>] [-v]

Options:
  -h, --help       Show version and help.
      --version    Show version only.
  -v, --verbose    Show additional execution traces.
  -p, --path       Target repository root. Required.
  -r, --remote     Optional origin remote URL.
  -t, --tag        SemVer Git tag. Default: $default_tag.
EOF
}

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

trace() {
    if [ "$verbose_mode" -eq 1 ]; then
        printf '%s\n' "$*"
    fi
}

require_value() {
    option_name="$1"
    value="${2:-}"

    if [ -z "$value" ] || [ "${value#-}" != "$value" ]; then
        fail "$option_name requires a value."
    fi
}

absolute_path() {
    case "$1" in
        /* | [A-Za-z]:/* | [A-Za-z]:\\*)
            printf '%s\n' "$1"
            ;;
        *)
            printf '%s/%s\n' "$(pwd -P)" "$1"
            ;;
    esac
}

git_success() {
    git "$@" >/dev/null 2>&1
}

run_git() {
    trace "git $*"
    git "$@"
}

git_status_files() {
    local preview_git_dir=""
    local status_args
    local status_file

    status_file="$(mktemp)"
    status_args=(
        -C "$target_path"
        status
        --porcelain=v1
        -z
        --untracked-files=all
    )

    if [ ! -e "$target_path/.git" ]; then
        preview_git_dir="$(mktemp -d)"
        git init --bare "$preview_git_dir" >/dev/null
        status_args=(
            --git-dir="$preview_git_dir"
            --work-tree="$target_path"
            status
            --porcelain=v1
            -z
            --untracked-files=all
        )
    fi

    if ! git "${status_args[@]}" >"$status_file"; then
        rm -f -- "$status_file"
        if [ -n "$preview_git_dir" ]; then
            rm -rf -- "$preview_git_dir"
        fi
        return 1
    fi

    while IFS= read -r -d '' entry; do
        if [ "${#entry}" -lt 4 ]; then
            continue
        fi

        printf '%s\0' "${entry:3}"
    done <"$status_file"

    rm -f -- "$status_file"
    if [ -n "$preview_git_dir" ]; then
        rm -rf -- "$preview_git_dir"
    fi
}

is_risky_path() {
    normalized_path="${1//\\//}"
    normalized_path="${normalized_path,,}"

    case "$normalized_path" in
        .env | .env.* | .envrc | */.envrc | *.env | *.env.* | \
            *.secret | *.secrets | \
            .npmrc | */.npmrc | .pypirc | */.pypirc | .netrc | */.netrc | \
            id_rsa | */id_rsa | id_rsa.* | */id_rsa.* | \
            id_ed25519 | */id_ed25519 | id_ed25519.* | */id_ed25519.* | \
            *.key | *.pem | *.p12 | *.pfx | *.jks | *.keystore | \
            *.log | *.err | *.out | *.7z | *.gz | *.rar | *.tar | \
            *.tgz | *.zip)
            return 0
            ;;
    esac

    case "/$normalized_path/" in
        */node_modules/* | */vendor/* | */.venv/* | */venv/* | */env/* | \
            */dist/* | */build/* | */coverage/* | */logs/* | */log/* | \
            */var/* | */.aws/* | */.kube/* | */.ssh/* | */tmp/* | \
            */temp/* | */.tmp/*)
            return 0
            ;;
    esac

    return 1
}

if [ "$#" -eq 0 ]; then
    usage
    exit 0
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        -h | --help)
            show_help=1
            shift
            ;;
        --version)
            show_version=1
            shift
            ;;
        -v | --verbose)
            verbose_mode=1
            shift
            ;;
        -p | --path)
            require_value "$1" "${2:-}"
            target_path="$2"
            shift 2
            ;;
        -r | --remote)
            require_value "$1" "${2:-}"
            remote="$2"
            shift 2
            ;;
        -t | --tag)
            require_value "$1" "${2:-}"
            tag="$2"
            shift 2
            ;;
        *)
            fail "Unknown argument: $1"
            ;;
    esac
done

if [ "$show_version" -eq 1 ]; then
    printf '%s\n' "$script_version"
    exit 0
fi

if [ "$show_help" -eq 1 ]; then
    usage
    exit 0
fi

if [ -z "$target_path" ]; then
    fail "--path is required."
fi

if ! [[ "$tag" =~ $semver_tag_pattern ]]; then
    fail "--tag must be a SemVer tag prefixed with v, for example v1.0.0."
fi

target_path="$(absolute_path "$target_path")"

if [ ! -d "$target_path" ]; then
    fail "Target path must be an existing directory: $target_path"
fi

target_has_content=0
for entry in "$target_path"/* "$target_path"/.[!.]* "$target_path"/..?*; do
    if [ ! -e "$entry" ]; then
        continue
    fi

    if [ "$(basename "$entry")" = ".git" ]; then
        continue
    fi

    target_has_content=1
    break
done

if [ "$target_has_content" -eq 0 ]; then
    fail "Target directory must contain files before Git initialization: $target_path"
fi

if [ -e "$target_path/.git" ]; then
    if git_success -C "$target_path" rev-parse --verify HEAD; then
        fail "Target repository already has commits: $target_path"
    fi

    if git_success -C "$target_path" rev-parse --verify "refs/tags/$tag"; then
        fail "Tag already exists in target repository: $tag"
    fi
fi

remote_display="$remote"
if [ -z "$remote_display" ]; then
    remote_display="(none)"
fi

printf 'Initialize Git using this information? [y/N]\n'
printf 'Path: %s\n' "$target_path"
printf 'Tag: %s\n' "$tag"
printf 'Remote: %s\n' "$remote_display"
IFS= read -r confirmation
confirmation="${confirmation%$'\r'}"

if [ "$confirmation" != "y" ] && [ "$confirmation" != "Y" ]; then
    printf 'Git initialization cancelled.\n'
    exit 0
fi

mapfile -d '' -t committable_files < <(git_status_files)
if [ "${#committable_files[@]}" -eq 0 ]; then
    fail "No committable files found in target directory: $target_path"
fi

printf 'Files Git can commit:\n'
for file in "${committable_files[@]}"; do
    printf '  %s\n' "$file"
done

printf 'Commit these files? [y/N]\n'
IFS= read -r commit_confirmation
commit_confirmation="${commit_confirmation%$'\r'}"

if [ "$commit_confirmation" != "y" ] && [ "$commit_confirmation" != "Y" ]; then
    printf 'Git commit cancelled.\n'
    exit 0
fi

risky_files=()
for file in "${committable_files[@]}"; do
    if is_risky_path "$file"; then
        risky_files+=("$file")
    fi
done

if [ "${#risky_files[@]}" -gt 0 ]; then
    printf 'Risky paths detected:\n'
    for file in "${risky_files[@]}"; do
        printf '  %s\n' "$file"
    done

    printf 'Continue with risky paths? [y/N]\n'
    IFS= read -r risky_confirmation
    risky_confirmation="${risky_confirmation%$'\r'}"

    if [ "$risky_confirmation" != "y" ] && [ "$risky_confirmation" != "Y" ]; then
        printf 'Git commit cancelled.\n'
        exit 0
    fi
fi

run_git init "$target_path" >/dev/null

if git_success -C "$target_path" rev-parse --verify "refs/tags/$tag"; then
    fail "Tag already exists in target repository: $tag"
fi

run_git -C "$target_path" add --all >/dev/null
run_git -C "$target_path" commit -m "$commit_message" >/dev/null
run_git -C "$target_path" branch -M main
run_git -C "$target_path" tag -a "$tag" -m "$tag_message"

if [ -n "$remote" ]; then
    run_git -C "$target_path" remote add origin "$remote"
    run_git -C "$target_path" push -u origin main --tags
fi

printf 'Git repository initialized: %s\n' "$target_path"
