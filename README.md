# Git Starter Kit

A minimal, reusable starter repository for Git and GitHub projects.

## Features

- Git and editor conventions for repository consistency.
- Generic ignore rules for local files, secrets, direnv files, runtime
  storage, caches, and build outputs.
- Commit message guidance with a reusable Git commit template, strict scoped
  commitlint rules, and optional commit-message validation.
- Optional staged Markdown and YAML pre-commit hook.
- Lightweight spelling configuration for documentation and repository files.
- Coding-agent instructions for cautious, verifiable repository changes.
- VS Code workspace recommendations for consistent local editing.
- Repository file inventory in `docs/repository-files.md`.
- Tool reference documentation in `tools/README.md`.
- Reusable templates for README, tool-directory README, changelog,
  contributing, code of conduct, security, support, environment, Git, Codex,
  skill documentation, and release notes files.
- GitHub community files for pull requests, issues, conduct, and support.
- GitHub Actions workflow for lightweight Markdown, spelling, commit message,
  script, and configuration audits.
- Shared local and CI repository audit script for release readiness checks.
- CI-gated release package automation for exports enriched with coding-agent
  rules.
- Interactive Git initialization scripts for PowerShell and Bash.
- Repository-scoped Codex skill for canonical SemVer bump analysis, explicitly
  gated commits and tags, atomic pushes, and CI-gated GitHub Releases.

## Installation

Use this repository as a starting point for a new project.

```bash
git clone <repository-url> <new-project-name>
cd <new-project-name>
```

## Usage

```bash
git status
git config commit.template .gitmessage
git config core.hooksPath .githooks
```

The optional pre-commit hook checks staged `*.md` files with
`markdownlint-cli2` and staged `*.yml` or `*.yaml` files with `yamllint`.
The optional commit-msg hook checks commit messages with `commitlint` and the
repository-specific scoped Conventional Commit rules. Install those tools before
enabling the hooks, or leave `core.hooksPath` unset.

Copy files from `templates/` when starting a new project and replace the
placeholder values with project-specific content.

Use the GitHub templates in `.github/` to keep issues and pull requests
reviewable with minimal process.

Run the same audit suite locally that GitHub Actions runs:

```bash
bash tools/repository-audit.sh
```

The default audit is the full profile. Run it only in an environment where
package bootstrap, temporary files, network access, and smoke repositories are
allowed. The explicit `full` mode is an alias for this default behavior:

```bash
bash tools/repository-audit.sh full
```

Use the optional read-only profile when installations, network access,
temporary files, and mutating smoke tests are not allowed:

```bash
bash tools/repository-audit.sh readonly
```

The read-only profile uses installed tools and disables optional Git locks.
Missing tools fail the audit instead of being installed or skipped.

Do not create a release tag or GitHub release if the full audit fails. The full
profile bootstraps `codespell` 2.4.2 in a temporary Python target and requires
the same tools as CI, including `shellcheck`, `pwsh`, `python`, `node`, `git`,
and `npx`. It intentionally resolves the latest published
`agent-coding-rules` release during release package smoke checks; do not pin
that check to an older rules release.

Audit tool bootstrap uses version-pinned package downloads from npm and PyPI
without package hash verification. This is an accepted lightweight trust
tradeoff for the generic starter kit.

The full profile needs network access to npm for Markdown lint bootstrapping,
PyPI for Codespell bootstrapping, and GitHub for the latest agent-rules smoke
check. Use `markdown`, `spelling`, or `static` to run one full-profile audit
family at a time when diagnosing network or tool availability problems.

When the audit runs from WSL with Windows PowerShell for PowerShell checks,
it uses the ignored `.tmp/` path for temporary files that both environments
can access.

Published releases can attach a generated ZIP package that overlays a resolved
`agent-coding-rules` release and records the requested and resolved source in
`_agent-rules-source.json`. See [Release Package](docs/release-package.md) for
automatic and manual usage.

Automatic release packages use the latest published full `agent-coding-rules`
release. Manual runs accept `latest` or a SemVer agent-rules tag. When `latest`
is used, the generated manifest records both the requested `latest` reference
and the resolved SemVer tag.

Initialize a target repository with an explicit confirmation prompt:

```bash
bash tools/git-init.sh --path ../example-app --tag v1.0.0
```

```powershell
powershell -NoProfile -File tools\git-init.ps1 --path ..\example-app --tag v1.0.0
```

Both scripts preview the files Git can commit before creating target `.git`
metadata. If commit confirmation is declined, the target directory is left
uninitialized.
If a target already contains unreadable `.git` metadata, repair or remove it
before rerunning the initializer.

The Bash script requires Bash 4 or newer.

Use `--remote <url>` when the initialized repository should add `origin` and
push `main` with tags. When `--remote` is omitted, the scripts do not push.

Run either script without arguments, or with `--help`, to show usage.

See [Tools](tools/README.md) for detailed tool synopsis, options, examples,
exit status, and usage notes.

Invoke `$git-commit-push-tag` in Codex only when its guarded release workflow
is explicitly requested. Without `BUMP=patch`, `BUMP=minor`, or `BUMP=major`,
the skill reports the recommended bump and tag without modifying the
repository. A GitHub Release is created from the release-notes template only
when `CREATE_GITHUB_RELEASE=true` is explicitly provided. It starts as a
prerelease and is complete only after the automatic `Release package` workflow
uploads the verified asset and promotes it to a stable release.

## Maintainer operations

The verified migration of the canonical maintainer worktree from Google Drive
to local NTFS storage is recorded in
[Repository migration](docs/repository-migration.md).

## Contributing

Keep changes minimal, generic, and directly useful for reusable Git/GitHub
project setup.

Please make sure to update `docs/repository-files.md` when repository files
are added or changed.

## Authors

- Repository maintainers

## License

[MIT](LICENSE)
