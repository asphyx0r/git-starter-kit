# Contributing

Project maintainers: fill in your repository URL, review process, supported
application runtimes and application test commands before accepting contributions.

## Development

Install the locked hook dependencies with
`npm ci --ignore-scripts --prefix tools/quality`. Run
`bash tools/repository-audit.sh fast` for core checks and
`bash tools/repository-audit.sh project-checks` for explicitly declared
application validation. Empty checks warn; they do not prove regressions passed.
See [Project configuration](docs/project-configuration.md).

## Commits and reviews

Follow [Commit rules](COMMIT_RULES.md), [Branch rules](BRANCH_RULES.md) and
[Code quality rules](CODING_RULES.md). Subjects use English, meaningful lower-case
scopes and at most 50 characters. For example:

```text
feat(api): add health endpoint
fix(auth): reject expired tokens
```

Hooks enforce syntax and content constraints through Commitlint. Choose scopes
that describe your application. Pull requests require the project's review and
validation policy. Optional guarded merge activation uses trusted default-branch
settings; ordinary reviews remain necessary when it is disabled.

## Community and security

See [Code of conduct](CODE_OF_CONDUCT.md), [Support](SUPPORT.md) and
[Security](SECURITY.md). Preserve the legal notices in [LICENSE](LICENSE).
