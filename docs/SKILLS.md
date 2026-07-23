# Skills

This file is a documentation-only inventory of the skills available in this
repository. It is not loaded or executed by Codex. Each skill's `SKILL.md` file
is the authoritative source for its behavior and instructions.

## Available skills

| Skill | Purpose | Path |
| --- | --- | --- |
<!-- markdownlint-disable-next-line MD013 -->
| **Git Commit, Push, Tag, and CI-Gated GitHub Release** | Runs the canonical guarded SemVer analysis, validated commit, tag, atomic push, synchronization checks, and optional template-based, CI-gated GitHub Release workflow. | `.agents/skills/git-commit-push-tag` |

## Git Commit, Push, Tag, and CI-Gated GitHub Release

- **Slug:** `git-commit-push-tag`
- **Path:** `.agents/skills/git-commit-push-tag`
- **Invocation:** `$git-commit-push-tag`

Runs the canonical guarded SemVer analysis, validated commit, tag, atomic push,
synchronization checks, and optional template-based, CI-gated GitHub Release
workflow.

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
- Perform an explicitly validated commit, tag, atomic push, and synchronization
  checks.
- Complete a requested, template-based GitHub Release only after its automatic
  Release package CI succeeds.

### Usage examples

```text
Use $git-commit-push-tag to analyze the next SemVer bump.
Mutate only with an explicit BUMP, and complete a requested GitHub Release
only after its automatic Release package CI succeeds.
```

### Contents

```text
.agents/skills/git-commit-push-tag/
├── agents/
│   └── openai.yaml
├── assets/
├── references/
│   └── git-commit-push-tag.txt
├── scripts/
└── SKILL.md
```

### Dependencies

- `.agents/skills/git-commit-push-tag/references/git-commit-push-tag.txt` must
  be readable in full before the skill takes any action or runs any Git
  command.

### Limitations

- The canonical reference is the sole behavioral source of truth and must be
  followed exactly.
- If the canonical reference cannot be read completely, the skill stops
  without modifying the repository.
