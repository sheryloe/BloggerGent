param(
    [switch]$DryRun,
    [switch]$Canary,
    [switch]$Full,
    [ValidateSet("blogger-only", "all")]
    [string]$Source = "blogger-only",
    [int[]]$BlogId = @(),
    [string[]]$BlogSlug = @(),
    [int]$CanaryCount = 4
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$selected = @($DryRun, $Canary, $Full) | Where-Object { $_ }
if ($selected.Count -gt 1) {
    throw "Choose only one mode: -DryRun or -Canary or -Full"
}

$mode = "dry-run"
if ($Canary) { $mode = "canary" }
if ($Full) { $mode = "full" }

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

New-Item -ItemType Directory -Path "TEST/logs" -Force | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = "TEST/logs/ia-r2-live-relayout-$ts.log"
$reportPath = "/app/storage/_common/analysis/ia-r2-live-relayout-$ts.json"

"[$(Get-Date -Format o)] mode=$mode source=$Source canary_count=$CanaryCount blog_ids=$($BlogId -join ',') blog_slugs=$($BlogSlug -join ',')" | Tee-Object -FilePath $logPath -Append | Out-Null

$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& docker compose up -d 2>&1 | Tee-Object -FilePath $logPath -Append | Out-Null
$composeExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
if ($composeExitCode -ne 0) {
    "[$(Get-Date -Format o)] warning=docker compose up failed exit_code=$composeExitCode; continue with current containers" | Tee-Object -FilePath $logPath -Append | Out-Null
}

$cmd = @(
    "compose", "exec", "-T", "api",
    "python", "/app/scripts/r2_live_relayout_webp.py",
    "--source", $Source,
    "--mode", $mode,
    "--canary-count", "$CanaryCount",
    "--report-path", $reportPath
)
foreach ($item in $BlogId) {
    if ($item -gt 0) {
        $cmd += @("--blog-id", "$item")
    }
}
foreach ($item in $BlogSlug) {
    if (-not [string]::IsNullOrWhiteSpace($item)) {
        $cmd += @("--blog-slug", "$item")
    }
}

$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& docker @cmd 2>&1 | Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference

"[$(Get-Date -Format o)] log=$logPath report=$reportPath exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append | Out-Null
exit $exitCode
