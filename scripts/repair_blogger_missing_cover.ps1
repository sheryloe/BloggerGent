param(
    [ValidateSet("dry-run", "apply")]
    [string]$Mode = "dry-run",
    [int[]]$BlogId = @(),
    [string[]]$Url = @(),
    [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

New-Item -ItemType Directory -Path "TEST/logs" -Force | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = "TEST/logs/repair-blogger-missing-cover-$ts.log"

if (-not $ReportPath) {
    $ReportPath = "/app/storage/_common/analysis/repair-blogger-missing-cover-$ts.json"
}

"[$(Get-Date -Format o)] mode=$Mode report_path=$ReportPath" | Tee-Object -FilePath $logPath -Append | Out-Null

$composeOutput = cmd /c "docker compose up -d 2>&1"
$composeOutput | Tee-Object -FilePath $logPath -Append | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed with exit code $LASTEXITCODE"
}

$cmd = @(
    "compose", "exec", "-T", "api",
    "python", "/app/scripts/repair_blogger_missing_cover.py",
    "--mode", $Mode,
    "--report-path", $ReportPath
)

foreach ($id in $BlogId) {
    $cmd += @("--blog-id", "$id")
}
foreach ($item in $Url) {
    if ($item) {
        $cmd += @("--url", $item)
    }
}

& docker @cmd 2>&1 | Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE

"[$(Get-Date -Format o)] log=$logPath report=$ReportPath exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append | Out-Null
exit $exitCode
