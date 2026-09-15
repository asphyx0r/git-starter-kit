# Quick start: create your own project

Git Starter Kit provides a universal, ready-to-use Git foundation for scripts,
CLI tools and applications. Its generic template lets you choose your own
language and framework. Download the starter ZIP in one click, then follow
these setup steps. The commands below use Windows PowerShell.

## Setup steps

1. **Prepare your tools.** Install Git for Windows with Bash, Python 3.11+
   with `venv` and `pip`, Node.js 24 and npm. Check that Git has your real
   author name and email configured.

2. **Download and extract the starter.** Open the
   [published releases](https://github.com/asphyx0r/git-starter-kit/releases)
   and click the asset ending in `-with-agent-rules.zip`.
   Extract its contents into an empty folder, such as `C:\codex\my-project`,
   and open PowerShell there. Run every command from this project root.
   Use the release ZIP for new projects; source clones are for maintaining
   the starter itself.

3. **Install the starter dependencies.** Create a local Python environment,
   select it and install the locked dependencies:

   ```powershell
   python -m venv .venv
   $env:PATH = (Resolve-Path .venv/Scripts).Path + ";" + $env:PATH
   python -m pip install --require-hashes --requirement tools/quality/requirements.lock
   npm ci --ignore-scripts --prefix tools/quality
   ```

   Keep this PowerShell session open for the remaining steps. Stop and resolve
   any installation error before continuing.

4. **Prepare the quality tools.** Follow the local installation instructions
   in the [tools guide](../tools/README.md) for Actionlint, shfmt,
   PSScriptAnalyzer, ShellCheck and Gitleaks. Use the pinned versions and
   session search paths shown there. Installing PSScriptAnalyzer through the
   local installer requires PowerShell 7.4.6+ (`pwsh`) on `PATH`.
   Audits never install missing tools automatically.

5. **Preview initialization.** Check the planned actions without changing
   the project:

   ```powershell
   powershell -NoProfile -File tools/git-init.ps1 --path . --dry-run
   ```

6. **Initialize your repository.** Run the initializer and accept its
   confirmations after reviewing the proposed files:

   ```powershell
   powershell -NoProfile -File tools/git-init.ps1 --path .
   ```

   This creates `main`, the first system-only commit, local Git hooks,
   release artifacts and the annotated `v1.0.0` tag. Nothing is published.
   **Add application code and personalize the starter only after this step.**

7. **Verify the result.** Check the first commit, the `v1.0.0` tag and the
   starter's core validation:

   ```powershell
   git status
   git log -1 --oneline
   git tag --list
   bash tools/repository-audit.sh fast
   ```

   Resolve any reported errors. Core validation does not replace application
   tests; a warning about an empty check list is expected before adding them.

8. **Publish to GitHub — optional.** Create an empty GitHub repository without
   a README, license or `.gitignore`, and ensure Git can authenticate to it.
   Replace the example URL below with your repository URL.
   **For no workflow runs, complete step 10 before this first push.**

   ```powershell
   git remote add origin https://github.com/YOUR-ACCOUNT/my-project.git
   git push -u origin main --tags
   ```

   If GitHub Actions is enabled, check the results in the repository's
   **Actions** tab and resolve any failures.

9. **Start building your application.** Add your code, personalize the README
   and project contact information, and declare your application test commands
   in `.starter-kit-project.json`. Run the declared checks with
   `bash tools/repository-audit.sh project-checks` after preparing their
   dependencies. Application checks must be configured explicitly.

10. **Disable GitHub Actions — optional.** For a repository with no GitHub
    workflow execution, open **Settings → Actions → General**. Under
    **Actions permissions**, select **Disable actions**, then **Save**.
    See the [GitHub Actions settings guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).
    Keep the workflow files: local hooks and audits remain active, and you
    can enable Actions again from the same settings. The starter's optional
    automation flags alone do not disable all GitHub Actions.
    If branch protection requires checks from disabled workflows, review
    those requirements so pull requests do not wait for checks that cannot run.
