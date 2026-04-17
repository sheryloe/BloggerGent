[CmdletBinding()]
param(
    [string]$Owner = "",
    [string]$Repo = "",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

function Resolve-OwnerRepo {
    param(
        [string]$OwnerInput,
        [string]$RepoInput
    )

    if ($OwnerInput -and $RepoInput) {
        return @{ owner = $OwnerInput; repo = $RepoInput }
    }

    $remote = git remote get-url origin
    if (-not $remote) {
        throw "origin remote not found. Pass -Owner and -Repo explicitly."
    }

    $normalized = $remote.Trim()
    $normalized = $normalized -replace "\.git$", ""
    $normalized = $normalized -replace "^git@github\.com:", "https://github.com/"

    if ($normalized -notmatch "github\.com/(?<owner>[^/]+)/(?<repo>[^/]+)$") {
        throw "Unable to parse owner/repo from origin remote: $remote"
    }

    return @{ owner = $matches.owner; repo = $matches.repo }
}

function Invoke-GhApiPatch {
    param(
        [string]$Endpoint,
        [hashtable]$Payload
    )
    $json = $Payload | ConvertTo-Json -Depth 20 -Compress
    $json | gh api --method PATCH $Endpoint --input - | Out-Null
}

function Invoke-GhApiPut {
    param(
        [string]$Endpoint,
        [hashtable]$Payload
    )
    $json = $Payload | ConvertTo-Json -Depth 20 -Compress
    $json | gh api --method PUT $Endpoint --input - | Out-Null
}

$resolved = Resolve-OwnerRepo -OwnerInput $Owner -RepoInput $Repo
$owner = $resolved.owner
$repo = $resolved.repo

Write-Host "Applying security baseline to $owner/$repo (branch: $Branch)"

# 1) Repository security & analysis toggles
Invoke-GhApiPatch -Endpoint "/repos/$owner/$repo" -Payload @{
    security_and_analysis = @{
        advanced_security              = @{ status = "enabled" }
        secret_scanning                = @{ status = "enabled" }
        secret_scanning_push_protection = @{ status = "enabled" }
        dependabot_security_updates    = @{ status = "enabled" }
    }
}

# 2) Branch protection
Invoke-GhApiPut -Endpoint "/repos/$owner/$repo/branches/$Branch/protection" -Payload @{
    required_status_checks = @{
        strict   = $true
        contexts = @(
            "Dependency Review",
            "Secret Scan",
            "API Check",
            "Web Build Check",
            "Analyze (python)",
            "Analyze (javascript-typescript)"
        )
    }
    enforce_admins = $true
    required_pull_request_reviews = @{
        dismissal_restrictions      = @{}
        dismiss_stale_reviews       = $true
        require_code_owner_reviews  = $true
        required_approving_review_count = 1
        require_last_push_approval  = $true
    }
    restrictions = $null
    allow_force_pushes = $false
    allow_deletions = $false
    block_creations = $false
    required_linear_history = $true
    lock_branch = $false
    allow_fork_syncing = $true
}

Write-Host "Security baseline applied successfully."
