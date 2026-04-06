#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_PATH="${1:-$ROOT_DIR/env/runtime.settings.env}"
ENV_PATH="${2:-$ROOT_DIR/.env}"

mkdir -p "$(dirname "$OUT_PATH")"

docker compose exec -T api python - <<'PY' > "$OUT_PATH"
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
PY

python - <<'PY' "$OUT_PATH" "$ENV_PATH"
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])

def load_env(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()

def parse_env(lines: list[str]) -> dict[str, str]:
    data = {}
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        data[key.strip()] = value.strip()
    return data

out_lines = load_env(out_path)
out_map = parse_env(out_lines)
if not out_map:
    raise SystemExit(f"No settings exported: {out_path}")

lines = load_env(env_path)
existing = parse_env(lines)

updated_lines = []
seen_keys = set()
for line in lines:
    raw = line.strip()
    if not raw or raw.startswith("#") or "=" not in raw:
        updated_lines.append(line)
        continue
    key, _ = raw.split("=", 1)
    key = key.strip()
    if key in out_map:
        updated_lines.append(f"{key}={out_map[key]}")
        seen_keys.add(key)
    else:
        updated_lines.append(line)

missing = [key for key in out_map.keys() if key not in seen_keys and key not in existing]
if missing:
    if updated_lines and updated_lines[-1].strip():
        updated_lines.append("")
    updated_lines.append("# Synced from settings")
    for key in missing:
        updated_lines.append(f"{key}={out_map[key]}")

env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
PY

echo "Exported grouped settings -> $OUT_PATH"
echo "Merged settings into -> $ENV_PATH"
