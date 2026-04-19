param(
    [ValidateSet("blogger", "cloudflare", "all")]
    [string]$Source = "all",
    [int[]]$BlogId = @(),
    [string[]]$BlogSlug = @(),
    [int]$Timeout = 30
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

New-Item -ItemType Directory -Path "TEST/logs" -Force | Out-Null
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = "TEST/logs/ia-verify-blogger-r2-layout-$ts.log"
$reportPath = "/app/storage/_common/analysis/ia-verify-blogger-r2-layout-$ts.json"

"[$(Get-Date -Format o)] source=$Source timeout=$Timeout blog_ids=$($BlogId -join ',') blog_slugs=$($BlogSlug -join ',')" | Tee-Object -FilePath $logPath -Append | Out-Null

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
    "python", "/app/scripts/verify_blogger_r2_layout.py",
    "--source", $Source,
    "--timeout", "$Timeout",
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
