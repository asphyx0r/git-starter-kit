# Guarded pull request merges

This guide explains how maintainers validate an exact squash message before a
privileged pull request merge. The mechanism is distributed with the starter
kit, but enforcement remains inactive until publication and GitHub repository
activation are separately authorized and completed.

## Safety model

The requester validates the exact UTF-8 message with the repository-pinned
Commitlint, seals the pull request number and 40-character head SHA, and sends a
`guarded-squash-merge` repository dispatch. The workflow correlates the request
with `Guarded merge <UUID>` and checks out only the immutable default-branch
commit in `github.sha`, with credential persistence disabled.

The workflow never checks out or executes pull request code. Fork pull requests
are therefore supported. Its first pass has only `contents: read` and
`pull-requests: read`; it decodes the event payload, checks the SHA-256 digest,
validates the exact message, re-reads the pull request, and requires all
effective default-branch status-check contexts to be present and successful.
The exact required `Repository audit` check must come from the `Repository
audit` workflow on a `pull_request` event. The tool brackets that check query
with reads of the pull request head SHA so a concurrent head update fails
closed.

An effective required-check rule may use a null `integration_id` or a positive
integer such as the GitHub Actions App ID. The preflight rejects booleans,
strings, and nonpositive values, binds the visible context, workflow, event,
state, and head SHA, and leaves enforcement of the configured integration ID
to GitHub when the merge is attempted.

The final read in each pass uses a dedicated GraphQL query for the pull request
head, base target, auto-merge request, actual merge-queue membership, and
merge-queue availability. GitHub CLI's `pr view --json` does not expose both
merge-queue booleans. This final point-in-time read closes head, base, auto, or
queue changes that occur while checks are inspected; a change after that read
and before `gh pr merge` remains an API race, so the exact postcondition below
is still mandatory.

Only after that pass succeeds does the workflow mint the existing GitHub App
token, limited to `contents: write` and `pull-requests: write`. It repeats every
validation with that token. Each pass also requires repository auto-merge to
be disabled, rejects every effective merge-queue rule on the trusted default
branch, and rejects a pull request that already has auto-merge enabled or is
queued. The final command calls `gh pr merge` with squash mode, the exact
subject, an explicit body file, and the sealed head SHA; it supplies no auto,
administrator, auto-disable, or branch-deletion option.

## Prerequisites

Install the locked Node dependencies and authenticate GitHub CLI:

```bash
npm ci --ignore-scripts --prefix tools/quality
gh auth status
```

The repository must provide the existing App configuration used by the
workflow:

- repository variable `AGENT_RULES_APP_CLIENT_ID`;
- repository secret `AGENT_RULES_APP_PRIVATE_KEY`.

Do not place either value in a message file, event file, command, or log.

## Message contract

Write the complete candidate to a file without normalization. It must be
non-empty UTF-8 without BOM or NUL, use LF only, and end in exactly one LF. The
only accepted forms are:

```text
subject
```

or:

```text
subject

body
```

The second form may contain multiple body lines. Commitlint still enforces the
repository limits, including the 72-character body-line maximum. The tool
always supplies both the subject and `--body-file`; subject-only messages use an
empty body file so GitHub cannot generate default text.

## Request a merge

Preview validation and the sealed dispatch without sending it:

```bash
python tools/merge-pull-request.py --dry-run request \
  --pull-request 17 \
  --message-file /path/to/merge-message.txt \
  --repository owner/repository
```

Send the request and answer with an uppercase `Y` when prompted:

```bash
python tools/merge-pull-request.py request \
  --pull-request 17 \
  --message-file /path/to/merge-message.txt \
  --repository owner/repository \
  --timeout-seconds 900
```

Use `--force` only when an already approved automation must skip the prompt.
It does not bypass message, pull request, head SHA, or required-check
validation. Omitting `--repository` selects the repository resolved by `gh`.
Immediately before the mutating dispatch POST, the requester prints and flushes
the exact `Guarded merge <UUID>` identity. Preserve it for recovery if the
requester is interrupted.

`--timeout-seconds` must convert to a finite, non-negative value. The requester
rejects an unrepresentable value before it can dispatch anything.

Run correlation accepts only the guarded workflow path as returned by the API,
either bare or suffixed with `@<default-branch>`. It also requires the
repository-dispatch event, exact UUID title, default head branch, and a valid
40-character head SHA before trusting a completed run.

The `execute --event-file` interface is for the repository-owned workflow. A
maintainer should not invoke it with a hand-built payload as a substitute for
the request path.

## Results and recovery

Exit status `0` means the requested operation was confirmed successful. Status
`1` means validation or the operation definitely failed, and status `2` means
the command line was invalid. Status `3` means an irreversible submission may
have started but its exact result is unavailable or conflicting. This includes
a lost repository-dispatch response, an uncorrelated or duplicate workflow
run, a timeout, and a merge whose final state or exact message cannot be read.
Every status-3 diagnostic includes the exact `Guarded merge <UUID>` identity.

Never automatically repeat a status `3` request. First inspect GitHub Actions
for the exact `Guarded merge <UUID>` run and inspect the pull request. A repeated
dispatch uses a new UUID and can race with the original request; UUID and hash
values provide correlation and integrity, not origin authentication.

After `gh pr merge` returns, and after any correlated workflow result including
`success`, the requester or executor requires the pull request to be merged,
still targets the trusted default branch with the sealed head, reads the real
merge commit, validates its message with Commitlint, and compares it
byte-for-byte with the candidate. The only accepted difference is GitHub
omitting the candidate's single final LF. An explicit `OPEN` or `CLOSED` state
without a merge commit proves failure and returns status `1` only when the final
GraphQL read also proves the same base/head identity and inactive auto-merge
and merge-queue state. An unavailable read, changed base or head, active
auto-merge or queue state, or a conflicting merged message returns status `3`
with the request UUID.

## Activate enforcement separately

Adding these files does not activate repository enforcement. A separately
authorized publication and GitHub configuration change must complete all of
the following steps for each target repository:

1. Publish a release or cumulative package containing the workflow, CLI,
   tests, audit contract, and this guide.
2. Install that package on the repository's default branch and require its
   normal `Repository audit` pull request check.
3. Create a distinct default-branch ruleset that enables only the GitHub
   `Restrict updates` rule and grants bypass only to the configured App.
4. Keep the existing `Protect master` ruleset without any bypass actor so the
   App remains subject to its required checks and review controls.
5. Disable repository auto-merge and ensure that no repository or organization
   ruleset applying to the default branch enables a merge queue. GitHub CLI can
   otherwise implicitly enable auto-merge or enqueue a pull request, as
   documented by [`gh pr merge`](https://cli.github.com/manual/gh_pr_merge).
6. Disable merge-commit and rebase merge methods in repository settings,
   leaving squash merge as the supported method.
7. Open a disposable pull request and prove that a manual merge is blocked,
   while the App path succeeds only after the required checks pass.

Record the ruleset identities, App identity, repository settings, disposable
pull request, required-check run, guarded workflow run, and merge commit as the
activation evidence. Do not describe enforcement as active before that proof
exists.

## Distribution

The workflow, CLI, this guide, and their tests use the starter kit's default
`replace` package strategy. Release-identification artifacts are intentionally
unchanged by this implementation and are regenerated only in a future,
separately authorized release.
