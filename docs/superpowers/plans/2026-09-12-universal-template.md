# Universal Git Starter Kit Implementation Plan

## Goal and approved specification

Implement the thirteen retained findings of the read-only v2.10.0 audit without regressing existing repositories.
The complete user-approved specification is the plan in the conversation "Auditer le template Git universel".
This file records its executable tasks and acceptance criteria for continuity across sessions.

## Global constraints

- New projects use only the published with-agent-rules ZIP; clones maintain the starter itself.
- Keep one initialization ZIP and the existing companion upgrade toolkit.
- Every newly built initialization ZIP includes the latest published agent-coding-rules release resolved at build start.
- Preserve the upstream rule files faithfully, their provenance and all mandatory requirements.
- Initialize on main regardless of local Git defaults; keep CI compatible with main and master.
- Preserve the initial annotated v1.0.0 tag on the first system-only commit.
- Prepare VERSION, SHA256SUMS and manifest.json before that first commit, without invented deployment metadata.
- Separate starter maintenance, distributed core checks and explicitly declared project checks.
- Missing project checks warn without blocking; an explicitly declared failing check blocks.
- Advanced automations are explicitly enabled for new projects. Existing repositories retain compatible behavior.
- Protect project-owned files, settings, history, versions, branches and application layout during cumulative upgrades.
- Keep ambiguous gitignore rules commented and explained; preserve legitimate sources and fixtures.
- Provide Bash, PowerShell, Perl, Python, Java, Rust, Go, Laravel, JavaScript and C/C++ ignore sections.
- Laravel is created in laravel/ after v1.0.0 using Composer create-project; public root is laravel/public/.
- Official tested platforms are Windows x64 and Linux x64. Do not claim macOS support.
- Publication, hosted main migration and downstream patch application retain their distinct authorization gates.
- Never edit upstream agent rule files to bypass a requirement.
- No automatic deletion of obsolete downstream files and no hand-edited generated provenance.

## Task 1: Project configuration contract

**Files:** tools/project_config.py and tests/test_project_config.py.

Create a standard-library-only shared loader and read-only CLI for .starter-kit-project.json.
Do not integrate it into existing hooks or workflows in this task.

The version 1 input object has exactly these fields:

```json
{
  "schemaVersion": 1,
  "repositoryRole": "project",
  "releaseKind": "repository",
  "automations": {
    "agentRulesSync": false,
    "guardedMerge": false,
    "releasePreflight": false
  },
  "checks": []
}
```

repositoryRole accepts project or source; releaseKind accepts repository or deployment.
All automation fields are required booleans. An existing file with unknown, missing or malformed fields is an error.
Each check has a unique nonempty name, nonempty argv string array, workingDirectory and platforms.
workingDirectory is a portable relative path, including dot for the repository root; reject escaping or absolute paths.
platforms is a nonempty unique array of linux and/or windows. Reject NULs and empty command names.
Do not require the working directory to exist during configuration parsing; execution will check it again.
Check resolved paths stay within the repository when an existing symlink or junction is encountered.

Missing configuration returns explicit legacy mode, deployment releases, all automations enabled and no declared checks.
Do not create a configuration file when it is missing. Legacy mode is never a fallback for malformed content.

Expose load_configuration(root: Path) returning a Configuration value with mode, repository_role, release_kind,
automations and checks, plus a stable as_dict() JSON representation and ConfigurationError.
Each parsed check exposes name, argv, working_directory and platforms.
Provide default_project_configuration() for producing the new-project configuration above.
The read-only CLI supports --repository-root, --get for a dotted effective-configuration key, --help, --version,
--dry-run and --verbose. Default output is the complete effective JSON configuration.
For --get, strings are printed as text; other values use JSON, including lowercase booleans.
Unknown requested keys and invalid input return nonzero without a traceback unless verbose was requested.

- [x] Write and observe failing tests for legacy preservation, explicit new-project defaults and malformed input.
- [x] Implement the smallest loader and CLI satisfying the contract.
- [x] Test path escapes, duplicate checks, invalid argv/platforms and read-only CLI behavior.
- [x] Run focused tests, Ruff and Mypy for the new module; self-review and provide evidence for independent review.

## Task 2: Repository inventory release format

**Files:** tools/release-artifacts.py, templates/release schemas and tests/test_release_artifacts.py.

- [x] Add a separately versioned repository inventory manifest, keeping existing deployment format 2.0.0 compatible.
- [x] Add explicit prepare selection for repository manifests and the Git index before HEAD exists.
- [x] Include version, UTC date and verifiable file inventory without fictitious deployment identity or policy.
- [x] Preserve existing checksum exclusions and canonical file/mode inventory behavior.
- [x] Test preparation before the first commit, staged content versus working tree, corrupt/missing artifacts and tags.
- [x] Preserve all existing deployment preparation and validation behavior and CLI invocations.

## Task 3: Initializers

**Files:** tools/git-init.sh, tools/git-init.ps1 and focused initializer tests.

- [x] Restore executable Git index modes from the package inventory, including Windows extraction without chmod bits.
- [x] Resolve local Commitlint before PATH, consistently with hooks.
- [x] Initialize directly on main, prepare initial changelog and release inventory from staged system files.
- [x] Keep the pre-tag changelog minimal; do not invent history or try to embed the first commit's own checksum.
- [x] Commit only after validation, then create annotated v1.0.0 on that exact first commit.
- [x] Keep confirmations and historical CLI options, including the explicit tag override; v1.0.0 remains the standard.
- [x] Verify optional remote publication separately; never claim remote default main without observing it.
- [x] Test Windows/Linux paths with spaces, missing tools, existing history, failures and initial-tag consistency.

## Task 4: Core and application validation integration

**Files:** repository-audit dispatcher/modules, quality configuration and relevant tests.

- [x] Use the shared configuration reader and the managed-file inventory instead of treating all tools/tests as core.
- [x] Keep source maintenance tests and coverage in the canonical repository, with no consumer dependency on them.
- [x] Make consumer SemVer, static checks and smoke checks independent of source-only files.
- [x] Run explicitly configured project checks against the exact pushed revision and CI revision, with bounded processes.
- [x] Display separate core/project/automation results. Empty checks warn; only the initial system state is non-applicable.
- [x] Include relevant ps1, psm1 and psd1 files within their owning scope.
- [x] Preserve legacy behavior for an absent configuration and public audit entrypoints.
- [x] Test Bash, PowerShell, Go and Laravel path routing, failed checks, missing tools and immutable revision selection.

## Task 5: Workflows and explicit automations

**Files:** workflows, workflow-contracts.py, release verification/skill integration and tests.

- [x] Cover main/master pushes and PRs while preserving tag, release and preflight triggers.
- [x] Keep the required aggregate name Repository audit; require all selected jobs to succeed.
- [x] Respect automation configuration on every event, including releases.
- [x] Avoid dependencies, credentials and privileged operations for disabled functions.
- [x] Keep permission separation and exact event/ref/SHA/result verification when functions are enabled.
- [x] Keep new configuration source-owned for canonical defaults and project-owned after distribution.
- [x] Test enabled/disabled/legacy modes, invalid configuration and required-check aggregation.

## Task 6: Consumer package and documentation

**Files:** package builder, starter manifest, source/project templates and package tests.

- [x] Resolve and pin latest published agent rules once per build, fail on unavailable or unverifiable upstream content.
- [x] Preserve rule bytes and provenance and verify the composed package, not just its file list.
- [x] Exclude source-only maintenance tests, manufacturing files, migration journals and this implementation plan.
- [x] Provide consumer documentation without source history, private workstation paths or false security contacts.
- [x] Keep starter-specific Commitlint scopes canonical; allow application scopes in the consumer configuration.
- [x] Preserve legal notices, licensing and legitimate provenance links.
- [x] Replace CONTRIBUTING prose-string dependencies with technical behavior checks; make shipped templates usable.
- [x] Check relative links and compute inventories after every composition step.
- [x] Keep upgrade toolkit content and checksums compatible and preserve initialize-only/merge strategies.

## Task 7: Conservative ignores and Laravel onboarding

**Files:** .gitignore and consumer/source onboarding documentation.

- [x] Provide the ten requested language sections and explain that headings do not scope Git patterns.
- [x] Comment contextual and ambiguous patterns with activation guidance; preserve source, fixtures and lock files.
- [x] Keep precise exclusions for known local core outputs, secrets and operating-system artifacts where unambiguous.
- [x] Check examples from the audit with git check-ignore, including log/logger.go, build.sh, expected.out and archive.zip.
- [x] Document composer create-project --prefer-dist --remove-vcs laravel/laravel laravel after initial v1.0.0.
- [x] Document prerequisites, empty destination, a single Git repository, laravel/tests and laravel/public.
- [x] Keep Laravel-generated files in the application scope; do not automatically merge its files with core files.

## Task 8: Local tool provisioning

**Files:** tools/quality/install-external-tools.py, version registry, tests and usage documentation.

- [x] Support an explicit local installation root without requiring RUNNER_TEMP.
- [x] Keep existing CI confinement, integrity-pinned versions, archive safety and process timeouts.
- [x] Provision only selected capabilities and support Windows x64 and Linux x64.
- [x] Document unsupported macOS and application-owned language dependencies.
- [x] Test local and CI roots, invalid paths, missing tools, corrupt archives and platform selection.

## Task 9: End-to-end package and cumulative patch qualification

**Files:** package and upgrade test suites and upgrade documentation.

- [x] Test the final composed ZIP through extraction, initialization, first commit/tag and consumer validation on both OSes.
- [x] Include a real Laravel project with a pinned test version and focused Bash, PowerShell and Go project scenarios.
- [x] Test patches from supported historical formats, v2.7.0 and v2.10.0 to the candidate package.
- [x] Preserve source/current provenance, application content, local settings and obsolete files.
- [x] Verify equivalent application validation before and after patches, with explicit project-owned commands or CI.
- [x] Verify conflicts, CRLF/modes, external rollback, interruptions, concurrent changes and repeat-apply no-op behavior.
- [x] Keep new lightweight defaults out of existing projects unless adopted explicitly.
- [x] Run the complete relevant source checks with the declared tools and retain all independent review findings.

## Task 10: Hosted migration, delivery and downstream rollout gates

- [ ] Integrate dual-branch CI before migrating the canonical default branch.
- [ ] Re-read classic protection, rulesets, release environment policies and open PRs before any hosted changes.
- [ ] Preserve Repository audit strict checking, administrator enforcement and release-tag protection.
- [ ] Migrate canonical main/default/upstream references and verify open PR retargeting without changing PR contents.
- [ ] Do not automatically delete master or change any downstream default branch.
- [ ] Publish only after separately authorized release operations and final package/toolkit qualification.
- [ ] For each authorized downstream target: exact base/target packages, plan, conflict resolution, external backup, apply,
  core/project validation, authorized Git/PR integration and verification of the final merged SHA.
- [ ] Update git-core only after verified successful application and within the authorized tracking scope.
- [ ] Never reinitialize a downstream repository or rewrite its tags, history, versions or application layout.

## Completion evidence

No task is complete because only a narrow check is green. Track implementation, independent review and relevant tests.
Do not declare the goal achieved until every approved requirement has authoritative evidence or a separately resolved gate.
Temporary files, test caches and review workspace must be tracked and cleaned after they are no longer needed.
