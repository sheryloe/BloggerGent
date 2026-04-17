from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, load_only, selectinload

from app.models.entities import (
    AgentRun,
    AgentWorker,
    Blog,
    ContentItem,
    ManagedChannel,
    MetricFact,
    PlatformCredential,
    PublicationRecord,
)
from app.services.cloudflare.cloudflare_asset_policy import ensure_cloudflare_channel_metadata
from app.services.integrations.secret_service import decrypt_secret_value, encrypt_secret_value
from app.services.integrations.settings_service import get_settings_map

_MOJIBAKE_HINTS: tuple[str, ...] = ("�",)
_TRAVEL_PURPOSE_BY_LANGUAGE: dict[str, str] = {
    "ja": "일본인 여행자를 위해 한국 지역 여행지, 축제, 맛집, 문화, K-컬처 정보를 실용적으로 안내하는 블로그",
    "es": "스페인어권 여행자를 위해 한국 지역 여행지, 축제, 맛집, 문화, K-컬처 정보를 실용적으로 안내하는 블로그",
    "en": "해외 여행자를 위해 한국 지역 여행지, 축제, 맛집, 문화, K-컬처 정보를 실용적으로 안내하는 블로그",
}


@dataclass(frozen=True, slots=True)
class PlatformPromptStepDefinition:
    stage_type: str
    stage_label: str
    name: str
    role_name: str
    objective: str
    provider_hint: str
    provider_model: str


DEFAULT_CHANNELS: tuple[dict[str, object], ...] = (
    {
        "provider": "youtube",
        "channel_id": "youtube:main",
        "display_name": "YouTube Studio",
        "status": "attention",
        "capabilities": ["video_upload", "thumbnail", "analytics", "seo_feedback"],
        "oauth_state": "not_configured",
        "primary_category": "video",
        "purpose": "유튜브 장문 영상과 쇼츠 운영 채널",
    },
    {
        "provider": "instagram",
        "channel_id": "instagram:main",
        "display_name": "Instagram Studio",
        "status": "attention",
        "capabilities": ["image_post", "reel_queue", "insights", "playback_preview"],
        "oauth_state": "not_configured",
        "primary_category": "social",
        "purpose": "인스타그램 이미지와 릴스 발행 채널",
    },
)

DEFAULT_AGENT_PACKS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "blogger": (
        ("topic", "Topic Scout", "codex_cli", "gpt-5"),
        ("writer", "Writer", "claude_cli", "claude-sonnet"),
        ("image", "Image Director", "gemini_cli", "gemini-2.5-flash"),
        ("seo", "SEO Analyst", "codex_cli", "gpt-5"),
        ("publisher", "Publisher", "codex_cli", "gpt-5"),
        ("analyst", "Performance Analyst", "claude_cli", "claude-sonnet"),
    ),
    "youtube": (
        ("metadata", "Metadata Writer", "claude_cli", "claude-sonnet"),
        ("thumbnail", "Thumbnail Director", "gemini_cli", "gemini-2.5-flash"),
        ("uploader", "Video Uploader", "codex_cli", "gpt-5"),
        ("seo", "YouTube SEO Analyst", "codex_cli", "gpt-5"),
        ("analyst", "Audience Analyst", "claude_cli", "claude-sonnet"),
    ),
    "instagram": (
        ("caption", "Caption Writer", "claude_cli", "claude-sonnet"),
        ("image", "Image Stylist", "gemini_cli", "gemini-2.5-flash"),
        ("reels", "Reels Packager", "codex_cli", "gpt-5"),
        ("publisher", "Instagram Publisher", "codex_cli", "gpt-5"),
        ("analyst", "Engagement Analyst", "claude_cli", "claude-sonnet"),
    ),
}

PLATFORM_PROMPT_STEPS: dict[str, tuple[PlatformPromptStepDefinition, ...]] = {
    "youtube": (
        PlatformPromptStepDefinition(
            stage_type="video_metadata_generation",
            stage_label="영상 메타데이터",
            name="유튜브 메타데이터 에이전트",
            role_name="유튜브 메타데이터 에이전트",
            objective="제목, 설명, 태그, 챕터 초안을 생성합니다.",
            provider_hint="claude_cli",
            provider_model="claude-sonnet",
        ),
        PlatformPromptStepDefinition(
            stage_type="thumbnail_generation",
            stage_label="썸네일 전략",
            name="썸네일 전략 에이전트",
            role_name="썸네일 전략 에이전트",
            objective="썸네일 카피와 레이아웃 지시를 만듭니다.",
            provider_hint="gemini_cli",
            provider_model="gemini-2.5-flash",
        ),
        PlatformPromptStepDefinition(
            stage_type="platform_publish",
            stage_label="플랫폼 게시",
            name="유튜브 발행 에이전트",
            role_name="유튜브 발행 에이전트",
            objective="업로드와 게시 상태 전환을 담당합니다.",
            provider_hint="codex_cli",
            provider_model="gpt-5",
        ),
        PlatformPromptStepDefinition(
            stage_type="performance_review",
            stage_label="성과 분석",
            name="유튜브 분석 에이전트",
            role_name="유튜브 분석 에이전트",
            objective="조회수, CTR, retention 기반 피드백을 제공합니다.",
            provider_hint="claude_cli",
            provider_model="claude-sonnet",
        ),
    ),
    "instagram": (
        PlatformPromptStepDefinition(
            stage_type="article_generation",
            stage_label="캡션 초안",
            name="인스타그램 캡션 에이전트",
            role_name="인스타그램 캡션 에이전트",
            objective="게시 캡션과 해시태그 초안을 생성합니다.",
            provider_hint="claude_cli",
            provider_model="claude-sonnet",
        ),
        PlatformPromptStepDefinition(
            stage_type="thumbnail_generation",
            stage_label="이미지/커버 전략",
            name="인스타그램 커버 에이전트",
            role_name="인스타그램 커버 에이전트",
            objective="피드 대표 이미지와 릴스 커버 지시를 생성합니다.",
            provider_hint="gemini_cli",
            provider_model="gemini-2.5-flash",
        ),
        PlatformPromptStepDefinition(
            stage_type="reel_packaging",
            stage_label="릴스 패키징",
            name="릴스 패키징 에이전트",
            role_name="릴스 패키징 에이전트",
            objective="릴스 자막/설명/미디어 패키징을 준비합니다.",
            provider_hint="codex_cli",
            provider_model="gpt-5",
        ),
        PlatformPromptStepDefinition(
            stage_type="platform_publish",
            stage_label="플랫폼 게시",
            name="인스타그램 발행 에이전트",
            role_name="인스타그램 발행 에이전트",
            objective="이미지/릴스 게시 큐를 관리합니다.",
            provider_hint="codex_cli",
            provider_model="gpt-5",
        ),
        PlatformPromptStepDefinition(
            stage_type="performance_review",
            stage_label="성과 분석",
            name="인스타그램 분석 에이전트",
            role_name="인스타그램 분석 에이전트",
            objective="도달/참여/탭별 인사이트를 분석합니다.",
            provider_hint="claude_cli",
            provider_model="claude-sonnet",
        ),
    ),
}


def _looks_corrupted_text(value: str | None) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return True
    if raw.count("?") >= 3:
        return True
    return any(token in raw for token in _MOJIBAKE_HINTS)


def _safe_text(value: str | None, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if _looks_corrupted_text(raw):
        return str(fallback).strip() or ""
    return raw


def _safe_display_name(value: str | None, *, fallback: str) -> str:
    return _safe_text(value, fallback=fallback or "Channel") or "Channel"


def _humanize_channel_label(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = [part for part in raw.replace("_", "-").split("-") if part]
    if not parts:
        return ""
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def _blogger_fallback_display_name(blog: Blog) -> str:
    slug_label = _humanize_channel_label(blog.slug)
    host_label = ""
    parsed = urlparse(str(blog.blogger_url or "").strip())
    if parsed.netloc:
        host_label = parsed.netloc.strip().lower()
        if host_label.startswith("www."):
            host_label = host_label[4:]

    if slug_label and host_label:
        return f"{slug_label} ({host_label})"
    if slug_label:
        return slug_label
    if host_label:
        return host_label
    return f"Blogger Channel {blog.id}"


def resolve_blogger_channel_display_name(blog: Blog) -> str:
    return _safe_display_name(blog.name, fallback=_blogger_fallback_display_name(blog))


def _blog_audience_label_ko(blog: Blog) -> str:
    language = str(blog.primary_language or "").strip().lower()
    if language.startswith("ja"):
        return "일본인"
    if language.startswith("es"):
        return "스페인어권 독자"
    if language.startswith("en"):
        return "해외 독자"
    return "독자"


def _blogger_purpose_fallback(blog: Blog) -> str:
    profile_key = str(blog.profile_key or "").strip().lower()
    category = str(blog.content_category or "").strip().lower()

    if profile_key == "korea_travel" or "travel" in category:
        language = str(blog.primary_language or "").strip().lower()
        if language.startswith("ja"):
            return _TRAVEL_PURPOSE_BY_LANGUAGE["ja"]
        if language.startswith("es"):
            return _TRAVEL_PURPOSE_BY_LANGUAGE["es"]
        return _TRAVEL_PURPOSE_BY_LANGUAGE["en"]

    if profile_key == "world_mystery" or "mystery" in category:
        return f"{_blog_audience_label_ko(blog)}를 위해 세계 미스터리, 다큐, 전설, 사건 아카이브를 정리해 소개하는 블로그"

    category_label = str(blog.content_category or "운영").strip() or "운영"
    return f"{_blog_audience_label_ko(blog)}를 위해 {category_label} 정보를 이해하기 쉽게 정리해 제공하는 블로그"


def _resolve_blogger_channel_purpose(blog: Blog) -> str:
    return _safe_text(blog.content_brief, fallback=_blogger_purpose_fallback(blog))


def _channel_purpose_fallback(channel: ManagedChannel) -> str:
    if channel.provider == "blogger":
        return "운영 목적 정보가 아직 정리되지 않아 기본 안내 문구를 표시합니다."
    if channel.provider == "youtube":
        return "유튜브 장문 영상과 쇼츠 운영 채널"
    if channel.provider == "instagram":
        return "인스타그램 이미지와 릴스 운영 채널"
    if channel.provider == "cloudflare":
        return "Cloudflare 아카이브 게시 및 보관 채널"
    return "운영 목적 정보가 아직 정리되지 않았습니다."


def _channel_query():
    return (
        select(ManagedChannel)
        .options(
            selectinload(ManagedChannel.credentials),
            selectinload(ManagedChannel.content_items).load_only(ContentItem.lifecycle_status),
            selectinload(ManagedChannel.agent_workers).load_only(AgentWorker.role_name, AgentWorker.status),
            selectinload(ManagedChannel.agent_runs).load_only(AgentRun.id),
            selectinload(ManagedChannel.publication_records).load_only(PublicationRecord.id),
            selectinload(ManagedChannel.linked_blog).load_only(Blog.id),
        )
        .order_by(ManagedChannel.created_at.asc(), ManagedChannel.id.asc())
    )


def _ensure_default_agent_pack(db: Session, channel: ManagedChannel) -> None:
    definitions = DEFAULT_AGENT_PACKS.get(channel.provider, ())
    if not definitions:
        return

    existing = {worker.worker_key for worker in channel.agent_workers}
    changed = False
    for index, (role_name, display_name, runtime_kind, provider_model) in enumerate(definitions, start=1):
        worker_key = f"{channel.channel_id}:{role_name}:{index}"
        if worker_key in existing:
            continue
        db.add(
            AgentWorker(
                managed_channel_id=channel.id,
                worker_key=worker_key,
                display_name=display_name,
                role_name=role_name,
                runtime_kind=runtime_kind,
                queue_name=f"{channel.provider}.{role_name}",
                concurrency_limit=2 if channel.provider in {"youtube", "instagram"} else 1,
                status="idle",
                config_payload={"provider_model": provider_model},
            )
        )
        changed = True
    if changed:
        db.flush()


def _blog_channel_should_exist(blog: Blog | None) -> bool:
    if blog is None:
        return False
    return bool(blog.is_active) and bool((blog.blogger_blog_id or "").strip())


def _channel_has_runtime_activity(channel: ManagedChannel) -> bool:
    return bool(channel.publication_records or channel.content_items or channel.agent_runs)


def _channel_is_operational(channel: ManagedChannel) -> bool:
    if not channel.is_enabled:
        return False

    provider = str(channel.provider or "").strip().lower()
    if provider == "blogger":
        return _blog_channel_should_exist(channel.linked_blog)
    if provider == "cloudflare":
        return bool((channel.base_url or "").strip())
    if provider in {"youtube", "instagram"}:
        return channel.oauth_state == "connected" or _channel_has_runtime_activity(channel)
    return True


def ensure_managed_channels(db: Session) -> list[ManagedChannel]:
    existing = {
        channel.channel_id: channel
        for channel in db.execute(_channel_query()).scalars().unique().all()
    }
    changed = False

    blogs = db.execute(select(Blog).order_by(Blog.created_at.asc(), Blog.id.asc())).scalars().all()
    for blog in blogs:
        if not _blog_channel_should_exist(blog):
            continue
        channel_id = f"blogger:{blog.id}"
        channel = existing.get(channel_id)
        has_valid_credential = bool(channel and has_valid_channel_credential(channel, "blogger"))
        oauth_state = "connected" if has_valid_credential else "not_configured"
        status = "connected" if has_valid_credential else "attention"
        payload = {
            "provider": "blogger",
            "channel_id": channel_id,
            "display_name": resolve_blogger_channel_display_name(blog),
            "remote_resource_id": blog.blogger_blog_id or None,
            "linked_blog_id": blog.id,
            "status": status,
            "base_url": blog.blogger_url,
            "primary_category": blog.content_category,
            "purpose": _resolve_blogger_channel_purpose(blog),
            "capabilities": ["article_publish", "seo_feedback", "search_console", "ga4"],
            "oauth_state": oauth_state,
            "quota_state": {},
            "channel_metadata": {"profile_key": blog.profile_key},
            "is_enabled": bool(blog.is_active),
        }
        if channel is None:
            channel = ManagedChannel(**payload)
            db.add(channel)
            db.flush()
            existing[channel_id] = channel
            changed = True
        else:
            for key, value in payload.items():
                if getattr(channel, key) != value:
                    setattr(channel, key, value)
                    changed = True

        normalized_brief = _resolve_blogger_channel_purpose(blog)
        if str(blog.content_brief or "").strip() != normalized_brief:
            blog.content_brief = normalized_brief
            db.add(blog)
            changed = True

    stale_blogger_channels = [
        channel
        for channel in list(existing.values())
        if channel.provider == "blogger" and not _blog_channel_should_exist(channel.linked_blog)
    ]
    for channel in stale_blogger_channels:
        db.delete(channel)
        existing.pop(channel.channel_id, None)
        changed = True

    settings_values = get_settings_map(db)
    cloudflare_enabled = str(settings_values.get("cloudflare_channel_enabled") or "false").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }
    cloudflare_api_base_url = str(settings_values.get("cloudflare_blog_api_base_url") or "").strip().rstrip("/")
    cloudflare_public_base_url = str(settings_values.get("cloudflare_r2_public_base_url") or "").strip().rstrip("/")
    cloudflare_token_configured = bool(str(settings_values.get("cloudflare_blog_m2m_token") or "").strip())
    cloudflare_channel_id = "cloudflare:dongriarchive"
    cloudflare_channel = existing.get(cloudflare_channel_id)

    if cloudflare_enabled or cloudflare_channel is not None or cloudflare_api_base_url:
        cloudflare_is_connected = cloudflare_enabled and bool(cloudflare_api_base_url) and cloudflare_token_configured
        cloudflare_is_enabled = cloudflare_enabled and bool(cloudflare_api_base_url)
        cloudflare_base_url = cloudflare_public_base_url or (f"{cloudflare_api_base_url}/assets" if cloudflare_api_base_url else None)
        cloudflare_payload = {
            "provider": "cloudflare",
            "channel_id": cloudflare_channel_id,
            "display_name": "Dongri Archive",
            "remote_resource_id": "dongriarchive",
            "linked_blog_id": None,
            "status": "connected" if cloudflare_is_connected else "attention",
            "base_url": cloudflare_base_url,
            "primary_category": "archive",
            "purpose": "Cloudflare 아카이브 게시 및 보관 채널",
            "capabilities": ["archive_publish", "analytics", "seo_feedback", "indexing"],
            "oauth_state": "connected" if cloudflare_is_connected else "not_configured",
            "quota_state": {},
            "channel_metadata": ensure_cloudflare_channel_metadata(
                {
                    **dict(getattr(cloudflare_channel, "channel_metadata", {}) or {}),
                    "api_base_url": cloudflare_api_base_url or None,
                    "token_configured": cloudflare_token_configured,
                }
            ),
            "is_enabled": cloudflare_is_enabled,
        }
        if cloudflare_channel is None:
            cloudflare_channel = ManagedChannel(**cloudflare_payload)
            db.add(cloudflare_channel)
            db.flush()
            existing[cloudflare_channel_id] = cloudflare_channel
            changed = True
        else:
            for key, value in cloudflare_payload.items():
                if getattr(cloudflare_channel, key) != value:
                    setattr(cloudflare_channel, key, value)
                    changed = True

    for defaults in DEFAULT_CHANNELS:
        channel = existing.get(str(defaults["channel_id"]))
        if channel is None:
            channel = ManagedChannel(
                provider=str(defaults["provider"]),
                channel_id=str(defaults["channel_id"]),
                display_name=str(defaults["display_name"]),
                remote_resource_id=None,
                linked_blog_id=None,
                status=str(defaults["status"]),
                base_url=None,
                primary_category=str(defaults["primary_category"]),
                purpose=str(defaults["purpose"]),
                capabilities=list(defaults["capabilities"]),
                oauth_state=str(defaults["oauth_state"]),
                quota_state={},
                channel_metadata={},
                is_enabled=True,
            )
            db.add(channel)
            db.flush()
            existing[channel.channel_id] = channel
            changed = True
            continue

        oauth_state = "connected" if has_valid_channel_credential(channel, str(defaults["provider"])) else str(defaults["oauth_state"])
        status = "connected" if oauth_state == "connected" else str(defaults["status"])
        desired_capabilities = list(defaults["capabilities"])
        for capability in channel.capabilities or []:
            normalized = str(capability).strip()
            if normalized and normalized not in desired_capabilities:
                desired_capabilities.append(normalized)

        if channel.status != status:
            channel.status = status
            changed = True
        if channel.oauth_state != oauth_state:
            channel.oauth_state = oauth_state
            changed = True
        if channel.primary_category != str(defaults["primary_category"]):
            channel.primary_category = str(defaults["primary_category"])
            changed = True
        if channel.purpose != str(defaults["purpose"]):
            channel.purpose = str(defaults["purpose"])
            changed = True
        if list(channel.capabilities or []) != desired_capabilities:
            channel.capabilities = desired_capabilities
            changed = True
        if not channel.is_enabled:
            channel.is_enabled = True
            changed = True

    channels = db.execute(_channel_query()).scalars().unique().all()
    for channel in channels:
        _ensure_default_agent_pack(db, channel)

    if changed:
        db.commit()
        channels = db.execute(_channel_query()).scalars().unique().all()
    return channels


def list_managed_channels(db: Session, *, include_disconnected: bool = False) -> list[ManagedChannel]:
    channels = ensure_managed_channels(db)
    if include_disconnected:
        return channels
    return [channel for channel in channels if _channel_is_operational(channel)]


def get_managed_channel_by_channel_id(db: Session, channel_id: str) -> ManagedChannel | None:
    ensure_managed_channels(db)
    query = _channel_query().where(ManagedChannel.channel_id == str(channel_id).strip())
    return db.execute(query).scalar_one_or_none()


def get_channel_credential(channel: ManagedChannel, provider: str | None = None) -> PlatformCredential | None:
    target_provider = (provider or channel.provider or "").strip().lower()
    for credential in channel.credentials:
        if (credential.provider or "").strip().lower() == target_provider:
            return credential
    return None


def has_valid_channel_credential(channel: ManagedChannel, provider: str | None = None) -> bool:
    credential = get_channel_credential(channel, provider)
    if credential is None or not credential.is_valid:
        return False
    return bool(decrypt_secret_value(credential.access_token_encrypted))


def sync_managed_channel_state(
    db: Session,
    channel: ManagedChannel,
    *,
    oauth_state: str | None = None,
    status: str | None = None,
    remote_resource_id: str | None = None,
    base_url: str | None = None,
    display_name: str | None = None,
    capabilities: list[str] | None = None,
    quota_state: dict | None = None,
    metadata_updates: dict | None = None,
) -> ManagedChannel:
    if oauth_state is not None:
        channel.oauth_state = oauth_state
    if status is not None:
        channel.status = status
    if remote_resource_id is not None:
        channel.remote_resource_id = remote_resource_id
    if base_url is not None:
        channel.base_url = base_url
    if display_name is not None:
        channel.display_name = _safe_display_name(
            display_name,
            fallback=channel.display_name or channel.channel_id,
        )
    if capabilities is not None:
        channel.capabilities = capabilities
    if quota_state is not None:
        channel.quota_state = quota_state
    if metadata_updates:
        merged_metadata = dict(channel.channel_metadata or {})
        merged_metadata.update(metadata_updates)
        channel.channel_metadata = merged_metadata
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def list_platform_integrations(db: Session) -> list[dict]:
    channels = ensure_managed_channels(db)
    items: list[dict] = []
    for channel in channels:
        credential = next((item for item in channel.credentials if item.provider == channel.provider), None)
        items.append(
            {
                "provider": channel.provider,
                "channel_id": channel.channel_id,
                "display_name": channel.display_name,
                "oauth_state": channel.oauth_state,
                "status": channel.status,
                "scope_count": len(credential.scopes) if credential else 0,
                "expires_at": credential.expires_at if credential else None,
                "is_valid": bool(credential and credential.is_valid),
                "last_error": credential.last_error if credential else None,
            }
        )
    return items


def upsert_platform_credential(
    db: Session,
    *,
    channel: ManagedChannel,
    provider: str,
    credential_key: str,
    subject: str | None,
    scopes: list[str],
    access_token: str = "",
    refresh_token: str = "",
    expires_at: datetime | None = None,
    token_type: str = "Bearer",
    is_valid: bool = True,
    refresh_metadata: dict | None = None,
    last_error: str | None = None,
) -> PlatformCredential:
    record = next(
        (item for item in channel.credentials if item.provider == provider and item.credential_key == credential_key),
        None,
    )
    if record is None:
        record = PlatformCredential(
            managed_channel_id=channel.id,
            provider=provider,
            credential_key=credential_key,
            subject=subject,
            scopes=scopes,
            access_token_encrypted=encrypt_secret_value(access_token),
            refresh_token_encrypted=encrypt_secret_value(refresh_token),
            expires_at=expires_at,
            token_type=token_type,
            is_valid=is_valid,
            refresh_metadata=refresh_metadata or {},
            last_error=last_error,
        )
        db.add(record)
    else:
        record.subject = subject
        record.scopes = scopes
        record.access_token_encrypted = encrypt_secret_value(access_token)
        record.refresh_token_encrypted = encrypt_secret_value(refresh_token)
        record.expires_at = expires_at
        record.token_type = token_type
        record.is_valid = is_valid
        record.refresh_metadata = refresh_metadata or {}
        record.last_error = last_error
    db.commit()
    db.refresh(record)
    db.expire(channel, ["credentials"])
    return record


def serialize_platform_credential(record: PlatformCredential) -> dict:
    return {
        "id": record.id,
        "provider": record.provider,
        "credential_key": record.credential_key,
        "subject": record.subject,
        "scopes": list(record.scopes or []),
        "access_token_configured": bool(decrypt_secret_value(record.access_token_encrypted)),
        "refresh_token_configured": bool(decrypt_secret_value(record.refresh_token_encrypted)),
        "expires_at": record.expires_at,
        "token_type": record.token_type,
        "is_valid": record.is_valid,
        "last_error": record.last_error,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def list_content_items(
    db: Session,
    *,
    provider: str | None = None,
    channel_id: str | None = None,
    channel_ids: list[str] | None = None,
    lifecycle_status: str | None = None,
    content_type: str | None = None,
    limit: int = 50,
    ensure_channels: bool = True,
) -> list[ContentItem]:
    if ensure_channels:
        ensure_managed_channels(db)
    query = (
        select(ContentItem)
        .options(
            selectinload(ContentItem.managed_channel),
            selectinload(ContentItem.publication_records),
            selectinload(ContentItem.metric_facts),
            selectinload(ContentItem.agent_runs),
        )
        .order_by(ContentItem.created_at.desc(), ContentItem.id.desc())
        .limit(max(1, min(limit, 200)))
    )
    normalized_channel_ids = [str(item).strip() for item in (channel_ids or []) if str(item).strip()]
    if channel_id:
        query = query.join(ContentItem.managed_channel).where(ManagedChannel.channel_id == channel_id)
    elif normalized_channel_ids:
        query = query.join(ContentItem.managed_channel).where(ManagedChannel.channel_id.in_(normalized_channel_ids))
    elif provider:
        query = query.join(ContentItem.managed_channel).where(ManagedChannel.provider == provider)
    elif channel_ids is not None and not normalized_channel_ids:
        return []
    if lifecycle_status:
        query = query.where(ContentItem.lifecycle_status == lifecycle_status)
    if content_type:
        query = query.where(ContentItem.content_type == content_type)
    return db.execute(query).scalars().unique().all()


def create_content_item(
    db: Session,
    *,
    channel: ManagedChannel,
    content_type: str,
    title: str,
    description: str = "",
    body_text: str = "",
    asset_manifest: dict | None = None,
    brief_payload: dict | None = None,
    scheduled_for: datetime | None = None,
    created_by_agent: str | None = None,
    idempotency_key: str | None = None,
    lifecycle_status: str = "draft",
    blocked_reason: str | None = None,
) -> ContentItem:
    normalized_title = str(title or "").strip()
    normalized_description = str(description or "").strip()
    normalized_body = str(body_text or "").strip()
    normalized_schedule = scheduled_for.isoformat() if scheduled_for is not None else None
    normalized_agent = str(created_by_agent or "").strip()
    explicit_key = str(idempotency_key or "").strip()
    if explicit_key:
        resolved_idempotency_key = explicit_key[:120]
    else:
        raw = json.dumps(
            {
                "channel_id": channel.channel_id,
                "content_type": str(content_type or "").strip(),
                "title": normalized_title,
                "description": normalized_description,
                "body_text": normalized_body,
                "scheduled_for": normalized_schedule,
                "created_by_agent": normalized_agent,
                "asset_manifest": asset_manifest or {},
                "brief_payload": brief_payload or {},
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        resolved_idempotency_key = f"auto:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:48]}"

    existing = db.execute(
        select(ContentItem)
        .where(ContentItem.managed_channel_id == channel.id)
        .where(ContentItem.idempotency_key == resolved_idempotency_key)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    item = ContentItem(
        managed_channel_id=channel.id,
        idempotency_key=resolved_idempotency_key,
        blog_id=channel.linked_blog_id,
        content_type=content_type,
        lifecycle_status=lifecycle_status,
        title=title,
        description=description,
        body_text=body_text,
        asset_manifest=asset_manifest or {},
        brief_payload=brief_payload or {},
        scheduled_for=scheduled_for,
        blocked_reason=blocked_reason,
        created_by_agent=created_by_agent,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_content_item(
    db: Session,
    item: ContentItem,
    *,
    lifecycle_status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    body_text: str | None = None,
    approval_status: str | None = None,
    asset_manifest: dict | None = None,
    brief_payload: dict | None = None,
    review_notes: list | None = None,
    scheduled_for: datetime | None = None,
    last_feedback: str | None = None,
    blocked_reason: str | None = None,
    last_score: dict | None = None,
) -> ContentItem:
    if lifecycle_status is not None:
        item.lifecycle_status = lifecycle_status
    if title is not None:
        item.title = title
    if description is not None:
        item.description = description
    if body_text is not None:
        item.body_text = body_text
    if approval_status is not None:
        item.approval_status = approval_status
    if asset_manifest is not None:
        item.asset_manifest = asset_manifest
    if brief_payload is not None:
        item.brief_payload = brief_payload
    if review_notes is not None:
        item.review_notes = review_notes
    if scheduled_for is not None:
        item.scheduled_for = scheduled_for
    if last_feedback is not None:
        item.last_feedback = last_feedback
    if blocked_reason is not None:
        item.blocked_reason = blocked_reason
    if last_score is not None:
        item.last_score = last_score
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_agent_workers(
    db: Session,
    *,
    channel_id: str | None = None,
    channel_ids: list[str] | None = None,
    runtime_kind: str | None = None,
    ensure_channels: bool = True,
    include_unbound: bool = False,
) -> list[AgentWorker]:
    if ensure_channels:
        ensure_managed_channels(db)
    query = (
        select(AgentWorker)
        .options(selectinload(AgentWorker.managed_channel))
        .order_by(AgentWorker.created_at.asc(), AgentWorker.id.asc())
    )
    normalized_channel_ids = [str(item).strip() for item in (channel_ids or []) if str(item).strip()]
    if channel_id:
        query = query.join(AgentWorker.managed_channel).where(ManagedChannel.channel_id == channel_id)
    elif normalized_channel_ids:
        if include_unbound:
            query = query.outerjoin(AgentWorker.managed_channel).where(
                or_(ManagedChannel.channel_id.in_(normalized_channel_ids), AgentWorker.managed_channel_id.is_(None))
            )
        else:
            query = query.join(AgentWorker.managed_channel).where(ManagedChannel.channel_id.in_(normalized_channel_ids))
    elif channel_ids is not None and not normalized_channel_ids:
        if not include_unbound:
            return []
        query = query.where(AgentWorker.managed_channel_id.is_(None))
    if runtime_kind:
        query = query.where(AgentWorker.runtime_kind == runtime_kind)
    return db.execute(query).scalars().unique().all()


def create_agent_worker(
    db: Session,
    *,
    channel: ManagedChannel | None,
    worker_key: str,
    display_name: str,
    role_name: str,
    runtime_kind: str,
    queue_name: str,
    concurrency_limit: int,
    status: str = "idle",
    config_payload: dict | None = None,
) -> AgentWorker:
    worker = AgentWorker(
        managed_channel_id=channel.id if channel else None,
        worker_key=worker_key,
        display_name=display_name,
        role_name=role_name,
        runtime_kind=runtime_kind,
        queue_name=queue_name,
        concurrency_limit=max(1, concurrency_limit),
        status=status,
        config_payload=config_payload or {},
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def update_agent_worker(
    db: Session,
    worker: AgentWorker,
    *,
    status: str | None = None,
    concurrency_limit: int | None = None,
    config_payload: dict | None = None,
    last_heartbeat_at: datetime | None = None,
    last_error: str | None = None,
) -> AgentWorker:
    if status is not None:
        worker.status = status
    if concurrency_limit is not None:
        worker.concurrency_limit = max(1, concurrency_limit)
    if config_payload is not None:
        worker.config_payload = config_payload
    if last_heartbeat_at is not None:
        worker.last_heartbeat_at = last_heartbeat_at
    if last_error is not None:
        worker.last_error = last_error
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


def list_agent_runs(
    db: Session,
    *,
    channel_id: str | None = None,
    status: str | None = None,
    channel_ids: list[str] | None = None,
    limit: int = 100,
    ensure_channels: bool = True,
    include_unbound: bool = False,
) -> list[AgentRun]:
    if ensure_channels:
        ensure_managed_channels(db)
    query = (
        select(AgentRun)
        .options(
            selectinload(AgentRun.managed_channel),
            selectinload(AgentRun.worker),
            selectinload(AgentRun.content_item),
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(max(1, min(limit, 200)))
    )
    normalized_channel_ids = [str(item).strip() for item in (channel_ids or []) if str(item).strip()]
    if channel_id:
        query = query.join(AgentRun.managed_channel).where(ManagedChannel.channel_id == channel_id)
    elif normalized_channel_ids:
        if include_unbound:
            query = query.outerjoin(AgentRun.managed_channel).where(
                or_(ManagedChannel.channel_id.in_(normalized_channel_ids), AgentRun.managed_channel_id.is_(None))
            )
        else:
            query = query.join(AgentRun.managed_channel).where(ManagedChannel.channel_id.in_(normalized_channel_ids))
    elif channel_ids is not None and not normalized_channel_ids:
        if not include_unbound:
            return []
        query = query.where(AgentRun.managed_channel_id.is_(None))
    if status:
        query = query.where(AgentRun.status == status)
    return db.execute(query).scalars().unique().all()


def create_agent_run(
    db: Session,
    *,
    run_key: str,
    runtime_kind: str,
    assigned_role: str,
    managed_channel: ManagedChannel | None,
    content_item: ContentItem | None,
    worker: AgentWorker | None,
    provider_model: str | None = None,
    priority: int = 50,
    timeout_seconds: int = 900,
    prompt_snapshot: str = "",
    status: str = "queued",
) -> AgentRun:
    run = AgentRun(
        managed_channel_id=managed_channel.id if managed_channel else None,
        content_item_id=content_item.id if content_item else None,
        worker_id=worker.id if worker else None,
        run_key=run_key,
        runtime_kind=runtime_kind,
        assigned_role=assigned_role,
        provider_model=provider_model,
        status=status,
        priority=priority,
        timeout_seconds=timeout_seconds,
        prompt_snapshot=prompt_snapshot,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_agent_run(
    db: Session,
    run: AgentRun,
    *,
    status: str | None = None,
    retry_count: int | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    response_snapshot: str | None = None,
    log_lines: list | None = None,
    error_message: str | None = None,
) -> AgentRun:
    if status is not None:
        run.status = status
    if retry_count is not None:
        run.retry_count = max(0, retry_count)
    if started_at is not None:
        run.started_at = started_at
    if ended_at is not None:
        run.ended_at = ended_at
    if response_snapshot is not None:
        run.response_snapshot = response_snapshot
    if log_lines is not None:
        run.log_lines = log_lines
    if error_message is not None:
        run.error_message = error_message
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_agent_runtime_health(db: Session) -> dict:
    ensure_managed_channels(db)
    workers = list_agent_workers(db, ensure_channels=False)
    runs = list_agent_runs(db, limit=200, ensure_channels=False)
    worker_status = Counter(worker.status for worker in workers)
    run_status = Counter(run.status for run in runs)
    last_run = runs[0].created_at if runs else None
    return {
        "worker_count": len(workers),
        "run_count": len(runs),
        "worker_status": dict(worker_status),
        "run_status": dict(run_status),
        "last_run_at": last_run,
        "runtime_kinds": sorted({worker.runtime_kind for worker in workers}),
        "healthy": not bool(run_status.get("failed")) and not bool(worker_status.get("error")),
        "generated_at": datetime.now(UTC),
    }


def serialize_channel(channel: ManagedChannel) -> dict:
    role_counter = Counter(worker.role_name for worker in channel.agent_workers)
    pending_items = sum(
        1 for item in channel.content_items if item.lifecycle_status in {"draft", "review", "scheduled", "ready_to_publish", "blocked_asset"}
    )
    failed_items = sum(1 for item in channel.content_items if item.lifecycle_status in {"failed", "blocked"})
    live_workers = sum(1 for worker in channel.agent_workers if worker.status in {"busy", "running"})
    latest_credential = next((item for item in channel.credentials if item.provider == channel.provider), None)
    return {
        "provider": channel.provider,
        "channel_id": channel.channel_id,
        "name": _safe_display_name(channel.display_name, fallback=channel.channel_id),
        "is_enabled": bool(channel.is_enabled),
        "status": channel.status,
        "base_url": channel.base_url,
        "primary_category": channel.primary_category,
        "purpose": _safe_text(channel.purpose, fallback=_channel_purpose_fallback(channel)),
        "posts_count": len(channel.publication_records),
        "categories_count": len(set(role_counter.keys())) or 1,
        "prompts_count": len(DEFAULT_AGENT_PACKS.get(channel.provider, ())),
        "planner_supported": channel.provider in {"blogger", "cloudflare", "youtube", "instagram"},
        "analytics_supported": True,
        "prompt_flow_supported": True,
        "capabilities": list(channel.capabilities or []),
        "oauth_state": channel.oauth_state,
        "quota_state": dict(channel.quota_state or {}),
        "agent_pack_summary": [
            {"role_name": role_name, "count": count}
            for role_name, count in sorted(role_counter.items(), key=lambda item: item[0])
        ],
        "live_worker_count": live_workers,
        "pending_items": pending_items,
        "failed_items": failed_items,
        "linked_blog_id": channel.linked_blog_id,
        "credential_state": serialize_platform_credential(latest_credential) if latest_credential else None,
    }


def serialize_content_item(item: ContentItem) -> dict:
    latest_publication = item.publication_records[0] if item.publication_records else None
    latest_score = item.last_score or {}
    return {
        "id": item.id,
        "channel_id": item.managed_channel.channel_id,
        "managed_channel_id": item.managed_channel_id,
        "idempotency_key": item.idempotency_key,
        "provider": item.managed_channel.provider,
        "blog_id": item.blog_id,
        "job_id": item.job_id,
        "source_article_id": item.source_article_id,
        "content_type": item.content_type,
        "lifecycle_status": item.lifecycle_status,
        "title": item.title,
        "description": item.description,
        "body_text": item.body_text,
        "asset_manifest": item.asset_manifest,
        "brief_payload": item.brief_payload,
        "review_notes": item.review_notes,
        "approval_status": item.approval_status,
        "scheduled_for": item.scheduled_for,
        "last_feedback": item.last_feedback,
        "blocked_reason": item.blocked_reason,
        "last_score": latest_score,
        "created_by_agent": item.created_by_agent,
        "latest_publication": serialize_publication_record(latest_publication) if latest_publication else None,
        "metric_count": len(item.metric_facts),
        "run_count": len(item.agent_runs),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def serialize_publication_record(record: PublicationRecord | None) -> dict | None:
    if record is None:
        return None
    return {
        "id": record.id,
        "provider": record.provider,
        "remote_id": record.remote_id,
        "remote_url": record.remote_url,
        "target_state": record.target_state,
        "publish_status": record.publish_status,
        "error_code": record.error_code,
        "scheduled_for": record.scheduled_for,
        "published_at": record.published_at,
        "response_payload": record.response_payload,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def serialize_metric_fact(record: MetricFact) -> dict:
    return {
        "id": record.id,
        "managed_channel_id": record.managed_channel_id,
        "content_item_id": record.content_item_id,
        "provider": record.provider,
        "metric_scope": record.metric_scope,
        "metric_name": record.metric_name,
        "value": record.value,
        "normalized_score": record.normalized_score,
        "dimension_key": record.dimension_key,
        "dimension_value": record.dimension_value,
        "snapshot_at": record.snapshot_at,
        "payload": record.metric_payload,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def serialize_agent_worker(worker: AgentWorker) -> dict:
    return {
        "id": worker.id,
        "managed_channel_id": worker.managed_channel_id,
        "channel_id": worker.managed_channel.channel_id if worker.managed_channel else None,
        "worker_key": worker.worker_key,
        "display_name": worker.display_name,
        "role_name": worker.role_name,
        "runtime_kind": worker.runtime_kind,
        "queue_name": worker.queue_name,
        "concurrency_limit": worker.concurrency_limit,
        "status": worker.status,
        "config_payload": worker.config_payload,
        "last_heartbeat_at": worker.last_heartbeat_at,
        "last_error": worker.last_error,
        "created_at": worker.created_at,
        "updated_at": worker.updated_at,
    }


def serialize_agent_run(run: AgentRun) -> dict:
    return {
        "id": run.id,
        "managed_channel_id": run.managed_channel_id,
        "channel_id": run.managed_channel.channel_id if run.managed_channel else None,
        "content_item_id": run.content_item_id,
        "worker_id": run.worker_id,
        "run_key": run.run_key,
        "runtime_kind": run.runtime_kind,
        "assigned_role": run.assigned_role,
        "provider_model": run.provider_model,
        "status": run.status,
        "priority": run.priority,
        "timeout_seconds": run.timeout_seconds,
        "retry_count": run.retry_count,
        "max_retries": run.max_retries,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "prompt_snapshot": run.prompt_snapshot,
        "response_snapshot": run.response_snapshot,
        "log_lines": run.log_lines,
        "error_message": run.error_message,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }
