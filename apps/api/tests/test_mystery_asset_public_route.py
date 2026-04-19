from __future__ import annotations

import json

from app import main as main_module
from app.services.integrations.mystery_asset_public_service import (
    guess_asset_content_type,
    mystery_asset_path_to_object_key,
)
from app.services.providers.base import ProviderRuntimeError


class _DummySession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _DummyRequest:
    def __init__(self, method: str) -> None:
        self.method = method


def test_mystery_asset_path_to_object_key_accepts_canonical_path() -> None:
    resolved = mystery_asset_path_to_object_key(
        "the-midnight-archives/casefile/2026/04/mapping-check/mapping-check.webp"
    )
    assert resolved == "assets/the-midnight-archives/casefile/2026/04/mapping-check/mapping-check.webp"


def test_mystery_asset_path_to_object_key_rejects_duplicated_assets_prefix() -> None:
    resolved = mystery_asset_path_to_object_key(
        "assets/the-midnight-archives/casefile/2026/04/mapping-check/mapping-check.webp"
    )
    assert resolved is None


def test_mystery_asset_path_to_object_key_rejects_legacy_media_prefix() -> None:
    resolved = mystery_asset_path_to_object_key(
        "the-midnight-archives/casefile/2026/04/media/posts/mapping-check.webp"
    )
    assert resolved is None


def test_guess_asset_content_type_defaults_to_webp() -> None:
    assert guess_asset_content_type("assets/the-midnight-archives/x/y/z.webp") == "image/webp"


def test_serve_mystery_asset_maps_public_path_to_object_key(monkeypatch) -> None:
    session = _DummySession()
    captured: dict[str, str] = {}

    def _fake_session_local() -> _DummySession:
        return session

    def _fake_download_binary(_db, *, public_key: str, key: str) -> bytes:
        captured["public_key"] = public_key
        captured["key"] = key
        return b"ok"

    monkeypatch.setattr(main_module, "SessionLocal", _fake_session_local)
    monkeypatch.setattr(main_module, "cloudflare_r2_download_binary", _fake_download_binary)

    response = main_module.serve_mystery_asset(
        "the-midnight-archives/casefile/2026/04/mapping-check/mapping-check.webp",
        _DummyRequest("GET"),
    )

    assert response.status_code == 200
    assert response.media_type == "image/webp"
    assert response.body == b"ok"
    assert captured == {
        "public_key": "",
        "key": "assets/the-midnight-archives/casefile/2026/04/mapping-check/mapping-check.webp",
    }
    assert session.closed is True


def test_serve_mystery_asset_returns_not_found_for_invalid_path() -> None:
    response = main_module.serve_mystery_asset(
        "assets/the-midnight-archives/casefile/2026/04/mapping-check/mapping-check.webp",
        _DummyRequest("GET"),
    )
    body = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 404
    assert body["error"]["code"] == "ASSET_NOT_FOUND"


def test_serve_mystery_asset_returns_not_found_when_r2_object_missing(monkeypatch) -> None:
    session = _DummySession()

    def _fake_session_local() -> _DummySession:
        return session

    def _fake_download_binary(_db, *, public_key: str, key: str) -> bytes:
        raise ProviderRuntimeError(
            provider="cloudflare_r2",
            status_code=404,
            message="missing",
            detail=f"missing:{key}",
        )

    monkeypatch.setattr(main_module, "SessionLocal", _fake_session_local)
    monkeypatch.setattr(main_module, "cloudflare_r2_download_binary", _fake_download_binary)

    response = main_module.serve_mystery_asset(
        "the-midnight-archives/casefile/2026/04/mapping-check/mapping-check.webp",
        _DummyRequest("GET"),
    )
    body = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 404
    assert body["error"]["code"] == "ASSET_NOT_FOUND"
    assert session.closed is True
