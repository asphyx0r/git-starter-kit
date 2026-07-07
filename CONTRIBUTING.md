# Contributing

Thank you for helping improve this repository template.

## Contribution principles

- Keep changes small, explicit, and reusable.
- Prefer generic Git and GitHub conventions over project-specific rules.
- Avoid adding language-specific tooling unless it has been explicitly approved.
- Do not commit secrets, tokens, passwords, or real environment values.
- Update `docs/repository-files.md` when repository files are added or changed.

## Before changing files

Review the existing repository context first:

- `README.md` for the repository purpose.
- `AGENTS.md` for coding-agent instructions.
- `docs/repository-files.md` for the file inventory.

## Commit messages

Use `.gitmessage` as a commit message template when helpful:

```bash
git commit --template=.gitmessage
```

Commit messages should follow the rules in `commitlint.config.cjs`. This
repository does not install a commit-message hook by default; run `commitlint`
manually or from a downstream hook when strict validation is needed.

## Optional pre-commit hook

Enable the repository hook path when staged Markdown and YAML validation should
run before each commit:

```bash
git config core.hooksPath .githooks
```

The hook requires `markdownlint-cli2` for staged `*.md` files and `yamllint` for
staged `*.yml` or `*.yaml` files.

## Pull requests

A good pull request should explain:

- What changed.
- Why the change is useful.
- How the change was verified.
- Whether any files were intentionally deferred, rejected, or removed.

## Verification

Before submitting changes, check that:

- Only expected files changed.
- Markdown and configuration files are readable and valid.
- The repository inventory matches the files present in the repository.
