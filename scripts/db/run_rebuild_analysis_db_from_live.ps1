param(
    [string]$ServiceEnvFile = "env/runtime.settings.env",
    [string]$ApiBaseUrl = "http://localhost:7002/api/v1",
    [switch]$Execute,
    [switch]$DryRun,
    [switch]$PurgeLegacyFacts
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

if ($Execute -and $DryRun) {
    throw "-Execute and -DryRun cannot be used together."
}
$shouldExecute = [bool]$Execute.IsPresent -and (-not [bool]$DryRun.IsPresent)
$env:SERVICE_ENV_FILE = $ServiceEnvFile

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed (exit code: $LASTEXITCODE)"
    }
}

function Wait-ApiReady {
    param(
        [string]$HealthUrl,
        [int]$MaxAttempts = 90,
        [int]$DelaySeconds = 2
    )
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            $resp = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 5
            if ($resp.status -eq "ok") {
                return
            }
        } catch {
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    throw "API health check timeout: $HealthUrl"
}

function Get-EnvFlagsForService {
    param([string]$ServiceName)
    $raw = docker compose exec -T $ServiceName printenv
    Assert-LastExitCode -Step "inspect-env:$ServiceName"
    $rawText = ($raw | Out-String)
    $flags = @{
        BLOGGER_CLIENT_ID = [bool](Select-String -InputObject $rawText -Pattern '(?m)^BLOGGER_CLIENT_ID=')
        CLOUDFLARE_BLOG_API_BASE_URL = [bool](Select-String -InputObject $rawText -Pattern '(?m)^CLOUDFLARE_BLOG_API_BASE_URL=')
        DATABASE_URL = [bool](Select-String -InputObject $rawText -Pattern '(?m)^DATABASE_URL=')
    }
    return [pscustomobject]$flags
}

function Validate-RequiredColumns {
    param(
        [Parameter(Mandatory=$true)][object[]]$Items,
        [Parameter(Mandatory=$true)][string[]]$RequiredColumns,
        [Parameter(Mandatory=$true)][string]$Label
    )
    $missing = @()
    foreach ($item in $Items) {
        foreach ($column in $RequiredColumns) {
            if (-not ($item.PSObject.Properties.Name -contains $column)) {
                $missing += "$Label missing column '$column'"
            }
        }
    }
    return $missing
}

function Invoke-PostgresJsonQuery {
    param(
        [Parameter(Mandatory=$true)][string]$Sql,
        [Parameter(Mandatory=$true)][string]$Step
    )
    $raw = docker compose exec -T postgres psql -U bloggent -d bloggent -t -A -v ON_ERROR_STOP=1 -c $Sql
    Assert-LastExitCode -Step $Step
    $json = (($raw | Out-String).Trim())
    if (-not $json) {
        return [pscustomobject]@{}
    }
    return $json | ConvertFrom-Json
}

function Get-CanonicalLiveSummary {
    $summarySql = @"
WITH blogger_live_urls AS (
    SELECT
        id,
        blog_id,
        lower(regexp_replace(regexp_replace(trim(url), '^https?://', ''), '/+$', '')) AS identity_key
    FROM synced_blogger_posts
    WHERE url IS NOT NULL
      AND trim(url) <> ''
      AND lower(coalesce(status, '')) IN ('live', 'published')
),
fact_candidates AS (
    SELECT
        id,
        blog_id,
        status,
        seo_score,
        geo_score,
        lighthouse_score,
        lower(regexp_replace(regexp_replace(trim(coalesce(actual_url, '')), '^https?://', ''), '/+$', '')) AS identity_key
    FROM analytics_article_facts
),
live_facts AS (
    SELECT fact.*
    FROM fact_candidates fact
    WHERE fact.identity_key <> ''
      AND EXISTS (
        SELECT 1
        FROM blogger_live_urls live
        WHERE live.blog_id = fact.blog_id
          AND live.identity_key = fact.identity_key
      )
),
stale_facts AS (
    SELECT fact.*
    FROM fact_candidates fact
    WHERE fact.identity_key = ''
       OR NOT EXISTS (
        SELECT 1
        FROM blogger_live_urls live
        WHERE live.blog_id = fact.blog_id
          AND live.identity_key = fact.identity_key
      )
),
cloudflare_published AS (
    SELECT *
    FROM synced_cloudflare_posts
    WHERE lower(coalesce(status, '')) IN ('live', 'published')
)
SELECT json_build_object(
    'blogger_live_count', (SELECT count(*) FROM blogger_live_urls),
    'blogger_non_live_synced_count', (
        SELECT count(*) FROM synced_blogger_posts
        WHERE lower(coalesce(status, '')) NOT IN ('live', 'published')
    ),
    'cloudflare_published_count', (SELECT count(*) FROM cloudflare_published),
    'cloudflare_non_published_count', (
        SELECT count(*) FROM synced_cloudflare_posts
        WHERE lower(coalesce(status, '')) NOT IN ('live', 'published')
    ),
    'facts_to_normalize', (
        SELECT count(*) FROM live_facts
        WHERE lower(coalesce(status, '')) <> 'published'
    ),
    'facts_to_purge', (SELECT count(*) FROM stale_facts),
    'score_missing', json_build_object(
        'blogger_seo_count', (SELECT count(*) FROM live_facts WHERE seo_score IS NULL),
        'blogger_geo_count', (SELECT count(*) FROM live_facts WHERE geo_score IS NULL),
        'blogger_lighthouse_count', (SELECT count(*) FROM live_facts WHERE lighthouse_score IS NULL),
        'cloudflare_lighthouse_count', (SELECT count(*) FROM cloudflare_published WHERE lighthouse_score IS NULL)
    ),
    'sample_normalize_fact_ids', (
        SELECT coalesce(json_agg(id), '[]'::json)
        FROM (
            SELECT id FROM live_facts
            WHERE lower(coalesce(status, '')) <> 'published'
            ORDER BY id
            LIMIT 20
        ) sample
    ),
    'sample_purge_fact_ids', (
        SELECT coalesce(json_agg(id), '[]'::json)
        FROM (
            SELECT id FROM stale_facts
            ORDER BY id
            LIMIT 20
        ) sample
    ),
    'sample_cloudflare_lighthouse_remote_ids', (
        SELECT coalesce(json_agg(remote_post_id), '[]'::json)
        FROM (
            SELECT remote_post_id FROM cloudflare_published
            WHERE lighthouse_score IS NULL
            ORDER BY id
            LIMIT 20
        ) sample
    )
)::text;
"@
    return Invoke-PostgresJsonQuery -Sql $summarySql -Step "canonical-live-summary"
}

Write-Host "[1/11] Start Docker stack with fixed env file: SERVICE_ENV_FILE=$ServiceEnvFile"
docker compose --profile async up -d --force-recreate postgres redis api web worker scheduler | Out-Null
Assert-LastExitCode -Step "docker compose up"

Write-Host "[2/11] Wait for API health"
$apiRoot = ($ApiBaseUrl -replace "/api/v1/?$", "").TrimEnd("/")
Wait-ApiReady -HealthUrl "$apiRoot/healthz"

Write-Host "[3/11] Validate runtime env keys in API/WEB/WORKER"
$composeConfig = docker compose config
Assert-LastExitCode -Step "docker compose config"
if (-not ($composeConfig -match [Regex]::Escape($ServiceEnvFile))) {
    throw "docker compose config does not include expected env file: $ServiceEnvFile"
}
$apiFlags = Get-EnvFlagsForService -ServiceName "api"
$webFlags = Get-EnvFlagsForService -ServiceName "web"
$workerFlags = Get-EnvFlagsForService -ServiceName "worker"
Write-Host ("api flags: BLOGGER={0} CLOUDFLARE={1} DB={2}" -f $apiFlags.BLOGGER_CLIENT_ID, $apiFlags.CLOUDFLARE_BLOG_API_BASE_URL, $apiFlags.DATABASE_URL)
Write-Host ("worker flags: BLOGGER={0} CLOUDFLARE={1} DB={2}" -f $workerFlags.BLOGGER_CLIENT_ID, $workerFlags.CLOUDFLARE_BLOG_API_BASE_URL, $workerFlags.DATABASE_URL)
Write-Host ("web flags: BLOGGER={0} CLOUDFLARE={1} DB={2}" -f $webFlags.BLOGGER_CLIENT_ID, $webFlags.CLOUDFLARE_BLOG_API_BASE_URL, $webFlags.DATABASE_URL)
foreach ($flags in @($apiFlags, $workerFlags)) {
    if (-not $flags.BLOGGER_CLIENT_ID -or -not $flags.CLOUDFLARE_BLOG_API_BASE_URL -or -not $flags.DATABASE_URL) {
        throw "Environment key validation failed: one of Blogger/Cloudflare/DB keys is empty."
    }
}
if (-not $webFlags.BLOGGER_CLIENT_ID -or -not $webFlags.CLOUDFLARE_BLOG_API_BASE_URL) {
    Write-Host "warning: WEB service does not expose full Blogger/Cloudflare credentials; continuing with API/WORKER validated."
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = "D:\Donggri_Runtime\BloggerGent\db\snapshots\analysis-rebuild-$stamp"
$reportDir = "D:\Donggri_Runtime\BloggerGent\storage\_common\analysis"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

Write-Host "[4/11] Create DB backups (pg_dump + table CSV snapshots)"
$dumpPath = Join-Path $backupDir "bloggent-full-$stamp.sql"
docker compose exec -T postgres pg_dump -U bloggent -d bloggent > $dumpPath
Assert-LastExitCode -Step "pg_dump"

$snapshotTables = @(
    "analytics_article_facts",
    "analytics_theme_monthly_stats",
    "analytics_blog_monthly_reports",
    "synced_blogger_posts",
    "synced_cloudflare_posts"
)
foreach ($table in $snapshotTables) {
    $csvPath = Join-Path $backupDir "$table-$stamp.csv"
    $copySql = "\copy (select * from $table) to stdout csv header"
    docker compose exec -T postgres psql -U bloggent -d bloggent -c $copySql > $csvPath
    Assert-LastExitCode -Step "snapshot:$table"
}

if ($shouldExecute) {
    Write-Host "[5/11] Reset analysis/sync tables (schema kept)"
    $truncateSql = @"
DELETE FROM analytics_theme_monthly_stats;
DELETE FROM analytics_blog_monthly_reports;
DELETE FROM analytics_article_facts;
DELETE FROM synced_blogger_posts;
DELETE FROM synced_cloudflare_posts;
"@
    docker compose exec -T postgres psql -U bloggent -d bloggent -v ON_ERROR_STOP=1 -c $truncateSql | Out-Null
    Assert-LastExitCode -Step "truncate-analysis-sync-tables"
} else {
    Write-Host "[5/11] DryRun: skip table reset"
}

Write-Host "[6/11] Resync Blogger from live posts"
$bloggerRefresh = if ($shouldExecute) {
    Invoke-RestMethod -Uri "$ApiBaseUrl/google/synced-posts/refresh-all" -Method Post -TimeoutSec 1800
} else {
    @{ status = "dry_run"; refreshed_blog_count = 0; warnings = @() }
}

Write-Host "[7/11] Resync Cloudflare from live posts"
$cloudflareRefresh = if ($shouldExecute) {
    Invoke-RestMethod -Uri "$ApiBaseUrl/cloudflare/posts/refresh" -Method Post -TimeoutSec 1800
} else {
    @{ status = "dry_run"; count = 0 }
}

Write-Host "[8/11] Collect grouped lists (Blogger by blog, Cloudflare by category)"
$bloggerGrouped = Invoke-RestMethod -Uri "$ApiBaseUrl/google/synced-posts/grouped-by-blog" -Method Get -TimeoutSec 300
$cloudflareGrouped = Invoke-RestMethod -Uri "$ApiBaseUrl/cloudflare/posts/grouped-by-category" -Method Get -TimeoutSec 300

$requiredColumns = @("seo_score", "geo_score", "lighthouse_score", "index_status", "live_image_count", "status")
$bloggerItems = @()
foreach ($group in ($bloggerGrouped.groups | Where-Object { $_ -ne $null })) {
    $bloggerItems += @($group.items)
}
$cloudflareItems = @()
foreach ($group in ($cloudflareGrouped | Where-Object { $_ -ne $null })) {
    $cloudflareItems += @($group.items)
}

$validationErrors = @()
$validationErrors += Validate-RequiredColumns -Items $bloggerItems -RequiredColumns $requiredColumns -Label "blogger"
$validationErrors += Validate-RequiredColumns -Items $cloudflareItems -RequiredColumns $requiredColumns -Label "cloudflare"

if ($validationErrors.Count -gt 0) {
    throw "Required column validation failed: $($validationErrors -join '; ')"
}

Write-Host "[9/11] Collect canonical live DB summary"
$canonicalSummary = Get-CanonicalLiveSummary
Write-Host ("canonical live summary: " + ($canonicalSummary | ConvertTo-Json -Depth 20 -Compress))

if ($shouldExecute -and $PurgeLegacyFacts) {
    Write-Host "[10/11] Normalize live analytics facts and delete rows not matching live published URLs"
    $normalizeSql = @"
WITH live_urls AS (
    SELECT
        blog_id,
        lower(regexp_replace(regexp_replace(trim(url), '^https?://', ''), '/+$', '')) AS identity_key
    FROM synced_blogger_posts
    WHERE url IS NOT NULL
      AND trim(url) <> ''
      AND lower(coalesce(status, '')) IN ('live', 'published')
),
fact_candidates AS (
    SELECT
        id,
        blog_id,
        lower(regexp_replace(regexp_replace(trim(coalesce(actual_url, '')), '^https?://', ''), '/+$', '')) AS identity_key
    FROM analytics_article_facts
),
live_matched_facts AS (
    SELECT fact.id
    FROM analytics_article_facts fact
    JOIN fact_candidates cand ON cand.id = fact.id
    WHERE cand.identity_key <> ''
      AND EXISTS (
        SELECT 1 FROM live_urls lu
        WHERE lu.blog_id = cand.blog_id
          AND lu.identity_key = cand.identity_key
      )
)
UPDATE analytics_article_facts fact
SET status = 'published'
FROM live_matched_facts matched
WHERE fact.id = matched.id
  AND lower(coalesce(fact.status, '')) <> 'published';
"@
    docker compose exec -T postgres psql -U bloggent -d bloggent -v ON_ERROR_STOP=1 -c $normalizeSql | Out-Null
    Assert-LastExitCode -Step "normalize-live-analytics-facts"

    $purgeSql = @"
WITH live_urls AS (
    SELECT
        blog_id,
        lower(regexp_replace(regexp_replace(trim(url), '^https?://', ''), '/+$', '')) AS identity_key
    FROM synced_blogger_posts
    WHERE url IS NOT NULL
      AND trim(url) <> ''
      AND lower(coalesce(status, '')) IN ('live', 'published')
),
fact_candidates AS (
    SELECT
        id,
        blog_id,
        lower(regexp_replace(regexp_replace(trim(coalesce(actual_url, '')), '^https?://', ''), '/+$', '')) AS identity_key
    FROM analytics_article_facts
)
DELETE FROM analytics_article_facts fact
USING fact_candidates cand
WHERE fact.id = cand.id
  AND (
    cand.identity_key = ''
    OR NOT EXISTS (
      SELECT 1 FROM live_urls lu
      WHERE lu.blog_id = cand.blog_id
        AND lu.identity_key = cand.identity_key
    )
  );
"@
    docker compose exec -T postgres psql -U bloggent -d bloggent -v ON_ERROR_STOP=1 -c $purgeSql | Out-Null
    Assert-LastExitCode -Step "purge-legacy-analytics-facts"

    $rebuildCode = @'
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.entities import AnalyticsArticleFact
from app.services.ops.analytics_service import rebuild_blog_month_rollup

db = SessionLocal()
try:
    pairs = db.execute(
        select(AnalyticsArticleFact.blog_id, AnalyticsArticleFact.month).distinct()
    ).all()
    for blog_id, month in pairs:
        if month:
            rebuild_blog_month_rollup(db, blog_id, month, commit=False)
    db.commit()
finally:
    db.close()
'@
    $rebuildCode | docker compose exec -T api python - | Out-Null
    Assert-LastExitCode -Step "rebuild-monthly-rollups"

    $canonicalSummary = Get-CanonicalLiveSummary
    Write-Host ("canonical live summary after cleanup: " + ($canonicalSummary | ConvertTo-Json -Depth 20 -Compress))
}

Write-Host "[11/11] Save result reports"
$report = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    execute = $shouldExecute
    purge_legacy_facts = [bool]$PurgeLegacyFacts
    service_env_file = $ServiceEnvFile
    backup_dir = $backupDir
    blogger_refresh = $bloggerRefresh
    cloudflare_refresh = $cloudflareRefresh
    canonical_live_summary = $canonicalSummary
    blogger_group_count = ($bloggerGrouped.total_groups)
    blogger_item_count = $bloggerItems.Count
    cloudflare_category_count = ($cloudflareGrouped | Measure-Object).Count
    cloudflare_item_count = $cloudflareItems.Count
}
$reportPath = Join-Path $reportDir "analysis-rebuild-live-$stamp.json"
$report | ConvertTo-Json -Depth 20 | Set-Content -Path $reportPath -Encoding UTF8

$bloggerListPath = Join-Path $reportDir "analysis-blogger-grouped-$stamp.json"
$cloudflareListPath = Join-Path $reportDir "analysis-cloudflare-grouped-$stamp.json"
$bloggerGrouped | ConvertTo-Json -Depth 30 | Set-Content -Path $bloggerListPath -Encoding UTF8
$cloudflareGrouped | ConvertTo-Json -Depth 30 | Set-Content -Path $cloudflareListPath -Encoding UTF8

Write-Host "Done: $reportPath"
Write-Host "Blogger list: $bloggerListPath"
Write-Host "Cloudflare list: $cloudflareListPath"
