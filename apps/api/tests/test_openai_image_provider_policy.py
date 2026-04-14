from __future__ import annotations

import base64

import pytest

from app.services.providers.base import ProviderRuntimeError
from app.services.providers.factory import get_image_provider
from app.services.providers.openai import OpenAIImageProvider


class _MockImageResponse:
    def __init__(self, payload: dict, *, is_success: bool = True, status_code: int = 200) -> None:
        self.is_success = is_success
        self.status_code = status_code
        self.text = "error"
        self._payload = payload

    def json(self) -> dict:
        if not self.is_success:
            return {"error": {"message": "mock failure"}}
        return {
            "data": [
                {
                    "b64_json": base64.b64encode(b"policy-image").decode("ascii"),
                }
            ]
        }


def test_generate_image_uses_gpt_image_1_with_collage_defaults(monkeypatch) -> None:
    captured: dict = {}

    def _mock_post(_url: str, *, headers: dict, json: dict, timeout: float):  # noqa: ARG001
        captured["payload"] = dict(json)
        return _MockImageResponse(json)

    monkeypatch.setattr("app.services.providers.openai.httpx.post", _mock_post)
    provider = OpenAIImageProvider(api_key="test-key", model="gpt-image-1")

    image_bytes, raw = provider.generate_image("Create one hero collage with panel borders.", "sample-slug")

    assert image_bytes == b"policy-image"
    assert captured["payload"]["model"] == "gpt-image-1"
    assert captured["payload"]["size"] == "1024x1536"
    assert captured["payload"]["quality"] == "high"
    assert raw["requested_model"] == "gpt-image-1"
    assert raw["actual_model"] == "gpt-image-1"


def test_generate_image_falls_back_to_dall_e_3_when_gpt_image_fails(monkeypatch) -> None:
    payloads: list[dict] = []

    def _mock_post(_url: str, *, headers: dict, json: dict, timeout: float):  # noqa: ARG001
        payloads.append(dict(json))
        if json.get("model") == "gpt-image-1":
            return _MockImageResponse(json, is_success=False, status_code=400)
        return _MockImageResponse(json)

    monkeypatch.setattr("app.services.providers.openai.httpx.post", _mock_post)
    provider = OpenAIImageProvider(api_key="test-key", model="gpt-image-1")

    _image_bytes, raw = provider.generate_image("Realistic travel collage poster.", "sample-slug")

    assert len(payloads) == 2
    assert payloads[0]["model"] == "gpt-image-1"
    assert payloads[0]["size"] == "1024x1536"
    assert payloads[0]["quality"] == "high"
    assert payloads[1]["model"] == "dall-e-3"
    assert payloads[1]["size"] == "1024x1792"
    assert payloads[1]["quality"] == "hd"
    assert raw["requested_model"] == "gpt-image-1"
    assert raw["actual_model"] == "dall-e-3"
    assert raw["fallback_used"] is True


def test_get_image_provider_requires_openai_key_in_live_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.providers.factory.get_settings_map",
        lambda _db: {
            "provider_mode": "live",
            "openai_api_key": "",
            "openai_image_model": "gpt-image-1",
            "topic_discovery_provider": "codex_cli",
            "topic_discovery_model": "gpt-5.4",
            "gemini_api_key": "",
            "gemini_model": "gemini-2.5-flash",
            "blogger_access_token": "",
            "default_publish_mode": "draft",
            "text_runtime_kind": "codex_cli",
            "text_runtime_model": "gpt-5.4",
            "image_runtime_kind": "openai_image",
            "codex_job_timeout_seconds": "900",
        },
    )

    with pytest.raises(ProviderRuntimeError) as exc_info:
        get_image_provider(object())

    assert exc_info.value.status_code == 503
    assert "image api key is required" in exc_info.value.message.lower()
