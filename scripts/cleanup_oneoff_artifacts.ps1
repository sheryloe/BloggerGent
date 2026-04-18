param(
    [ValidateSet("dry-run", "apply")]
    [string]$Mode = "dry-run",
    [switch]$DeleteEnv,
    [switch]$AllowEnvDelete,
    [string]$ReportPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-AbsolutePath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$PathValue
    )
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $PathValue))
}

function Get-PathStat {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue)) {
        return [pscustomobject]@{
            exists = $false
            files = 0
            size_bytes = 0
            size_gb = 0
        }
    }
    if ((Get-Item -LiteralPath $PathValue).PSIsContainer) {
        $m = Get-ChildItem -LiteralPath $PathValue -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum
        return [pscustomobject]@{
            exists = $true
            files = [int]$m.Count
            size_bytes = [int64]$m.Sum
            size_gb = [math]::Round(($m.Sum / 1GB), 3)
        }
    }
    $f = Get-Item -LiteralPath $PathValue
    return [pscustomobject]@{
        exists = $true
        files = 1
        size_bytes = [int64]$f.Length
        size_gb = [math]::Round(($f.Length / 1GB), 6)
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$runtimeReportDir = "D:\Donggri_Runtime\BloggerGent\tools\reports"
if (-not (Test-Path -LiteralPath $runtimeReportDir)) {
    New-Item -ItemType Directory -Force -Path $runtimeReportDir | Out-Null
}

if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $ReportPath = Join-Path $runtimeReportDir ("cleanup-oneoff-artifacts-{0}.json" -f $stamp)
}
$reportAbs = Resolve-AbsolutePath -RepoRoot $repoRoot -PathValue $ReportPath
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $reportAbs) | Out-Null

$defaultTargets = @(
    "apps/web/.next",
    ".venv-api",
    ".pytest_cache",
    ".docker-data",
    ".codex",
    "allposts.json",
    "cats.json",
    "feed.xml",
    "page.html",
    "popup.json",
    "public_top.json",
    "rss.xml"
)

$protectedPaths = @(
    "env",
    "env/runtime.settings.env"
)

if ($DeleteEnv -and -not $AllowEnvDelete) {
    throw "env_delete_blocked: pass -AllowEnvDelete to explicitly delete env"
}

$targets = @($defaultTargets)
if ($DeleteEnv) {
    $targets += @("env")
}

$planned = @()
$deleted = @()
$missing = @()
$protectedSkipped = @()

# Always record env protection in report for auditability.
foreach ($p in $protectedPaths) {
    $abs = Resolve-AbsolutePath -RepoRoot $repoRoot -PathValue $p
    $stat = Get-PathStat -PathValue $abs
    $protectedSkipped += [pscustomobject]@{
        path = $abs
        exists = $stat.exists
        reason = if ($DeleteEnv) { "blocked_without_allow_flag" } else { "protected_default" }
    }
}

foreach ($target in $targets) {
    $abs = Resolve-AbsolutePath -RepoRoot $repoRoot -PathValue $target
    $stat = Get-PathStat -PathValue $abs
    if (-not $stat.exists) {
        $missing += [pscustomobject]@{
            path = $abs
        }
        continue
    }
    $planned += [pscustomobject]@{
        path = $abs
        files = $stat.files
        size_bytes = $stat.size_bytes
        size_gb = $stat.size_gb
    }
    if ($Mode -eq "apply") {
        Remove-Item -LiteralPath $abs -Recurse -Force
        $deleted += [pscustomobject]@{
            path = $abs
        }
    }
}

$report = [pscustomobject]@{
    generated_at = (Get-Date).ToString("s")
    mode = $Mode
    delete_env_requested = [bool]$DeleteEnv
    allow_env_delete = [bool]$AllowEnvDelete
    planned_delete = $planned
    deleted = $deleted
    missing = $missing
    protected_skipped = $protectedSkipped
}

$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportAbs -Encoding UTF8
Write-Host ("Cleanup report -> {0}" -f $reportAbs)
