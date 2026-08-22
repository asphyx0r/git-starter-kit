# BRANCH_RULES.md

## Purpose

This file defines universal default rules for Git branches created or managed
by an AI coding agent.

## Scope

Apply these rules:

- before the first write intended to change repository content for an isolated
  task;
- before creating, renaming, publishing, integrating, rebasing, or deleting a
  Git branch.

Repository-specific branch instructions take precedence. When the repository
does not define a branch workflow or naming convention, use the defaults in
this file.

Use `COMMIT_RULES.md` for commit creation and `RELEASE_RULES.md` for Git tag
creation. Branch compliance does not imply commit or tag compliance.

## Task Branch Requirement

- Before changing repository content for a feature, fix, documentation update,
  refactoring, test change, maintenance task, release preparation, or
  experiment, ensure that the work is isolated on a dedicated task branch or
  task worktree.
- Create the task branch before the first repository write.
- Do not create a branch for read-only inspection, analysis, planning, or
  validation that does not change repository content.
- If the current branch or worktree is already dedicated to the same coherent
  task, continue using it instead of creating another branch.
- Do not perform routine development directly on `main`, `master`, or another
  repository-defined permanent or shared integration branch.
- Direct development on `main` or `master` is allowed only when the user
  explicitly requests it and the repository is confirmed to be a small or
  single-user project. If either condition is unknown, ask before writing.
- Keep permanent and shared integration branches stable. Do not leave them with
  unvalidated or unrelated task changes.

## Branch Creation Safety

Before creating a task branch:

- Confirm the intended Git repository root and worktree.
- Inspect the current branch, worktree status, and any in-progress Git
  operation.
- Preserve unrelated staged, unstaged, and untracked work.
- Stop and ask before creating or switching branches when unrelated work makes
  the task boundary or starting point ambiguous.
- Identify the repository-defined integration point for the task. Do not assume
  that every repository uses `main` or `master`.
- Identify the exact starting commit and do not claim that a local or remote
  base is current unless it was verified.
- Check that the candidate branch does not already exist locally. When remote
  publication is intended, also inspect the relevant known remote refs.
- Validate the exact candidate with `git check-ref-format --branch` using the
  shell's safe argument-passing syntax.
- Treat a successful `git check-ref-format --branch` result as Git syntax
  validation only; validate the repository naming policy separately.
- After creation, verify the active branch and its starting commit before
  changing repository content.

If Git validation cannot be run, report that limitation and do not claim that
the candidate name is valid.

## Default Naming Convention

When no repository-specific naming convention exists, permanent branches
explicitly defined by the repository may keep their declared names. Every task
branch must use exactly one of these types:

| Type | Intended use |
| --- | --- |
| `feat` | A new feature. |
| `fix` | A defect or regression correction. |
| `docs` | Documentation-only changes. |
| `refactor` | Restructuring with no intended functional change. |
| `test` | Test additions, corrections, or improvements. |
| `chore` | Technical maintenance outside features and fixes. |
| `release` | Release preparation, stabilization, or finalization. |
| `experiment` | A prototype or exploration with no guarantee of integration. |

Use one of these forms:

```text
<type>/<description>
<type>/<ticket>-<description>
```

A `release` branch may use a repository-approved version in place of the normal
description, for example:

```text
release/1.2.0
```

Apply these naming rules:

- Use lowercase ASCII characters.
- Use only `a-z`, `0-9`, and `-` in ordinary segments.
- Use `/` only to separate the type from the branch-specific segment.
- Use `.` only in a repository-approved release version.
- Write descriptions in concise, explicit, action-oriented kebab-case.
- Include a ticket immediately after the type when a real ticket identifier is
  supplied by the user or repository; never invent a ticket.
- Normalize a supplied ticket identifier to lowercase when the repository does
  not require another form.
- Do not use whitespace, underscores, uppercase letters, CamelCase, accented
  characters, other Unicode characters, or repeated separators.
- Do not use vague, personal, or temporary descriptions such as `changes`,
  `wip`, `final`, or `v2`.
- Do not introduce aliases such as `feature`, `bugfix`, or `hotfix` under the
  default convention.
- Do not combine a repository-specific prefix with a default type unless the
  repository convention explicitly requires that structure.

Examples:

```text
feat/add-manifest-schema
fix/psc-187-handle-empty-support-url
docs/update-release-process
refactor/simplify-config-loader
test/add-installer-regression-tests
chore/update-gitignore
release/1.2.0
experiment/try-parser-strategy
```

## Branch Lifecycle Safety

- Keep one coherent and verifiable objective per task branch.
- Do not mix unrelated features, fixes, documentation changes, refactorings,
  tests, maintenance, release work, or experiments.
- Keep task branches only as long as required to complete, review, integrate,
  or abandon their objective.
- Keep `experiment` branches isolated from validated feature work. Before
  integration, move accepted experimental work to a compliant `feat` branch
  only when renaming or recreating the branch is safe.
- Keep `release` branches limited to work required for the associated release.
  Apply `RELEASE_RULES.md` separately when creating a Git tag.
- Treat local branch creation and remote publication as separate actions. Do
  not push a branch or configure remote tracking unless the user authorized
  publication or the requested workflow clearly requires it.
- Before first publication, revalidate the branch name and inspect relevant
  remote refs for a collision.
- Do not rename a published branch without explicit authorization and a plan
  for dependent pull requests, CI references, scripts, protections, and
  collaborators.
- Follow the repository-defined merge, rebase, or squash policy. Do not choose
  an integration strategy when the repository or user has not established one.
- Do not integrate a task branch into a permanent or shared branch without
  explicit authorization and the required repository checks.
- Rebase unpublished task commits only when the repository workflow permits it.
- Do not rebase published commits when another person, branch, pull request,
  workflow, or automation may depend on their existing identities.
- Do not force-push rewritten history without explicit authorization after
  reporting the affected remote branch and dependencies.
- After integration or explicit abandonment, recommend deleting the task branch
  but do not delete it without explicit authorization.
- Before deletion, verify whether the branch is fully integrated and report any
  unique commits.
- Prefer safe deletion that refuses to remove unmerged work. Do not force-delete
  a branch unless the user explicitly approves discarding the reported
  unmerged commits.
- Treat local and remote branch deletion as separate destructive actions, each
  requiring explicit authorization.

## Stop Conditions

Stop and ask for direction when:

- the repository, task boundary, integration point, or starting commit is
  ambiguous;
- unrelated work would be carried into the task branch;
- the applicable naming convention or branch type cannot be determined;
- the candidate conflicts with an existing local or remote branch;
- direct work on a permanent branch does not satisfy the documented exception;
- a rename, rebase, integration, force-push, or deletion could affect shared or
  unmerged work.
