# Changelog

All notable changes to this repository will be documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this repository
uses [Semantic Versioning](https://semver.org/).

## v1.8.0 - 2026-07-17

### Added in v1.8.0

- Optional non-mutating repository audit profile using installed tools without
  package installation, network access, temporary files, or mutating smoke
  tests.
- Windows mitigation guidance for the external Codex Git process issue.
- Annotated-tag policy for new releases, with documented lightweight
  historical exceptions.

### Changed in v1.8.0

- Preserved the full repository audit as the default behavior and added
  `full` as an explicit alias.
- Made new release tag creation consistently use annotated tags.

### Fixed in v1.8.0

- Corrected the Git commit, push, and tag skill agent YAML metadata.
- Guarded full-audit temporary cleanup against unexpected paths.
- Preserved read-only PowerShell parsing when Windows PowerShell is called
  from WSL.

## v1.7.3 - 2026-07-13

### Added in v1.7.3

- Reusable skill documentation template for source-based repository skill
  inventories.

## v1.7.2 - 2026-07-08

### Added in v1.7.2

- Reusable tool-directory README template for documenting script and utility
  collections.
- Added PowerShell execution-policy troubleshooting for downloaded
  `git-init.ps1` release copies.

## v1.7.1 - 2026-07-08

### Added in v1.7.1

- Added man-page-style reference documentation for every script in `tools/`.

### Changed in v1.7.1

- Renamed repository management paths from `scripts/` to `tools/`.

### Fixed in v1.7.1

- Made the Git initializers explain unreadable preexisting `.git` metadata
  before previewing committable files.

## v1.7.0 - 2026-07-07

### Added in v1.7.0

- Added an opt-in pre-commit hook for staged Markdown and YAML validation.
- Added an opt-in commit-msg hook for scoped Conventional Commit validation.

### Changed in v1.7.0

- Documented Git hook activation and added hook validation to the
  repository audit.
- Required scoped commit messages in the commitlint configuration.
- Aligned the commit message template with scoped commit headers.

## v1.6.0 - 2026-07-03

### Added in v1.6.0

- Added a repository-scoped Codex skill for guarded commit, atomic push, and
  SemVer tag workflows.

### Changed in v1.6.0

- Documented the Codex skill in the README and repository file inventory.

## v1.5.4 - 2026-06-28

### Changed in v1.5.4

- Documented the decision to defer `.gitleaks.toml` and exclude
  `.betterleaks.toml` as duplicate secret scanner configuration.

## v1.5.3 - 2026-06-26

### Changed in v1.5.3

- Documented the Bash 4 requirement for the Bash Git initialization script.
- Documented the WSL-compatible `.tmp/` audit path used for PowerShell checks.
- Aligned Codespell archive skips with generic archive ignore rules.
- Added an EditorConfig rule for tab-indented Git configuration templates.

### Fixed in v1.5.3

- Removed ScriptAnalyzer's `Write-Host` warning from the PowerShell Git
  initialization confirmation prompt.
- Clarified the release package workflow tag input description.

## v1.5.2 - 2026-06-25

### Added in v1.5.2

- Added a shared repository audit script for local release readiness and
  GitHub Actions checks.
- Added a static audit check that detects SemVer validation pattern drift
  across release, workflow, and initialization surfaces.

### Changed in v1.5.2

- Documented that releases require the local audit suite before tagging or
  publishing.
- Documented that release package smoke checks intentionally resolve the
  latest published `agent-coding-rules` release.
- Documented full-audit network requirements, partial audit modes, and the
  accepted trust model for version-pinned tool downloads.
- Pinned the Codespell audit bootstrap to a temporary Python target.
- Added default ignore and initialization warnings for `.envrc` files and
  `var/` runtime storage paths.

### Fixed in v1.5.2

- Made repository audit PowerShell checks work from WSL with Windows
  PowerShell.
- Aligned Codespell skips with ignored runtime and temporary paths.
- Added repository audit coverage for commit messages introduced by the
  current pull request, push, or local branch.
- Made PowerShell Git initialization confirmations consume piped standard
  input deterministically and keep prompts out of boolean returns in CI
  smoke tests.

### Security in v1.5.2

- Disabled checkout credential persistence in repository audit and release
  package workflows.
- Removed unnecessary GitHub token exposure from release package builds and
  pull request static audit checks.

## v1.5.1 - 2026-06-23

### Changed in v1.5.1

- Recorded the requested agent rules reference in release package manifests and
  verified cloned agent rules tags against the resolved tag.
- Documented the accepted lightweight CI tradeoff for version-pinned tool
  downloads without hash verification.
- Clarified that VS Code format-on-save settings are human IDE defaults, not
  agent authorization for formatters or automatic fixers.

### Fixed in v1.5.1

- Deferred Git repository creation in initialization scripts until after all
  user confirmations are accepted.

## v1.5.0 - 2026-06-22

### Changed in v1.5.0

- Neutralized regional defaults in the environment template.
- Covered complex SemVer tags in Git initialization smoke checks.
- Wrapped long GitHub Actions shell lines for YAML lint readability.
- Aligned Codespell skips with generated and cache ignore paths.
- Preferred unelevated sandboxing in the Codex configuration template.
- Made latest agent rules the default release package source.
- Clarified that the environment template is intentionally broad.
- Validated release package names before creating or replacing ZIP files.
- Aligned Git initialization first commit messages with Conventional Commits.
- Pinned GitHub Actions runner, checkout, Markdown lint, and spelling tool
  versions for reproducible repository audits.
- Expanded repository audit checks to cover script syntax, ShellCheck,
  PowerShell parsing, Git whitespace, and commitlint configuration.
- Documented commitlint usage and clarified that no commit hook is installed
  by default.
- Pinned GitHub Actions checkout usage by SHA while retaining readable version
  comments.
- Included tracked VS Code workspace files in Codespell coverage.
- Validated release package tags before checkout and upload.
- Resolved `latest` release package agent rules references to concrete SemVer
  tags before cloning.
- Clarified that VS Code format-on-save settings do not authorize agent-run
  formatters or automatic fixers.
- Documented GitHub private reporting for sensitive security and conduct
  reports.
- Cleaned release package script warnings reported by PowerShell
  ScriptAnalyzer.
- Replaced the Codex configuration template model example with a stable
  placeholder.
- Validated Git initialization target directories before creating commits.
- Previewed Git initialization commit file lists and risky paths before
  staging files.
- Required explicit `AGENT_RULES_REF` values for automatic release packages
  while accepting `latest` or SemVer tags.
- Added smoke checks for Git initialization and release package scripts.
- Hardened repository audit tool setup and logged the ShellCheck version.
- Clarified the Windows sandbox scope in the Codex configuration template.

## v1.4.2 - 2026-06-20

### Changed in v1.4.2

- Tightened commitlint rules and documentation for stricter Conventional
  Commit validation.

## v1.4.1 - 2026-06-20

### Fixed in v1.4.1

- Tightened the commitlint parser pattern to reject scopes containing `!`.

## v1.4.0 - 2026-06-19

### Added in v1.4.0

- Commitlint configuration for explicit Conventional Commit validation.
- PowerShell and Bash scripts for confirmed Git repository initialization with
  SemVer tag validation and optional remote push.

### Changed in v1.4.0

- Git initialization scripts now show help when run without arguments.
- Updated README and repository file inventory for commitlint and Git
  initialization scripts.

## v1.3.0 - 2026-06-18

### Added in v1.3.0

- Release package script for generated starter-kit archives enriched with
  `agent-coding-rules` instruction files.
- GitHub Actions workflow that builds and uploads the enriched release package
  on published releases or manual dispatch.
- Release package documentation with `agent-coding-rules` context for automatic
  and manual usage.

### Changed in v1.3.0

- Updated README and repository file inventory for release package automation.

## v1.2.2 - 2026-06-18

### Changed in v1.2.2

- Documented the decision to exclude the reviewed project-specific
  `.markdownlint-cli2.yaml` configuration.

## v1.2.1 - 2026-06-18

### Changed in v1.2.1

- Renamed the reusable GitHub release notes template to
  `GITHUB_RELEASE_NOTES.md`.

## v1.2.0 - 2026-06-18

### Added in v1.2.0

- VS Code workspace recommendations for consistent local editing.
- Reusable Codex project configuration template for trusted repositories.
- Reusable environment variable template for future projects.
- Reusable Git configuration template for placeholder-based local setup.
- Reusable GitHub release notes template for future releases.

### Changed in v1.2.0

- Updated README feature coverage for the new reusable templates.
- Updated repository file inventory for VS Code and new template files.

## v1.1.1 - 2026-06-18

### Changed in v1.1.1

- Clarified optional file status semantics in the repository inventory.
- Replaced visible bug report step placeholders with hidden guidance text.
- Updated GitHub community file documentation to avoid code ownership references.

### Removed in v1.1.1

- GitHub CODEOWNERS configuration from the default template.

## v1.1.0 - 2026-06-18

### Added in v1.1.0

- Code of conduct for repository participation.
- Reusable code of conduct template for future projects.
- GitHub CODEOWNERS configuration for default repository ownership.
- GitHub issue templates for bug reports, documentation, and feature requests.
- GitHub Actions workflow for minimal repository Markdown and spelling audits.
- Support guidance for repository users.
- Reusable support template for future projects.

## v1.0.0 - 2026-06-17

### Added in v1.0.0

- Initial repository starter-kit structure.
- Git and editor convention files.
- Generic ignore rules and Git attributes.
- Commit message template.
- Lightweight Codespell configuration.
- Coding-agent, contribution, security, and pull request guidance.
- Reusable project templates.
- Repository file inventory.

### Changed in v1.0.0

- None.

### Removed in v1.0.0

- None.

### Fixed in v1.0.0

- None.

### Security in v1.0.0

- None.
