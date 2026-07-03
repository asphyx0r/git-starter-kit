---
name: git-commit-push-tag
description: Manually run a safe Git workflow that updates docs if needed, commits expected changes, pushes the branch, creates a SemVer tag, and verifies local/remote sync. Use only when explicitly invoked for commit, push, or tag creation; never create a GitHub Release by default.
---

# Git Commit, Push, and SemVer Tag

Use this skill only when the user explicitly invokes `$git-commit-push-tag`
or explicitly asks to use this skill. Do not invoke it implicitly.

## Scope

This skill performs one controlled Git publication workflow:

1. Inspect the repository state.
2. Update `README.md` and `CHANGELOG.md` only if needed since the last tag.
3. Commit only expected changes.
4. Create one SemVer tag only after all pre-push checks pass.
5. Push the current branch and tag together with an atomic push.
6. Verify that local `HEAD`, `origin/<branch>`, and `<tag>^{}` point to
   the same commit.

Out of scope:

- Implementing unrelated code changes.
- Refactoring or formatting unrelated files.
- Creating non-SemVer tags.
- Publishing a GitHub Release without explicit user validation after final
  sync checks.
- Fixing CI, merge conflicts, or branch divergence unless the user explicitly asks.

## Required inputs and confirmations

Before creating the tag, determine:

- the current branch;
- the latest existing SemVer tag, if any;
- the target SemVer tag or requested bump type: `major`, `minor`, or `patch`;
- the repository's existing tag style: annotated or lightweight.

If the target tag or bump type is not explicit, inspect the changes since the
latest SemVer tag and propose the smallest SemVer bump with a short rationale,
then ask the user to confirm before creating the tag.

If there is no previous SemVer tag, ask the user to confirm the initial version.
Do not invent an initial tag.

If the repository's tag style cannot be determined, ask whether to create an
annotated or lightweight tag. Prefer matching the repository's existing style.

## Safety rules

Abort immediately, without creating or pushing a tag, when any check fails.
Do not repair the repository state unless the user explicitly asks.

Never run `git add .`. Stage files explicitly.

Never stage secrets, credentials, local environment files, generated artifacts,
or unrelated files. Treat files such as `.env`, private keys, tokens, local IDE
settings, build outputs, dependency caches, and temporary files as unsafe unless
the user explicitly confirms they are expected.

Do not publish a GitHub Release during the default workflow. After the final
sync verification, stop and ask for explicit validation if a GitHub Release is
requested.

Command examples below use PowerShell. When operating from another shell, use
shell-native equivalents and preserve the same checks, exit-code handling, and
abort conditions.

## Workflow

### 1. Pre-flight repository checks

Run:

```powershell
git rev-parse --is-inside-work-tree
git remote get-url origin
git branch --show-current
git fetch origin --prune --tags
```

Abort if:

- the current directory is not inside a Git work tree;
- `origin` is missing;
- `HEAD` is detached;
- the current branch cannot be identified.

Set `<branch>` to the current branch name.

Check synchronization safety:

```powershell
git status --short --branch
git rev-parse --verify "origin/<branch>"
git merge-base --is-ancestor "origin/<branch>" HEAD
git fsck --no-dangling
git diff --check
```

Abort if:

- `origin/<branch>` does not exist;
- `origin/<branch>` is not an ancestor of `HEAD`;
- the branch is behind or diverged from the remote;
- repository integrity checks fail;
- whitespace or patch integrity checks fail.

### 2. Inspect changes and update docs only if needed

Identify the latest SemVer tag:

```powershell
$semverTags = git tag --list 'v*.*.*' --sort=-v:refname |
  Where-Object { $_ -match '^v\d+\.\d+\.\d+$' }
$latestTag = $semverTags | Select-Object -First 1
$latestTag
```

Determine the repository tag style from the latest SemVer tag when
one exists:

```powershell
if ($latestTag) {
  git cat-file -t $latestTag
}
```

Interpret `tag` as an annotated tag and `commit` as a lightweight tag. If there
are several previous SemVer tags and their styles differ, stop and ask the user
which style to use.

To inspect recent tag styles when needed:

```powershell
$semverTags | Select-Object -First 5 | ForEach-Object {
  Write-Output ($_ + ' ' + (git cat-file -t $_))
}
```

Inspect changes since the latest tag when one exists:

```powershell
git log --oneline <latest-tag>..HEAD
git diff --stat <latest-tag>..HEAD
```

Also inspect current uncommitted changes:

```powershell
git status --short
git diff --stat
git diff --name-only
```

Update `README.md` and `CHANGELOG.md` only when they are missing required
information about the changes since the latest tag. Keep edits minimal and
project-local. Do not rewrite unrelated documentation.

### 3. Stage and commit expected changes

Review every changed file before staging:

```powershell
git status --short
git diff -- <file>
```

Stage only expected files explicitly:

```powershell
git add -- <file1> <file2>
```

Before committing, verify the staged diff:

```powershell
git diff --cached --stat
git diff --cached --check
git diff --cached --name-only
```

If there are expected staged changes, create a commit with an English message:

- subject line: maximum 50 characters;
- body lines: maximum 72 characters;
- body content: changed files and concise rationale.

If the working tree is already clean and no documentation update is needed, do
not create an empty commit. Continue with the tag workflow on the current `HEAD`.

After committing, verify:

```powershell
git status --short
git merge-base --is-ancestor "origin/<branch>" HEAD
git fsck --no-dangling
```

Abort if the repository is not clean, not sane, or no longer safely ahead of the
remote.

### 4. Select and create the SemVer tag

Determine the target tag from the confirmed bump or explicit user target.
The tag must match:

```text
v<MAJOR>.<MINOR>.<PATCH>
```

Before creating it, verify that it does not already exist locally or remotely:

```powershell
git rev-parse -q --verify 'refs/tags/<tag>'
if ($LASTEXITCODE -eq 0) {
  throw 'Tag already exists locally: <tag>'
}
if ($LASTEXITCODE -ne 1) {
  throw 'Could not verify local tag absence: <tag>'
}

git ls-remote --exit-code --tags origin 'refs/tags/<tag>'
if ($LASTEXITCODE -eq 0) {
  throw 'Tag already exists remotely: <tag>'
}
if ($LASTEXITCODE -ne 2) {
  throw 'Could not verify remote tag absence: <tag>'
}
```

For these absence checks, exit code `0` means the tag exists and must abort.
The expected non-existing-tag exit codes are `1` for `rev-parse` and `2` for
`ls-remote --exit-code`. Abort on any other exit code.

Create the tag only after all previous checks pass. Match the repository's
existing tag style.

For an annotated tag:

```powershell
git tag -a <tag> -m "<tag>"
```

For a lightweight tag:

```powershell
git tag <tag>
```

### 5. Push branch and tag atomically

Push the branch and tag together:

```powershell
git push --atomic origin <branch> <tag>
```

If the atomic push fails, verify whether the tag reached the remote. If it did
not, delete the local tag created by this workflow:

```powershell
git tag -d <tag>
```

Then stop and report the failure. Do not attempt a non-atomic push.

### 6. Final synchronization checks

After a successful push, run:

```powershell
git fetch origin --prune --tags
$headCommit = git rev-parse HEAD
$remoteCommit = git rev-parse 'origin/<branch>'
$tagCommit = git rev-parse '<tag>^{}'
$headCommit
$remoteCommit
$tagCommit
git status --short --branch
```

Verify that:

- `HEAD` equals `origin/<branch>`;
- `HEAD` equals `<tag>^{}`;
- the working tree is clean;
- the local branch is synchronized with the remote.

If any final verification fails, report the exact failing check and do not
create a GitHub Release.

## Final response format

Report concisely:

- branch name;
- commit hash;
- created tag;
- whether the push was atomic;
- final sync status;
- whether `README.md` or `CHANGELOG.md` changed;
- whether a GitHub Release still requires explicit validation.
