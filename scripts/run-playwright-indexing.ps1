param(
  [string]$ApiBaseUrl = "http://localhost:7002",
  [int]$Count = 12,
  [switch]$Force,
  [switch]$RunLive,
  [int]$TestLimit = 100,
  [ValidateSet("blogger+cloudflare", "blogger", "cloudflare")]
  [string]$TargetScope = "blogger+cloudflare"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot "TEST\\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "playwright-indexing-$timestamp.log"

$payload = @{
  count = $Count
  force = [bool]$Force
  run_test = -not [bool]$RunLive
  test_limit = $TestLimit
  target_scope = $TargetScope
}

try {
  $result = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBaseUrl/api/v1/google/indexing/request-playwright" `
    -ContentType "application/json" `
    -Body ($payload | ConvertTo-Json -Depth 10)
}
catch {
  $errorPayload = @{
    status = "failed"
    message = $_.Exception.Message
    payload = $payload
    api = $ApiBaseUrl
    at = (Get-Date).ToString("o")
  }
  ($errorPayload | ConvertTo-Json -Depth 10) | Out-File -FilePath $logPath -Encoding utf8
  throw
}

($result | ConvertTo-Json -Depth 20) | Tee-Object -FilePath $logPath
Write-Host ""
Write-Host "Saved log: $logPath"
