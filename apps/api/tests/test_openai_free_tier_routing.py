from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.entities import WorkflowStageType
from app.schemas.api import OpenAIFreeUsageBucketRead, OpenAIFreeUsageRead
from app.services import openai_usage_service
from app.services.openai_usage_service import (
    FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
    FREE_TIER_DEFAULT_SMALL_TEXT_MODEL,
    LARGE_MODEL_LIMIT,
    LARGE_MODEL_SWITCH_THRESHOLD_TOKENS,
    SMALL_MODEL_LIMIT,
    route_openai_free_tier_text_model,
)
from app.services.providers.base import ProviderRuntimeError
from app.tasks.pipeline import _resolve_stage_text_model, _stage_allows_large_text_model


def _usage(*, large_used: int, small_used: int = 0) -> OpenAIFreeUsageRead:
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
            usage_percent=0.0,
            matched_models=[],
        ),
        small=OpenAIFreeUsageBucketRead(
            label="Small Models",
            limit_tokens=SMALL_MODEL_LIMIT,
            input_tokens=small_used,
            output_tokens=0,
            used_tokens=small_used,
            remaining_tokens=max(SMALL_MODEL_LIMIT - small_used, 0),
            usage_percent=0.0,
            matched_models=[],
        ),
        warning=None,
    )


def test_route_replaces_non_free_model_with_small(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=0, small_used=0),
    )

    decision = route_openai_free_tier_text_model(
        db=object(),
        requested_model="gpt-5.4-2026-03-05",
        allow_large=True,
    )

    assert decision.resolved_model == FREE_TIER_DEFAULT_SMALL_TEXT_MODEL
    assert decision.resolved_bucket == "small"
    assert "non_free_model_replaced" in decision.reasons


def test_route_switches_large_to_small_at_half_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=LARGE_MODEL_SWITCH_THRESHOLD_TOKENS, small_used=0),
    )

    decision = route_openai_free_tier_text_model(
        db=object(),
        requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
        allow_large=True,
    )

    assert decision.large_threshold_reached is True
    assert decision.resolved_model == FREE_TIER_DEFAULT_SMALL_TEXT_MODEL
    assert "large_bucket_threshold_reached" in decision.reasons


def test_route_switches_large_to_small_above_half_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=LARGE_MODEL_SWITCH_THRESHOLD_TOKENS + 1, small_used=0),
    )

    decision = route_openai_free_tier_text_model(
        db=object(),
        requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
        allow_large=True,
    )

    assert decision.large_threshold_reached is True
    assert decision.resolved_model == FREE_TIER_DEFAULT_SMALL_TEXT_MODEL
    assert "large_bucket_threshold_reached" in decision.reasons


def test_route_keeps_large_model_before_half_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=LARGE_MODEL_SWITCH_THRESHOLD_TOKENS - 1, small_used=0),
    )

    decision = route_openai_free_tier_text_model(
        db=object(),
        requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
        allow_large=True,
    )

    assert decision.large_threshold_reached is False
    assert decision.resolved_model == FREE_TIER_DEFAULT_LARGE_TEXT_MODEL
    assert decision.resolved_bucket == "large"


def test_route_allows_large_when_small_exhausted_but_large_under_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=100_000, small_used=SMALL_MODEL_LIMIT),
    )

    decision = route_openai_free_tier_text_model(
        db=object(),
        requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
        allow_large=True,
    )

    assert decision.resolved_model == FREE_TIER_DEFAULT_LARGE_TEXT_MODEL
    assert decision.resolved_bucket == "large"


def test_route_blocks_when_small_bucket_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: _usage(large_used=LARGE_MODEL_SWITCH_THRESHOLD_TOKENS, small_used=SMALL_MODEL_LIMIT),
    )

    with pytest.raises(ProviderRuntimeError) as exc_info:
        route_openai_free_tier_text_model(
            db=object(),
            requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
            allow_large=True,
        )

    assert exc_info.value.status_code == 429
    assert "small model quota exhausted" in exc_info.value.message.lower()


def test_route_fail_open_to_small_when_usage_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: (_ for _ in ()).throw(
            ProviderRuntimeError(
                provider="openai_usage",
                status_code=500,
                message="Failed to fetch OpenAI usage.",
                detail="upstream timeout",
            )
        ),
    )
    monkeypatch.setattr(openai_usage_service, "_LAST_USAGE_CACHE", None)
    monkeypatch.setattr(openai_usage_service, "_LAST_USAGE_CACHE_AT", None)

    decision = route_openai_free_tier_text_model(
        db=object(),
        requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
        allow_large=True,
    )

    assert decision.resolved_model == FREE_TIER_DEFAULT_SMALL_TEXT_MODEL
    assert "usage_fetch_failed_fallback_small" in decision.reasons


def test_route_uses_cached_usage_when_usage_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        openai_usage_service,
        "get_openai_free_usage",
        lambda _db: (_ for _ in ()).throw(
            ProviderRuntimeError(
                provider="openai_usage",
                status_code=503,
                message="Failed to fetch OpenAI usage.",
                detail="service unavailable",
            )
        ),
    )
    monkeypatch.setattr(
        openai_usage_service,
        "_LAST_USAGE_CACHE",
        _usage(large_used=100_000, small_used=10_000),
    )
    monkeypatch.setattr(
        openai_usage_service,
        "_LAST_USAGE_CACHE_AT",
        datetime.now(timezone.utc),
    )

    decision = route_openai_free_tier_text_model(
        db=object(),
        requested_model=FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
        allow_large=True,
    )

    assert decision.resolved_model == FREE_TIER_DEFAULT_LARGE_TEXT_MODEL
    assert "usage_fetch_failed_cached" in decision.reasons


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


def test_stage_policy_allows_large_for_prompt_stages() -> None:
    assert _stage_allows_large_text_model(WorkflowStageType.TOPIC_DISCOVERY) is True
    assert _stage_allows_large_text_model(WorkflowStageType.ARTICLE_GENERATION) is True
    assert _stage_allows_large_text_model(WorkflowStageType.IMAGE_PROMPT_GENERATION) is True


def test_stage_default_article_model_is_large() -> None:
    runtime = SimpleNamespace(topic_discovery_model="", openai_text_model=FREE_TIER_DEFAULT_SMALL_TEXT_MODEL)

    resolved = _resolve_stage_text_model(
        stage_type=WorkflowStageType.ARTICLE_GENERATION,
        configured_model=None,
        runtime=runtime,
    )

    assert resolved == FREE_TIER_DEFAULT_LARGE_TEXT_MODEL
