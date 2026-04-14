from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.entities import WorkflowStageType
from app.schemas.api import OpenAIFreeUsageBucketRead, OpenAIFreeUsageRead
from app.services import openai_usage_service
from app.services.ops.model_policy_service import validate_text_settings_payload
from app.services.ops.openai_usage_service import (
    FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
    LARGE_MODEL_LIMIT,
    OPENAI_USAGE_HARD_CAP_PERCENT,
    SMALL_MODEL_LIMIT,
    assert_openai_api_stage_allowed,
    get_openai_free_usage_status,
    route_openai_free_tier_text_model,
)
from app.services.providers.base import ProviderRuntimeError
from app.tasks.pipeline import _resolve_stage_text_model, _stage_allows_large_text_model


def _usage(*, large_used: int, small_used: int = 0) -> OpenAIFreeUsageRead:
    large_percent = round((large_used / LARGE_MODEL_LIMIT) * 100, 2) if LARGE_MODEL_LIMIT else 0.0
    small_percent = round((small_used / SMALL_MODEL_LIMIT) * 100, 2) if SMALL_MODEL_LIMIT else 0.0
    return OpenAIFreeUsageRead(
        date_label="2026-03-30 UTC",
        window_start_utc="2026-03-30T00:00:00+00:00",
        window_end_utc="2026-03-30T12:00:00+00:00",
        key_mode="admin",
        admin_key_configured=True,
        large=OpenAIFreeUsageBucketRead(
            label="Large Models",
            limit_tokens=LARGE_MODEL_LIMIT,
            input_tokens=large_used,
            output_tokens=0,
            used_tokens=large_used,
            remaining_tokens=max(LARGE_MODEL_LIMIT - large_used, 0),
            usage_percent=large_percent,
            matched_models=[],
        ),
        small=OpenAIFreeUsageBucketRead(
            label="Small Models",
            limit_tokens=SMALL_MODEL_LIMIT,
            input_tokens=small_used,
            output_tokens=0,
            used_tokens=small_used,
            remaining_tokens=max(SMALL_MODEL_LIMIT - small_used, 0),
            usage_percent=small_percent,
            matched_models=[],
        ),
        warning=None,
        hard_cap_enabled=True,
        blocked_due_to_usage_unavailable=False,
        blocked_due_to_usage_cap=max(large_percent, small_percent) >= OPENAI_USAGE_HARD_CAP_PERCENT,
        warning_threshold_percent=80.0,
        hard_cap_threshold_percent=100.0,
        unexpected_text_api_call_count=0,
    )


def test_route_blocks_when_small_bucket_hits_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=0, small_used=SMALL_MODEL_LIMIT),
    )

    with pytest.raises(ProviderRuntimeError) as exc_info:
        route_openai_free_tier_text_model(
            db=object(),
            requested_model="gpt-5-mini-2025-08-07",
            allow_large=False,
        )

    assert exc_info.value.status_code == 429
    assert "hard cap reached" in exc_info.value.message.lower()


def test_route_blocks_when_usage_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: (_ for _ in ()).throw(
            ProviderRuntimeError(
                provider="openai_usage",
                status_code=503,
                message="Failed to fetch OpenAI usage.",
                detail="usage endpoint timeout",
            )
        ),
    )

    with pytest.raises(ProviderRuntimeError) as exc_info:
        route_openai_free_tier_text_model(
            db=object(),
            requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
            allow_large=True,
        )

    assert exc_info.value.status_code == 503
    assert "usage is unavailable" in exc_info.value.message.lower()


def test_route_blocks_at_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=LARGE_MODEL_LIMIT, small_used=0),
    )

    with pytest.raises(ProviderRuntimeError) as exc_info:
        route_openai_free_tier_text_model(
            db=object(),
            requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
            allow_large=True,
        )

    assert exc_info.value.status_code == 429
    assert "hard cap reached" in exc_info.value.message.lower()


def test_assert_openai_api_stage_allowed_blocks_on_unavailable_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_settings_map",
        lambda _db: {"openai_usage_hard_cap_enabled": "true"},
    )
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: (_ for _ in ()).throw(
            ProviderRuntimeError(
                provider="openai_usage",
                status_code=503,
                message="Failed to fetch OpenAI usage.",
                detail="timeout",
            )
        ),
    )

    with pytest.raises(ProviderRuntimeError) as exc_info:
        assert_openai_api_stage_allowed(object(), stage_name="image_generation")

    assert exc_info.value.status_code == 503
    assert "blocked" in exc_info.value.message.lower()


def test_assert_openai_api_stage_allowed_ignores_disabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_settings_map",
        lambda _db: {"openai_usage_hard_cap_enabled": "false"},
    )
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=LARGE_MODEL_LIMIT, small_used=0),
    )

    with pytest.raises(ProviderRuntimeError) as exc_info:
        assert_openai_api_stage_allowed(object(), stage_name="image_generation")

    assert exc_info.value.status_code == 429
    assert "hard cap reached" in exc_info.value.message.lower()


def test_get_openai_free_usage_status_marks_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: (_ for _ in ()).throw(
            ProviderRuntimeError(
                provider="openai_usage",
                status_code=503,
                message="Failed to fetch OpenAI usage.",
                detail="timeout",
            )
        ),
    )

    snapshot = get_openai_free_usage_status(object())

    assert snapshot.blocked_due_to_usage_unavailable is True
    assert snapshot.blocked_due_to_usage_cap is False
    assert snapshot.hard_cap_enabled is True


def test_usage_count_is_strictly_based_on_free_tier_model_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    class _MockResponse:
        is_success = True
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict:
            return {
                "data": [
                    {
                        "results": [
                            {"model": "gpt-5.4-2026-03-05", "input_tokens": 400, "output_tokens": 100},
                            {"model": "gpt-4.1-2025-04-14", "input_tokens": 200, "output_tokens": 100},
                            {"model": "gpt-4.1-mini-2025-04-14", "input_tokens": 10, "output_tokens": 20},
                        ]
                    }
                ]
            }

    monkeypatch.setattr(
        openai_usage_service,
        "get_settings_map",
        lambda _db: {"openai_admin_api_key": "", "openai_api_key": "test-key"},
    )
    monkeypatch.setattr(openai_usage_service.httpx, "get", lambda *args, **kwargs: _MockResponse())

    usage = openai_usage_service.get_openai_free_usage(object())

    assert usage.large.input_tokens == 200
    assert usage.large.output_tokens == 100
    assert usage.large.used_tokens == 300
    assert usage.small.input_tokens == 10
    assert usage.small.output_tokens == 20
    assert usage.small.used_tokens == 30
    assert "gpt-5.4-2026-03-05" not in usage.large.matched_models
    assert "gpt-5.4-2026-03-05" not in usage.small.matched_models


def test_empty_usage_snapshot_sets_input_and_output_to_zero() -> None:
    snapshot = openai_usage_service._empty_usage_snapshot(datetime(2026, 4, 9, 11, 30, tzinfo=timezone.utc))

    assert snapshot.large.input_tokens == 0
    assert snapshot.large.output_tokens == 0
    assert snapshot.large.used_tokens == 0
    assert snapshot.small.input_tokens == 0
    assert snapshot.small.output_tokens == 0
    assert snapshot.small.used_tokens == 0
    assert snapshot.blocked_due_to_usage_unavailable is True


def test_validate_text_settings_payload_keeps_hard_cap_flag_for_compatibility_only() -> None:
    validate_text_settings_payload({"openai_usage_hard_cap_enabled": "false"})


def test_stage_policy_allows_large_for_prompt_stages() -> None:
    assert _stage_allows_large_text_model(WorkflowStageType.TOPIC_DISCOVERY) is True
    assert _stage_allows_large_text_model(WorkflowStageType.ARTICLE_GENERATION) is True
    assert _stage_allows_large_text_model(WorkflowStageType.IMAGE_PROMPT_GENERATION) is True


def test_stage_default_article_model_is_codex_when_runtime_requires_it() -> None:
    runtime = SimpleNamespace(
        topic_discovery_model="",
        openai_text_model="gpt-4.1-mini-2025-04-14",
        text_runtime_kind="codex_cli",
        text_runtime_model="gpt-5.4",
    )

    resolved = _resolve_stage_text_model(
        stage_type=WorkflowStageType.ARTICLE_GENERATION,
        configured_model=None,
        runtime=runtime,
    )

    assert resolved == "gpt-5.4"
