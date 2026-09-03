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

The non-conventional historical commit
`2fbb9bcb749db1d9e2a9a79403246ba20884a90a`
(`Rename GitHub release notes template`, 2026-06-18) predates this strict
policy. It remains a retained exception and must never be rewritten.

## Git hooks

Enable the repository hook path for ordinary local Git commands:

```bash
git config core.hooksPath .githooks
```

The pre-commit hook checks only a temporary staged snapshot from the Git index.
It routes staged Markdown, YAML, Python, Bash or hook, JavaScript, and
PowerShell files to their language-specific checks. It also validates relevant
quality configuration and release artifacts, and never auto-formats files. The
commit-msg hook requires `commitlint` and rejects messages that do not match the
repository-specific scoped Conventional Commit rules.

The pre-push hook selects the affected Python and/or shell test families from
each pushed branch update and runs them at the pushed commit in disposable
detached clones. Each selected test family has a 180-second timeout. The hook
removes those clones when it exits. It also validates `VERSION`, `SHA256SUMS`,
and `manifest.json` for pushed SemVer tags. Guarded repository tools force this
hook path independently of local Git configuration.

## Release tags

Create all new SemVer release tags as annotated tags. The published `v1.2.1`,
`v1.2.2`, and `v1.3.0` tags are historical lightweight exceptions and must not
be rewritten.

Before creating a new release tag, resolve manifest values from authoritative
project sources, exact release facts, or a non-conflicting previous manifest.
Ask the user only for unresolved or contradictory values, require explicit
validation, and commit the generated `VERSION`, `SHA256SUMS`, and
`manifest.json` together. Never invent missing release metadata.

## Pull requests

`.github/CODEOWNERS` assigns every path to `@asphyx0r`. This provides ownership
and review traceability, but does not provide an independent approval by
another person. Branch protection, required reviews, and required conversation
resolution are GitHub repository settings. Configure and verify them on GitHub;
this document does not assert that they are enabled.

A good pull request should explain:

- What changed.
- Why the change is useful.
- How the change was verified.
- Whether any files were intentionally deferred, rejected, or removed.

## Verification

The supported CI gate runs the exhaustive profile on Ubuntu 24.04 with Python
3.11 and runs the fast profile, complete Python suite, and PSScriptAnalyzer on
Windows 2025 with Python 3.14. Both jobs use Node.js 24.20.0, install the locked
dependencies and integrity-verified external tools without a generic cache,
and must pass before the aggregate `Repository audit` check succeeds.

Before submitting changes, run the applicable focused hook profiles and the
complete local audit when its required tools are available, then check that:

- Only expected files changed.
- Markdown and configuration files are readable and valid.
- The repository inventory matches the files present in the repository.
- `bash tools/repository-audit.sh full` succeeds in the locked quality
  environment.
