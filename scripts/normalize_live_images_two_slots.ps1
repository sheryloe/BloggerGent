param(
    [ValidateSet("audit", "canary", "full")]
    [string]$Mode = "audit",
    [ValidateSet("all", "blogger", "cloudflare")]
    [string]$Source = "all",
    [string]$Model = "gpt-image-1",
    [int]$CanaryCount = 15,
    [double]$Timeout = 20.0
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

New-Item -ItemType Directory -Path "TEST/logs" -Force | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = "TEST/logs/normalize-live-images-two-slots-$ts.log"
$reportPath = "/app/storage/reports/normalize-live-images-two-slots-$ts.json"

"[$(Get-Date -Format o)] mode=$Mode source=$Source model=$Model canary_count=$CanaryCount timeout=$Timeout" | Tee-Object -FilePath $logPath -Append | Out-Null

$composeOutput = cmd /c "docker compose up -d 2>&1"
$composeOutput | Tee-Object -FilePath $logPath -Append | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed with exit code $LASTEXITCODE"
}

$cmd = @(
    "compose", "exec", "-T", "api",
    "python", "/app/scripts/normalize_live_images_two_slots.py",
    "--mode", $Mode,
    "--source", $Source,
    "--model", $Model,
    "--canary-count", "$CanaryCount",
    "--timeout", "$Timeout",
    "--report-path", $reportPath
)

& docker @cmd 2>&1 | Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE

"[$(Get-Date -Format o)] log=$logPath report=$reportPath exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append | Out-Null
exit $exitCode
