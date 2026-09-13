#!/usr/bin/env bash
# Common globals are initialized before this module is sourced.
# shellcheck disable=SC2154

check_semver_pattern_drift() {
  local node_cmd="$1"
  local scope
  scope="$(resolve_validation_scope)" || return

  AUDIT_VALIDATION_SCOPE="${scope}" "$node_cmd" <<'JS'
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

function extractFragmentedShellPattern(path, label, variable = "semver_tag_pattern") {
  const parts = [];
  const expression = new RegExp(
    "^\\s*" + variable + "\\+?='([^']+)'",
    "gm"
  );
  const content = readFile(path);
  let match = expression.exec(content);
  while (match) {
    parts.push(match[1]);
    match = expression.exec(content);
  }

  if (parts.length === 0) {
    throw new Error("Unable to extract " + label + " SemVer pattern.");
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

if (fs.existsSync("tools/starter-kit-manifest.py") && process.env.AUDIT_VALIDATION_SCOPE !== "project") {
patterns.set(
  "tools/starter-kit-manifest.py",
  extractPythonPattern(
    "tools/starter-kit-manifest.py",
    "starter manifest"
  )
);
}
patterns.set(
  "tools/release-artifacts.py",
  extractPythonPattern("tools/release-artifacts.py", "release artifacts")
);
patterns.set(
  "tools/repository-audit/hooks.sh",
  extractFragmentedShellPattern(
    "tools/repository-audit/hooks.sh",
    "pre-push hook",
    "hook_semver_tag_pattern"
  )
);

if (fs.existsSync("tools/build-release-package.ps1") && process.env.AUDIT_VALIDATION_SCOPE !== "project") {
  patterns.set(
    "tools/build-release-package.ps1",
    extractSingle(
      "tools/build-release-package.ps1",
      /^\$SemVerTagPattern = "([^"]+)"$/m,
      "release package SemVer pattern"
    )
  );
}
if (fs.existsSync(".github/workflows/release-package.yml") && process.env.AUDIT_VALIDATION_SCOPE !== "project") {
  patterns.set(
    ".github/workflows/release-package.yml",
    extractFragmentedShellPattern(
      ".github/workflows/release-package.yml",
      "release workflow"
    )
  );
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

check_workflow_contract() {
  local workflow_name="$1"
  local workflow_path="$2"
  local versions_path="${3:-tools/quality/versions.json}"
  local python_cmd

  python_cmd="$(resolve_command python python3 python.exe)" || return
  "$python_cmd" -B tools/repository-audit/workflow-contracts.py \
    --workflow "$workflow_name" --path "$workflow_path" \
    --versions "$versions_path"
}

check_release_package_portability() {
  check_workflow_contract release-package \
    "${1:-.github/workflows/release-package.yml}" \
    "${2:-tools/quality/versions.json}"
}

check_agent_rules_update_workflow_contract() {
  check_workflow_contract agent-rules-update \
    "${1:-.github/workflows/agent-rules-update.yml}" \
    "${2:-tools/quality/versions.json}"
}

check_repository_audit_workflow_contract() {
  check_workflow_contract repository-audit \
    "${1:-.github/workflows/repository-audit.yml}" \
    "${2:-tools/quality/versions.json}"
}

check_guarded_pull_request_merge_workflow_contract() {
  check_workflow_contract guarded-pull-request-merge \
    "${1:-.github/workflows/guarded-pull-request-merge.yml}" \
    "${2:-tools/quality/versions.json}"
}

check_release_artifact_contract() {
  local main_reference_path=".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt"
  local release_reference_path=".agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt"
  local required_path
  local workflow_path="${1:-.github/workflows/release-artifacts.yml}"

  for required_path in \
    .githooks/pre-push \
    .github/workflows/release-artifacts.yml \
    templates/release/manifest.template.json \
    templates/release/manifest.schema.json \
    tests/test_release_artifacts.py \
    tools/release-artifacts-requirements.txt \
    tools/git_objects.py \
    tools/process_runner.py \
    tools/release-artifacts.py \
    tools/repository-audit/hooks.sh; do
    if [ ! -f "$required_path" ]; then
      printf 'Release artifact component is missing: %s\n' "$required_path" >&2
      exit 1
    fi
  done

  if git ls-files --error-unmatch .githooks/pre-push >/dev/null 2>&1 &&
    [ "$(git ls-files --stage .githooks/pre-push | cut -d ' ' -f 1)" != \
      "100755" ]; then
    printf '%s\n' 'The tracked pre-push hook must use Git mode 100755.' >&2
    exit 1
  fi

  if ! check_workflow_contract release-artifacts "$workflow_path"; then
    return 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F 'tools/release-artifacts.py' \
    tools/repository-audit/hooks.sh >/dev/null ||
    ! grep -F \
      'if ((check_status == 0 && ${#release_paths[@]} > 0)); then' \
      tools/repository-audit/hooks.sh >/dev/null ||
    ! grep -F -- '--expected-ref' \
      tools/repository-audit/hooks.sh >/dev/null; then
    printf '%s\n' 'Release artifact hooks are incomplete.' >&2
    exit 1
  fi

  if ! grep -F "PRÉPARATION DES ARTEFACTS D'IDENTIFICATION DE RELEASE" \
    "$main_reference_path" >/dev/null ||
    ! grep -F 'RELEASE_ARTIFACTS_STATUS=complete' \
      "$main_reference_path" >/dev/null ||
    ! grep -F 'git -c core.hooksPath=.githooks push --atomic' \
      "$main_reference_path" >/dev/null; then
    printf '%s\n' 'Release guard omits release artifact preparation.' >&2
    exit 1
  fi

  if [ -f "$release_reference_path" ] &&
    ! grep -F "inventorieront le \`starter-kit-manifest.json\` final" \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' \
      'Starter release guard omits the final starter manifest.' >&2
    exit 1
  fi
}

check_release_skill_contract() {
  local skill_path=".agents/skills/git-commit-push-tag/SKILL.md"
  local metadata_path=".agents/skills/git-commit-push-tag/agents/openai.yaml"
  local reference_path=".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt"
  local expected_steps
  local metadata_resolution_line
  local metadata_validation_line
  local phase_two_line
  local preconditions_line
  local release_metadata_line
  local steps

  for required_path in "$skill_path" "$metadata_path" "$reference_path"; do
    if [ ! -f "$required_path" ] ||
      ! git ls-files --error-unmatch "$required_path" >/dev/null 2>&1; then
      printf 'Release skill component is missing or untracked: %s\n' \
        "$required_path" >&2
      exit 1
    fi
  done

  # shellcheck disable=SC2016
  if ! grep -F \
    '[`references/git-commit-push-tag.txt`](references/git-commit-push-tag.txt)' \
    "$skill_path" >/dev/null ||
    ! grep -F 'Treat it as the sole behavioral' "$skill_path" >/dev/null ||
    ! grep -F 'allow_implicit_invocation: false' "$metadata_path" >/dev/null; then
    printf '%s\n' \
      'Release skill does not delegate exclusively to the canonical reference.' \
      >&2
    exit 1
  fi

  expected_steps="$(seq -s, 1 41)"
  steps="$(
    grep -E '^[0-9]+\.' "$reference_path" |
      sed 's/\..*$//' |
      paste -sd, -
  )"
  if [ "$steps" != "$expected_steps" ]; then
    printf '%s\n' 'Release guard steps are not contiguous from 1 through 41.' >&2
    exit 1
  fi

  preconditions_line="$(
    grep -n -m 1 -F 'PRÉCONDITIONS AVANT TOUTE MUTATION' \
      "$reference_path" | cut -d: -f1
  )"
  phase_two_line="$(
    grep -n -m 1 -F 'PHASE 2 — PRÉPARATION DU COMMIT' \
      "$reference_path" | cut -d: -f1
  )"
  # shellcheck disable=SC2016
  release_metadata_line="$(
    grep -n -m 1 -F 'program_id`, `name`, `channel`' \
      "$reference_path" | cut -d: -f1
  )"
  metadata_resolution_line="$(
    grep -n -m 1 -F 'Pour chaque valeur, utilise exclusivement' \
      "$reference_path" | cut -d: -f1
  )"
  metadata_validation_line="$(
    grep -n -m 1 -F 'Lorsque toutes les valeurs sont résolues' \
      "$reference_path" | cut -d: -f1
  )"
  if [ -z "$preconditions_line" ] || [ -z "$phase_two_line" ] ||
    [ -z "$release_metadata_line" ] ||
    [ -z "$metadata_resolution_line" ] ||
    [ -z "$metadata_validation_line" ] ||
    [ "$preconditions_line" -ge "$phase_two_line" ] ||
    [ "$release_metadata_line" -ge "$metadata_resolution_line" ] ||
    [ "$metadata_resolution_line" -ge "$metadata_validation_line" ] ||
    [ "$metadata_validation_line" -ge "$phase_two_line" ]; then
    printf '%s\n' \
      'Release prerequisites and metadata are not validated before mutation.' >&2
    exit 1
  fi

  if grep -F 'sans les déduire du repository' "$reference_path" >/dev/null ||
    ! grep -F "une source d'autorité actuelle du repository" \
      "$reference_path" >/dev/null ||
    ! grep -F "le \`manifest.json\` du plus grand tag SemVer stable" \
      "$reference_path" >/dev/null ||
    ! grep -F 'demande uniquement' "$reference_path" >/dev/null ||
    ! grep -F "N'utilise jamais \`null\`" "$reference_path" >/dev/null ||
    ! grep -F 'provenance concise par valeur' "$reference_path" >/dev/null ||
    ! grep -F 'Après validation, enregistre exactement le JSON validé' \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      'Release metadata is not resolved from evidence before user validation.' \
      >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F 'le fichier frère `git-starter-kit-release-package.txt`' \
    "$reference_path" >/dev/null ||
    ! grep -F 'AGENT_RULES_APP_CLIENT_ID' "$reference_path" >/dev/null ||
    ! grep -F 'AGENT_RULES_APP_PRIVATE_KEY' "$reference_path" >/dev/null ||
    ! grep -F 'Elle contient toujours `Repository audit`' \
      "$reference_path" >/dev/null ||
    ! grep -F 'Fixe `RELEASE_STATUS=complete` uniquement après la réussite' \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      'Universal release guard omits common provisioning or completion gates.' \
      >&2
    exit 1
  fi
  check_release_automation_contract "$reference_path" || return
}

check_release_automation_contract() {
  local reference_path="$1"
  # codespell:ignore-next-line branche
  local trusted_activation_phrase='snapshot immuable de la branche par défaut'
  # codespell:ignore-next-line branche
  local target_tag_audit_phrase='Exige sans condition que le workflow audite les pushes de la branche cible et du tag prévu.'
  # shellcheck disable=SC2016
  if ! grep -F "${trusted_activation_phrase}" "$reference_path" >/dev/null ||
    ! grep -F 'snapshot immuable de la cible pour `releaseKind`' "$reference_path" >/dev/null ||
    ! grep -F 'Les flags de la cible ne sélectionnent aucun automatisme.' "$reference_path" >/dev/null ||
    ! grep -F 'validation avant chaque opération dépendante' "$reference_path" >/dev/null ||
    ! grep -F "${target_tag_audit_phrase}" \
      "$reference_path" >/dev/null ||
    ! grep -F 'Lorsque `guardedMerge=false`' "$reference_path" >/dev/null ||
    ! grep -F 'Lorsque `releasePreflight=false`' "$reference_path" >/dev/null ||
    ! grep -F 'Pour `releaseKind=repository`' "$reference_path" >/dev/null ||
    ! grep -F -- '--dry-run prepare --kind repository' "$reference_path" >/dev/null ||
    ! grep -F -- '--force prepare --kind repository' "$reference_path" >/dev/null; then
    printf '%s\n' \
      'Universal release guard omits common provisioning or completion gates.' >&2
    return 1
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
  local commitlint_cmd
  commitlint_cmd="$(resolve_hook_node_tool commitlint)" || return
  if printf '%s\n' 'not a conventional commit message' |
    "${commitlint_cmd}" --config "${repository_root}/commitlint.config.cjs" >/dev/null 2>&1; then
    printf '%s\n' \
      'Commit-message configuration accepted an invalid conventional message.' >&2
    return 1
  fi
  printf '%s\n' 'chore(git): validate commit message' |
    "${commitlint_cmd}" --config "${repository_root}/commitlint.config.cjs"
}

check_release_guard_contract() {
  local reference_path=".agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt"
  local release_reference_path=".agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt"

  if [ ! -f "$release_reference_path" ]; then
    printf '%s\n' "Starter release guard extension is missing." >&2
    exit 1
  fi
  check_release_automation_contract "$reference_path" || return

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

  # shellcheck disable=SC2016
  if ! grep -F 'branche cible de release immuable' \
    "$reference_path" >/dev/null ||
    ! grep -F 'Limite chaque PR à un commit candidat' \
      "$reference_path" >/dev/null ||
    [[ "$(grep -F -c -- '--message-file <même-fichier-temporaire>' \
      "$reference_path")" != 2 ]] ||
    ! grep -F 'au SHA exact du squash et après cet horodatage' \
      "$reference_path" >/dev/null ||
    ! grep -F 'contrôles du changelog seulement après sa préparation pour la release' \
      "$reference_path" >/dev/null ||
    ! grep -F "et non partagée lorsque les instructions du repository l'autorisent." \
      "$reference_path" >/dev/null ||
    ! grep -F 'python tools/merge-pull-request.py request --force' \
      "$reference_path" >/dev/null ||
    ! grep -F 'revalide les artefacts contre le véritable arbre fusionné' \
      "$reference_path" >/dev/null ||
    ! grep -F 'le filtre `push.branches` couvre `codex/release-preflight-*`' \
      "$reference_path" >/dev/null; then
    printf '%s\n' \
      'Release guard omits protected-branch integration gates.' >&2
    exit 1
  fi

  if ! grep -F "contient exactement trois assets nommés" \
    "$release_reference_path" >/dev/null ||
    ! grep -F 'git-starter-kit-<tag>-with-agent-rules.zip' \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'git-starter-kit-<tag>-upgrade-toolkit.zip' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' "Release guard does not require all three release assets." >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F 'un job `build` limité à `contents: read`' \
    "$release_reference_path" >/dev/null ||
    ! grep -F 'sans `--clobber`' "$release_reference_path" >/dev/null ||
    ! grep -F 'octet pour octet les deux lignes attendues' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' 'Release guard omits the sealed publication boundary.' >&2
    exit 1
  fi

  # shellcheck disable=SC2016
  if ! grep -F \
    'Enregistre `Release package` comme workflow de release obligatoire' \
    "$release_reference_path" >/dev/null ||
    ! grep -F "Résous avec l'API GitHub l'identité exacte" \
      "$release_reference_path" >/dev/null ||
    ! grep -F 'y ajoute `Release package`' "$reference_path" >/dev/null ||
    grep -F '.github/workflows/agent-rules-update.yml' \
      "$release_reference_path" >/dev/null ||
    grep -F '.github/workflows/repository-audit.yml' \
      "$release_reference_path" >/dev/null; then
    printf '%s\n' \
      "Starter release guard duplicates or omits the package-only workflow." >&2
    exit 1
  fi

}
