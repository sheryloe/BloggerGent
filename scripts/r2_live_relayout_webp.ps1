param(
    [switch]$DryRun,
    [switch]$Canary,
    [switch]$Full,
    [int]$CanaryCount = 4
)

$ErrorActionPreference = "Stop"

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
$reportPath = "/app/storage/reports/ia-r2-live-relayout-$ts.json"

"[$(Get-Date -Format o)] mode=$mode canary_count=$CanaryCount" | Tee-Object -FilePath $logPath -Append | Out-Null

& docker compose up -d 2>&1 | Tee-Object -FilePath $logPath -Append | Out-Null

$cmd = @(
    "compose", "exec", "-T", "api",
    "python", "/app/scripts/r2_live_relayout_webp.py",
    "--mode", $mode,
    "--canary-count", "$CanaryCount",
    "--report-path", $reportPath
)

& docker @cmd 2>&1 | Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE

"[$(Get-Date -Format o)] log=$logPath report=$reportPath exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append | Out-Null
exit $exitCode
