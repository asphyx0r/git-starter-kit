# Audit remediation F01 to F19

## Goal and authority

Implement the plan approved in this chat, with a regression test, minimal
correction, focused verification and final integrated qualification for each
finding. The starting commit is `3de324856a6d6cdceb7ba19130a2dadca5c741c3`.
Work belongs on `fix/audit-remediation-2026-10-27`.

The approved chat plan is the specification. This file records its execution
contract; it does not authorize integration, tags or a release.

## Global constraints

- Preserve published history, version identification and release baselines.
- Preserve staged snapshots, exact pushed objects, deadlines, rollback,
  customized consumer files and no-clobber publication.
- Keep the existing workflow permissions, SHA action pins, required check names,
  pip/npm download caches and Linux/Windows parallelism.
- Keep Python 3.11 on Ubuntu 24.04, Python 3.14 on Windows 2025, Node 24.20.0,
  and the 85% global and branch coverage floors for Linux and combined reports.
- Keep Dependabot with controlled completion of its proposals. Its documented
  rejection of incomplete proposals remains intentional.
- Explicitly remove the public npm patch and verify commands; update known
  callers and document the CLI change. Keep a blocking audit-only wrapper.
- Keep merge exit statuses 0/1/2/3 and existing exact-postcondition recovery.
- Branch publication requires separate user authorization, then a draft PR and
  exact-SHA hosted qualification. Do not integrate or publish a release.
- Track and remove every task-owned temporary artifact. Preserve existing ones.

## Tasks and acceptance

Each code correction uses a failing regression before implementation, focused
checks, independent review and a coherent commit with its tests and applicable
documentation. F18 governs all commits; do not rewrite old commits.

| Task | Findings | Deliverable and acceptance |
| --- | --- | --- |
| A | F01-F04 | Target certifi 2026.10.19 and filelock 4.2.1 in the existing Python lock under Python 3.11; target markdown-it 15.0.3 and fast-uri 3.1.9 through exact existing npm overrides. Preserve other pins and require integrity-checked clean installations and renewed audits. |
| B | F13, F15 | Reject unsupported or duplicate normalized requirement declarations with file/line context; retain valid extras, comments, versions and hashed lock blocks. Prove incomplete and completed Dependabot proposals using the existing controlled procedure. |
| C | F16 | Remove brace-specific patch payloads, exemptions, unique fixtures and all active patch calls. Keep npm audit with its 120-second containment, isolated cache, dry-run and fail-closed diagnostics; block high/critical findings. Update active contracts, tests, docs and consumer composition. |
| D | F05 | Preview composition reads tracked NUL-separated Git paths and worktree bytes. SemVer retains authenticated HEAD selection/bytes. Exclude ignored and untracked files from ZIPs and inventories; preserve prior destination on failure. |
| E | F06, F14 | Add upgrade schema 4 with independent baseline content kind; read schemas 1-3 unchanged and keep full inventories at schema 3. Reject invalid adoption schema types without traceback or ancestry queries. |
| F | F07, F08, F17 | Repair mixed CLI option syntax without swallowing unknown flags, preserve Windows quoting repair, clamp ZIP dates, and preserve primary plus cleanup diagnostics. |
| G | F09, F10 | Retain cumulative timeout outputs once. Report confirmed merge identity separately from failed cleanup, use controlled status 1 for cleanup-only failure, preserve primary statuses and interrupts, never retry mutation. |
| H | F11, F12 | Expand shell wildcard to all six existing suites exactly once under the 900-second family budget. Share tracked-file spelling selection between source and read-only profiles; preserve consumer/staged selection. |
| I | F19 | In qualification decision job, use direct full decision for source PRs, ordinary branch pushes and manual runs; skip reuse setup/downloads there. Preserve OS fresh captures, aggregate producer sealing, tag/release verification and seven-day evidence validity. |

## Compatibility decisions

Only cumulative upgrade manifests advance to schema 4. Their required
`baseContentKind` is `text`, `binary`, or null; null corresponds exactly to
absent baseline digests. `contentKind` still describes the target. Permit
`starter-kit-state` in upgrade schemas 3 and 4. Historical schemas keep their
original digest semantics.

For encoding transitions, update only content matching the authenticated base,
recognize an already aligned target and conflict on customized content.
Preserve CRLF normalization and raw-byte concurrency checks. Do not merge text
across classifications or accept malformed legacy UTF-8 by a general fallback.
Old readers must reject schema 4 cleanly; new readers retain old formats.

Invalid adoption schema values, including booleans, lists and objects, return
the existing unsupported-evidence result. Supported integers remain 1 and 2.

After merge confirmation, cleanup-only failure prints the known repository,
PR and head plus the residual path/error and returns 1, without traceback.
Combined failures preserve the primary exception/status and interrupts.
Unknown post-dispatch outcomes remain 3. Existing requester recovery to 0 on
an exactly confirmed merge and successful local cleanup remains unchanged.

Obsolete patch files in upgraded consumers stay preserved and inert. Run
script-disabled npm ci to restore upstream installed bytes. Do not add an
automatic deletion migration or rewrite historical package assertions.

## Qualification and handoff

1. Establish an immutable baseline and selected-runtime evidence.
2. Integrate dependency and guard changes before removing the obsolete patch.
3. Use one owner for shared workflow, contract, profile and documentation files.
4. Run focused Python/shell tests and language checks for each correction.
5. Run the complete integrated local suite, coverage, static checks, dependency
   audits, secret scans and package/init/upgrade qualification.
6. Preserve all still-relevant tests. Update obsolete patch-specific tests and
   distinguish current packages from historical releases.
7. Independently review the final branch and record F01-F19 closure evidence.
8. After separate publication authorization, open the draft PR and require the
   Linux/Windows and aggregate checks on its exact SHA.
9. Remove owned temporary artifacts and verify repository and cleanup state.

No missing check is a pass. Live production release/reuse qualification is a
separate authorized operation. Published VERSION, manifest, SHA256SUMS and
starter baselines remain unchanged until separate release preparation.
