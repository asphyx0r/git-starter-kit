# Audit Remediation Evidence

## Scope and Status

This record tracks the nineteen findings from the 2026-10-12 audit and the
[approved implementation plan](../plans/2026-10-12-audit-remediation.md).
It records local implementation and activation evidence as of 2026-10-13. It does not close
findings that still require candidate qualification, integration or live settings.

The original base is `bace76a55c165d18b67bdc9e25b224dc725d4286`. Work is isolated on
`fix/audit-remediation`. Published history and unrelated repositories are preserved.
The proposed candidate is `v2.12.0`; the published baseline remains `v2.11.7`.
No primary tag or GitHub Release has been performed. Authorized remote settings
were activated after the local candidate; publication and hosted proof remain
separate gates.

## Local Deliverables

| Commit | Responsibility |
| --- | --- |
| `9d2af9e` | Locked dependencies, attested braces fix, security gates and provisioning |
| `a310134` | Interrupted output restoration, early tag validation and Mypy scope |
| `2688bd2` | Focused workflow execution and security contracts |
| `c94aa08` | Affected Python/shell test selection across pushed revisions |
| `b9c513f` | Indexed runtime preflight and actual executable version checks |
| `900d77c` | OS coverage artifacts, folded project checks and push cancellation |
| `235c5ff` | Caller-safe coverage reporting and expanded coverage/security regressions |
| `61f08f3` | Offline npm fixtures and precise fixture routing |
| `43ef0d9` | Isolated shell metadata and actual host CLI selection |
| `77cf5dc` | Bounded Windows fixture cleanup with persistent-error regressions |
| `e4ca84c` | Reject incomplete guarded activation; preserve permissions and document administrative bypass verification |

Behavior changes include their tests and relevant source/consumer documentation.
Future commits continue this separation; no historical commit is rewritten.

## Finding Ledger

"Local" means the implementation and focused verification exist. Every local
finding still depends on the final candidate checks below.

| ID | Axis | Implementation and evidence | Remaining proof |
| --- | --- | --- | --- |
| 01 | 2 | Local braces walkers, exact upstream provenance and attestation gate; 18 security tests and 3,315 differential API cases | Exact-candidate dependency audit and distribution |
| 02 | 6 | Local preflight rejects incomplete rules/settings; owner supplied App ID 4355746; separate main restriction activated as ruleset 24996187 | Administrative bypass audit and disposable-PR proof |
| 03 | 2 | smol-toml 1.9.1 pinned in registry/overrides/lock; installed occurrences checked | Candidate audit and integration |
| 04 | 3 | Output rollback handles interrupts and independent cleanup/restoration failures; 48 release tests | Candidate full suite |
| 05 | 3 | Shared SemVer validation precedes initializer writes/index changes; 19 initializer tests | Candidate full suite and package initialization |
| 06 | 1 | Initializer/new tools in Mypy; tracked-tool coverage invariant; 24 files checked for both platforms | Candidate typing and scope checks |
| 07 | 1 | Source Windows measurement plus matched OS artifacts; artifact regressions cover input identity, OS paths and caller measurement isolation | Complete OS measurements and combined floors at the candidate |
| 08 | 4 | v2.12.0 metadata/checksums prepared after substantive changes; both selected-index checks passed | Final commit checks and exact-candidate package qualification |
| 09 | 5 | Broken environment rebuilt; pinned local tools provisioned; selected real executables checked against indexed pins | Candidate hooks and runtime qualification |
| 10 | 6 | Registry, declarations and hashed locks updated coherently; maintenance procedure documented | Integration and coordinated future bot proposals |
| 11 | 6 | Single-maintainer review exception accepted; release reviewer asphyx0r configured with self-review allowed | Disabled admin bypass and live gate proof |
| 12 | 5 | Focused pre-commit/pre-push suites selected with shared conservative fallback | Candidate pre-push qualification |
| 13 | 2 | KaTeX 0.18.2 override checked against the lock and installed tree; real Markdownlint runs pass | Candidate dependency and CLI checks |
| 14 | 4 | Local commits separate responsibilities; code/tests/docs accompany behavior | Final branch review and evidence completeness |
| 15 | 6 | pip-audit added for both hashed Python locks; real scans reported no known vulnerabilities | Candidate CI security gates |
| 16 | 5 | Isolated test changes select their own family; shared paths retain complete tests | Candidate routing and consumer checks |
| 17 | 6 | Project checks execute in both existing OS jobs; standalone jobs removed; aggregate rejects each failed/cancelled/skipped input | Source and consumer hosted execution |
| 18 | 6 | Ordinary pushes grouped by ref; release/preflight/manual evidence retained; negative contract tests pass | Hosted cancellation and event evidence |
| 19 | 1 | Named script seals and explicit boundaries replace copied bodies; 49 workflow tests pass on Python 3.11 and 3.14 | Candidate full contracts and review |

## Verified Checks and Limits

- Windows Python 3.14.8 and WSL Ubuntu Python 3.11.17 used the hashed quality lock.
  The portable Linux interpreter archive matched its published GitHub SHA-256.
  Node 24.20.0 for Linux matched the official Node checksum. Initial Windows
  provisioning used Node 26.5.1; current qualification uses Node 26.8.1.
- Both actual OS runtimes passed 49 workflow-contract tests and 16 coverage-artifact
  tests. Linux passed the ten coverage-policy tests. Windows passed twenty manifest
  tests and the two strict package-distribution cases.
- The complete repository-audit dispatcher/profile behavior suite passed. The
  `--focused-orchestration` argument used during that run is ignored by the script;
  the result covers the complete suite, not a special focused mode.
- The full Windows Coverage run was stopped after failures; 297 of 574 test markers
  were observed, with no usable final coverage report. Two distribution expectations
  were corrected. The initializer/process cases passed a focused replay and a
  second replay under Coverage. Their intermittent full-run failures remain a
  qualification concern. A later complete run passed all 585 tests; final candidate
  qualification remains required after the outstanding guard changes.
- Python 3.11 exposed different empty-list AST dump defaults. The compatibility
  regression failed first and then passed; existing workflow script seals were kept.
  Windows 3.14 exposed unclosed in-memory SQLite connections. A ResourceWarning
  regression failed first; both CoverageData objects now close in `finally`.
- Pinned Ruff, both Mypy target platforms, ShellCheck, shfmt, Actionlint, Yamllint,
  PSScriptAnalyzer and affected Markdown guides passed. Git integrity checks passed.
  Betterleaks failed before scanning with Windows `NUL`; the prescribed staged
  Gitleaks fallback passed. No scanner allowlist was introduced.

## Subsequent Linux Qualification

A native Linux workspace was provisioned with verified Python 3.11.17,
Node 24.20.0, PowerShell 7.6.6 and the five locked external tools. Its initial
clone matched `9fc0fe8`. The complete runtime preflight passed. The first
suite attempt exposed Windows PowerShell inherited through WSL's PATH; the
qualification environment was restricted to native tools, matching Ubuntu CI.

All 577 Python tests then passed with ten platform skips. Coverage still failed:
the measurements contained 10,757 arcs, but reported zero because nested report
generation changed Coverage's global relative directory. A regression reproduced
that caller-state change before the fix. Report generation now uses an explicit
source root without changing directories. Eleven artifact tests pass on Windows;
the instrumented Linux replay measures 90 helper lines and preserves paths.
That replay passed 578 tests with ten skips. The global score was 88.59%, but
branch coverage was 84.65%, below the preserved 85% floor. Additional tests now
exercise runtime-version rejection, platform validation, destination preservation,
malformed metadata, CLI failure reporting, npm dry-run and untrusted-byte rejection.
The expanded Linux suite passed all 585 tests with ten skips in 210.298 seconds.
Coverage is 89.39% globally (6,894/7,712) and 85.38% for branches (1,875/2,196).
No production source was excluded and no threshold was lowered.

The Linux skips were:

| Test | Reason |
| --- | --- |
| `test_windows_junctions_abort_before_copy` | Windows junction fixture |
| `test_cloud_archive_integrity_collision_and_cleanup` | No authorized mounted-cloud integration target |
| `test_windows_archive_succeeds_when_hard_links_are_unsupported` | Windows publication behavior |
| `test_short_alias_roots_preserve_composition_paths` | Windows short paths |
| `test_successful_build_replaces_destination_with_windows_powershell_5_1` | Windows PowerShell 5.1 |
| `test_inventory_directory_junction_outside_target_is_refused` | Windows directory junction |
| `test_short_alias_inventory_stays_confined` | Windows short paths |
| `test_junction_escape_is_rejected` | Windows directory junction |
| `test_target_rejects_existing_junction_before_reading` | Windows junction regression |
| `test_windows_mode_only_difference_does_not_schedule_repair` | Windows mode-enforcement contract |

## Subsequent Windows and Combined Qualification

The complete Windows suite passed all 585 tests with nineteen skips in
906.429 seconds. Coverage is 89.55% globally (6,906/7,712), 91.23% for statements
(5,032/5,516), and 85.34% for branches (1,874/2,196). The same 85% global and
branch policy passed independently for Linux and Windows.

Both data sets were exported and combined with the real artifact CLI. Source
digests, policy, locked Coverage version and matching fixture identities were
checked. Windows and Linux renderers both reported the same union: 90.62%
globally (6,989/7,712), 92.02% for statements (5,076/5,516), and 87.11% for branches
(1,913/2,196). The native clone now points to `235c5ff`; its previously overlaid
source/test files were verified byte-for-byte against that commit before checkout.

These are local measurements of the production/test bytes in `235c5ff`, collected
before the commit was created. Artifact run/attempt `1` are explicit local fixture
identities, not GitHub Actions evidence. They do not establish final candidate or
hosted qualification. The remaining substantive guard changes require a new final
candidate qualification.

The Windows skips were:

| Test | Reason |
| --- | --- |
| `test_source_tree_symbolic_link_is_rejected` | Windows symlink privilege unavailable |
| `test_cloud_archive_integrity_collision_and_cleanup` | No authorized mounted-cloud integration target |
| `test_linux_unsupported_hard_links_fail_without_final_archive` | Linux publication behavior |
| `test_missing_setsid_fails_before_launching_git` | Unix process-session prerequisite |
| `test_generated_output_symlink_is_refused_before_writing_outside_target` | Linux symlink fixture |
| `test_static_context_rejects_real_file_symlink` | Windows symlink privilege unavailable |
| `test_symlink_escape_is_rejected_even_with_missing_descendants` | Windows symlink privilege unavailable |
| `test_cwd_symlink_escape_is_rejected` | Windows symlink privilege unavailable |
| `test_real_symlink_roots_are_rejected_when_supported` | Windows directory symlink privilege unavailable |
| `test_failed_or_ineffective_chmod_rolls_back` | POSIX executable permissions |
| `test_failed_write_restores_exact_posix_mode` | POSIX file modes |
| `test_later_write_failure_restores_mode_only_update_exactly` | POSIX executable permissions |
| `test_matching_git_mode_leaves_custom_execute_bits_unchanged` | POSIX executable permissions |
| `test_mode_only_drift_preserves_initialize_only_and_delegated_files` | POSIX executable permissions |
| `test_mode_only_update_enables_execution_and_saves_rollback` | POSIX executable permissions |
| `test_mode_only_update_preserves_accepted_merge_customization` | POSIX executable permissions |
| `test_mode_only_update_preserves_crlf_bytes` | POSIX executable permissions |
| `test_mode_only_update_removes_execution_and_preserves_other_bits` | POSIX executable permissions |
| `test_permission_change_after_planning_blocks_application` | POSIX executable permissions |

## Package Preview Qualification

The native package builder succeeded from the exact `235c5ff` checkout with a
read-only verification of the latest upstream rules `v1.42.0`. The temporary
`preview-235c5ff` ZIP contains 100 files. Eleven security/runtime inputs, including
both Python locks, npm pins, the security gate and the six braces patch/license
files, match the source bytes. Source tests, remediation records, installed
dependencies and the source-only coverage helper are absent as required.
The extracted consumer passed the real initializer's `validate` command.

Its SHA-256 is
`3a42abd12e62e5aa020b1d44bbf2ac5ed3ad21b5b2d7aad68cd277d0a6037999`.
This preview uses a non-release ref. It proves distribution and consumer
validation for those bytes; it does not prove SemVer-tag packaging, final release
metadata, initialization, cumulative upgrades or restoration. Those checks remain
part of the exact final candidate gate.

Primary `HEAD` still fails both release checksums and the starter core inventory.
An artifact preparation dry run succeeds, but no primary metadata has been
regenerated while the remaining substantive guard work is undecided.

## Isolated Pre-Push Regression

A complete Windows pre-push simulation of `235c5ff` failed thirteen npm test
setups among 585 tests in 849.808 seconds. The isolated pushed clone has no
`node_modules`; those setups incorrectly copied the prepared checkout's braces
package. The failure occurred within the unchanged 900-second family deadline.
No push was performed, and shell/workflow families were not reached.

A new regression reproduced the dependency on a checkout installation before
the fix. The suite now reconstructs braces and its three actual dependencies from
four exact upstream archives, verifies their locked SHA512 values and confines
extraction to its temporary tree. The three added fixtures total 16,932 bytes,
include their upstream MIT licenses and remain source-only. Hook routing includes
each fixture in the npm suite; hooks still install nothing. All eighteen npm
tests pass on Windows and Linux without a checkout dependency tree. A complete pre-push
replay of the correction remains required.

At the exact `61f08f3` commit, Linux passed all 586 tests with the same ten
platform skips in 254.379 seconds. Its global and branch coverage remained
89.39% and 85.38%, respectively. Both OS fast profiles passed: 44 Python files
formatted and 24 production files accepted by Mypy. They explicitly warned that
the canonical project has no configured application checks; these results do
not establish consumer application or hosted validation.

The complete Windows pre-push replay passed its 586 Python tests with nineteen
skips in 772.071 seconds, within the unchanged 900-second deadline. Its shell
phase then failed when the message-validation fixture copied installed package
metadata from the dependency-free clone. A separate remaining-family run exposed
a second assumption: the real Markdown case forced a CLI path inside that clone.

The message suite now always clones its source without dependencies, seeds test
metadata from the tracked lock and invokes the actual locked host Commitlint.
The Markdown fixture preserves the actual selected host CLI before isolating
repositories. Both regressions were observed before correction. The complete
message suite and the pre-commit/pre-push suites pass on Windows and Linux,
including indexed content/configuration, exact pushed identities, failure
propagation and cleanup. The Windows remaining suites ran through the production
family executor in a clone with no `node_modules`. Its 900-second deadline was
preserved. These component results do not replace the complete corrected hook
replay or final candidate qualification.

The complete replay of `43ef0d9` then stopped after 586 Python tests in
722.191 seconds: one error occurred in cleanup of the concurrent-backup fixture,
with nineteen existing skips. The production backup source and its test body
matched the original audit base. Publication assertions passed and both executor
workers had finished; the residual target directory was empty. The same cleanup
error reproduced at iteration 58 under Windows Python 3.14 and iteration 187
under Python 3.11. Subsequent empty-directory removal succeeded.

The fixture now retries only `WinError 145`, at most three times with two 10 ms
waits. A regression failed before that change; persistent error 145 and all other
cleanup errors still propagate unchanged. Production backup behavior, test
assertions and family deadlines are preserved. All 48 backup tests pass on both
OSes, with three individually applicable platform/capability skips. The unchanged
concurrent-publication assertions and corrected fixture cleanup also pass 1,000
times on each Windows interpreter. The full corrected pre-push remains required.

Windows documents deferred deletion until the final handle closes. The observed
empty-directory cleanup failure is consistent with that behavior; the handle
holder was not identified. This is a bounded test-fixture correction, not evidence
of a production publisher leak.
[Windows deletion semantics](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew).

## Complete Hook Qualification at `77cf5dc`

The real Windows pre-push wrapper completed with exit status zero for the exact
`77cf5dcf71ef229191e151672bd83be9cdd0873f` revision against the original audit base.
It used an isolated pushed-object clone without dependency installation. All
588 Python tests passed with nineteen previously explained skips in 745.571
seconds. All four mandatory shell suites, real Actionlint/workflow contracts and
the project runner completed successfully. Each family kept its 900-second
deadline. The canonical project explicitly warned that no application checks
are configured; this result does not claim application or hosted validation.
The simulated input did not perform a push.

At the same exact commit, the complete Linux Coverage suite passed 588 tests
with ten previously explained skips in 200.047 seconds. Coverage remained
89.39% globally (6,894/7,712), 90.99% for statements (5,019/5,516), and 85.38%
for branches (1,875/2,196). Both preserved 85% floors passed. The Windows coverage
and combined measurements above remain their earlier, separately identified
proofs; the plain Windows pre-push run did not collect new coverage.

These local results close the observed qualification regressions at this
revision. The substantive guard choice, regenerated final metadata, complete
candidate profiles/packages, final OS measurements and hosted activation are
still required. No final candidate or nineteen-finding completion is claimed.

## Governance Work Still Open

Live reads still show all repository merge methods enabled, no update restriction
on main, and no release reviewer. Release admin bypass is enabled. The ordinary
main ruleset remains active with required checks/conversation resolution and zero
required independent approvals. These settings have not been changed.

The owner supplied numeric App ID `4355746` for `agent-coding-rules-sync` on
2026-10-13. This is owner-provided identity evidence, not an independently
confirmed API response. The public client ID and bot account ID remain distinct
identifiers and cannot substitute for it.

GitHub documents that ruleset bypass actors can be omitted when the requesting
token lacks write access to the ruleset. The existing workflow starts with read
permissions, then mints an App token limited to contents/pull-request writes.
The owner chose to preserve these permissions and audit complete bypass lists
administratively at activation. The local preflight checks active rules and
merge methods without asserting bypass visibility. Missing actor data is not
proof of an empty bypass list. Re-audit the complete lists after any governance
change; no automatic administrative identity is added.
[GitHub ruleset API](https://docs.github.com/en/rest/repos/rules#get-a-repository-ruleset).

### Proposed Settings

These are reviewable targets, not applied changes. The owner supplied the App
identity and selected administrative verification at activation. Applying these
settings still requires separate authorization and live verification.

| Setting | Current | Proposed |
| --- | --- | --- |
| Repository merge methods | Merge, rebase and squash enabled | Squash enabled; merge/rebase disabled; auto-merge stays disabled |
| Main ordinary protections, ruleset `23177592` | Checks/conversation resolution, zero approvals, no bypass | Preserve these controls; allow only squash in the pull-request rule |
| Main update restriction | Absent | Separate active branch ruleset for `refs/heads/main`, only `update`, fetch/merge bypass disabled, sole `Integration` actor `4355746` with `always` bypass |
| Release reviewer | None | Required human reviewer `asphyx0r`, verified User ID `83057672`; self-approval allowed for the accepted single-maintainer policy |
| Release admin bypass | Enabled | Disabled |
| Release reference restrictions | Branches `main`/`master`, tags `v*` | Preserve these existing policies |
| Workflow credential boundary | Read-only first pass; limited existing App token afterward | Preserve it; audit complete bypass lists with administrative access at activation and after governance changes |

Read-only API refresh after receiving those answers still returned the current
settings above, including ordinary main ruleset `23177592` with no bypass,
all three merge methods, zero required independent approvals, and release
admin bypass enabled. No remote setting was changed.

### Local Activation Guard

New negative tests reproduced acceptance of missing update restrictions,
fetch-and-merge permission, shared protection/update rulesets, unverifiable
rule provenance and unsupported repository/pull-request merge methods. The red
run had 21 failing assertions across eleven tests. After the correction, all
79 guarded merge CLI tests passed. The requester, read-only execute pass and
privileged execute pass each reject incomplete activation before mutation.

The gate uses the effective active-branch-rules endpoint and repository metadata;
it needs no administrative permission and does not claim to verify bypass actors.
The workflow, App-token scope, immutable checkout and script seals are preserved.
These local tests do not replace the pending activation/disposable-PR proof.

The local guard commit `e4ca84c` passed its active pre-commit and commit-message
hooks, the configured Ruff checks, Mypy for all 24 production files, Markdown
validation and all 49 workflow-contract tests on native Windows. The initial
sandbox contract run failed MSYS object creation; the native retry passed.
Betterleaks failed before scanning because of `NUL`; the prescribed staged
Gitleaks fallback passed. No hook was bypassed.

### Candidate Preparation Policy

Preparation targets `v2.12.0` with the actual UTC preparation timestamp and
updated remediation notes/ZIP identity. The existing stable channel,
`critical_update=false`, minimum source version `2.4.2`, patch strategy, backup
and rollback policy, platform target and support/license metadata are retained.
This candidate does not impose a forced upgrade or assert publication. Both
manifests/checksums must be checked against the selected index and final commit;
package, initialization, upgrade and restoration qualification remains required.

The first candidate preparation used `2026-10-13T06:30:43Z`. The deployment
manifest inventories 167 files; the starter core manifest inventories 89 files.
Both validators passed on the selected index/tree. That date identifies the
first candidate snapshot. Fixture corrections committed at `7458aff` require
fresh metadata with its actual preparation timestamp. No primary `v2.12.0` tag
exists, and these generated files are candidate metadata only.

Required activation evidence includes the exact settings responses, ruleset and
App identities, a blocked native merge, the required-check run, a successful
guarded workflow after those checks, and the resulting exact merge message.
The accepted absence of independent PR review must remain explicit; the release
reviewer is a human publication gate, not an independent reviewer claim.

## Completion Gate

Completion requires one final candidate tree, complete profiles and OS suites,
unchanged coverage floors, dependency security checks, initialization/upgrades
and package restoration, coherent documentation/inventories, and a fresh review
of the whole branch. Hosted results and remote activation are separate proofs.
Findings 02/11 remain open until live settings and the disposable PR demonstrate
the agreed governance. Task-owned temporary artifacts must be removed and their
absence verified; permanent local environments are recorded separately.

## Candidate Qualification at `2c856e1`

Both actual candidate dependency gates passed: the npm gate reported no blocked
finding and retained its raw advisories with the exact braces attestation; both
hashed Python locks reported no known vulnerabilities. These are live registry
results at qualification time, not a perpetual absence-of-vulnerabilities claim.

A separate disposable Ubuntu clone built the actual SemVer candidate package,
with an annotated fixture-only `v2.12.0` tag at
`2c856e1794606d5fa061601ec139c8570934d800`. This does not qualify a release
changelog, hosted status or publication. The ZIP contains 100 files; all eleven
security/runtime files match the exact source. Its SHA-256 is
`508635589a5372a06f608fa5d0f70d6ba1495f45406281fe9c92ed1290f390e7`.

The published `v2.11.7` base ZIP matched the live GitHub asset digest
`ea18e7a5e5a14f302f48767a9a19d0a1b99d5134f8b2f78875f93c9a66e623f6`.
The new consumer validated and prepared its unborn Git index. A cumulative
upgrade and toolkit were built from the real base. Actual application preserved
customized documentation, tracked application content and unrelated untracked
notes. An injected failure on the third write restored the original non-Git
file bytes and modes; the subsequent normal CLI application succeeded.

The Linux full profile passed all 595 Python tests and six shell suites, with
89.43% global coverage (6,921/7,739) and 85.45% branches (1,885/2,206). It then
failed initializer smoke: the synthetic fixture omitted the version checker and
locked declarations required by the mandatory commit-message preflight. The
cancelled initialization itself returned zero. The later positive initialization
failed in its real hook. The fixture correction carries those inputs and test
metadata derived from the tracked lock while delegating to the real host CLI.
Dependency installation and runtime enforcement are unchanged.

Windows completed 595 tests in 2,421.091 seconds with nineteen explained skips,
but one npm fixture cleanup raised `WinError 145`. The affected directory was
subsequently observed empty; the handle holder was not identified. No production
leak is inferred. Two deterministic registered-cleanup regressions failed before
the correction, then all twenty npm tests passed. The bounded cleanup already
qualified for the backup fixture is now shared; all 48 native Windows backup
tests still pass with three applicable skips. Persistent and other cleanup errors
retain their original exception. The initial sandbox backup run encountered
filesystem access errors; the unchanged native retry passed.

These failures prevent a complete profile or final Windows/combined coverage
claim at this revision. The successful Linux and package phases remain separate
proofs. The fixture corrections require updated candidate metadata, exact-commit
qualification and a fresh whole-branch review before completion.

The corrected fixtures passed twenty npm tests and 48 backup tests on both
platforms, plus the complete dispatcher suite on both platforms and the entire
real smoke family on Linux. The focused initializer regression verifies the
locked inputs, excluded dependency metadata and real initial commit-message hook.
Ruff, the repository's `shfmt -i 2` policy, ShellCheck and Markdown checks passed.
The failed npm fixture residue was removed only after its owned absolute path,
regular-directory type and absence of links were checked; absence was verified.

## Candidate Qualification at `5cb9994`

The regenerated candidate inventories 168 deployment files and 89 core files.
Both validators and active commit hooks passed on its index and final commit.
The actual preparation timestamp is `2026-10-13T08:21:49Z`.

The complete Linux profile passed all 597 Python tests in 231.934 seconds, with
the ten previously explained skips, all six shell suites and real smoke checks.
Linux coverage retained 89.43% globally and 85.45% for branches. The Windows
profile passed all 597 tests in 1,227.674 seconds with nineteen explained skips,
then passed the Windows hook suites, PowerShell static checks and project runner.
The project runner's warning remains explicit: no application checks are
configured, so application validation did not run.

The sealed measurements use the same candidate SHA and local run/attempt `2/1`.
Their verified union passed the unchanged 85% floors: 90.66% globally
(7,016/7,739), 92.05% for statements (5,093/5,533), and 87.17% for branches
(1,923/2,206). These are local qualification results, not hosted CI evidence.

The npm gate again returned no blocked finding while retaining the raw advisories
and exact braces attestation. Both hashed Python locks reported no known
vulnerabilities. The actual 100-file package has SHA-256
`7461a1af1d89a8cd2038aa7a8d0d8745a36eaf00e408c752f48898e90dce90fc`;
all eleven security/runtime files match its exact source. New-consumer index
preparation, cumulative upgrade and toolkit generation passed against the
digest-verified published baseline. Customized, tracked and unrelated untracked
consumer content survived. Failure on the third write restored exact non-Git
bytes and modes before the normal application passed.

## Final Branch Review

One fresh read-only review covered 63 changed files and all nineteen domains
across the seventeen commits through `5cb9994`. It found no critical or minor
issue and one important compatibility regression: the closed `commit-msg`
snapshot omitted files imported relatively by Commitlint configuration. The
review did not replay complete suites or claim external activation.

A regression through the real forced Git hook reproduced `MODULE_NOT_FOUND` for
a tracked JSON helper. The configuration and helper in the worktree deliberately
differ from their indexed versions. The targeted correction exports the complete
index while retaining the isolated snapshot, locked runtime preflight and cleanup.
The negative case checks indexed helper rejection without moving HEAD or changing
the index. Source and consumer contribution guides describe the same contract.

The corrected complete commit-message suite passed on Windows and Linux,
including the relative helper acceptance/rejection cases. ShellCheck, the
repository's `shfmt -i 2` checks and all four changed Markdown files passed.
The correction is committed at `2a3ea20`; subsequent qualification must identify
its regenerated candidate. The successful `5cb9994` measurements remain their
immutable milestone; they are not relabeled as later results.
Findings 02/11 and the separate activation/hosted/cleanup gates remain open.

## Reviewed Candidate Qualification at `fd7064c`

The candidate includes the final review correction `2a3ea20`. Both manifest
validators passed on its selected index and exact commit: 168 deployment files
and 89 core files, prepared at `2026-10-13T09:16:15Z`.

Complete profiles passed on Windows and native Ubuntu. Windows ran all 597
Python tests in 1,158.641 seconds with nineteen platform skips, then passed its
hook suites, PowerShell static checks and project runner. Linux ran all 597 tests
in 310.161 seconds with ten platform skips, all six shell suites, the corrected
relative-import regression, real smoke checks and project runner. Application
checks are not configured; that warning is retained without claiming application
validation.

Linux coverage remained 89.43% globally and 85.45% for branches. Both sealed
measurements identify the same SHA and local run/attempt `3/1`. Their verified
union passed the unchanged 85% floors: 90.66% globally (7,016/7,739), 92.05% for
statements (5,093/5,533) and 87.17% for branches (1,923/2,206). These are local
results, not hosted GitHub Actions evidence.

The npm gate reported no blocked finding, retaining the raw advisories and exact
braces attestation. Both hashed Python locks reported no known vulnerabilities.
The actual candidate ZIP contains 100 files and has SHA-256
`b6a3a25633f44d62acb8d30cbca6ab15d7b3293fcbe8627b3b99ecbe3d663d8a`.
Its eleven security/runtime files and corrected hook match the exact source.
New-consumer index preparation, cumulative upgrade and toolkit generation passed
against the digest-verified published `v2.11.7` baseline. Customized documentation,
tracked application content and unrelated untracked notes survived. An injected
third-write error restored exact non-Git bytes and modes before normal application
passed.

The original Windows provisioning used Node 26.5.1; the current qualification
observes Node 26.8.1. The supported minimum and locked CLI versions are unchanged.
Linux uses the verified Node 24.20.0 runtime.

The actual complete pre-push hook also passed at this exact revision, comparing
against the original audit base. All 597 Python tests passed in 728.091 seconds
with nineteen platform skips, inside the unchanged 900-second family deadline.
All four mandatory shell suites passed, followed by the workflow/Actionlint and
project checks. No push occurred. Expected negative fixture diagnostics are
covered by the successful parent result; they are not hidden application errors.

## Local Closure and External Gates

Local implementation, both complete OS profiles, security gates, packages,
restoration and the single final review are verified through `fd7064c`. The final
proof consolidation changes only this source-only report and generated deployment
metadata/checksums. Every other tracked input must remain byte-identical to the
qualified revision. Manifest and Markdown checks qualify that consolidation;
earlier OS data retain their tested SHA and are never relabeled.

| Findings | Verified local closure | Remaining external evidence |
| --- | --- | --- |
| 01, 03, 13, 15 | Locks, attestation, actual dependency audits and distributed security/runtime bytes | Hosted execution after authorized integration |
| 04, 05, 06 | Interrupt restoration, early validation, complete tests and production typing | Hosted execution after authorized integration |
| 07, 08 | Exact-candidate manifests, both OS measurements, unchanged floors, package/init/upgrade/rollback | Integration provenance; publication remains separately controlled |
| 09, 12, 16 | Actual locked tools, indexed configuration including relative helpers, routing and complete pre-push | Hosted execution after authorized integration |
| 10, 14, 19 | Coherent declarations/locks, scoped commits, documentation, semantic workflow contracts and final review | Integration and hosted contract execution |
| 17, 18 | OS project checks, fail-closed aggregate and event/concurrency contracts | Actual hosted OS/consumer execution and superseded-push cancellation |
| 02, 11 | Reviewed activation guard and explicit single-maintainer policy | Authorized settings, administrative bypass audit, disposable PR and human release gate |

No nineteen-finding completion, hosted CI success or remote activation is claimed.
All remote changes require the separate authorization recorded in the plan.
The administrative bypass snapshot currently exposes empty actor arrays on all
three existing rulesets. Re-audit the complete arrays at activation and after any
governance change; workflow permissions remain unchanged.

### Concrete Activation Surface

The reviewed targets above preserve every ordinary main rule and parameter
except its allowed merge methods, narrowed to squash. Repository merge/rebase and
auto-merge are disabled; squash stays enabled. A distinct active update-only main
ruleset admits only owner-provided Integration ID `4355746` with `always` bypass
and disables fetch-and-merge. Ordinary protections retain no App bypass.

The release reviewer is verified User `83057672` (`asphyx0r`); self-review is
allowed under the accepted single-maintainer exception. Existing branch/tag
patterns `main`, `master`, and `v*` and the absence of a wait timer are preserved.
The documented REST environment update and live GraphQL `UpdateEnvironmentInput`
do not expose the administrative-bypass write field. Disable that bypass through
Settings > Environments > release by clearing the corresponding protection-rule
checkbox, then confirm `can_admins_bypass=false` through the read API. An
unsupported REST field is not an activation mechanism.
[GitHub environment settings](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

The current trusted main revision `6d5b6d1` accepts an update rule while retaining
its required-check gate. Settings can therefore be activated before using the
new requester; no temporary guard bypass or bootstrap code change is required.
Verify the resulting settings before any disposable native-merge test. Publishing
this branch, creating its integration PR and running hosted evidence are separate
external actions; no such action has occurred in this qualification.

## Authorized External Activation

The owner authorized branch publication, its PR and guarded integration, the
four proposed GitHub settings payloads, administrative bypass auditing and
hosted/disposable-PR qualification. Primary tags and GitHub Releases remain
outside that authorization.

The pre-activation main SHA was
`6d5b6d1fe992022157e0f3ef4b0366836aa713a5`; the task branch was absent remotely.
Repository settings now permit squash only, with auto-merge disabled. Ordinary
main ruleset `23177592` retains its required `Repository audit` check from
Integration `15368`, conversation resolution and all other existing parameters;
only allowed merge methods were narrowed. Separate update-only ruleset
`24996187` permits only Integration `4355746` to bypass that restriction.
The release environment now requires User `83057672` (`asphyx0r`), permits
self-review and retains the existing `main`, `master` and `v*` restrictions.
Administrative bypass is still true at this checkpoint and requires the
supported settings UI, whose accessible browser is unauthenticated.

Live GitHub GET responses omit the update rule's parameters for this non-fork
repository, including with API version `2026-03-10`. The documented flag controls
pulling from an upstream repository. The prior guard incorrectly rejected this
representation. A regression test failed with `Restrict updates` before the
fix. The guard now accepts absent parameters only after a repository GET proves
`fork=false`; explicit null, malformed/empty parameters, enabled fetch-and-merge,
forks and missing/ambiguous fork metadata still fail. All 81 guard CLI tests
pass on native Windows; the actual activated API policy resolves to
`Repository audit`. Workflow permissions and ordinary protections are unchanged.
The sandbox run failed fixture writes with access-denied errors; the native
regression and complete focused suite are the applicable evidence.

The earlier 597-test OS measurements and package digests remain bound to their
recorded commits. They are not relabelled as qualification of this subsequent
integration correction. Hosted checks and the active publication hook must
qualify the resulting candidate before integration.
