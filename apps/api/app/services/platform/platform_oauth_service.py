from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from html import unescape
from secrets import token_urlsafe
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Blog, ManagedChannel
from app.services.blogger.blogger_oauth_service import (
    BLOGGER_LIST_URL,
    GOOGLE_OAUTH_SCOPES,
    get_blogger_redirect_uri,
    persist_blogger_tokens,
)
from app.services.platform.platform_service import (
    get_channel_credential,
    get_managed_channel_by_channel_id,
    list_managed_channels,
    sync_managed_channel_state,
    upsert_platform_credential,
)
from app.services.integrations.secret_service import decrypt_secret_value
from app.services.integrations.settings_service import get_settings_map, upsert_settings

GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

INSTAGRAM_DIALOG_URL_TEMPLATE = "https://www.facebook.com/{version}/dialog/oauth"
INSTAGRAM_TOKEN_URL_TEMPLATE = "https://graph.facebook.com/{version}/oauth/access_token"
INSTAGRAM_ACCOUNTS_URL_TEMPLATE = "https://graph.facebook.com/{version}/me/accounts"

YOUTUBE_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)

INSTAGRAM_OAUTH_SCOPES = (
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
)


class PlatformOAuthError(Exception):
    def __init__(self, message: str, *, detail: str | None = None, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or message
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(UTC)


def get_platform_web_return_url(channel_id: str | None = None) -> str:
    query = f"?channel_id={channel_id}" if channel_id else ""
    return f"{settings.public_web_base_url}/settings{query}"


def _encode_state(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def try_decode_platform_oauth_state(state: str | None) -> dict | None:
    raw_state = str(state or "").strip()
    if not raw_state:
        return None
    padded = raw_state + ("=" * (-len(raw_state) % 4))
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != "platform_oauth":
        return None
    return payload


def _channel_metadata_nonce(channel: ManagedChannel) -> str:
    metadata = dict(channel.channel_metadata or {})
    oauth_state = metadata.get("oauth") if isinstance(metadata.get("oauth"), dict) else {}
    return str(oauth_state.get("nonce") or "").strip()


def _write_channel_oauth_nonce(db: Session, channel: ManagedChannel, *, nonce: str, redirect_uri: str) -> ManagedChannel:
    oauth_metadata = {
        "nonce": nonce,
        "redirect_uri": redirect_uri,
        "updated_at": _utcnow().isoformat(),
    }
    return sync_managed_channel_state(db, channel, metadata_updates={"oauth": oauth_metadata})


def _google_scopes_for_provider(provider: str) -> tuple[str, ...]:
    if provider == "youtube":
        return YOUTUBE_OAUTH_SCOPES
    if provider == "blogger":
        return GOOGLE_OAUTH_SCOPES
    raise PlatformOAuthError("Google OAuth is not supported for this provider.", status_code=400)


def _google_client_config(values: dict[str, str]) -> tuple[str, str, str]:
    client_id = (values.get("blogger_client_id") or "").strip()
    client_secret = (values.get("blogger_client_secret") or "").strip()
    redirect_uri = get_blogger_redirect_uri(values)
    if not client_id or not client_secret:
        raise PlatformOAuthError("Google OAuth client settings are missing.")
    return client_id, client_secret, redirect_uri


def _instagram_client_config(values: dict[str, str]) -> tuple[str, str, str, str]:
    client_id = (values.get("instagram_client_id") or "").strip()
    client_secret = (values.get("instagram_client_secret") or "").strip()
    redirect_uri = (values.get("instagram_redirect_uri") or "").strip()
    if not redirect_uri:
        redirect_uri = f"{settings.public_api_base_url}{settings.api_v1_prefix}/workspace/oauth/instagram/callback"
    version = (values.get("meta_graph_api_version") or settings.meta_graph_api_version or "v23.0").strip()
    if not client_id or not client_secret:
        raise PlatformOAuthError("Instagram / Meta OAuth client settings are missing.")
    return client_id, client_secret, redirect_uri, version


def build_platform_authorization_url(db: Session, *, channel_id: str) -> str:
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise PlatformOAuthError("Channel not found.", status_code=404)

    values = get_settings_map(db)
    nonce = token_urlsafe(24)
    if channel.provider in {"blogger", "youtube"}:
        client_id, _client_secret, redirect_uri = _google_client_config(values)
        _write_channel_oauth_nonce(db, channel, nonce=nonce, redirect_uri=redirect_uri)
        payload = _encode_state(
            {
                "kind": "platform_oauth",
                "provider": "google",
                "channel_id": channel.channel_id,
                "nonce": nonce,
            }
        )
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(_google_scopes_for_provider(channel.provider)),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": payload,
        }
        return f"{GOOGLE_AUTH_BASE_URL}?{urlencode(params)}"

    if channel.provider == "instagram":
        client_id, _client_secret, redirect_uri, version = _instagram_client_config(values)
        _write_channel_oauth_nonce(db, channel, nonce=nonce, redirect_uri=redirect_uri)
        payload = _encode_state(
            {
                "kind": "platform_oauth",
                "provider": "instagram",
                "channel_id": channel.channel_id,
                "nonce": nonce,
            }
        )
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(INSTAGRAM_OAUTH_SCOPES),
            "state": payload,
        }
        return f"{INSTAGRAM_DIALOG_URL_TEMPLATE.format(version=version)}?{urlencode(params)}"

    raise PlatformOAuthError("OAuth is not supported for this provider.", status_code=400)


def _extract_expires_at(token_payload: dict) -> datetime | None:
    try:
        expires_in = int(token_payload.get("expires_in", 0) or 0)
    except (TypeError, ValueError):
        expires_in = 0
    if expires_in <= 0:
        return None
    return _utcnow() + timedelta(seconds=expires_in)


def _raise_token_error(response: httpx.Response, message: str) -> None:
    detail = response.text
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("error_user_msg") or detail)
        else:
            detail = str(payload.get("error_description") or payload.get("message") or detail)
    raise PlatformOAuthError(message, detail=detail, status_code=response.status_code)


def _google_token_request(payload: dict[str, str]) -> dict:
    response = httpx.post(GOOGLE_TOKEN_URL, data=payload, timeout=60.0)
    if not response.is_success:
        _raise_token_error(response, "Google OAuth token request failed.")
    return response.json()


def _platform_google_request(access_token: str, method: str, url: str, *, params: dict | None = None) -> dict:
    response = httpx.request(
        method,
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
        timeout=60.0,
    )
    if not response.is_success:
        _raise_token_error(response, "Google platform profile request failed.")
    return response.json()


def _list_blogger_blogs_with_token(access_token: str) -> list[dict]:
    payload = _platform_google_request(access_token, "GET", BLOGGER_LIST_URL)
    items = payload.get("items", []) or []
    blogs: list[dict] = []
    for item in items:
        blogs.append(
            {
                "id": str(item.get("id", "")).strip(),
                "name": unescape(str(item.get("name", "")).strip()),
                "url": unescape(str(item.get("url", "")).strip()),
                "description": unescape(str(item.get("description", "")).strip()),
            }
        )
    return blogs


def _fetch_youtube_channel_identity(access_token: str) -> dict:
    payload = _platform_google_request(
        access_token,
        "GET",
        YOUTUBE_CHANNELS_URL,
        params={"part": "snippet", "mine": "true", "maxResults": "1"},
    )
    items = payload.get("items", []) or []
    if not items:
        return {}
    first = items[0]
    snippet = first.get("snippet", {}) if isinstance(first.get("snippet"), dict) else {}
    channel_id = str(first.get("id", "")).strip()
    custom_url = str(snippet.get("customUrl", "")).strip()
    base_url = f"https://www.youtube.com/{custom_url}" if custom_url else (f"https://www.youtube.com/channel/{channel_id}" if channel_id else None)
    return {
        "remote_resource_id": channel_id or None,
        "display_name": str(snippet.get("title", "")).strip() or None,
        "base_url": base_url,
        "subject": str(snippet.get("title", "")).strip() or None,
        "metadata": {
            "channel_title": str(snippet.get("title", "")).strip(),
            "custom_url": custom_url or None,
            "channel_id": channel_id or None,
        },
    }


def _sync_blogger_channel_metadata(
    db: Session,
    channel: ManagedChannel,
    *,
    access_token: str,
) -> None:
    if channel.linked_blog is None:
        return

    linked_blog: Blog = channel.linked_blog
    remote_blogs = _list_blogger_blogs_with_token(access_token)
    selected: dict | None = None
    if (linked_blog.blogger_blog_id or "").strip():
        selected = next((item for item in remote_blogs if item["id"] == linked_blog.blogger_blog_id), None)
    elif len(remote_blogs) == 1:
        selected = remote_blogs[0]
        linked_blog.blogger_blog_id = selected["id"]
        linked_blog.blogger_url = selected["url"] or linked_blog.blogger_url
        db.add(linked_blog)
        db.commit()
        db.refresh(linked_blog)

    if selected is None:
        sync_managed_channel_state(
            db,
            channel,
            oauth_state="connected",
            status="attention",
            metadata_updates={"remote_blog_count": len(remote_blogs)},
        )
        return

    sync_managed_channel_state(
        db,
        channel,
        oauth_state="connected",
        status="connected",
        remote_resource_id=selected["id"] or channel.remote_resource_id,
        base_url=selected["url"] or channel.base_url,
        display_name=linked_blog.name,
        metadata_updates={"remote_blog_count": len(remote_blogs), "remote_blog_name": selected["name"]},
    )


def _persist_google_channel_credential(
    db: Session,
    *,
    channel: ManagedChannel,
    token_payload: dict,
    subject: str | None,
    metadata_updates: dict | None = None,
) -> None:
    scopes = [scope for scope in str(token_payload.get("scope") or "").split() if scope]
    access_token = str(token_payload.get("access_token") or "")
    refresh_token = str(token_payload.get("refresh_token") or "")
    expires_at = _extract_expires_at(token_payload)

    if channel.provider == "blogger":
        persist_blogger_tokens(db, token_payload)
        for blogger_channel in [item for item in list_managed_channels(db) if item.provider == "blogger"]:
            upsert_platform_credential(
                db,
                channel=blogger_channel,
                provider="blogger",
                credential_key=blogger_channel.channel_id,
                subject=subject,
                scopes=scopes,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                token_type=str(token_payload.get("token_type") or "Bearer"),
                refresh_metadata=metadata_updates or {},
                is_valid=bool(access_token),
                last_error=None,
            )
            sync_managed_channel_state(db, blogger_channel, oauth_state="connected")
        refreshed = get_managed_channel_by_channel_id(db, channel.channel_id)
        if refreshed is not None:
            _sync_blogger_channel_metadata(db, refreshed, access_token=access_token)
        return

    identity = _fetch_youtube_channel_identity(access_token) if channel.provider == "youtube" else {}
    resolved_subject = subject or str(identity.get("subject") or "").strip() or None
    upsert_platform_credential(
        db,
        channel=channel,
        provider=channel.provider,
        credential_key=channel.channel_id,
        subject=resolved_subject,
        scopes=scopes,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        token_type=str(token_payload.get("token_type") or "Bearer"),
        refresh_metadata=metadata_updates or {},
        is_valid=bool(access_token),
        last_error=None,
    )
    sync_managed_channel_state(
        db,
        channel,
        oauth_state="connected",
        status="connected" if identity.get("remote_resource_id") else "attention",
        remote_resource_id=identity.get("remote_resource_id") or channel.remote_resource_id,
        base_url=identity.get("base_url") or channel.base_url,
        display_name=identity.get("display_name") or channel.display_name,
        metadata_updates={**(metadata_updates or {}), **identity.get("metadata", {})},
    )


def complete_google_platform_oauth(db: Session, *, code: str, state: str | None) -> dict:
    payload = try_decode_platform_oauth_state(state)
    if payload is None or payload.get("provider") != "google":
        raise PlatformOAuthError("Invalid Google OAuth state.")

    channel = get_managed_channel_by_channel_id(db, str(payload.get("channel_id") or ""))
    if channel is None:
        raise PlatformOAuthError("Channel not found.", status_code=404)

    expected_nonce = _channel_metadata_nonce(channel)
    if not expected_nonce or expected_nonce != str(payload.get("nonce") or ""):
        raise PlatformOAuthError("OAuth state validation failed.")

    values = get_settings_map(db)
    client_id, client_secret, redirect_uri = _google_client_config(values)
    token_payload = _google_token_request(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    )
    subject = None
    metadata = {"oauth_provider": "google", "granted_scopes": token_payload.get("scope", "")}
    _persist_google_channel_credential(db, channel=channel, token_payload=token_payload, subject=subject, metadata_updates=metadata)
    sync_managed_channel_state(db, channel, metadata_updates={"oauth": {"nonce": "", "updated_at": _utcnow().isoformat()}})
    upsert_settings(db, {"blogger_oauth_state": ""})
    return {"provider": "google", "channel_id": channel.channel_id}


def _instagram_request(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    timeout: float = 60.0,
) -> dict:
    response = httpx.request(method, url, params=params, data=data, timeout=timeout)
    if not response.is_success:
        _raise_token_error(response, "Instagram / Meta request failed.")
    return response.json()


def _exchange_instagram_code(values: dict[str, str], *, code: str) -> tuple[dict, str]:
    client_id, client_secret, redirect_uri, version = _instagram_client_config(values)
    token_payload = _instagram_request(
        "GET",
        INSTAGRAM_TOKEN_URL_TEMPLATE.format(version=version),
        params={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )
    access_token = str(token_payload.get("access_token") or "")
    if not access_token:
        raise PlatformOAuthError("Instagram OAuth did not return an access token.")
    long_lived_payload = _instagram_request(
        "GET",
        INSTAGRAM_TOKEN_URL_TEMPLATE.format(version=version),
        params={
            "grant_type": "fb_exchange_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "fb_exchange_token": access_token,
        },
    )
    if long_lived_payload.get("access_token"):
        return long_lived_payload, version
    return token_payload, version


def _discover_instagram_account(access_token: str, *, version: str) -> dict:
    payload = _instagram_request(
        "GET",
        INSTAGRAM_ACCOUNTS_URL_TEMPLATE.format(version=version),
        params={
            "access_token": access_token,
            "fields": "id,name,instagram_business_account{id,username,profile_picture_url}",
        },
    )
    for item in payload.get("data", []) or []:
        if not isinstance(item, dict):
            continue
        instagram_account = item.get("instagram_business_account")
        if not isinstance(instagram_account, dict):
            continue
        remote_id = str(instagram_account.get("id", "")).strip()
        username = str(instagram_account.get("username", "")).strip()
        base_url = f"https://www.instagram.com/{username}/" if username else None
        return {
            "remote_resource_id": remote_id or None,
            "display_name": username or str(item.get("name", "")).strip() or None,
            "subject": username or str(item.get("name", "")).strip() or None,
            "base_url": base_url,
            "metadata": {
                "page_id": str(item.get("id", "")).strip() or None,
                "page_name": str(item.get("name", "")).strip() or None,
                "instagram_username": username or None,
                "instagram_business_account_id": remote_id or None,
            },
        }
    return {}


def complete_instagram_oauth(db: Session, *, code: str, state: str | None) -> dict:
    payload = try_decode_platform_oauth_state(state)
    if payload is None or payload.get("provider") != "instagram":
        raise PlatformOAuthError("Invalid Instagram OAuth state.")

    channel = get_managed_channel_by_channel_id(db, str(payload.get("channel_id") or ""))
    if channel is None:
        raise PlatformOAuthError("Channel not found.", status_code=404)

    expected_nonce = _channel_metadata_nonce(channel)
    if not expected_nonce or expected_nonce != str(payload.get("nonce") or ""):
        raise PlatformOAuthError("OAuth state validation failed.")

    values = get_settings_map(db)
    token_payload, version = _exchange_instagram_code(values, code=code)
    access_token = str(token_payload.get("access_token") or "")
    expires_at = _extract_expires_at(token_payload)
    identity = _discover_instagram_account(access_token, version=version)
    capabilities = list(channel.capabilities or [])
    publish_enabled = str(values.get("instagram_publish_api_enabled") or str(settings.instagram_publish_api_enabled).lower()).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if publish_enabled and "instagram_live_publish" not in capabilities:
        capabilities.append("instagram_live_publish")

    upsert_platform_credential(
        db,
        channel=channel,
        provider="instagram",
        credential_key=channel.channel_id,
        subject=identity.get("subject"),
        scopes=list(INSTAGRAM_OAUTH_SCOPES),
        access_token=access_token,
        refresh_token="",
        expires_at=expires_at,
        token_type=str(token_payload.get("token_type") or "Bearer"),
        refresh_metadata={
            "oauth_provider": "instagram",
            "refresh_strategy": "fb_exchange_token",
            "graph_version": version,
            **identity.get("metadata", {}),
        },
        is_valid=bool(access_token),
        last_error=None,
    )
    sync_managed_channel_state(
        db,
        channel,
        oauth_state="connected",
        status="connected" if identity.get("remote_resource_id") else "attention",
        remote_resource_id=identity.get("remote_resource_id") or channel.remote_resource_id,
        base_url=identity.get("base_url") or channel.base_url,
        display_name=identity.get("display_name") or channel.display_name,
        capabilities=capabilities,
        metadata_updates={
            "oauth": {"nonce": "", "updated_at": _utcnow().isoformat()},
            **identity.get("metadata", {}),
        },
    )
    return {"provider": "instagram", "channel_id": channel.channel_id}


def refresh_platform_access_token(db: Session, *, channel_id: str) -> PlatformCredential:
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise PlatformOAuthError("Channel not found.", status_code=404)

    credential = get_channel_credential(channel)
    if credential is None:
        raise PlatformOAuthError("Credential not found for this channel.", status_code=404)

    values = get_settings_map(db)
    if channel.provider in {"blogger", "youtube"}:
        client_id, client_secret, _redirect_uri = _google_client_config(values)
        refresh_token = decrypt_secret_value(credential.refresh_token_encrypted)
        if not refresh_token:
            raise PlatformOAuthError("Refresh token is missing for this channel.", status_code=401)
        token_payload = _google_token_request(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )
        token_payload["refresh_token"] = refresh_token
        token_payload["scope"] = " ".join(credential.scopes or [])
        _persist_google_channel_credential(
            db,
            channel=channel,
            token_payload=token_payload,
            subject=credential.subject,
            metadata_updates=dict(credential.refresh_metadata or {}),
        )
        refreshed_channel = get_managed_channel_by_channel_id(db, channel.channel_id)
        refreshed_credential = get_channel_credential(refreshed_channel or channel)
        if refreshed_credential is None:
            raise PlatformOAuthError("Credential refresh did not persist correctly.", status_code=500)
        return refreshed_credential

    if channel.provider == "instagram":
        client_id, client_secret, _redirect_uri, version = _instagram_client_config(values)
        access_token = decrypt_secret_value(credential.access_token_encrypted)
        if not access_token:
            raise PlatformOAuthError("Access token is missing for this channel.", status_code=401)
        token_payload = _instagram_request(
            "GET",
            INSTAGRAM_TOKEN_URL_TEMPLATE.format(version=version),
            params={
                "grant_type": "fb_exchange_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "fb_exchange_token": access_token,
            },
        )
        refreshed_token = str(token_payload.get("access_token") or "")
        if not refreshed_token:
            raise PlatformOAuthError("Instagram token refresh did not return a new access token.")
        upsert_platform_credential(
            db,
            channel=channel,
            provider="instagram",
            credential_key=channel.channel_id,
            subject=credential.subject,
            scopes=list(credential.scopes or INSTAGRAM_OAUTH_SCOPES),
            access_token=refreshed_token,
            refresh_token="",
            expires_at=_extract_expires_at(token_payload),
            token_type=str(token_payload.get("token_type") or credential.token_type or "Bearer"),
            refresh_metadata=dict(credential.refresh_metadata or {}),
            is_valid=True,
            last_error=None,
        )
        sync_managed_channel_state(db, channel, oauth_state="connected", status="connected")
        refreshed_channel = get_managed_channel_by_channel_id(db, channel.channel_id)
        refreshed_credential = get_channel_credential(refreshed_channel or channel)
        if refreshed_credential is None:
            raise PlatformOAuthError("Credential refresh did not persist correctly.", status_code=500)
        return refreshed_credential

    raise PlatformOAuthError("Refresh is not supported for this provider.", status_code=400)


def get_valid_platform_access_token(db: Session, *, channel_id: str) -> str:
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise PlatformOAuthError("Channel not found.", status_code=404)

    credential = get_channel_credential(channel)
    if credential is None or not credential.is_valid:
        raise PlatformOAuthError("Channel is not authenticated.", status_code=401)

    access_token = decrypt_secret_value(credential.access_token_encrypted)
    if not access_token:
        raise PlatformOAuthError("Access token is missing.", status_code=401)

    expires_at = credential.expires_at
    if expires_at is not None:
        current = _utcnow()
        expiry = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
        if expiry <= current + timedelta(minutes=1):
            refreshed = refresh_platform_access_token(db, channel_id=channel.channel_id)
            access_token = decrypt_secret_value(refreshed.access_token_encrypted)
            if not access_token:
                raise PlatformOAuthError("Refreshed access token is empty.", status_code=401)
    return access_token


def authorized_platform_request(
    db: Session,
    *,
    channel_id: str,
    method: str,
    url: str,
    params: dict | None = None,
    json_payload: dict | None = None,
    data: object | None = None,
    content: object | None = None,
    headers: dict | None = None,
    timeout: float = 60.0,
) -> httpx.Response:
    access_token = get_valid_platform_access_token(db, channel_id=channel_id)
    request_headers = {"Authorization": f"Bearer {access_token}", **(headers or {})}
    response = httpx.request(
        method,
        url,
        params=params,
        json=json_payload,
        data=data,
        content=content,
        headers=request_headers,
        timeout=timeout,
    )
    if response.status_code != 401:
        return response

    refreshed = refresh_platform_access_token(db, channel_id=channel_id)
    refreshed_token = decrypt_secret_value(refreshed.access_token_encrypted)
    request_headers["Authorization"] = f"Bearer {refreshed_token}"
    return httpx.request(
        method,
        url,
        params=params,
        json=json_payload,
        data=data,
        content=content,
        headers=request_headers,
        timeout=timeout,
    )
