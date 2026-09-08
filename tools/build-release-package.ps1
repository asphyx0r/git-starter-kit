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
    "tools/starter_kit_upgrade/"
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
    if ($normalizedRef -ceq "latest") {
        $latestRelease = Get-GitHubLatestRelease -Repository $Repository
        $latestRef = [string]$latestRelease.tag_name
        if ([string]::IsNullOrWhiteSpace($latestRef) -or
            $latestRef -notmatch $SemVerTagPattern) {
            throw "Latest agent rules release tag must be a SemVer tag prefixed with v."
        }

        return [ordered]@{
            RequestedRef = $normalizedRef
            Ref          = $latestRef
            ReleaseUrl   = [string]$latestRelease.html_url
            ReleaseDate  = [string]$latestRelease.published_at
        }
    }

    if ($normalizedRef -notmatch $SemVerTagPattern) {
        throw "AgentRulesRef must be latest or a SemVer tag prefixed with v."
    }

    return [ordered]@{
        RequestedRef = $normalizedRef
        Ref          = $normalizedRef
        ReleaseUrl   = $null
        ReleaseDate  = $null
    }
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
    param([Parameter(Mandatory = $true)][byte[]]$Content)

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

$repoRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
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
    $preservedProperty = $sourceProvenance.PSObject.Properties["preservedFiles"]
    $preservedFiles = @()
    if ($null -ne $preservedProperty -and $null -ne $preservedProperty.Value) {
        $preservedFiles = @($preservedProperty.Value)
    }

    New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

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
        $actualHash = (Get-ContentMetadataRecord -Path $rulePath).canonicalSha256
        $expectedHash = [string]$hashProperty.Value
        if ($actualHash -cne $expectedHash) {
            $preservedMatch = @(
                $preservedFiles |
                    Where-Object {
                        [string]$_.path -ceq $ruleFile -and
                        [string]$_.canonicalSha256 -ceq $actualHash
                    }
            )
            if ($preservedMatch.Count -ne 1) {
                throw "Tracked rule $ruleFile differs from source without a matching preservedFiles record."
            }
        }
    }

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
    if ($preservedFiles.Count -gt 0) {
        $manifest["preservedFiles"] = $preservedFiles
    }

    $manifestPath = Join-Path $stagingRoot "_agent-rules-source.json"
    Write-Utf8NoBomFile -Path $manifestPath -Content ($manifest | ConvertTo-Json -Depth 8)
    $fileModes["_agent-rules-source.json"] = "100644"

    $fileManifestPath = Join-Path $stagingRoot "_starter-kit-files.json"
    $managedFiles = @(
        Get-ChildItem -LiteralPath $stagingRoot -File -Recurse -Force |
            Where-Object { $_.FullName -cne $fileManifestPath } |
            ForEach-Object {
                $relativePath = $_.FullName.Substring($stagingRoot.Length + 1)
                $relativePath = $relativePath -replace "\\", "/"
                $mode = "100644"
                if ($fileModes.ContainsKey($relativePath)) {
                    $mode = $fileModes[$relativePath]
                }
                $contentMetadata = Get-ContentMetadataRecord -Path $_.FullName

                [ordered]@{
                    path            = $relativePath
                    sha256          = Get-Sha256 -Path $_.FullName
                    canonicalSha256 = $contentMetadata.canonicalSha256
                    contentKind     = $contentMetadata.contentKind
                    mode            = $mode
                    strategy        = Get-UpgradeStrategy -Path $relativePath
                }
            } |
            Sort-Object -Property path
    )
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


    $temporaryPackagePath = Join-Path `
        $outputRoot `
        ".$([System.IO.Path]::GetFileNameWithoutExtension($packagePath)).$([guid]::NewGuid().ToString('N')).zip.tmp"

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stagingRoot,
        $temporaryPackagePath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )

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
