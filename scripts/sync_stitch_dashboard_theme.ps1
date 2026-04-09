$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envFilePath = Join-Path $repoRoot ".env"
$outputPath = Join-Path $repoRoot "apps\web\app\theme.stitch.dark.json"

$spaceName = "bloggergent-design-system"
$memoryName = "dashboard_dark_theme_tokens"
$defaultBaseUrl = "https://api-demo.stitch-ai.co"

$defaultTokens = [ordered]@{
  background = "#070B14"
  backgroundElevated = "rgba(15, 23, 42, 0.78)"
  foreground = "#E5ECF7"
  foregroundMuted = "#94A3B8"
  border = "rgba(148, 163, 184, 0.25)"
  shadowSoft = "0 24px 64px rgba(2, 6, 23, 0.55)"
  accentPrimary = "#F97316"
  accentSecondary = "#2563EB"
  accentSuccess = "#10B981"
}

function Get-DotEnvValue {
  param(
    [string]$Path,
    [string]$Key
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }

  $regex = "^\s*" + [regex]::Escape($Key) + "\s*=\s*(.+)\s*$"
  $line = Get-Content -LiteralPath $Path | Where-Object { $_ -match $regex } | Select-Object -Last 1
  if (-not $line) {
    return $null
  }

  $value = ($line -replace "^\s*" + [regex]::Escape($Key) + "\s*=\s*", "").Trim()
  if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
    $value = $value.Substring(1, $value.Length - 2)
  }
  return $value
}

function Pick-Value {
  param(
    [string]$Primary,
    [string]$Fallback
  )

  if ($Primary -and $Primary.Trim().Length -gt 0) {
    return $Primary.Trim()
  }
  return $Fallback
}

function Read-ExistingTokens {
  param(
    [string]$Path
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }

  try {
    $raw = Get-Content -LiteralPath $Path -Raw
    $json = $raw | ConvertFrom-Json
    if ($json.tokens) {
      return $json.tokens
    }
  } catch {
    Write-Warning "Existing theme file parse failed: $($_.Exception.Message)"
  }

  return $null
}

function Parse-TokensFromMemoryContent {
  param(
    [string]$RawContent
  )

  if (-not $RawContent) {
    return $null
  }

  $candidate = $RawContent.Trim()
  if ($candidate.StartsWith('```')) {
    $candidate = [regex]::Replace($candidate, '^\s*```(?:json)?\s*', '')
    $candidate = [regex]::Replace($candidate, '\s*```\s*$', '')
  }

  try {
    $json = $candidate | ConvertFrom-Json
    if ($json.tokens) {
      return $json.tokens
    }
    return $json
  } catch {
    return $null
  }
}

function To-TokenObject {
  param(
    [object]$SourceTokens
  )

  if (-not $SourceTokens) {
    $SourceTokens = $defaultTokens
  }

  $tokenObject = [ordered]@{
    background = Pick-Value -Primary $SourceTokens.background -Fallback $defaultTokens.background
    backgroundElevated = Pick-Value -Primary $SourceTokens.backgroundElevated -Fallback $defaultTokens.backgroundElevated
    foreground = Pick-Value -Primary $SourceTokens.foreground -Fallback $defaultTokens.foreground
    foregroundMuted = Pick-Value -Primary $SourceTokens.foregroundMuted -Fallback $defaultTokens.foregroundMuted
    border = Pick-Value -Primary $SourceTokens.border -Fallback $defaultTokens.border
    shadowSoft = Pick-Value -Primary $SourceTokens.shadowSoft -Fallback $defaultTokens.shadowSoft
    accentPrimary = Pick-Value -Primary $SourceTokens.accentPrimary -Fallback $defaultTokens.accentPrimary
    accentSecondary = Pick-Value -Primary $SourceTokens.accentSecondary -Fallback $defaultTokens.accentSecondary
    accentSuccess = Pick-Value -Primary $SourceTokens.accentSuccess -Fallback $defaultTokens.accentSuccess
  }

  return $tokenObject
}

function Write-ThemeFile {
  param(
    [string]$Path,
    [string]$Space,
    [string]$Memory,
    [object]$Tokens
  )

  $payload = [ordered]@{
    meta = [ordered]@{
      source = "stitch"
      space = $Space
      memoryName = $Memory
      updatedAt = (Get-Date).ToUniversalTime().ToString("o")
      version = 1
    }
    tokens = $Tokens
  }

  $json = $payload | ConvertTo-Json -Depth 8
  Set-Content -LiteralPath $Path -Value $json -Encoding UTF8
}

$stitchApiKey = if ($env:STITCH_API_KEY) { $env:STITCH_API_KEY } else { Get-DotEnvValue -Path $envFilePath -Key "STITCH_API_KEY" }
$stitchBaseUrl = if ($env:STITCH_BASE_URL) { $env:STITCH_BASE_URL } else { Get-DotEnvValue -Path $envFilePath -Key "STITCH_BASE_URL" }

if (-not $stitchApiKey) {
  throw "STITCH_API_KEY is required. Set it in environment or .env."
}

if (-not $stitchBaseUrl) {
  $stitchBaseUrl = $defaultBaseUrl
}

$stitchBaseUrl = $stitchBaseUrl.TrimEnd("/")

$existingTokens = Read-ExistingTokens -Path $outputPath
$resolvedTokens = To-TokenObject -SourceTokens $existingTokens

try {
  $user = Invoke-RestMethod -Method Get -Uri "$stitchBaseUrl/user/api-key/user?apiKey=$stitchApiKey"
  $userId = $user.userId
  if (-not $userId) {
    throw "Unable to resolve Stitch userId."
  }

  $spaces = Invoke-RestMethod -Method Get -Uri "$stitchBaseUrl/user/memory-space?userId=$userId"
  $targetSpace = @($spaces) | Where-Object { $_.name -eq $spaceName } | Select-Object -First 1

  if (-not $targetSpace) {
    Invoke-RestMethod -Method Post -Uri "$stitchBaseUrl/memory-space/create?apiKey=$stitchApiKey&userId=$userId" -ContentType "application/json" -Body (@{
        repository = $spaceName
        type = "AGENT_MEMORY"
      } | ConvertTo-Json) | Out-Null
    Write-Host "Created Stitch space: $spaceName"
  }

  $memoryQuery = @(
    "apiKey=$([uri]::EscapeDataString($stitchApiKey))"
    "userId=$([uri]::EscapeDataString([string]$userId))"
    "memoryNames=$([uri]::EscapeDataString($memoryName))"
    "limit=1"
    "offset=0"
  ) -join "&"
  $memoryUri = "$stitchBaseUrl/user/memory/all?$memoryQuery"

  $memoryList = Invoke-RestMethod -Method Get -Uri $memoryUri
  $firstMemory = @($memoryList) | Select-Object -First 1

  if ($firstMemory -and $firstMemory.episodicMemory -and $firstMemory.episodicMemory.content) {
    $parsed = Parse-TokensFromMemoryContent -RawContent $firstMemory.episodicMemory.content
    if ($parsed) {
      $resolvedTokens = To-TokenObject -SourceTokens $parsed
      Write-Host "Loaded tokens from Stitch memory: $memoryName"
    } else {
      Write-Warning "Stitch memory parse failed. Using local/default tokens."
    }
  } else {
    $bootstrapPayload = [ordered]@{
      tokens = $defaultTokens
    } | ConvertTo-Json -Depth 6

    Invoke-RestMethod -Method Post -Uri "$stitchBaseUrl/memory/$spaceName/create?apiKey=$stitchApiKey&userId=$userId" -ContentType "application/json" -Body (@{
        files = @(
          @{
            filePath = "episodic.data"
            content = $bootstrapPayload
          }
        )
        message = $memoryName
      } | ConvertTo-Json -Depth 8) | Out-Null

    $resolvedTokens = To-TokenObject -SourceTokens $defaultTokens
    Write-Host "No memory found. Bootstrapped default memory: $memoryName"
  }
} catch {
  Write-Warning "Stitch sync failed: $($_.Exception.Message)"
  Write-Warning "Updating theme file with local/default tokens."
}

Write-ThemeFile -Path $outputPath -Space $spaceName -Memory $memoryName -Tokens $resolvedTokens
Write-Host "Theme token file updated: $outputPath"
