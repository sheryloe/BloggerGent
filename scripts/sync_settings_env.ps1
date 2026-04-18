param(
    [string]$OutPath = "env/runtime.settings.env",
    [string]$ComposeFile = "docker-compose.yml"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if ([System.IO.Path]::IsPathRooted($OutPath)) {
    $targetPath = [System.IO.Path]::GetFullPath($OutPath)
} else {
    $targetPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetPath) | Out-Null

$pythonScript = @'
from app.db.session import SessionLocal
from app.services.settings_service import get_settings_map

GROUPS = [
    ("OpenAI", [
        ("provider_mode", "PROVIDER_MODE"),
        ("openai_api_key", "OPENAI_API_KEY"),
        ("openai_admin_api_key", "OPENAI_ADMIN_API_KEY"),
        ("openai_text_model", "OPENAI_TEXT_MODEL"),
        ("article_generation_model", "ARTICLE_GENERATION_MODEL"),
        ("openai_image_model", "OPENAI_IMAGE_MODEL"),
        ("openai_request_saver_mode", "OPENAI_REQUEST_SAVER_MODE"),
        ("topic_discovery_provider", "TOPIC_DISCOVERY_PROVIDER"),
        ("topic_discovery_model", "TOPIC_DISCOVERY_MODEL"),
    ]),
    ("Gemini", [
        ("gemini_api_key", "GEMINI_API_KEY"),
        ("gemini_model", "GEMINI_MODEL"),
        ("gemini_daily_request_limit", "GEMINI_DAILY_REQUEST_LIMIT"),
        ("gemini_requests_per_minute_limit", "GEMINI_REQUESTS_PER_MINUTE_LIMIT"),
    ]),
    ("Blogger OAuth", [
        ("blogger_client_name", "BLOGGER_CLIENT_NAME"),
        ("blogger_client_id", "BLOGGER_CLIENT_ID"),
        ("blogger_client_secret", "BLOGGER_CLIENT_SECRET"),
        ("blogger_redirect_uri", "BLOGGER_REDIRECT_URI"),
        ("blogger_refresh_token", "BLOGGER_REFRESH_TOKEN"),
        ("blogger_access_token", "BLOGGER_ACCESS_TOKEN"),
        ("blogger_access_token_expires_at", "BLOGGER_ACCESS_TOKEN_EXPIRES_AT"),
        ("blogger_token_scope", "BLOGGER_TOKEN_SCOPE"),
        ("blogger_token_type", "BLOGGER_TOKEN_TYPE"),
    ]),
    ("Cloudflare Blog", [
        ("cloudflare_channel_enabled", "CLOUDFLARE_CHANNEL_ENABLED"),
        ("cloudflare_blog_api_base_url", "CLOUDFLARE_BLOG_API_BASE_URL"),
        ("cloudflare_blog_m2m_token", "CLOUDFLARE_BLOG_M2M_TOKEN"),
    ]),
    ("GitHub Pages", [
        ("github_pages_owner", "GITHUB_PAGES_OWNER"),
        ("github_pages_repo", "GITHUB_PAGES_REPO"),
        ("github_pages_branch", "GITHUB_PAGES_BRANCH"),
        ("github_pages_token", "GITHUB_PAGES_TOKEN"),
        ("github_pages_base_url", "GITHUB_PAGES_BASE_URL"),
        ("github_pages_assets_dir", "GITHUB_PAGES_ASSETS_DIR"),
    ]),
]

db = SessionLocal()
try:
    values = get_settings_map(db)
finally:
    db.close()

for group_name, items in GROUPS:
    print(f"# {group_name}")
    for key, env_key in items:
        raw = values.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        print(f"{env_key}={value}")
    print("")
'@

$output = $pythonScript | docker compose -f $ComposeFile exec -T api python -
if ($LASTEXITCODE -ne 0) {
    throw "failed_to_export_runtime_settings_env"
}

if ([string]::IsNullOrWhiteSpace($output)) {
    throw "runtime_settings_export_empty"
}

Set-Content -LiteralPath $targetPath -Value $output -Encoding UTF8

$lineCount = (Get-Content -LiteralPath $targetPath | Measure-Object).Count
if ($lineCount -lt 2) {
    throw "runtime_settings_env_too_short"
}

Write-Host ("Exported runtime settings env -> {0}" -f $targetPath)
