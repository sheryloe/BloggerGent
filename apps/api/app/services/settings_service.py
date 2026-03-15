from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Blog, Setting
from app.services.secret_service import decrypt_secret_value, encrypt_secret_value, is_encrypted_secret


@dataclass(slots=True)
class DefaultSetting:
    value: str
    description: str
    is_secret: bool = False


DEFAULT_SETTINGS: dict[str, DefaultSetting] = {
    "provider_mode": DefaultSetting(settings.provider_mode, "mock 또는 live 중 실제 공급자 사용 모드"),
    "public_image_provider": DefaultSetting(
        settings.public_image_provider,
        "대표 이미지를 공개 URL로 노출하는 방식. local 또는 cloudinary",
    ),
    "public_asset_base_url": DefaultSetting(
        settings.public_asset_base_url,
        "local 저장 파일을 외부에서 볼 수 있는 공개 베이스 URL. 예: https://your-domain.com",
    ),
    "github_pages_owner": DefaultSetting(settings.github_pages_owner, "GitHub Pages owner 또는 조직명"),
    "github_pages_repo": DefaultSetting(settings.github_pages_repo, "GitHub Pages 저장소 이름"),
    "github_pages_branch": DefaultSetting(settings.github_pages_branch, "GitHub Pages 업로드 대상 브랜치"),
    "github_pages_token": DefaultSetting(settings.github_pages_token, "GitHub Personal Access Token", True),
    "github_pages_base_url": DefaultSetting(
        settings.github_pages_base_url,
        "GitHub Pages 공개 베이스 URL. 비우면 owner/repo로 자동 계산",
    ),
    "github_pages_assets_dir": DefaultSetting(
        settings.github_pages_assets_dir,
        "GitHub Pages 저장소 안에서 이미지를 쌓을 폴더. 날짜별 하위 폴더가 자동으로 붙습니다.",
    ),
    "cloudinary_cloud_name": DefaultSetting(settings.cloudinary_cloud_name, "Cloudinary Cloud Name"),
    "cloudinary_api_key": DefaultSetting(settings.cloudinary_api_key, "Cloudinary API Key", True),
    "cloudinary_api_secret": DefaultSetting(settings.cloudinary_api_secret, "Cloudinary API Secret", True),
    "cloudinary_folder": DefaultSetting(settings.cloudinary_folder, "Cloudinary 업로드 폴더명"),
    "openai_api_key": DefaultSetting(settings.openai_api_key, "OpenAI API 키", True),
    "openai_text_model": DefaultSetting(settings.openai_text_model, "본문 생성에 사용할 OpenAI 텍스트 모델"),
    "openai_image_model": DefaultSetting(settings.openai_image_model, "대표 이미지 생성에 사용할 OpenAI 이미지 모델"),
    "openai_request_saver_mode": DefaultSetting(
        str(settings.openai_request_saver_mode).lower(),
        "켜면 이미지 프롬프트 전용 OpenAI 호출을 생략하고 본문 생성 결과의 최종 프롬프트를 바로 사용합니다.",
    ),
    "gemini_api_key": DefaultSetting(settings.gemini_api_key, "Gemini API 키", True),
    "gemini_model": DefaultSetting(settings.gemini_model, "주제 발굴에 사용할 Gemini 모델"),
    "gemini_daily_request_limit": DefaultSetting(
        str(settings.gemini_daily_request_limit),
        "Gemini 일일 최대 요청 수. 0이면 제한 없음",
    ),
    "gemini_requests_per_minute_limit": DefaultSetting(
        str(settings.gemini_requests_per_minute_limit),
        "Gemini 분당 최대 요청 수. 0이면 제한 없음",
    ),
    "pipeline_stop_after": DefaultSetting(
        settings.pipeline_stop_after,
        "파이프라인을 중간 종료할 단계. none이면 전체 실행",
    ),
    "blogger_client_name": DefaultSetting(settings.blogger_client_name, "Google OAuth 클라이언트 표시 이름"),
    "blogger_client_id": DefaultSetting(settings.blogger_client_id, "Google OAuth Client ID"),
    "blogger_client_secret": DefaultSetting(settings.blogger_client_secret, "Google OAuth Client Secret", True),
    "blogger_redirect_uri": DefaultSetting(settings.blogger_redirect_uri, "Google OAuth Redirect URI"),
    "blogger_refresh_token": DefaultSetting(settings.blogger_refresh_token, "Google OAuth Refresh Token", True),
    "blogger_oauth_state": DefaultSetting(settings.blogger_oauth_state, "Google OAuth state 값", True),
    "blogger_access_token": DefaultSetting(settings.blogger_access_token, "Google OAuth Access Token", True),
    "blogger_access_token_expires_at": DefaultSetting(
        settings.blogger_access_token_expires_at,
        "Google OAuth Access Token 만료 시각",
    ),
    "blogger_token_scope": DefaultSetting(settings.blogger_token_scope, "Google OAuth 승인 scope"),
    "blogger_token_type": DefaultSetting(settings.blogger_token_type, "Google OAuth token type"),
    "default_publish_mode": DefaultSetting(settings.default_publish_mode, "새 작업의 기본 발행 모드"),
    "schedule_enabled": DefaultSetting(str(settings.schedule_enabled).lower(), "매일 자동 스케줄 실행 여부"),
    "schedule_time": DefaultSetting(settings.schedule_time, "자동 실행 시각. HH:MM 형식"),
    "schedule_timezone": DefaultSetting(settings.schedule_timezone, "자동 실행 기준 시간대"),
    "last_schedule_run_on": DefaultSetting("", "마지막 자동 실행 성공 날짜"),
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
        meta = DEFAULT_SETTINGS.get(key, DefaultSetting("", "사용자 정의 설정"))
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
