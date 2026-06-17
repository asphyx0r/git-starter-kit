# Git Starter Kit

A minimal, reusable starter repository for Git and GitHub projects.

## Features

- Git and editor conventions for repository consistency.
- Generic ignore rules for local files, secrets, caches, and build outputs.
- Commit message guidance with a reusable Git commit template.
- Lightweight spelling configuration for documentation and repository files.
- Coding-agent instructions for cautious, verifiable repository changes.
- Repository file inventory in `docs/repository-files.md`.
- Reusable templates for README, changelog, contributing, code of conduct,
  security, and support files.
- GitHub community files for pull requests, issues, code ownership, conduct,
  and support.
- GitHub Actions workflow for lightweight Markdown and spelling audits.

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

Use the GitHub templates in `.github/` to keep issues, pull requests, and
repository ownership reviewable with minimal process.

## Contributing

Keep changes minimal, generic, and directly useful for reusable Git/GitHub
project setup.

Please make sure to update `docs/repository-files.md` when repository files
are added or changed.

## Authors

- Repository maintainers

## License

[MIT](LICENSE)
