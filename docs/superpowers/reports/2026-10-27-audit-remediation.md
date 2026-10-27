# Audit remediation evidence: F01 to F19

This record follows the [approved plan](../plans/2026-10-27-audit-remediation.md).
Implementation is on `fix/audit-remediation-2026-10-27`, starting at
`3de324856a6d6cdceb7ba19130a2dadca5c741c3` (published v2.13.0).

Local implementation and independent code review are complete. Linux passed;
the complete Windows run failed in two cases whose symptoms also reproduce on
the starting code. Overall local qualification is therefore not a pass. Hosted
qualification remains required. This record does not authorize branch
publication, integration, tags, a release or changes to GitHub protection.
The frozen candidate is `9c9e5efcbdf9e2b46bd069cee7e7c64104b46619`;
subsequent evidence-only documentation does not change its executable inputs.
Published `VERSION`, `manifest.json`, `SHA256SUMS` and
`starter-kit-manifest.json` remain unchanged. Historical reports retain their
original meaning and finding identifiers; this record concerns the October 27
audit only.
This is the local pre-publication snapshot. Subsequent hosted outcomes belong
to the draft PR and check artifacts for the actually published SHA.

## Finding evidence

The table records implementation and focused verification. A focused pass is
not a substitute for the final local and hosted qualification gates below.

| Finding | Implementation | Focused evidence and limits |
| --- | --- | --- |
| F01 | `30bf823`: certifi 2026.10.19, regenerated Python lock hashes | Clean hash-checked installation; OSV audit reported no known vulnerabilities. |
| F02 | `30bf823`: markdown-it 15.0.3 override, synchronized npm lock and registry | Clean script-disabled npm installation, installed override checks and blocking npm audit passed. Required nested argparse update follows the new constraint. |
| F03 | `30bf823`: filelock 4.2.1, regenerated Python lock hashes | Quality lock and release dependency OSV audits reported no known vulnerabilities; existing direct Python pins retained. |
| F04 | `30bf823`: fast-uri 3.1.9 override, synchronized npm lock and registry | All installed override occurrences matched; dependency and configuration checks passed. |
| F05 | `1b7a9be`: preview selects tracked NUL-separated template paths; SemVer retains authenticated HEAD bytes | Regression failed on both PowerShell hosts, then three focused tests passed in 535.272 seconds. Includes untracked/ignored inputs, Unicode and spaces, missing tracked files and preservation of prior destination. |
| F06 | `ca09b94`: upgrade schema 4 separates baseline and target content kinds | Four classification transitions, customized conflicts, aligned targets, rollback and raw-byte concurrency tests passed. A review-discovered forged binary baseline was rejected before the absent-payload shortcut. Readers 1-3 and full inventory schema 3 remain supported. |
| F07 | `fcf592a`: argument repair retains option and delimiter boundaries | Mixed equals syntax, unknown flags, hyphen paths and Windows quoting regressions passed. |
| F08 | `03c0a4c`: ZIP timestamps clamp to supported limits | Old and future timestamps preserve source bytes and metadata; focused and backup module checks passed. |
| F09 | `5c5a76d`: timeout output is drained and displayed once | Three timeout regressions and the 20-test validation module passed; one existing Windows symlink privilege skip. Explicit cp1252, ASCII and UTF-8-mode codec cases passed. Deadlines and descendant containment retained. |
| F10 | `9e9a9ee`: confirmed merge identity survives cleanup failure | All 88 merge tests passed. Cleanup-only failure returns 1 with residual path, primary failures and interrupts retain their classification, unknown post-dispatch outcome remains 3; no mutation retry added. |
| F11 | `99e3555`: wildcard runs all six existing shell suites once; `c3b3a59` corrects the three current guides | Production selection trace and each failure position tested. Official native hook, pre-push and repository-audit suites passed without changing their budgets. |
| F12 | `99e3555`: source and read-only spelling share tracked regular-file selection | NUL paths, option-like names, links, absent files, producer failure and empty selection tested. Consumer and staged selection retained. |
| F13 | `30bf823` and current guides document controlled Dependabot completion | Synthetic registry-only proposal failed with three drift diagnostics; matching registry, declaration and lock proposal passed. No fake version was installed or audited; no bot bypass or new automerge added. |
| F14 | `ca09b94`: adoption schema requires an exact supported integer | Booleans, containers and unsupported values yield the existing unsupported-evidence result before ancestry queries. Committed with F06; see the grouping deviation below. |
| F15 | `4a3d0ba`, `65b4ab0`, `f9a59c9`: exact pins, valid identifiers, normalized duplicates and complete hash continuations | The final review's hidden-directive, malformed/orphaned hash and continuation cases failed first, then passed. A focused 58-test toolchain run passed with one Windows symlink skip. Generated blocks and actual locked declarations remain accepted. Scoped independent re-review approved; the later complete Windows result is recorded separately below. |
| F16 | `d5ac3c3`: audit-only npm CLI; obsolete patch commands, active callers, exemptions, payloads and unique fixtures removed | Twenty core tests and publication caller regression passed; real npm audit returned zero advisories. High/critical findings and malformed reports block. Existing consumer payloads remain inert; historical evidence is preserved. |
| F17 | `3498696`, `fc1ab89`: transfer and both owned-directory boundaries retain primary and cleanup diagnostics | Both outer paths preserve OSError, BackupError, KeyboardInterrupt and SystemExit identity; cleanup-only errors still propagate. The final 55 backup tests passed in 33.502 seconds with three existing platform/optional integration skips. Scoped independent re-review approved. |
| F18 | Coherent local correction commits; published history unchanged | Separate backup, timeout, merge, packaging, dependency, hook and CI commits retain their tests. F06/F14 share one updater commit, a deviation from the planned separation. |
| F19 | `3e38b78`: ineligible decision events select full qualification directly | Workflow 12, protocol 29 and contract 55 tests passed; final event matrix passed in 43.845 seconds. Tag/release verifier, seven-day validity, paired OS captures and producer sealing retained. |

`a474400` also repairs an existing experiment's deterministic test clock. Its
fixed October 15 producer correctly expired under the real October 27 clock.
The test now uses the fixture clock; production validity, provenance, packet
bytes and expiry assertions remain unchanged. The focused regression failed
first, then the complete experiment/protocol selection passed all 41 tests.

### Verification and current-guide map

These source paths locate the checks and instructions behind the finding table;
the final discovery includes every Python module below.

| Findings | Verification sources | Current documentation |
| --- | --- | --- |
| F01-F04 | [Toolchain tests](../../../tests/test_quality_toolchain.py), [npm tests](../../../tests/test_npm_security.py), hash-checked installs and live dependency audits | [Tools guide](../../../tools/README.md), [quick start](../../quick-start.md) |
| F05 | [Package tests](../../../tests/test_build_release_package.py) | [Release-package guide](../../release-package.md) |
| F06, F14 | [Upgrade tests](../../../tests/test_starter_kit_upgrade.py) | [Tools guide](../../../tools/README.md) |
| F07, F08, F17 | [Backup tests](../../../tests/test_backup_target_directory.py) | [Tools guide](../../../tools/README.md) |
| F09, F10 | [Validation tests](../../../tests/test_project_validation.py), [merge tests](../../../tests/test_merge_pull_request.py) | [Tools guide](../../../tools/README.md), [guarded merges](../../guarded-pull-request-merges.md) |
| F11, F12 | [Hook tests](../../../tests/test_quality_hooks.sh), [pre-push tests](../../../tests/test_quality_pre_push.sh), [audit tests](../../../tests/test_repository_audit.sh), [commit-message tests](../../../tests/test_commit_message_validation.sh) | [Tools guide](../../../tools/README.md), [consumer tools guide](../../../templates/project/tools/README.md) |
| F13, F15 | [Toolchain tests](../../../tests/test_quality_toolchain.py), controlled partial/completed proposal experiment | [Quick start](../../quick-start.md), [tools guide](../../../tools/README.md) |
| F16 | [npm tests](../../../tests/test_npm_security.py), [publication tests](../../../tests/test_release_publication.py), [package tests](../../../tests/test_build_release_package.py) | [README](../../../README.md), [tools guide](../../../tools/README.md), [consumer tools guide](../../../templates/project/tools/README.md) |
| F18 | Local Git commit history and independent review | This record's execution rulings and grouping deviation |
| F19 | [Workflow tests](../../../tests/test_qualification_workflow.py), [protocol tests](../../../tests/test_qualification.py), [workflow contracts](../../../tests/test_workflow_contracts.py), [experiment tests](../../../tests/test_qualification_experiment.py) | [Approved execution contract](../plans/2026-10-27-audit-remediation.md) and this record's simplification section |

## Baseline and final qualification

The measurements below use the frozen `9c9e5ef` candidate. Test counts include
skipped cases. No expected failures or unexpected successes were reported.

| Measurement | Observed result | Status |
| --- | --- | --- |
| Linux Python | 749 cases, 0 failures, 0 errors, 11 skips; measured 348.706405 seconds | PASS |
| Linux official shell | All six suites; 104.167040 seconds | PASS |
| Windows Python | 749 cases, 1 failure, 1 error, 19 skips; measured 2,049.354348 seconds | FAIL |
| Windows official shell | Both existing `--windows` suites; 211.526 seconds | PASS |
| Linux coverage | Global 91.21%, statements 92.62%, branches 87.62% | Both 85% floors PASS |
| Windows coverage | Global 91.43%, statements 92.92%, branches 87.62% | Measured; no standalone Windows floor required |
| Combined coverage | Global 92.43%, statements 93.66%, branches 89.29% | Both 85% floors PASS |
| Overall local qualification | Complete Windows failure retained | FAIL |

Linux's unittest footer was 348.104 seconds and Windows's was 2,048.181 seconds;
the measured runner also includes discovery overhead. The official Windows
shell suites took 110.219 seconds for pre-commit and 100.847 seconds for
pre-push. Both available Windows PowerShell hosts were exercised by the Python
package tests. No filters, deadline increases or new skips were introduced for
these final runs.

Combined coverage was recomputed from both original branch databases using
the existing `read_data`, `coverage_report` and coverage-policy functions.
All 25 measured source-file digests matched between platforms. The exact
combined totals are 5,570/5,947 lines and 2,084/2,334 branches, giving
7,654/8,281 global units. The local receipt records `evidenceKind=local-only`,
`coverageFloorsPassed=true`, `testsPassed=false` and
`localQualificationPassed=false`; the combining command returned 1. No GitHub
run identity was invented, and coverage success does not erase test failures.

### Open Windows result and controlled comparison

The Windows error was
`ExternalInstallerTests.test_powershell_module_preserves_exact_regular_zip_entries`:
`PermissionError: WinError 5` when `staging.rename(destination)` published an
installation. The failure was
`ReleaseArtifactTests.test_short_git_and_ref_deadlines_reap_a_blocking_child`:
the child's immediate `poll()` result remained `None`.

The two test-method ASTs and their connected installer, release-artifact,
Git-object and process-runner production modules are unchanged between the
starting SHA and candidate. Controlled focused comparisons retained the same
Windows Python 3.14.9, cp1252/UTF-8-mode-0 environment, Node 24.20.0, coverage
7.16.2, byte-identical coverage policy and original deadlines:

| Code under test | Installer case | Deadline case |
| --- | --- | --- |
| Candidate `9c9e5ef` | PASS, 1 test, 0.095 seconds | PASS, 1 test, 1.655 seconds |
| Starting SHA `3de3248` | Same WinError 5, 1 test, 0.121 seconds | Same `poll()` failure, 1 test, 2.887 seconds |

These observations support a pre-existing, context-sensitive behavior; they do
not establish its exact cause or turn the complete candidate run into a pass.
No assertions, production code or deadlines were changed to obtain a green
result. Independent evidence adjudication accepted requesting the separately
required publication authorization so the mandatory hosted Linux/Windows and
aggregate checks can assess the actual published SHA. It did not approve
integration or waive the open complete Windows result. No blind full-suite
retry was used to replace that result.

### Baseline and intermediate attempts

The immutable Windows baseline at the starting SHA completed 719 tests in
5,018.531 seconds: three failures, three errors and 19 skips. It did not pass.
Coverage was 90.494479% global, 92.065618% statements and 86.513995% branches.
Five of the six failing cases passed a focused retry with the selected runtime
and minimal process PATH; the deterministic experiment clock remained failing
and was corrected as described above. These retries do not turn the original
full baseline into a pass.

Final local Linux uses native Debian 13 storage, Python 3.11.17, Node 24.20.0
and the pinned tools. Final local Windows uses Python 3.14.9, Node 24.20.0 and
the pinned tools, including both available PowerShell hosts. Linux is not the
hosted Ubuntu 24.04 image; local Windows is not proof of Windows 2025 image
equivalence. Hosted checks remain a distinct gate.

The native Linux Python environment was recreated from a byte/link-verified
portable runtime and 55 hash-locked binary wheels. The unchanged 15-second
runtime guard passed in 5.744 seconds. The initial DrvFs runtime guard had timed
out; that failed preparation attempt is retained as such.

The first complete corrected Linux discovery at `c3b3a59` ran 749 tests in
381.673 seconds: one failure, one error and 11 skips. It did not pass. The
failure was a consumer-workflow test harness omitting the new job-level
`VERIFY_REUSE` input. The error was the codec test replacing interpreter-global
`sys.flags` with an incomplete namespace during a cold Python 3.11 codec import.
Both require test-fixture corrections; no production default or encoding rule
is relaxed. `9c9e5ef` corrects those two fixtures and the shell fixture described
below. Both Python cases then passed in fresh native Python 3.11 and Windows
Python 3.14 processes. Its complete results are recorded above.

The official Linux shell runner passed its first four suites, then stopped on
the commit-message suite. Its fixture still supplied only the former four npm
metadata entries, so the strengthened runtime guard rejected missing fast-uri
and markdown-it before the intended message-length assertion. This third
fixture correction derives override names from the existing registry, as the
other current fixture builders already do. It changes no production guard.
The corrected exact native commit-message suite passed in 14 seconds.
The unreached sixth suite is measured separately rather than inferred to pass.
It subsequently passed in 9.569 seconds. Thus all six official shell commands
were executed once at `c3b3a59`: five passed and the fixture-dependent
commit-message suite failed. The complete static-before phase passed in
36.989 seconds, explicit Windows-target Mypy in 2.472 seconds and static-after
in 47.920 seconds. Default Linux-target Mypy is part of static-before. The
configured project-check command returned 0 while explicitly reporting that no
application checks were configured; it is not application runtime evidence.

The fixture follow-up changes only three test files (10 insertions and two
deletions). A Git comparison confirms no changes to `tools/`, `.github/` or
`.githooks/` from the reviewed `c3b3a59` production inputs. Existing complete
static evidence therefore remains relevant; affected fixture language checks,
normal commit hooks and a fresh complete Linux/Windows test qualification
cover the new commit. The redundant slow DrvFs shell reproduction was
deliberately interrupted and is not counted as failure proof or a pass; the
complete official native failure supplies the RED evidence.
An independent fixture-only review approved the three corrections and confirmed
that the prior production-code review remained valid. The new frozen Windows
clone was clean before its full discovery started; the justified complete Linux
retry subsequently passed as recorded at the start of this section.

That failed run nevertheless produced complete raw coverage: global
91.21% (7,553/8,281), statements 92.62% (5,508/5,947) and branches
87.62% (2,045/2,334). Both existing 85% floors passed. Coverage does not make
the failing test suite successful.

The first final Linux discovery at `a474400` was deliberately interrupted after
112.206 seconds when review identified the two remaining fixes. Its partial
coverage and logs are incomplete evidence. No final test-count JSON or pass
was produced. Windows discovery had not started. Twelve selected Windows
statics passed at `a474400`; qualification of the corrected SHA was still
pending at that point.

The consolidated review-fix wave completed 113 focused module tests with no
failures and four expected skips. The toolchain module's first sandbox attempt
had an MSYS initialization denial and two missing expected override diagnostics;
the environment-only retry and the minimal expected-list correction each passed,
then the complete 58-test module passed in 107.565 seconds. The two override
expectations correspond to the intentional F02/F04 registry changes, rather
than a change to runtime-check behavior. Pinned Ruff, scoped Mypy, declarations,
Markdown and spelling passed. The wave was committed in three coherent commits
with normal hooks, then submitted for one scoped independent re-review.
That re-review approved all three corrections after independently repeating
the original parser and cleanup probes. No blocking code finding remained;
full qualification is still required. It explicitly accepted retaining the
disclosed F06/F14 grouping deviation without a history rewrite, while rejecting
any claim of exact planned commit separation.

The full accessible Git-history Betterleaks scan passed, scanning about 4.89 MB.
Normal `git fsck --full --no-dangling` passed. `main` and peeled `v2.13.0` still
resolve to the starting SHA. Published identification-file comparison passed.
Final local counts, separate Linux/combined coverage floors, shell results and
review disposition are recorded above. The complete Windows result keeps
overall local qualification open despite successful focused comparisons.

## Local measurement digests

The temporary raw inputs have the following SHA-256 digests. These identify the
observed local measurements; they cannot reconstruct deleted inputs and do not
constitute trusted GitHub qualification artifacts.

| Local input | SHA-256 |
| --- | --- |
| Linux branch data | `6277e640ddb128f9f295a4da87881f5fe375771d6b440681b1a9255ae01a3efa` |
| Linux test counts | `41431860cac34b1884db0ec08070ff0841fc47abd5f93e34935a060b649a6583` |
| Windows branch data | `3110d19b6b797eee580fcaee48670b25c7e9e99db52ad0c4a380bc940a72c00a` |
| Windows test counts | `b342d987d53b5af31f5c438742c99273a105df2642f6e4ae91d274e3b4cfd81a` |
| Combined coverage JSON | `d67ea05661328cd0beae2c9593a342ab7d7ab4ef1ba6fc0183f06a45a525ded8` |
| Windows controlled comparison | `eb578b2fe44573fd0da76bba32275e8bcf28fdcf5862c60d33ec1c3684a658a3` |

## Simplification and compatibility

The existing three hooks and common dispatcher remain. Static and staged secret
checks stay in pre-commit, affected tests in pre-push, and complete coverage in
CI. The six-suite wildcard is exhaustive without making every targeted path
run every suite. Spelling consumes tracked inputs instead of installed tools
and ignored reports. Existing locked-environment activation is documented;
process PATH selection changes no global installation or profile.

CI retains SHA-pinned actions, existing permissions, required check names,
lock-keyed download caches, OS parallelism and separate build/publication
boundaries. Ordinary decision events skip unnecessary dependency setup and
artifact downloads. Push and PR evidence remain separate because they have
different event contracts. Removing npm patch maintenance leaves the blocking
audit, isolated cache, 120-second containment and dry-run behavior in place.

Upgrade schema 4 deliberately requires a new reader. Existing readers reject
it cleanly; the new reader preserves schemas 1-3. Customized content does not
merge across classifications. Obsolete patch files in upgraded consumers are
preserved and inert; no automatic deletion migration was introduced. The public
npm patch/verify CLI removal is an intentional compatibility change documented
in the breaking-change commit and current guides.

## Execution rulings and deviations

- Reused the clean checkout on the approved dedicated branch, rather than
  creating another worktree. Risk: unrelated work could be mixed in; initial
  cleanliness, explicit ownership and root-only staging guard this boundary.
- Allowed disjoint agent edits with one controller owning shared files and all
  staging/commits. Risk: overlapping integration; each integrated diff and exact
  staged tree was checked and independently reviewed.
- Preserved published identifiers and baselines until separate release
  preparation. Risk: the working branch is not itself a new distributable
  release; this report makes no such claim.
- Used task-owned native Linux fixtures to exercise POSIX behavior unavailable
  on NTFS/DrvFs. Risk: Debian results do not prove hosted runner equivalence;
  the hosted exact-SHA gate remains open.
- Repaired only the deterministic experiment test clock. Risk: a fixture clock
  could conceal time-policy defects; original packet bytes, age assertions,
  expiry negative tests and production policy remain intact and were rerun.
- Executed normal commit hooks in a native clone after Windows Actionlint hung,
  then imported an offline bundle. Risk: branch/index divergence; exact parent,
  index tree and compare-and-swap ref checks guarded every import. No hook was
  disabled, no production or hook timeout increased and no main/tag/remote ref
  was changed.
- Moved task-owned native artifacts from volatile `/tmp` to persistent
  `/var/tmp`. Risk: leftovers; descriptor and ownership marker identify the
  exact cleanup root. Earlier vanished raw hook logs are not reconstructible;
  retained summaries are distinguished from final repeated measurements.
- F06 and F14 were committed together in the four-file updater correction,
  although the plan proposed separate commits. This is a commit-grouping
  deviation, not a claim of exact plan conformance. Selectively reverting one
  correction requires a patch; published history was not rewritten to alter
  that grouping.

The derived Git commit-graph cache once referred to a missing unreachable
commit after bundle import. Reachable-object traversal and cache-independent
fsck found no missing reachable object. Rebuilding the cache with
`git commit-graph write --reachable --split=replace` restored normal fsck.
No persistent integrity-check bypass or history rewrite was used.

## Remaining gates and compliance

1. Obtain the separately required authorization to publish this reviewed result,
   including its open complete Windows result and disclosed F18 grouping.
2. Publish the task branch, create the draft PR and require hosted Linux,
   Windows and aggregate checks on its exact SHA. No merge, tag or release is
   authorized by the implementation goal. Local diagnostic retries do not
   replace this gate or change the recorded complete Windows failure.
3. After the authorized qualification sequence, record its evidence in the PR
   and remove verified task-owned runtimes, clones, caches and raw inputs.
   Pre-existing environments and unrelated artifacts must remain preserved.

The recorded fixture-only temporary paths have been removed with absence
checks. The task's private runtimes and raw evidence remain retained for normal
pre-push hooks and the next qualification gate. Overall temporary cleanup is
pending; this report makes no cleanup-complete claim.

Applied `AGENTS.md`, `CODING_RULES.md`, relevant `LANGUAGE_RULES.md` sections,
`DOCUMENTATION_RULES.md`, `BRANCH_RULES.md` and `COMMIT_RULES.md`. Release rules
were consulted for context; no release operation was performed. Focused tests,
language checks, dependency audits, secret scans and independent reviews are
reported with their actual scope. Missing, failed and interrupted checks are
not passes. Raw task evidence is temporary; this source-only report preserves
the observed results and their limits after cleanup.

Exact planned F06/F14 commit separation was not applied, as disclosed above.
Native Windows Actionlint was not relaunched after its host hang; pinned Linux
Actionlint with ShellCheck passed instead, and no Windows Actionlint pass is
claimed. Optional mounted-cloud tests were not enabled, no application checks
were configured, and hosted runner equivalence remains unverified.
