# Audit remediation evidence: F01 to F16

Historical snapshot: this record describes local qualification before the
authorized publication and hosted follow-ups. Its remaining-gate statements
below preserve that earlier state. On 2026-10-16, F14 was subsequently closed
under the user's accepted alternative criterion; see the
[completed experimental results](2026-10-16-f14-experiment.md) for current
disposition and its limits. Ordinary hosted verification is recorded in
[draft PR 90](https://github.com/asphyx0r/git-starter-kit/pull/90).

This record follows the [approved plan](../plans/2026-10-16-audit-remediation.md).
Local implementation and qualification are complete on the frozen candidate.
Hosted qualification and the measured release-sequence costs required for F14
remain open. No Git publication or hosted speed claim follows from this record.

## Scope and starting state

- Base: `e67c9dc0bf4e05353aeeeefbe7c5916cc9a89e63` (published v2.12.2).
- Local branch: `codex/audit-remediation-2026-10-16`.
- User goal: implement the approved F01-F16 plan.
- No remote mutation, integration, tag, release or GitHub protection change.
- Published release metadata and historical evidence remain unchanged.

## Baseline and environment

The existing [Repository audit run 38531872955](https://github.com/asphyx0r/git-starter-kit/actions/runs/38531872955),
attempt 1, was reverified through the GitHub API on 2026-10-16. It is a completed,
successful default-branch push at the exact base SHA. Linux/Python 3.11,
Windows/Python 3.14 and the required aggregate all succeeded. This is pre-change
evidence, not qualification of the remediation.

The local Windows full-suite baseline was interrupted before producing a final
test count. It is not recorded as a pass. The identical-SHA hosted run supplies
the complete baseline; the final local full suite will run without concurrent
test workers. Any local-only failure must be compared against the original
snapshot before attribution to a correction.

The locked runtime preflight passed with the existing `.venv/Scripts` and
`tools/quality/external/bin` on session PATH, and
`tools/quality/external/Modules` on session PSModulePath. It used the existing
native `.cmd` launchers for Commitlint and Markdownlint via `--executable`.
The first POSIX-wrapper probes timed out; no deadline or version was changed.
The selected Python is 3.14.8 and Node is v26.8.1, rather than CI Node 24.20.0.
This proves selected local tool versions, not equivalence to the hosted runner
images. No global installation or configuration was changed.

Existing WSL Ubuntu and Debian provide Python 3.12.3 and 3.13.5 respectively,
rather than the CI Linux Python 3.11 environment. No Linux runtime was installed.
Final hosted qualification remains a separate authorization gate.

For final local qualification, isolated portable Node 24.20.0 was subsequently
prepared for both OSes and checked against the official SHA-256 manifests.
Windows now passes the complete default runtime check without executable
overrides, using the existing Python 3.14.8 environment and pinned external tools.
The earlier Node 26.8.1 attempt remains separate historical preparation evidence.

A task-owned native Debian environment also passes the complete runtime check:
existing Python 3.13.5, portable Node 24.20.0 and PowerShell 7.6.7, all locked
Python/npm packages and the registry-pinned external tools, including
PSScriptAnalyzer 1.25.0. Installation verified both existing Python locks and
official/registry archive hashes; no global installation or setting changed.
Python 3.13.5 still differs from hosted Linux Python 3.11. These successful
preflights establish readiness, not a final suite result.

## Finding status

| Findings | Local result | Remaining gate |
| --- | --- | --- |
| F11 | Current onboarding corrected; documentation checks pass | Hosted confirmation of the final Git commit. |
| F12 | Actual default locked tools selected; both local OS suites pass | Hosted Linux Python 3.11 and runner-image validation. |
| F01, F05 | Preparation and independent cleanup corrections reviewed and tested | Hosted confirmation. |
| F02 | Selected-tree blobs, attributes and factory provenance tested, including actual ZIPs and both Windows PowerShell hosts | Hosted confirmation. |
| F03, F04, F10 | Invalid text, journal finalization and documented dry-run behavior tested; guides synchronized | Hosted confirmation. |
| F06, F07, F13 | Encoding, initializer selection and ownership-list corrections tested | Hosted confirmation. |
| F08, F09, F15 | Native exit codes, resumable publication and shallow-checkout contracts tested; obsolete duplicate harness replaced | Hosted confirmation; no real publication performed. |
| F16 | Retry instructions and original-pair exception synchronized; identity/refusal tests pass | Hosted confirmation. |
| F14 | Seven-job implementation reviewed; reuse/refusal/full-fallback scenarios and final local coverage pass | Hosted execution and measured gain/fallback cost on a complete release sequence; finding remains open. |

## Packaging evidence and integration

- Preparation-control regressions failed first, then three tests passed in
  95.251 seconds using template, schema and inventory from one Git selection.
- The actual ZIP matrix passed on PowerShell 7 and Windows PowerShell 5.1,
  covering SemVer/preview modes, Unicode paths, clean-filter-masked local
  runtime/template bytes and explicit CRLF checkout behavior. The final matrix
  passed in 240.090 seconds; affected consumer/template/initializer tests also
  passed. Unmerged index stages remain blocking.
- Review found two provenance gaps in succession: worktree copies authenticated
  through a clean filter, then non-tree Git attributes affecting the snapshot.
  Both were fixed and independently accepted. Four contradictory local
  attribute scenarios failed first; the final two direct tests passed in
  37.662 seconds, including missing-object refusal and temporary cleanup.
- Three cleanup regressions passed in 85.059 seconds: independent attempts,
  original-error diagnostics and preservation of an already validated ZIP.
  Original PowerShell ErrorRecord identity/type was not separately asserted;
  this is a proof limitation, not a demonstrated defect.
- Ruff, formatting, PowerShell parsing and ScriptAnalyzer passed. The final
  reviewed final patch is `a4291eea12cf448aa213003eb06e5c6e0c448dde4fb9e97483c6bc723ca9f331`.
  All four root files match their reviewed raw SHA-256 values, including the
  PowerShell CRLF bytes. Shared packaging documentation is synchronized.
- The preparatory final review found another composition input: SemVer
  configuration generation still imports the worktree's `project_config.py`.
  A masked factory override can therefore diverge from the embedded HEAD module.
  Its targeted real-function regression failed on both PowerShell hosts in
  9.132 seconds, then passed in 9.108 seconds: SemVer uses the HEAD factory,
  while previews retain the local factory. Strong independent re-review
  accepted the two-line correction. The two changed root files match the final
  reviewed bytes. G received this new base before reapplying its separate
  source-only exclusion; shared-file ownership was transferred sequentially.

## Updater evidence and integration

- Fourteen focused regressions passed in 155.401 seconds after failing before
  correction. They cover invalid local text, journal failures and real dry-run
  merge behavior.
- Configured Ruff and Mypy passed; Mypy checked seven source files.
- The full isolated updater suite ran 90 tests in 481.815 seconds: 78 passed,
  ten platform skips, one failure and one error. It did not pass.
- The unchanged descendant-deadline test failed because its child had not
  created a marker before timeout. The unchanged junction test failed when
  Windows `mklink /J` returned 1. Their original snapshots subsequently passed
  together in isolation (two tests, 4.736 seconds), followed by the integrated
  candidate (two tests, 4.540 seconds), with unchanged deadlines. The initial
  full-suite failure remains recorded; the retries do not turn it into a pass.
- Independent review required two journal corrections: propagate finalization
  interruptions without an earlier operation error, and retain secondary notes.
  Their new tests failed first, then all five selected journal tests passed in
  12.180 seconds. Ruff and Mypy passed, and scoped re-review accepted both fixes.
- The integrated six files were compared byte-for-byte with the reviewed
  candidate. Shared CLI/JSON, dry-run and journal behavior is documented in the
  tools guide and upgrade guide. All 50 Markdown files lint successfully.

## Validation and hooks evidence

- The complete isolated hook suite returned 0 with five PASS groups, including
  both initializer modules exactly once from the pushed SHA, and 100 unrelated
  application paths filtered with one ownership-list invocation.
- UTF-8/NUL output, absent Unicode paths and the unchanged existing-file listing
  passed focused CLI tests. Review found a partial-output error for a malformed
  surrogate path; the test first failed, then all three selected CLI tests passed
  in 2.076 seconds after preencoding the entire list. Scoped re-review accepted
  the fix. The four integrated files match the reviewed candidate byte-for-byte.
- The initial Python suite had 14 passes, one Windows symlink skip and one
  existing 60-second pushed-configuration timeout with a ResourceWarning. Its
  single retry passed in 54.075 seconds with explicit pinned PATH and unchanged
  timeout. The initial attempt remains recorded as a failure.
- Ruff, Mypy, shfmt, ShellCheck, separate Bash syntax checks and whitespace
  checks passed. The final integrated results are recorded below.

## CI safeguards evidence before integration

- The actual inline publication script is exercised against an isolated local
  API process stub. The final publication, confinement and native PowerShell
  suite passed all 17 tests in 114.617 seconds. Workflow contracts passed all
  55 tests in 64.952 seconds. The strict coverage-identity test passed, including
  wrong-run and wrong-attempt mutations. Adversarial guards passed before
  updating the two affected workflow seals.
- Independent review found the production implementation conformant, with no
  concrete code defect. The privileged publisher retains its inline trust
  boundary, minimal token permissions and release environment.
- The complete Windows transfer attempt failed with timeout 124 at
  `prepare-source-mismatch`; it remains a failed suite. The unchanged original
  and candidate also time out in the same group under a serial, requalified
  environment. The retained logs do not expose the internally redirected stderr
  on timeout, so they cannot establish whether the earlier `/tmp` warnings
  recurred internally. The timeout exists in the original; its cause remains
  unproved. The remaining Windows publication group subsequently passed,
  including lease refusal and post-push races.
- The first complementary Debian full transfer attempt failed because the
  Windows-mounted temporary filesystem cannot create FIFO fixtures. A new
  native Linux temporary directory passed FIFO and command-confinement
  preflights; the complete transfer suite then passed in 12 seconds. Its exact
  owned directory was removed and absence checked. This is Debian/Python 3.13.5
  evidence, distinct from CI Python 3.11 and from the failed Windows full suite.
- Configured Ruff, Mypy, YAML, Actionlint, Bash syntax, ShellCheck, shfmt and
  PowerShell parsing passed. PSScriptAnalyzer reports the same pre-existing
  Information diagnostic for positional `npm ci` in original and candidate;
  no rule was suppressed. Hosted qualification and real publication were not
  performed.

## Controlled qualification evidence and integration

- The 15-file G patch is
  `3d7d63fe515eea1e2dd90b18fe3aa27af2f238ae747796d5b314bf65c034d8d8`.
  All root base hashes matched before integration, and the integrated raw
  bytes matched the independently reviewed candidate. Subsequent presentation
  and fixture-label follow-ups are recorded below. The preceding packaging
  provenance fix is preserved; its additional PowerShell delta is only the
  source-only helper exclusion.
- Review found two defects before integration. An inherited
  `AUDIT_COVERAGE_DIR` could reenter the shell reporter; the real child-process
  regression failed first and passed in 0.470 seconds after removing only that
  variable from suite environments. Three blocking auxiliary uploads could
  prevent the promised full fallback. Their regression failed first and passed
  in 0.050 seconds after making only predecision candidate/fresh transfers
  optional. Heavy measurements and required postdecision transport stay strict.
- Final focused results: 53 helper/orchestration tests passed in 34.879 seconds
  and nine workflow-boundary tests passed in 34.667 seconds. The targeted
  98.04% coverage is not a global coverage result. Ruff, Mypy on 25 sources,
  Actionlint and Yamllint passed; unchanged shell deltas passed locked shfmt
  3.14.0 and ShellCheck.
- Provenance scenarios cover latest-producer failure, identity/attempt changes,
  original expiration, altered or absent OS evidence, malformed API responses,
  before-decision common fallback and after-decision refusal. Packaging tests
  actually track the helper in a Git fixture before proving its exclusion;
  the exported consumer decision runs without that source helper.
- The seven-job graph, three-command CLI, unchanged complete local profile
  order and preserved coverage scope/floors were independently accepted.
  Documentation uses one canonical protocol and indexes the three new files.
  Hosted execution and the gain/fallback cost of a real release sequence are
  still unmeasured; no hosted speed claim is made.

## Qualification history

The first frozen source copy contains 176 source files and 40 changed paths.
Its Windows runtime preflight passed in 27.590 seconds with the default locked
tools. The following fast gate failed in 10.515 seconds: Ruff 0.17.0 required
formatting in two updater files. No complete Python or shell suite had started.
The original failed preflight remains distinct from its subsequent correction
and retry; it is not counted as a successful qualification.

The formatting-only correction is
`c624085213a3cefb0afb27f0898f64a30869003a648310d38330ae4e06cb9cc8`.
Independent review recalculated equal ASTs including type comments, unchanged
comments and changes confined to the existing C additions. Locked Ruff 0.17.0
checks pass on both candidates; the reviewed bytes are integrated before the
next freeze. Behavioral suites were not repeated for formatting alone.

The next Windows preflight passed: runtime 17.425 seconds, fast gate 21.921
seconds, PowerShell static analysis 41.717 seconds and project-check dispatch
0.443 seconds. Ruff accepts all 49 Python files and Mypy all 25 configured
sources. No application checks are configured in this source repository;
that dispatch reports its limitation rather than claiming application validation.

The owned Git fixture passed integrity checks. Betterleaks could not validate
staged content because of a Windows `NUL` access error; its partial scan is not
a pass. The prescribed Gitleaks fallback passed on 306,534 staged bytes. All
50 Markdown files passed. The source-only spelling gate then found one French
fixture label. Its single-word correction preserves the space, accented and
CJK characters; independent review accepted patch
`dca82c4e6fa310cebd8946ef417f06bea5e234f28b0e411d881419da34ba5fb4`.
Codespell reproduced exit 65 before and returned 0 after the correction; the
remaining AST and all comments are unchanged. No production behavior changed.

The first complete Windows trial used the owned fixture commit
`1413658fb901011e325c56241345d5442d23ad99`. It encountered an import error in
all 23 project-configuration tests and another error in an unchanged
descendant-interruption test. It was deliberately stopped after the confirmed
import defect; no final test counts, complete tracebacks or qualified coverage
were produced. Its partial output and input hashes were kept separate until final review and cleanup.

The actual Coverage file entry point reproduced `ModuleNotFoundError: tools`
without `PYTHONPATH`. The minimal correction adds the current directory before
discovery and restores `sys.path` in place in `finally`, including on errors and
interruptions. Independent review accepted patch
`9e4b1cb6f24e3b0515af032ca9fe88c9a9c945a3703fbfa214b64a2e6586c1cc`.
The regression failed first; all 27 orchestration tests then passed in 6.166
seconds. Through the actual Coverage entry point, the 23 configuration tests
passed in 6.361 seconds with one existing capability skip outside the sandbox.
The unchanged interruption case passed separately against both original and
candidate with its original two-second deadline. Its initial error has no
established cause; these isolated passes do not qualify the interrupted trial.
Both reviewed files match their raw candidate hashes before the next freeze.

### First complete OS attempts after the import correction

The next owned fixture commit was
`c501351be482b4f82654f791f06bf78b1fe8fd72`. It is a local technical identity,
with synthetic run `2026101601`, attempt 1; it is not a hosted producer.
All 176 source-file hashes were checked before executing the two OS attempts.

| Attempt | Python tests | Skipped | Failures | Errors | Python elapsed |
| --- | --- | --- | --- | --- | --- |
| Windows | 703 | 19 | 0 | 0 | 1,752.385 seconds |
| Debian | 703 | 11 | 1 | 0 | 240.377 seconds |

Both focused Windows shell suites passed: pre-commit in 75.066 seconds and
pre-push in 65.154 seconds. Its measured environments before and after are
identical. The complete Windows attempt passed; the Debian attempt did not.

The Debian failure is confined to the new tagged-package/filter regression:
the builder refuses its fixture because the manifest core inventory differs
from the selected tree. Its executable index entry lacked the corresponding
physical Unix permission. A subsequent `git add` therefore changed the selected
tree after manifest preparation. The builder correctly refused that mismatch.
No assertion, deadline, skip or production guard is relaxed. The failed attempt's computed
90.28% global and 86.51% branch coverage is not qualified success evidence.
Its failure prevents continuation to the six shell suites and smoke stages.

Before that Python attempt, all configured Linux static gates passed, including
50 Markdown files and 25 Mypy sources. Gitleaks scanned 311 commits and about
4.54 MB without findings. The npm policy check passed with its existing attested
`GHSA-vfj7-8cjw-p6xm` mitigation: its raw report still lists five high-severity
transitive entries, all attested, with no blocked entry. This is not a claim
that the raw dependency graph contains no advisory. OSV reported no known
vulnerability in either Python lock. Its warning states that `--require-hashes`
with OSV checks presence, not hash validity; installation had separately
verified the locked package hashes. No dependency policy was weakened.

The exact Linux failure was reproduced in 2.446 seconds. Two added test lines
set the physical Unix permission before index and manifest preparation, using
the existing fixture pattern. The same regression then passed on Linux in
4.951 seconds and on both Windows PowerShell hosts in 141.351 seconds.
Independent review accepted the cause and the minimal correction, patch
`16966d70bfffa3fea86ec71a086a7ad1c6438982e1cf873c7337310ebc17dc60`.
Ruff and formatting passed. Production code is unchanged by this follow-up.
The reviewed candidate hash is verified before another 176-file freeze and
complete OS reruns; the earlier Windows success is retained separately.

### Next complete OS attempts and the connected shell harness

The next owned fixture commit was
`78165031219384d34debd46d1a02506a8e96e8e9`. Windows ran all 703 tests in
1,911.619 seconds with 19 skips, zero failures and one error. The third CLI
invocation in `test_first_system_head_runs_new_declared_checks_in_real_cli`
reached its unchanged ten-second outer timeout while testing a deliberately
failing declared check. The run did not export qualified coverage.

The exact isolated test subsequently passed against the original base in
6.612 seconds and against this candidate in 7.039 seconds, through the real
Coverage entry point. Its method AST and deadline are unchanged. The four
involved files are also byte-identical between the preceding successful
Windows fixture and this fixture. No cause was established, no deadline was
changed, and no correction was inferred from those isolated passes. They do
not turn the failed full run into a success.

The subsequent native Debian attempt passed all 703 Python tests in 231.510
seconds, with 11 skips, zero failures and zero errors. Its raw coverage was
90.28% global (7,520/8,330), 91.76% statements (5,480/5,972) and 86.51% branches
(2,040/2,358). The complete audit then failed in its first shell suite after
4.920 seconds: the old publication harness invoked the new publisher without
`EXPECTED_PACKAGE_SHA256`. This Python success is not a complete audit or an
accepted two-OS pair. Its remaining shell and smoke stages did not run.

The connected shell test still expected the removed `gh release upload` and
`gh release edit` interface. The actual API publisher already has a confined
canonical Python harness. The correction therefore keeps shell sealing and
handoff checks, while removing the obsolete duplicate publication simulator.
It retains seven invalid payload cases, one valid outside-directory handoff
and exact sealed-checksum comparison. A refusing `gh` sentinel prevents an
accidental real publication from this shell test. Canonical Python coverage
retains the exact manual/stable event cases and now requires all three expected
uploads in each case. Independent review found the initial missing assertion;
a mutant returning success without uploading failed in all three subcases.
The final 17-test publication suite passed in 8.613 seconds with one expected
Windows-only skip on Linux. The complete changed shell suite had already
passed in 40 seconds; no further shell behavior changed during that review fix.

Independent specification and quality review accepted patch
`258a57ef2bf6e1bd60f5dfb924746739e247e8f307831847ea4616bae498989f`.
Both integrated files match the reviewed raw candidate hashes. The production
workflow used temporarily by the mutation test was restored and hash-checked.
A separate static review found no other obsolete interface in the five
remaining shell suites. Complete runtime qualification is still required.

## Final local qualification

Both OSes used the same frozen source identity
`b26fd3c31fecc449b5e2f93c2a9cce7467656740`, synthetic local run `2026101601`,
attempt 2. This technical commit exists only in an owned test clone. These
identities are not a GitHub Actions producer or reusable hosted evidence.
The 176-file input-manifest SHA-256 is
`6e801fc57a5273552880865f4cc1c2570de7f888cc51827a284ae618d44eba92`.
Both coverage datasets have the same 25 measured source hashes and policy
`088f1e1f9a721b11c1575a2474d57b1b03618bdcac1746cf5029be17ee6e988e`.

| OS | Python tests | Skipped | Failures | Errors | Structured runner seconds | Shell suites |
| --- | --- | --- | --- | --- | --- | --- |
| Debian | 703 | 11 | 0 | 0 | 340.844 | 6, all exit 0 |
| Windows | 703 | 19 | 0 | 0 | 2633.609 | 2, all exit 0 |

The full Linux `all` profile passed in 487 seconds, including static gates,
Python coverage, six Bash suites, smoke tests and Commitlint, followed by the
final environment probe and project-check dispatch. Windows passed its full
Python suite, export and coverage JSON generation, then its two focused hook
suites. Relevant locked static and documentation gates also passed on the
frozen source. Each OS has identical measured environments before and after
its heavy work. This source repository declares no application checks; its
dispatch warns accordingly rather than claiming application validation.

| Shell suite | Linux seconds | Windows seconds |
| --- | --- | --- |
| `tests/test_repository_audit.sh` | 11.804 | Not in the Windows focused profile |
| `tests/test_agent_rules_transfer.sh` | 7.301 | Not in the Windows focused profile |
| `tests/test_quality_hooks.sh` | 3.535 | Not in the Windows focused profile |
| `tests/test_quality_pre_commit.sh` | 19.937 | 173.487 |
| `tests/test_commit_message_validation.sh` | 14.025 | Not in the Windows focused profile |
| `tests/test_quality_pre_push.sh` | 4.662 | 192.833 |

Windows unittest elapsed time was 2,631.179 seconds; its structured runner
includes orchestration overhead. These local durations are descriptive, not
a hosted speed comparison or the release-sequence measurements required by F14.
The earlier failed Windows timeout retains its unknown cause; this successful
complete attempt does not retrospectively qualify that failed attempt.

The canonical combiner verified identities and raw digests before combining.
It rechecked both the Linux and combined 85% global/85% branch floors without
changing scope or exclusions:

| Dataset | Global | Statements | Branches |
| --- | --- | --- | --- |
| Linux rechecked | 90.28% (7,520/8,330) | 91.76% (5,480/5,972) | 86.51% (2,040/2,358) |
| Combined | 91.49% (7,621/8,330) | 92.80% (5,542/5,972) | 88.17% (2,079/2,358) |

Independent final review accepted the implementation and the coherent local
proof pair. The final evidence text was separately reviewed and checked with
the locked Markdown, spelling and secret scanners before applying its exact
bytes after cleanup. Coverage commands and the original-pair rules remain in
the [tools guide](../../../tools/README.md) and
[canonical qualification protocol](../../release-package.md#controlled-ci-qualification).

### Evidence receipts

| Artifact | Linux SHA-256 | Windows SHA-256 |
| --- | --- | --- |
| `.coverage` | `65e0c51635466fa5e73b27f641cde3566910fab49c27fffb5fe9d502c467fa17` | `6e579bb65aee6d2a6991876566f4dd817309551734e40a8bb6a22ec983776023` |
| `coverage.json` | `8375896294176045f23627c2b65a180d2961cbbc5167751161a8c60b0348ff2d` | `31fde0c36234a8bba5a799f954858e48a556501f45f8d51ebfa6aada8dc538d1` |
| `environment-after.json` | `68aabc671499cb4e428da625cfe3d2d91ffb7293f94ead87700a7caa0f141f8b` | `683f5d516f7deb8912857e20bbf35e42cf2ab4f345b0ac0ca291759e5c813d75` |
| `environment-before.json` | `68aabc671499cb4e428da625cfe3d2d91ffb7293f94ead87700a7caa0f141f8b` | `683f5d516f7deb8912857e20bbf35e42cf2ab4f345b0ac0ca291759e5c813d75` |
| `metadata.json` | `ad6b9f9cba6d090aa3ad0704e13f69ae8745e66e55e73dd09bc229c6646a274b` | `1330953c875a02e7ed2721b8a968ee40703313bc46c930a7a61ccbce90cbdb88` |
| `shell.json` | `561c0cca90f306733768ce9fdb5f583cbb750ab5e3df879a7fe44f9e2832fee4` | `3a64b651757ccb04e2add22c5929fc5cccddd5de8262d1932d20c88121b825a8` |
| `shell.log` | `5e5e95da8cd3aa60b1b83957524a5c0c0d3cfb2a735c6d6b7b490c101db00c83` | `2f0e31e55702863798986c561296dd365923d2665af6aae4482df6058a0c4a96` |
| `tests.json` | `2c22307fe6b216b033c904613e62a8309ac0782c987d59d7141449e029ba3cb3` | `257b8586bd40a9dc74f7764e5a68cf6011bdfd3ab1015b9406647ff15daece66` |

Rechecked Linux JSON SHA-256: `1a00a8703feea98542c27d411e4d62dca7e67c3e881ed181b8f6fb46bd334d6b`.

Combined JSON SHA-256: `6a47585aae27b22240ca6133d4be93840bf5adeeb7d1f4afc4758c4de7df9aac`.

Raw coverage, logs and review copies were task-owned temporary artifacts.
They were removed after review and receipt capture; the table preserves their
hashes, not the raw files. They cannot be supplied as a hosted producer bundle.

### Completion and preserved state

The following exact owned roots were removed and absence verified:

- `C:\codex\git-starter-kit\.tmp\gsk-final-win-20261016`.
- `C:\codex\git-starter-kit\.tmp\audit-remediation-20261016`.
- `/var/tmp/gsk-final-20261016-N23Gx7`.
- `/var/tmp/gsk-audit-remediation-20261016-env-8N391J`.

Nine earlier native fixture/environment roots were also verified absent,
including all five publication follow-up directories. The existing `.venv`,
`tools/quality/node_modules` and `tools/quality/external` were preserved.
Cleanup refused linked roots and checked resolved targets before deletion.
After cleanup, 175 frozen files and the exact reviewed final-report bytes were
checked again. The 40-path scope, empty root index, original HEAD and branch,
and the five published metadata files remain unchanged as intended. No root
commit, push, integration, tag, release or protection-setting change occurred.

Applied instruction files: `AGENTS.md`, `CODING_RULES.md`, `LANGUAGE_RULES.md`,
`DOCUMENTATION_RULES.md` and `BRANCH_RULES.md`; `COMMIT_RULES.md` applied to the
owned technical fixture commits only. No applicable instruction was bypassed.
Betterleaks could not complete its Windows scans; its failures and the passing
Gitleaks fallback are distinguished above. Hosted qualification remains behind
the approved plan's explicit authorization gate. Release rules were not
activated because no tag or publication was performed.

## Decisions and cleanup

- Use the task-owned ignored `.tmp` workspace for implementation copies and
  review packages; retain durable evidence here before deleting that workspace.
- Use the live, identical-SHA hosted full run as baseline, and distinguish the
  interrupted local attempt from a success. A local-only fault needs a base
  reproduction; this decision does not waive final qualification.
- Retain the plan's literal selected-HEAD content requirement for SemVer
  packaging, while preserving existing refusal guards and defined composition
  transformations. The first patch corrected modes but still copied locally
  authenticated bytes; reviewed follow-ups now select both blobs and attributes
  exclusively from the selected tree.
- Temporary artifacts belong only to this task. The interrupted baseline's
  process tree was stopped and its fixture directory removed; absence was
  verified. Worker fixtures and caches are cleaned by their owners. Existing
  `.venv`, Node dependencies and external-tool installations are preserved.

Local results and cleanup are recorded above. Hosted validation and measured
F14 release-sequence costs remain pending explicit authorization. No speed
improvement is claimed.
