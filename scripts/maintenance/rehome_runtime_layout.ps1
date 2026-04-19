param(
    [ValidateSet("dry-run", "apply")]
    [string]$Mode = "dry-run",
    [string]$RuntimeRoot = "D:\Donggri_Runtime\BloggerGent",
    [int]$KeepBackupSets = 2,
    [int]$ReportRetentionDays = 14
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Write-Step {
    param([string]$Message)
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}

function Normalize-PathString {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return ([System.IO.Path]::GetFullPath($PathValue)).Replace("\", "/")
}

function Get-EnvMap {
    param([Parameter(Mandatory = $true)][string]$EnvPath)
    $map = @{}
    if (-not (Test-Path -LiteralPath $EnvPath)) {
        return $map
    }

    $lines = Get-Content -LiteralPath $EnvPath
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith("#")) { continue }
        $parts = $line -split "=", 2
        if ($parts.Length -ne 2) { continue }
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($key) {
            $map[$key] = $value
        }
    }
    return $map
}

function Resolve-PathFromEnvOrDefault {
    param(
        [Parameter(Mandatory = $true)][hashtable]$EnvMap,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$DefaultValue,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $raw = if ($EnvMap.ContainsKey($Key) -and $EnvMap[$Key]) { $EnvMap[$Key] } else { $DefaultValue }
    if ($raw -match '^[A-Za-z]:[\\/]') {
        return [System.IO.Path]::GetFullPath($raw)
    }
    if ($raw.StartsWith("./") -or $raw.StartsWith(".\")) {
        $tail = $raw.Substring(2)
        return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $tail))
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $raw))
}

function Get-ContainerMountSource {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeFile,
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $containerId = (& docker compose -f $ComposeFile ps -a -q $Service 2>$null) -join ""
    $containerId = $containerId.Trim()
    if (-not $containerId) {
        return $null
    }

    $mountJson = & docker inspect $containerId --format "{{json .Mounts}}" 2>$null
    if (-not $mountJson) {
        return $null
    }
    $mounts = $mountJson | ConvertFrom-Json
    foreach ($mount in $mounts) {
        if ($mount.Destination -eq $Destination) {
            return [string]$mount.Source
        }
    }
    return $null
}

function Get-PathStat {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue)) {
        return [PSCustomObject]@{
            Path = $PathValue
            Exists = $false
            FileCount = 0
            SizeBytes = 0
            SizeGB = 0
        }
    }
    $files = Get-ChildItem -LiteralPath $PathValue -Recurse -Force -File -ErrorAction SilentlyContinue
    $size = ($files | Measure-Object -Property Length -Sum).Sum
    return [PSCustomObject]@{
        Path = $PathValue
        Exists = $true
        FileCount = $files.Count
        SizeBytes = [int64]$size
        SizeGB = [math]::Round(($size / 1GB), 3)
    }
}

function Invoke-RobocopySync {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )
    if (-not (Test-Path -LiteralPath $SourcePath)) {
        Write-Step "Source missing, skip copy: $SourcePath"
        return
    }
    New-Item -ItemType Directory -Path $TargetPath -Force | Out-Null
    & robocopy $SourcePath $TargetPath /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ /NFL /NDL /NP /NJH /NJS | Out-Null
    $code = $LASTEXITCODE
    if ($code -gt 7) {
        throw "robocopy_failed source=$SourcePath target=$TargetPath exit_code=$code"
    }
}

function Set-Or-Add-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$EnvPath,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )
    $lines = @()
    if (Test-Path -LiteralPath $EnvPath) {
        $lines = Get-Content -LiteralPath $EnvPath
    }
    $updated = $false
    $newLines = foreach ($line in $lines) {
        if ($line -match "^\s*${Key}=") {
            $updated = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $updated) {
        if ($newLines.Count -gt 0 -and $newLines[-1] -ne "") {
            $newLines += ""
        }
        $newLines += "$Key=$Value"
    }
    Set-Content -LiteralPath $EnvPath -Value $newLines -Encoding UTF8
}

function Wait-ContainerReady {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeFile,
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSeconds = 180
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $containerId = (& docker compose -f $ComposeFile ps -a -q $Service 2>$null) -join ""
        $containerId = $containerId.Trim()
        if (-not $containerId) {
            Start-Sleep -Seconds 2
            continue
        }

        $statusJson = & docker inspect $containerId --format "{{json .State}}" 2>$null
        if (-not $statusJson) {
            Start-Sleep -Seconds 2
            continue
        }
        $state = $statusJson | ConvertFrom-Json
        if (-not $state.Running) {
            Start-Sleep -Seconds 2
            continue
        }

        $hasHealth = $state.PSObject.Properties.Name -contains "Health"
        if ($hasHealth -and $null -ne $state.Health) {
            if ($state.Health.Status -eq "healthy") {
                return $true
            }
        } else {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Cleanup-BackupSets {
    param(
        [Parameter(Mandatory = $true)][string]$BackupRoot,
        [int]$KeepCount = 2,
        [string]$ModeValue = "dry-run"
    )
    if (-not (Test-Path -LiteralPath $BackupRoot)) {
        return @()
    }
    $dirs = Get-ChildItem -LiteralPath $BackupRoot -Directory -Force | Sort-Object LastWriteTime -Descending
    if ($dirs.Count -le $KeepCount) {
        return @()
    }
    $toDelete = $dirs | Select-Object -Skip $KeepCount
    if ($ModeValue -eq "apply") {
        foreach ($dir in $toDelete) {
            Remove-Item -LiteralPath $dir.FullName -Recurse -Force
        }
    }
    return $toDelete.FullName
}

function Cleanup-OldReports {
    param(
        [Parameter(Mandatory = $true)][string]$ReportRoot,
        [int]$RetentionDays = 14,
        [string]$ModeValue = "dry-run"
    )
    if (-not (Test-Path -LiteralPath $ReportRoot)) {
        return [PSCustomObject]@{
            Files = @()
            DeletedSizeBytes = 0
        }
    }
    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    $oldFiles = Get-ChildItem -LiteralPath $ReportRoot -Recurse -File -Force | Where-Object { $_.LastWriteTime -lt $cutoff }
    $size = ($oldFiles | Measure-Object -Property Length -Sum).Sum
    if ($ModeValue -eq "apply") {
        foreach ($file in $oldFiles) {
            Remove-Item -LiteralPath $file.FullName -Force
        }
        # empty directory cleanup
        Get-ChildItem -LiteralPath $ReportRoot -Recurse -Directory -Force |
            Sort-Object FullName -Descending |
            ForEach-Object {
                if (-not (Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue)) {
                    Remove-Item -LiteralPath $_.FullName -Force
                }
            }
    }
    return [PSCustomObject]@{
        Files = $oldFiles.FullName
        DeletedSizeBytes = [int64]$size
    }
}

function Assert-Http200 {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSeconds = 5
    )
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "http_check_failed url=$Url status=$($response.StatusCode)"
    }
}

$scriptDir = Split-Path -Parent $PSCommandPath
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\.."))
$composeFile = Join-Path $repoRoot "docker-compose.yml"
$envFile = Join-Path $repoRoot ".env"

$runtimeRootAbs = [System.IO.Path]::GetFullPath($RuntimeRoot)
$targetDbRoot = Join-Path $runtimeRootAbs "db"
$targetStorageRoot = Join-Path $runtimeRootAbs "storage"

$envMap = Get-EnvMap -EnvPath $envFile
$defaults = @{
    postgres = Resolve-PathFromEnvOrDefault -EnvMap $envMap -Key "POSTGRES_DATA_DIR" -DefaultValue "./.docker-data/postgres" -RepoRoot $repoRoot
    redis = Resolve-PathFromEnvOrDefault -EnvMap $envMap -Key "REDIS_DATA_DIR" -DefaultValue "./.docker-data/redis" -RepoRoot $repoRoot
    minio = Resolve-PathFromEnvOrDefault -EnvMap $envMap -Key "MINIO_DATA_DIR" -DefaultValue "./.docker-data/minio" -RepoRoot $repoRoot
    storage = Resolve-PathFromEnvOrDefault -EnvMap $envMap -Key "API_STORAGE_DIR" -DefaultValue "D:/Donggri_Runtime/BloggerGent/storage" -RepoRoot $repoRoot
}

$sourceMap = @{
    postgres = (Get-ContainerMountSource -ComposeFile $composeFile -Service "postgres" -Destination "/var/lib/postgresql/data")
    redis = (Get-ContainerMountSource -ComposeFile $composeFile -Service "redis" -Destination "/data")
    minio = (Get-ContainerMountSource -ComposeFile $composeFile -Service "minio" -Destination "/data")
    storage = (Get-ContainerMountSource -ComposeFile $composeFile -Service "api" -Destination "/app/storage")
}

foreach ($key in @("postgres", "redis", "minio", "storage")) {
    if (-not $sourceMap[$key]) {
        $sourceMap[$key] = $defaults[$key]
    }
}

$targetMap = @{
    postgres = Join-Path $targetDbRoot "postgres"
    redis = Join-Path $targetDbRoot "redis"
    minio = Join-Path $targetDbRoot "minio"
    storage = $targetStorageRoot
}

$beforeGit = & git -C $repoRoot count-objects -vH

$sourceStats = @{
    postgres = Get-PathStat -PathValue $sourceMap.postgres
    redis = Get-PathStat -PathValue $sourceMap.redis
    minio = Get-PathStat -PathValue $sourceMap.minio
    storage = Get-PathStat -PathValue $sourceMap.storage
}

Write-Step "Mode=$Mode RuntimeRoot=$runtimeRootAbs"
Write-Step "Source -> Target mapping"
foreach ($name in @("postgres", "redis", "minio", "storage")) {
    Write-Host ("  {0}: {1} -> {2}" -f $name, $sourceMap[$name], $targetMap[$name])
}

Write-Step "Source size snapshot"
foreach ($name in @("postgres", "redis", "minio", "storage")) {
    $s = $sourceStats[$name]
    Write-Host ("  {0}: exists={1}, files={2}, size_gb={3}" -f $name, $s.Exists, $s.FileCount, $s.SizeGB)
}

$backupRoot = Join-Path $targetDbRoot "snapshots"
$reportsRoot = Join-Path $targetStorageRoot "_common\analysis"
$plannedBackupDeletes = Cleanup-BackupSets -BackupRoot $backupRoot -KeepCount $KeepBackupSets -ModeValue "dry-run"
$plannedReportDeletes = Cleanup-OldReports -ReportRoot $reportsRoot -RetentionDays $ReportRetentionDays -ModeValue "dry-run"

if ($Mode -eq "dry-run") {
    Write-Step "Dry-run complete (no changes)."
    Write-Host ("  backups_to_delete={0}" -f @($plannedBackupDeletes).Count)
    Write-Host ("  reports_to_delete={0}, reports_size_gb={1}" -f @($plannedReportDeletes.Files).Count, [math]::Round($plannedReportDeletes.DeletedSizeBytes / 1GB, 3))
    Write-Host "  planned_env_values:"
    Write-Host ("    POSTGRES_DATA_DIR={0}" -f (Normalize-PathString -PathValue $targetMap.postgres))
    Write-Host ("    REDIS_DATA_DIR={0}" -f (Normalize-PathString -PathValue $targetMap.redis))
    Write-Host ("    MINIO_DATA_DIR={0}" -f (Normalize-PathString -PathValue $targetMap.minio))
    Write-Host ("    API_STORAGE_DIR={0}" -f (Normalize-PathString -PathValue $targetMap.storage))
    Write-Step "Current git count-objects -vH"
    $beforeGit | ForEach-Object { Write-Host ("  " + $_) }
    exit 0
}

Write-Step "Apply started."
New-Item -ItemType Directory -Path $runtimeRootAbs -Force | Out-Null
New-Item -ItemType Directory -Path $targetDbRoot -Force | Out-Null
New-Item -ItemType Directory -Path $targetStorageRoot -Force | Out-Null

Invoke-RobocopySync -SourcePath $sourceMap.postgres -TargetPath $targetMap.postgres
Invoke-RobocopySync -SourcePath $sourceMap.redis -TargetPath $targetMap.redis
Invoke-RobocopySync -SourcePath $sourceMap.minio -TargetPath $targetMap.minio
Invoke-RobocopySync -SourcePath $sourceMap.storage -TargetPath $targetMap.storage

Set-Or-Add-EnvValue -EnvPath $envFile -Key "POSTGRES_DATA_DIR" -Value (Normalize-PathString -PathValue $targetMap.postgres)
Set-Or-Add-EnvValue -EnvPath $envFile -Key "REDIS_DATA_DIR" -Value (Normalize-PathString -PathValue $targetMap.redis)
Set-Or-Add-EnvValue -EnvPath $envFile -Key "MINIO_DATA_DIR" -Value (Normalize-PathString -PathValue $targetMap.minio)
Set-Or-Add-EnvValue -EnvPath $envFile -Key "API_STORAGE_DIR" -Value (Normalize-PathString -PathValue $targetMap.storage)

Write-Step "Validating docker compose config."
& docker compose -f $composeFile config > $null
if ($LASTEXITCODE -ne 0) {
    throw "docker_compose_config_failed"
}

Write-Step "Restarting services with new mounts."
& docker compose -f $composeFile up -d postgres redis api
if ($LASTEXITCODE -ne 0) {
    throw "docker_compose_up_failed core_services"
}
& docker compose -f $composeFile --profile storage up -d minio
if ($LASTEXITCODE -ne 0) {
    throw "docker_compose_up_failed minio"
}

Write-Step "Waiting health checks."
if (-not (Wait-ContainerReady -ComposeFile $composeFile -Service "postgres" -TimeoutSeconds 180)) {
    throw "postgres_not_ready"
}
if (-not (Wait-ContainerReady -ComposeFile $composeFile -Service "redis" -TimeoutSeconds 180)) {
    throw "redis_not_ready"
}
if (-not (Wait-ContainerReady -ComposeFile $composeFile -Service "api" -TimeoutSeconds 180)) {
    throw "api_not_ready"
}
if (-not (Wait-ContainerReady -ComposeFile $composeFile -Service "minio" -TimeoutSeconds 180)) {
    throw "minio_not_ready"
}

$apiPort = if ($envMap.ContainsKey("API_PORT") -and $envMap["API_PORT"]) { [int]$envMap["API_PORT"] } else { 8000 }
$minioPort = if ($envMap.ContainsKey("MINIO_API_PORT") -and $envMap["MINIO_API_PORT"]) { [int]$envMap["MINIO_API_PORT"] } else { 9000 }
Assert-Http200 -Url ("http://localhost:{0}/healthz" -f $apiPort)
Assert-Http200 -Url ("http://localhost:{0}/minio/health/live" -f $minioPort)

$removedBackups = Cleanup-BackupSets -BackupRoot $backupRoot -KeepCount $KeepBackupSets -ModeValue "apply"
$removedReports = Cleanup-OldReports -ReportRoot $reportsRoot -RetentionDays $ReportRetentionDays -ModeValue "apply"

Write-Step "Running local git cleanup."
& git -C $repoRoot reflog expire --expire=now --expire-unreachable=now --all
if ($LASTEXITCODE -ne 0) { throw "git_reflog_expire_failed" }
& git -C $repoRoot gc --prune=now --aggressive
if ($LASTEXITCODE -ne 0) { throw "git_gc_failed" }
$afterGit = & git -C $repoRoot count-objects -vH

$targetStats = @{
    postgres = Get-PathStat -PathValue $targetMap.postgres
    redis = Get-PathStat -PathValue $targetMap.redis
    minio = Get-PathStat -PathValue $targetMap.minio
    storage = Get-PathStat -PathValue $targetMap.storage
}

$report = [PSCustomObject]@{
    mode = $Mode
    runtime_root = $runtimeRootAbs
    mapping = [PSCustomObject]@{
        postgres = [PSCustomObject]@{ source = $sourceMap.postgres; target = $targetMap.postgres }
        redis = [PSCustomObject]@{ source = $sourceMap.redis; target = $targetMap.redis }
        minio = [PSCustomObject]@{ source = $sourceMap.minio; target = $targetMap.minio }
        storage = [PSCustomObject]@{ source = $sourceMap.storage; target = $targetMap.storage }
    }
    source_stats = $sourceStats
    target_stats = $targetStats
    cleanup = [PSCustomObject]@{
        removed_backup_sets = $removedBackups
        removed_backup_set_count = @($removedBackups).Count
        removed_report_file_count = @($removedReports.Files).Count
        removed_report_size_gb = [math]::Round($removedReports.DeletedSizeBytes / 1GB, 3)
        keep_backup_sets = $KeepBackupSets
        report_retention_days = $ReportRetentionDays
    }
    git = [PSCustomObject]@{
        before = $beforeGit
        after = $afterGit
    }
    generated_at = (Get-Date).ToString("o")
}

$reportDir = Join-Path $runtimeRootAbs "tools\reports"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportPath = Join-Path $reportDir ("rehome-runtime-layout-{0}.json" -f $stamp)
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Step "Apply complete."
Write-Host ("  report_path={0}" -f $reportPath)
Write-Host ("  removed_backup_sets={0}" -f @($removedBackups).Count)
Write-Host ("  removed_report_files={0}" -f @($removedReports.Files).Count)
Write-Step "git count-objects -vH (before)"
$beforeGit | ForEach-Object { Write-Host ("  " + $_) }
Write-Step "git count-objects -vH (after)"
$afterGit | ForEach-Object { Write-Host ("  " + $_) }
