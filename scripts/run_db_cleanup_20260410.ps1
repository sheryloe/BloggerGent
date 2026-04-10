param(
    [string]$CutoffDate = "2026-04-10",
    [ValidateSet("all", "blogger", "cloudflare")]
    [string]$Scope = "all",
    [string]$Timezone = "Asia/Seoul",
    [switch]$Execute,
    [switch]$DryRun,
    [switch]$SkipLiveSync
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if ($Execute -and $DryRun) {
    throw "--Execute and --DryRun cannot be used together"
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed (exit code: $LASTEXITCODE)"
    }
}

$env:SERVICE_ENV_FILE = "env/runtime.settings.env"

if (-not $env:DATABASE_URL) {
    $postgresPort = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { "15432" }
    $env:DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:$postgresPort/bloggent"
}
if (-not $env:STORAGE_ROOT) {
    $env:STORAGE_ROOT = Join-Path $RepoRoot "storage"
}

$backupRoot = Join-Path $RepoRoot "storage\backups"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runDir = Join-Path $backupRoot "cleanup-$stamp"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

Write-Host "[1/5] Start Docker stack (SERVICE_ENV_FILE=$($env:SERVICE_ENV_FILE))"
docker compose up -d postgres redis api | Out-Null
Assert-LastExitCode -Step "docker compose up"

Write-Host "[2/5] Validate docker compose env_file"
$configText = docker compose config
Assert-LastExitCode -Step "docker compose config"
if (-not ($configText -match "env/runtime.settings.env")) {
    throw "docker compose env_file default is not env/runtime.settings.env"
}

Write-Host "[3/5] Create Postgres full dump and CSV snapshots"
$dumpSqlPath = Join-Path $runDir "bloggent-full-$stamp.sql"
docker compose exec -T postgres pg_dump -U bloggent -d bloggent > $dumpSqlPath
Assert-LastExitCode -Step "pg_dump"

$tables = @(
    "analytics_article_facts",
    "synced_cloudflare_posts",
    "synced_blogger_posts"
)

foreach ($table in $tables) {
    $csvPath = Join-Path $runDir "$table-$stamp.csv"
    $copySql = "\copy (select * from $table) to stdout csv header"
    docker compose exec -T postgres psql -U bloggent -d bloggent -c $copySql > $csvPath
    Assert-LastExitCode -Step "snapshot:$table"
}

Write-Host "[4/5] Run dedupe cleanup job"
$pythonArgs = @(
    ".\scripts\cleanup_db_by_publication.py",
    "--cutoff-date", $CutoffDate,
    "--timezone", $Timezone,
    "--scope", $Scope
)
if ($Execute) {
    $pythonArgs += "--execute"
} else {
    $pythonArgs += "--dry-run"
}
if ($SkipLiveSync) {
    $pythonArgs += "--skip-live-sync"
}
python @pythonArgs
Assert-LastExitCode -Step "cleanup_db_by_publication.py"

Write-Host "[5/5] Done"
Write-Host "Backup directory: $runDir"
