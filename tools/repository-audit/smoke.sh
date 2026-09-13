#!/usr/bin/env bash
# Common globals are initialized before this module is sourced.
# shellcheck disable=SC2154

prepare_initializer_validation_fixture() {
  local fixture_root="$1"
  local strict_header_length="${2:-false}"

  mkdir -p "$fixture_root/.githooks" || return
  cp .githooks/commit-msg "$fixture_root/.githooks/commit-msg" || return
  mkdir -p "$fixture_root/tools" || return
  cp tools/repository-audit.sh "$fixture_root/tools/repository-audit.sh" || return
  cp -R tools/repository-audit "$fixture_root/tools/repository-audit" || return
  chmod +x "$fixture_root/.githooks/commit-msg" || return

  if [ "$strict_header_length" = "true" ]; then
    cat >"$fixture_root/commitlint.config.cjs" <<'COMMITLINT' || return
module.exports = {
  rules: {
    "header-max-length": [2, "always", 10],
  },
};
COMMITLINT
  else
    cp commitlint.config.cjs "$fixture_root/commitlint.config.cjs" || return
  fi

  # Model an extracted release inventory, including exact source index modes.
  cp tools/release-artifacts.py tools/git_objects.py tools/process_runner.py "$fixture_root/tools/" || return
  cp -R tools/git-inventory-context "$fixture_root/tools/" || return
  mkdir -p "$fixture_root/templates/release" || return
  cp templates/release/repository-manifest.schema.json "$fixture_root/templates/release/" || return
  printf 'hello\n' >"$fixture_root/README.md" || return
  printf 'hello spaces\n' >"$fixture_root/notes with spaces.txt" || return
  local fixture_python
  fixture_python="$(resolve_command python python3 python.exe)" || return
  "$fixture_python" -B - "$fixture_root" <<'PY' || return
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
modes = {}
for record in subprocess.check_output(["git", "ls-files", "--stage", "-z"]).split(b"\0"):
    if record:
        metadata, name = record.split(b"\t", 1)
        modes[name.decode("utf-8")] = metadata.split()[0].decode("ascii")
entries = [
    {"path": path.relative_to(root).as_posix(),
     "mode": modes.get(path.relative_to(root).as_posix(), "100644")}
    for path in sorted(root.rglob("*")) if path.is_file()
]
(root / "_starter-kit-files.json").write_text(
    json.dumps({"schemaVersion": 3, "files": entries}), encoding="utf-8"
)
PY
}

run_release_hook_smoke() {
  local python_cmd="$1"
  local fixture_root="$audit_temp/release-hook-smoke"
  local metadata_path="$audit_temp/release-hook-metadata.json"
  local tag_object_id

  mkdir -p "$fixture_root/.githooks" "$fixture_root/templates/release" \
    "$fixture_root/tools" || return
  cp .githooks/pre-push "$fixture_root/.githooks/pre-push" || return
  cp tools/repository-audit.sh "$fixture_root/tools/repository-audit.sh" || return
  cp -R tools/repository-audit "$fixture_root/tools/repository-audit" || return
  cp tools/release-artifacts.py "$fixture_root/tools/release-artifacts.py" || return
  cp tools/git_objects.py "$fixture_root/tools/git_objects.py" || return
  cp tools/process_runner.py "$fixture_root/tools/process_runner.py" || return
  cp tools/project_validation.py "$fixture_root/tools/project_validation.py" || return
  cp tools/project_config.py "$fixture_root/tools/project_config.py" || return
  cp templates/release/manifest.template.json \
    "$fixture_root/templates/release/manifest.template.json" || return
  cp templates/release/manifest.schema.json \
    "$fixture_root/templates/release/manifest.schema.json" || return
  printf '# Release hook smoke\n' >"$fixture_root/README.md" || return

  git init -q "$fixture_root" || return
  git -C "$fixture_root" config core.autocrlf false || return
  git -C "$fixture_root" config user.name "Release Hook Test" || return
  git -C "$fixture_root" config user.email "release-hook@example.com" || return
  git -C "$fixture_root" add README.md templates tools || return
  git -C "$fixture_root" commit -q -m "test: create release hook fixture" || return

  cat >"$metadata_path" <<'JSON' || return
{
  "program_id": "release-hook-smoke",
  "name": "Release Hook Smoke",
  "channel": "test",
  "critical_update": false,
  "release_notes": ["Validate the pre-push hook."],
  "update": {
    "min_source_version": "1.0.0",
    "strategy": "patch",
    "preserve_paths": [],
    "remove_obsolete_files": false,
    "backup_required": false,
    "restart_required": false,
    "rollback_supported": false,
    "migrations": []
  },
  "artifact": {
    "id": "source-tree",
    "target": {
      "os": "any",
      "arch": "any",
      "min_os_version": "not-applicable"
    }
  },
  "metadata": {
    "author": "Release Hook Test",
    "license": "MIT",
    "support_url": "https://example.com/support"
  }
}
JSON

  "$python_cmd" "$fixture_root/tools/release-artifacts.py" --force prepare \
    --release-ref v1.0.0 \
    --release-date 2026-08-18T12:00:00Z \
    --metadata-file "$metadata_path" \
    --repository-root "$fixture_root" >/dev/null || return
  git -C "$fixture_root" add VERSION SHA256SUMS manifest.json || return
  git -C "$fixture_root" commit -q -m "chore: prepare release artifacts" || return
  git -C "$fixture_root" tag -a v1.0.0 -m "Release v1.0.0" || return
  tag_object_id="$(git -C "$fixture_root" rev-parse refs/tags/v1.0.0)" || return

  printf 'refs/tags/v1.0.0 %s refs/tags/v1.0.0 %s\n' \
    "$tag_object_id" \
    '0000000000000000000000000000000000000000' |
    (
      cd "$fixture_root" || exit
      bash .githooks/pre-push origin example || return
    ) || return
}

require_smoke_python_dependencies() {
  local python_cmd="$1"

  if ! "$python_cmd" -c \
    'from jsonschema import Draft202012Validator, FormatChecker' \
    >/dev/null 2>&1; then
    printf '%s\n' \
      'Repository audit smoke requires locked Python quality dependencies.' \
      'Install them with:' \
      '  python -m pip install --disable-pip-version-check --no-input --require-hashes --requirement tools/quality/requirements.lock' \
      >&2
    return 1
  fi
}

run_starter_manifest_smoke() (
  local python_cmd="$1" release_ref release_commit tag_status
  unset GIT_COMMON_DIR GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE
  export PYTHONDONTWRITEBYTECODE=1
  release_ref="$(
    "$python_cmd" -B - "$repository_root/starter-kit-manifest.json" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(value["current"]["ref"])
PY
  )" || return
  if [[ ! "$release_ref" =~ $hook_semver_tag_pattern ]]; then
    "$python_cmd" -B tools/starter-kit-manifest.py check
    return
  fi
  if release_commit="$(git -C "$repository_root" rev-parse --verify --quiet "refs/tags/$release_ref^{commit}")"; then
    :
  else
    tag_status=$?
    if ((tag_status != 1)); then return "$tag_status"; fi
    "$python_cmd" -B tools/starter-kit-manifest.py check
    return
  fi
  local tagged_manifest="$audit_temp/starter-manifest-tagged.json"
  git -C "$repository_root" show "$release_commit:starter-kit-manifest.json" >"$tagged_manifest" || return
  "$python_cmd" -B - "$repository_root/starter-kit-manifest.json" "$tagged_manifest" <<'PY' || return
import json
import sys
from pathlib import Path

source, tagged = [json.loads(Path(path).read_text(encoding="utf-8")) for path in sys.argv[1:]]
if source != tagged:
    raise SystemExit("Tracked starter-kit manifest does not match its release tag.")
PY
  local release_root="$audit_temp/starter-manifest-release"
  env GIT_ALLOW_PROTOCOL=file git clone --quiet --local --no-hardlinks --no-checkout -- \
    "$repository_root" "$release_root" || return
  git -C "$release_root" -c core.autocrlf=false checkout --quiet --detach "$release_commit" || return
  "$python_cmd" -B "$release_root/tools/starter-kit-manifest.py" check \
    --expected-ref "$release_ref" --repository-root "$release_root" --treeish "$release_commit"
)

run_script_smoke() {
  require_command bash || return
  require_command git || return
  local commitlint_cmd
  local python_cmd
  local pwsh_cmd
  python_cmd="$(resolve_command python python3 python.exe)" || return
  require_smoke_python_dependencies "$python_cmd" || return
  commitlint_cmd="$(resolve_hook_node_tool commitlint)" || return
  pwsh_cmd="$(resolve_powershell_command)" || return

  ensure_audit_temp || return

  local initializer_bin="$audit_temp/initializer-bin"
  mkdir -p "$initializer_bin" || return
  cat >"$initializer_bin/commitlint" <<'COMMITLINT' || return
#!/usr/bin/env bash
set -euo pipefail
exec "$AUDIT_COMMITLINT_COMMAND" "$@"
COMMITLINT
  chmod +x "$initializer_bin/commitlint" || return
  export AUDIT_COMMITLINT_COMMAND="$commitlint_cmd"
  export PATH="$initializer_bin:$PATH"

  export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-Codex}"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-codex@example.com}"
  export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-Codex}"
  export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-codex@example.com}"

  "$python_cmd" tools/starter-kit-manifest.py --help || return
  "$python_cmd" tools/starter-kit-manifest.py --version || return
  run_starter_manifest_smoke "$python_cmd" || return
  "$python_cmd" tools/release-artifacts.py --help || return
  "$python_cmd" tools/release-artifacts.py --version || return
  run_release_hook_smoke "$python_cmd" || return

  local complex_semver_tag="v1.0.0-rc.1+build.1"
  local git_init_ps1
  git_init_ps1="$(to_pwsh_path "$repository_root/tools/git-init.ps1" "$pwsh_cmd")" || return
  local build_release_package_ps1=""
  if [ -f "$repository_root/tools/build-release-package.ps1" ]; then
    build_release_package_ps1="$(
      to_pwsh_path "$repository_root/tools/build-release-package.ps1" "$pwsh_cmd"
    )" || return
  fi

  bash tools/git-init.sh --help || return
  if bash tools/git-init.sh --path "$audit_temp" --tag invalid; then
    echo "Bash init accepted an invalid tag." >&2
    exit 1
  fi

  local bash_invalid_git_target="$audit_temp/git-init-bash-invalid-git"
  local bash_invalid_git_output="$audit_temp/git-init-bash-invalid-git.out"
  mkdir -p "$bash_invalid_git_target/.git" || return
  printf 'hello\n' >"$bash_invalid_git_target/README.md" || return
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
  mkdir -p "$bash_cancel_target" || return
  printf 'hello\n' >"$bash_cancel_target/README.md" || return
  printf 'y\nn\n' | bash tools/git-init.sh \
    --path "$bash_cancel_target" \
    --tag v1.0.0 || return
  if [ -e "$bash_cancel_target/.git" ]; then
    echo "Bash init created .git before commit confirmation." >&2
    exit 1
  fi

  local bash_target="$audit_temp/git-init bash smoke"
  local bash_target_argument="$bash_target/"
  local bash_verbose_output="$audit_temp/git-init-bash-smoke.out"
  local bash_verbose_error="$audit_temp/git-init-bash-smoke.err"
  mkdir -p "$bash_target" || return
  prepare_initializer_validation_fixture "$bash_target" || return
  printf 'hello\n' >"$bash_target/README.md" || return
  printf 'hello spaces\n' >"$bash_target/notes with spaces.txt" || return
  printf 'y\ny\n' | bash tools/git-init.sh \
    --path "$bash_target_argument" \
    --tag v1.0.0 \
    --verbose >"$bash_verbose_output" 2>"$bash_verbose_error" || return
  if grep -F "git " "$bash_verbose_output" >/dev/null; then
    echo "Bash verbose init wrote Git traces to standard output." >&2
    exit 1
  fi
  if ! grep -Fx "  README.md" "$bash_verbose_output" >/dev/null ||
    ! grep -Fx "  notes with spaces.txt" "$bash_verbose_output" >/dev/null; then
    echo "Bash verbose init corrupted the committable file preview." >&2
    exit 1
  fi
  if ! grep -Fx "git init --initial-branch=main $bash_target_argument" "$bash_verbose_error" >/dev/null ||
    ! grep -Fx "git -C $bash_target_argument symbolic-ref HEAD refs/heads/main" "$bash_verbose_error" >/dev/null ||
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
  if [ "$(git -C "$bash_target" config --local --get core.hooksPath)" != \
    ".githooks" ]; then
    echo "Bash init did not activate repository hooks." >&2
    exit 1
  fi
  if [ -n "$(git -C "$bash_target" status --short)" ]; then
    echo "Bash init smoke repository is not clean." >&2
    exit 1
  fi

  local bash_semver_target="$audit_temp/git-init-bash-semver-smoke"
  local bash_semver_output="$audit_temp/git-init-bash-semver-smoke.out"
  local bash_semver_error="$audit_temp/git-init-bash-semver-smoke.err"
  mkdir -p "$bash_semver_target" || return
  prepare_initializer_validation_fixture "$bash_semver_target" || return
  printf 'hello\n' >"$bash_semver_target/README.md" || return
  printf 'y\ny\n' | bash tools/git-init.sh \
    --path "$bash_semver_target" \
    --tag "$complex_semver_tag" \
    >"$bash_semver_output" 2>"$bash_semver_error" || return
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
  mkdir -p "$bash_commitlint_failure_target" || return
  prepare_initializer_validation_fixture \
    "$bash_commitlint_failure_target" true || return
  printf 'hello\n' >"$bash_commitlint_failure_target/README.md" || return
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

  "$pwsh_cmd" -NoProfile -File "$git_init_ps1" --help || return
  if "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$audit_temp" "$pwsh_cmd")" \
    --tag invalid; then
    echo "PowerShell init accepted an invalid tag." >&2
    exit 1
  fi

  local pwsh_invalid_git_target="$audit_temp/git-init-pwsh-invalid-git"
  local pwsh_invalid_git_output="$audit_temp/git-init-pwsh-invalid-git.out"
  mkdir -p "$pwsh_invalid_git_target/.git" || return
  printf 'hello\n' >"$pwsh_invalid_git_target/README.md" || return
  if printf 'y\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_invalid_git_target" "$pwsh_cmd")" \
    --tag v1.0.0 >"$pwsh_invalid_git_output" 2>&1; then
    echo "PowerShell init accepted invalid .git metadata." >&2
    exit 1
  fi
  if ! grep -F "Target contains .git metadata" "$pwsh_invalid_git_output" >/dev/null; then
    echo "PowerShell init did not explain invalid .git metadata." >&2
    exit 1
  fi

  local pwsh_cancel_target="$audit_temp/git-init-pwsh-cancel"
  mkdir -p "$pwsh_cancel_target" || return
  printf 'hello\n' >"$pwsh_cancel_target/README.md" || return
  printf 'y\nn\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_cancel_target" "$pwsh_cmd")" \
    --tag v1.0.0 || return
  if [ -e "$pwsh_cancel_target/.git" ]; then
    echo "PowerShell init created .git before commit confirmation." >&2
    exit 1
  fi

  local pwsh_target="$audit_temp/git-init pwsh smoke"
  local pwsh_expected_target_path
  local pwsh_target_path
  local pwsh_verbose_output="$audit_temp/git-init-pwsh-smoke.out"
  local pwsh_verbose_error="$audit_temp/git-init-pwsh-smoke.err"
  mkdir -p "$pwsh_target" || return
  prepare_initializer_validation_fixture "$pwsh_target" || return
  printf 'hello\n' >"$pwsh_target/README.md" || return
  printf 'hello spaces\n' >"$pwsh_target/notes with spaces.txt" || return
  pwsh_expected_target_path="$(to_pwsh_path "$pwsh_target" "$pwsh_cmd")" || return
  pwsh_target_path="$(to_pwsh_path "$pwsh_target/" "$pwsh_cmd")" || return
  printf 'y\ny\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$pwsh_target_path" \
    --tag v1.0.0 \
    --verbose >"$pwsh_verbose_output" 2>"$pwsh_verbose_error" || return
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
  if [ "$(git -C "$pwsh_target" config --local --get core.hooksPath)" != \
    ".githooks" ]; then
    echo "PowerShell init did not activate repository hooks." >&2
    exit 1
  fi
  if [ -n "$(git -C "$pwsh_target" status --short)" ]; then
    echo "PowerShell init smoke repository is not clean." >&2
    exit 1
  fi

  local pwsh_semver_target="$audit_temp/git-init-pwsh-semver-smoke"
  local pwsh_semver_output="$audit_temp/git-init-pwsh-semver-smoke.out"
  local pwsh_semver_error="$audit_temp/git-init-pwsh-semver-smoke.err"
  mkdir -p "$pwsh_semver_target" || return
  prepare_initializer_validation_fixture "$pwsh_semver_target" || return
  printf 'hello\n' >"$pwsh_semver_target/README.md" || return
  printf 'y\ny\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_semver_target" "$pwsh_cmd")" \
    --tag "$complex_semver_tag" \
    >"$pwsh_semver_output" 2>"$pwsh_semver_error" || return
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
  mkdir -p "$pwsh_commitlint_failure_target" || return
  prepare_initializer_validation_fixture \
    "$pwsh_commitlint_failure_target" true || return
  printf 'hello\n' >"$pwsh_commitlint_failure_target/README.md" || return
  if printf 'y\ny\n' | "$pwsh_cmd" -NoProfile -File "$git_init_ps1" \
    --path "$(to_pwsh_path "$pwsh_commitlint_failure_target" "$pwsh_cmd")" \
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
    -OutputDirectory "$(to_pwsh_path "$release_output" "$pwsh_cmd")" \
    -PackageName latest-release-package.zip || return

  local manifest_ref
  manifest_ref="$(
    "$python_cmd" - "$latest_package" <<'PY' || return
import json
import sys
import zipfile

archive = zipfile.ZipFile(sys.argv[1])
manifest = json.load(archive.open("_agent-rules-source.json"))
print(manifest["agentRules"]["ref"])
PY
  )" || return

  local manifest_requested_ref
  manifest_requested_ref="$(
    "$python_cmd" - "$latest_package" <<'PY' || return
import json
import sys
import zipfile

archive = zipfile.ZipFile(sys.argv[1])
manifest = json.load(archive.open("_agent-rules-source.json"))
print(manifest["agentRules"]["requestedRef"])
PY
  )" || return

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

  "$python_cmd" - "$latest_package" <<'PY' || return
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
        ".github/CODEOWNERS",
        ".github/workflows/release-package.yml",
        "SHA256SUMS",
        "VERSION",
        "docs/release-package.md",
        "docs/upgrade-toolkit.md",
        "docs/repository-migration.md",
        "templates/README.md",
        "templates/README_TOOLS.md",
        "templates/CONTRIBUTING.md",
        "templates/CHANGELOG.md",
        "templates/CODE_OF_CONDUCT.md",
        "templates/SECURITY.md",
        "templates/SUPPORT.md",
        "templates/SKILLS.md",
        "tools/quality/check-coverage.py",
        "tests/test_build_release_package.py",
        "tests/test_starter_kit_manifest.py",
        "tests/test_starter_kit_upgrade.py",
        "tools/build-release-package.ps1",
        "tools/starter-kit-manifest.py",
        "tools/starter-kit-upgrade.py",
        "tools/starter_kit_upgrade/__init__.py",
        "tools/starter_kit_upgrade/application.py",
        "tools/starter_kit_upgrade/archive.py",
        "tools/starter_kit_upgrade/cli.py",
        "tools/starter_kit_upgrade/common.py",
        "tools/starter_kit_upgrade/planning.py",
        "manifest.json",
    }
    forbidden_prefixes = (
        "tools/starter_kit_upgrade/", "tests/", "docs/superpowers/",
        "templates/project/", ".superpowers/",
    )
    present_forbidden = sorted(
        name
        for name in names
        if name in forbidden or name.startswith(forbidden_prefixes)
    )
    if present_forbidden:
        raise SystemExit(
            "Starter-only files leaked into package: " + ", ".join(present_forbidden)
        )
    source = json.load(archive.open("_agent-rules-source.json"))
    files = json.load(archive.open("_starter-kit-files.json"))
    expected_agent_rule_files = {
        "AGENTS.md",
        "BRANCH_RULES.md",
        "CODING_RULES.md",
        "COMMIT_RULES.md",
        "DOCUMENTATION_RULES.md",
        "LANGUAGE_RULES.md",
        "RELEASE_RULES.md",
    }
    if source["schemaVersion"] != 3:
        raise SystemExit("Unexpected release provenance schema.")
    if set(source["agentRules"]["files"]) != expected_agent_rule_files:
        raise SystemExit("Unexpected packaged agent-rule file list.")
    if set(source["agentRules"]["fileHashes"]) != expected_agent_rule_files:
        raise SystemExit("Unexpected packaged agent-rule hash perimeter.")
    if source["repository"]["name"] != "git-starter-kit":
        raise SystemExit("Unexpected packaged repository name.")
    if files["schemaVersion"] != 3:
        raise SystemExit("Unexpected managed-file schema.")
    starter = json.load(archive.open("starter-kit-manifest.json"))
    if starter["schemaVersion"] != 1:
        raise SystemExit("Unexpected starter-kit manifest schema.")
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
    expected_quality_paths = {
        "tools/quality/PSScriptAnalyzerSettings.psd1",
        "tools/quality/check-versions.py",
        "tools/quality/install-external-tools.py",
        "tools/quality/package-lock.json",
        "tools/quality/package.json",
        "tools/quality/pyproject.toml",
        "tools/quality/requirements.in",
        "tools/quality/requirements.lock",
        "tools/quality/versions.json",
        "tools/quality/yamllint.yaml",
    }
    actual_quality_paths = {
        path for path in strategies if path.startswith("tools/quality/")
    }
    if actual_quality_paths != expected_quality_paths:
        raise SystemExit("Unexpected quality-tool distribution perimeter.")
    for path in expected_quality_paths:
        if strategies[path] != "replace":
            raise SystemExit(f"Quality tool must use replace strategy: {path}")
    names.remove("_starter-kit-files.json")
    if names != listed:
        missing = ", ".join(sorted(names - listed))
        unexpected = ", ".join(sorted(listed - names))
        raise SystemExit(
            "Managed-file coverage mismatch. "
            f"Missing: {missing or '(none)'}. "
            f"Unexpected: {unexpected or '(none)'}."
        )
    expected_merge_paths = {
        ".codespellrc",
        ".editorconfig",
        ".gitattributes",
        ".gitignore",
        ".github/dependabot.yml",
        ".github/workflows/repository-audit.yml",
    }
    expected_merge_paths.update(
        path
        for path in {".betterleaks.toml", ".gitleaks.toml"}
        if path in names
    )
    expected_strategy_paths = {
        "agent-rules": expected_agent_rule_files | {"_agent-rules-source.json"},
        "merge": expected_merge_paths,
        "initialize-only": {
            ".starter-kit-project.json",
            "CHANGELOG.md",
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "README.md",
            "SECURITY.md",
            "SUPPORT.md",
            "docs/SKILLS.md",
            "docs/repository-files.md",
            "tools/README.md",
        },
        "starter-kit-state": {"starter-kit-manifest.json"},
    }
    audit_runtime_paths = {
        "tools/repository-audit.sh",
        "tools/repository-audit/common.sh",
        "tools/repository-audit/agent-rules-transfer.sh",
        "tools/repository-audit/contracts.sh",
        "tools/repository-audit/hooks.sh",
        "tools/repository-audit/profiles.sh",
        "tools/repository-audit/security.sh",
        "tools/repository-audit/smoke.sh",
        "tools/repository-audit/workflow-contracts.py",
    }
    required_replace_paths = audit_runtime_paths | {
        "tools/initialize-repository.py", "tools/release-artifacts.py",
        "tools/git_objects.py", "tools/process_runner.py",
        "tools/project_config.py", "tools/project_validation.py",
        "tools/automation_config.py", "docs/project-configuration.md",
        "templates/release/repository-manifest.schema.json",
        "templates/GITHUB_RELEASE_NOTES.md", "commitlint.config.cjs",
    }
    for path in required_replace_paths:
        if strategies.get(path) != "replace":
            raise SystemExit(f"Required consumer runtime/resource must use replace: {path}")
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
    -OutputDirectory "$(to_pwsh_path "$release_output" "$pwsh_cmd")" \
    -PackageName rejected-downstream-package.zip; then
    echo "Release package accepted a downstream repository slug." >&2
    exit 1
  fi

  local downstream_root="$audit_temp/downstream-package-repository"
  mkdir -p "$downstream_root" || return
  git init -q "$downstream_root" || return
  git -C "$downstream_root" remote add origin \
    https://github.com/example/downstream.git || return
  if "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRoot "$(to_pwsh_path "$downstream_root" "$pwsh_cmd")" \
    -RepositoryRef local-test \
    -RepositorySlug asphyx0r/git-starter-kit \
    -AgentRulesRef "$manifest_ref" \
    -OutputDirectory "$(to_pwsh_path "$release_output" "$pwsh_cmd")" \
    -PackageName rejected-downstream-origin-package.zip; then
    echo "Release package accepted a downstream repository origin." >&2
    exit 1
  fi

  if "$pwsh_cmd" -NoProfile -File "$build_release_package_ps1" \
    -RepositoryRef local-test \
    -RepositorySlug asphyx0r/git-starter-kit \
    -AgentRulesRef invalid \
    -OutputDirectory "$(to_pwsh_path "$release_output" "$pwsh_cmd")"; then
    echo "Release package accepted an invalid agent rules ref." >&2
    exit 1
  fi
}
