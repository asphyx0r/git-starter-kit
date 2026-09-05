# Repository files

## Purpose

This document lists the files and directories that belong to this repository
template.

## Scope

This inventory covers repository-level files and directories that are included,
deferred, or explicitly excluded from the template.

## Status definitions

- `required`: included in the base template.
- `optional`: included in the template, but safe to remove or adapt in
  downstream projects.
- `deferred`: intentionally postponed until a concrete need is confirmed.
- `rejected`: intentionally excluded from the template.
- `duplicate`: excluded because another path owns the same responsibility.

## File and directory records

### `.agents/`

- Type: `directory`
- Status: `optional`
- Goal: Stores repository-scoped Codex agent assets.
- Usage: Codex discovers checked-in skills from `.agents/skills` when working
  in this repository.
- Notes: Keep agent assets generic, explicit, and documented in this
  inventory.

### `.agents/skills/`

- Type: `directory`
- Status: `optional`
- Goal: Stores reusable Codex skills for repository workflows.
- Usage: Invoke skills explicitly when their workflow is requested.
- Notes: Keep each skill focused and avoid auxiliary documentation files.

### `.agents/skills/git-commit-push-tag/`

- Type: `directory`
- Status: `optional`
- Goal: Provides the canonical guarded SemVer analysis and publication
  workflow.
- Usage: Use through `$git-commit-push-tag` only when explicitly requested.
- Notes: Repository mutation requires an explicit bump. GitHub Release
  publication requires a separate explicit parameter and a successful
  preflight of common release workflows and GitHub App configuration. Package
  CI applies only when the exact `asphyx0r/git-starter-kit` remote is active.

### `.agents/skills/git-commit-push-tag/SKILL.md`

- Type: `file`
- Status: `optional`
- Goal: Loads the canonical guarded Git workflow instructions.
- Usage: Codex loads this file after explicit skill invocation.
- Notes: The canonical reference is the generic behavioral source of truth and
  loads a separate starter-only release extension when applicable.

### `.agents/skills/git-commit-push-tag/agents/`

- Type: `directory`
- Status: `optional`
- Goal: Stores Codex app metadata for the `git-commit-push-tag` skill.
- Usage: Keep machine-facing metadata separate from the skill instructions.
- Notes: Include only metadata needed for discovery, policy, or dependencies.

### `.agents/skills/git-commit-push-tag/agents/openai.yaml`

- Type: `file`
- Status: `optional`
- Goal: Configures display metadata and explicit-invocation policy for the
  `git-commit-push-tag` skill.
- Usage: Codex uses this metadata in skill UI and invocation policy handling.
- Notes: Advertises the guarded release flow while
  `allow_implicit_invocation` remains `false`.

### `.agents/skills/git-commit-push-tag/references/`

- Type: `directory`
- Status: `optional`
- Goal: Stores the canonical workflow loaded by the skill.
- Usage: Keep behavioral reference files beside the skill that consumes them.
- Notes: Do not duplicate the canonical workflow in `SKILL.md`.

### `.agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt`

- Type: `file`
- Status: `optional`
- Goal: Defines canonical bump analysis, exact-file commit validation, explicit
  release-artifact preparation, remote audit preflight, tag, atomic final push,
  synchronization, and generic GitHub Release behavior.
- Usage: Read completely before the skill takes any action or runs Git.
- Notes: Preserve this file as the generic behavioral source of truth. It
  requires the common `Agent rules update` and `Repository audit` release runs.
  The starter-only extension adds only its package release contract.

### `.agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt`

- Type: `file`
- Status: `optional`
- Goal: Orders starter-manifest and release-artifact preparation, then adds the
  package CI and two-asset completion gate used only by
  `asphyx0r/git-starter-kit`.
- Usage: Load only through the generic skill when its exact remote matches.
- Notes: This source-repository extension adds `Release package`, prerelease
  promotion, asset, digest, and provenance checks without duplicating common
  release-run controls. It is excluded from packages distributed to derived
  repositories.

### `.betterleaks.toml`

- Type: `file`
- Status: `required`
- Goal: Defines strict Betterleaks secret scanning rules while retaining all
  rules built into the installed scanner.
- Usage: Betterleaks loads it automatically from the target repository root.
- Notes: Keep it byte-for-byte identical to `.gitleaks.toml`. Local rules catch
  credential assignments, authorization headers, and credentials in service
  URIs while allowing only explicit placeholders and variable references.

### `.codespellrc`

- Type: `file`
- Status: `required`
- Goal: Configures Codespell for lightweight spelling checks.
- Usage: Run `codespell` from the repository root.
- Notes: Checks hidden files, file names, and tracked workspace configs while
  skipping generated, dependency, report, cache, runtime, temporary, archive,
  binary, and canonical French reference paths.

### `.editorconfig`

- Type: `file`
- Status: `required`
- Goal: Defines editor-level formatting defaults for a polyglot template.
- Usage: Editors and IDEs that support EditorConfig apply these settings.
- Notes: Keep rules language-family oriented rather than framework-specific,
  with a dedicated Git config rule for tab-indented config templates.

### `.gitattributes`

- Type: `file`
- Status: `required`
- Goal: Defines Git text normalization and common binary formats.
- Usage: Git normalizes text to LF and preserves CRLF for Windows scripts.
- Notes: Keep the binary list focused on common formats.

### `.gitleaks.toml`

- Type: `file`
- Status: `required`
- Goal: Defines strict Gitleaks secret scanning rules while retaining all rules
  built into the installed scanner.
- Usage: Gitleaks loads it automatically from the target repository root.
- Notes: Keep it byte-for-byte identical to `.betterleaks.toml`. The starter-kit
  upgrade strategy merges downstream customizations instead of replacing them.

### `.github/`

- Type: `directory`
- Status: `required`
- Goal: Stores GitHub-specific community and collaboration files.
- Usage: Keep GitHub files here when the platform expects this location.
- Notes: Avoid duplicating root-level files in this directory.

### `.github/CODEOWNERS`

- Type: `file`
- Status: `optional`
- Goal: Assigns ownership of the canonical source repository to its verified
  maintainer.
- Usage: GitHub applies the single catch-all rule to every repository path.
- Notes: Contains exactly `* @asphyx0r`. This repository-specific ownership
  file is source-only and is not distributed to derived repositories.

### `.github/dependabot.yml`

- Type: `file`
- Status: `required`
- Goal: Requests regular dependency updates for maintained automation and
  quality toolchains.
- Usage: Dependabot checks GitHub Actions at the repository root and the Python
  and npm declarations under `tools/quality/` every week.
- Notes: Defines only the three verified ecosystems, directories, and weekly
  schedules. Cumulative upgrades merge downstream customizations instead of
  replacing them.

### `.github/ISSUE_TEMPLATE/`

- Type: `directory`
- Status: `optional`
- Goal: Stores GitHub issue templates for common repository feedback.
- Usage: GitHub uses these files to prefill new issue forms.
- Notes: Keep templates lightweight and avoid project-specific automation.

### `.github/ISSUE_TEMPLATE/bug_report.md`

- Type: `file`
- Status: `optional`
- Goal: Guides issue authors through a clear bug report.
- Usage: Use for reproducible problems with repository files or templates.
- Notes: Keep reproduction and verification prompts concise.

### `.github/ISSUE_TEMPLATE/documentation.md`

- Type: `file`
- Status: `optional`
- Goal: Guides issue authors through documentation feedback.
- Usage: Use for unclear, missing, outdated, or incorrect documentation.
- Notes: Prefer concrete locations and proposed wording.

### `.github/ISSUE_TEMPLATE/feature_request.md`

- Type: `file`
- Status: `optional`
- Goal: Guides issue authors through proposed repository improvements.
- Usage: Use for reusable starter-kit improvements or template additions.
- Notes: Keep proposals scoped and tied to a concrete need.

### `.github/PULL_REQUEST_TEMPLATE.md`

- Type: `file`
- Status: `required`
- Goal: Provides a lightweight GitHub pull request template.
- Usage: GitHub uses this file to prefill pull request descriptions.
- Notes: Guide review without introducing CI/CD requirements.

### `.github/workflows/`

- Type: `directory`
- Status: `optional`
- Goal: Stores GitHub Actions workflows for repository-level automation.
- Usage: Keep only lightweight, generic workflows in this directory.
- Notes: Avoid adding application build, test, deploy, or release pipelines
  unless a concrete project need is approved.

### `.github/workflows/repository-audit.yml`

- Type: `file`
- Status: `optional`
- Goal: Runs the shared repository audit and publishes one aggregate required
  check on GitHub Actions.
- Usage: Executes on `master` and `v*` pushes, pull requests targeting
  `master`, published releases, and manual dispatch.
- Notes: `quality-linux` runs the exhaustive profile on Ubuntu 24.04 with
  Python 3.11; `compatibility-windows` runs the fast profile, complete Python
  suite, and PSScriptAnalyzer on Windows 2025 with Python 3.14. Both use Node.js
  24.20.0, actions pinned by SHA, locked Python and npm dependencies, and the
  integrity-pinned external-tool installer without a generic cache or Go
  bootstrap. Each dependency family is installed once per isolated job. The
  aggregate requires both environments and uses `Repository audit` for
  automatic events and `Repository audit (manual)` for manual runs. Read-only
  permissions, disabled checkout credential persistence, and the absence of a
  forwarded workflow token keep checked-out audit code unprivileged. Filtering
  branch pushes avoids duplicating pull-request runs. Pull requests, `master`
  updates, and release tags validate the complete commit range since the
  highest reachable stable tag.

### `.github/workflows/guarded-pull-request-merge.yml`

- Type: `file`
- Status: `optional`
- Goal: Revalidates and squash-merges a sealed pull request without executing
  pull request code.
- Usage: Runs only for the typed `guarded-squash-merge` repository dispatch
  sent by `tools/merge-pull-request.py`.
- Notes: Checks out immutable `github.sha` without credentials, validates with
  the read-only workflow token, and mints the existing App token only for a
  second validation and exact merge. The token is limited to `contents: write`
  and `pull-requests: write`; concurrency is deterministic per pull request and
  does not cancel an active run. Cumulative packages distribute this workflow
  with the default `replace` strategy. Its presence does not activate GitHub
  enforcement.

### `.github/workflows/agent-rules-update.yml`

- Type: `file`
- Status: `required`
- Goal: Keeps each initialized repository aligned with the latest canonical
  agent-rule release without a central repository registry.
- Usage: Runs daily, on every published release, or by manual dispatch and
  opens a repository-local pull request when the seven rule files change.
- Notes: Resolves and seals the exact canonical rule transfer before minting
  the target-repository GitHub App token in the publishing job. The publishing
  phase revalidates source, base, transfer hashes, and the target ref before a
  lease-protected push and pull request update. It restricts changes to the
  seven rules and provenance, preserves customized rule files, and runs in the
  starter kit as well as downstream repositories. Set
  `AGENT_RULES_SYNC_ENABLED=false` to suspend scheduled and manual jobs;
  published releases always run the job. Cumulative upgrades replace this
  universal workflow. The guarded release flow requires the repository
  variable `AGENT_RULES_APP_CLIENT_ID` and secret
  `AGENT_RULES_APP_PRIVATE_KEY` before publication, then requires the exact
  automatic release run to succeed.

### `.github/workflows/release-package.yml`

- Type: `file`
- Status: `optional`
- Goal: Builds and uploads two release ZIPs plus their checksum manifest, then
  promotes a validated prerelease.
- Usage: Runs when a release is published or manually through workflow
  dispatch.
- Notes: A read-only `build` job validates the canonical repository and release
  inputs, installs each locked quality environment once, and seals exactly the
  full package, upgrade toolkit, and `SHA256SUMS` as three regular files. The
  dependent `publish` job alone has `contents: write` and the `release`
  environment. It checks out no repository, executes no downloaded payload,
  revalidates the three names and SHA-256 values before exposing its
  write-scoped token, and uploads without overwriting an existing asset.
  Tag-scoped concurrency does not cancel an in-progress run. Automatic runs use
  `latest` and promote a prerelease only after upload; manual runs validate an
  explicit release tag and never promote. Actions are pinned by SHA, checkout
  credentials are not persisted, and both jobs are limited to the exact
  canonical repository. This source-only workflow is excluded from derived
  packages.

### `.github/workflows/release-artifacts.yml`

- Type: `file`
- Status: `required`
- Goal: Validates the three release-identification artifacts for every pushed
  SemVer tag.
- Usage: Runs automatically on tag pushes matching `v*`.
- Notes: Uses Python 3.11 through `actions/setup-python@v7.0.0` pinned by SHA,
  installs the hash-locked validator without interactive input, reads the exact
  tagged Git tree, and blocks the `Release artifacts` check when `VERSION`,
  `SHA256SUMS`, or `manifest.json` is missing, stale, or inconsistent.

### `.githooks/`

- Type: `directory`
- Status: `optional`
- Goal: Stores versioned Git hooks for local repository validation.
- Usage: Enable with `git config core.hooksPath .githooks` when local hooks are
  desired.
- Notes: Each hook is a minimal wrapper around a repository-audit hook profile;
  it does not duplicate checks, install dependencies, or modify files. The
  initializers activate this directory only in repositories they create. The
  guarded release skill forces this path for every commit independently of
  local Git configuration.

### `.githooks/commit-msg`

- Type: `file`
- Status: `optional`
- Goal: Blocks commits when commit messages fail scoped Conventional Commit
  validation.
- Usage: Runs after local hook activation or through a guarded commit that
  explicitly sets `core.hooksPath=.githooks`.
- Notes: Delegates the message-file argument and exit status to the shared
  `hook-commit-msg` profile, which uses `commitlint.config.cjs`.

### `.githooks/pre-commit`

- Type: `file`
- Status: `optional`
- Goal: Blocks commits when applicable staged source, configuration,
  documentation, or release artifacts fail validation.
- Usage: Runs through Git after `core.hooksPath` points to `.githooks`.
- Notes: Delegates to the shared `hook-pre-commit` profile. It checks only the
  staged snapshot with the applicable Markdown, YAML, Python, Bash, JavaScript,
  PowerShell, quality-declaration, spelling-configuration, Commitlint-
  configuration, and release-artifact validators. It reports formatting drift
  but never formats or installs dependencies.

### `.githooks/pre-push`

- Type: `file`
- Status: `required`
- Goal: Runs affected test families against pushed commits and validates every
  pushed SemVer release tag.
- Usage: Runs through Git after `core.hooksPath` points to `.githooks`.
- Notes: Delegates its input and arguments to the shared `hook-pre-push`
  profile. The profile checks out each affected pushed object in a validated
  disposable local clone, assigns that clone the pushed remote URL, runs the
  relevant Python family or the focused hook and commit-message shell suites,
  and validates each pushed `refs/tags/v*` tree with the tracked release
  artifact tool. The exhaustive repository-audit shell suite remains a CI
  responsibility. Historical and non-release refs are not reclassified.

### `.gitignore`

- Type: `file`
- Status: `required`
- Goal: Prevents common local files and generated artifacts from commits.
- Usage: Git excludes matching paths from normal version control.
- Notes: Covers common credential stores, direnv files, runtime storage, and
  generated files while avoiding source files, tests, lock files, or project
  config.

### `.gitmessage`

- Type: `file`
- Status: `required`
- Goal: Provides a reusable commit message template.
- Usage: Copy its structure into the temporary message file that will be
  validated and committed unchanged.
- Notes: Advisory only; it uses scoped Conventional Commit examples and does
  not enforce commit validation.

### `.markdownlint-cli2.yaml`

- Type: `file`
- Status: `required`
- Goal: Defines the portable Markdown lint baseline shared by generated
  repositories.
- Usage: Markdownlint CLI tools load it from the repository root.
- Notes: Keeps the default rules while allowing 120-character lines outside
  code blocks, headings, and tables, and limits duplicate-heading checks to
  sibling sections. Repository-specific proper-name and link-style policies
  remain local extensions.

### `.vscode/`

- Type: `directory`
- Status: `optional`
- Goal: Stores Visual Studio Code workspace recommendations.
- Usage: VS Code reads supported workspace files from this directory.
- Notes: Keep only generic recommendations that fit the starter kit.

### `.vscode/extensions.json`

- Type: `file`
- Status: `optional`
- Goal: Recommends VS Code extensions useful for this starter kit.
- Usage: VS Code suggests these extensions when the repository is opened.
- Notes: Keep recommendations generic and avoid personal preferences.

### `.vscode/settings.json`

- Type: `file`
- Status: `optional`
- Goal: Defines shared VS Code workspace defaults for this starter kit.
- Usage: VS Code applies these settings when the repository is opened.
- Notes: Keep settings aligned with `.editorconfig` and generic editor
  recommendations. Format-on-save settings are human VS Code defaults only;
  they do not permit agents to run formatters or automatic fixers.

### `_agent-rules-source.json`

- Type: `file`
- Status: `required`
- Goal: Records repository, upstream starter-kit, and agent-rules provenance.
- Usage: The autonomous synchronization workflow updates agent-rules data. A
  cumulative starter-kit upgrade updates only `repository` and `starterKit`.
  Release packaging validates the combined provenance.
- Notes: Schema 3 retains repository and starter-kit provenance, records source
  file hashes, and lists customized rule files under `preservedFiles`.

### `_starter-kit-files.json`

- Type: `file`
- Status: `optional`
- Goal: Records the managed files in an enriched release package.
- Usage: Generated inside the ZIP and used by cumulative upgrade tooling.
- Notes: Schema 3 stores raw and canonical SHA-256 digests, content kinds, Git
  modes, and `agent-rules`, `replace`, `merge`, `initialize-only`, or
  `starter-kit-state` strategies. The manifest does not include its own
  digest.

### `starter-kit-manifest.json`

- Type: `file`
- Status: `required`
- Goal: Records the original and current published starter-kit core baselines.
- Usage: Inspect `source` for the release used to derive the repository and
  `current` for the most recent cumulative core upgrade.
- Notes: Generated only in the canonical repository before a release tag and
  distributed to direct clones, forks, and release packages. Its sorted core
  inventory stores raw and canonical SHA-256 digests, content kinds, Git
  modes, and upgrade strategies. Cumulative upgrades preserve `source` and
  replace `current` plus the core inventory.

### `VERSION`

- Type: `file`
- Status: `optional`
- Goal: Stores the exact SemVer number of the release identified by the tag.
- Usage: Read the single UTF-8 line without the tag's leading `v`.
- Notes: Generated in the canonical source repository immediately before each
  release tag. Starter packages omit this source-release state so derived
  repositories generate their own value.

### `SHA256SUMS`

- Type: `file`
- Status: `optional`
- Goal: Records deterministic SHA-256 digests for the tagged release tree.
- Usage: Validate each listed Git blob by its repository-relative path.
- Notes: Includes `VERSION` and excludes gitlinks, untracked or ignored files,
  plus the two self-referential outputs `SHA256SUMS` and `manifest.json`.
  Starter packages omit this source-release state.

### `manifest.json`

- Type: `file`
- Status: `optional`
- Goal: Describes the exact tagged release tree and its explicit release
  metadata.
- Usage: Validate it with `templates/release/manifest.schema.json` and compare
  its inventory with `SHA256SUMS`.
- Notes: Generated from `templates/release/manifest.template.json`. The release
  workflow resolves values from explicit current input, authoritative project
  sources, exact release facts, or a non-conflicting previous manifest. It asks
  the user only for unresolved or contradictory values and never invents a
  default. Starter packages omit this source-release state.

### `AGENTS.md`

- Type: `file`
- Status: `required`
- Goal: Provides repository-level instructions for coding agents.
- Usage: Read before making changes in this repository.
- Notes: Avoid duplicating agent instructions in GitHub-specific files.

### `BRANCH_RULES.md`

- Type: `file`
- Status: `required`
- Goal: Defines universal branch lifecycle and naming rules.
- Usage: Read before the first repository write or any branch operation.

### `CODING_RULES.md`

- Type: `file`
- Status: `required`
- Goal: Provides language-agnostic code-quality rules.
- Usage: Applied through the instruction scope defined in `AGENTS.md`.

### `COMMIT_RULES.md`

- Type: `file`
- Status: `required`
- Goal: Defines repository readiness and commit-message requirements.
- Usage: Read before creating commits.

### `DOCUMENTATION_RULES.md`

- Type: `file`
- Status: `required`
- Goal: Defines documentation and README quality requirements.
- Usage: Read before changing project documentation.

### `LANGUAGE_RULES.md`

- Type: `file`
- Status: `required`
- Goal: Defines language-, dialect-, and framework-specific coding rules.
- Usage: Apply only the sections relevant to files being changed.

### `RELEASE_RULES.md`

- Type: `file`
- Status: `required`
- Goal: Defines SemVer, tag, and release-readiness requirements.
- Usage: Read before creating Git tags or releases.

### `CHANGELOG.md`

- Type: `file`
- Status: `required`
- Goal: Tracks notable changes to this repository.
- Usage: Update with notable repository changes before release commits.
- Notes: Keep release entries aligned with changes since the previous tag.
  Record breaking skill behavior explicitly. Future-project placeholders
  belong in `templates/CHANGELOG.md`.

### `CODE_OF_CONDUCT.md`

- Type: `file`
- Status: `optional`
- Goal: Defines expected behavior for participation in this repository.
- Usage: Read before contributing or participating in project discussions.
- Notes: Keep GitHub-specific duplicates out of `.github/` and document a
  enabled private path for sensitive conduct reports.

### `commitlint.config.cjs`

- Type: `file`
- Status: `required`
- Goal: Defines the default commitlint rules for Conventional Commits.
- Usage: Run `commitlint` from the repository root or from a commit-msg hook.
- Notes: Keeps parser options and strict commit rules explicit to reject
  loosely formatted or unscoped commit messages.

### `CONTRIBUTING.md`

- Type: `file`
- Status: `required`
- Goal: Explains how contributors should propose and verify changes.
- Usage: Read before contributing to the starter kit.
- Notes: Documents local Git hook activation and the required exact-file
  Commitlint sequence for guarded commits. Future-project placeholders belong
  in `templates/CONTRIBUTING.md`.

### `LICENSE`

- Type: `file`
- Status: `required`
- Goal: Defines the legal terms for using and redistributing this repository.
- Usage: Reference this file from README files.
- Notes: This repository uses the MIT License with `asphyx` as holder.

### `README.md`

- Type: `file`
- Status: `required`
- Goal: Introduces the repository purpose, features, setup, and license.
- Usage: Read first when evaluating or reusing the starter kit.
- Notes: Summarizes audit prerequisites, local Git hook activation,
  release package behavior, the canonical skill invocation contract, generic
  ignore coverage, and the maintainer migration record. Do not leave
  future-project placeholders in the root README.

### `SECURITY.md`

- Type: `file`
- Status: `required`
- Goal: Explains how to report security issues for this repository.
- Usage: Use for suspected vulnerabilities in the starter kit itself.
- Notes: Requires GitHub private vulnerability reporting to remain enabled
  instead of inventing maintainer email addresses or response timelines.

### `SUPPORT.md`

- Type: `file`
- Status: `optional`
- Goal: Explains where users can get help for this repository.
- Usage: Read before opening support questions or asking for help.
- Notes: Keep support scope distinct from security reporting.

### `tools/`

- Type: `directory`
- Status: `optional`
- Goal: Stores small repository management and maintenance tools.
- Usage: Keep tools generic and tied to documented repository workflows.
- Notes: Avoid project-specific build, test, or deploy automation here.

### `tools/backup-target-directory.py`

- Type: `file`
- Status: `optional`
- Goal: Creates a staged ZIP backup of a directory tree with Git provenance in
  the archive name.
- Usage: Run with an existing source and external target directory; use
  `--dry-run` before creating the archive.
- Notes: Uses only the Python standard library, includes `.git` and all files
  present during staging, rejects symbolic links, and accepts an optional
  staging parent. The archive name contains the captured 12-character `HEAD`
  and only a SemVer tag that points to that commit. The copy is not
  transactional and does not preserve every NTFS metadata class or add a
  cryptographic manifest.

### `tools/build-release-package.ps1`

- Type: `file`
- Status: `optional`
- Goal: Generates a starter-kit release package enriched with agent rules.
- Usage: Run from the release package workflow or manually with PowerShell.
- Notes: Copies core paths from the tracked release manifest for SemVer
  packages, resolves `latest` through the public GitHub release API by default,
  and verifies tracked rule hashes and
  provenance against that release. It writes repository provenance plus
  per-file raw and canonical SHA-256 hashes, content kinds, modes, and upgrade
  strategies for every distributed file, including dotfiles, validates package
  file names before writing ZIP files, keeps SemVer validation aligned with CI
  smoke cases, and verifies exhaustive manifest coverage and repository-owned
  documentation strategies in the archive. Agent-rule paths use an independent
  strategy so cumulative starter upgrades cannot overwrite them, while the
  tracked core manifest uses `starter-kit-state`. A previously tracked managed
  file manifest is excluded before its replacement is generated. Helper
  functions use ScriptAnalyzer-compatible names and explicit parameters. The
  SemVer path requires the selected tag to resolve to `HEAD` and rejects a
  packaged path whose Git-filtered content differs from `HEAD`. The
  command rejects every repository slug or `origin` except the canonical
  `asphyx0r/git-starter-kit` repository. It validates a sibling temporary ZIP
  before atomic same-volume publication, preserving an existing destination
  on build, validation, or replacement failure. The tool is excluded from
  packages distributed to derived repositories.

### `tools/README.md`

- Type: `file`
- Status: `optional`
- Goal: Documents the repository tools with man-page-style operational
  reference sections.
- Usage: Read before running scripts in `tools/` to understand their purpose,
  command-line interfaces, examples, exit status, and best practices.
- Notes: Keep entries aligned with current tool behavior whenever scripts are
  changed. Documents execution-policy troubleshooting for downloaded
  `git-init.ps1` copies that PowerShell blocks before launch, and records the
  backup and cumulative upgrade tools' provenance, consistency, and
  restoration limits. Cumulative upgrades treat this repository-specific
  operator reference as initialization-only.

### `tools/quality/`

- Type: `directory`
- Status: `required`
- Goal: Centralizes reproducible declarations and settings for repository
  quality checks.
- Usage: Install the locked Python and npm environments, then use the shared
  audit and hook profiles instead of invoking divergent tool versions.
- Notes: The component contains exactly ten maintained files. Cumulative
  upgrades replace it as one repository-owned quality baseline.

### `tools/quality/check-versions.py`

- Type: `file`
- Status: `required`
- Goal: Detects drift between the quality registry, dependency locks, and
  policy settings.
- Usage: Run without options to validate declarations or with `--runtime` to
  validate installed tool versions as well.
- Notes: Uses bounded runtime probes and fails on missing, extra, malformed, or
  inconsistent direct declarations.

### `tools/quality/install-external-tools.py`

- Type: `file`
- Status: `required`
- Goal: Installs non-package-manager quality tools from integrity-pinned
  artifacts.
- Usage: Select the declared platform and a new installation root strictly
  below `RUNNER_TEMP`; optionally select individual supported tools.
- Notes: Requires HTTPS, verifies SHA-256 before extraction, rejects unsafe
  archive layouts and links, probes staged tools, and publishes the completed
  installation only after every selected tool passes.

### `tools/quality/package-lock.json`

- Type: `file`
- Status: `required`
- Goal: Locks the complete npm dependency graph used by repository quality
  checks.
- Usage: Install it with `npm ci --ignore-scripts --prefix tools/quality`.
- Notes: Records exact package versions and registry integrity values; do not
  edit it independently from `package.json`.

### `tools/quality/package.json`

- Type: `file`
- Status: `required`
- Goal: Declares the direct Node.js quality tools owned by the repository.
- Usage: Treat it as a private, non-publishable npm project and install through
  its lockfile.
- Notes: Contains only exact Commitlint and Markdownlint CLI development
  dependencies.

### `tools/quality/PSScriptAnalyzerSettings.psd1`

- Type: `file`
- Status: `required`
- Goal: Provides the shared PSScriptAnalyzer settings entry point.
- Usage: Pass it to `Invoke-ScriptAnalyzer` from audit and hook profiles.
- Notes: The empty settings map intentionally retains the analyzer's default
  rules without repository-wide exclusions or suppressions.

### `tools/quality/pyproject.toml`

- Type: `file`
- Status: `required`
- Goal: Defines scoped Ruff, Mypy, and branch-coverage policy for maintained
  Python code.
- Usage: Pass it explicitly to the corresponding quality commands.
- Notes: Targets Python 3.11, lists the maintained production modules for Mypy,
  and requires at least 85 percent branch coverage across `tools/`.

### `tools/quality/requirements.in`

- Type: `file`
- Status: `required`
- Goal: Declares the exact direct Python dependencies used by quality and
  manifest validation.
- Usage: Change this input first when deliberately updating a direct Python
  quality dependency, then regenerate the lock.
- Notes: Contains only exact direct requirements; transitive integrity data
  belongs in `requirements.lock`.

### `tools/quality/requirements.lock`

- Type: `file`
- Status: `required`
- Goal: Locks the complete Python quality dependency graph with artifact
  integrity.
- Usage: Install with pip using both `--require-hashes` and
  `--requirement tools/quality/requirements.lock`.
- Notes: Generated with Python 3.11 from `requirements.in`; every requirement
  block carries accepted SHA-256 hashes.

### `tools/quality/versions.json`

- Type: `file`
- Status: `required`
- Goal: Acts as the single registry for direct quality-tool versions and
  enforced quality policy values.
- Usage: Keep Python and npm declarations aligned with their lockfiles and use
  the external records as installer inputs.
- Notes: Schema 2 records supported platforms, official HTTPS artifact URLs,
  SHA-256 digests, installation contracts, and version probes for Actionlint,
  Shfmt, PSScriptAnalyzer, and ShellCheck.

### `tools/quality/yamllint.yaml`

- Type: `file`
- Status: `required`
- Goal: Defines the shared YAML syntax and style baseline.
- Usage: Run Yamllint with this configuration from audit and hook profiles.
- Notes: Extends the default rules while disabling only document-start and
  line-length enforcement.

### `tools/repository-audit.sh`

- Type: `file`
- Status: `optional`
- Goal: Dispatches shared local, hook, and CI repository audit profiles.
- Usage: Run `bash tools/repository-audit.sh` with `full`, `readonly`,
  `markdown`, `spelling`, `static`, `fast`, `powershell-static`, or a supported
  hook profile.
- Notes: This compatibility entry point validates and loads the six audit
  profile modules under `tools/repository-audit/`, then delegates without duplicating
  their checks. `all` remains an alias for `full`. Cumulative upgrades treat
  the dispatcher and its modules as one replace-managed runtime; local changes
  cause a blocking conflict instead of being overwritten.

### `tools/repository-audit/`

- Type: `directory`
- Status: `optional`
- Goal: Separates repository audit policy into focused Bash modules.
- Usage: Load the six audit profile modules through `tools/repository-audit.sh`;
  the agent-rules workflow invokes the autonomous transfer module directly.
- Notes: Contains exactly seven modules for shared infrastructure, contracts,
  hooks, profiles, security, smoke tests, and sealed agent-rule transfer.
  Cumulative upgrades add or update the complete runtime atomically and block
  rather than overwrite downstream changes.

### `tools/repository-audit/agent-rules-transfer.sh`

- Type: `file`
- Status: `optional`
- Goal: Implements the bounded transfer boundary used by autonomous agent-rule
  synchronization.
- Usage: The workflow invokes its `resolve`, `seal`, `prepare-publish`, and
  `publish` phases with their explicit environment contracts.
- Notes: Preserves canonical tag and commit identity, seals only the allowed
  rule and provenance files, revalidates source and target refs, and uses
  lease-protected publication before creating or updating one pull request.

### `tools/repository-audit/common.sh`

- Type: `file`
- Status: `optional`
- Goal: Provides shared repository, command, temporary-path, Git-range, and
  line-ending helpers.
- Usage: The dispatcher loads it before modules that consume its globals and
  helper functions.
- Notes: Keeps cleanup bounded to audit-owned temporary directories and
  resolves push, pull-request, release, and local audit ranges explicitly.

### `tools/repository-audit/contracts.sh`

- Type: `file`
- Status: `optional`
- Goal: Enforces repository-owned cross-file and workflow contracts.
- Usage: Static and read-only profiles call its checks for SemVer, initializer,
  release, guarded merge, workflow, skill, and documentation consistency.
- Notes: Contract failures use focused diagnostics and are exercised with
  valid fixtures plus single-cause mutations.

### `tools/repository-audit/hooks.sh`

- Type: `file`
- Status: `optional`
- Goal: Owns the shared `pre-commit`, `commit-msg`, and `pre-push` behavior.
- Usage: Invoke only through the matching dispatcher profiles and versioned
  hook wrappers.
- Notes: Validates staged snapshots without modifying them, resolves locked
  local tools, runs affected pushed-object tests in isolated local clones, and
  retains release-tag artifact validation.

### `tools/repository-audit/profiles.sh`

- Type: `file`
- Status: `optional`
- Goal: Composes named audit profiles from reusable checks.
- Usage: The dispatcher selects the requested full, read-only, focused, fast,
  platform-specific, or hook profile.
- Notes: The full/static profile owns exhaustive quality, guarded-workflow
  contract, coverage, behavior, smoke, and commit-range validation; focused
  profiles avoid repeating unrelated work.

### `tools/repository-audit/security.sh`

- Type: `file`
- Status: `optional`
- Goal: Validates secret-scanner configuration and representative detection
  behavior.
- Usage: Full audits validate the configuration contract; read-only audits also
  exercise scanner fixtures.
- Notes: Requires byte-identical Betterleaks and Gitleaks policy, inherited
  default rules, the repository's strict additions, and verified placeholder
  exclusions.

### `tools/repository-audit/smoke.sh`

- Type: `file`
- Status: `optional`
- Goal: Exercises end-to-end initializer, hook, release, package, and upgrade
  behavior in disposable fixtures.
- Usage: The full/static profile invokes it after locked dependencies are
  available.
- Notes: Verifies distribution strategies and package contents against the
  maintained manifests while keeping mutations inside audit-owned temporary
  directories.

### `tools/release-artifacts.py`

- Type: `file`
- Status: `required`
- Goal: Prepares and validates `VERSION`, `SHA256SUMS`, and `manifest.json`
  against an exact Git tree.
- Usage: Run `prepare` with a SemVer tag, one UTC release timestamp, and an
  explicit metadata JSON file outside the repository; run `check` against the
  index or a tagged tree.
- Notes: Inventories Git blobs rather than working-tree files, ignores
  untracked and ignored content, validates Draft 2020-12 JSON Schema formats,
  and never derives unknown business metadata.

### `tools/release-artifacts-requirements.txt`

- Type: `file`
- Status: `required`
- Goal: Selects the shared hash-locked Python environment required for release
  manifest validation.
- Usage: Install it with pip using `--require-hashes` before running the release
  artifact tool or its tests.
- Notes: Delegates to `tools/quality/requirements.lock`, which includes the
  exact `jsonschema[format]` dependency and all transitive artifact hashes.

### `tools/merge-pull-request.py`

- Type: `file`
- Status: `optional`
- Goal: Seals, dispatches, revalidates, and confirms exact squash merges.
- Usage: Use `request` with a positive pull request number and exact message
  file; the repository-owned workflow uses `execute --event-file`.
- Notes: Validates Commitlint before the first `gh` call, requires an open
  non-draft default-branch pull request and every effective required check,
  rejects repository auto-merge and applicable merge queues, supports forks
  without running their code, never retries a dispatch, and returns `3` when a
  started dispatch or merge has an indeterminate result. Cumulative packages
  use the default `replace` strategy.

### `tools/verify-repository-audit-runs.py`

- Type: `file`
- Status: `optional`
- Goal: Waits for the exact GitHub Actions push runs required by a guarded
  release and rejects every missing, ambiguous, or unsuccessful run.
- Usage: Supply the repository, resolved workflow ID, exact SHA, inclusive UTC
  lower bound, and one `--ref` for every expected branch or tag.
- Notes: Uses authenticated read-only `gh api` queries, ignores manual and
  unrelated runs, bounds each subprocess by 30 seconds and the remaining
  global timeout, exposes a side-effect-free `--dry-run`, and is included in
  packages for derived repositories.

### `tools/starter-kit-upgrade.py`

- Type: `file`
- Status: `optional`
- Goal: Preserves the executable and import-compatible interface for cumulative
  starter-kit upgrades.
- Usage: Build from exact base and new full packages, inspect with `plan`, and
  use `apply` only with an external backup directory.
- Notes: Re-exports the supported public surface and delegates each
  responsibility to `tools/starter_kit_upgrade/` while retaining patchable
  compatibility adapters. The facade and package sources are excluded from the
  full package and supplied together inside the upgrade toolkit.

### `tools/starter_kit_upgrade/`

- Type: `directory`
- Status: `optional`
- Goal: Implements cumulative starter-kit upgrades as responsibility-focused
  Python modules.
- Usage: Execute the public facade rather than individual package modules.
- Notes: Contains exactly six source-only modules with dependencies flowing
  from shared primitives through archive, planning, application, and CLI
  layers. The complete package accompanies the facade in upgrade toolkits.

### `tools/starter_kit_upgrade/__init__.py`

- Type: `file`
- Status: `optional`
- Goal: Defines the minimal public package entry point.
- Usage: Import `main`, `VERSION`, or `UpgradeError` when package-level access
  is required.
- Notes: Keeps the package surface narrow; compatibility exports remain owned
  by `tools/starter-kit-upgrade.py`.

### `tools/starter_kit_upgrade/application.py`

- Type: `file`
- Status: `optional`
- Goal: Applies validated upgrade plans with rollback protection.
- Usage: The CLI calls it only after archive and target planning succeeds and
  an external backup directory is supplied.
- Notes: Captures file snapshots, writes validated payloads, creates the
  rollback archive, and restores changed paths after a failed application.

### `tools/starter_kit_upgrade/archive.py`

- Type: `file`
- Status: `optional`
- Goal: Reads, validates, and builds full upgrade packages and portable
  toolkits.
- Usage: The CLI uses it for `build` and `toolkit` operations before target
  planning or application.
- Notes: Enforces safe archive paths, exact starter provenance, hashes,
  strategy manifests, and the complete source-only module inventory.

### `tools/starter_kit_upgrade/cli.py`

- Type: `file`
- Status: `optional`
- Goal: Defines command-line parsing and orchestration for cumulative upgrades.
- Usage: The facade delegates `build`, `toolkit`, `plan`, and `apply` commands
  to this module.
- Notes: Keeps command routing separate from archive, planning, and filesystem
  mutation logic.

### `tools/starter_kit_upgrade/common.py`

- Type: `file`
- Status: `optional`
- Goal: Provides shared constants, validated data primitives, hashing, JSON,
  and run-journal behavior.
- Usage: Other upgrade modules depend on these primitives instead of
  duplicating provenance or content rules.
- Notes: Owns the upgrade error type, path validation, raw and canonical
  SHA-256 helpers, and structured operation logging.

### `tools/starter_kit_upgrade/planning.py`

- Type: `file`
- Status: `optional`
- Goal: Evaluates a target repository and produces a guarded upgrade plan.
- Usage: `plan` and `apply` use it to validate adoption, classify file actions,
  and report operational compliance.
- Notes: Handles three-way text merges, local ownership, conflicts, starter
  manifest evolution, and exact-release alignment without writing the target.

### `tools/starter-kit-manifest.py`

- Type: `file`
- Status: `optional`
- Goal: Prepares and validates the tracked starter-kit core manifest.
- Usage: Run `prepare` with an exact selected release tag after all other
  release content is committed, then run `check` before tagging.
- Notes: Uses only the Python standard library, hashes Git blobs, requires the
  canonical HTTPS `origin` for preparation, supports a real dry-run, and
  validates existing manifests without mutation. The source tool is excluded
  from distributed packages; its generated root manifest is included.

### `tools/git-init.ps1`

- Type: `file`
- Status: `optional`
- Goal: Initializes a target Git repository from PowerShell after explicit
  user confirmation.
- Usage: Run with `--path <directory>` and optional `--tag <tag>`,
  `--remote <url>`, and `--verbose`. Run without arguments to show help.
- Notes: Requires Bash 4 or newer, validates SemVer tags covered by CI smoke
  cases, requires
  existing non-empty target directories,
  previews committable files from Git porcelain status without creating target
  Git metadata, explains invalid preexisting `.git` metadata, warns on risky
  credential, direnv, and artifact paths, refuses
  existing target commits, writes prompts without polluting confirmation
  return values, writes verbose traces without polluting Git command return
  values, reads confirmation answers from standard input for
  deterministic CI smoke tests, warns on runtime storage paths, creates the
  first Conventional Commit from one temporary UTF-8 message file validated by
  Commitlint and the forced repository hooks, verifies the recorded message,
  tags it, and only pushes when `--remote` is provided.

### `tools/git-init.sh`

- Type: `file`
- Status: `optional`
- Goal: Initializes a target Git repository from Bash after explicit user
  confirmation.
- Usage: Run with `--path <directory>` and optional `--tag <tag>`,
  `--remote <url>`, and `--verbose`. Run without arguments to show help.
- Notes: Validates SemVer tags covered by CI smoke cases, requires
  existing non-empty target directories,
  previews committable files from Git porcelain status without creating target
  Git metadata, explains invalid preexisting `.git` metadata, warns on risky
  credential, direnv, artifact, and runtime storage paths, refuses existing
  target commits, writes verbose Git traces to standard error so they remain
  visible when command output is suppressed, creates the first Conventional
  Commit from one temporary message file validated by Commitlint and the
  forced repository hooks, verifies the recorded message, tags it, and only
  pushes when `--remote` is provided.

### `tests/`

- Type: `directory`
- Status: `optional`
- Goal: Stores focused automated tests for reusable repository tools.
- Usage: Run the Python suite directly or through the repository audit.
- Notes: Tests must isolate filesystem and Git mutations in temporary
  directories and must not leave repository artifacts.

### `tests/test_agent_rules_transfer.sh`

- Type: `file`
- Status: `required`
- Goal: Verifies the sealed, privilege-separated agent-rule transfer contract.
- Usage: Run with Bash from a checkout that provides Git and the test's local
  command fixtures.
- Notes: Covers canonical ref resolution, path and checksum sealing, preserved
  content, source and target races, lease-protected publication, pull request
  handling, signal cleanup, and exact command boundaries. It is distributed by
  replacement with the universal synchronization workflow.

### `tests/test_backup_target_directory.py`

- Type: `file`
- Status: `optional`
- Goal: Verifies the backup tool's CLI, Git provenance, safety checks, staging
  cleanup, archive contents, and readable ZIP output.
- Usage: Run
  `python -B -m unittest discover -s tests -p "test_backup_target_directory.py"`.
- Notes: Uses only `unittest` and the Python standard library. Git-dependent
  and symbolic-link cases skip only when the required platform capability is
  unavailable.

### `tests/test_build_release_package.py`

- Type: `file`
- Status: `optional`
- Goal: Verifies release-package distribution policy and atomic ZIP
  publication.
- Usage: Run with Python where PowerShell 7 is available. On Windows, keep
  Windows PowerShell 5.1 available for the dedicated compatibility case.
- Notes: Builds real packages from alternate Git indexes, checks source-only,
  merge, initialize-only, and replace perimeters, and proves that build,
  validation, or replacement failures preserve an existing destination. This
  canonical-repository test is source-only.

### `tests/test_commit_message_validation.sh`

- Type: `file`
- Status: `optional`
- Goal: Reproduces overlong commit bodies and verifies forced hooks, exact
  message-file commits, preflight ranges, tag ranges, and first-release ranges.
- Usage: Run `bash tests/test_commit_message_validation.sh` with Git, Bash, and
  Node.js after installing the locked Node quality dependencies.
- Notes: Reproduces PR #17 with the valid branch message and invalid squash
  message, requires the latter to fail on `body-max-line-length` before any
  `gh` call, uses only temporary Git repositories, and is included in packages
  for derived repositories.

### `tests/test_merge_pull_request.py`

- Type: `file`
- Status: `optional`
- Goal: Verifies exact message, payload, pull request, dispatch, workflow, and
  post-merge behavior for the guarded squash merge CLI.
- Usage: Run
  `python -B -m unittest discover -s tests -p "test_merge_pull_request.py"`.
- Notes: Covers Unicode and message boundaries, malformed event values,
  confirmation and dry-run behavior, forks, stale heads, required checks,
  merge-queue and auto-merge rejection, bounded timeout status `3`, exact merge
  arguments, cleanup, and post-merge recovery or mismatch. GitHub operations
  are replaced by deterministic in-memory boundaries.

### `tests/test_quality_hooks.sh`

- Type: `file`
- Status: `optional`
- Goal: Verifies hook wrappers, dispatcher integration, activation, and shared
  hook helper behavior.
- Usage: Run with Bash from the repository root.
- Notes: Exercises argument, input, output, and failure propagation; missing
  dependency guidance; affected-path classification; and initializer-owned
  hook activation in disposable repositories.

### `tests/test_quality_pre_commit.sh`

- Type: `file`
- Status: `optional`
- Goal: Verifies staged-only pre-commit selection and validation.
- Usage: Run with Bash after installing the locked quality dependencies.
- Notes: Exercises applicable Markdown, YAML, Python, Bash, JavaScript,
  PowerShell, configuration, and release-artifact paths while proving that
  unstaged working-tree content does not replace the staged snapshot.

### `tests/test_quality_pre_push.sh`

- Type: `file`
- Status: `optional`
- Goal: Verifies affected-test and release validation against pushed object
  identities.
- Usage: Run with Bash in an environment that provides the locked test
  dependencies.
- Notes: Uses disposable local repositories to cover new and updated refs,
  multiple object identities, detached pushed-object execution, tag checks,
  failure propagation, and temporary-path cleanup.

### `tests/test_quality_toolchain.py`

- Type: `file`
- Status: `optional`
- Goal: Verifies the centralized quality registry, integrity locks, policies,
  runtime probes, and external-tool installer.
- Usage: Run with Python's `unittest`; network behavior is replaced by
  deterministic in-memory responses and local artifacts.
- Notes: Covers declaration drift, exact direct dependencies, complete hashes,
  coverage policy, HTTPS redirects, archive safety, symlink rejection,
  staged probes, atomic publication, and bounded diagnostics.

### `tests/test_release_artifacts.py`

- Type: `file`
- Status: `required`
- Goal: Verifies deterministic artifact generation, explicit metadata gates,
  SemVer handling, schema validation, index checks, and tag checks.
- Usage: Install `tools/release-artifacts-requirements.txt`, then run
  `python -B -m unittest tests.test_release_artifacts`.
- Notes: Uses temporary Git repositories and leaves the source repository
  unchanged.

### `tests/test_repository_audit.sh`

- Type: `file`
- Status: `optional`
- Goal: Verifies dispatcher loading, profile routing, and repository-owned
  audit contracts.
- Usage: Run with Bash from the repository root.
- Notes: Exercises missing, malformed, and failing modules without changing a
  sourcing caller's shell state, plus guarded-merge, workflow, and distribution
  mutations with exact failure diagnostics.

### `tests/test_verify_repository_audit_runs.py`

- Type: `file`
- Status: `optional`
- Goal: Verifies exact workflow-run selection and proves that one failed
  required ref blocks a release even when another run for the SHA is green.
- Usage: Run
  `python -B -m unittest discover -s tests -p "test_verify_repository_audit_runs.py"`.
- Notes: Uses in-memory GitHub Actions fixtures, checks the CLI option order,
  version, and dry-run contract, and performs no GitHub queries.

### `tests/test_starter_kit_upgrade.py`

- Type: `file`
- Status: `optional`
- Goal: Verifies facade compatibility, modular cumulative package construction,
  three-state planning, provenance gates, conflict handling, rollback, and
  archive path safety.
- Usage: Run
  `python -B -m unittest discover -s tests -p "test_starter_kit_upgrade.py"`.
- Notes: Uses temporary Git repositories and ZIP files without changing the
  working repository. It verifies the exact six-module topology, public
  re-exports, isolated imports, and toolkit execution. This starter-only test
  is excluded from the full package.

### `tests/test_starter_kit_manifest.py`

- Type: `file`
- Status: `optional`
- Goal: Verifies manifest generation, validation, identity gates, distribution
  perimeters, dry-run, idempotence, and release-tag inventory checks.
- Usage: Run
  `python -B -m unittest discover -s tests -p "test_starter_kit_manifest.py"`.
- Notes: Uses temporary Git repositories, only the Python standard library,
  and no network access. It checks the exact governance files and source-only,
  merge, initialize-only, and replace policies. This starter-only test is
  excluded from the full package.

### `docs/`

- Type: `directory`
- Status: `required`
- Goal: Stores repository documentation.
- Usage: Keep maintained documentation that supports the starter kit here.
- Notes: Avoid duplicating root-level community files.

### `docs/SKILLS.md`

- Type: `file`
- Status: `optional`
- Goal: Documents repository-scoped Codex skills.
- Usage: Consult to discover available skills, supported invocations,
  capabilities, dependencies, and limitations.
- Notes: This file is documentation-only. Each skill's `SKILL.md` remains the
  authoritative source for its behavior and instructions. Cumulative upgrades
  preserve this repository-specific inventory as initialization-only.

### `docs/guarded-pull-request-merges.md`

- Type: `file`
- Status: `optional`
- Goal: Defines the operator procedure and security boundaries for exact
  guarded squash merges.
- Usage: Read before requesting a guarded merge or separately activating its
  GitHub rulesets and repository settings.
- Notes: Documents the message contract, status `3` recovery, privilege split,
  fork safety, distinct rulesets, merge-method settings, and disposable pull
  request proof. Cumulative packages use the default `replace` strategy.

### `docs/repository-files.md`

- Type: `file`
- Status: `required`
- Goal: Maintains the inventory of repository files and directories.
- Usage: Update whenever repository files or directories are added or changed.
- Notes: This file is the source of truth for repository file ownership.
  Cumulative upgrades preserve it as initialization-only.

### `docs/release-package.md`

- Type: `file`
- Status: `optional`
- Goal: Explains automatic and manual enriched release package generation.
- Usage: Read before publishing or manually regenerating release package
  assets.
- Notes: Covers the rule-freshness gate, prerelease promotion, the mandatory
  automatic CI gate, generated ZIP contents, local testing, and
  troubleshooting. Cumulative upgrades preserve this repository-specific
  guide as initialization-only. This operator guide is excluded from the full
  package.

### `docs/upgrade-toolkit.md`

- Type: `file`
- Status: `optional`
- Goal: Explains how to build, review, and apply a cumulative starter-kit
  upgrade.
- Usage: Follow the documented `build`, `plan`, and `apply` sequence when
  aligning a repository derived from an earlier starter-kit release.
- Notes: This source-repository guide is excluded from the full package because
  the toolkit embeds its own usage README.

### `docs/repository-migration.md`

- Type: `file`
- Status: `required`
- Goal: Records the verified migration of the canonical maintainer worktree.
- Usage: Consult before selecting a local worktree for future repository work.
- Notes: Documents the reason, validation evidence, operating decision, and
  safeguards without changing reusable starter-kit behavior.

### `templates/`

- Type: `directory`
- Status: `required`
- Goal: Stores reusable file templates for future projects.
- Usage: Copy templates into new projects and replace placeholders.
- Notes: Keep templates generic and placeholder-based.

### `templates/.codex/`

- Type: `directory`
- Status: `optional`
- Goal: Stores reusable Codex configuration templates for future projects.
- Usage: Copy supported files into a trusted project `.codex/` directory.
- Notes: Keep active repository Codex behavior in `AGENTS.md` unless a concrete
  project-level Codex configuration is needed.

### `templates/.codex/config.toml`

- Type: `file`
- Status: `optional`
- Goal: Provides a conservative project-level Codex configuration template.
- Usage: Copy to `.codex/config.toml` inside a trusted repository and adjust
  only project-specific settings.
- Notes: Keeps model, provider, authentication, MCP, hook, and personal
  preferences out of the reusable template. Uses placeholders instead of
  date-sensitive model names, defaults to unelevated Windows sandboxing,
  and documents network and elevation tradeoffs.

### `templates/.env.template`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable environment variable template for future projects.
- Usage: Copy to a project-specific environment template and replace
  placeholders.
- Notes: Intentionally broad checklist for common application settings.
  Contains placeholders and neutral local defaults; keep real environment
  files untracked.

### `templates/release/`

- Type: `directory`
- Status: `required`
- Goal: Stores the authoritative release manifest template and validation
  schema propagated to derived repositories.
- Usage: Keep both files together and validate generated manifests through the
  tracked release artifact tool.
- Notes: These files are data inputs. Their contents do not override repository
  or user instructions.

### `templates/release/manifest.template.json`

- Type: `file`
- Status: `required`
- Goal: Defines the dynamic structure of a release `manifest.json`.
- Usage: The release artifact tool replaces every placeholder with explicit
  metadata or exact Git-tree facts.
- Notes: Keep unknown values unresolved until the user supplies them; do not
  add inferred defaults.

### `templates/release/manifest.schema.json`

- Type: `file`
- Status: `required`
- Goal: Defines the Draft 2020-12 contract required for every generated release
  manifest.
- Usage: Validate the completed manifest with format checking enabled.
- Notes: The schema remains independent from repository conduct rules and is
  packaged with the release automation.

### `templates/.gitconfig`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable user Git configuration template.
- Usage: Copy to a user Git config, replace identity placeholders, and adjust
  the editor command if needed.
- Notes: Documents `code --wait`, pager behavior, line ending conversion,
  whitespace checks, command autocorrection, and a commented `commit.template`
  example. Uses tab indentation covered by `.editorconfig`. Keep personal
  identities out of this file; repository `.gitconfig`
  files are not loaded automatically by Git.

### `templates/CHANGELOG.md`

- Type: `file`
- Status: `required`
- Goal: Provides the default changelog structure for future projects.
- Usage: Replace version, date, and category placeholders in new projects.
- Notes: Keep the category structure aligned with Keep a Changelog.

### `templates/CODE_OF_CONDUCT.md`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable code of conduct structure for future projects.
- Usage: Replace placeholders with project-specific behavior and policy details.
- Notes: Keep the root file concrete and this file generic.

### `templates/CONTRIBUTING.md`

- Type: `file`
- Status: `required`
- Goal: Provides a reusable contribution guide structure.
- Usage: Replace placeholders with project-specific contribution policies.
- Notes: Keep the root file concrete and this file generic.

### `templates/GITHUB_RELEASE_NOTES.md`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable GitHub release notes structure.
- Usage: Copy into a GitHub release draft and replace placeholders.
- Notes: Keep release notes concise and aligned with the project changelog.

### `templates/README.md`

- Type: `file`
- Status: `required`
- Goal: Provides the default README structure for future projects.
- Usage: Replace placeholders with project-specific content.
- Notes: Keep the root README concrete and this file generic.

### `templates/README_TOOLS.md`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable README structure for directories that contain
  scripts, command-line tools, or maintenance utilities.
- Usage: Copy to a tool directory as `README.md`, then replace placeholders
  with exact commands, options, inputs, outputs, side effects, and exit codes.
- Notes: Use for collections such as `tools/`; keep per-tool entries aligned
  with the current implementation and avoid inventing undocumented behavior.

### `templates/SECURITY.md`

- Type: `file`
- Status: `required`
- Goal: Provides a reusable security policy structure.
- Usage: Replace placeholders with project-specific security policy details.
- Notes: Keep the root file concrete and this file generic.

### `templates/SKILLS.md`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable documentation-only inventory structure for Codex
  skills.
- Usage: Copy to a repository documentation directory as `SKILLS.md`, then
  replace placeholders from existing skill source files.
- Notes: Keep the generated inventory in English, source-based, and limited to
  capabilities and paths that actually exist. Each `SKILL.md` file remains
  authoritative.

### `templates/SUPPORT.md`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable support policy structure for future projects.
- Usage: Replace placeholders with project-specific support channels.
- Notes: Keep the root file concrete and this file generic.
