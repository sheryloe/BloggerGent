from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.schemas.api import OpenAIFreeUsageBucketRead, OpenAIFreeUsageRead
from app.services.providers.base import ProviderRuntimeError
from app.services.settings_service import get_settings_map

OPENAI_USAGE_ENDPOINT = "https://api.openai.com/v1/organization/usage/completions"

LARGE_MODEL_LIMIT = 1_000_000
SMALL_MODEL_LIMIT = 10_000_000

LARGE_MODEL_PREFIXES = (
    "gpt-5.4",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-chat-latest",
    "gpt-4.1",
    "gpt-4o",
)
SMALL_MODEL_PREFIXES = (
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.1-codex-mini",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o-mini",
    "codex-mini-latest",
)

LARGE_MODEL_EXACT = {"o1", "o3", "gpt-5.1-codex", "gpt-5-codex"}
SMALL_MODEL_EXACT = {"o1-mini", "o3-mini", "o4-mini"}


@dataclass(slots=True)
class UsageBucket:
    limit_tokens: int
    used_tokens: int = 0
    matched_models: set[str] | None = None

    def __post_init__(self) -> None:
        if self.matched_models is None:
            self.matched_models = set()


def _utc_day_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _normalize_model_name(model: str | None) -> str:
    return (model or "").strip().lower()


def _is_large_model(model: str) -> bool:
    if model in LARGE_MODEL_EXACT:
        return True
    if model.startswith(("o1-", "o3-")) and "mini" not in model:
        return True
    return any(model.startswith(prefix) for prefix in LARGE_MODEL_PREFIXES) and "mini" not in model and "nano" not in model


def _is_small_model(model: str) -> bool:
    if model in SMALL_MODEL_EXACT:
        return True
    return any(model.startswith(prefix) for prefix in SMALL_MODEL_PREFIXES)


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
            message="OpenAI API 키가 없습니다.",
            detail="OpenAI API Key를 먼저 저장해 주세요.",
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
                message="조직 사용량 조회는 OpenAI Admin API Key가 필요할 수 있습니다.",
                detail=detail,
            )

        raise ProviderRuntimeError(
            provider="openai_usage",
            status_code=response.status_code,
            message="OpenAI 사용량 조회에 실패했습니다.",
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
        large=_bucket_to_read("대형 모델", large),
        small=_bucket_to_read("소형 모델", small),
        warning=(
            "무료 토큰은 OpenAI 데이터 공유 활성화 트래픽에만 적용됩니다. 잔량 기준은 오늘 UTC 사용량입니다."
        ),
    )
