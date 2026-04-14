param(
    [string]$RepoRoot = "",
    [string]$OutputDir = "docs/reports",
    [string]$JsonPath = "",
    [string]$TreePath = "",
    [string]$HtmlPath = ""
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$scriptDir = Split-Path -Parent $PSCommandPath
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $resolvedRepoRoot = Resolve-Path (Join-Path $scriptDir "..")
} else {
    $resolvedRepoRoot = Resolve-Path $RepoRoot
}

Set-Location $resolvedRepoRoot
New-Item -ItemType Directory -Path "TEST/logs" -Force | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = "TEST/logs/ia-source-usage-analysis-$ts.log"

"[$(Get-Date -Format o)] repo_root=$resolvedRepoRoot output_dir=$OutputDir" | Tee-Object -FilePath $logPath -Append | Out-Null

$scriptPyPath = Join-Path $resolvedRepoRoot "scripts/analyze_source_usage.py"

$cmd = @(
    "$scriptPyPath",
    "--repo-root", "$resolvedRepoRoot",
    "--output-dir", "$OutputDir"
)

if (-not [string]::IsNullOrWhiteSpace($JsonPath)) {
    $cmd += @("--json-path", "$JsonPath")
}
if (-not [string]::IsNullOrWhiteSpace($TreePath)) {
    $cmd += @("--tree-path", "$TreePath")
}
if (-not [string]::IsNullOrWhiteSpace($HtmlPath)) {
    $cmd += @("--html-path", "$HtmlPath")
}

$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& python @cmd 2>&1 | Tee-Object -FilePath $logPath -Append
$exitCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference

"[$(Get-Date -Format o)] log=$logPath exit_code=$exitCode" | Tee-Object -FilePath $logPath -Append | Out-Null
exit $exitCode
