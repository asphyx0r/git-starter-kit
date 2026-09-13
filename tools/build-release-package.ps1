param(
    [string]$RepositoryRoot = (Get-Location).Path,
    [string]$OutputDirectory = (Join-Path (Get-Location).Path "dist"),
    [string]$PackageName = "",
    [Alias("StarterRef")]
    [string]$RepositoryRef = $env:GITHUB_REF_NAME,
    [string]$RepositorySlug = $env:GITHUB_REPOSITORY,
    [string]$StarterKitRepository = "asphyx0r/git-starter-kit",
    [string]$StarterKitRef = "",
    [string]$StarterKitCommit = "",
    [string]$AgentRulesRepository = "asphyx0r/agent-coding-rules",
    [string]$AgentRulesRef = "latest"
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

# Keep this pattern aligned with repository-audit SemVer smoke tests.
$SemVerTagPattern = "^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"

$RequiredRuleFiles = @(
    "AGENTS.md",
    "BRANCH_RULES.md",
    "CODING_RULES.md",
    "COMMIT_RULES.md",
    "DOCUMENTATION_RULES.md",
    "LANGUAGE_RULES.md",
    "RELEASE_RULES.md"
)
$StarterKitManifestPath = "starter-kit-manifest.json"

$StarterOnlyPaths = @(
    "docs/repository-migration.md",
    "templates/README.md",
    "templates/README_TOOLS.md",
    "templates/CONTRIBUTING.md",
    "templates/CHANGELOG.md",
    "templates/CODE_OF_CONDUCT.md",
    "templates/SECURITY.md",
    "templates/SUPPORT.md",
    "templates/SKILLS.md",
    "tools/quality/check-coverage.py",
    ".agents/skills/git-commit-push-tag/references/git-starter-kit-release-package.txt",
    ".github/CODEOWNERS",
    ".github/workflows/release-package.yml",
    "SHA256SUMS",
    "VERSION",
    "docs/release-package.md",
    "docs/upgrade-toolkit.md",
    "manifest.json",
    "tests/test_build_release_package.py",
    "tests/test_starter_kit_manifest.py",
    "tests/test_starter_kit_upgrade.py",
    "tools/build-release-package.ps1",
    "tools/starter-kit-manifest.py",
    "tools/starter-kit-upgrade.py",
    "tools/starter_kit_upgrade/__init__.py",
    "tools/starter_kit_upgrade/application.py",
    "tools/starter_kit_upgrade/archive.py",
    "tools/starter_kit_upgrade/cli.py",
    "tools/starter_kit_upgrade/common.py",
    "tools/starter_kit_upgrade/planning.py"
)
$StarterOnlyPrefixes = @(
    "tools/starter_kit_upgrade/",
    "tests/",
    "docs/superpowers/",
    "templates/project/",
    ".superpowers/"
)
$CanonicalRepositorySlug = "asphyx0r/git-starter-kit"
$CanonicalRepositoryUrls = @(
    "https://github.com/asphyx0r/git-starter-kit",
    "https://github.com/asphyx0r/git-starter-kit.git"
)

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

$GitTimeoutSeconds = 30
$GitBulkTimeoutSeconds = 300
$HttpTimeoutSeconds = 60

if (-not ("ReleaseProcessScope" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public sealed class ReleaseProcessScope : IDisposable
{
    private const uint CreateSuspended = 4;
    private const uint CreateNoWindow = 0x08000000;
    private const int StartUseStandardHandles = 0x100;
    private IntPtr job;
    public Process Process { get; private set; }
    public StreamReader Output { get; private set; }
    public StreamReader Error { get; private set; }

    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes
    {
        public int Size;
        public IntPtr Descriptor;
        [MarshalAs(UnmanagedType.Bool)] public bool Inherit;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public int Size;
        public string Reserved;
        public string Desktop;
        public string Title;
        public int X;
        public int Y;
        public int Width;
        public int Height;
        public int Columns;
        public int Rows;
        public int Fill;
        public int Flags;
        public short Show;
        public short ReservedSize;
        public IntPtr ReservedBytes;
        public IntPtr Input;
        public IntPtr Output;
        public IntPtr Error;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation
    {
        public IntPtr Process;
        public IntPtr Thread;
        public int ProcessId;
        public int ThreadId;
    }
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateJobObject(IntPtr job, int exitCode);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CreatePipe(out IntPtr read, out IntPtr write,
        ref SecurityAttributes attributes, int size);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetHandleInformation(IntPtr handle, int mask, int flags);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CreateProcess(string application, StringBuilder command,
        IntPtr processAttributes, IntPtr threadAttributes, bool inherit, uint flags,
        IntPtr environment, string directory, ref StartupInfo startup, out ProcessInformation process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateProcess(IntPtr process, int exitCode);
    [DllImport("kernel32.dll")]
    private static extern IntPtr GetStdHandle(int kind);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
    [DllImport("libc", EntryPoint = "kill", SetLastError = true)]
    private static extern int Kill(int processGroup, int signal);

    public static void StopGroup(int processId)
    {
        if (Kill(-processId, 9) != 0 && Marshal.GetLastWin32Error() != 3)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    private static StreamReader CreateOutputPipe(out IntPtr write)
    {
        SecurityAttributes attributes = new SecurityAttributes();
        attributes.Size = Marshal.SizeOf(attributes);
        attributes.Inherit = true;
        IntPtr read;
        if (!CreatePipe(out read, out write, ref attributes, 0))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        SafeFileHandle handle = new SafeFileHandle(read, true);
        try
        {
            if (!SetHandleInformation(read, 1, 0))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return new StreamReader(new FileStream(handle, FileAccess.Read), Encoding.UTF8);
        }
        catch
        {
            handle.Dispose();
            throw;
        }
    }

    public static ReleaseProcessScope Start(string executable, string command)
    {
        ReleaseProcessScope scope = new ReleaseProcessScope();
        IntPtr outputWrite = IntPtr.Zero;
        IntPtr errorWrite = IntPtr.Zero;
        ProcessInformation information = new ProcessInformation();
        try
        {
            scope.job = CreateJobObject(IntPtr.Zero, null);
            if (scope.job == IntPtr.Zero) { throw new Win32Exception(Marshal.GetLastWin32Error()); }
            scope.Output = CreateOutputPipe(out outputWrite);
            scope.Error = CreateOutputPipe(out errorWrite);
            StartupInfo startup = new StartupInfo();
            startup.Size = Marshal.SizeOf(startup);
            startup.Flags = StartUseStandardHandles;
            startup.Input = GetStdHandle(-10);
            startup.Output = outputWrite;
            startup.Error = errorWrite;
            if (!CreateProcess(executable, new StringBuilder(command), IntPtr.Zero, IntPtr.Zero,
                true, CreateSuspended | CreateNoWindow, IntPtr.Zero, null, ref startup, out information))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            scope.Process = Process.GetProcessById(information.ProcessId);
            if (!AssignProcessToJobObject(scope.job, scope.Process.Handle) ||
                ResumeThread(information.Thread) == UInt32.MaxValue)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return scope;
        }
        catch
        {
            // Creation succeeded but assignment/resumption may have failed.
            try
            {
                if (information.Process != IntPtr.Zero && !TerminateProcess(information.Process, 1))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
            }
            finally { scope.Dispose(); }
            throw;
        }
        finally
        {
            if (outputWrite != IntPtr.Zero) { CloseHandle(outputWrite); }
            if (errorWrite != IntPtr.Zero) { CloseHandle(errorWrite); }
            if (information.Thread != IntPtr.Zero) { CloseHandle(information.Thread); }
            if (information.Process != IntPtr.Zero) { CloseHandle(information.Process); }
        }
    }

    public void Stop()
    {
        if (job != IntPtr.Zero && !TerminateJobObject(job, 1))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public void Dispose()
    {
        try { Stop(); }
        finally
        {
            if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
            if (Output != null) { Output.Dispose(); }
            if (Error != null) { Error.Dispose(); }
            if (Process != null) { Process.Dispose(); }
        }
    }
}
'@
}


function ConvertTo-NativeArgument {
    param([AllowEmptyString()][string]$Argument)

    # Windows PowerShell 5.1 lacks ProcessStartInfo.ArgumentList.
    $quoted = [regex]::Replace($Argument, '(\\*)"', '$1$1\"')
    $quoted = [regex]::Replace($quoted, '(\\+)$', '$1$1')
    return '"' + $quoted + '"'
}

function Invoke-GitLine {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [double]$TimeoutSeconds = $(
            if ($Arguments -contains "ls-files" -or $Arguments -contains "ls-tree") {
                $GitBulkTimeoutSeconds
            }
            else {
                $GitTimeoutSeconds
            }
        )
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $gitPath = @(Get-Command git -CommandType Application -ErrorAction Stop)[0].Source
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT -and
        [System.IO.Path]::GetFileName($gitPath) -ieq "git.exe" -and
        (Split-Path -Leaf (Split-Path -Parent $gitPath)) -in @("cmd", "bin")) {
        $installation = Split-Path -Parent (Split-Path -Parent $gitPath)
        foreach ($architecture in @("mingw64", "mingw32")) {
            $nativeGit = Join-Path $installation "$architecture/bin/git.exe"
            if (Test-Path -LiteralPath $nativeGit -PathType Leaf) {
                $gitPath = $nativeGit
                break
            }
        }
    }
    $argumentLine = ($Arguments | ForEach-Object { ConvertTo-NativeArgument -Argument $_ }) -join ' '
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $totalMilliseconds = $TimeoutSeconds * 1000
    $workMilliseconds = $totalMilliseconds - [Math]::Min(1000, $totalMilliseconds / 2)
    $scope = $null
    $process = $null
    $tasks = @()
    try {
        if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
            $commandLine = (ConvertTo-NativeArgument -Argument $gitPath) + ' ' + $argumentLine
            $scope = [ReleaseProcessScope]::Start($gitPath, $commandLine)
            $process = $scope.Process
            $stdout = $scope.Output.ReadToEndAsync()
            $stderr = $scope.Error.ReadToEndAsync()
        }
        else {
            $setsid = @(Get-Command setsid -CommandType Application -ErrorAction SilentlyContinue)
            if ($setsid.Count -eq 0) {
                throw "setsid (util-linux) is required to bound Git process groups on Unix."
            }
            $startInfo.FileName = $setsid[0].Source
            $startInfo.Arguments = (ConvertTo-NativeArgument -Argument $gitPath) + ' ' + $argumentLine
            $startInfo.UseShellExecute = $false
            $startInfo.CreateNoWindow = $true
            $startInfo.RedirectStandardOutput = $true
            $startInfo.RedirectStandardError = $true
            $process = [System.Diagnostics.Process]::Start($startInfo)
            $stdout = $process.StandardOutput.ReadToEndAsync()
            $stderr = $process.StandardError.ReadToEndAsync()
        }
        # Native creation is synchronous; budget execution, collection and cleanup together.
        $watch.Restart()
        $tasks = [System.Threading.Tasks.Task[]]@($stdout, $stderr)
        if (-not $process.WaitForExit((Get-ProcessTimeRemaining -Watch $watch -Limit $workMilliseconds)) -or
            -not [System.Threading.Tasks.Task]::WaitAll(
                $tasks, (Get-ProcessTimeRemaining -Watch $watch -Limit $workMilliseconds))) {
            throw "git $($Arguments -join ' ') timed out after $TimeoutSeconds seconds."
        }
        if ($process.ExitCode -ne 0) {
            throw "git $($Arguments -join ' ') failed: $($stderr.Result.Trim())"
        }
        $reader = New-Object System.IO.StringReader($stdout.Result)
        try {
            while ($null -ne ($line = $reader.ReadLine())) { $line }
        }
        finally { $reader.Dispose() }
    }
    finally {
        if ($null -ne $process) {
            try {
                if ($null -ne $scope) { $scope.Stop() }
                else { [ReleaseProcessScope]::StopGroup($process.Id) }
                if (-not $process.WaitForExit((Get-ProcessTimeRemaining -Watch $watch -Limit $totalMilliseconds)) -or
                    -not [System.Threading.Tasks.Task]::WaitAll(
                        $tasks, (Get-ProcessTimeRemaining -Watch $watch -Limit $totalMilliseconds))) {
                    throw "git $($Arguments -join ' ') timed out during process cleanup."
                }
            }
            finally {
                if ($null -ne $scope) { $scope.Dispose() }
                else { $process.Dispose() }
            }
        }
    }
}

function Get-ProcessTimeRemaining {
    param([Diagnostics.Stopwatch]$Watch, [double]$Limit)

    return [int][Math]::Max(0, [Math]::Floor($Limit - $Watch.Elapsed.TotalMilliseconds))
}

function Get-GitHubLatestRelease {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $headers = @{
        Accept                 = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
        $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
    }

    $releaseUrl = "https://api.github.com/repos/$Repository/releases/latest"
    try {
        return Invoke-RestMethod `
            -Method Get `
            -Uri $releaseUrl `
            -Headers $headers `
            -UserAgent "git-starter-kit-release-package" `
            -TimeoutSec $HttpTimeoutSeconds
    }
    catch {
        throw "Unable to resolve latest agent rules release from $releaseUrl`: $($_.Exception.Message)"
    }
}

function Resolve-AgentRulesRelease {
    param(
        [string]$RequestedRef,
        [Parameter(Mandatory = $true)][string]$Repository
    )

    if ([string]::IsNullOrWhiteSpace($RequestedRef)) {
        throw "AgentRulesRef must be latest or a SemVer tag prefixed with v."
    }

    $normalizedRef = $RequestedRef.Trim()
    if ($normalizedRef -cne "latest" -and $normalizedRef -notmatch $SemVerTagPattern) {
        throw "AgentRulesRef must be latest or a SemVer tag prefixed with v."
    }
    $latestRelease = Get-GitHubLatestRelease -Repository $Repository
    $latestRef = [string]$latestRelease.tag_name
    if ([string]::IsNullOrWhiteSpace($latestRef) -or $latestRef -notmatch $SemVerTagPattern) {
        throw "Latest agent rules release tag must be a SemVer tag prefixed with v."
    }
    if ($normalizedRef -cne "latest" -and $normalizedRef -cne $latestRef) {
        throw "AgentRulesRef must identify the latest published agent rules release ($latestRef)."
    }
    $immutableRules = Get-GitHubImmutableAgentRuleSet -Repository $Repository -Reference $latestRef
    return [ordered]@{
        RequestedRef = $normalizedRef
        Ref          = $latestRef
        Commit       = $immutableRules.Commit
        Files        = $immutableRules.Files
        ReleaseUrl   = [string]$latestRelease.html_url
        ReleaseDate  = [string]$latestRelease.published_at
    }
}

function Get-GitHubApiResponse {
    param([Parameter(Mandatory = $true)][string]$ApiPath)

    $headers = @{ Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28" }
    if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
    try {
        Invoke-RestMethod -Uri "https://api.github.com/$ApiPath" -Headers $headers `
            -UserAgent "git-starter-kit-release-package" -TimeoutSec $HttpTimeoutSeconds
    }
    catch {
        throw "Unable to verify immutable upstream agent rules ($ApiPath): $($_.Exception.Message)"
    }
}

function Get-GitHubImmutableAgentRuleSet {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Reference
    )

    $tag = Get-GitHubApiResponse -ApiPath "repos/$Repository/git/ref/tags/$([Uri]::EscapeDataString($Reference))"
    if ([string]$tag.ref -cne "refs/tags/$Reference") { throw "Upstream agent rules ref identity mismatch." }
    $object = $tag.object
    $seen = @{}
    while ([string]$object.type -ceq "tag") {
        $tagSha = [string]$object.sha
        if ($tagSha -notmatch "^[0-9a-f]{40}$" -or $seen.ContainsKey($tagSha)) {
            throw "Upstream agent rules tag has an invalid or cyclic object identity."
        }
        $seen[$tagSha] = $true
        $peeled = Get-GitHubApiResponse -ApiPath "repos/$Repository/git/tags/$tagSha"
        if ([string]$peeled.sha -cne $tagSha) { throw "Upstream agent rules tag identity mismatch." }
        $object = $peeled.object
    }
    $commit = [string]$object.sha
    if ([string]$object.type -cne "commit" -or $commit -notmatch "^[0-9a-f]{40}$") {
        throw "Upstream agent rules tag must resolve to an immutable commit."
    }
    $verifiedCommit = Get-GitHubApiResponse -ApiPath "repos/$Repository/git/commits/$commit"
    if ([string]$verifiedCommit.sha -cne $commit) { throw "Upstream agent rules commit identity mismatch." }
    $treeSha = [string]$verifiedCommit.tree.sha
    if ($treeSha -notmatch "^[0-9a-f]{40}$") { throw "Upstream agent rules tree identity is invalid." }
    $tree = Get-GitHubApiResponse -ApiPath "repos/$Repository/git/trees/$treeSha"
    if ([string]$tree.sha -cne $treeSha -or $tree.truncated) { throw "Upstream agent rules tree identity mismatch or truncation." }
    $files = @{}
    foreach ($ruleFile in $RequiredRuleFiles) {
        $records = @($tree.tree | Where-Object { [string]$_.path -ceq $ruleFile })
        if ($records.Count -ne 1 -or [string]$records[0].type -cne "blob" -or
            [string]$records[0].mode -cne "100644") {
            throw "Upstream rule must be one regular root blob: $ruleFile"
        }
        $blobSha = [string]$records[0].sha
        if ($blobSha -notmatch "^[0-9a-f]{40}$") { throw "Upstream rule blob identity is invalid: $ruleFile" }
        $blob = Get-GitHubApiResponse -ApiPath "repos/$Repository/git/blobs/$blobSha"
        if ([string]$blob.sha -cne $blobSha -or [string]$blob.encoding -cne "base64") {
            throw "Upstream rule blob identity or encoding mismatch: $ruleFile"
        }
        $bytes = [Convert]::FromBase64String([string]$blob.content)
        $header = [Text.Encoding]::ASCII.GetBytes("blob $($bytes.Length)" + [char]0)
        $sha1 = [Security.Cryptography.SHA1]::Create()
        try { $digest = $sha1.ComputeHash([byte[]]($header + $bytes)) }
        finally { $sha1.Dispose() }
        $actualBlob = ($digest | ForEach-Object { $_.ToString("x2") }) -join ""
        if ($actualBlob -cne $blobSha) { throw "Upstream rule Git blob digest mismatch: $ruleFile" }
        $files[$ruleFile] = $bytes
    }
    return [ordered]@{ Commit = $commit; Files = $files }
}

function Copy-TrackedRepositoryFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$TargetRoot,
        [Parameter(Mandatory = $true)][string]$RepositoryReference
    )

    if ($RepositoryReference -match $SemVerTagPattern) {
        $tagCommit = ((Invoke-GitLine -Arguments @(
            "-C",
            $SourceRoot,
            "rev-parse",
            "--verify",
            "refs/tags/$RepositoryReference^{commit}"
        )) -join "").Trim()
        $headCommit = ((Invoke-GitLine -Arguments @(
            "-C",
            $SourceRoot,
            "rev-parse",
            "HEAD"
        )) -join "").Trim()
        if ($tagCommit -cne $headCommit) {
            throw "RepositoryRef tag must resolve to HEAD for SemVer packaging."
        }

        $manifestTool = Join-Path $SourceRoot "tools/starter-kit-manifest.py"
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $manifestCheck = & python $manifestTool check `
                --repository-root $SourceRoot `
                --expected-ref $RepositoryReference `
                --treeish HEAD 2>&1
            if ($LASTEXITCODE -ne 0) {
                $message = @($manifestCheck | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
                throw "Starter-kit manifest validation failed: $message"
            }
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }

        $releaseManifest = Get-Content `
            -LiteralPath (Join-Path $SourceRoot $StarterKitManifestPath) `
            -Raw |
            ConvertFrom-Json
        $trackedFiles = @(
            @($releaseManifest.files | ForEach-Object { [string]$_.path }) +
                $RequiredRuleFiles +
                @("_agent-rules-source.json", $StarterKitManifestPath)
        )
    }
    else {
        $trackedFiles = @(
            Invoke-GitLine -Arguments @("-C", $SourceRoot, "ls-files")
            $StarterKitManifestPath
        ) | Sort-Object -Unique
    }

    foreach ($relativePath in $trackedFiles) {
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }
        $isStarterOnly = $StarterOnlyPaths -ccontains $relativePath
        foreach ($starterOnlyPrefix in $StarterOnlyPrefixes) {
            if ($relativePath.StartsWith(
                    $starterOnlyPrefix,
                    [System.StringComparison]::Ordinal
                )) {
                $isStarterOnly = $true
                break
            }
        }
        if ($isStarterOnly) {
            continue
        }

        $nativePath = $relativePath -replace "/", [System.IO.Path]::DirectorySeparatorChar
        $sourcePath = Join-Path $SourceRoot $nativePath
        if ($RepositoryReference -match $SemVerTagPattern) {
            $headObject = ((Invoke-GitLine -Arguments @(
                "-C",
                $SourceRoot,
                "rev-parse",
                ("HEAD:{0}" -f $relativePath)
            )) -join "").Trim()
            $worktreeObject = ((Invoke-GitLine -Arguments @(
                "-C",
                $SourceRoot,
                "hash-object",
                ("--path={0}" -f $relativePath),
                $sourcePath
            )) -join "").Trim()
            if ($headObject -cne $worktreeObject) {
                throw "Packaged file differs from HEAD: $relativePath"
            }
        }

        $targetPath = Join-Path $TargetRoot $nativePath
        $targetDirectory = Split-Path -Parent $targetPath

        if (-not [string]::IsNullOrWhiteSpace($targetDirectory)) {
            New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
        }

        Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
    }
}

function Get-GitFileModeMap {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $modes = @{}
    $indexLines = Invoke-GitLine -Arguments @("-C", $Repository, "ls-files", "--stage")
    foreach ($line in $indexLines) {
        $match = [regex]::Match(
            $line,
            "^(?<mode>[0-9]{6}) [0-9a-f]+ [0-9]+`t(?<path>.+)$"
        )
        if ($match.Success) {
            $modes[$match.Groups["path"].Value] = $match.Groups["mode"].Value
        }
    }

    return $modes
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $digest = $sha256.ComputeHash($stream)
        }
        finally {
            $sha256.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }

    return (($digest | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Get-Sha256ByteArray {
    param([Parameter(Mandatory = $true)][AllowEmptyCollection()][byte[]]$Content)

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($Content)
    }
    finally {
        $sha256.Dispose()
    }

    return (($digest | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Get-ContentMetadataRecord {
    param([Parameter(Mandatory = $true)][string]$Path)

    $content = [System.IO.File]::ReadAllBytes($Path)
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    try {
        $text = $encoding.GetString($content)
        $canonicalText = $text -replace "`r`n?", "`n"
        if ($canonicalText.Length -gt 0) {
            $canonicalText = $canonicalText.TrimEnd([char]"`n") + "`n"
        }
        $canonicalEncoding = New-Object System.Text.UTF8Encoding($false)
        $canonicalContent = $canonicalEncoding.GetBytes($canonicalText)
        return [ordered]@{
            contentKind     = "text"
            canonicalSha256 = Get-Sha256ByteArray -Content $canonicalContent
        }
    }
    catch [System.Text.DecoderFallbackException] {
        return [ordered]@{
            contentKind     = "binary"
            canonicalSha256 = Get-Sha256ByteArray -Content $content
        }
    }
}

function Get-UpgradeStrategy {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($Path -ceq $StarterKitManifestPath) {
        return "starter-kit-state"
    }

    $agentRules = $RequiredRuleFiles + @("_agent-rules-source.json")
    if ($agentRules -contains $Path) {
        return "agent-rules"
    }

    $initializeOnly = @(
        ".starter-kit-project.json",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "SUPPORT.md",
        "docs/SKILLS.md",
        "docs/repository-files.md",
        "docs/repository-migration.md",
        "tools/README.md"
    )
    if ($initializeOnly -contains $Path) {
        return "initialize-only"
    }

    $mergeManaged = @(
        ".betterleaks.toml",
        ".codespellrc",
        ".editorconfig",
        ".gitattributes",
        ".gitleaks.toml",
        ".gitignore",
        ".github/dependabot.yml",
        ".github/workflows/repository-audit.yml"
    )
    if ($mergeManaged -contains $Path) {
        return "merge"
    }

    if ($Path.StartsWith(
            "tools/quality/",
            [System.StringComparison]::Ordinal
        )) {
        return "replace"
    }

    return "replace"
}

function Get-RepositoryName {
    param(
        [string]$Slug,
        [Parameter(Mandatory = $true)][string]$Root
    )
    if (-not [string]::IsNullOrWhiteSpace($Slug)) {
        $parts = $Slug.Trim().Split("/")
        if ($parts.Count -eq 2 -and
            -not [string]::IsNullOrWhiteSpace($parts[0]) -and
            -not [string]::IsNullOrWhiteSpace($parts[1])) {
            return $parts[1]
        }

        throw "RepositorySlug must use the owner/name format."
    }

    return (Split-Path -Leaf $Root)
}

function ConvertTo-GitHubRepositorySlug {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $normalized = $Repository.Trim()
    $normalized = $normalized -replace "^https://github\.com/", ""
    $normalized = $normalized -replace "\.git$", ""
    if ($normalized -notmatch "^[^/]+/[^/]+$") {
        throw "Repository values must use owner/name or a GitHub repository URL."
    }

    return $normalized
}

function Resolve-StarterKitProvenance {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RepositoryName,
        [Parameter(Mandatory = $true)][string]$RepositoryCommit,
        [Parameter(Mandatory = $true)][string]$RepositoryReference,
        [string]$StarterRepository,
        [string]$StarterReference,
        [string]$StarterCommit
    )

    $sourceManifestPath = Join-Path $Root "_agent-rules-source.json"
    if (([string]::IsNullOrWhiteSpace($StarterReference) -or
            [string]::IsNullOrWhiteSpace($StarterCommit)) -and
        (Test-Path -LiteralPath $sourceManifestPath -PathType Leaf)) {
        $sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw |
            ConvertFrom-Json
        $starterKitProperty = $sourceManifest.PSObject.Properties["starterKit"]
        if ($null -ne $starterKitProperty -and
            $null -ne $starterKitProperty.Value) {
            $sourceStarterKit = $starterKitProperty.Value
            if ([string]::IsNullOrWhiteSpace($StarterRepository)) {
                $StarterRepository = [string]$sourceStarterKit.repository
            }
            if ([string]::IsNullOrWhiteSpace($StarterReference)) {
                $StarterReference = [string]$sourceStarterKit.ref
            }
            if ([string]::IsNullOrWhiteSpace($StarterCommit)) {
                $StarterCommit = [string]$sourceStarterKit.commit
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($StarterReference) -or
        [string]::IsNullOrWhiteSpace($StarterCommit)) {
        if ($RepositoryName -cne "git-starter-kit") {
            throw "StarterKitRef and StarterKitCommit are required when the packaged repository has no starterKit provenance."
        }

        $StarterReference = $RepositoryReference
        $StarterCommit = $RepositoryCommit
    }

    return [ordered]@{
        Repository = ConvertTo-GitHubRepositorySlug -Repository $StarterRepository
        Ref        = $StarterReference
        Commit     = $StarterCommit
    }
}

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Resolve-PackageFilePath {
    param(
        [Parameter(Mandatory = $true)][string]$OutputRoot,
        [Parameter(Mandatory = $true)][string]$PackageName
    )

    if ([string]::IsNullOrWhiteSpace($PackageName)) {
        throw "PackageName must not be empty."
    }

    if ([System.IO.Path]::IsPathRooted($PackageName) -or
        $PackageName.Contains("/") -or
        $PackageName.Contains("\")) {
        throw "PackageName must be a file name, not a path."
    }

    if ($PackageName.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "PackageName contains invalid file name characters."
    }

    $resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
    $packagePath = [System.IO.Path]::GetFullPath(
        (Join-Path $resolvedOutputRoot $PackageName)
    )
    $rootPrefix = $resolvedOutputRoot.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar

    if (-not $packagePath.StartsWith(
            $rootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
        throw "Package path must stay inside OutputDirectory."
    }

    return $packagePath
}

function Get-PackageFileRecord {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][hashtable]$Modes)

    $records = @{}
    foreach ($file in Get-ChildItem -LiteralPath $Root -File -Recurse -Force) {
        $relativePath = $file.FullName.Substring($Root.Length + 1) -replace "\\", "/"
        $mode = "100644"
        if ($Modes.ContainsKey($relativePath)) { $mode = $Modes[$relativePath] }
        $metadata = Get-ContentMetadataRecord -Path $file.FullName
        $records[$relativePath] = [ordered]@{
            path = $relativePath
            sha256 = Get-Sha256 -Path $file.FullName
            canonicalSha256 = $metadata.canonicalSha256
            contentKind = $metadata.contentKind
            mode = $mode
            strategy = Get-UpgradeStrategy -Path $relativePath
        }
    }
    $paths = [string[]]@($records.Keys)
    [Array]::Sort($paths, [StringComparer]::Ordinal)
    foreach ($path in $paths) { $records[$path] }
}

function Assert-TrackedProjectTemplate {
    param([Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$RepositoryReference)

    if ($RepositoryReference -match $SemVerTagPattern) {
        $trackedTemplates = @(Invoke-GitLine -Arguments @(
            "-C", $SourceRoot, "ls-tree", "-r", "--name-only", "HEAD", "--", "templates/project/"
        ))
        if ($trackedTemplates.Count -eq 0) { throw "HEAD contains no consumer composition templates." }
        foreach ($sourceRelativePath in $trackedTemplates) {
            $sourcePath = Join-Path $SourceRoot $sourceRelativePath
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
                throw "Tracked composed template is missing: $sourceRelativePath"
            }
        }
    }
}

function Copy-ProjectTemplate {
    param([Parameter(Mandatory = $true)][string]$SourceRoot, [Parameter(Mandatory = $true)][string]$TargetRoot,
        [Parameter(Mandatory = $true)][string]$RepositoryReference)

    $templatesRoot = Join-Path $SourceRoot "templates/project"
    foreach ($file in Get-ChildItem -LiteralPath $templatesRoot -File -Recurse -Force) {
        $relativePath = $file.FullName.Substring($templatesRoot.Length + 1)
        if ($RepositoryReference -match $SemVerTagPattern) {
            $sourceRelativePath = "templates/project/" + ($relativePath -replace "\\", "/")
            $headObject = ((Invoke-GitLine -Arguments @("-C", $SourceRoot, "rev-parse", "HEAD:$sourceRelativePath")) -join "").Trim()
            $worktreeObject = ((Invoke-GitLine -Arguments @("-C", $SourceRoot, "hash-object", "--path=$sourceRelativePath", $file.FullName)) -join "").Trim()
            if ($headObject -cne $worktreeObject) { throw "Composed template differs from HEAD: $sourceRelativePath" }
        }
        $destination = Join-Path $TargetRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    }
    $configuration = & python -B -c "import json,sys; sys.path.insert(0,sys.argv[1]); from project_config import default_project_configuration; print(json.dumps(default_project_configuration(),indent=2))" (Join-Path $SourceRoot "tools")
    if ($LASTEXITCODE -ne 0) { throw "Unable to compose the shared default project configuration." }
    Write-Utf8NoBomFile -Path (Join-Path $TargetRoot ".starter-kit-project.json") `
        -Content (($configuration -join "`n") + "`n")
    $inventoryDocument = Join-Path $TargetRoot "docs/repository-files.md"
    $inventoryHeader = Get-Content -LiteralPath $inventoryDocument -Raw
    $paths = @(Get-ChildItem -LiteralPath $TargetRoot -File -Recurse -Force | ForEach-Object {
        $_.FullName.Substring($TargetRoot.Length + 1) -replace "\\", "/"
    }) + @("_starter-kit-files.json")
    Write-Utf8NoBomFile -Path $inventoryDocument `
        -Content ($inventoryHeader.TrimEnd() + "`n`n" + '```text' + "`n" + (($paths | Sort-Object -Unique) -join "`n") + "`n" + '```' + "`n")
    foreach ($document in Get-ChildItem -LiteralPath $TargetRoot -File -Recurse -Filter "*.md") {
        if ($RequiredRuleFiles -ccontains $document.Name) { continue }
        $text = Get-Content -LiteralPath $document.FullName -Raw
        foreach ($match in [regex]::Matches($text, "\[[^\]]*\]\(([^)]+)\)")) {
            $link = $match.Groups[1].Value.Split([char]"#")[0]
            if (-not $link -or $link -match "^[a-zA-Z][a-zA-Z0-9+.-]*:") { continue }
            $target = [IO.Path]::GetFullPath((Join-Path $document.DirectoryName $link))
            $rootPrefix = $TargetRoot + [IO.Path]::DirectorySeparatorChar
            if (-not $target.StartsWith($rootPrefix, [StringComparison]::Ordinal) -or
                -not (Test-Path -LiteralPath $target)) {
                throw "Consumer documentation relative link does not resolve: $($document.Name): $link"
            }
        }
    }
}

$repoRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$repoRoot = (Get-Item -LiteralPath $repoRoot -Force).FullName
$outputRoot = Get-FullPath -Path $OutputDirectory
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "git-starter-kit-release-package-$([guid]::NewGuid().ToString('N'))"
$stagingRoot = Join-Path $tempRoot "package"
$temporaryPackagePath = $null
$temporaryBackupPath = $null

if ($RepositorySlug -cne $CanonicalRepositorySlug) {
    throw "RepositorySlug must be exactly $CanonicalRepositorySlug."
}

try {
    $originUrl = ((Invoke-GitLine -Arguments @(
                "-C",
                $repoRoot,
                "remote",
                "get-url",
                "origin"
            )) -join "").Trim()
}
catch {
    throw "RepositoryRoot must have the canonical git-starter-kit origin: $($_.Exception.Message)"
}
if ($CanonicalRepositoryUrls -cnotcontains $originUrl) {
    throw "RepositoryRoot origin must identify the canonical git-starter-kit repository."
}

try {
    $repositoryCommit = ((Invoke-GitLine -Arguments @("-C", $repoRoot, "rev-parse", "HEAD")) -join "").Trim()
    if ([string]::IsNullOrWhiteSpace($RepositoryRef)) {
        $RepositoryRef = ((Invoke-GitLine -Arguments @("-C", $repoRoot, "rev-parse", "--short", "HEAD")) -join "").Trim()
    }

    $repositoryName = Get-RepositoryName `
        -Slug $RepositorySlug `
        -Root $repoRoot
    $starterKit = Resolve-StarterKitProvenance `
        -Root $repoRoot `
        -RepositoryName $repositoryName `
        -RepositoryCommit $repositoryCommit `
        -RepositoryReference $RepositoryRef `
        -StarterRepository $StarterKitRepository `
        -StarterReference $StarterKitRef `
        -StarterCommit $StarterKitCommit

    if ([string]::IsNullOrWhiteSpace($PackageName)) {
        $safeRef = $RepositoryRef -replace "[^A-Za-z0-9._-]", "-"
        $PackageName = "$repositoryName-$safeRef-with-agent-rules.zip"
    }
    elseif (-not $PackageName.EndsWith(".zip", [System.StringComparison]::OrdinalIgnoreCase)) {
        $PackageName = "$PackageName.zip"
    }

    $packagePath = Resolve-PackageFilePath `
        -OutputRoot $outputRoot `
        -PackageName $PackageName

    $resolvedAgentRules = Resolve-AgentRulesRelease `
        -RequestedRef $AgentRulesRef `
        -Repository $AgentRulesRepository
    $resolvedAgentRulesRef = $resolvedAgentRules.Ref

    $sourceProvenancePath = Join-Path $repoRoot "_agent-rules-source.json"
    if (-not (Test-Path -LiteralPath $sourceProvenancePath -PathType Leaf)) {
        throw "Tracked agent-rules provenance is required: _agent-rules-source.json"
    }
    try {
        $sourceProvenance = Get-Content -LiteralPath $sourceProvenancePath -Raw |
            ConvertFrom-Json
    }
    catch {
        throw "Tracked agent-rules provenance is invalid JSON."
    }
    if ([int]$sourceProvenance.schemaVersion -lt 3 -or
        $null -eq $sourceProvenance.agentRules) {
        throw "Tracked agent-rules provenance must use schema version 3."
    }

    $trackedAgentRulesRef = [string]$sourceProvenance.agentRules.ref
    if ($trackedAgentRulesRef -cne $resolvedAgentRulesRef) {
        throw "Tracked agent rules ref $trackedAgentRulesRef does not match requested ref $resolvedAgentRulesRef."
    }
    $trackedAgentRulesRepository = [string]$sourceProvenance.agentRules.repository
    $expectedAgentRulesRepository = "https://github.com/$AgentRulesRepository"
    if ($trackedAgentRulesRepository -cne $expectedAgentRulesRepository) {
        throw "Tracked agent rules repository does not match $expectedAgentRulesRepository."
    }
    $agentRulesCommit = [string]$sourceProvenance.agentRules.commit
    if ($agentRulesCommit -notmatch "^[0-9a-f]{40}$") {
        throw "Tracked agent-rules provenance has an invalid commit."
    }
    if ($agentRulesCommit -cne [string]$resolvedAgentRules.Commit) {
        throw "Tracked agent rules commit differs from latest immutable upstream; synchronize with the official updater."
    }
    Assert-TrackedProjectTemplate -SourceRoot $repoRoot -RepositoryReference $RepositoryRef
    New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
    $stagingRoot = (Get-Item -LiteralPath $stagingRoot -Force).FullName

    Write-Output "Validating tracked agent rules ref $resolvedAgentRulesRef."

    Copy-TrackedRepositoryFile `
        -SourceRoot $repoRoot `
        -TargetRoot $stagingRoot `
        -RepositoryReference $RepositoryRef
    $fileModes = Get-GitFileModeMap -Repository $repoRoot

    foreach ($ruleFile in $RequiredRuleFiles) {
        $rulePath = Join-Path $repoRoot $ruleFile
        if (-not (Test-Path -LiteralPath $rulePath -PathType Leaf)) {
            throw "Tracked rule file is missing: $ruleFile"
        }
        $ruleItem = Get-Item -LiteralPath $rulePath -Force
        if (($ruleItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Tracked rule file must not be a symbolic link: $ruleFile"
        }
        $hashProperty = $sourceProvenance.agentRules.fileHashes.PSObject.Properties[$ruleFile]
        if ($null -eq $hashProperty -or
            [string]::IsNullOrWhiteSpace([string]$hashProperty.Value)) {
            throw "Tracked provenance has no canonical hash for $ruleFile."
        }
        $upstreamBytes = [byte[]]$resolvedAgentRules.Files[$ruleFile]
        $encoding = New-Object System.Text.UTF8Encoding($false, $true)
        $upstreamText = $encoding.GetString($upstreamBytes)
        $localText = $encoding.GetString([IO.File]::ReadAllBytes($rulePath))
        # Markdown Git blobs are LF; CRLF checkout conversion is the only permitted byte adaptation.
        $localBlobBytes = $encoding.GetBytes($localText.Replace("`r`n", "`n"))
        if ((Get-Sha256ByteArray -Content $localBlobBytes) -cne
            (Get-Sha256ByteArray -Content $upstreamBytes)) {
            throw "Tracked rule $ruleFile differs from immutable upstream; synchronize with the official updater."
        }
        $canonicalText = $upstreamText -replace "`r`n?", "`n"
        $canonicalBytes = $encoding.GetBytes($canonicalText.TrimEnd([char]"`n") + "`n")
        if ([string]$hashProperty.Value -cne (Get-Sha256ByteArray -Content $canonicalBytes)) {
            throw "Tracked provenance hash differs from immutable upstream: $ruleFile"
        }
        [IO.File]::WriteAllBytes((Join-Path $stagingRoot $ruleFile), $upstreamBytes)
    }

    Copy-ProjectTemplate -SourceRoot $repoRoot -TargetRoot $stagingRoot -RepositoryReference $RepositoryRef
    $fileModes[".starter-kit-project.json"] = "100644"

    $manifest = [ordered]@{
        schemaVersion = 3
        generatedAt   = (Get-Date).ToUniversalTime().ToString("o")
        repository  = [ordered]@{
            name       = $repositoryName
            slug       = $RepositorySlug
            ref        = $RepositoryRef
            commit     = $repositoryCommit
        }
        starterKit  = [ordered]@{
            repository = "https://github.com/$($starterKit.Repository)"
            ref        = $starterKit.Ref
            commit     = $starterKit.Commit
        }
        agentRules = [ordered]@{
            repository   = $trackedAgentRulesRepository
            requestedRef = $resolvedAgentRules.RequestedRef
            ref          = $resolvedAgentRulesRef
            commit       = $agentRulesCommit
            releaseUrl   = $resolvedAgentRules.ReleaseUrl
            releaseDate  = $resolvedAgentRules.ReleaseDate
            files        = $RequiredRuleFiles
            fileHashes   = $sourceProvenance.agentRules.fileHashes
        }
    }

    $manifestPath = Join-Path $stagingRoot "_agent-rules-source.json"
    Write-Utf8NoBomFile -Path $manifestPath -Content ($manifest | ConvertTo-Json -Depth 8)
    $fileModes["_agent-rules-source.json"] = "100644"

    $starterStatePath = Join-Path $stagingRoot $StarterKitManifestPath
    $starterState = Get-Content -LiteralPath $starterStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $coreRecords = @(Get-PackageFileRecord -Root $stagingRoot -Modes $fileModes | Where-Object {
        $_.path -cne $StarterKitManifestPath -and $_.path -cne "_starter-kit-files.json" -and
        $_.strategy -cne "agent-rules"
    })
    $starterState.files = $coreRecords
    Write-Utf8NoBomFile -Path $starterStatePath -Content ($starterState | ConvertTo-Json -Depth 8)
    $starterStateSerializer = @'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
state = json.loads(path.read_text(encoding="utf-8"))
path.write_bytes((json.dumps(state, indent=2, sort_keys=False) + "\n").encode("utf-8"))
'@
    $starterStateSerializer | & python -B - $starterStatePath
    if ($LASTEXITCODE -ne 0) {
        throw "Starter-kit state serialization failed."
    }

    $fileManifestPath = Join-Path $stagingRoot "_starter-kit-files.json"
    $managedFiles = @(Get-PackageFileRecord -Root $stagingRoot -Modes $fileModes |
        Where-Object { $_.path -cne "_starter-kit-files.json" })
    $fileManifest = [ordered]@{
        schemaVersion = 3
        generatedAt   = $manifest.generatedAt
        repository    = $manifest.repository
        starterKit    = $manifest.starterKit
        agentRules    = [ordered]@{
            repository = $manifest.agentRules.repository
            ref        = $manifest.agentRules.ref
            commit     = $manifest.agentRules.commit
        }
        files         = $managedFiles
    }
    Write-Utf8NoBomFile `
        -Path $fileManifestPath `
        -Content ($fileManifest | ConvertTo-Json -Depth 8)

    $requiredFiles = $RequiredRuleFiles + @(
        ".githooks/commit-msg",
        "commitlint.config.cjs",
        ".starter-kit-project.json",
        "tools/initialize-repository.py",
        "tools/git-inventory-context/HEAD",
        "tools/git-inventory-context/objects/.gitkeep",
        "tools/git-inventory-context/refs/.gitkeep",
        "tools/project_config.py",
        "tools/project_validation.py",
        "tools/automation_config.py",
        "tools/release-artifacts.py",
        "tools/git_objects.py",
        "tools/process_runner.py",
        "tools/repository-audit.sh",
        "tools/repository-audit/common.sh",
        "tools/repository-audit/contracts.sh",
        "tools/repository-audit/hooks.sh",
        "tools/repository-audit/profiles.sh",
        "tools/repository-audit/security.sh",
        "tools/repository-audit/smoke.sh",
        "tools/repository-audit/agent-rules-transfer.sh",
        "tools/repository-audit/workflow-contracts.py",
        "templates/release/repository-manifest.schema.json",
        ".github/workflows/agent-rules-update.yml",
        "_agent-rules-source.json",
        "_starter-kit-files.json",
        $StarterKitManifestPath
    )
    foreach ($requiredFile in $requiredFiles) {
        $stagedPath = Join-Path $stagingRoot $requiredFile
        if (-not (Test-Path -LiteralPath $stagedPath -PathType Leaf)) {
            throw "Release package staging is missing required file: $requiredFile"
        }
    }


    if ($fileModes[".githooks/commit-msg"] -cne "100755") {
        throw "Packaged commit-msg hook must retain its executable Git mode."
    }

    $temporaryPackagePath = Join-Path `
        $outputRoot `
        ".$([System.IO.Path]::GetFileNameWithoutExtension($packagePath)).$([guid]::NewGuid().ToString('N')).zip.tmp"

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Add-Type -AssemblyName System.IO.Compression
    $zip = [System.IO.Compression.ZipFile]::Open($temporaryPackagePath, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in Get-ChildItem -LiteralPath $stagingRoot -File -Recurse -Force) {
            $name = $file.FullName.Substring($stagingRoot.Length + 1) -replace "\\", "/"
            $entry = $zip.CreateEntry($name, [IO.Compression.CompressionLevel]::Optimal)
            $unixMode = 33188
            if ($fileModes[$name] -ceq "100755") { $unixMode = 33261 }
            $entry.ExternalAttributes = $unixMode -shl 16
            $source = [IO.File]::OpenRead($file.FullName)
            $destination = $entry.Open()
            try { $source.CopyTo($destination) }
            finally { $source.Dispose(); $destination.Dispose() }
        }
    }
    finally { $zip.Dispose() }

    $zip = [System.IO.Compression.ZipFile]::OpenRead($temporaryPackagePath)
    try {
        $zipEntries = @($zip.Entries | ForEach-Object { $_.FullName -replace "\\", "/" })
        foreach ($requiredFile in $requiredFiles) {
            if ($zipEntries -notcontains $requiredFile) {
                throw "Release package archive is missing required file: $requiredFile"
            }
        }

        $archiveManagedPaths = @(
            $zipEntries |
                Where-Object {
                    -not $_.EndsWith("/") -and
                    $_ -cne "_starter-kit-files.json"
                } |
                Sort-Object
        )
        $manifestManagedPaths = @(
            $managedFiles |
                ForEach-Object { $_.path } |
                Sort-Object
        )
        $manifestDifference = @(
            Compare-Object `
                -ReferenceObject $archiveManagedPaths `
                -DifferenceObject $manifestManagedPaths
        )
        if ($manifestDifference.Count -ne 0) {
            throw "Managed-file manifest does not cover every archive file."
        }
        $inventoryEntry = $zip.GetEntry("_starter-kit-files.json")
        $inventoryStream = $inventoryEntry.Open()
        $inventoryBuffer = New-Object IO.MemoryStream
        try { $inventoryStream.CopyTo($inventoryBuffer); $inventoryBytes = $inventoryBuffer.ToArray() }
        finally { $inventoryStream.Dispose(); $inventoryBuffer.Dispose() }
        if ((Get-Sha256ByteArray -Content $inventoryBytes) -cne (Get-Sha256 -Path $fileManifestPath)) {
            throw "Composed archive inventory byte mismatch."
        }
        foreach ($record in $managedFiles) {
            $entry = $zip.GetEntry($record.path)
            $stream = $entry.Open()
            $buffer = New-Object IO.MemoryStream
            try { $stream.CopyTo($buffer); $bytes = $buffer.ToArray() }
            finally { $stream.Dispose(); $buffer.Dispose() }
            if ((Get-Sha256ByteArray -Content $bytes) -cne $record.sha256) {
                throw "Composed archive byte mismatch: $($record.path)"
            }
            $expectedMode = if ($record.mode -ceq "100755") { 33261 } else { 33188 }
            if (($entry.ExternalAttributes -shr 16 -band 65535) -ne $expectedMode) {
                throw "Composed archive mode mismatch: $($record.path)"
            }
        }

    }
    finally {
        $zip.Dispose()
    }

    if (Test-Path -LiteralPath $packagePath) {
        $temporaryBackupPath = Join-Path `
            $outputRoot `
            ".$([System.IO.Path]::GetFileNameWithoutExtension($packagePath)).$([guid]::NewGuid().ToString('N')).zip.bak"
        [System.IO.File]::Replace(
            $temporaryPackagePath,
            $packagePath,
            $temporaryBackupPath
        )
        Remove-Item -LiteralPath $temporaryBackupPath -Force
        $temporaryBackupPath = $null
    }
    else {
        [System.IO.File]::Move($temporaryPackagePath, $packagePath)
    }
    $temporaryPackagePath = $null

    if ($env:GITHUB_OUTPUT) {
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "package_path=$packagePath"
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "package_name=$PackageName"
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "agent_rules_ref=$resolvedAgentRulesRef"
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "agent_rules_commit=$agentRulesCommit"
    }

    Write-Output "Created release package: $packagePath"
}
finally {
    if ($null -ne $temporaryBackupPath -and
        (Test-Path -LiteralPath $temporaryBackupPath)) {
        Remove-Item -LiteralPath $temporaryBackupPath -Force
    }
    if ($null -ne $temporaryPackagePath -and
        (Test-Path -LiteralPath $temporaryPackagePath)) {
        Remove-Item -LiteralPath $temporaryPackagePath -Force
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
