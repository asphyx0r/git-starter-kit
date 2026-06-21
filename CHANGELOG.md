# Changelog

All notable changes to this repository will be documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this repository
uses [Semantic Versioning](https://semver.org/).

## Unreleased

### Changed

- Tightened commitlint rules and documentation for stricter Conventional
  Commit validation.
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
- Restricted release package agent rules references to `latest` or SemVer tags.
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
- Required pinned `AGENT_RULES_REF` SemVer tags for automatic release packages.

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
