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

The release package workflow adds two downloadable files to a
`git-starter-kit` release. The enriched ZIP contains the canonical rule files
already tracked at the release tag, and the upgrade toolkit packages the
guarded cumulative updater.

## Generated File

The generated assets are named like this:

```text
git-starter-kit-vX.Y.Z-with-agent-rules.zip
git-starter-kit-vX.Y.Z-upgrade-toolkit.zip
```

The ZIP includes the normal starter kit files plus these files from
`agent-coding-rules`:

- `AGENTS.md`
- `CODING_RULES.md`
- `COMMIT_RULES.md`
- `DOCUMENTATION_RULES.md`
- `LANGUAGE_RULES.md`
- `RELEASE_RULES.md`

The ZIP also includes two provenance files:

- `_agent-rules-source.json` records the packaged repository, upstream starter
  kit, and agent-rules references and commits.
- `_starter-kit-files.json` records each managed path, raw and canonical
  SHA-256 digests, content kind, Git mode, and upgrade strategy.

The upgrade toolkit contains the guarded updater and the complete enriched
package. It can build a cumulative upgrade from the exact earlier package used
to initialize a target repository. Only `git-starter-kit` publishes this
toolkit. When the release workflow is inherited by a downstream repository,
the repository publishes its own enriched package but skips the starter
upgrade toolkit.

The cumulative updater classifies the six rule files and
`_agent-rules-source.json` as `agent-rules`. It reports those paths but never
writes them. Each target repository remains responsible for synchronizing
those files through its own pull-request workflow.

Repository-specific inventories and operator documentation are
initialization-only. Cumulative upgrades preserve `docs/SKILLS.md`,
`docs/release-package.md`, `docs/repository-files.md`, and `tools/README.md`
instead of attempting an unsafe generic merge. They also preserve
`tools/repository-audit.sh`, whose test and tool inventory belongs to the
target repository.

When an initialization-only file changed upstream, the plan reports
`review-initialize-only`. The signal does not block or write the target; it
identifies repository-owned content that maintainers should review separately.

## Rule Freshness Gate

The package builder resolves the requested public `agent-coding-rules` release
and compares it with the tracked `_agent-rules-source.json`. It then verifies
the canonical hash of every tracked rule. A customized file is accepted only
when provenance schema 3 contains its matching `preservedFiles` record.

No source-repository GitHub App token is required. The built-in workflow token
is used only to upload assets to the current repository release.

## Automatic Release Mode

Use this mode for the normal release process.

1. Prepare the release commit in `git-starter-kit`.
2. From a clean repository, run `bash tools/repository-audit.sh` locally.
3. Stop if the local audit fails; do not create a release tag or release.
4. Create and push the release tag, for example `v1.3.0`.
5. On GitHub, open the repository page.
6. Open **Releases**.
7. Create a new release from the tag.
8. Mark it as a prerelease and do not mark it as latest.
9. Publish the prerelease.

After the prerelease is published, GitHub starts the `Release package`
workflow automatically. Automatic releases intentionally use `latest` so the
package always includes the latest published full `agent-coding-rules`
release.

The workflow then:

1. Checks out `git-starter-kit` at the published release tag.
2. Resolves `latest` to the latest published full `agent-coding-rules` release.
3. Verifies that tracked provenance and rule hashes match the resolved tag.
4. Copies the tracked starter-kit files into a temporary package folder.
5. Retains the six tracked rule files in that package folder.
6. Writes validated provenance and the managed-file manifest.
7. Creates the ZIP file.
8. Verifies that the required files and managed-file hashes are present.
9. Extracts the composed package and runs its Markdown and Codespell audits.
10. Bundles the guarded updater and complete package as an upgrade toolkit.
11. Uploads both ZIP files to the GitHub release as release assets.
12. Promotes the prerelease to the latest stable release in a separate job
    that depends on successful packaging.

The release is complete only when this exact `release.published` workflow run
finishes with `success`, the release is no longer a prerelease, and both
expected assets and their provenance have been verified. A manual workflow run
does not satisfy this completion gate.

When the workflow finishes, the GitHub release should show an asset such as:

```text
git-starter-kit-v1.3.0-with-agent-rules.zip
git-starter-kit-v1.3.0-upgrade-toolkit.zip
```

Download this ZIP when you want a ready-to-use starter kit with agent rules
already included.

## Manual Release Mode

Use this mode when you need to create or recreate the enriched package for an
existing release.

The release must already exist on GitHub before running the workflow manually.
The `tag` input must be an existing GitHub release tag that uses SemVer with a
leading `v`, for example `v1.3.0`. The manual workflow uploads an asset to
that release; it does not create the release itself.

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
that the ZIP asset is listed under the release assets.

## Local Test

Run the full repository audit locally before publishing a release:

```bash
bash tools/repository-audit.sh
```

The full audit intentionally resolves the latest published full
`agent-coding-rules` release during package smoke checks. Treat a failure to
resolve or validate that latest release as an audit failure before publishing.
It also needs network access to npm for Markdown lint bootstrapping and PyPI
for Codespell bootstrapping. Use `markdown`, `spelling`, or `static` when you
need to isolate one audit family.

You can also test only the package generation locally before publishing a release.

From the repository root, run:

```powershell
powershell -NoProfile -File tools\build-release-package.ps1 `
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
does not overlay files from the source repository.

The script copies files reported by `git ls-files`. Local untracked files are
not included in the package. This is intentional, because release packages
should be built from committed repository content.

## Troubleshooting

If the release asset is missing, open the **Actions** tab and inspect the latest
`Release package` workflow run.

If a release remains a prerelease, inspect the matching run triggered by the
`release` event. The run must match the release tag and tag commit and must end
with `success` before the release is complete.

If the manual workflow fails, check that the `tag` input matches an existing
GitHub release tag using SemVer with a leading `v`.

If only the promotion job fails, rerun only the failed jobs of the same
automatic run. Do not delete a valid asset or start a manual replacement run.

If the package must use a specific agent rules version, run the manual
workflow again with an explicit SemVer `agent_rules_ref` value.
