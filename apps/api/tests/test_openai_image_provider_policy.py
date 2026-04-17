from __future__ import annotations

import base64

import pytest

from app.services.providers.base import ProviderRuntimeError
from app.services.providers.factory import get_image_provider
from app.services.providers.openai import ENFORCED_OPENAI_IMAGE_MODEL, OpenAIImageProvider


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
                    "revised_prompt": "revised prompt",
                }
            ]
        }


def test_generate_image_enforces_runtime_model_with_collage_defaults(monkeypatch) -> None:
    captured: dict = {}

    def _mock_post(_url: str, *, headers: dict, json: dict, timeout: float):  # noqa: ARG001
        captured["payload"] = dict(json)
        return _MockImageResponse(json)

    monkeypatch.setattr("app.services.providers.openai.httpx.post", _mock_post)
    provider = OpenAIImageProvider(api_key="test-key", model="gpt-image-1")

    image_bytes, raw = provider.generate_image("Create one hero collage with panel borders.", "sample-slug")

    assert image_bytes == b"policy-image"
    assert captured["payload"]["model"] == ENFORCED_OPENAI_IMAGE_MODEL
    assert captured["payload"]["size"] == "1024x1536"
    assert captured["payload"]["quality"] == "high"
    assert raw["requested_model"] == ENFORCED_OPENAI_IMAGE_MODEL
    assert raw["actual_model"] == ENFORCED_OPENAI_IMAGE_MODEL
    assert raw["generation_strategy"] == "images_generation_direct"
    assert raw["revised_prompt"] == "revised prompt"
    assert raw["model_policy_overridden"] is False
    assert raw["requested_model_input"] == "gpt-image-1"


def test_generate_image_allows_size_override(monkeypatch) -> None:
    captured: dict = {}

    def _mock_post(_url: str, *, headers: dict, json: dict, timeout: float):  # noqa: ARG001
        captured["payload"] = dict(json)
        return _MockImageResponse(json)

    monkeypatch.setattr("app.services.providers.openai.httpx.post", _mock_post)
    provider = OpenAIImageProvider(api_key="test-key", model="gpt-image-1")

    image_bytes, raw = provider.generate_image(
        "Create one hero collage with panel borders.",
        "sample-slug",
        size_override="1024x1024",
    )

    assert image_bytes == b"policy-image"
    assert captured["payload"]["size"] == "1024x1024"
    assert raw["width"] == 1024
    assert raw["height"] == 1024


def test_generate_image_blocks_dall_e_3_before_request(monkeypatch) -> None:
    calls: list[dict] = []

    def _mock_post(_url: str, *, headers: dict, json: dict, timeout: float):  # noqa: ARG001
        calls.append(dict(json))
        return _MockImageResponse(json)

    monkeypatch.setattr("app.services.providers.openai.httpx.post", _mock_post)

    with pytest.raises(ProviderRuntimeError) as exc_info:
        OpenAIImageProvider(api_key="test-key", model="dall-e-3")

    assert exc_info.value.status_code == 422
    assert "blocked" in exc_info.value.message.lower()
    assert calls == []


def test_generate_image_raises_when_response_has_no_image(monkeypatch) -> None:
    def _mock_post(_url: str, *, headers: dict, json: dict, timeout: float):  # noqa: ARG001
        return _MockImageResponse({"model": json["model"]})

    monkeypatch.setattr("app.services.providers.openai.httpx.post", _mock_post)
    monkeypatch.setattr(
        _MockImageResponse,
        "json",
        lambda self: {"data": [{"revised_prompt": "no image"}]},
    )
    provider = OpenAIImageProvider(api_key="test-key", model="gpt-image-1")

    with pytest.raises(ProviderRuntimeError) as exc_info:
        provider.generate_image("Realistic travel collage poster.", "sample-slug")

    assert exc_info.value.status_code == 502
    assert "missing image data" in exc_info.value.message.lower()


def test_get_image_provider_requires_openai_key_in_live_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.providers.factory.get_settings_map",
        lambda _db: {
            "provider_mode": "live",
            "openai_api_key": "",
            "openai_image_model": ENFORCED_OPENAI_IMAGE_MODEL,
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
