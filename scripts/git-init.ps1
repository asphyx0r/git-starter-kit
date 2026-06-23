$ScriptVersion = "1.0.0"
$DefaultTag = "v1.0.0"
$CommitMessage = "chore: initialize repository"
$TagMessage = "Initial version/First commit"
# Keep this pattern aligned with repository-audit SemVer smoke tests.
$SemVerTagPattern = "^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$showHelp = $false
$showVersion = $false
$verboseMode = $false
$path = ""
$remote = ""
$tag = $DefaultTag

function Write-Usage {
    Write-Output "git-init.ps1 $ScriptVersion"
    Write-Output ""
    Write-Output "Usage:"
    Write-Output "  powershell -NoProfile -File scripts\git-init.ps1 -p <path> [-t <tag>] [-r <remote>] [-v]"
    Write-Output ""
    Write-Output "Options:"
    Write-Output "  -h, --help       Show version and help."
    Write-Output "      --version    Show version only."
    Write-Output "  -v, --verbose    Show additional execution traces."
    Write-Output "  -p, --path       Target repository root. Required."
    Write-Output "  -r, --remote     Optional origin remote URL."
    Write-Output "  -t, --tag        SemVer Git tag. Default: $DefaultTag."
}

function Read-OptionValue {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][int]$Index,
        [Parameter(Mandatory = $true)][string]$OptionName
    )

    if ($Index + 1 -ge $Arguments.Count -or $Arguments[$Index + 1].StartsWith("-")) {
        throw "$OptionName requires a value."
    }

    return $Arguments[$Index + 1]
}

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$InputPath)

    if ([System.IO.Path]::IsPathRooted($InputPath)) {
        return [System.IO.Path]::GetFullPath($InputPath)
    }

    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $InputPath))
}

function Write-Trace {
    param([Parameter(Mandatory = $true)][string]$Message)

    if ($verboseMode) {
        Write-Output $Message
    }
}

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    Write-Trace "git $($Arguments -join ' ')"

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git @Arguments 2>&1
        if ($LASTEXITCODE -ne 0) {
            $message = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
            throw "git $($Arguments -join ' ') failed: $message"
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return @($output | ForEach-Object { $_.ToString() })
}

function Test-GitSuccess {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & git @Arguments *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-CommittableFile {
    param([Parameter(Mandatory = $true)][string]$RepositoryPath)

    $previewGitDirectory = ""
    try {
        $gitMetadataPath = Join-Path $RepositoryPath ".git"
        if (Test-Path -LiteralPath $gitMetadataPath) {
            $statusArguments = @(
                "-C", $RepositoryPath, "status", "--porcelain=v1", "-z",
                "--untracked-files=all"
            )
        }
        else {
            $previewGitDirectory = Join-Path `
                ([System.IO.Path]::GetTempPath()) `
                "git-init-preview-$([guid]::NewGuid().ToString('N'))"
            Invoke-Git -Arguments @("init", "--bare", $previewGitDirectory) | Out-Null
            $statusArguments = @(
                "--git-dir=$previewGitDirectory",
                "--work-tree=$RepositoryPath",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all"
            )
        }

        $statusText = (Invoke-Git -Arguments $statusArguments) -join ""
        $files = @()
        foreach ($entry in ($statusText -split "`0")) {
            if ($entry.Length -lt 4) {
                continue
            }

            $files += $entry.Substring(3)
        }

        return $files
    }
    finally {
        if (-not [string]::IsNullOrWhiteSpace($previewGitDirectory) -and
            (Test-Path -LiteralPath $previewGitDirectory)) {
            Remove-Item -LiteralPath $previewGitDirectory -Recurse -Force
        }
    }
}

function Test-RiskyPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $normalizedPath = ($Path -replace "\\", "/").ToLowerInvariant()
    if ($normalizedPath -match "(^|/)(node_modules|vendor|\.venv|venv|env|dist|build|coverage|logs?|tmp|temp|\.tmp|\.aws|\.kube|\.ssh)(/|$)") {
        return $true
    }

    foreach ($pattern in @(
            ".env", ".env.*", "*.env", "*.env.*", "*.secret", "*.secrets",
            ".npmrc", "*/.npmrc", ".pypirc", "*/.pypirc", ".netrc", "*/.netrc",
            "id_rsa", "*/id_rsa", "id_rsa.*", "*/id_rsa.*",
            "id_ed25519", "*/id_ed25519", "id_ed25519.*", "*/id_ed25519.*",
            "*.key", "*.pem", "*.p12", "*.pfx", "*.jks", "*.keystore",
            "*.log", "*.err", "*.out", "*.7z", "*.gz", "*.rar", "*.tar",
            "*.tar.gz", "*.tgz", "*.zip"
        )) {
        if ($normalizedPath -like $pattern) {
            return $true
        }
    }

    return $false
}

function Read-Confirmation {
    param([Parameter(Mandatory = $true)][string]$Prompt)

    Write-Output $Prompt
    $response = Read-Host
    return ($response -ceq "y" -or $response -ceq "Y")
}

if ($args.Count -eq 0) {
    Write-Usage
    exit 0
}

for ($index = 0; $index -lt $args.Count; $index++) {
    switch ($args[$index]) {
        "-h" { $showHelp = $true }
        "--help" { $showHelp = $true }
        "--version" { $showVersion = $true }
        "-v" { $verboseMode = $true }
        "--verbose" { $verboseMode = $true }
        "-p" {
            $path = Read-OptionValue -Arguments $args -Index $index -OptionName $args[$index]
            $index++
        }
        "--path" {
            $path = Read-OptionValue -Arguments $args -Index $index -OptionName $args[$index]
            $index++
        }
        "-r" {
            $remote = Read-OptionValue -Arguments $args -Index $index -OptionName $args[$index]
            $index++
        }
        "--remote" {
            $remote = Read-OptionValue -Arguments $args -Index $index -OptionName $args[$index]
            $index++
        }
        "-t" {
            $tag = Read-OptionValue -Arguments $args -Index $index -OptionName $args[$index]
            $index++
        }
        "--tag" {
            $tag = Read-OptionValue -Arguments $args -Index $index -OptionName $args[$index]
            $index++
        }
        default {
            throw "Unknown argument: $($args[$index])"
        }
    }
}

if ($showVersion) {
    Write-Output $ScriptVersion
    exit 0
}

if ($showHelp) {
    Write-Usage
    exit 0
}

if ([string]::IsNullOrWhiteSpace($path)) {
    throw "--path is required."
}

if ([string]::IsNullOrWhiteSpace($tag) -or $tag -notmatch $SemVerTagPattern) {
    throw "--tag must be a SemVer tag prefixed with v, for example v1.0.0."
}

$targetPath = Get-FullPath -InputPath $path
$gitMetadataPath = Join-Path $targetPath ".git"

if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
    throw "Target path must be an existing directory: $targetPath"
}

$targetEntries = @(
    Get-ChildItem -LiteralPath $targetPath -Force |
        Where-Object { $_.Name -ne ".git" }
)
if ($targetEntries.Count -eq 0) {
    throw "Target directory must contain files before Git initialization: $targetPath"
}

if (Test-Path -LiteralPath $gitMetadataPath) {
    if (Test-GitSuccess -Arguments @("-C", $targetPath, "rev-parse", "--verify", "HEAD")) {
        throw "Target repository already has commits: $targetPath"
    }

    if (Test-GitSuccess -Arguments @("-C", $targetPath, "rev-parse", "--verify", "refs/tags/$tag")) {
        throw "Tag already exists in target repository: $tag"
    }
}

$remoteDisplay = if ([string]::IsNullOrWhiteSpace($remote)) { "(none)" } else { $remote }

Write-Output "Initialize Git using this information? [y/N]"
Write-Output "Path: $targetPath"
Write-Output "Tag: $tag"
Write-Output "Remote: $remoteDisplay"
$confirmation = Read-Host

if ($confirmation -cne "y" -and $confirmation -cne "Y") {
    Write-Output "Git initialization cancelled."
    exit 0
}

$committableFiles = @(Get-CommittableFile -RepositoryPath $targetPath)
if ($committableFiles.Count -eq 0) {
    throw "No committable files found in target directory: $targetPath"
}

Write-Output "Files Git can commit:"
foreach ($file in $committableFiles) {
    Write-Output "  $file"
}

if (-not (Read-Confirmation -Prompt "Commit these files? [y/N]")) {
    Write-Output "Git commit cancelled."
    exit 0
}

$riskyFiles = @($committableFiles | Where-Object { Test-RiskyPath -Path $_ })
if ($riskyFiles.Count -gt 0) {
    Write-Output "Risky paths detected:"
    foreach ($file in $riskyFiles) {
        Write-Output "  $file"
    }

    if (-not (Read-Confirmation -Prompt "Continue with risky paths? [y/N]")) {
        Write-Output "Git commit cancelled."
        exit 0
    }
}

Invoke-Git -Arguments @("init", $targetPath) | Out-Null

if (Test-GitSuccess -Arguments @("-C", $targetPath, "rev-parse", "--verify", "refs/tags/$tag")) {
    throw "Tag already exists in target repository: $tag"
}

Invoke-Git -Arguments @("-C", $targetPath, "add", "--all") | Out-Null
Invoke-Git -Arguments @("-C", $targetPath, "commit", "-m", $CommitMessage) | Out-Null
Invoke-Git -Arguments @("-C", $targetPath, "branch", "-M", "main") | Out-Null
Invoke-Git -Arguments @("-C", $targetPath, "tag", "-a", $tag, "-m", $TagMessage) | Out-Null

if (-not [string]::IsNullOrWhiteSpace($remote)) {
    Invoke-Git -Arguments @("-C", $targetPath, "remote", "add", "origin", $remote) | Out-Null
    Invoke-Git -Arguments @("-C", $targetPath, "push", "-u", "origin", "main", "--tags") | Out-Null
}

Write-Output "Git repository initialized: $targetPath"
