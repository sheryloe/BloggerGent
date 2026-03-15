param(
  [ValidateSet("edge", "chrome")]
  [string]$Browser = "edge",
  [int]$BrowserPort = 9222,
  [int]$BridgePort = 9223,
  [string]$StartUrl = "https://www.blogger.com",
  [string]$ProfileDir = ""
)

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProfileDir) {
  $ProfileDir = Join-Path $repoRoot "storage\\playwright-browser"
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$browserCandidates = switch ($Browser.ToLower()) {
  "chrome" {
    @(
      "$env:ProgramFiles\\Google\\Chrome\\Application\\chrome.exe",
      "${env:ProgramFiles(x86)}\\Google\\Chrome\\Application\\chrome.exe"
    )
  }
  default {
    @(
      "$env:ProgramFiles\\Microsoft\\Edge\\Application\\msedge.exe",
      "${env:ProgramFiles(x86)}\\Microsoft\\Edge\\Application\\msedge.exe"
    )
  }
}

$browserPath = $browserCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browserPath) {
  throw "Could not find $Browser. Install it or pass a different browser option."
}

$arguments = @(
  "--remote-debugging-port=$BrowserPort"
  "--remote-debugging-address=0.0.0.0"
  "--user-data-dir=$ProfileDir"
  $StartUrl
)

Start-Process -FilePath $browserPath -ArgumentList $arguments | Out-Null

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  throw "Python is required to start the CDP bridge."
}

$bridgeScript = Join-Path $PSScriptRoot "browser_cdp_bridge.py"
$bridgeCommand = "`"$($python.Source)`" `"$bridgeScript`" --listen-port $BridgePort --target-port $BrowserPort"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $bridgeCommand | Out-Null

Write-Host ""
Write-Host "Started $Browser with remote debugging."
Write-Host "Profile dir : $ProfileDir"
Write-Host "Browser CDP : http://127.0.0.1:$BrowserPort"
Write-Host "Bridge CDP  : http://host.docker.internal:$BridgePort"
Write-Host "Next step   : sign into Blogger once in that browser window."
