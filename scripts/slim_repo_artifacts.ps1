param(
    [ValidateRange(1, 365)]
    [int]$KeepRecentBackups = 3,
    [switch]$PruneBackups,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$targets = @(
    ".codex-output",
    "apps/web/.next",
    "storage/playwright-browser"
)

function Remove-IfExists {
    param(
        [string]$PathValue,
        [bool]$DoRemove
    )
    if (-not (Test-Path $PathValue)) {
        return
    }
    if ($DoRemove) {
        Remove-Item -LiteralPath $PathValue -Recurse -Force
        Write-Host "removed: $PathValue"
    } else {
        Write-Host "dry-run: $PathValue"
    }
}

Write-Host "Start cleanup (execute=$Execute)"
foreach ($target in $targets) {
    Remove-IfExists -PathValue (Join-Path $RepoRoot $target) -DoRemove ([bool]$Execute)
}

$backupRoot = Join-Path $RepoRoot "storage\backups"
if ($PruneBackups -and (Test-Path $backupRoot)) {
    $backupDirs = Get-ChildItem -Path $backupRoot -Directory | Sort-Object LastWriteTime -Descending
    $stale = $backupDirs | Select-Object -Skip ([Math]::Max(0, $KeepRecentBackups))
    foreach ($dir in $stale) {
        if ($Execute) {
            Remove-Item -LiteralPath $dir.FullName -Recurse -Force
            Write-Host "removed backup: $($dir.FullName)"
        } else {
            Write-Host "dry-run backup: $($dir.FullName)"
        }
    }
}

Write-Host "Cleanup completed"
