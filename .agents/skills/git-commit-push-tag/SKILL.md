---
name: git-commit-push-tag
description: >-
  Execute the canonical guarded workflow for SemVer bump analysis, an
  explicitly validated commit, tag, atomic push, synchronization checks,
  and an optional template-based GitHub Release. Use only when explicitly
  invoked with $git-commit-push-tag or explicitly requested by name; never
  invoke implicitly.
---

# Git Commit, Push, Tag, and Optional GitHub Release

Before taking any action or running any Git command, read
[`references/git-commit-push-tag.txt`](references/git-commit-push-tag.txt)
completely.

Follow that canonical workflow exactly. Treat it as the sole behavioral
source of truth for parameters, defaults, analysis, mutations, command
ordering, retry rules, stop conditions, GitHub Release handling, and final
reporting. Do not summarize, reinterpret, relax, supplement, or override any
of its requirements.

If the canonical reference cannot be read completely, stop without modifying
the repository.
