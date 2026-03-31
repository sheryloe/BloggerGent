from __future__ import annotations

import logging
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import ModelPolicyRead, OpenAIFreeUsageRead, SettingItem, SettingUpdate
from app.services.blog_service import list_blog_profiles
from app.services.blogger_oauth_service import (
    BloggerOAuthError,
    build_blogger_authorization_url,
    exchange_blogger_code,
    get_blogger_redirect_uri,
    get_blogger_web_return_url,
    get_google_oauth_scopes,
    get_granted_google_scopes,
    list_blogger_blogs,
)
from app.services.blogger_sync_service import sync_connected_blogger_posts
from app.services.google_reporting_service import list_analytics_properties, list_search_console_sites
from app.services.model_policy_service import build_model_policy, validate_text_settings_payload
from app.services.openai_usage_service import get_openai_free_usage
from app.services.providers.base import ProviderRuntimeError
from app.services.settings_service import get_blogger_config, get_settings_map, list_settings, upsert_settings
from app.services.storage_service import is_private_asset_url

router = APIRouter()
blogger_router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_int_setting(values: dict[str, str], key: str, *, minimum: int, maximum: int, allow_zero: bool = False) -> None:
    if key not in values:
        return
    raw_value = (values.get(key) or "").strip()
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{key} must be an integer") from exc
    if allow_zero and parsed == 0:
        return
    if parsed < minimum or parsed > maximum:
        raise HTTPException(status_code=422, detail=f"{key} must be between {minimum} and {maximum}")


def _cloudflare_direct_upload_ready(values: dict[str, str]) -> bool:
    return all(
        (
            (values.get("cloudflare_account_id") or "").strip(),
            (values.get("cloudflare_r2_bucket") or "").strip(),
            (values.get("cloudflare_r2_access_key_id") or "").strip(),
            (values.get("cloudflare_r2_secret_access_key") or "").strip(),
        )
    )


def _cloudflare_integration_upload_ready(values: dict[str, str]) -> bool:
    return all(
        (
            (values.get("cloudflare_blog_api_base_url") or "").strip(),
            (values.get("cloudflare_blog_m2m_token") or "").strip(),
        )
    )


def _cloudflare_public_base_url(values: dict[str, str]) -> str:
    configured_public_base_url = (values.get("cloudflare_r2_public_base_url") or "").strip()
    if configured_public_base_url:
        return configured_public_base_url

    integration_base_url = (values.get("cloudflare_blog_api_base_url") or "").strip().rstrip("/")
    if integration_base_url:
        return f"{integration_base_url}/assets"
    return ""


@router.get("", response_model=list[SettingItem])
def get_settings(db: Session = Depends(get_db)):
    return [
        SettingItem(
            key=item.key,
            value="" if item.is_secret else item.value,
            description=item.description,
            is_secret=item.is_secret,
        )
        for item in list_settings(db)
    ]


@router.put("", response_model=list[SettingItem])
def update_settings(payload: SettingUpdate, db: Session = Depends(get_db)):
    _parse_int_setting(payload.values, "topic_discovery_max_topics_per_run", minimum=1, maximum=20, allow_zero=True)
    _parse_int_setting(payload.values, "publish_min_interval_seconds", minimum=0, maximum=3600)
    _parse_int_setting(payload.values, "travel_schedule_interval_hours", minimum=1, maximum=24)
    _parse_int_setting(payload.values, "travel_topics_per_run", minimum=1, maximum=5)
    _parse_int_setting(payload.values, "mystery_schedule_interval_hours", minimum=1, maximum=24)
    _parse_int_setting(payload.values, "mystery_topics_per_run", minimum=1, maximum=5)
    _parse_int_setting(payload.values, "cloudflare_daily_publish_interval_hours", minimum=1, maximum=24)
    _parse_int_setting(payload.values, "cloudflare_daily_publish_weekday_quota", minimum=0, maximum=24)
    _parse_int_setting(payload.values, "cloudflare_daily_publish_sunday_quota", minimum=0, maximum=24)
    try:
        validate_text_settings_payload(payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        SettingItem(
            key=item.key,
            value="" if item.is_secret else item.value,
            description=item.description,
            is_secret=item.is_secret,
        )
        for item in upsert_settings(db, payload.values)
    ]


@router.get("/openai-free-usage", response_model=OpenAIFreeUsageRead)
def get_openai_free_usage_route(db: Session = Depends(get_db)):
    try:
        return get_openai_free_usage(db)
    except ProviderRuntimeError as exc:
        status_code = exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 422, 429} else 502
        raise HTTPException(
            status_code=status_code,
            detail={
                "provider": exc.provider,
                "message": exc.message,
                "detail": exc.detail,
            },
        ) from exc


@router.get("/model-policy", response_model=ModelPolicyRead)
def get_model_policy_route():
    policy = build_model_policy()
    return ModelPolicyRead(
        large=policy.large,
        small=policy.small,
        deprecated=policy.deprecated,
        defaults=policy.defaults,
    )


def _append_public_image_warnings(values: dict[str, str], warnings: list[str]) -> None:
    public_image_provider = (values.get("public_image_provider") or "local").strip().lower()
    public_asset_base_url = (values.get("public_asset_base_url") or "").strip()

    if public_image_provider == "local":
        if not public_asset_base_url:
            warnings.append(
                "Local delivery is selected but public_asset_base_url is empty. Blogger posts will still point at a private URL."
            )
        elif is_private_asset_url(public_asset_base_url):
            warnings.append(
                "Local delivery base URL still looks private. Use a real public domain, Cloudflare R2, or Cloudinary before publishing."
            )
        return

    if public_image_provider == "cloudflare_r2":
        direct_ready = _cloudflare_direct_upload_ready(values)
        integration_ready = _cloudflare_integration_upload_ready(values)
        public_base_url = _cloudflare_public_base_url(values)

        if not direct_ready and not integration_ready:
            warnings.append(
                "Cloudflare R2를 선택했지만 직접 업로드용 계정 정보 또는 연동 API 주소/토큰이 비어 있습니다."
            )
        if not public_base_url:
            warnings.append(
                "Cloudflare 공개 이미지 기준 URL이 없습니다. 권장값은 https://img.example.com 이며, integration 업로드를 쓰면 cloudflare_blog_api_base_url + /assets 가 기본값으로 사용됩니다."
            )
        elif is_private_asset_url(public_base_url):
            warnings.append(
                "Cloudflare 공개 이미지 URL이 아직 사설 주소로 보입니다. 외부에서 열리는 https://img.<domain> 또는 공개 자산 도메인을 사용해야 합니다."
            )
        else:
            hostname = (urlparse(public_base_url).hostname or "").lower()
            if hostname and not hostname.startswith("img."):
                warnings.append(
                    "현재 공개 이미지 호스트가 img.<domain> 전용 서브도메인은 아닙니다. 동작은 가능하지만 변환 캐시와 규칙 분리를 위해 img.<domain> 구성을 권장합니다."
                )
        warnings.append(
            "참고: 원본 파일만 Cloudflare에 올린다고 이미지 최적화가 적용되지는 않습니다. 실제 렌더링 HTML이 /cdn-cgi/image 변환 URL을 사용해야 hero/card/thumb 성능이 개선됩니다."
        )
        return

    if public_image_provider == "github_pages":
        github_base_url = (values.get("github_pages_base_url") or "").strip()
        github_owner = (values.get("github_pages_owner") or "").strip()
        github_repo = (values.get("github_pages_repo") or "").strip()
        github_token = (values.get("github_pages_token") or "").strip()
        if not github_owner or not github_repo or not github_token:
            warnings.append("GitHub Pages is selected but owner, repo, or token is missing.")
        if github_base_url and is_private_asset_url(github_base_url):
            warnings.append(
                "GitHub Pages base URL still looks private. Check that it points to a public https://username.github.io/... address."
            )
        warnings.append(
            "Deleting old GitHub Pages assets later will break images inside existing Blogger posts that still reference those URLs."
        )
        return

    if public_image_provider == "cloudinary":
        if not (
            (values.get("cloudinary_cloud_name") or "").strip()
            and (values.get("cloudinary_api_key") or "").strip()
            and (values.get("cloudinary_api_secret") or "").strip()
        ):
            warnings.append("Cloudinary is selected but cloud name, API key, or API secret is missing.")
        warnings.append(
            "Cloudinary optimization only becomes real when rendered HTML uses transformation URLs instead of the original secure_url."
        )


@blogger_router.get("/config")
def get_blogger_settings(db: Session = Depends(get_db)) -> dict:
    values = get_settings_map(db)
    config = get_blogger_config(db)
    config["oauth_scopes"] = get_google_oauth_scopes()
    config["granted_scopes"] = get_granted_google_scopes(values)
    config["profiles"] = list_blog_profiles()
    config["imported_blogger_blog_ids"] = [
        blog["blogger_blog_id"] for blog in config.get("blogs", []) if (blog.get("blogger_blog_id") or "").strip()
    ]
    config["search_console_sites"] = []
    config["analytics_properties"] = []
    config["warnings"] = []
    _append_public_image_warnings(values, config["warnings"])

    try:
        config["redirect_uri"] = get_blogger_redirect_uri(values)
        config["authorization_url"] = build_blogger_authorization_url(db)
    except BloggerOAuthError as exc:
        config["authorization_url"] = None
        config["authorization_error"] = exc.detail
        config["warnings"].append(exc.detail)

    try:
        config["available_blogs"] = list_blogger_blogs(db)
        config["connected"] = True
    except BloggerOAuthError as exc:
        config["available_blogs"] = []
        config["connected"] = False
        config["connection_error"] = exc.detail
        config["warnings"].append(exc.detail)

    if config["connected"]:
        try:
            config["search_console_sites"] = list_search_console_sites(db)
        except BloggerOAuthError as exc:
            config["warnings"].append(f"Failed to load Search Console sites: {exc.detail}")
        try:
            config["analytics_properties"] = list_analytics_properties(db)
        except BloggerOAuthError as exc:
            config["warnings"].append(f"Failed to load GA4 properties: {exc.detail}")

    return config


@blogger_router.put("/config")
def update_blogger_settings(payload: SettingUpdate, db: Session = Depends(get_db)) -> dict:
    settings_items = upsert_settings(db, payload.values)
    return {item.key: ("" if item.is_secret else item.value) for item in settings_items if item.key in payload.values}


@blogger_router.get("/oauth/start")
def start_blogger_oauth(db: Session = Depends(get_db)):
    try:
        authorization_url = build_blogger_authorization_url(db)
    except BloggerOAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return RedirectResponse(url=authorization_url, status_code=307)


@blogger_router.get("/oauth/callback")
def complete_blogger_oauth(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    base_url = get_blogger_web_return_url()
    if error:
        return RedirectResponse(url=f"{base_url}?{urlencode({'blogger_oauth': 'error', 'message': error})}", status_code=307)
    if not code:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'blogger_oauth': 'error', 'message': 'missing_code'})}",
            status_code=307,
        )

    try:
        exchange_blogger_code(db, code=code, state=state)
    except BloggerOAuthError as exc:
        return RedirectResponse(
            url=f"{base_url}?{urlencode({'blogger_oauth': 'error', 'message': exc.detail})}",
            status_code=307,
        )

    sync_warnings = sync_connected_blogger_posts(db)
    if sync_warnings:
        logger.warning("Blogger OAuth succeeded but synced post refresh had warnings: %s", " | ".join(sync_warnings))

    return RedirectResponse(url=f"{base_url}?blogger_oauth=success", status_code=307)


@blogger_router.get("/blogs")
def get_blogger_blog_list(db: Session = Depends(get_db)) -> dict:
    try:
        blogs = list_blogger_blogs(db)
    except BloggerOAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"items": blogs}
