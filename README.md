# Git Starter Kit

A minimal, reusable starter repository for Git and GitHub projects.

## Features

- Git and editor conventions for repository consistency.
- Generic ignore rules for local files, secrets, caches, and build outputs.
- Commit message guidance with a reusable Git commit template and strict
  commitlint rules.
- Lightweight spelling configuration for documentation and repository files.
- Coding-agent instructions for cautious, verifiable repository changes.
- VS Code workspace recommendations for consistent local editing.
- Repository file inventory in `docs/repository-files.md`.
- Reusable templates for README, changelog, contributing, code of conduct,
  security, support, environment, Git, Codex, and release notes files.
- GitHub community files for pull requests, issues, conduct, and support.
- GitHub Actions workflow for lightweight Markdown, spelling, script, and
  configuration audits.
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

Published releases can attach a generated ZIP package that overlays a pinned
`agent-coding-rules` release and records its source in
`_agent-rules-source.json`. See [Release Package](docs/release-package.md) for
automatic and manual usage.

Automatic release packages require the `AGENT_RULES_REF` repository variable to
name a SemVer agent-rules tag. Manual runs must also use a SemVer tag.

Initialize a target repository with an explicit confirmation prompt:

```bash
bash scripts/git-init.sh --path ../example-app --tag v1.0.0
```

```powershell
powershell -NoProfile -File scripts\git-init.ps1 --path ..\example-app --tag v1.0.0
```

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
