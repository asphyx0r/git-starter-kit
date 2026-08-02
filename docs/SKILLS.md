# Skills

This file is a documentation-only inventory of the skills available in this
repository. It is not loaded or executed by Codex. Each skill's `SKILL.md` file
is the authoritative source for its behavior and instructions.

## Available skills

| Skill | Purpose | Path |
| --- | --- | --- |
<!-- markdownlint-disable-next-line MD013 -->
| **Git Commit, Push, Tag, and GitHub Release** | Runs guarded SemVer analysis, exact commit validation, audit preflight, tag, atomic final push, and an optional template-based GitHub Release. | `.agents/skills/git-commit-push-tag` |

## Git Commit, Push, Tag, and GitHub Release

- **Slug:** `git-commit-push-tag`
- **Path:** `.agents/skills/git-commit-push-tag`
- **Invocation:** `$git-commit-push-tag`

Runs the canonical guarded SemVer analysis, exact-file commit validation,
remote SHA preflight, tag, atomic final push, synchronization checks, and
optional template-based GitHub Release workflow.

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
- Prevalidate the release SHA, then require every expected branch and tag audit
  run around the atomic final push.
- Complete a requested, template-based GitHub Release after every applicable
  repository-specific check succeeds.

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
- The starter-only release extension must be readable when the exact
  `asphyx0r/git-starter-kit` remote is active. It is intentionally omitted
  from packages distributed to derived repositories.

### Limitations

- The generic reference and any applicable repository-specific extension are
  the complete behavioral source of truth and must be followed exactly.
- If the canonical reference cannot be read completely, the skill stops
  without modifying the repository.
