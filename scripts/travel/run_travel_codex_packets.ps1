param(
  [Parameter(Mandatory = $true)]
  [string]$PacketDir,

  [string]$ResponseDir = "",

  [int]$Limit = 0,

  [string]$Model = "gpt-5.4-mini"
)

$ErrorActionPreference = "Stop"
$repoRoot = "D:\Donggri_Platform\BloggerGent"
$packetPath = Resolve-Path -LiteralPath $PacketDir
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not $ResponseDir) {
  $ResponseDir = Join-Path (Split-Path -Parent $packetPath) "responses"
}
New-Item -ItemType Directory -Force -Path $ResponseDir | Out-Null

$packets = Get-ChildItem -LiteralPath $packetPath -Filter *.json | Sort-Object Name
if ($Limit -gt 0) {
  $packets = $packets | Select-Object -First $Limit
}

$summary = @()
foreach ($packetFile in $packets) {
  $packet = Get-Content -LiteralPath $packetFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
  $requestId = [string]$packet.request_id
  $schemaPath = Join-Path $ResponseDir "$requestId.schema.json"
  $rawPath = Join-Path $ResponseDir "$requestId.raw.json"
  $responsePath = Join-Path $ResponseDir "$requestId.json"

  [System.IO.File]::WriteAllText($schemaPath, ($packet.response_schema | ConvertTo-Json -Depth 40), $utf8NoBom)

  Write-Host "RUN $requestId"
  $packet.prompt | codex exec `
    --cd $repoRoot `
    --sandbox read-only `
    --model $Model `
    --output-schema $schemaPath `
    --output-last-message $rawPath `
    - | Out-Host

  if (-not (Test-Path -LiteralPath $rawPath)) {
    throw "Codex did not write output: $rawPath"
  }

  $rawContent = Get-Content -LiteralPath $rawPath -Raw -Encoding UTF8
  $wrapper = [ordered]@{
    request_id = $requestId
    content = $rawContent
    packet_path = $packetFile.FullName
    model = $Model
    created_at = (Get-Date).ToString("o")
  }
  [System.IO.File]::WriteAllText($responsePath, ($wrapper | ConvertTo-Json -Depth 20), $utf8NoBom)
  $summary += [ordered]@{
    request_id = $requestId
    response_path = $responsePath
    packet_path = $packetFile.FullName
  }
}

$summaryPath = Join-Path $ResponseDir "codex-run-summary.json"
[System.IO.File]::WriteAllText($summaryPath, ($summary | ConvertTo-Json -Depth 20), $utf8NoBom)
Write-Host "DONE $($summary.Count) responses -> $ResponseDir"
