param(
    [ValidateSet("dry-run", "canary", "full")]
    [string]$Mode = "dry-run",
    [int]$CanaryCount = 10
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

New-Item -ItemType Directory -Path "TEST/logs" -Force | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = "TEST/logs/fix-broken-live-asset-urls-$ts.log"
$reportPath = "/app/storage/_common/analysis/fix-broken-live-asset-urls-$ts.json"

"[$(Get-Date -Format o)] mode=$Mode canary_count=$CanaryCount" | Tee-Object -FilePath $logPath -Append | Out-Null

$composeOutput = cmd /c "docker compose up -d 2>&1"
$composeOutput | Tee-Object -FilePath $logPath -Append | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed with exit code $LASTEXITCODE"
}

$cmd = @(
    "compose", "exec", "-T", "api",
    "python", "/app/scripts/fix_broken_live_asset_urls.py",
    "--mode", $Mode,
    "--canary-count", "$CanaryCount",
    "--report-path", $reportPath
)

& docker @cmd 2>&1 | Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE

"[$(Get-Date -Format o)] log=$logPath report=$reportPath exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append | Out-Null
exit $exitCode
