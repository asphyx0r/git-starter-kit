# Audit Remediation Evidence

## Scope and Status

This record tracks the nineteen findings from the 2026-10-12 audit and the
[approved implementation plan](../plans/2026-10-12-audit-remediation.md).
It records local implementation evidence as of 2026-10-13. It does not close
findings that still require candidate qualification, integration or live settings.

The original base is `bace76a55c165d18b67bdc9e25b224dc725d4286`. Work is isolated on
`fix/audit-remediation`. Published history and unrelated repositories are preserved.
The proposed candidate is `v2.12.0`; the published baseline remains `v2.11.7`.
No primary tag, push, GitHub Release or remote activation has been performed.

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

Behavior changes include their tests and relevant source/consumer documentation.
Future commits continue this separation; no historical commit is rewritten.

## Finding Ledger

"Local" means the implementation and focused verification exist. Every local
finding still depends on the final candidate checks below.

| ID | Axis | Implementation and evidence | Remaining proof |
| --- | --- | --- | --- |
| 01 | 2 | Local braces walkers, exact upstream provenance and attestation gate; 17 security tests and 3,315 differential API cases | Exact-candidate dependency audit and distribution |
| 02 | 6 | Current settings read; no effective Restrict updates rule on main | Guard preflight, authoritative App ID, activation and disposable-PR proof |
| 03 | 2 | smol-toml 1.9.1 pinned in registry/overrides/lock; installed occurrences checked | Candidate audit and integration |
| 04 | 3 | Output rollback handles interrupts and independent cleanup/restoration failures; 48 release tests | Candidate full suite |
| 05 | 3 | Shared SemVer validation precedes initializer writes/index changes; 19 initializer tests | Candidate full suite and package initialization |
| 06 | 1 | Initializer/new tools in Mypy; tracked-tool coverage invariant; 24 files checked for both platforms | Candidate typing and scope checks |
| 07 | 1 | Source Windows measurement plus matched OS artifacts; artifact regressions cover input identity, OS paths and caller measurement isolation | Complete OS measurements and combined floors at the candidate |
| 08 | 4 | Candidate preparation deliberately follows substantive changes | Regenerated metadata/checksums checked on the index and final commit |
| 09 | 5 | Broken environment rebuilt; pinned local tools provisioned; selected real executables checked against indexed pins | Candidate hooks and runtime qualification |
| 10 | 6 | Registry, declarations and hashed locks updated coherently; maintenance procedure documented | Integration and coordinated future bot proposals |
| 11 | 6 | Single-maintainer review exception accepted; release environment still has no reviewer | Documented human gate, live reviewer and disabled admin bypass |
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
  Node 24.20.0 for Linux matched the official Node checksum; Windows uses Node 26.5.1.
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

## Governance Work Still Open

Live reads still show all repository merge methods enabled, no update restriction
on main, and no release reviewer. Release admin bypass is enabled. The ordinary
main ruleset remains active with required checks/conversation resolution and zero
required independent approvals. These settings have not been changed.

The numeric App ID must come from authoritative owner metadata. The configured
public client ID and the bot account ID are distinct identifiers and cannot
substitute for it. Owner input has been requested.

GitHub documents that ruleset bypass actors can be omitted when the requesting
token lacks write access to the ruleset. The existing workflow starts with read
permissions, then mints an App token limited to contents/pull-request writes.
The preflight implementation must be qualified against this visibility boundary;
missing actor data must not be presented as proof of an empty bypass list.
[GitHub ruleset API](https://docs.github.com/en/rest/repos/rules#get-a-repository-ruleset).

### Proposed Settings

These are reviewable targets, not applied changes. The owner must supply the
numeric App identity and settle the administrative verification boundary first.

| Setting | Current | Proposed |
| --- | --- | --- |
| Repository merge methods | Merge, rebase and squash enabled | Squash enabled; merge/rebase disabled; auto-merge stays disabled |
| Main ordinary protections, ruleset `23177592` | Checks/conversation resolution, zero approvals, no bypass | Preserve these controls; allow only squash in the pull-request rule |
| Main update restriction | Absent | Separate active branch ruleset for `refs/heads/main`, only `update`, fetch/merge bypass disabled, only the verified App with `always` bypass |
| Release reviewer | None | Required human reviewer `asphyx0r`, verified User ID `83057672`; self-approval allowed for the accepted single-maintainer policy |
| Release admin bypass | Enabled | Disabled |
| Release reference restrictions | Branches `main`/`master`, tags `v*` | Preserve these existing policies |
| Workflow credential boundary | Read-only first pass; limited existing App token afterward | Preserve it; qualify visibility before selecting the full bypass-verification design |

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
