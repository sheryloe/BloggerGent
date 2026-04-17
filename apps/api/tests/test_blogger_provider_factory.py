from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.blogger.blogger_oauth_service import BloggerOAuthError
from app.services.providers.base import ProviderRuntimeError, RuntimeProviderConfig
from app.services.providers.factory import get_blogger_provider


def test_get_blogger_provider_raises_when_live_oauth_refresh_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="",
        openai_text_model="gpt-5.4-2026-03-05",
        openai_image_model="gpt-image-1",
        topic_discovery_provider="openai",
        topic_discovery_model="gpt-5.4-2026-03-05",
        gemini_api_key="",
        gemini_model="gemini-2.5-flash",
        blogger_access_token="",
        default_publish_mode="publish",
    )
    blog = SimpleNamespace(blogger_blog_id="123456789")

    monkeypatch.setattr("app.services.providers.factory.get_runtime_config", lambda _db: runtime)

    def _raise(_db):
        raise BloggerOAuthError(
            "refresh failed",
            detail="Token has been expired or revoked.",
            status_code=400,
        )

    monkeypatch.setattr("app.services.providers.factory.get_valid_blogger_access_token", _raise)

    with pytest.raises(ProviderRuntimeError) as exc_info:
        get_blogger_provider(object(), blog)

    assert exc_info.value.provider == "blogger"
    assert exc_info.value.status_code == 400
    assert "revoked" in exc_info.value.detail.lower()
