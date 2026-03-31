from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.schemas.api import OpenAIFreeUsageBucketRead, OpenAIFreeUsageRead
from app.services.providers.base import ProviderRuntimeError
from app.services.model_policy_service import DEFAULT_LIGHTWEIGHT_MODEL, DEFAULT_TEXT_MODEL, FREE_MODEL_POLICY
from app.services.settings_service import get_settings_map

OPENAI_USAGE_ENDPOINT = "https://api.openai.com/v1/organization/usage/completions"

LARGE_MODEL_LIMIT = 1_000_000
SMALL_MODEL_LIMIT = 10_000_000
LARGE_MODEL_SWITCH_RATIO = 0.5
LARGE_MODEL_SWITCH_THRESHOLD_TOKENS = int(LARGE_MODEL_LIMIT * LARGE_MODEL_SWITCH_RATIO)
USAGE_CACHE_TTL_SECONDS = 180

FREE_TIER_DEFAULT_LARGE_TEXT_MODEL = DEFAULT_TEXT_MODEL
FREE_TIER_DEFAULT_SMALL_TEXT_MODEL = DEFAULT_LIGHTWEIGHT_MODEL

FREE_TIER_LARGE_MODEL_ALIASES = {
    "gpt-5": "gpt-5-2025-08-07",
    "gpt-5-chat-latest": "gpt-5-chat-latest",
    "gpt-4.1": "gpt-4.1-2025-04-14",
    "gpt-4o": "gpt-4o-2024-11-20",
    "o3": "o3-2025-04-16",
    "o1": "o1-2024-12-17",
}

FREE_TIER_SMALL_MODEL_ALIASES = {
    "gpt-5-mini": "gpt-5-mini-2025-08-07",
    "gpt-5-nano": "gpt-5-nano-2025-08-07",
    "gpt-4.1-mini": "gpt-4.1-mini-2025-04-14",
    "gpt-4.1-nano": "gpt-4.1-nano-2025-04-14",
    "gpt-4o-mini": "gpt-4o-mini-2024-07-18",
    "o4-mini": "o4-mini-2025-04-16",
    "o1-mini": "o1-mini-2024-09-12",
    "codex-mini": "codex-mini-latest",
}

FREE_TIER_LARGE_MODELS = set(FREE_MODEL_POLICY["large"])
FREE_TIER_SMALL_MODELS = set(FREE_MODEL_POLICY["small"])

_LAST_USAGE_CACHE: OpenAIFreeUsageRead | None = None
_LAST_USAGE_CACHE_AT: datetime | None = None


@dataclass(slots=True)
class UsageBucket:
    limit_tokens: int
    used_tokens: int = 0
    matched_models: set[str] | None = None

    def __post_init__(self) -> None:
        if self.matched_models is None:
            self.matched_models = set()


@dataclass(slots=True)
class FreeTierTextRoutingDecision:
    requested_model: str
    requested_bucket: str | None
    resolved_model: str
    resolved_bucket: str
    allow_large: bool
    large_threshold_tokens: int
    large_used_tokens: int
    large_limit_tokens: int
    large_threshold_reached: bool
    small_remaining_tokens: int
    small_limit_tokens: int
    minimum_remaining_tokens: int
    reasons: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "requested_model": self.requested_model,
            "requested_bucket": self.requested_bucket,
            "resolved_model": self.resolved_model,
            "resolved_bucket": self.resolved_bucket,
            "allow_large": self.allow_large,
            "large_threshold_tokens": self.large_threshold_tokens,
            "large_used_tokens": self.large_used_tokens,
            "large_limit_tokens": self.large_limit_tokens,
            "large_threshold_reached": self.large_threshold_reached,
            "small_remaining_tokens": self.small_remaining_tokens,
            "small_limit_tokens": self.small_limit_tokens,
            "minimum_remaining_tokens": self.minimum_remaining_tokens,
            "reasons": list(self.reasons),
        }


def _utc_day_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _normalize_model_name(model: str | None) -> str:
    return (model or "").strip().lower()


def _is_large_model(model: str) -> bool:
    normalized = _normalize_model_name(model)
    if not normalized:
        return False
    return normalized in FREE_TIER_LARGE_MODELS or normalized in FREE_TIER_LARGE_MODEL_ALIASES


def _is_small_model(model: str) -> bool:
    normalized = _normalize_model_name(model)
    if not normalized:
        return False
    return normalized in FREE_TIER_SMALL_MODELS or normalized in FREE_TIER_SMALL_MODEL_ALIASES


def classify_model_bucket(model: str | None) -> str | None:
    normalized = _normalize_model_name(model)
    if not normalized:
        return None
    if _is_small_model(normalized):
        return "small"
    if _is_large_model(normalized):
        return "large"
    return None


def _canonical_free_tier_text_model(model: str | None) -> tuple[str | None, str | None]:
    normalized = _normalize_model_name(model)
    if not normalized:
        return None, None

    if normalized in FREE_TIER_SMALL_MODELS:
        return normalized, "small"
    if normalized in FREE_TIER_SMALL_MODEL_ALIASES:
        return FREE_TIER_SMALL_MODEL_ALIASES[normalized], "small"

    if normalized in FREE_TIER_LARGE_MODELS:
        return normalized, "large"
    if normalized in FREE_TIER_LARGE_MODEL_ALIASES:
        return FREE_TIER_LARGE_MODEL_ALIASES[normalized], "large"

    return None, None


def resolve_free_tier_text_model(model: str | None, *, allow_large: bool) -> str:
    if not _normalize_model_name(model):
        return FREE_TIER_DEFAULT_LARGE_TEXT_MODEL if allow_large else FREE_TIER_DEFAULT_SMALL_TEXT_MODEL

    canonical_model, canonical_bucket = _canonical_free_tier_text_model(model)
    if canonical_model and canonical_bucket == "small":
        return canonical_model

    if canonical_model and canonical_bucket == "large" and allow_large:
        return canonical_model

    return FREE_TIER_DEFAULT_SMALL_TEXT_MODEL


def route_openai_free_tier_text_model(
    db: Session,
    *,
    requested_model: str | None,
    allow_large: bool,
    minimum_remaining_tokens: int = 1,
) -> FreeTierTextRoutingDecision:
    normalized_requested = _normalize_model_name(requested_model)
    requested_bucket = classify_model_bucket(normalized_requested)
    canonical_requested_model, canonical_requested_bucket = _canonical_free_tier_text_model(requested_model)

    reasons: list[str] = []
    if normalized_requested and canonical_requested_model is None:
        reasons.append("non_free_model_replaced")
    if canonical_requested_bucket == "large" and not allow_large:
        reasons.append("stage_forced_small_model")

    resolved_model = resolve_free_tier_text_model(requested_model, allow_large=allow_large)
    resolved_bucket = classify_model_bucket(resolved_model) or "small"
    required_remaining = max(int(minimum_remaining_tokens), 1)
    now_utc = datetime.now(timezone.utc)
    usage: OpenAIFreeUsageRead
    usage_fail_open = False
    try:
        usage = get_openai_free_usage(db)
        _write_usage_cache(usage, now_utc)
    except Exception as exc:  # noqa: BLE001
        if not _should_fail_open_for_usage_error(exc):
            raise
        cached_usage = _read_usage_cache(now_utc)
        if cached_usage is not None:
            usage = cached_usage
            reasons.append("usage_fetch_failed_cached")
        else:
            usage = _empty_usage_snapshot(now_utc)
            usage_fail_open = True
            if resolved_bucket != "small":
                resolved_model = FREE_TIER_DEFAULT_SMALL_TEXT_MODEL
                resolved_bucket = "small"
            reasons.append("usage_fetch_failed_fallback_small")

    large_threshold_reached = int(usage.large.used_tokens) >= LARGE_MODEL_SWITCH_THRESHOLD_TOKENS
    if resolved_bucket == "large" and large_threshold_reached:
        resolved_model = FREE_TIER_DEFAULT_SMALL_TEXT_MODEL
        resolved_bucket = "small"
        reasons.append("large_bucket_threshold_reached")

    if (
        not usage_fail_open
        and resolved_bucket == "small"
        and int(usage.small.remaining_tokens) < required_remaining
    ):
        raise ProviderRuntimeError(
            provider="openai_usage",
            status_code=429,
            message="OpenAI free-tier small model quota exhausted.",
            detail=(
                f"small_remaining={usage.small.remaining_tokens}, required={required_remaining}, "
                f"requested_model={requested_model}, resolved_model={resolved_model}"
            ),
        )

    return FreeTierTextRoutingDecision(
        requested_model=normalized_requested,
        requested_bucket=requested_bucket,
        resolved_model=resolved_model,
        resolved_bucket=resolved_bucket,
        allow_large=allow_large,
        large_threshold_tokens=LARGE_MODEL_SWITCH_THRESHOLD_TOKENS,
        large_used_tokens=int(usage.large.used_tokens),
        large_limit_tokens=int(usage.large.limit_tokens),
        large_threshold_reached=large_threshold_reached,
        small_remaining_tokens=int(usage.small.remaining_tokens),
        small_limit_tokens=int(usage.small.limit_tokens),
        minimum_remaining_tokens=required_remaining,
        reasons=tuple(reasons),
    )


def assert_openai_free_tier_capacity(
    db: Session,
    *,
    model: str,
    minimum_remaining_tokens: int = 1,
) -> None:
    resolved_bucket = classify_model_bucket(model)
    if resolved_bucket not in {"small", "large"}:
        raise ProviderRuntimeError(
            provider="openai_usage",
            status_code=422,
            message="Model is not mapped to a free-tier token bucket.",
            detail=f"Unsupported or unmapped model: {model}",
        )

    usage = get_openai_free_usage(db)
    bucket = usage.small if resolved_bucket == "small" else usage.large
    if int(bucket.remaining_tokens) >= int(max(minimum_remaining_tokens, 1)):
        return

    raise ProviderRuntimeError(
        provider="openai_usage",
        status_code=429,
        message="OpenAI free-tier token quota exceeded.",
        detail=(
            f"bucket={bucket.label}, used={bucket.used_tokens}, "
            f"limit={bucket.limit_tokens}, remaining={bucket.remaining_tokens}, model={model}"
        ),
    )


def _bucket_to_read(label: str, bucket: UsageBucket) -> OpenAIFreeUsageBucketRead:
    remaining = max(bucket.limit_tokens - bucket.used_tokens, 0)
    usage_percent = 0.0
    if bucket.limit_tokens > 0:
        usage_percent = round((bucket.used_tokens / bucket.limit_tokens) * 100, 2)
    return OpenAIFreeUsageBucketRead(
        label=label,
        limit_tokens=bucket.limit_tokens,
        used_tokens=bucket.used_tokens,
        remaining_tokens=remaining,
        usage_percent=usage_percent,
        matched_models=sorted(bucket.matched_models or set()),
    )


def _is_usage_cache_fresh(now_utc: datetime) -> bool:
    if _LAST_USAGE_CACHE_AT is None:
        return False
    return (now_utc - _LAST_USAGE_CACHE_AT) <= timedelta(seconds=USAGE_CACHE_TTL_SECONDS)


def _read_usage_cache(now_utc: datetime) -> OpenAIFreeUsageRead | None:
    if _LAST_USAGE_CACHE is None:
        return None
    if not _is_usage_cache_fresh(now_utc):
        return None
    return _LAST_USAGE_CACHE


def _write_usage_cache(usage: OpenAIFreeUsageRead, now_utc: datetime) -> None:
    global _LAST_USAGE_CACHE, _LAST_USAGE_CACHE_AT
    _LAST_USAGE_CACHE = usage
    _LAST_USAGE_CACHE_AT = now_utc


def _empty_usage_snapshot(now_utc: datetime) -> OpenAIFreeUsageRead:
    start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    large = UsageBucket(limit_tokens=LARGE_MODEL_LIMIT, used_tokens=0)
    small = UsageBucket(limit_tokens=SMALL_MODEL_LIMIT, used_tokens=0)
    return OpenAIFreeUsageRead(
        date_label=f"{start.strftime('%Y-%m-%d')} UTC",
        window_start_utc=start.isoformat(),
        window_end_utc=now_utc.isoformat(),
        key_mode="unavailable",
        admin_key_configured=False,
        large=_bucket_to_read("Large Models", large),
        small=_bucket_to_read("Small Models", small),
        warning="Live usage unavailable; routing used fail-open fallback.",
    )


def _should_fail_open_for_usage_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPError | TimeoutError):
        return True
    if not isinstance(exc, ProviderRuntimeError):
        return False

    status_code = int(exc.status_code or 0)
    message = str(exc.message or "").strip().lower()
    detail = str(exc.detail or "").strip().lower()
    if status_code in {401, 403, 408, 429}:
        return True
    if status_code >= 500:
        return True
    if "failed to fetch openai usage" in message:
        return True
    if "organization usage" in message:
        return True
    if "timed out" in detail or "timeout" in detail:
        return True
    return False


def _extract_rows(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for bucket in payload.get("data", []):
        if isinstance(bucket, dict) and isinstance(bucket.get("results"), list):
            for row in bucket["results"]:
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def get_openai_free_usage(db: Session) -> OpenAIFreeUsageRead:
    values = get_settings_map(db)
    admin_key = (values.get("openai_admin_api_key") or "").strip()
    standard_key = (values.get("openai_api_key") or "").strip()
    api_key = admin_key or standard_key
    key_mode = "admin" if admin_key else "standard"

    if not api_key:
        raise ProviderRuntimeError(
            provider="openai_usage",
            status_code=400,
            message="OpenAI API key is not configured.",
            detail="Configure OpenAI API key in settings first.",
        )

    start, end = _utc_day_window()
    response = httpx.get(
        OPENAI_USAGE_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        params=[
            ("start_time", str(int(start.timestamp()))),
            ("end_time", str(int(end.timestamp()))),
            ("bucket_width", "1d"),
            ("group_by", "model"),
            ("limit", "1"),
        ],
        timeout=30.0,
    )

    if not response.is_success:
        detail = response.text
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message", detail)
        except ValueError:
            pass

        if response.status_code in {401, 403} and not admin_key:
            raise ProviderRuntimeError(
                provider="openai_usage",
                status_code=response.status_code,
                message="OpenAI Admin API key is required for organization usage.",
                detail=detail,
            )

        raise ProviderRuntimeError(
            provider="openai_usage",
            status_code=response.status_code,
            message="Failed to fetch OpenAI usage.",
            detail=detail,
        )

    payload = response.json()
    large = UsageBucket(limit_tokens=LARGE_MODEL_LIMIT)
    small = UsageBucket(limit_tokens=SMALL_MODEL_LIMIT)

    for row in _extract_rows(payload):
        model = _normalize_model_name(row.get("model"))
        if not model:
            continue
        input_tokens = int(row.get("input_tokens") or 0)
        output_tokens = int(row.get("output_tokens") or 0)
        total_tokens = input_tokens + output_tokens
        if total_tokens <= 0:
            continue

        if _is_small_model(model):
            small.used_tokens += total_tokens
            small.matched_models.add(model)
            continue

        if _is_large_model(model):
            large.used_tokens += total_tokens
            large.matched_models.add(model)

    return OpenAIFreeUsageRead(
        date_label=f"{start.strftime('%Y-%m-%d')} UTC",
        window_start_utc=start.isoformat(),
        window_end_utc=end.isoformat(),
        key_mode=key_mode,
        admin_key_configured=bool(admin_key),
        large=_bucket_to_read("Large Models", large),
        small=_bucket_to_read("Small Models", small),
        warning="Usage reflects today's UTC window and includes only free-tier model buckets.",
    )
