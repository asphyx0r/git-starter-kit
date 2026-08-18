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

Use `.gitmessage` as a starting point when helpful, but write the complete
candidate message to a temporary file outside the working tree. Validate and
commit that exact file from the repository root:

```bash
commitlint --edit /path/to/commit-message.txt
git -c core.hooksPath=.githooks commit \
  --file=/path/to/commit-message.txt \
  --cleanup=verbatim
```

Commit messages must use scoped Conventional Commit headers that follow the
rules in `commitlint.config.cjs`, for example `docs(readme): update usage`.
Never use `-m` or `--no-verify`. A Commitlint or hook failure blocks the commit
and requires correcting and revalidating the same candidate file.

## Git hooks

Enable the repository hook path for ordinary local Git commands:

```bash
git config core.hooksPath .githooks
```

The pre-commit hook requires `markdownlint-cli2` for staged `*.md` files,
`yamllint` for staged `*.yml` or `*.yaml` files, and Python plus the pinned
release-artifact requirements when release identification is staged. The
commit-msg hook requires `commitlint` and rejects messages that do not match the
repository-specific scoped Conventional Commit rules. The pre-push hook blocks
SemVer tags whose `VERSION`, `SHA256SUMS`, or `manifest.json` is inconsistent.
Guarded repository tools force this hook path independently of local Git
configuration.

## Release tags

Create all new SemVer release tags as annotated tags. The published `v1.2.1`,
`v1.2.2`, and `v1.3.0` tags are historical lightweight exceptions and must not
be rewritten.

Before creating a new release tag, collect every unknown manifest value from
the user and commit the generated `VERSION`, `SHA256SUMS`, and `manifest.json`
together. Never infer missing release metadata.

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
