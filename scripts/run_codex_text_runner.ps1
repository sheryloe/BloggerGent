param(
  [string]$StorageRoot = (Join-Path $PSScriptRoot "..\\storage"),
  [int]$PollSeconds = 1,
  [switch]$Once,
  [int]$WorkerCount = 1,
  [switch]$ChildWorker
)

$ErrorActionPreference = "Stop"

function Ensure-Directory {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
  }
}

function Write-JsonFile {
  param(
    [string]$Path,
    [hashtable]$Payload
  )
  $tempPath = "$Path.tmp"
  $json = $Payload | ConvertTo-Json -Depth 20
  Write-Utf8NoBomFile -Path $tempPath -Value $json
  Move-Item -LiteralPath $tempPath -Destination $Path -Force
}

function Write-Utf8NoBomFile {
  param(
    [string]$Path,
    [string]$Value
  )
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, [string]$Value, $utf8NoBom)
}

function Restore-OrphanedRequests {
  param(
    [string]$ProcessingDir,
    [string]$RequestsDir,
    [int]$StaleSeconds = 30
  )

  $cutoff = (Get-Date).AddSeconds(-1 * [Math]::Max($StaleSeconds, 1))
  $orphaned = Get-ChildItem -LiteralPath $ProcessingDir -Filter "*.json" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff }

  foreach ($item in $orphaned) {
    $destination = Join-Path $RequestsDir $item.Name
    Move-Item -LiteralPath $item.FullName -Destination $destination -Force
  }
}

function Invoke-CodexQueueItem {
  param(
    [string]$RequestPath,
    [string]$ProcessingDir,
    [string]$ResponsesDir,
    [string]$FailedDir
  )

  $requestFileName = [System.IO.Path]::GetFileName($RequestPath)
  $processingPath = Join-Path $ProcessingDir $requestFileName
  Move-Item -LiteralPath $RequestPath -Destination $processingPath -Force

  $request = Get-Content -LiteralPath $processingPath -Raw -Encoding utf8 | ConvertFrom-Json
  $requestId = [string]$request.request_id
  $stageName = [string]$request.stage_name
  $model = [string]$request.model
  $workspaceDir = [string]$request.workspace_dir
  $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
  if ([string]::IsNullOrWhiteSpace($workspaceDir) -or -not (Test-Path -LiteralPath $workspaceDir)) {
    $workspaceDir = $repoRoot
  }
  $prompt = [string]$request.prompt
  $responseKind = [string]$request.response_kind

  $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "bloggent-codex-runner"
  Ensure-Directory -Path $tempRoot
  $promptPath = Join-Path $tempRoot "$requestId.prompt.txt"
  $outputPath = Join-Path $tempRoot "$requestId.output.txt"
  $logPath = Join-Path $tempRoot "$requestId.log.txt"
  $schemaPath = $null

  Write-Utf8NoBomFile -Path $promptPath -Value $prompt
  if ($responseKind -eq "json_schema" -and $null -ne $request.response_schema) {
    $schemaPath = Join-Path $tempRoot "$requestId.schema.json"
    Write-Utf8NoBomFile -Path $schemaPath -Value ($request.response_schema | ConvertTo-Json -Depth 50)
  }

  $args = @(
    "exec",
    "-m",
    $model,
    "-C",
    $workspaceDir,
    "-s",
    "read-only",
    "--disable",
    "plugins",
    "--skip-git-repo-check",
    "--ephemeral",
    "-o",
    $outputPath,
    "-"
  )
  if ($schemaPath) {
    $args += @("--output-schema", $schemaPath)
  }

  $codexCommand = (Get-Command "codex.cmd" -ErrorAction SilentlyContinue).Source
  if (-not $codexCommand) {
    $codexCommand = (Get-Command "codex" -ErrorAction Stop).Source
  }

  try {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $runnerPayloadPath = Join-Path $tempRoot "$requestId.runner.json"
    try {
      $promptText = Get-Content -LiteralPath $promptPath -Raw -Encoding utf8
      Write-JsonFile -Path $runnerPayloadPath -Payload @{
        codex_command = $codexCommand
        args = $args
        workspace_dir = $workspaceDir
        prompt_path = $promptPath
        log_path = $logPath
      }
      $runnerResult = @'
import json
import subprocess
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
prompt = Path(payload["prompt_path"]).read_text(encoding="utf-8")
proc = subprocess.run(
    ["cmd.exe", "/d", "/c", payload["codex_command"], *payload["args"]],
    input=prompt,
    text=True,
    capture_output=True,
    encoding="utf-8",
    errors="replace",
    cwd=payload["workspace_dir"],
)
log_text = "\n".join(part.strip() for part in (proc.stderr, proc.stdout) if part and part.strip())
Path(payload["log_path"]).write_text(log_text, encoding="utf-8")
print(json.dumps({"returncode": proc.returncode}))
'@ | python - $runnerPayloadPath
      $runnerPayload = ($runnerResult | Select-Object -Last 1 | ConvertFrom-Json)
      $global:LASTEXITCODE = [int]($runnerPayload.returncode)
    }
    finally {
      $ErrorActionPreference = $previousErrorActionPreference
      Remove-Item -LiteralPath $runnerPayloadPath -ErrorAction SilentlyContinue
    }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
      throw "codex exited with code $exitCode"
    }
    $content = ""
    if (Test-Path -LiteralPath $outputPath) {
      $content = Get-Content -LiteralPath $outputPath -Raw -Encoding utf8
    }
    Write-JsonFile -Path (Join-Path $ResponsesDir "$requestId.json") -Payload @{
      status = "completed"
      request_id = $requestId
      stage_name = $stageName
      provider_name = "codex-cli"
      provider_model = $model
      runtime_kind = "codex_cli"
      content = $content
      log_path = $logPath
    }
  }
  catch {
    $errorMessage = $_.Exception.Message
    $logTail = ""
    if (Test-Path -LiteralPath $logPath) {
      $logTail = (Get-Content -LiteralPath $logPath -Tail 50 -Encoding utf8) -join "`n"
    }
    Write-JsonFile -Path (Join-Path $FailedDir "$requestId.json") -Payload @{
      status = "failed"
      request_id = $requestId
      stage_name = $stageName
      provider_name = "codex-cli"
      provider_model = $model
      runtime_kind = "codex_cli"
      error = $errorMessage
      log_excerpt = $logTail
    }
  }
  finally {
    Remove-Item -LiteralPath $processingPath -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $promptPath -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $outputPath -ErrorAction SilentlyContinue
    if ($schemaPath) {
      Remove-Item -LiteralPath $schemaPath -ErrorAction SilentlyContinue
    }
  }
}

$queueRoot = [System.IO.Path]::GetFullPath($StorageRoot)
Ensure-Directory -Path $queueRoot
$requestsDir = Join-Path $queueRoot "codex-queue\\requests"
$processingDir = Join-Path $queueRoot "codex-queue\\processing"
$responsesDir = Join-Path $queueRoot "codex-queue\\responses"
$failedDir = Join-Path $queueRoot "codex-queue\\failed"

Ensure-Directory -Path $requestsDir
Ensure-Directory -Path $processingDir
Ensure-Directory -Path $responsesDir
Ensure-Directory -Path $failedDir

if (-not $ChildWorker -and $WorkerCount -gt 1) {
  $workerTotal = [Math]::Max($WorkerCount, 1)
  $powershellPath = (Get-Command "powershell.exe" -ErrorAction SilentlyContinue).Source
  if (-not $powershellPath) {
    $powershellPath = (Get-Process -Id $PID).Path
  }

  $childProcesses = @()
  try {
    for ($index = 1; $index -le $workerTotal; $index++) {
      $argumentList = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $PSCommandPath,
        "-StorageRoot",
        $queueRoot,
        "-PollSeconds",
        [string]$PollSeconds,
        "-ChildWorker"
      )
      if ($Once) {
        $argumentList += "-Once"
      }
      $childProcesses += Start-Process -FilePath $powershellPath -ArgumentList $argumentList -PassThru
    }
    Wait-Process -Id ($childProcesses | Select-Object -ExpandProperty Id)
  }
  finally {
    foreach ($process in $childProcesses) {
      if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
      }
    }
  }
  return
}

$pythonRunnerPath = Join-Path $PSScriptRoot "run_codex_text_runner.py"
$pythonArgs = @($pythonRunnerPath, "--storage-root", $queueRoot, "--poll-seconds", [string]$PollSeconds)
if ($Once) {
  $pythonArgs += "--once"
}
& python @pythonArgs
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
return

while ($true) {
  Restore-OrphanedRequests -ProcessingDir $processingDir -RequestsDir $requestsDir
  $request = Get-ChildItem -LiteralPath $requestsDir -Filter "*.json" -File | Sort-Object LastWriteTime | Select-Object -First 1
  if ($null -eq $request) {
    if ($Once) {
      break
    }
    Start-Sleep -Seconds $PollSeconds
    continue
  }

  Invoke-CodexQueueItem -RequestPath $request.FullName -ProcessingDir $processingDir -ResponsesDir $responsesDir -FailedDir $failedDir

  if ($Once) {
    break
  }
}
