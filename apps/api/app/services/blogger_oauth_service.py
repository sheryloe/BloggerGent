from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
from secrets import token_urlsafe
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.settings_service import get_settings_map, upsert_settings

BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"
SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"
GOOGLE_OAUTH_SCOPES = (BLOGGER_SCOPE, SEARCH_CONSOLE_SCOPE, ANALYTICS_SCOPE, INDEXING_SCOPE)

AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_LIST_URL = "https://www.googleapis.com/blogger/v3/users/self/blogs"


class BloggerOAuthError(Exception):
    def __init__(self, message: str, *, detail: str | None = None, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or message
        self.status_code = status_code


def get_google_oauth_scopes() -> list[str]:
    return list(GOOGLE_OAUTH_SCOPES)


def get_granted_google_scopes(values: dict[str, str] | None = None) -> list[str]:
    config = values or {}
    raw_scope = (config.get("blogger_token_scope") or "").strip()
    if not raw_scope:
        return []
    return [scope for scope in raw_scope.split() if scope]


def has_granted_google_scope(scope: str, values: dict[str, str] | None = None) -> bool:
    return scope in set(get_granted_google_scopes(values))


def get_blogger_redirect_uri(values: dict[str, str] | None = None) -> str:
    config = values or {}
    redirect_uri = (config.get("blogger_redirect_uri") or "").strip()
    if redirect_uri:
        return redirect_uri
    return f"{settings.public_api_base_url}{settings.api_v1_prefix}/blogger/oauth/callback"


def get_blogger_web_return_url() -> str:
    return f"{settings.public_web_base_url}/settings"


def build_blogger_authorization_url(db: Session) -> str:
    values = get_settings_map(db)
    client_id = (values.get("blogger_client_id") or "").strip()
    if not client_id:
        raise BloggerOAuthError("Blogger Client ID가 설정되어 있지 않습니다.")

    state = token_urlsafe(24)
    upsert_settings(db, {"blogger_oauth_state": state})
    params = {
        "client_id": client_id,
        "redirect_uri": get_blogger_redirect_uri(values),
        "response_type": "code",
        "scope": " ".join(GOOGLE_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_BASE_URL}?{urlencode(params)}"


def _require_blogger_client_config(values: dict[str, str]) -> tuple[str, str, str]:
    client_id = (values.get("blogger_client_id") or "").strip()
    client_secret = (values.get("blogger_client_secret") or "").strip()
    redirect_uri = get_blogger_redirect_uri(values)
    if not client_id or not client_secret:
        raise BloggerOAuthError("Blogger OAuth 클라이언트 설정이 비어 있습니다.")
    return client_id, client_secret, redirect_uri


def _token_request(payload: dict[str, str]) -> dict:
    response = httpx.post(TOKEN_URL, data=payload, timeout=60.0)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text
        try:
            error_payload = response.json()
            detail = error_payload.get("error_description") or error_payload.get("error") or detail
        except ValueError:
            pass
        raise BloggerOAuthError(
            "Google OAuth 토큰 요청에 실패했습니다.",
            detail=detail,
            status_code=response.status_code,
        ) from exc
    return response.json()


def exchange_blogger_code(db: Session, *, code: str, state: str | None) -> dict:
    values = get_settings_map(db)
    expected_state = (values.get("blogger_oauth_state") or "").strip()
    if not expected_state or state != expected_state:
        raise BloggerOAuthError("Blogger OAuth state 검증에 실패했습니다.", status_code=400)

    client_id, client_secret, redirect_uri = _require_blogger_client_config(values)
    token_payload = _token_request(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    )
    persist_blogger_tokens(db, token_payload)
    upsert_settings(db, {"blogger_oauth_state": ""})
    return token_payload


def persist_blogger_tokens(db: Session, token_payload: dict) -> None:
    expires_in = int(token_payload.get("expires_in", 0) or 0)
    expires_at = ""
    if expires_in > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    values_to_save = {
        "blogger_access_token": token_payload.get("access_token", ""),
        "blogger_access_token_expires_at": expires_at,
        "blogger_token_scope": token_payload.get("scope", " ".join(GOOGLE_OAUTH_SCOPES)),
        "blogger_token_type": token_payload.get("token_type", "Bearer"),
    }
    refresh_token = token_payload.get("refresh_token")
    if refresh_token:
        values_to_save["blogger_refresh_token"] = refresh_token
    upsert_settings(db, values_to_save)


def refresh_blogger_access_token(db: Session) -> str:
    values = get_settings_map(db)
    client_id, client_secret, _redirect_uri = _require_blogger_client_config(values)
    refresh_token = (values.get("blogger_refresh_token") or "").strip()
    if not refresh_token:
        raise BloggerOAuthError("Blogger refresh token이 없습니다. 다시 연결해주세요.", status_code=401)

    token_payload = _token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )
    if "refresh_token" not in token_payload:
        token_payload["refresh_token"] = refresh_token
    persist_blogger_tokens(db, token_payload)
    return token_payload["access_token"]


def get_valid_blogger_access_token(db: Session) -> str:
    values = get_settings_map(db)
    access_token = (values.get("blogger_access_token") or "").strip()
    expires_at_raw = (values.get("blogger_access_token_expires_at") or "").strip()
    if access_token and expires_at_raw:
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > datetime.now(timezone.utc) + timedelta(minutes=1):
                return access_token
        except ValueError:
            pass
    if access_token and not (values.get("blogger_refresh_token") or "").strip():
        return access_token
    return refresh_blogger_access_token(db)


def authorized_google_request(
    db: Session,
    method: str,
    url: str,
    *,
    params: dict | list[tuple[str, str]] | None = None,
    json: dict | None = None,
    timeout: float = 60.0,
) -> httpx.Response:
    access_token = get_valid_blogger_access_token(db)
    headers = {"Authorization": f"Bearer {access_token}"}
    response = httpx.request(method, url, headers=headers, params=params, json=json, timeout=timeout)
    if response.status_code != 401:
        return response

    refreshed_token = refresh_blogger_access_token(db)
    headers["Authorization"] = f"Bearer {refreshed_token}"
    return httpx.request(method, url, headers=headers, params=params, json=json, timeout=timeout)


def list_blogger_blogs(db: Session) -> list[dict]:
    response = authorized_google_request(db, "GET", BLOGGER_LIST_URL)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text
        try:
            detail = response.json().get("error", {}).get("message", detail)
        except ValueError:
            pass
        raise BloggerOAuthError(
            "Blogger 블로그 목록 조회에 실패했습니다.",
            detail=detail,
            status_code=response.status_code,
        ) from exc

    items = response.json().get("items", []) or []
    blogs: list[dict] = []
    for item in items:
        posts = item.get("posts", {}) if isinstance(item.get("posts"), dict) else {}
        pages = item.get("pages", {}) if isinstance(item.get("pages"), dict) else {}
        blogs.append(
            {
                "id": item.get("id", ""),
                "name": unescape(item.get("name", "")),
                "description": unescape(item.get("description", "")),
                "url": unescape(item.get("url", "")),
                "published": item.get("published", ""),
                "updated": item.get("updated", ""),
                "locale": item.get("locale", {}),
                "posts_total_items": int(posts.get("totalItems", 0) or 0) if posts else None,
                "pages_total_items": int(pages.get("totalItems", 0) or 0) if pages else None,
            }
        )
    return blogs
