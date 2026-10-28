# Windows local qualification follow-up

This record closes the two local Windows anomalies retained in the
[October 27 audit evidence](2026-10-27-audit-remediation.md). The completed local
qualification passes on the corrected source snapshot. Earlier diagnostic
failures and a discarded harness attempt are recorded separately below.

## Source and verification identity

- Base: `5fe4998047862297c0cbbc209817f00570c47830`, the squash merge of PR #100.
- Local branch: `fix/windows-local-qualification`; no publication or integration.
- Measured code: base plus the three-file patch with SHA-256
  `d382c0c209112d0519562a6f22f2101508cf36e1019ba84f3802bc79e53d464a`.
- The manifest of all 172 tracked source files has SHA-256
  `8287d299a9b8984756146867db08d53480431d332976426ff79a72cf88e81345`.
  Every file matched before and after both completed platform runs.
- This report and its inventory entry are documentation added after measurement.
  Executable sources and tests remain identical to the measured snapshot.
- Evidence is local only. No synthetic GitHub run, attempt or candidate commit
  identity was assigned, and no hosted CI result is claimed for this patch.

## Corrections and their limits

### Windows installer publication

The unchanged PSScriptAnalyzer archive test intermittently failed at the native
directory rename, despite an absent destination, normal attributes and full
permissions. A real Win32 handle held on a staging descendant reproduces
`WinError 5`; holding the staging directory itself reproduces `WinError 32`.
Closing the controlled handle permits the same rename. The owning process in
the original intermittent refusals was not identified; no antivirus attribution
is made. The Windows [file-sharing contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
explains why a reader can prevent delete or rename access.

[The installer](../../../tools/quality/install-external-tools.py) now retries
only Windows permission errors 5 and 32, for at most a 100 ms retry window with
10 ms pauses. Both private preparation and public publication use that helper.
Each attempt keeps the native atomic rename without overwriting a destination.
A persistent lock, unrelated error or competing destination still fails;
existing concurrent data is preserved. Download and probe deadlines are unchanged.

Five new Windows-only regression tests exercise real handles, release after the
first refusal, persistent refusal, a concurrent destination, private preparation
and unrelated errors. The recovery cases failed against the original code before
the fix. Ten focused tests and 30 additional repetitions of the historical case
passed before the complete qualification. The five new native tests are skipped
on Linux; no existing skip was added to make a failing Windows test pass.

### Short process deadline observation

The original short-deadline test reproduced its failure under Python 3.14.9,
coverage 7.16.2, cp1252 and UTF-8 mode 0. Instrumentation showed that the job had
requested termination, the execution budget was exhausted and an immediate
`poll()` still returned `None`. The same child subsequently exited with code 1
without an additional kill. Windows process termination is
[asynchronous](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess).

[The test](../../../tests/test_release_artifacts.py) now uses `wait(timeout=1)`,
matching the adjacent batch test, to observe and reap the terminated child.
The operational deadline remains 0.1 seconds, the child still sleeps for 60
seconds unless terminated, and both pipe-closure assertions remain. No process
runner or release-artifact production code changed. Five fresh focused runs
passed before qualification; the complete Windows run also passes this case.

## Completed local qualification

Counts include skipped cases. No expected failures or unexpected successes
were reported. Windows retains the existing 19 platform or capability skips;
Linux has its existing 11 plus the five new Windows-native cases.

| Check | Linux | Windows |
| --- | --- | --- |
| Python | 3.11.17 | 3.14.9, cp1252, UTF-8 mode 0 |
| Node / coverage | 24.20.0 / 7.16.2 | 24.20.0 / 7.16.2 |
| Complete Python discovery | 754 cases, 0 failures/errors, 16 skips | 754 cases, 0 failures/errors, 19 skips |
| Measured Python runner | 535.558 s | 1,503.458 s |
| Official shell suites | 6/6 pass, 88.373 s summed | 2/2 pass, 142.926 s summed |
| Static validation | Complete before/after profiles pass | Fast checks and PowerShell analysis pass |
| Runtime checks after qualification | All pins and 55 distributions unchanged | Selected runtimes match; dependency consistency passes |

Linux uses native Debian storage under WSL, not the hosted Ubuntu image.
Windows is the local host, not a Windows 2025 hosted-runner image. Private
Python, Node and PowerShell resources were used where needed; global tool
installations were not changed. Linux npm and OSV audits of both quality and
release locks report no known vulnerabilities. Wheel hashes were checked by
`pip --require-hashes` during installation; OSV advisory lookup is not a
substitute for that integrity check.

The original branch coverage databases were independently reread and combined.
All 25 measured source-file hashes matched across platforms. The unchanged
minimum is 85% for both global and separate branch coverage.

| Measurement | Global | Statements | Branches | Gate |
| --- | --- | --- | --- | --- |
| Linux | 7,558/8,300 = 91.06% | 5,512/5,962 = 92.45% | 2,046/2,338 = 87.51% | PASS |
| Windows, informational | 7,586/8,300 = 91.40% | 5,539/5,962 = 92.91% | 2,047/2,338 = 87.55% | No separate gate required |
| Combined | 7,673/8,300 = 92.45% | 5,585/5,962 = 93.68% | 2,088/2,338 = 89.31% | PASS |

Raw database SHA-256 values are
`42754a0d77756c653ca9ba231c169e65c1add3991d7e95f3bac4881f6c9a772c`
(Linux) and
`6884f4698c4370e6c9c02d1b40b9d19e473105a24a2c11c44746eeeb37fa08ec`
(Windows). These hashes identify the measurements; they do not reconstruct
temporary databases after cleanup.

## Earlier attempts retained in the assessment

A preliminary release-artifact module run completed 53 tests with one error in
the unchanged interruption fixture. Its two-second deadline expired before the
first blob and before the intended `KeyboardInterrupt` could be injected.
The test AST and its three connected production modules match the base. The
cause of the startup delay was not established, and no deadline was increased.
This observation was not counted as a passing qualification. The same case
passes in the completed canonical Windows discovery.

The first complete Windows attempt used an incorrect private harness: its
temporary directory was inside the checkout. It was interrupted after the
recorded 187 progress markers, with one error and one failure, and never counted
as a completed discovery. A controlled existing-test pair proved the coverage
failure: moving only TEMP outside the checkout, at exactly the same path length,
changed the report key from checkout-relative to absolute. Both variants retained
identical 4/4 statement and 2/2 branch totals; only the path assertion failed
inside the checkout. Neither the assertion nor production code was changed.

The other early error's detailed traceback was unavailable when that invalid
run was stopped; its cause is not claimed. Its corresponding archive case passes
in the final discovery. The corrected harness uses a private system temporary
directory outside the checkout and prints original unittest failures immediately.
The completed Windows results above come from that fresh, unfiltered discovery.

## Scope and housekeeping

No hosted CI, merge, tag, release or application-runtime validation is claimed.
The project-check command returns zero with its explicit warning that no
application checks are configured. The optional mounted-cloud test remains
disabled, as in the original local qualification.

Instruction scope: `AGENTS.md`, `BRANCH_RULES.md`, `CODING_RULES.md`, applicable
Python rules in `LANGUAGE_RULES.md`, and `DOCUMENTATION_RULES.md`. Full Markdown
validation and focused spelling validation cover this report and its inventory
entry after qualification. Task-owned scratch resources are removed before
handoff; the source virtual environment, quality dependencies and pre-existing
caches are retained.
