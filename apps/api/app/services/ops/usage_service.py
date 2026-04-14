from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.models.entities import AIUsageEvent, Article, Blog, Job
from app.services.providers.factory import get_runtime_config


def _as_dict(payload: object) -> dict:
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def extract_token_usage(raw_response: object) -> tuple[int, int]:
    payload = _as_dict(raw_response)
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        return _safe_int(usage.get("prompt_tokens") or usage.get("input_tokens")), _safe_int(
            usage.get("completion_tokens") or usage.get("output_tokens")
        )
    return 0, 0


def record_usage_event(
    db: Session,
    *,
    blog_id: int,
    stage_type: str,
    provider_name: str,
    endpoint: str,
    provider_model: str | None = None,
    job_id: int | None = None,
    article_id: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_usd: float | None = None,
    request_count: int = 1,
    latency_ms: int | None = None,
    image_count: int = 0,
    image_width: int | None = None,
    image_height: int | None = None,
    success: bool = True,
    error_message: str | None = None,
    raw_usage: dict | None = None,
) -> AIUsageEvent:
    runtime = get_runtime_config(db)
    event = AIUsageEvent(
        blog_id=blog_id,
        job_id=job_id,
        article_id=article_id,
        stage_type=stage_type,
        provider_mode=runtime.provider_mode,
        provider_name=provider_name,
        provider_model=provider_model,
        endpoint=endpoint,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        request_count=request_count,
        latency_ms=latency_ms,
        image_count=image_count,
        image_width=image_width,
        image_height=image_height,
        success=success,
        error_message=error_message,
        raw_usage=raw_usage or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def record_text_generation_usage(
    db: Session,
    *,
    blog_id: int,
    job_id: int | None,
    article_id: int | None,
    stage_type: str,
    provider_name: str,
    provider_model: str | None,
    endpoint: str,
    raw_response: object,
) -> AIUsageEvent:
    input_tokens, output_tokens = extract_token_usage(raw_response)
    payload = _as_dict(raw_response)
    return record_usage_event(
        db,
        blog_id=blog_id,
        job_id=job_id,
        article_id=article_id,
        stage_type=stage_type,
        provider_name=provider_name,
        provider_model=provider_model,
        endpoint=endpoint,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        raw_usage=_as_dict(payload.get("usage")) or payload,
    )


def record_image_generation_usage(
    db: Session,
    *,
    blog_id: int,
    job_id: int | None,
    article_id: int | None,
    stage_type: str,
    provider_name: str,
    provider_model: str | None,
    endpoint: str,
    raw_response: object,
) -> AIUsageEvent:
    payload = _as_dict(raw_response)
    return record_usage_event(
        db,
        blog_id=blog_id,
        job_id=job_id,
        article_id=article_id,
        stage_type=stage_type,
        provider_name=provider_name,
        provider_model=provider_model,
        endpoint=endpoint,
        image_count=max(1, len(payload.get("data") or [])) if isinstance(payload.get("data"), list) else 1,
        image_width=_safe_int(payload.get("width")) or None,
        image_height=_safe_int(payload.get("height")) or None,
        raw_usage=payload,
    )


def record_mock_usage(
    db: Session,
    *,
    blog_id: int,
    job_id: int | None,
    article_id: int | None,
    stage_type: str,
    provider_name: str,
    provider_model: str,
    endpoint: str,
    raw_usage: dict | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    image_count: int = 0,
) -> AIUsageEvent:
    return record_usage_event(
        db,
        blog_id=blog_id,
        job_id=job_id,
        article_id=article_id,
        stage_type=stage_type,
        provider_name=provider_name,
        provider_model=provider_model,
        endpoint=endpoint,
        image_width=image_width,
        image_height=image_height,
        image_count=image_count,
        estimated_cost_usd=0.0,
        raw_usage=raw_usage or {},
    )


def usage_summary_for_article(article: Article | None) -> dict | None:
    if not article:
        return None
    return article.usage_summary


def link_usage_events_to_article(db: Session, *, job: Job, article: Article) -> None:
    updated = False
    for event in list(job.ai_usage_events or []):
        if event.article_id is not None:
            continue
        event.article_id = article.id
        db.add(event)
        updated = True
    if updated:
        db.commit()


def summarize_usage_events_for_blog(blog: Blog) -> dict:
    total_tokens = sum(int(item.total_tokens or 0) for item in blog.ai_usage_events or [])
    return {
        "event_count": len(blog.ai_usage_events or []),
        "total_tokens": total_tokens,
    }
