param(
  [Parameter(Mandatory = $true)]
  [string]$Path
)

if (-not (Test-Path -LiteralPath $Path)) {
  throw "Env file not found: $Path"
}

Get-Content -LiteralPath $Path | ForEach-Object {
  $line = $_.Trim()
  if (-not $line) { return }
  if ($line.StartsWith("#")) { return }

  $parts = $line.Split("=", 2)
  if ($parts.Count -ne 2) { return }

  $name = $parts[0].Trim()
  $value = $parts[1].Trim()
  [Environment]::SetEnvironmentVariable($name, $value, "Process")
}

Write-Host "Loaded env from $Path"
