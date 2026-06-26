# Git Starter Kit

A minimal, reusable starter repository for Git and GitHub projects.

## Features

- Git and editor conventions for repository consistency.
- Generic ignore rules for local files, secrets, direnv files, runtime
  storage, caches, and build outputs.
- Commit message guidance with a reusable Git commit template and strict
  commitlint rules.
- Lightweight spelling configuration for documentation and repository files.
- Coding-agent instructions for cautious, verifiable repository changes.
- VS Code workspace recommendations for consistent local editing.
- Repository file inventory in `docs/repository-files.md`.
- Reusable templates for README, changelog, contributing, code of conduct,
  security, support, environment, Git, Codex, and release notes files.
- GitHub community files for pull requests, issues, conduct, and support.
- GitHub Actions workflow for lightweight Markdown, spelling, commit message,
  script, and configuration audits.
- Shared local and CI repository audit script for release readiness checks.
- Release package automation for exports enriched with coding-agent rules.
- Interactive Git initialization scripts for PowerShell and Bash.

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
```

Copy files from `templates/` when starting a new project and replace the
placeholder values with project-specific content.

Use the GitHub templates in `.github/` to keep issues and pull requests
reviewable with minimal process.

Run the same audit suite locally that GitHub Actions runs:

```bash
bash scripts/repository-audit.sh
```

Do not create a release tag or GitHub release if this local audit fails. The
script bootstraps `codespell` 2.4.2 in a temporary Python target and
requires the same tools as CI, including `shellcheck`, `pwsh`, `python`,
`node`, `git`, and `npx`. The full audit intentionally resolves the
latest published `agent-coding-rules` release during release package smoke
checks; do not pin that check to an older rules release.

Audit tool bootstrap uses version-pinned package downloads from npm and PyPI
without package hash verification. This is an accepted lightweight trust
tradeoff for the generic starter kit.

The full audit needs network access to npm for Markdown lint bootstrapping,
PyPI for Codespell bootstrapping, and GitHub for the latest agent-rules smoke
check. Use `markdown`, `spelling`, or `static` to run one audit family at a
time when diagnosing network or tool availability problems.

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
bash scripts/git-init.sh --path ../example-app --tag v1.0.0
```

```powershell
powershell -NoProfile -File scripts\git-init.ps1 --path ..\example-app --tag v1.0.0
```

Both scripts preview the files Git can commit before creating target `.git`
metadata. If commit confirmation is declined, the target directory is left
uninitialized.

The Bash script requires Bash 4 or newer.

Use `--remote <url>` when the initialized repository should add `origin` and
push `main` with tags. When `--remote` is omitted, the scripts do not push.

Run either script without arguments, or with `--help`, to show usage.

## Contributing

Keep changes minimal, generic, and directly useful for reusable Git/GitHub
project setup.

Please make sure to update `docs/repository-files.md` when repository files
are added or changed.

## Authors

- Repository maintainers

## License

[MIT](LICENSE)
