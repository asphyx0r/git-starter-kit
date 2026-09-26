# Git Starter Kit

A minimal, reusable starter repository for Git and GitHub projects.

## Features

- Git and editor conventions for repository consistency.
- Conservative ignore rules for explicit local outputs and root secrets, with
  optional language patterns that preserve application sources and fixtures.
- Commit message guidance with a reusable Git commit template, strict scoped
  Commitlint rules, and blocking validation for guarded commits.
- Versioned staged-only pre-commit, commit-message, and affected-test pre-push
  hooks.
- Lightweight spelling configuration for documentation and repository files.
- Strict, byte-identical Betterleaks and Gitleaks rules for credential
  assignments, authorization headers, and service URI passwords.
- Coding-agent instructions for cautious, verifiable repository changes.
- VS Code workspace recommendations for consistent local editing.
- Repository file inventory in `docs/repository-files.md`.
- Tool reference documentation in `tools/README.md`.
- Staged ZIP backup utility with exact Git `HEAD` and SemVer tag provenance.
- Tracked starter-kit release manifest with original and current core baselines.
- Reusable templates for README, tool-directory README, changelog,
  contributing, code of conduct, security, support, environment, Git, Codex,
  skill documentation, and release notes files.
- GitHub community files for pull requests, issues, conduct, and support.
- GitHub Actions quality checks for Ubuntu with Python 3.11 and Windows with
  Python 3.14, published through one aggregate required check.
- Per-repository scheduled workflow that proposes canonical agent-rule updates
  through a repository-local pull request.
- Shared local and CI repository audit script for release readiness checks.
- Starter-only, CI-gated release package automation for exports enriched with
  coding-agent rules.
- Interactive Git initialization scripts for PowerShell and Bash.
- Repository-scoped Codex skill for canonical SemVer bump analysis, explicitly
  gated commits and tags, atomic pushes, and CI-gated GitHub Releases.

## Installation

For a numbered Windows walkthrough, follow the
[quick-start cheat sheet](docs/quick-start.md).

For a new project, download the `with-agent-rules.zip` asset from a published
[release](https://github.com/asphyx0r/git-starter-kit/releases), extract it into
a new empty directory and follow the project README composed inside that ZIP.
Install its locked Node hook dependencies and run the real initializer:

```bash
npm ci --ignore-scripts --prefix tools/quality
bash tools/git-init.sh --path .
```

An optional `bash tools/git-init.sh --path . --dry-run` inspects the actions
before initialization. Windows users may run the equivalent
`powershell -NoProfile -File tools/git-init.ps1 --path .`.
Prerequisites are Git, Bash, Python 3.11+, Node.js 24 and npm; `.ps1` tools use
Windows PowerShell 5.1/PowerShell 7 on Windows and PowerShell 7 on Linux.
Provision selected pinned external tools with the
[explicit local installer](tools/README.md#local-provisioning) before checks
that require them; audits never install these tools automatically.

Clone this source repository only to maintain the starter itself. Raw source
archives do not contain the composed consumer inventory or project defaults.
The companion `upgrade-toolkit.zip` embeds the exact initialization ZIP for
reviewed updates to existing projects; see [Upgrade toolkit](docs/upgrade-toolkit.md).

New consumer settings use project/repository mode with optional automations
disabled and an empty explicit check list. Ordinary mandatory rules, hooks,
core audits and release-artifact verification remain active. Empty checks warn;
application validation must be adopted explicitly and actually executed in CI.
`starter-kit-manifest.json` retains the original and current published core
baselines, with the consumer file inventory recomputed after composition.

## Usage

```bash
git status
git config commit.template .gitmessage
git config core.hooksPath .githooks
```

The optional hooks delegate to the shared repository-audit profiles. Pre-commit
validates applicable staged content without rewriting it, commit-msg enforces
the scoped Conventional Commit rules, and pre-push runs affected Python or
shell test families against exact pushed objects and validates SemVer release
artifacts. Install the locked quality toolchain before enabling the hooks.
Leaving `core.hooksPath` unset allows ordinary manual Git commands to bypass
them; guarded repository tools force `.githooks` independently. See
[Contributing](CONTRIBUTING.md) for the hook policy and [Tools](tools/README.md)
for the exact profiles and prerequisites.

Source templates under `templates/project/` are composed into the consumer ZIP.
Complete its identified project name, application commands and contact fields
before publishing an application.

The `.gitignore` language headings are comments; they do not scope patterns.
Keep contextual exclusions commented until a project identifies exact generated
locations, and preserve sources, test/archive/binary fixtures and lockfiles.
The consumer [ignore policy](templates/project/docs/project-configuration.md#ignore-policy)
explains the explicit local tooling paths. Its
[Laravel onboarding](templates/project/docs/project-configuration.md#laravel-onboarding)
creates the application in an absent or empty `laravel/` only after the initial
system-only annotated `v1.0.0`; application configuration stays inside that
directory and the root remains the single Git repository.

Use the GitHub templates in `.github/` to keep issues and pull requests
reviewable with minimal process.

Run the exhaustive audit used by the primary GitHub Actions job:

```bash
bash tools/repository-audit.sh
```

The default audit, `all`, `full`, and `static` select the same exhaustive
profile without repeating audit families. It consumes the locked Python and
npm environments plus integrity-verified external tools already installed by
the caller; audit profiles never install dependencies. The explicit `full`
mode is therefore an alias for the default behavior:

```bash
bash tools/repository-audit.sh full
```

Use the optional read-only profile when network access, temporary files, and
mutating smoke tests are not allowed:

```bash
bash tools/repository-audit.sh readonly
```

The read-only profile uses installed tools and disables optional Git locks.
A tool required by a selected check fails that check instead of being installed
or skipped. Only the exhaustive profile's release-package smoke check uses the
network: it queries GitHub for the latest `agent-coding-rules` release metadata
without downloading release assets or dependencies.

The Repository audit workflow covers all branch and tag pushes, pull requests
targeting `main` or `master`, published releases, and manual runs. Reference
deletions report that there is no new commit and skip the content suites.
Linux runs a blocking npm audit of development dependencies at the high
severity threshold; registry errors also fail the job. Tags outside the release
SemVer contract trigger an audit without creating a release.

The source repository's `checks: []` declares no additional application checks.
The repository quality checks and test suites still run in both CI environments.

The Repository audit workflow installs each declared dependency family once
per isolated job and caches pip and npm downloads using the tracked dependency
locks and tool versions. `quality-linux` runs the exhaustive profile on
Ubuntu 24.04 with Python 3.11.
`compatibility-windows` uses Windows 2025 with Python 3.14 for the fast
cross-platform profile, the complete Python test suite, focused Git Bash hook
checks, and PSScriptAnalyzer.
Both use Node.js 24.20.0. The aggregate `Repository audit` check requires both
jobs to succeed; manual runs retain the distinct
`Repository audit (manual)` name.

Do not create a release tag or GitHub release if the exhaustive audit fails.

For new refs and stable release tags, the audit validates commit messages from
the highest reachable stable tag through `HEAD`. A first release validates all
reachable commits. Tag validation therefore cannot be replaced by a green
check that inspected only the tag target commit.

Use `markdown`, `spelling`, `fast`, or `powershell-static` to isolate a focused
subset while diagnosing failures. See [Tools](tools/README.md) for the complete
profile contract and integrity-pinned installation procedure.

When the audit runs from WSL with Windows PowerShell for PowerShell checks,
it uses the ignored `.tmp/` path for temporary files that both environments
can access.

Preview a staged backup of the current repository into an existing external
directory:

```bash
python tools/backup-target-directory.py \
  --dry-run \
  --source-directory . \
  --target-directory ../backups
```

Remove `--dry-run` to create the ZIP. Keep repository writers stopped during
the copy when a consistent point-in-time backup is required. See
[Tools](tools/README.md) for archive contents, provenance rules, limitations,
and restoration caveats.

`git-starter-kit` releases attach two generated ZIP packages and their
`SHA256SUMS` file. The package build asserts that the recorded sources match
the release tag and requested `agent-coding-rules` release. It transfers only
those three regular files to a separate write-scoped publish job, which
revalidates their names and SHA-256 values before upload. Package-production
tooling is source-repository-only and is excluded from derived repository
packages. See [Release Package](docs/release-package.md) for automatic and
manual usage.

Automatic release packages use the latest published full `agent-coding-rules`
release. Manual runs accept `latest` or a SemVer agent-rules tag. When `latest`
is used, the generated manifest records both the requested `latest` reference
and the resolved SemVer tag.

Each initialized repository owns its agent-rule synchronization. The
`Agent rules update` workflow resolves the latest `agent-coding-rules` release,
executes that release's synchronization tool without write credentials, and
seals the allowed transfer. Its publishing job revalidates the source, target,
and sealed hashes before minting the GitHub App token used only to push the
branch and open or update the pull request in the repository that executed the
workflow. Configure
`AGENT_RULES_APP_CLIENT_ID` as a repository variable and
`AGENT_RULES_APP_PRIVATE_KEY` as a repository secret. Install that GitHub App
on the target repository with **Contents** and **Pull requests** write access.
Repositories with `.starter-kit-project.json` use its
`automations.agentRulesSync` flag from an immutable default-branch snapshot.
Set it to `false` to disable scheduled and release-triggered synchronization.
Intentional manual synchronization remains available on the default branch.
The `AGENT_RULES_SYNC_ENABLED` repository Actions variable applies only when
that configuration file is absent: `false` disables scheduled and manual
synchronization, while published releases still synchronize. The workflow also
runs in `git-starter-kit`, so its tracked rule files remain current instead of
being injected only during package generation.

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

The target must contain a readable `.githooks/commit-msg` and
`commitlint.config.cjs`, and Commitlint must be installed. Both initializers
validate one temporary UTF-8 message file with `commitlint --edit`, commit that
same file with `core.hooksPath=.githooks`, and stop without creating `HEAD` if
either validation fails.

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
when `CREATE_GITHUB_RELEASE=true` is explicitly provided. Before mutation, the
skill validates the required workflows, branch protection, release metadata,
and the repository variable and secret used by `Agent rules update`.

On a protected or shared release target, each preparation intention uses a
dedicated branch and pull request. The installed guarded merge workflow
validates the exact squash message, then the skill waits for the resulting
target-branch audit and rechecks the merged tree before preparing the next
intention. The final atomic push leaves that already-published target unchanged.

In a derived repository, the skill creates a stable latest release without
assets. That release is complete only after the exact automatic
`Agent rules update` and `Repository audit` release runs succeed. The canonical
`git-starter-kit` extension instead creates a prerelease; `Release package`
must also succeed, upload both verified ZIPs plus `SHA256SUMS`, and promote the
release. Its read-only build seals those three files for a separate privileged
publication job; the skill verifies all three GitHub digests and the checksum
asset's exact two ZIP entries.

For this canonical repository, the guarded workflow prepares and validates
`starter-kit-manifest.json` in a distinct release-preparation commit before
the remote preflight and tag. A GitHub release event validates the committed
manifest; it never attempts to rewrite tag contents after publication.

Every repository carrying the starter-kit release automation also prepares a
second, repository-owned release commit containing `VERSION`, `SHA256SUMS`, and
`manifest.json`. The generator inventories the exact candidate Git tree,
validates the dynamic manifest against the tracked JSON Schema, and asks for
every release-specific value that cannot be established mechanically. The
pre-commit and pre-push hooks reject incomplete or stale artifact sets, and the
tag-only `Release artifacts` workflow independently validates the pushed tag.
The canonical starter package excludes its own three generated root files so
each derived repository creates release identification for itself.

Before creating a tag, the guarded workflow pushes the candidate SHA to a
unique `codex/release-preflight-*` branch and requires the aggregate
`Repository audit` check to succeed. The workflow must cover that prefix,
either through unfiltered pushes or matching branch filters, without path
filters that could suppress the required run. After the final atomic branch-and-tag
push, every expected branch and tag audit run must succeed; a manual or
scheduled green run cannot replace a failed push run. Protect the default
branch with this GitHub Actions check and apply the rule to administrators when
the repository supports required checks.

Publishing any release directly triggers `Agent rules update` and `Repository
audit`. The canonical starter-kit prerelease also triggers `Release package`.
Each required run must match the published tag, its exact commit, the `release`
event, and the publication time; a manual, scheduled, or tag-push run cannot
replace any of these release runs.

The retained non-conventional historical commit, single-owner CODEOWNERS risk,
and external GitHub branch and release-environment protections are documented
in [Contributing](CONTRIBUTING.md) and
[Release Package](docs/release-package.md). Repository files alone do not prove
those GitHub settings or an independent human approval.

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
