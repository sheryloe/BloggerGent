param(
    [ValidateSet("dry-run", "canary", "full")]
    [string]$Mode = "dry-run",
    [ValidateSet("none-only")]
    [string]$Scope = "none-only",
    [ValidateSet("strict")]
    [string]$MatchPolicy = "strict",
    [int]$GenerateSlots = 2,
    [string]$Model = "gpt-image-1",
    [int]$CanaryCount = 10
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

New-Item -ItemType Directory -Path "TEST/logs" -Force | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = "TEST/logs/restore-missing-live-images-$ts.log"
$reportPath = "/app/storage/reports/restore-missing-live-images-$ts.json"

"[$(Get-Date -Format o)] mode=$Mode scope=$Scope match_policy=$MatchPolicy generate_slots=$GenerateSlots model=$Model canary_count=$CanaryCount" | Tee-Object -FilePath $logPath -Append | Out-Null

$composeOutput = cmd /c "docker compose up -d 2>&1"
$composeOutput | Tee-Object -FilePath $logPath -Append | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed with exit code $LASTEXITCODE"
}

$cmd = @(
    "compose", "exec", "-T", "api",
    "python", "/app/scripts/restore_missing_live_images.py",
    "--mode", $Mode,
    "--scope", $Scope,
    "--match-policy", $MatchPolicy,
    "--generate-slots", "$GenerateSlots",
    "--model", $Model,
    "--canary-count", "$CanaryCount",
    "--report-path", $reportPath
)

& docker @cmd 2>&1 | Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE

"[$(Get-Date -Format o)] log=$logPath report=$reportPath exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append | Out-Null
exit $exitCode
