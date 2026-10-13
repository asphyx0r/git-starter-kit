# Audit Remediation Implementation Plan

This approved plan implements the nineteen findings from the 2026-10-12 audit.
The candidate version is `v2.12.0`; preparing the candidate does not publish it.

## Goal and Constraints

- Start from `bace76a55c165d18b67bdc9e25b224dc725d4286` on
  `fix/audit-remediation`, preserving the existing fixes and unrelated files.
- Keep Python 3.11+, Node.js 22.12+, the Markdownlint CLI and consumer
  configuration contracts, staged validation, and exact pushed-object tests.
- Keep `Repository audit` and `Repository audit (manual)` check names, release
  event evidence, permissions, SHA-pinned actions, and existing coverage floors.
- Keep npm lifecycle scripts disabled. Hooks and audits never install tools.
- Do not rewrite published history, migrate other repositories, create a tag
  in the primary repository, or publish a GitHub Release.
- Update tests, documentation, templates, inventories, and package ownership
  in the same deliverable as their behavior change.
- Remove task-owned temporary artifacts and verify their absence. Keep permanent
  environments and intended candidate deliverables separately identified.

## Approved Decisions

- Preserve `markdownlint-cli2`; fix `braces` locally with independently checked
  source provenance, before/after hashes, compatibility and regression tests.
- An explicit security gate can attest the fixed installed code while retaining
  the upstream npm advisory in its raw report. It must reject every other high
  advisory, unknown/ambiguous attribution, invalid patch, and registry failure.
- Keep single-maintainer governance. Finding 11's lack of independent review is
  an accepted, documented exception with mandatory human publication approval.
- Prepare a candidate without tagging or releasing it. GitHub activation is a
  separate required operation; findings 02/11 stay open until verified live.

## Execution

### Task 1: Dependencies and Reproducible Environment

Findings: **01, 03, 09, 10, 13, 15**.

- Update Mypy to 2.4.0, Ruff to 0.16.10, Coverage to 7.16.2 and add
  pip-audit 2.10.1, synchronizing the registry and hashed locks.
- Add exact npm overrides for smol-toml 1.9.1 and KaTeX 0.18.2 and verify every
  installed occurrence. Preserve direct Markdownlint and Commitlint versions.
- Replace vulnerable recursive braces walkers with iterative traversal while
  preserving outputs, ordering, options, and existing limits.
- Record the exact upstream package, advisory, license, patch, and executable
  file hashes. Do not disguise the upstream version or suppress its advisory.
- Add `tools/quality/npm-security.py` with `patch`, `verify`, and `audit`.
  Patch application is idempotent, refuses unexpected bytes and links, and
  restores already replaced files after failure. Apply explicitly after npm ci.
- A high finding is attested only when all its advisory leaves are the recorded
  braces advisory and every installed affected occurrence matches the patch.
- Rebuild the broken local environment safely; provision pinned external tools
  with the existing installer. Do not change global user tooling.
- Maintain Dependabot proposals by committing coherent declarations/locks;
  never modify CI checkout content to hide drift. Audit both Python locks.
- Verify: adversarial patch/audit tests, deeply nested patterns, differential
  compatibility cases, lock consistency, runtime checks and real CLI behavior.

### Task 2: Transactions and Type Coverage

Findings: **04, 05, 06**.

- Restore release outputs after interrupts and re-raise the original exception;
  keep original, restoration, and cleanup diagnostics.
- Reject invalid initialization tags before writes, chmod, or Git index changes.
- Include every tracked production Python tool in Mypy, including new tools.
- Verify: interruptions at each replacement, failed restoration/cleanup, invalid
  tags with unchanged files/index, valid existing SemVer behavior and Mypy scope.

### Task 3: Focused Workflow Contracts

Finding: **19**.

- Replace redundant full workflow mirrors with explicit invariants, retaining
  the loader and public validator interface.
- Keep strict event/check names, permissions, action identity/pinning, trusted
  refs, guard order, token boundaries and sealed artifact verification.
- Admit harmless presentation/cache changes without admitting extra dangerous
  execution in privileged jobs. Preserve all existing adversarial tests.
- Verify: current workflows and planned optimizations accepted; every dangerous
  mutation still rejected; no regex-only replacement for script semantics.

### Task 4: Precise Hooks and Runtime Preflight

Findings: **12, 16**; integrates **09**.

- Retain the three wrappers, snapshots, isolated clones and existing deadlines.
- Extend check-versions with repeatable `--runtime --tool NAME` and a distinct
  runtime location when expected declarations come from the staged snapshot.
- Verify the executable actually selected, not only distribution metadata.
- Route isolated test changes to their own family; select all impacted tests
  for shared modules. Select focused pre-commit/pre-push suites for their hooks.
- Verify: routing positives/negatives, wrong tools, partial staging, linked
  worktrees, spaced paths, multiple pushed refs and consumer configurations.

### Task 5: CI and Cross-Platform Coverage

Findings: **07, 17, 18**; integrates Task 1 security controls.

- Run cheap declaration checks before expensive installs.
- Move real project checks into existing OS jobs and remove standalone no-op
  project jobs. Preserve consumer validation and aggregate failure semantics.
- Measure Windows coverage and combine both OS measurements from the same run,
  SHA and inputs. Keep Linux floors and also enforce combined floors.
- Cancel superseded ordinary branch pushes using ref-based groups; preserve PR,
  tag, release and release-preflight evidence and immutable revision checks.
- Keep dependency caches tied to locks and restrictive permissions.
- Verify: missing/stale/wrong-SHA coverage rejected; no mandatory failed or
  missing check can become an aggregate success; OS paths combine correctly.

### Task 6: Documentation and Change Discipline

Finding: **14**; integrates every task's documentation.

- Use independently reviewable commits containing behavior, tests and docs.
- Preserve large historical commits; improve future change boundaries.
- Update source guides and consumer templates for provisioning, attestation,
  network checks, test routing, coverage, check names and governance.
- Distinguish candidate instructions from published v2.11.7 capabilities.
- Keep changelog sections based on real tags; record candidate changes here
  and in the remediation evidence until an actual release is authorized.
- Verify: Markdown, links, inventories, ownership and executable examples.

### Task 7: Candidate Artifacts

Finding: **08**.

- Prepare VERSION, release manifest, starter manifest and SHA256SUMS for the
  candidate using existing tools and exact selected Git content.
- Derive dates from actual preparation and retain/justify other metadata.
- Check the selected index, then the final commit, after all substantive changes.
- Qualify packages, initialization, upgrades and restoration in disposable
  clones/fixtures at the exact candidate commit; only fixture tags are allowed.
- Verify new runtime/attestation files are distributed and candidate provenance
  never asserts publication. Remove owned fixtures after qualification.

### Task 8: Separate GitHub Activation

Findings: **02, 11**.

- Prepare current/proposed settings before applying them. Identify the existing
  App from authoritative configured/proprietor metadata; never invent its ID.
- Add a distinct main Restrict updates ruleset with only that App as bypass.
  Keep ordinary protections without App bypass and support only squash merges.
- Make guarded preflight reject incomplete activation.
- Require asphyx0r to approve the release environment, allowing self-approval
  for the accepted single-maintainer policy. Retain existing ref restrictions.
- Document zero independent PR reviews, mandatory checks/conversation resolution
  and the human publication gate as the explicit governance exception.
- Verify live settings and a disposable PR: native merge blocked, App still
  bound by ordinary checks. Keep findings open until this proof exists.

## Completion Contract

For each finding, retain change, test, documentation and authoritative proof.
Run the complete profiles, OS suites, pinned linters, security gates and package
qualification on the exact candidate. Explain platform skips individually.
No partial success substitutes for full qualification. A fresh whole-branch
review precedes completion; fix consequential findings with regression tests.

## Progress

Implementation started on 2026-10-12. No finding is closed by this plan alone.
