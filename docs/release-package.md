# Release Package

## Purpose

This repository can publish an enriched release package for people who want to
start a new project with the Git starter kit and the coding-agent rules already
included.

The agent rules come from
[agent-coding-rules](https://github.com/asphyx0r/agent-coding-rules), a
repository that provides practical behavior and code-quality rules for AI
coding agents.

GitHub always adds two source archives to each release:

- `Source code (zip)`
- `Source code (tar.gz)`

Those archives contain only the files that are committed in `git-starter-kit`
at the release tag.

The release package workflow adds three downloadable files to a
`git-starter-kit` release. The enriched ZIP contains the canonical rule files
already tracked at the release tag, the upgrade toolkit packages the guarded
cumulative updater, and `SHA256SUMS` gates the integrity of both ZIP payloads
within the workflow trust boundary.

## Generated File

The generated assets are named like this:

```text
git-starter-kit-vX.Y.Z-with-agent-rules.zip
git-starter-kit-vX.Y.Z-upgrade-toolkit.zip
SHA256SUMS
```

`SHA256SUMS` contains the lowercase SHA-256 digest and exact filename of each
ZIP, in the order shown above.

The ZIP includes the normal starter kit files plus these files from
`agent-coding-rules`:

- `AGENTS.md`
- `BRANCH_RULES.md`
- `CODING_RULES.md`
- `COMMIT_RULES.md`
- `DOCUMENTATION_RULES.md`
- `LANGUAGE_RULES.md`
- `RELEASE_RULES.md`

The ZIP also includes three provenance files:

- `starter-kit-manifest.json` records the initial and current starter-kit
  releases plus the current core inventory. In a release package, `source`
  and `current` initially identify the same exact tag.

- `_agent-rules-source.json` records the packaged repository, upstream starter
  kit, and agent-rules references and commits.
- `_starter-kit-files.json` records each managed path, raw and canonical
  SHA-256 digests, content kind, Git mode, and upgrade strategy. Schema 3 uses
  `starter-kit-state` for the tracked core manifest.

The upgrade toolkit contains the guarded updater and the complete enriched
package. It can build a cumulative upgrade from the exact earlier package used
to initialize a target repository. Only `git-starter-kit` publishes the
enriched package and upgrade toolkit. `.github/CODEOWNERS`, the release-package
workflow, packaging and upgrade sources, their repository-specific tests, and
package operator documentation are source-only. They are excluded from derived
repository packages.

The package does include the release artifact generator, its manifest template
and schema, the repository-owned hooks, and the tag validation workflow. It
does not include the canonical repository's generated `VERSION`, `SHA256SUMS`,
or `manifest.json`: those three files identify one source release and each
derived repository must generate its own values before its own tag.

For a concise usage procedure in French, see
[Upgrade toolkit](upgrade-toolkit.md).

The cumulative updater classifies the seven rule files and
`_agent-rules-source.json` as `agent-rules`. It never writes the seven rule
files. For `_agent-rules-source.json`, it refreshes only the `repository` and
`starterKit` sections from the new package while preserving `agentRules`,
`preservedFiles`, and other target-owned fields. Each target repository remains
responsible for synchronizing its rule files through its own pull-request
workflow.

Distribution keeps `.github/dependabot.yml` merge-managed and replaces the
complete `tools/quality/` baseline. Repository-specific inventories and
operator documentation remain initialization-only. The repository-audit
dispatcher and modules are replace-managed so cumulative upgrades install the
complete runtime required by hooks and workflows. A downstream change to that
runtime is a blocking conflict and is never overwritten.

When an initialization-only file changed upstream, the plan reports
`review-initialize-only`. The signal does not block or write the target; it
identifies repository-owned content that maintainers should review separately.

## Rule Freshness Gate

The package builder resolves the latest published public `agent-coding-rules`
release exactly once per build. An explicit tag must identify that same latest
release. The immutable upstream tag, commit, tree and seven root blobs are
verified, including Git blob digests. Canonical tracked provenance and rule
bytes must match it; preserved local customizations cannot be packaged as
upstream truth. Declared Markdown CRLF checkout conversion is accepted; the ZIP
stores the exact upstream blob bytes. Offline or unverifiable latest fails.
Synchronize stale canonical rules with the official updater before packaging;
the builder never modifies canonical rule files.

`templates/project/` supplies consumer documentation and Commitlint without the
canonical-only scope whitelist. The shared default project configuration is
initialize-only. Final core state and managed inventories are recomputed after
composition, and the archive's bytes and executable modes are verified. Source
maintenance tests, manufacturing files, migration journals and template inputs
are excluded; required runtime modules and release schemas remain distributed.

No source-repository GitHub App token is required. The read-only `build` job
exposes the built-in workflow token only to the package-builder step, which
uses it when resolving `agent_rules_ref=latest`. After the transferred files
are revalidated, the final `publish` step receives the write-scoped token for
explicit-repository upload and conditional promotion. This public-source
access does not replace the repository variable and secret required by the
common `Agent rules update` release gate.

The `build`, `release-checks`, and `publish` jobs run only when `github.repository` is exactly
`asphyx0r/git-starter-kit`. Only `publish` has `contents: write` and the
`release` environment. It does not check out the repository or execute
downloaded artifact code. The package builder also rejects a different slug or
`origin` as a second identity check.

Runs for the same release tag share one non-cancelling concurrency group. The
tracked `environment: release` boundary does not prove that the corresponding
GitHub environment or its protection rules are configured. Verify those
settings on GitHub after workflow publication. With the sole CODEOWNER
`@asphyx0r`, the CODEOWNERS assignment alone does not provide an independent
human approval. The maintainer explicitly accepts this residual risk under the
single-maintainer model; automated checks and protected branches do not replace
independent human review. Adding a second maintainer is a future governance
decision, not a prerequisite for the current automation.

Before `publish` can start, the read-only `release-checks` job requires successful
`Repository audit` and `Agent rules update` runs from the original `release`
event. It matches the repository, resolved workflow IDs, release SHA, tag, and
release publication timestamp. Push or manual runs cannot substitute for this
evidence. Both checks share a 30-minute deadline; each GitHub query is bounded
to 30 seconds. The verifier is checked out from the workflow's immutable SHA so
manual repair of an older release uses the current workflow's verification code.

## Validation evidence and optimization pilot

This canonical-repository pilot implements the user's approved plan of
2026-10-02 following the local v2.11.5 usage audit. Its behavioral rules live
in the source-only skill extension
`.agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt`.
They apply during authorized execution with the exact canonical HTTPS origin;
bump analysis alone authorizes no mutation. Derived repositories keep the
generic workflow. The extension and this operator guide remain excluded from
distributed packages.

### Source and specification change

The source report is
`codex-usage-release-git-starter-kit-v2-11-5-20261001-01a0f440`, version
`1.0.0`, dated `2026-10-01T21:48:43+02:00`, with declared author `asphyx`.
It is a local draft, marked unreviewed and unpublished, retained under the
ignored `audits/` directory. Its exact-byte SHA-256 is:

```text
da3973499bd5dfc458c7935c8228d6a1852da0cc9709104716403686c759fd46
```

The recommendations are evidence to assess; they do not authorize changes.
The user's subsequent approval is the source of this process specification
change. The four adopted changes are early locked prechecks, explicit evidence
validity, one monitor per execution, and bounded log/resume context. Their
purpose is to detect predictable failures before long suites and reduce
duplicate supplemental work. No runtime behavior, profile, hook mapping,
timeout, generic skill step, release gate, model setting, or package schema
changes. The existing exhaustive audit still blocks release on failure.

### Order and ownership

Prepare the locked environment once before the first long pre-push suite.
Use the existing setup instructions in [Tools](../tools/README.md#prerequisites)
and integrity-verified external tools. Python installation retains
`--require-hashes`; npm retains `ci --ignore-scripts`. Audit commands do not
install tools. CI still uses Python 3.11 on Linux, Python 3.14 on Windows and
`policy.nodeCiVersion` from `tools/quality/versions.json` for Node.js. Record
local differences rather than claiming CI equivalence.

Run these existing commands separately, in order, from the repository root
using that environment; stop on the first failure:

```bash
python -B tools/quality/check-versions.py --runtime
npm audit --audit-level=high --include=dev --prefix tools/quality
bash tools/repository-audit.sh fast
mypy --config-file tools/quality/pyproject.toml --platform linux
mypy --config-file tools/quality/pyproject.toml --platform win32
```

Direct Ruff, Mypy and npm caches into task-owned temporary storage through
`RUFF_CACHE_DIR`, `MYPY_CACHE_DIR` and `npm_config_cache`. These are supplemental
prechecks. The two Mypy targets check static platform branches; they do not run
the Linux and Windows test suites. Changed inputs or environment require
requalification. Follow the generic workflow's stop and retry authorization
rules after a failure.

| Evidence | Owner and validity | Required boundary |
| --- | --- | --- |
| Supplemental read or diagnostic | Operator's temporary ledger; same command, scope, SHA, input hashes and environment | Recheck on any relevant change; mutable external facts require a fresh query |
| Commit and staged checks | Exact message file and indexed snapshot through the existing hooks | Every required commit/index check |
| Pre-push tests | Hook selection at the exact pushed objects; full selection for a new branch | Every required push; 900 seconds per selected family |
| Exhaustive local audit | Operator, exact candidate content and installed environment | Successful complete audit before dependent release operations |
| PR and merged target checks | Guarded merge and exact post-merge audit | Exact PR head and resulting merged SHA |
| CI gate | One prescribed monitor: verifier for its exact tuple, or discovery followed by the required `gh run watch` | Every required run; retain 5-second discovery/verifier polling and existing deadlines |
| Release assets | Existing package verifier and downloaded bytes | Every required asset, digest, provenance and metadata check |

For each command, record its exact scope and command, SHA and hashes of relevant
uncommitted inputs, platform, actual tool versions, lock/configuration hashes,
start/end, exit code, result and full-log reference. Keep full audits, focused
checks, retries, CI and asset verification as distinct entries. A failed full
audit remains failed even when its isolated failing test passes later. Only a
successful full audit supplies the required full-audit evidence.

Keep one owner and session/process handle per local execution. Resume its
existing handle; for a CI gate, retain its prescribed mechanism. Use one
verifier where required, or the existing discovery and `gh run watch` for the
release gates that prescribe it. Keep all selection rules and deadlines;
avoid concurrent outer GitHub polling. Emit new progress, failures and completion, with excerpts
limited by default to 30 lines and 4,000 characters. Retain the full log and
last range read; read additional ranges when diagnosis requires them. A compact
resume record includes objective, authorizations, branch/SHA, valid evidence,
unresolved failures, active handles, log position and temporary artifacts.
Remove only task-owned artifacts and prove cleanup before finishing.

### Historical errors and recovery limits

- `pre-push: affected Python test family timed out after 900 seconds.`
  The hook already enforces 900 seconds. The former 180-second statement in
  `CONTRIBUTING.md` was stale documentation. Check the selected family,
  elapsed time, environment and log before an authorized retry; a timeout
  supplies no passing test result. This pilot does not increase the limit.
- `tools\backup-target-directory.py:581: error: Module has no attribute
  "WinDLL"  [attr-defined]` was corrected in v2.11.5 by guarding the Windows
  API call with the platform check. The existing backup implementation owns
  that correction; the two Mypy prechecks detect platform typing failures
  earlier without changing backup behavior again.
- `OSError: [Errno 22] Invalid argument:` occurred while creating the
  `tools/quality/node_modules/.bin/commitlint.cmd` fixture in
  `tests.test_git_init.InitializerTests.test_commitlint_and_commit_failures_never_create_a_tag`.
  Later isolated runs passed, but do not prove the underlying cause or turn
  that full audit green. Preserve the traceback, reproduce with the locked
  environment, diagnose fixture/path access, and obtain a successful complete
  audit after any authorized correction. No deterministic fix is claimed.
- The v2.11.5 npm security correction was already applied to the locked
  dependencies. An early `npm audit` checks current advisories; a previous green
  result cannot establish the current state of the external advisory service.

The spelling profile runs `codespell --config .codespellrc .`; unlike Markdown
lint, it does not use Git's ignored-file selection. A local ignored French
report can therefore stop a working-tree audit with a diagnostic such as
`recommandations ==> recommendations`. <!-- codespell:ignore recommandations -->
Preserve that report and the failed
audit result. To validate the tracked candidate without changing local data or
scanner policy, use a disposable clone with the same history and canonical
origin, copy the tracked candidate bytes and verify every file's SHA-256, then
run the unchanged complete profile with the locked environment. Record this as
separate evidence for that tracked candidate; it does not make the original
working-tree audit successful or waive any later mandatory gate. Remove the
task-owned clone after verification. A scanner-policy change requires its own
analysis and approval.

The historical functional corrections are recorded in `CHANGELOG.md` under
v2.11.5. This pilot changes their detection and evidence handling, not their
implementation. Historical report totals are a baseline, not a savings
guarantee or a new billing calculation.

### Pilot acceptance and measurement

Before acceptance, verify that a precheck failure stops dependent work, a
focused success does not erase a full failure, changed revision or environment
invalidates affected supplemental proof, a wrong/failed CI run cannot be
replaced by another green run, and resumption attaches to existing handles.
Check the ordinary hooks and packaging contracts as well as documentation.
Record counts and elapsed time for full-suite attempts, targeted retries,
monitor queries, log reads and emitted output, with the same counting scope
for any comparison. Do not promise a percentage reduction from this pilot.
Manual acceptance and an explicit commit request remain separate user gates.

## Automatic Release Mode

Use this mode for the normal release process.

1. Prepare the release commits and changelog in `git-starter-kit`.
2. Prepare `starter-kit-manifest.json` for the exact selected tag with
    `tools/starter-kit-manifest.py`, then commit only that release metadata.
3. Resolve every release-manifest value from verified evidence, ask the user
    only for unresolved or contradictory values, obtain explicit validation,
    then generate and commit exactly `VERSION`, `SHA256SUMS`, and
    `manifest.json`. Whenever the Git index changes any release-identification
    artifact, the pre-commit hook validates the complete indexed release state.
    Normal generation stages all three files. A coherent correction may stage
    only `SHA256SUMS` and `manifest.json` when `VERSION` is unchanged.
4. From a clean repository, run `bash tools/repository-audit.sh` locally.
5. Stop if the local audit fails; do not create a release tag or release.
6. Create and push the release tag, for example `v1.3.0`.
7. Require the tag-only `Release artifacts` workflow to succeed.
8. On GitHub, open the repository page.
9. Open **Releases**.
10. Create a new release from the tag.
11. Mark it as a prerelease and do not mark it as latest.
12. Publish the prerelease.

After the prerelease is published, GitHub starts the `Release package`
workflow automatically. Automatic releases intentionally use `latest` so the
package always includes the latest published full `agent-coding-rules`
release.

The workflow then:

1. Checks out `git-starter-kit` at the published release tag without persisting
    credentials.
2. Configures Python 3.11 and Node.js 24.20.0 with download caches keyed by the
    lockfiles and runtime policy, then installs each locked quality environment
    once with hash verification and disabled npm lifecycle scripts, including
    `markdownlint-cli2` 0.23.3.
3. Resolves `latest` to the latest published full `agent-coding-rules` release.
4. Verifies that the tracked core manifest, provenance, and rule hashes match
    the resolved tag.
5. Copies the core paths declared by the tracked manifest, except
    source-repository-only packaging files, into a temporary package folder.
6. Retains the seven tracked rule files in that package folder.
7. Writes validated provenance and the schema 3 managed-file manifest.
8. Creates and validates the enriched ZIP with the already installed Markdown
    and Codespell tools.
9. Bundles the guarded updater and complete package as an upgrade toolkit.
10. Seals both ZIPs and the exact two-line `SHA256SUMS` file as the only three
    regular files in one inter-job artifact.
11. Requires both successful release-event checks for this exact release.
12. Downloads and revalidates those three files in `publish`, before exposing
    its token.
13. Uploads the three explicitly named release assets without overwriting an
    existing asset.
14. For a published prerelease only, promotes it as the final command after a
    successful upload.

The release is complete only when this exact `release.published` workflow run
finishes with `success`, the release is no longer a prerelease, and both ZIPs
plus `SHA256SUMS` have been verified. A manual workflow run does not satisfy
this completion gate.

When the workflow finishes, the GitHub release should show an asset such as:

```text
git-starter-kit-v1.3.0-with-agent-rules.zip
git-starter-kit-v1.3.0-upgrade-toolkit.zip
SHA256SUMS
```

Download the `with-agent-rules.zip` asset when you want a ready-to-use starter
kit with agent rules already included.

## Manual Release Mode

Use this mode when you need to create or recreate the enriched package for an
existing release.

The release must already be published on GitHub before running the workflow
manually, with successful original `release` runs for both required workflows.
The `tag` input must be an existing GitHub release tag that uses SemVer with a
leading `v`, for example `v1.3.0`. The manual workflow uploads both ZIPs and
`SHA256SUMS` to that release; it does not create the release itself.

Manual runs never promote a prerelease. If an automatic release run failed,
rerun the failed jobs of that same `release` run after correcting the cause.
Do not substitute a `workflow_dispatch` run for the automatic completion gate.

1. Open the `git-starter-kit` repository on GitHub.
2. Open the **Actions** tab.
3. Select the **Release package** workflow.
4. Click **Run workflow**.
5. Fill in `tag` with the release tag to package, for example `v1.3.0`.
6. Fill `agent_rules_ref` with `latest` or a SemVer `agent-coding-rules` tag,
    matching the latest published upstream release.
7. Click **Run workflow**.

Manual release packages accept `latest` or the same latest published SemVer tag.
Explicit older rules tags are rejected; old published assets stay immutable.
Branch names are still rejected so the generated asset stays reproducible.

When the workflow finishes, open the GitHub release page for the tag and check
that both ZIPs and `SHA256SUMS` are listed under the release assets.

## Local Test

Run the full repository audit locally before publishing a release:

```bash
bash tools/repository-audit.sh
```

The full audit uses the active locked Python and npm quality environments; its
release-package smoke test does not reinstall them. It intentionally resolves
the latest published full `agent-coding-rules` release. Treat a failure to
resolve or validate that release as an audit failure before publishing. Use
`markdown`, `spelling`, or `static` when you need to isolate one audit family.

You can also test only the package generation locally before publishing a release.

From the repository root, run:

```powershell
powershell -NoProfile -File tools\build-release-package.ps1 `
  -RepositorySlug asphyx0r/git-starter-kit `
  -RepositoryRef local-test `
  -OutputDirectory .tmp\release-package-test `
  -PackageName test-release-package.zip
```

Inspect the generated ZIP:

```powershell
tar -tf .tmp\release-package-test\test-release-package.zip
tar -xOf .tmp\release-package-test\test-release-package.zip _agent-rules-source.json
tar -xOf .tmp\release-package-test\test-release-package.zip _starter-kit-files.json
```

The local test creates a ZIP only. It does not upload anything to GitHub.
`AgentRulesRef` defaults to `latest`; pass a SemVer tag only when you need to
assert the same latest published agent-rules release. The argument validates
tracked content against immutable upstream bytes before composing the archive. The repository root must use
the canonical `git-starter-kit` HTTPS `origin`.

The script copies files reported by `git ls-files`, except the explicit
source-repository-only packaging files. Local untracked files are not included
in the package. This is intentional, because release packages should be built
from committed repository content.

## Troubleshooting

If a release asset is missing, open the **Actions** tab and inspect the latest
`Release package` workflow run. The publish step does not overwrite an existing
asset.

If a release remains a prerelease, inspect the matching run triggered by the
`release` event. The run must match the release tag and tag commit and must end
with `success` before the release is complete.

If the manual workflow fails, check that the `tag` input matches an existing
GitHub release tag using SemVer with a leading `v`.

If the final promotion command fails, inspect the `publish` job of that same
automatic run. Do not substitute a manual run for the automatic completion
gate.

To assert the latest upstream version explicitly, use its SemVer
`agent_rules_ref` value. Older versions and unverifiable latest metadata fail
the build; existing published assets must remain immutable.
