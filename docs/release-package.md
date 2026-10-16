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
settings on GitHub after workflow publication. Configure the canonical
repository's environment without required reviewers or a wait timer, with
administrator bypass disabled and deployment policies restricted to branches
`main` and `master` and tags `v*`. Keep the environment attached to `publish`.
This removes the manual `Review deployments` step while retaining all automated
release checks. With the sole CODEOWNER
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
python tools/quality/npm-security.py audit
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

## Controlled CI qualification

The remediation plan approved on 2026-10-16 adds this narrow exception to the
earlier validation pilot. It applies only to `asphyx0r/git-starter-kit` with
`repositoryRole: source`. Local `all`, `full` and `static` remain exhaustive,
in the order static checks, Python coverage, shell behavior, smoke and Commitlint.

A successful full default-branch push can supply an original Linux/Windows
qualification for the exact same commit on a SemVer tag push or a published
release. PRs, manual runs, preparation branches and application consumers run
their normal complete qualifications. Equal trees with different commit SHAs
are insufficient.

The normal qualification has seven jobs: activation and candidate resolution,
two fresh OS preflights, one common decision, two conditional heavy OS jobs, and
the required aggregate. One decision controls both heavy jobs. The aggregate accepts either
the verified original pair or both successful current heavy jobs. The required
check names remain `Repository audit` and `Repository audit (manual)`.

| Always fresh for the current event | Reusable only as one original pair |
| --- | --- |
| Ref/SHA, commit ranges and messages, tag manifests and trusted activation | Complete Python suites with raw branch coverage, reports and actual test counts |
| Secrets and dependency vulnerability audits, static/config/runtime/workflow checks | Six Linux shell suites and the two focused Windows hook suites, with status, logs and durations |
| Smoke and mutable network/latest resolution; declared project checks on both OSes | Original producer identities and actual heavy-job environments, without relabeling |

Candidate resolution selects the newest eligible default-branch producer before
examining its result. A newer failed or pending producer prevents selecting an
older green one. The producer must be a completed successful push at the exact
SHA, in the canonical repository and expected workflow. Its original date is
valid for at most seven days; the artifact retention is also seven days.
Consumers never become producers or refresh that date.

The source-only `tools/quality/qualification.py` helper exposes three CI commands:

- `resolve` records an immutable candidate run, attempt and artifact identity.
- `verify` compares the packet with both fresh environments and emits one
  `reuse` or `full` decision with a reason.
- `seal` prepares a packet only after a full eligible producer qualification.

The packet retains the original two OS measurements, test/shell results,
reports, file hashes and environments. Verification binds the workflow and
trusted validator, quality policy, `tools/quality/requirements.lock` and
`tools/release-artifacts-requirements.txt`, npm lock,
version registry, effective tool versions and both hosted image versions. Heavy
environment facts are captured around the actual heavy execution and compared
with the fresh preflights. A successful producer whose environments differ can
remain a successful audit without supplying an admissible reuse packet.

Missing, expired, ambiguous, altered or unverifiable proof before the common
decision selects both current full qualifications. This includes API errors
and proof lost after candidate resolution. Loss after the common reuse decision
fails the aggregate; rerun all jobs to resolve again. It never turns skipped
heavy jobs into successful proof.

The aggregate recalculates the existing Linux and combined global and branch
floors from the raw measurements: each required score must reach 85%. A green
producer status alone is insufficient. Original run/attempt metadata is
preserved. Ordinary current-run coverage still requires a matching Linux/Windows
pair from the same attempt; operators must not edit identities or mix old and
current OS data.

This helper and its protocol are source-only. Exported application workflows
continue to work without it and execute their own checks on both OSes. It does
not authorize a push, release, protection change or bypass of a release gate.
Hosted savings require measurement of a complete release sequence, including
fallback overhead; local simulations alone do not establish that gain.

### Accepted F14 experiment

On 2026-10-16, the user accepted an experimental closure criterion for F14 in
place of the original real release-sequence measurement. This acceptance does
not change production eligibility or authorize a merge, tag or release.

Use the existing manual workflow on the dedicated PR branch with the boolean
`qualification_experiment` input enabled. Ordinary runs retain their seven
qualification jobs. Two additional job definitions, disabled by default,
measure three isolated samples on each OS and verify their combined results.
Their token permissions remain read-only.

```powershell
gh workflow run repository-audit.yml `
  --repo asphyx0r/git-starter-kit `
  --ref codex/audit-remediation-2026-10-16 `
  --field qualification_experiment=true
```

Freeze the harness commit for the entire series. Its normal full Linux/Windows
qualification supplies the real warm-up and original paired measurements.
Each sample must observe the same effective tools, locks and hosted image as
that qualification, before and after its own execution. Record cache hits and
misses and retain the setup cache regime; never clear a shared cache to obtain
a preferred result.

The source-only `tests/qualification_experiment.py` harness calls the unchanged
`resolve`, `seal` and `verify` functions with an injected API. Only that fixture
simulates an eligible default-branch producer and tag consumer, including the
completed producer state required while the real manual run is still running.
It supplies the harness commit as the simulated trusted default-branch tip and
creates an unpublished artifact envelope; it does not attest the real `main`
trust relationship.
The receipt retains the real manual event and the simulated fields separately.
No production packet is published. Original coverage bytes, source hashes,
run, attempt and producer date remain intact.

Every sample exercises these cases:

| Case | Required observation |
| --- | --- |
| No proof | Common `full` decision, followed by the real complete native Python and shell suites |
| Valid original pair | `reuse`, unchanged original identity, date and packet files, with no heavy-suite execution |
| Invalid proof before decision | Common `full` decision, followed by the same complete native suites |
| Proof lost after a reuse decision | Aggregate validation refuses the incomplete pair; no partial success |

The final experimental aggregate requires all six samples, pairs their current
environments, recalculates raw full and fallback coverage, and enforces all
four existing 85% floors. Missing samples, failures, environment drift, mixed
commits or attempts invalidate the series. Keep failed attempts distinct.

Report measured component times per OS with the median and range of the three
samples. Count the original producer once when assembling the two-consumer
comparison: `P + 2 * median(full)` versus
`P + median(tag reuse) + median(release reuse)`. Compute the paired OS maximum
and sum before each median; the result is a sum of component medians, not a
median of complete sequences. Report invalid-proof fallback
overhead separately. These are assembled component costs, not observed
end-to-end release wall time or billed runner seconds. Real API latency,
release orchestration and future image/cache changes remain outside that
estimate. Report actual workflow/job durations separately from component
measurements, including setup and scheduling where applicable.

Retain experimental artifacts for seven days and record their SHA-256 hashes,
run/attempt, original pair, measured environments, test/skip counts, shell
outcomes and four coverage results in a durable report. Close F14 under this
accepted alternative only after every scenario and floor passes. A later
documentation commit must not be presented as the measured source commit.

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
release. With the environment policy above, the remaining jobs run without a
human approval. A failure in ZIP generation, integrity validation, required
release checks, or asset upload prevents promotion to stable/latest. Resolve
the failure and rerun the original release-event workflow; do not bypass the
checks to force promotion.

If the required `Repository audit` run fails, choose **Re-run all jobs** on
that original release-event run. Its Linux and Windows coverage must come
from the same attempt. Retrying only one failed OS job can leave an older
artifact for the other OS, which the aggregate refuses. This differs from
retrying failed jobs of the original `Release package` run; neither retry
may be replaced by an unrelated manual run or edited coverage metadata.

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
    SemVer contents, templates and modes come from the selected `HEAD`, with
    its explicit CRLF text attributes and existing canonical-checkout checks.
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
13. Compares all remote assets before any mutation: reuses identical uploaded
    files, uploads only missing files, and refuses changed, duplicate or
    unexpected assets. An absent digest is verified by streaming the asset by
    ID; a malformed digest blocks publication. Only a confirmed empty `starter`
    residue may be deleted by its exact ID before retrying that upload.
14. For a published prerelease only, promotes it as the final command after a
    fresh release-identity check and verification of all three remote assets,
    including `SHA256SUMS`. An already stable release is never downgraded.

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

For SemVer releases, the script reads contents and modes from the selected
`HEAD`, excluding source-only files. Local previews retain indexed paths and
modes with their local file contents. Untracked files are excluded.

## Troubleshooting

If a release asset is missing, open the **Actions** tab and inspect the latest
`Release package` workflow run. Retry the original run: publication reuses
identical assets and sends only missing ones. A mismatch blocks the retry;
inspect its diagnostic without deleting or overwriting a valid asset.

If a release remains a prerelease, inspect the matching run triggered by the
`release` event. The run must match the release tag and tag commit and must end
with `success` before the release is complete.

If the manual workflow fails, check that the `tag` input matches an existing
GitHub release tag using SemVer with a leading `v`.

If the final promotion command fails, inspect the `publish` job of that same
automatic run. Do not substitute a manual run for the automatic completion
gate. A retry verifies the retained assets again before promotion.

To assert the latest upstream version explicitly, use its SemVer
`agent_rules_ref` value. Older versions and unverifiable latest metadata fail
the build; existing published assets must remain immutable.
