# Repository migration

## Decision

As of 2026-07-18, the canonical local worktree for this repository is:

```text
C:\codex\git-starter-kit
```

The previous Google Drive worktree is retained only as a deprecated backup:

```text
G:\Mon Drive\Code\Git\DEPRECATED-git-starter-kit
```

Future implementations, commits, tags, and repository validation must use the
canonical local worktree.

## Reason

The repository was moved from Google Drive to a local NTFS volume to avoid
cloud-filesystem ACL, locking, and Codex process-launch failures such as
`helper_unknown_error`. The local path provides stable filesystem semantics
for Git object, reference, index, and lock-file operations.

## Actions performed

- Copied the complete worktree and `.git` directory to the local path.
- Compared the old and new branches, tags, references, objects, reflogs,
  configuration, tracked files, ignored files, and untracked files.
- Confirmed that all 948 objects present in the old repository were preserved
  in the new repository.
- Confirmed that the new repository contained the additional `v1.8.0` commit,
  tag, trees, and blobs already published to `origin`.
- Verified every tracked worktree file against its Git object hash.
- Confirmed that both repositories passed `git fsck --full --strict`.
- Confirmed that the new worktree had no locks, active local hooks, submodules,
  linked worktrees, alternates, grafts, sparse checkout, partial clone, or
  Google Drive path dependency.
- Ran the non-mutating repository audit profile successfully with Git Bash.
- Created and read back a temporary Git commit object and reference to prove
  write, lock, and atomic reference-update support in the new repository.
- Removed the temporary reference and object, then confirmed that objects,
  references, reflogs, index, configuration, status, and integrity output
  exactly matched the pre-test state.
- Confirmed that `HEAD`, `origin/master`, and `v1.8.0^{}` resolved to
  `9aa312e7ead7de15c55d0151b7c847486a09d48e` at migration validation time.

## Operational guidance

- Keep the deprecated Google Drive copy unchanged as a temporary safety backup.
- Do not use the deprecated copy for new work or attempt to synchronize it.
- Use `C:\Program Files\Git\bin\bash.exe` when the Windows `bash` command
  resolves to WSL without an installed distribution.
- Do not prune the non-corrupt dangling objects identified during validation
  while zero data loss remains a requirement.
- Treat GitHub Release publication as a separate action that requires explicit
  user approval after branch and tag synchronization checks.
