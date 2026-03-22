from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Setting
from app.services.secret_service import decrypt_secret_value, encrypt_secret_value, is_encrypted_secret


@dataclass(slots=True)
class DefaultSetting:
    value: str
    description: str
    is_secret: bool = False


DEFAULT_SETTINGS: dict[str, DefaultSetting] = {
    "provider_mode": DefaultSetting(settings.provider_mode, "mock or live provider mode"),
    "public_image_provider": DefaultSetting(
        settings.public_image_provider,
        "대표 이미지 공개 전달 방식. 현재 운영 권장값은 cloudflare_r2 입니다.",
    ),
    "public_asset_base_url": DefaultSetting(
        settings.public_asset_base_url,
        "Public base URL used only when provider is local. Example: https://your-domain.com",
    ),
    "cloudflare_account_id": DefaultSetting(settings.cloudflare_account_id, "Cloudflare account ID"),
    "cloudflare_r2_bucket": DefaultSetting(settings.cloudflare_r2_bucket, "Cloudflare R2 bucket name"),
    "cloudflare_r2_access_key_id": DefaultSetting(
        settings.cloudflare_r2_access_key_id,
        "Cloudflare R2 access key ID",
        True,
    ),
    "cloudflare_r2_secret_access_key": DefaultSetting(
        settings.cloudflare_r2_secret_access_key,
        "Cloudflare R2 secret access key",
        True,
    ),
    "cloudflare_r2_public_base_url": DefaultSetting(
        settings.cloudflare_r2_public_base_url,
        "Cloudflare 공개 이미지 기준 URL. integration 업로드를 쓰면 비워둘 때 cloudflare_blog_api_base_url + /assets 가 자동 적용됩니다.",
    ),
    "cloudflare_r2_prefix": DefaultSetting(
        settings.cloudflare_r2_prefix,
        "Object key prefix inside the R2 bucket. Files are stored as <prefix>/<slug>.png",
    ),
    "github_pages_owner": DefaultSetting(settings.github_pages_owner, "GitHub Pages owner or organization"),
    "github_pages_repo": DefaultSetting(settings.github_pages_repo, "GitHub Pages repository name"),
    "github_pages_branch": DefaultSetting(settings.github_pages_branch, "GitHub Pages upload branch"),
    "github_pages_token": DefaultSetting(settings.github_pages_token, "GitHub personal access token", True),
    "github_pages_base_url": DefaultSetting(
        settings.github_pages_base_url,
        "GitHub Pages base URL. If empty, it is derived from owner/repo.",
    ),
    "github_pages_assets_dir": DefaultSetting(
        settings.github_pages_assets_dir,
        "Directory inside the GitHub Pages repository where public images are uploaded.",
    ),
    "cloudinary_cloud_name": DefaultSetting(settings.cloudinary_cloud_name, "Cloudinary cloud name"),
    "cloudinary_api_key": DefaultSetting(settings.cloudinary_api_key, "Cloudinary API key", True),
    "cloudinary_api_secret": DefaultSetting(settings.cloudinary_api_secret, "Cloudinary API secret", True),
    "cloudinary_folder": DefaultSetting(settings.cloudinary_folder, "Cloudinary upload folder"),
    "openai_api_key": DefaultSetting(settings.openai_api_key, "OpenAI API key", True),
    "openai_admin_api_key": DefaultSetting(
        settings.openai_admin_api_key,
        "OpenAI Admin API key used for free-tier usage reporting",
        True,
    ),
    "openai_text_model": DefaultSetting(settings.openai_text_model, "기본 OpenAI 보조 텍스트 모델"),
    "article_generation_model": DefaultSetting(
        settings.article_generation_model,
        "장문 본문 생성과 리라이트에 쓰는 주력 OpenAI 모델",
    ),
    "openai_image_model": DefaultSetting(settings.openai_image_model, "Default OpenAI image model"),
    "openai_request_saver_mode": DefaultSetting(
        str(settings.openai_request_saver_mode).lower(),
        "Skip the extra image prompt refinement request when possible",
    ),
    "topic_discovery_provider": DefaultSetting(
        settings.topic_discovery_provider,
        "Topic discovery provider: openai or gemini",
    ),
    "topic_discovery_model": DefaultSetting(
        settings.topic_discovery_model,
        "Default topic discovery model when provider is OpenAI",
    ),
    "topic_discovery_max_topics_per_run": DefaultSetting(
        str(settings.topic_discovery_max_topics_per_run),
        "Maximum number of topics queued per discovery run. 0 means unlimited.",
    ),
    "gemini_api_key": DefaultSetting(settings.gemini_api_key, "Gemini API key", True),
    "gemini_model": DefaultSetting(settings.gemini_model, "Gemini model for topic discovery"),
    "gemini_daily_request_limit": DefaultSetting(
        str(settings.gemini_daily_request_limit),
        "Gemini daily request limit. 0 means unlimited.",
    ),
    "gemini_requests_per_minute_limit": DefaultSetting(
        str(settings.gemini_requests_per_minute_limit),
        "Gemini per-minute request limit. 0 means unlimited.",
    ),
    "pipeline_stop_after": DefaultSetting(settings.pipeline_stop_after, "Stop the pipeline after a given stage"),
    "blogger_client_name": DefaultSetting(settings.blogger_client_name, "Google OAuth client display name"),
    "blogger_client_id": DefaultSetting(settings.blogger_client_id, "Google OAuth client ID"),
    "blogger_client_secret": DefaultSetting(settings.blogger_client_secret, "Google OAuth client secret", True),
    "blogger_redirect_uri": DefaultSetting(settings.blogger_redirect_uri, "Google OAuth redirect URI"),
    "blogger_refresh_token": DefaultSetting(settings.blogger_refresh_token, "Google OAuth refresh token", True),
    "blogger_oauth_state": DefaultSetting(settings.blogger_oauth_state, "Google OAuth state", True),
    "blogger_access_token": DefaultSetting(settings.blogger_access_token, "Google OAuth access token", True),
    "blogger_access_token_expires_at": DefaultSetting(
        settings.blogger_access_token_expires_at,
        "Google OAuth access token expiry timestamp",
    ),
    "blogger_token_scope": DefaultSetting(settings.blogger_token_scope, "Granted Google OAuth scope"),
    "blogger_token_type": DefaultSetting(settings.blogger_token_type, "Google OAuth token type"),
    "blogger_playwright_enabled": DefaultSetting(
        str(settings.blogger_playwright_enabled).lower(),
        "Enable Playwright automation for Blogger search description sync",
    ),
    "blogger_playwright_auto_sync": DefaultSetting(
        str(settings.blogger_playwright_auto_sync).lower(),
        "Automatically sync Blogger search description after publish",
    ),
    "blogger_playwright_cdp_url": DefaultSetting(
        settings.blogger_playwright_cdp_url,
        "Remote debugging URL used by Playwright",
    ),
    "blogger_playwright_account_index": DefaultSetting(
        str(settings.blogger_playwright_account_index),
        "Account index used in the Blogger editor URL. Usually 0.",
    ),
    "telegram_bot_token": DefaultSetting(settings.telegram_bot_token, "Telegram bot token", True),
    "telegram_chat_id": DefaultSetting(settings.telegram_chat_id, "Telegram chat ID", True),
    "cloudflare_channel_enabled": DefaultSetting(
        str(settings.cloudflare_channel_enabled).lower(),
        "Cloudflare 채널 연동 사용 여부",
    ),
    "cloudflare_blog_api_base_url": DefaultSetting(
        settings.cloudflare_blog_api_base_url,
        "Cloudflare 연동 API 기본 주소. 예: https://api.dongriarchive.com",
    ),
    "cloudflare_blog_m2m_token": DefaultSetting(
        settings.cloudflare_blog_m2m_token,
        "Cloudflare integration Bearer 토큰",
        True,
    ),
    "google_sheet_url": DefaultSetting(
        settings.google_sheet_url,
        "Google Sheets URL used for weekly blog snapshot sync.",
    ),
    "google_sheet_id": DefaultSetting(
        settings.google_sheet_id,
        "Derived Google Sheets document id. Usually filled automatically from google_sheet_url.",
    ),
    "google_sheet_travel_tab": DefaultSetting(
        settings.google_sheet_travel_tab,
        "Tab name used for Korea travel snapshot rows.",
    ),
    "google_sheet_mystery_tab": DefaultSetting(
        settings.google_sheet_mystery_tab,
        "Tab name used for mystery snapshot rows.",
    ),
    "sheet_sync_enabled": DefaultSetting(
        str(settings.sheet_sync_enabled).lower(),
        "Enable weekly Google Sheets snapshot sync.",
    ),
    "sheet_sync_day": DefaultSetting(
        settings.sheet_sync_day,
        "Weekly Google Sheets sync day. Example: SUNDAY.",
    ),
    "sheet_sync_time": DefaultSetting(
        settings.sheet_sync_time,
        "Weekly Google Sheets sync time in HH:MM format.",
    ),
    "last_sheet_sync_on": DefaultSetting(
        settings.last_sheet_sync_on,
        "Last successful Google Sheets sync date (YYYY-MM-DD).",
    ),
    "default_publish_mode": DefaultSetting(settings.default_publish_mode, "Default publish mode"),
    "schedule_enabled": DefaultSetting(str(settings.schedule_enabled).lower(), "Enable the automatic scheduler"),
    "schedule_time": DefaultSetting(settings.schedule_time, "Scheduler run time in HH:MM format"),
    "schedule_timezone": DefaultSetting(settings.schedule_timezone, "Scheduler timezone"),
    "last_schedule_run_on": DefaultSetting("", "Last successful scheduler run date"),
    "training_schedule_enabled": DefaultSetting("false", "Enable daily scheduled training session"),
    "training_schedule_time": DefaultSetting("03:00", "Daily training schedule time in HH:MM format"),
    "training_schedule_timezone": DefaultSetting("Asia/Seoul", "Timezone for daily training schedule"),
    "training_schedule_last_run_on": DefaultSetting("", "Last date when scheduled training attempted"),
    "publish_daily_limit_per_blog": DefaultSetting("3", "Daily publish limit per blog"),
    "publish_min_interval_seconds": DefaultSetting(
        str(settings.publish_min_interval_seconds),
        "Minimum interval between Blogger publish requests for the same blog",
    ),
    "same_cluster_cooldown_hours": DefaultSetting("24", "Cooldown for repeating the same topic cluster"),
    "same_angle_cooldown_days": DefaultSetting("7", "Cooldown for repeating the same topic angle"),
    "topic_guard_enabled": DefaultSetting("true", "Enable topic memory based publish guard"),
    "travel_research_mode": DefaultSetting(
        settings.travel_research_mode,
        "Travel fact-check mode: hybrid, prompt_only, validate, or off.",
    ),
}

GOOGLE_SHEET_ID_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def _extract_google_sheet_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = GOOGLE_SHEET_ID_PATTERN.search(raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", raw):
        return raw
    return ""


def ensure_default_settings(db: Session) -> None:
    existing = {item.key: item for item in db.execute(select(Setting)).scalars().all()}
    changed = False
    for key, default in DEFAULT_SETTINGS.items():
        item = existing.get(key)
        if item:
            if item.description != default.description:
                item.description = default.description
                changed = True
            if item.is_secret != default.is_secret:
                item.is_secret = default.is_secret
                changed = True
            if item.is_secret and item.value and not is_encrypted_secret(item.value):
                item.value = encrypt_secret_value(item.value)
                changed = True
            continue
        db.add(
            Setting(
                key=key,
                value=encrypt_secret_value(default.value) if default.is_secret and default.value else default.value,
                description=default.description,
                is_secret=default.is_secret,
            )
        )
        changed = True
    if changed:
        db.commit()


def get_settings_map(db: Session) -> dict[str, str]:
    ensure_default_settings(db)
    items = db.execute(select(Setting).order_by(Setting.key.asc())).scalars().all()
    return {item.key: decrypt_secret_value(item.value) if item.is_secret else item.value for item in items}


def list_settings(db: Session) -> list[Setting]:
    ensure_default_settings(db)
    return db.execute(select(Setting).order_by(Setting.key.asc())).scalars().all()


def upsert_settings(db: Session, values: dict[str, str]) -> list[Setting]:
    ensure_default_settings(db)
    normalized_values = dict(values)
    if "google_sheet_url" in normalized_values:
        normalized_values["google_sheet_id"] = _extract_google_sheet_id(normalized_values.get("google_sheet_url", ""))
    existing = {item.key: item for item in db.execute(select(Setting)).scalars().all()}
    for key, value in normalized_values.items():
        if key in existing:
            if existing[key].is_secret and not str(value).strip():
                continue
            existing[key].value = encrypt_secret_value(value) if existing[key].is_secret else value
            continue
        meta = DEFAULT_SETTINGS.get(key, DefaultSetting("", "User-defined setting"))
        db.add(
            Setting(
                key=key,
                value=encrypt_secret_value(value) if meta.is_secret else value,
                description=meta.description,
                is_secret=meta.is_secret,
            )
        )
    db.commit()
    return list_settings(db)


def get_blogger_config(db: Session) -> dict:
    from app.services.blog_service import list_blog_profiles, list_blogs

    values = get_settings_map(db)
    blogs = list_blogs(db)
    return {
        "client_name": values.get("blogger_client_name", ""),
        "client_id_configured": bool(values.get("blogger_client_id", "").strip()),
        "client_secret_configured": bool(values.get("blogger_client_secret", "").strip()),
        "access_token_configured": bool(values.get("blogger_access_token", "").strip()),
        "refresh_token_configured": bool(values.get("blogger_refresh_token", "").strip()),
        "redirect_uri": values.get("blogger_redirect_uri", ""),
        "default_publish_mode": values.get("default_publish_mode", settings.default_publish_mode),
        "profiles": list_blog_profiles(),
        "imported_blogger_blog_ids": [blog.blogger_blog_id for blog in blogs if (blog.blogger_blog_id or "").strip()],
        "blogs": [
            {
                "id": blog.id,
                "name": blog.name,
                "blogger_blog_id": blog.blogger_blog_id or "",
                "blogger_url": blog.blogger_url or "",
                "search_console_site_url": blog.search_console_site_url or "",
                "ga4_property_id": blog.ga4_property_id or "",
                "publish_mode": blog.publish_mode.value,
                "is_active": blog.is_active,
            }
            for blog in blogs
        ],
    }
