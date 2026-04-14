param(
  [string]$Month = "2026-04",
  [double]$Threshold = 80,
  [int]$ParallelWorkers = 2,
  [int]$RunnerWorkers = 2,
  [switch]$SkipCloudflare,
  [switch]$SkipBlogger,
  [switch]$SkipAnalyticsBackfill,
  [switch]$SkipTelegram
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$apiBase = "http://localhost:7002/api/v1"
$outputDir = Join-Path $repoRoot "output"
if (-not (Test-Path -LiteralPath $outputDir)) {
  New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

function Invoke-JsonRequest {
  param(
    [ValidateSet("GET", "POST", "PUT")]
    [string]$Method,
    [Parameter(Mandatory = $true)]
    [string]$Uri,
    [object]$Body = $null,
    [int]$TimeoutSec = 7200
  )

  if ($null -eq $Body) {
    return Invoke-RestMethod -Method $Method -Uri $Uri -TimeoutSec $TimeoutSec
  }

  $json = $Body | ConvertTo-Json -Depth 20
  return Invoke-RestMethod -Method $Method -Uri $Uri -ContentType "application/json; charset=utf-8" -Body $json -TimeoutSec $TimeoutSec
}

function Get-CloudflareDryRun {
  return Invoke-JsonRequest -Method POST -Uri "$apiBase/cloudflare/refactor-low-score" -Body @{
    execute = $false
    threshold = $Threshold
    month = $Month
    limit = 500
    sync_before = $false
    parallel_workers = 1
  }
}

function Get-BloggerDryRun {
  param([int]$BlogId)
  return Invoke-JsonRequest -Method POST -Uri "$apiBase/google/blogs/$BlogId/refactor-low-score" -Body @{
    execute = $false
    threshold = $Threshold
    month = $Month
    limit = 500
    sync_before = $false
    run_lighthouse = $false
    parallel_workers = 1
  }
}

function Invoke-CloudflareBatch {
  return Invoke-JsonRequest -Method POST -Uri "$apiBase/cloudflare/refactor-low-score" -Body @{
    execute = $true
    threshold = $Threshold
    month = $Month
    limit = 500
    sync_before = $true
    parallel_workers = $ParallelWorkers
  }
}

function Invoke-BloggerBatch {
  param([int]$BlogId)
  return Invoke-JsonRequest -Method POST -Uri "$apiBase/google/blogs/$BlogId/refactor-low-score" -Body @{
    execute = $true
    threshold = $Threshold
    month = $Month
    limit = 500
    sync_before = $true
    run_lighthouse = $false
    parallel_workers = $ParallelWorkers
  }
}

function New-TelegramSummaryMessage {
  param(
    [hashtable]$CloudflareSummary,
    [System.Collections.ArrayList]$BloggerRuns
  )

  $lines = [System.Collections.Generic.List[string]]::new()
  $null = $lines.Add("[Bloggent] low-score refactor batch completed")
  $null = $lines.Add("month=$Month threshold=$Threshold")
  if ($CloudflareSummary.ContainsKey("status")) {
    $null = $lines.Add(("cloudflare: status={0} updated={1} failed={2}" -f $CloudflareSummary.status, $CloudflareSummary.updated_count, $CloudflareSummary.failed_count))
  }
  foreach ($item in $BloggerRuns) {
    $null = $lines.Add(("blogger[{0}:{1}]: status={2} updated={3} failed={4}" -f $item.blog_id, $item.blog_name, $item.status, $item.updated_count, $item.failed_count))
  }
  return ($lines -join "`n")
}

function Get-ArrayValue {
  param([object]$Value)

  if ($null -eq $Value) {
    return @()
  }
  if ($Value -is [System.Array]) {
    return @($Value)
  }
  if ($Value.PSObject.Properties.Name -contains "value") {
    return @($Value.value)
  }
  return @($Value)
}

function Get-IntValue {
  param([object]$Value)

  $text = [string]($Value | Select-Object -First 1)
  if ([string]::IsNullOrWhiteSpace($text)) {
    return 0
  }
  return [int]$text
}

$runnerProcesses = New-Object System.Collections.ArrayList
$results = [ordered]@{
  started_at = (Get-Date).ToString("o")
  month = $Month
  threshold = $Threshold
  parallel_workers = $ParallelWorkers
  runner_workers = $RunnerWorkers
  cloudflare_dry_run = $null
  blogger_dry_runs = @()
  cloudflare_run = $null
  blogger_runs = @()
  cloudflare_summary_after = $null
  blogger_summary_after = $null
  analytics_backfill = $null
  telegram = $null
}

try {
  $pythonExe = "python"
  $storageRoot = (Join-Path $repoRoot "storage")
  for ($index = 1; $index -le [Math]::Max($RunnerWorkers, 1); $index++) {
    $runnerArgs = @(
      (Join-Path $repoRoot "scripts/run_codex_text_runner.py"),
      "--storage-root", $storageRoot,
      "--poll-seconds", "1"
    )
    $runnerProcess = Start-Process -FilePath $pythonExe -ArgumentList $runnerArgs -PassThru
    $null = $runnerProcesses.Add($runnerProcess)
  }
  Start-Sleep -Seconds 2

  $blogs = @(Get-ArrayValue (Invoke-JsonRequest -Method GET -Uri "$apiBase/blogs"))
  $targetBlogs = @(
    $blogs |
      Where-Object {
        $_.blogger_blog_id -and
        $_.is_active -eq $true -and
        (Get-IntValue $_.published_posts) -gt 0
      } |
      Sort-Object id
  )

  if (-not $SkipCloudflare) {
    $results.cloudflare_dry_run = Get-CloudflareDryRun
    $results.cloudflare_run = Invoke-CloudflareBatch
  }

  if (-not $SkipBlogger) {
    $bloggerDryRuns = New-Object System.Collections.ArrayList
    $bloggerRuns = New-Object System.Collections.ArrayList
    foreach ($blog in $targetBlogs) {
      $dryRun = Get-BloggerDryRun -BlogId ([int]$blog.id)
      $null = $bloggerDryRuns.Add([ordered]@{
        blog_id = [int]$blog.id
        blog_name = [string]$blog.name
        result = $dryRun
      })
      if ((Get-IntValue $dryRun.total_candidates) -gt 0) {
        $run = Invoke-BloggerBatch -BlogId ([int]$blog.id)
      }
      else {
        $run = [ordered]@{
          status = "skipped"
          blog_id = [int]$blog.id
          blog_name = [string]$blog.name
          total_candidates = 0
          updated_count = 0
          failed_count = 0
          skipped_count = 0
          processed_count = 0
          items = @()
        }
      }
      $null = $bloggerRuns.Add($run)
    }
    $results.blogger_dry_runs = @($bloggerDryRuns)
    $results.blogger_runs = @($bloggerRuns)
  }

  if (-not ($SkipCloudflare -and $SkipBlogger)) {
    $null = Invoke-JsonRequest -Method POST -Uri "$apiBase/cloudflare/posts/refresh"
    $null = Invoke-JsonRequest -Method POST -Uri "$apiBase/google/synced-posts/refresh-all"
  }

  if (-not $SkipAnalyticsBackfill) {
    $results.analytics_backfill = Invoke-JsonRequest -Method POST -Uri "$apiBase/analytics/backfill"
  }

  $results.cloudflare_summary_after = Invoke-JsonRequest -Method GET -Uri "$apiBase/cloudflare/performance/summary?month=$Month"
  $results.blogger_summary_after = Invoke-JsonRequest -Method GET -Uri "$apiBase/analytics/blogs/monthly?month=$Month"

  if (-not $SkipTelegram) {
    $bloggerRunsForMessage = New-Object System.Collections.ArrayList
    foreach ($entry in @($results.blogger_runs)) {
      $null = $bloggerRunsForMessage.Add([ordered]@{
        blog_id = [int]($entry.blog_id | ForEach-Object { $_ })
        blog_name = [string]($entry.blog_name | ForEach-Object { $_ })
        status = [string]($entry.status | ForEach-Object { $_ })
        updated_count = [int]($entry.updated_count | ForEach-Object { $_ })
        failed_count = [int]($entry.failed_count | ForEach-Object { $_ })
      })
    }
    $cloudflareSummary = @{}
    if ($null -ne $results.cloudflare_run) {
      $cloudflareSummary = @{
        status = [string]$results.cloudflare_run.status
        updated_count = Get-IntValue $results.cloudflare_run.updated_count
        failed_count = Get-IntValue $results.cloudflare_run.failed_count
      }
    }
    $message = New-TelegramSummaryMessage -CloudflareSummary $cloudflareSummary -BloggerRuns $bloggerRunsForMessage
    $results.telegram = Invoke-JsonRequest -Method POST -Uri "$apiBase/telegram/test" -Body @{ message = $message }
  }
}
finally {
  foreach ($runner in @($runnerProcesses)) {
    if ($null -ne $runner -and -not $runner.HasExited) {
      Stop-Process -Id $runner.Id -Force -ErrorAction SilentlyContinue
    }
  }
  $results.ended_at = (Get-Date).ToString("o")
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $reportPath = Join-Path $outputDir "refactor-batch-$stamp.json"
  ($results | ConvertTo-Json -Depth 20) | Set-Content -Path $reportPath -Encoding UTF8
  Write-Output ("report_path={0}" -f $reportPath)
  $results | ConvertTo-Json -Depth 20
}
