# Release Package

## Purpose

This repository can publish an enriched release package for people who want to
start a new project with the Git starter kit and the coding-agent rules already
included.

The agent rules come from
[agent-coding-rules](https://github.com/asphyx0r/agent-coding-rules), a
repository that provides practical behavior and code-quality rules for AI
coding agents.

GitHub always adds two source archives to each release:

- `Source code (zip)`
- `Source code (tar.gz)`

Those archives contain only the files that are committed in `git-starter-kit`
at the release tag.

The release package workflow adds three downloadable files to a
`git-starter-kit` release. The enriched ZIP contains the canonical rule files
already tracked at the release tag, the upgrade toolkit packages the guarded
cumulative updater, and `SHA256SUMS` gates the integrity of both ZIP payloads
within the workflow trust boundary.

## Generated File

The generated assets are named like this:

```text
git-starter-kit-vX.Y.Z-with-agent-rules.zip
git-starter-kit-vX.Y.Z-upgrade-toolkit.zip
SHA256SUMS
```

`SHA256SUMS` contains the lowercase SHA-256 digest and exact filename of each
ZIP, in the order shown above.

The ZIP includes the normal starter kit files plus these files from
`agent-coding-rules`:

- `AGENTS.md`
- `BRANCH_RULES.md`
- `CODING_RULES.md`
- `COMMIT_RULES.md`
- `DOCUMENTATION_RULES.md`
- `LANGUAGE_RULES.md`
- `RELEASE_RULES.md`

The ZIP also includes three provenance files:

- `starter-kit-manifest.json` records the initial and current starter-kit
  releases plus the current core inventory. In a release package, `source`
  and `current` initially identify the same exact tag.

- `_agent-rules-source.json` records the packaged repository, upstream starter
  kit, and agent-rules references and commits.
- `_starter-kit-files.json` records each managed path, raw and canonical
  SHA-256 digests, content kind, Git mode, and upgrade strategy. Schema 3 uses
  `starter-kit-state` for the tracked core manifest.

The upgrade toolkit contains the guarded updater and the complete enriched
package. It can build a cumulative upgrade from the exact earlier package used
to initialize a target repository. Only `git-starter-kit` publishes the
enriched package and upgrade toolkit. `.github/CODEOWNERS`, the release-package
workflow, packaging and upgrade sources, their repository-specific tests, and
package operator documentation are source-only. They are excluded from derived
repository packages.

The package does include the release artifact generator, its manifest template
and schema, the repository-owned hooks, and the tag validation workflow. It
does not include the canonical repository's generated `VERSION`, `SHA256SUMS`,
or `manifest.json`: those three files identify one source release and each
derived repository must generate its own values before its own tag.

For a concise usage procedure in French, see
[Upgrade toolkit](upgrade-toolkit.md).

The cumulative updater classifies the seven rule files and
`_agent-rules-source.json` as `agent-rules`. It never writes the seven rule
files. For `_agent-rules-source.json`, it refreshes only the `repository` and
`starterKit` sections from the new package while preserving `agentRules`,
`preservedFiles`, and other target-owned fields. Each target repository remains
responsible for synchronizing its rule files through its own pull-request
workflow.

Distribution keeps `.github/dependabot.yml` merge-managed and replaces the
complete `tools/quality/` baseline. Repository-specific inventories, operator
documentation, `tools/repository-audit.sh`, and every module under
`tools/repository-audit/` are initialization-only, so cumulative upgrades
preserve their downstream ownership instead of attempting an unsafe generic
merge.

When an initialization-only file changed upstream, the plan reports
`review-initialize-only`. The signal does not block or write the target; it
identifies repository-owned content that maintainers should review separately.

## Rule Freshness Gate

The package builder resolves the requested public `agent-coding-rules` release
and compares it with the tracked `_agent-rules-source.json`. It then verifies
the canonical hash of every tracked rule. A customized file is accepted only
when provenance schema 3 contains its matching `preservedFiles` record.

No source-repository GitHub App token is required. The read-only `build` job
exposes the built-in workflow token only to the package-builder step, which
uses it when resolving `agent_rules_ref=latest`. After the transferred files
are revalidated, the final `publish` step receives the write-scoped token for
explicit-repository upload and conditional promotion. This public-source
access does not replace the repository variable and secret required by the
common `Agent rules update` release gate.

The `build` and `publish` jobs run only when `github.repository` is exactly
`asphyx0r/git-starter-kit`. Only `publish` has `contents: write` and the
`release` environment. It does not check out the repository or execute
downloaded artifact code. The package builder also rejects a different slug or
`origin` as a second identity check.

Runs for the same release tag share one non-cancelling concurrency group. The
tracked `environment: release` boundary does not prove that the corresponding
GitHub environment or its protection rules are configured. Verify those
settings on GitHub after workflow publication. With the sole CODEOWNER
`@asphyx0r`, the CODEOWNERS assignment alone does not provide an independent
human approval.

## Automatic Release Mode

Use this mode for the normal release process.

1. Prepare the release commits and changelog in `git-starter-kit`.
2. Prepare `starter-kit-manifest.json` for the exact selected tag with
    `tools/starter-kit-manifest.py`, then commit only that release metadata.
3. Resolve every release-manifest value from verified evidence, ask the user
    only for unresolved or contradictory values, obtain explicit validation,
    then generate and commit exactly `VERSION`, `SHA256SUMS`, and
    `manifest.json`.
4. From a clean repository, run `bash tools/repository-audit.sh` locally.
5. Stop if the local audit fails; do not create a release tag or release.
6. Create and push the release tag, for example `v1.3.0`.
7. Require the tag-only `Release artifacts` workflow to succeed.
8. On GitHub, open the repository page.
9. Open **Releases**.
10. Create a new release from the tag.
11. Mark it as a prerelease and do not mark it as latest.
12. Publish the prerelease.

After the prerelease is published, GitHub starts the `Release package`
workflow automatically. Automatic releases intentionally use `latest` so the
package always includes the latest published full `agent-coding-rules`
release.

The workflow then:

1. Checks out `git-starter-kit` at the published release tag without persisting
    credentials.
2. Configures Python 3.11 and Node.js 24.20.0 without dependency caches, then
    installs each locked quality environment once, including
    `markdownlint-cli2` 0.23.2.
3. Resolves `latest` to the latest published full `agent-coding-rules` release.
4. Verifies that the tracked core manifest, provenance, and rule hashes match
    the resolved tag.
5. Copies the core paths declared by the tracked manifest, except
    source-repository-only packaging files, into a temporary package folder.
6. Retains the seven tracked rule files in that package folder.
7. Writes validated provenance and the schema 3 managed-file manifest.
8. Creates and validates the enriched ZIP with the already installed Markdown
    and Codespell tools.
9. Bundles the guarded updater and complete package as an upgrade toolkit.
10. Seals both ZIPs and the exact two-line `SHA256SUMS` file as the only three
    regular files in one inter-job artifact.
11. Downloads and revalidates those three files in `publish`, before exposing
    its token.
12. Uploads the three explicitly named release assets without overwriting an
    existing asset.
13. For a published prerelease only, promotes it as the final command after a
    successful upload.

The release is complete only when this exact `release.published` workflow run
finishes with `success`, the release is no longer a prerelease, and both ZIPs
plus `SHA256SUMS` have been verified. A manual workflow run does not satisfy
this completion gate.

When the workflow finishes, the GitHub release should show an asset such as:

```text
git-starter-kit-v1.3.0-with-agent-rules.zip
git-starter-kit-v1.3.0-upgrade-toolkit.zip
SHA256SUMS
```

Download the `with-agent-rules.zip` asset when you want a ready-to-use starter
kit with agent rules already included.

## Manual Release Mode

Use this mode when you need to create or recreate the enriched package for an
existing release.

The release must already exist on GitHub before running the workflow manually.
The `tag` input must be an existing GitHub release tag that uses SemVer with a
leading `v`, for example `v1.3.0`. The manual workflow uploads both ZIPs and
`SHA256SUMS` to that release; it does not create the release itself.

Manual runs never promote a prerelease. If an automatic release run failed,
rerun the failed jobs of that same `release` run after correcting the cause.
Do not substitute a `workflow_dispatch` run for the automatic completion gate.

1. Open the `git-starter-kit` repository on GitHub.
2. Open the **Actions** tab.
3. Select the **Release package** workflow.
4. Click **Run workflow**.
5. Fill in `tag` with the release tag to package, for example `v1.3.0`.
6. Fill `agent_rules_ref` with `latest` or a SemVer `agent-coding-rules` tag,
    for example `v1.36.1`.
7. Click **Run workflow**.

Manual release packages accept `latest` or an explicit SemVer tag. Use a SemVer
tag when you need to recreate a package from a known agent-rules release.
Branch names are still rejected so the generated asset stays reproducible.

When the workflow finishes, open the GitHub release page for the tag and check
that both ZIPs and `SHA256SUMS` are listed under the release assets.

## Local Test

Run the full repository audit locally before publishing a release:

```bash
bash tools/repository-audit.sh
```

The full audit uses the active locked Python and npm quality environments; its
release-package smoke test does not reinstall them. It intentionally resolves
the latest published full `agent-coding-rules` release. Treat a failure to
resolve or validate that release as an audit failure before publishing. Use
`markdown`, `spelling`, or `static` when you need to isolate one audit family.

You can also test only the package generation locally before publishing a release.

From the repository root, run:

```powershell
powershell -NoProfile -File tools\build-release-package.ps1 `
  -RepositorySlug asphyx0r/git-starter-kit `
  -RepositoryRef local-test `
  -OutputDirectory .tmp\release-package-test `
  -PackageName test-release-package.zip
```

Inspect the generated ZIP:

```powershell
tar -tf .tmp\release-package-test\test-release-package.zip
tar -xOf .tmp\release-package-test\test-release-package.zip _agent-rules-source.json
tar -xOf .tmp\release-package-test\test-release-package.zip _starter-kit-files.json
```

The local test creates a ZIP only. It does not upload anything to GitHub.
`AgentRulesRef` defaults to `latest`; pass a SemVer tag only when you need to
assert a known agent-rules release. The argument validates tracked content; it
does not overlay files from the source repository. The repository root must use
the canonical `git-starter-kit` HTTPS `origin`.

The script copies files reported by `git ls-files`, except the explicit
source-repository-only packaging files. Local untracked files are not included
in the package. This is intentional, because release packages should be built
from committed repository content.

## Troubleshooting

If a release asset is missing, open the **Actions** tab and inspect the latest
`Release package` workflow run. The publish step does not overwrite an existing
asset.

If a release remains a prerelease, inspect the matching run triggered by the
`release` event. The run must match the release tag and tag commit and must end
with `success` before the release is complete.

If the manual workflow fails, check that the `tag` input matches an existing
GitHub release tag using SemVer with a leading `v`.

If the final promotion command fails, inspect the `publish` job of that same
automatic run. Do not substitute a manual run for the automatic completion
gate.

If the package must use a specific agent rules version, run the manual
workflow again with an explicit SemVer `agent_rules_ref` value.
