param(
    [string]$RepositoryRoot = (Get-Location).Path,
    [string]$OutputDirectory = (Join-Path (Get-Location).Path "dist"),
    [string]$PackageName = "",
    [string]$StarterRef = $env:GITHUB_REF_NAME,
    [string]$AgentRulesRepository = "asphyx0r/agent-coding-rules",
    [string]$AgentRulesRef = "latest",
    [string]$GitHubToken = $env:GITHUB_TOKEN
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$RequiredRuleFiles = @(
    "AGENTS.md",
    "CODING_RULES.md",
    "COMMIT_RULES.md",
    "DOCUMENTATION_RULES.md",
    "LANGUAGE_RULES.md",
    "RELEASE_RULES.md"
)

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Invoke-GitLines {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

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

function Get-GitHubHeaders {
    $headers = @{
        "Accept"               = "application/vnd.github+json"
        "User-Agent"           = "git-starter-kit-release-package"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    if (-not [string]::IsNullOrWhiteSpace($GitHubToken)) {
        $headers["Authorization"] = "Bearer $GitHubToken"
    }

    return $headers
}

function Resolve-AgentRulesRelease {
    if ($AgentRulesRef -ne "latest") {
        return [ordered]@{
            Ref         = $AgentRulesRef
            ReleaseUrl  = $null
            ReleaseDate = $null
        }
    }

    $headers = Get-GitHubHeaders
    $uri = "https://api.github.com/repos/$AgentRulesRepository/releases/latest"
    $release = Invoke-RestMethod -Uri $uri -Headers $headers

    if ($null -eq $release -or $release.draft -or $release.prerelease) {
        throw "No stable published release found for $AgentRulesRepository."
    }

    return [ordered]@{
        Ref         = $release.tag_name
        ReleaseUrl  = $release.html_url
        ReleaseDate = $release.published_at
    }
}

function Copy-TrackedRepositoryFiles {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$TargetRoot
    )

    $trackedFiles = Invoke-GitLines -Arguments @("-C", $SourceRoot, "ls-files")
    foreach ($relativePath in $trackedFiles) {
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }

        $nativePath = $relativePath -replace "/", [System.IO.Path]::DirectorySeparatorChar
        $sourcePath = Join-Path $SourceRoot $nativePath
        $targetPath = Join-Path $TargetRoot $nativePath
        $targetDirectory = Split-Path -Parent $targetPath

        if (-not [string]::IsNullOrWhiteSpace($targetDirectory)) {
            New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
        }

        Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
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

$repoRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$outputRoot = Get-FullPath -Path $OutputDirectory
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "git-starter-kit-release-package-$([guid]::NewGuid().ToString('N'))"
$stagingRoot = Join-Path $tempRoot "package"
$agentRulesRoot = Join-Path $tempRoot "agent-coding-rules"

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

try {
    $starterCommit = ((Invoke-GitLines -Arguments @("-C", $repoRoot, "rev-parse", "HEAD")) -join "").Trim()
    if ([string]::IsNullOrWhiteSpace($StarterRef)) {
        $StarterRef = ((Invoke-GitLines -Arguments @("-C", $repoRoot, "rev-parse", "--short", "HEAD")) -join "").Trim()
    }

    $resolvedAgentRules = Resolve-AgentRulesRelease
    $resolvedAgentRulesRef = $resolvedAgentRules.Ref
    $agentRulesCloneUrl = "https://github.com/$AgentRulesRepository.git"

    Write-Host "Using agent rules ref $resolvedAgentRulesRef from $AgentRulesRepository."
    Invoke-GitLines -Arguments @(
        "clone",
        "--depth", "1",
        "--branch", $resolvedAgentRulesRef,
        $agentRulesCloneUrl,
        $agentRulesRoot
    ) | Out-Null

    $agentRulesCommit = ((Invoke-GitLines -Arguments @("-C", $agentRulesRoot, "rev-parse", "HEAD")) -join "").Trim()
    $agentRulesCommitDate = ((Invoke-GitLines -Arguments @("-C", $agentRulesRoot, "log", "-1", "--format=%cI")) -join "").Trim()

    Copy-TrackedRepositoryFiles -SourceRoot $repoRoot -TargetRoot $stagingRoot

    foreach ($ruleFile in $RequiredRuleFiles) {
        $sourcePath = Join-Path $agentRulesRoot $ruleFile
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Required rule file missing from agent rules source: $ruleFile"
        }

        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $stagingRoot $ruleFile) -Force
    }

    $manifest = [ordered]@{
        generatedAt = (Get-Date).ToUniversalTime().ToString("o")
        starterKit  = [ordered]@{
            repository = "https://github.com/asphyx0r/git-starter-kit"
            ref        = $StarterRef
            commit     = $starterCommit
        }
        agentRules = [ordered]@{
            repository  = "https://github.com/$AgentRulesRepository"
            ref         = $resolvedAgentRulesRef
            commit      = $agentRulesCommit
            commitDate  = $agentRulesCommitDate
            releaseUrl  = $resolvedAgentRules.ReleaseUrl
            releaseDate = $resolvedAgentRules.ReleaseDate
            files       = $RequiredRuleFiles
        }
    }

    $manifestPath = Join-Path $stagingRoot "_agent-rules-source.json"
    Write-Utf8NoBomFile -Path $manifestPath -Content ($manifest | ConvertTo-Json -Depth 6)

    foreach ($requiredFile in ($RequiredRuleFiles + "_agent-rules-source.json")) {
        $stagedPath = Join-Path $stagingRoot $requiredFile
        if (-not (Test-Path -LiteralPath $stagedPath -PathType Leaf)) {
            throw "Release package staging is missing required file: $requiredFile"
        }
    }

    if ([string]::IsNullOrWhiteSpace($PackageName)) {
        $safeRef = $StarterRef -replace "[^A-Za-z0-9._-]", "-"
        $PackageName = "git-starter-kit-$safeRef-with-agent-rules.zip"
    }
    elseif (-not $PackageName.EndsWith(".zip", [System.StringComparison]::OrdinalIgnoreCase)) {
        $PackageName = "$PackageName.zip"
    }

    $packagePath = Join-Path $outputRoot $PackageName
    if (Test-Path -LiteralPath $packagePath) {
        Remove-Item -LiteralPath $packagePath -Force
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stagingRoot,
        $packagePath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    $zip = [System.IO.Compression.ZipFile]::OpenRead($packagePath)
    try {
        $zipEntries = @($zip.Entries | ForEach-Object { $_.FullName -replace "\\", "/" })
        foreach ($requiredFile in ($RequiredRuleFiles + "_agent-rules-source.json")) {
            if ($zipEntries -notcontains $requiredFile) {
                throw "Release package archive is missing required file: $requiredFile"
            }
        }
    }
    finally {
        $zip.Dispose()
    }

    if ($env:GITHUB_OUTPUT) {
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "package_path=$packagePath"
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "package_name=$PackageName"
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "agent_rules_ref=$resolvedAgentRulesRef"
        Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "agent_rules_commit=$agentRulesCommit"
    }

    Write-Host "Created release package: $packagePath"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
