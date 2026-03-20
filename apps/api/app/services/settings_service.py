from __future__ import annotations

from dataclasses import dataclass

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
        "Public image delivery provider. Recommended default is cloudflare_r2.",
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
        "Cloudflare custom image domain base URL. Example: https://img.example.com",
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
    "openai_text_model": DefaultSetting(settings.openai_text_model, "Default OpenAI text model"),
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
    "default_publish_mode": DefaultSetting(settings.default_publish_mode, "Default publish mode"),
    "schedule_enabled": DefaultSetting(str(settings.schedule_enabled).lower(), "Enable the automatic scheduler"),
    "schedule_time": DefaultSetting(settings.schedule_time, "Scheduler run time in HH:MM format"),
    "schedule_timezone": DefaultSetting(settings.schedule_timezone, "Scheduler timezone"),
    "last_schedule_run_on": DefaultSetting("", "Last successful scheduler run date"),
    "publish_daily_limit_per_blog": DefaultSetting("3", "Daily publish limit per blog"),
    "publish_min_interval_seconds": DefaultSetting(
        str(settings.publish_min_interval_seconds),
        "Minimum interval between Blogger publish requests for the same blog",
    ),
    "same_cluster_cooldown_hours": DefaultSetting("24", "Cooldown for repeating the same topic cluster"),
    "same_angle_cooldown_days": DefaultSetting("7", "Cooldown for repeating the same topic angle"),
    "topic_guard_enabled": DefaultSetting("true", "Enable topic memory based publish guard"),
}


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
    existing = {item.key: item for item in db.execute(select(Setting)).scalars().all()}
    for key, value in values.items():
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
