from __future__ import annotations

import itertools

import pytest

from app.core.config import settings as app_settings
from app.schemas.ai import ArticleGenerationOutput
from app.services import codex_cli_queue_service
from app.services.providers.base import ProviderRuntimeError, RuntimeProviderConfig


def _runtime() -> RuntimeProviderConfig:
    return RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="",
        openai_text_model="gpt-4.1-2025-04-14",
        openai_image_model="gpt-image-1",
        topic_discovery_provider="openai",
        topic_discovery_model="gpt-4.1-2025-04-14",
        gemini_api_key="",
        gemini_model="gemini-2.5-flash",
        blogger_access_token="",
        default_publish_mode="draft",
        text_runtime_kind="codex_cli",
        text_runtime_model="gpt-5.4",
        image_runtime_kind="openai_image",
        codex_job_timeout_seconds=900,
    )


def test_submit_codex_text_job_restores_processing_file_after_timeout(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    runtime = _runtime()
    monotonic_values = itertools.chain([0.0, 0.0, 31.0], itertools.repeat(31.0))

    def _fake_sleep(_seconds: float) -> None:
        requests_dir = codex_cli_queue_service._requests_dir(runtime)
        processing_dir = codex_cli_queue_service._processing_dir(runtime)
        request_files = sorted(requests_dir.glob("*.json"))
        if request_files:
            request_files[0].replace(processing_dir / request_files[0].name)

    monkeypatch.setattr(codex_cli_queue_service.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(codex_cli_queue_service.time, "sleep", _fake_sleep)

    with pytest.raises(ProviderRuntimeError) as exc_info:
        codex_cli_queue_service.submit_codex_text_job(
            runtime=runtime,
            stage_name="seo_rewrite",
            model="gpt-5.4",
            prompt="Rewrite this article",
            response_kind="text",
            timeout_seconds=1,
        )

    requests_dir = codex_cli_queue_service._requests_dir(runtime)
    processing_dir = codex_cli_queue_service._processing_dir(runtime)

    assert exc_info.value.status_code == 504
    assert len(list(requests_dir.glob("*.json"))) == 1
    assert len(list(processing_dir.glob("*.json"))) == 0


def test_normalize_codex_response_schema_disallows_additional_properties() -> None:
    schema = codex_cli_queue_service._normalize_codex_response_schema(ArticleGenerationOutput.model_json_schema())

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["FAQItem"]["additionalProperties"] is False
