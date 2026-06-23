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

### `.codespellrc`

- Type: `file`
- Status: `required`
- Goal: Configures Codespell for lightweight spelling checks.
- Usage: Run `codespell` from the repository root.
- Notes: Checks hidden files, file names, and tracked workspace configs while
  skipping generated, dependency, report, cache, and binary paths.

### `.editorconfig`

- Type: `file`
- Status: `required`
- Goal: Defines editor-level formatting defaults for a polyglot template.
- Usage: Editors and IDEs that support EditorConfig apply these settings.
- Notes: Keep rules language-family oriented rather than framework-specific.

### `.gitattributes`

- Type: `file`
- Status: `required`
- Goal: Defines Git text normalization and common binary formats.
- Usage: Git normalizes text to LF and preserves CRLF for Windows scripts.
- Notes: Keep the binary list focused on common formats.

### `.github/`

- Type: `directory`
- Status: `required`
- Goal: Stores GitHub-specific community and collaboration files.
- Usage: Keep GitHub files here when the platform expects this location.
- Notes: Avoid duplicating root-level files in this directory.

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
- Goal: Runs a minimal repository documentation audit on GitHub Actions.
- Usage: Executes on pushes, pull requests, and manual dispatch.
- Notes: The workflow uses a pinned runner, a checkout action pinned by SHA
  for `actions/checkout@v7.0.0`, `markdownlint-cli2`, and Codespell versions
  before running Markdown, spelling, script, smoke, and configuration checks.
  ShellCheck is provided by the runner, and its version is logged in CI.
  Long shell snippets are wrapped for YAML lint readability. SemVer
  smoke cases cover simple, complex, invalid, and cancelled initialization
  flows. Tool downloads are version-pinned but not hash-verified; this is an
  intentional lightweight CI tradeoff.

### `.github/workflows/release-package.yml`

- Type: `file`
- Status: `optional`
- Goal: Builds and uploads an enriched release package asset.
- Usage: Runs when a release is published or manually through workflow
  dispatch.
- Notes: Uses a pinned runner and a checkout action pinned by SHA for
  `actions/checkout@v7.0.0`, uses `latest` automatically for release
  packages, validates manual
  release tags and agent rules references, then calls
  `scripts/build-release-package.ps1`
  and uploads the generated ZIP. Shell validation messages are wrapped for
  YAML lint readability.

### `.gitignore`

- Type: `file`
- Status: `required`
- Goal: Prevents common local files and generated artifacts from commits.
- Usage: Git excludes matching paths from normal version control.
- Notes: Covers common credential stores and generated files while avoiding
  source files, tests, lock files, or project config.

### `.gitmessage`

- Type: `file`
- Status: `required`
- Goal: Provides a reusable commit message template.
- Usage: Use with `git commit --template=.gitmessage` or local Git config.
- Notes: Advisory only; it does not enforce commit validation.

### `.markdownlint-cli2.yaml`

- Type: `file`
- Status: `rejected`
- Goal: Would define repository-level Markdown lint rules.
- Usage: Not included; the audit workflow uses markdownlint defaults.
- Notes: The reviewed candidate was project-specific, included a broad proper
  names list, and rejected valid starter-kit placeholders such as
  `{GITHUB-USERNAME}`.

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
  recommendations. Format-on-save settings are for human VS Code use and do
  not authorize agents to run formatters or automatic fixers.

### `AGENTS.md`

- Type: `file`
- Status: `required`
- Goal: Provides repository-level instructions for coding agents.
- Usage: Read before making changes in this repository.
- Notes: Avoid duplicating agent instructions in GitHub-specific files.

### `CHANGELOG.md`

- Type: `file`
- Status: `required`
- Goal: Tracks notable changes to this repository.
- Usage: Update `Unreleased` when repository files or templates change.
- Notes: Future-project placeholders belong in `templates/CHANGELOG.md`.

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
  loosely formatted commit messages. No commit hook is installed by default.

### `CONTRIBUTING.md`

- Type: `file`
- Status: `required`
- Goal: Explains how contributors should propose and verify changes.
- Usage: Read before contributing to the starter kit.
- Notes: Future-project placeholders belong in `templates/CONTRIBUTING.md`.

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
- Notes: Do not leave future-project placeholders in the root README.

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

### `scripts/`

- Type: `directory`
- Status: `optional`
- Goal: Stores small repository maintenance scripts.
- Usage: Keep scripts generic and tied to documented repository workflows.
- Notes: Avoid project-specific build, test, or deploy automation here.

### `scripts/build-release-package.ps1`

- Type: `file`
- Status: `optional`
- Goal: Generates a starter-kit release package enriched with agent rules.
- Usage: Run from the release package workflow or manually with PowerShell.
- Notes: Copies tracked starter-kit files, resolves `latest` through the GitHub
  release API by default, overlays tagged `agent-coding-rules` files,
  writes `_agent-rules-source.json`, validates package file names before
  writing ZIP files, keeps SemVer validation aligned with CI smoke cases,
  and verifies required files in the archive. Helper
  functions use ScriptAnalyzer-compatible names and explicit parameters.

### `scripts/git-init.ps1`

- Type: `file`
- Status: `optional`
- Goal: Initializes a target Git repository from PowerShell after explicit
  user confirmation.
- Usage: Run with `--path <directory>` and optional `--tag <tag>`,
  `--remote <url>`, and `--verbose`. Run without arguments to show help.
- Notes: Validates SemVer tags covered by CI smoke cases, requires
  existing non-empty target directories,
  previews committable files from Git porcelain status without creating target
  Git metadata, warns on risky credential and artifact paths, refuses existing
  target commits, creates the first Conventional Commit on `main`, tags it,
  and only pushes when `--remote` is provided.

### `scripts/git-init.sh`

- Type: `file`
- Status: `optional`
- Goal: Initializes a target Git repository from Bash after explicit user
  confirmation.
- Usage: Run with `--path <directory>` and optional `--tag <tag>`,
  `--remote <url>`, and `--verbose`. Run without arguments to show help.
- Notes: Validates SemVer tags covered by CI smoke cases, requires
  existing non-empty target directories,
  previews committable files from Git porcelain status without creating target
  Git metadata, warns on risky credential and artifact paths, refuses existing
  target commits, creates the first Conventional Commit on `main`, tags it,
  and only pushes when `--remote` is provided.

### `docs/`

- Type: `directory`
- Status: `required`
- Goal: Stores repository documentation.
- Usage: Keep maintained documentation that supports the starter kit here.
- Notes: Avoid duplicating root-level community files.

### `docs/repository-files.md`

- Type: `file`
- Status: `required`
- Goal: Maintains the inventory of repository files and directories.
- Usage: Update whenever repository files or directories are added or changed.
- Notes: This file is the source of truth for repository file ownership.

### `docs/release-package.md`

- Type: `file`
- Status: `optional`
- Goal: Explains automatic and manual enriched release package generation.
- Usage: Read before publishing or manually regenerating release package
  assets.
- Notes: Covers the release package workflow, generated ZIP contents, local
  testing, and common troubleshooting steps.

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

### `templates/.gitconfig`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable user Git configuration template.
- Usage: Copy to a user Git config, replace identity placeholders, and adjust
  the editor command if needed.
- Notes: Documents `code --wait`, pager behavior, line ending conversion,
  whitespace checks, command autocorrection, and a commented `commit.template`
  example. Keep personal identities out of this file; repository `.gitconfig`
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

### `templates/SECURITY.md`

- Type: `file`
- Status: `required`
- Goal: Provides a reusable security policy structure.
- Usage: Replace placeholders with project-specific security policy details.
- Notes: Keep the root file concrete and this file generic.

### `templates/SUPPORT.md`

- Type: `file`
- Status: `optional`
- Goal: Provides a reusable support policy structure for future projects.
- Usage: Replace placeholders with project-specific support channels.
- Notes: Keep the root file concrete and this file generic.
