param(
    [switch]$Apply,
    [int]$GraceDays = 14,
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

New-Item -ItemType Directory -Path "TEST/logs" -Force | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = "TEST/logs/ia-r2-cleanup-$ts.log"
$reportPath = "/app/storage/reports/ia-r2-cleanup-$ts.json"

"[$(Get-Date -Format o)] apply=$($Apply.IsPresent) grace_days=$GraceDays limit=$Limit" | Tee-Object -FilePath $logPath -Append | Out-Null

& docker compose up -d 2>&1 | Tee-Object -FilePath $logPath -Append | Out-Null

$cmd = @(
    "compose", "exec", "-T", "api",
    "python", "/app/scripts/r2_cleanup_legacy_unused.py",
    "--grace-days", "$GraceDays",
    "--report-path", $reportPath
)
if ($Limit -gt 0) {
    $cmd += @("--limit", "$Limit")
}
if ($Apply) {
    $cmd += "--apply"
}

& docker @cmd 2>&1 | Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE

"[$(Get-Date -Format o)] log=$logPath report=$reportPath exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append | Out-Null
exit $exitCode
