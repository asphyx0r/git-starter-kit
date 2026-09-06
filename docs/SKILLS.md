# Skills

This file is a documentation-only inventory of the skills available in this
repository. It is not loaded or executed by Codex. Each skill's `SKILL.md` file
is the authoritative source for its behavior and instructions.

## Available skills

| Skill | Purpose | Path |
| --- | --- | --- |
<!-- markdownlint-disable-next-line MD013 -->
| **Git Commit, Push, Tag, and GitHub Release** | Runs guarded SemVer analysis, release-artifact preparation, audit preflight, tag, atomic final push, and an optional template-based GitHub Release. | `.agents/skills/git-commit-push-tag` |

## Git Commit, Push, Tag, and GitHub Release

- **Slug:** `git-commit-push-tag`
- **Path:** `.agents/skills/git-commit-push-tag`
- **Invocation:** `$git-commit-push-tag`

Runs the canonical guarded SemVer analysis, exact-file commit validation,
evidence-backed release-metadata resolution and validation, deterministic
release-artifact preparation, remote SHA preflight, tag, atomic final push,
synchronization checks, and optional template-based GitHub Release workflow.

### When to use

- Use it only when `$git-commit-push-tag` is explicitly invoked or the skill is
  explicitly requested by name.
- Use it to analyze the next SemVer bump and, after an explicit bump, carry out
  the guarded commit, tag, atomic push, synchronization, and optional release
  workflow.

### When not to use

- Do not use it through implicit invocation.

### Key capabilities

- Analyze the next SemVer bump before mutation.
- Commit the exact file accepted by Commitlint through the repository hooks.
- Keep the release target fixed while preparing one intention per dedicated
  branch and guarded pull request on protected or shared targets. Require the
  exact post-merge audit and revalidate the merged tree between intentions.
- Resolve release metadata from authoritative project and release evidence,
  request only unresolved or contradictory values, then require explicit user
  validation.
- Generate and validate `VERSION`, `SHA256SUMS`, and `manifest.json` without
  inventing release metadata.
- Prevalidate the release SHA, then require every expected branch and tag audit
  run around the atomic final push. Verify that the push filter covers the
  unique `codex/release-preflight-*` ref before mutation.
- Prevalidate release workflows and required GitHub App configuration before
  mutation when a GitHub Release is requested.
- Complete a requested, template-based GitHub Release only after the exact
  `Agent rules update` and `Repository audit` release runs, plus every
  applicable repository-specific run, succeed.
- For the canonical starter repository, verify the sealed build/publication
  boundary and exactly three assets: both ZIPs and their `SHA256SUMS` file.
  Validate all GitHub digests and the checksum file's exact two entries.

### Usage examples

```text
Use $git-commit-push-tag to analyze the next SemVer bump.
Mutate only with an explicit BUMP, and complete a requested GitHub Release
only after every applicable repository-specific check succeeds.
```

### Contents

```text
.agents/skills/git-commit-push-tag/
├── agents/
│   └── openai.yaml
├── assets/
├── references/
│   ├── git-commit-push-tag.txt
│   └── git-starter-kit-release-package.txt
├── scripts/
└── SKILL.md
```

### Dependencies

- `.agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt` must
  be readable in full before the skill takes any action or runs any Git
  command.
- Every repository must retain active `Repository audit` and
  `Release artifacts` workflows. A requested GitHub Release additionally
  requires the active `Agent rules update` workflow, the repository variable
  `AGENT_RULES_APP_CLIENT_ID`, and the repository secret
  `AGENT_RULES_APP_PRIVATE_KEY`.
- The starter-only release extension must be readable when the exact
  `asphyx0r/git-starter-kit` remote is active. It is intentionally omitted
  from packages distributed to derived repositories.
- The pull-request path requires the guarded merge tool, pinned Commitlint,
  and active guarded merge workflow to be installed on the release target.
  Missing prerequisites stop the skill; it does not bootstrap them itself.

### Limitations

- The generic reference and any applicable repository-specific extension are
  the complete behavioral source of truth and must be followed exactly.
- The preflight can verify that the GitHub App secret exists, but only the
  mandatory `Agent rules update` run proves that its value and installation
  access work.
- If the canonical reference cannot be read completely, the skill stops
  without modifying the repository.
