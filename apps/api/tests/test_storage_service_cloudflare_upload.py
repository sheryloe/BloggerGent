from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.integrations import storage_service  # noqa: E402


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        headers: dict[str, str] | None = None,
        json_payload: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._json_payload = json_payload

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        if self._json_payload is None:
            raise ValueError("no json payload")
        return self._json_payload


def test_upload_binary_to_cloudflare_r2_falls_back_to_integration_on_missing_bucket(monkeypatch) -> None:
    captured_post: dict = {}

    monkeypatch.setattr(
        storage_service,
        "get_settings_map",
        lambda _db: {
            "cloudflare_account_id": "acct-123",
            "cloudflare_r2_bucket": "donggeuri-assets",
            "cloudflare_r2_access_key_id": "access-key",
            "cloudflare_r2_secret_access_key": "secret-key",
            "cloudflare_r2_public_base_url": "https://api.dongriarchive.com",
            "cloudflare_r2_prefix": "assets",
            "cloudflare_blog_api_base_url": "https://api.dongriarchive.com",
            "cloudflare_blog_m2m_token": "cf-m2m-token",
        },
    )
    monkeypatch.setattr(storage_service, "_is_cloudflare_transform_enabled", lambda _values: False)
    monkeypatch.setattr(
        storage_service.httpx,
        "put",
        lambda *_args, **_kwargs: _FakeResponse(404, text="NoSuchBucket"),
    )
    monkeypatch.setattr(
        storage_service.httpx,
        "post",
        lambda *_args, **kwargs: (
            captured_post.update(kwargs)
            or _FakeResponse(
                200,
                json_payload={
                    "asset": {
                        "bucket": "proxy-bucket",
                        "objectKey": "assets/travel-blogger/travel/sample-slug.webp",
                        "publicUrl": "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp",
                        "etag": "etag-1",
                    }
                },
            )
        ),
    )

    public_url, upload_payload, delivery_meta = storage_service.upload_binary_to_cloudflare_r2(
        None,
        object_key="assets/travel-blogger/travel/sample-slug.webp",
        filename="sample-slug.webp",
        content=b"webp-bytes",
    )

    assert public_url == "https://api.dongriarchive.com/assets/travel-blogger/travel/sample-slug.webp"
    assert upload_payload["upload_path"] == "integration_fallback"
    assert upload_payload["direct_upload_error"]["status_code"] == 404
    assert upload_payload["object_key"] == "assets/travel-blogger/travel/sample-slug.webp"
    assert captured_post["data"]["objectKey"] == "assets/travel-blogger/travel/sample-slug.webp"
    assert upload_payload["public_base_url"] == "https://api.dongriarchive.com"
    assert delivery_meta["cloudflare"]["original_url"] == public_url


def test_resolve_cloudflare_r2_configuration_uses_travel_bucket_and_root_public_origin() -> None:
    config = storage_service._resolve_cloudflare_r2_configuration(  # noqa: SLF001
        {
            "cloudflare_account_id": "acct-123",
            "cloudflare_r2_bucket": "donggeuri-assets",
            "cloudflare_r2_access_key_id": "access-key",
            "cloudflare_r2_secret_access_key": "secret-key",
            "cloudflare_r2_public_base_url": "https://api.dongriarchive.com/assets",
            "cloudflare_r2_prefix": "assets",
        },
        object_key="assets/travel-blogger/culture/sample-slug.webp",
    )

    assert config[1] == "blogger-travel"
    assert config[4] == "https://api.dongriarchive.com"
    assert config[5] == "assets"
