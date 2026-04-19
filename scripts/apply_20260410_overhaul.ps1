param(
    [string]$Month = "2026-04",
    [string]$TargetDate = "2026-04-10",
    [switch]$OverwriteMonthPlan,
    [switch]$SyncSheet,
    [switch]$SkipPromptSync,
    [switch]$SkipPostSync,
    [ValidateSet("draft", "published")]
    [string]$CloudflareCanaryStatus = "draft",
    [string]$CloudflareCanaryCategory = "",
    [switch]$SkipCloudflareCanary,
    [switch]$SkipCloudflareRewriteCanary,
    [switch]$CloudflareRewriteApply
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not $env:DATABASE_URL) {
    if ($env:BLOGGENT_DATABASE_URL) {
        $env:DATABASE_URL = $env:BLOGGENT_DATABASE_URL
    } else {
        $env:DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
    }
}

if (-not $env:STORAGE_ROOT) {
    $env:STORAGE_ROOT = "D:\Donggri_Runtime\BloggerGent\storage"
}

Push-Location (Join-Path $RepoRoot "apps/api")
alembic upgrade head
Pop-Location

if (-not $SkipPromptSync) {
    python .\scripts\cloudflare\sync_cloudflare_prompt_files.py --execute
    python .\scripts\sync_channel_prompt_backups.py
}

$pythonArgs = @(
    ".\scripts\apply_20260410_overhaul.py",
    "--month", $Month,
    "--target-date", $TargetDate
)

if ($OverwriteMonthPlan) {
    $pythonArgs += "--overwrite-month-plan"
}
if ($SyncSheet) {
    $pythonArgs += "--sync-sheet"
}
if ($SkipPromptSync) {
    $pythonArgs += "--skip-prompt-sync"
}
if ($SkipPostSync) {
    $pythonArgs += "--skip-post-sync"
}
$pythonArgs += "--cloudflare-canary-status"
$pythonArgs += $CloudflareCanaryStatus
if ($CloudflareCanaryCategory) {
    $pythonArgs += "--cloudflare-canary-category"
    $pythonArgs += $CloudflareCanaryCategory
}
if ($SkipCloudflareCanary) {
    $pythonArgs += "--skip-cloudflare-canary"
}
if ($SkipCloudflareRewriteCanary) {
    $pythonArgs += "--skip-cloudflare-rewrite-canary"
}
if ($CloudflareRewriteApply) {
    $pythonArgs += "--cloudflare-rewrite-apply"
}

python @pythonArgs
