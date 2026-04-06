from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.models.entities import (
    Blog,
    GoogleIndexRequestLog,
    GoogleIndexUrlState,
    SearchConsolePageMetric,
    SyncedBloggerPost,
)
from app.services.blogger_oauth_service import (
    BloggerOAuthError,
    INDEXING_SCOPE,
    authorized_google_request,
    has_granted_google_scope,
)
from app.services.settings_service import get_settings_map

INDEXING_PUBLISH_URL = "https://indexing.googleapis.com/v3/urlNotifications:publish"
INDEXING_METADATA_URL = "https://indexing.googleapis.com/v3/urlNotifications/metadata"
URL_INSPECTION_INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
SEARCH_CONSOLE_QUERY_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site_url}/searchAnalytics/query"

DEFAULT_POLICY_MODE = "mixed"
DEFAULT_DAILY_QUOTA = 200
DEFAULT_COOLDOWN_DAYS = 7
DEFAULT_REFRESH_LIMIT = 50
LA_TIMEZONE = ZoneInfo("America/Los_Angeles")
URL_INSPECTION_FREE_DAILY_LIMIT = 2000
URL_INSPECTION_FREE_QPM_LIMIT = 600


@dataclass(slots=True)
class GoogleIndexingConfig:
    enabled: bool
    policy_mode: str
    daily_quota: int
    cooldown_days: int
    blog_quota_map: dict[int, int]


def _to_bool(value: str | bool | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _to_int(value: str | int | None, fallback: int, *, minimum: int = 0) -> int:
    try:
        parsed = int(str(value if value is not None else fallback).strip())
    except (TypeError, ValueError):
        return fallback
    return max(parsed, minimum)


def _normalize_url(value: str) -> str:
    return str(value or "").strip()


def _parse_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _response_detail(payload: dict[str, Any], fallback: str) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or fallback)
    if isinstance(error, str):
        return error
    return fallback


def _parse_blog_quota_map(raw_value: str | None) -> dict[int, int]:
    if not (raw_value or "").strip():
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    parsed: dict[int, int] = {}
    for key, value in payload.items():
        try:
            blog_id = int(str(key).strip())
            quota = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if blog_id <= 0:
            continue
        parsed[blog_id] = max(quota, 0)
    return parsed


def get_google_indexing_config(db: Session) -> GoogleIndexingConfig:
    values = get_settings_map(db)
    policy_mode = (values.get("google_indexing_policy_mode") or DEFAULT_POLICY_MODE).strip().lower() or DEFAULT_POLICY_MODE
    if policy_mode != DEFAULT_POLICY_MODE:
        policy_mode = DEFAULT_POLICY_MODE
    return GoogleIndexingConfig(
        enabled=_to_bool(values.get("automation_google_indexing_enabled"), default=False),
        policy_mode=policy_mode,
        daily_quota=_to_int(values.get("google_indexing_daily_quota"), DEFAULT_DAILY_QUOTA, minimum=1),
        cooldown_days=_to_int(values.get("google_indexing_cooldown_days"), DEFAULT_COOLDOWN_DAYS, minimum=1),
        blog_quota_map=_parse_blog_quota_map(values.get("google_indexing_blog_quota_map")),
    )


def has_required_indexing_scope(values: dict[str, str] | None = None) -> bool:
    return has_granted_google_scope(INDEXING_SCOPE, values)


def _la_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime, str]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(LA_TIMEZONE)
    day_start_local = datetime(local.year, local.month, local.day, tzinfo=LA_TIMEZONE)
    day_end_local = day_start_local + timedelta(days=1)
    return day_start_local.astimezone(timezone.utc), day_end_local.astimezone(timezone.utc), day_start_local.date().isoformat()


def count_request_logs_for_la_day(
    db: Session,
    *,
    request_type: str,
    now: datetime | None = None,
    blog_id: int | None = None,
) -> int:
    day_start_utc, day_end_utc, _ = _la_day_bounds(now)
    filters = [
        GoogleIndexRequestLog.request_type == request_type,
        GoogleIndexRequestLog.created_at >= day_start_utc,
        GoogleIndexRequestLog.created_at < day_end_utc,
    ]
    if blog_id is not None:
        filters.append(GoogleIndexRequestLog.blog_id == blog_id)
    return int(
        db.execute(
            select(func.count(GoogleIndexRequestLog.id)).where(*filters)
        ).scalar()
        or 0
    )


def count_publish_requests_for_la_day(db: Session, *, now: datetime | None = None) -> int:
    return count_request_logs_for_la_day(db, request_type="publish", now=now)


def remaining_publish_quota_for_la_day(db: Session, daily_quota: int, *, now: datetime | None = None) -> int:
    used = count_publish_requests_for_la_day(db, now=now)
    return max(daily_quota - used, 0)


def get_google_blog_indexing_quota(
    db: Session,
    *,
    blog_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    config = get_google_indexing_config(db)
    publish_used = count_publish_requests_for_la_day(db, now=now)
    publish_remaining = max(config.daily_quota - publish_used, 0)
    inspection_used = count_request_logs_for_la_day(
        db,
        request_type="inspection",
        now=now,
        blog_id=blog_id,
    )
    inspection_remaining = max(URL_INSPECTION_FREE_DAILY_LIMIT - inspection_used, 0)
    _day_start_utc, _day_end_utc, day_key = _la_day_bounds(now)
    return {
        "day_key": day_key,
        "blog_id": blog_id,
        "publish_used": publish_used,
        "publish_limit": config.daily_quota,
        "publish_remaining": publish_remaining,
        "inspection_used": inspection_used,
        "inspection_limit": URL_INSPECTION_FREE_DAILY_LIMIT,
        "inspection_remaining": inspection_remaining,
        "inspection_qpm_limit": URL_INSPECTION_FREE_QPM_LIMIT,
    }


def _blog_publish_allocation(*, blog_ids: list[int], total_quota: int, configured: dict[int, int]) -> dict[int, int]:
    if total_quota <= 0 or not blog_ids:
        return {blog_id: 0 for blog_id in blog_ids}

    has_explicit_quota = any(configured.get(blog_id, 0) > 0 for blog_id in blog_ids)
    allocations: dict[int, int] = {blog_id: 0 for blog_id in blog_ids}

    if has_explicit_quota:
        remaining = total_quota
        for blog_id in blog_ids:
            requested = max(configured.get(blog_id, 0), 0)
            assigned = min(requested, remaining)
            allocations[blog_id] = assigned
            remaining -= assigned
            if remaining <= 0:
                break
        return allocations

    base = total_quota // len(blog_ids)
    remainder = total_quota % len(blog_ids)
    for index, blog_id in enumerate(blog_ids):
        allocations[blog_id] = base + (1 if index < remainder else 0)
    return allocations


def _list_candidate_urls(db: Session, *, blog_id: int, limit: int = 200) -> list[str]:
    posts = db.execute(
        select(SyncedBloggerPost)
        .where(
            SyncedBloggerPost.blog_id == blog_id,
            SyncedBloggerPost.url.is_not(None),
            SyncedBloggerPost.url != "",
        )
        .order_by(SyncedBloggerPost.updated_at_remote.desc(), SyncedBloggerPost.published_at.desc(), SyncedBloggerPost.id.desc())
        .limit(limit)
    ).scalars().all()

    seen: set[str] = set()
    urls: list[str] = []
    for post in posts:
        url = _normalize_url(post.url or "")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _get_or_create_url_state(db: Session, *, blog_id: int, url: str) -> GoogleIndexUrlState:
    state = db.execute(
        select(GoogleIndexUrlState).where(
            GoogleIndexUrlState.blog_id == blog_id,
            GoogleIndexUrlState.url == url,
        )
    ).scalar_one_or_none()
    if state is not None:
        return state
    state = GoogleIndexUrlState(blog_id=blog_id, url=url, index_status="unknown")
    db.add(state)
    db.flush()
    return state


def _derive_index_status(
    *,
    coverage_state: str | None,
    index_state: str | None,
    verdict: str | None,
    last_notify_time: datetime | None,
    last_publish_success: bool | None,
) -> str:
    coverage = (coverage_state or "").strip().lower()
    indexing = (index_state or "").strip().lower()
    verdict_text = (verdict or "").strip().lower()

    if "indexed" in coverage or verdict_text == "pass":
        return "indexed"
    if "blocked" in coverage or "blocked" in indexing or verdict_text == "fail":
        return "blocked"
    if last_publish_success is False:
        return "failed"
    if last_notify_time is not None:
        return "submitted"
    if any(token in coverage for token in ("submitted", "discovered", "crawled", "pending", "unknown")):
        return "pending"
    if "pending" in indexing or "unknown" in indexing:
        return "pending"
    return "unknown"


def _pick_last_notify_time(metadata_payload: dict[str, Any]) -> datetime | None:
    candidate_times: list[datetime] = []
    latest_update = metadata_payload.get("latestUpdate")
    latest_remove = metadata_payload.get("latestRemove")
    if isinstance(latest_update, dict):
        parsed = _parse_datetime(str(latest_update.get("notifyTime") or ""))
        if parsed is not None:
            candidate_times.append(parsed)
    if isinstance(latest_remove, dict):
        parsed = _parse_datetime(str(latest_remove.get("notifyTime") or ""))
        if parsed is not None:
            candidate_times.append(parsed)
    if not candidate_times:
        return None
    return max(candidate_times)


def _record_request_log(
    db: Session,
    *,
    blog_id: int,
    url: str,
    request_type: str,
    trigger_mode: str,
    is_force: bool,
    success: bool,
    http_status: int | None,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    error_message: str | None = None,
) -> None:
    db.add(
        GoogleIndexRequestLog(
            blog_id=blog_id,
            url=url,
            request_type=request_type,
            trigger_mode=trigger_mode,
            is_force=is_force,
            success=success,
            http_status=http_status,
            error_message=error_message,
            request_payload=request_payload,
            response_payload=response_payload,
        )
    )


def _fetch_indexing_metadata(db: Session, *, blog_id: int, url: str, trigger_mode: str) -> tuple[dict[str, Any], int]:
    response = authorized_google_request(
        db,
        "GET",
        INDEXING_METADATA_URL,
        params={"url": url},
        timeout=60.0,
    )
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"raw": response.text}

    success = response.is_success
    error_message = None
    if not success:
        error_message = _response_detail(payload, response.text or "metadata request failed")

    _record_request_log(
        db,
        blog_id=blog_id,
        url=url,
        request_type="metadata",
        trigger_mode=trigger_mode,
        is_force=False,
        success=success,
        http_status=response.status_code,
        request_payload={"url": url},
        response_payload=payload,
        error_message=error_message,
    )

    if not success:
        raise BloggerOAuthError(
            "Indexing metadata 조회에 실패했습니다.",
            detail=error_message or "metadata request failed",
            status_code=response.status_code,
        )
    return payload if isinstance(payload, dict) else {}, int(response.status_code)


def _fetch_url_inspection(
    db: Session,
    *,
    blog_id: int,
    site_url: str,
    url: str,
    trigger_mode: str,
) -> tuple[dict[str, Any], int]:
    request_payload = {
        "inspectionUrl": url,
        "siteUrl": site_url,
        "languageCode": "en-US",
    }
    response = authorized_google_request(
        db,
        "POST",
        URL_INSPECTION_INSPECT_URL,
        json=request_payload,
        timeout=60.0,
    )
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"raw": response.text}

    success = response.is_success
    error_message = None
    if not success:
        error_message = _response_detail(payload, response.text or "inspection request failed")

    _record_request_log(
        db,
        blog_id=blog_id,
        url=url,
        request_type="inspection",
        trigger_mode=trigger_mode,
        is_force=False,
        success=success,
        http_status=response.status_code,
        request_payload=request_payload,
        response_payload=payload,
        error_message=error_message,
    )

    if not success:
        raise BloggerOAuthError(
            "URL Inspection 조회에 실패했습니다.",
            detail=error_message or "inspection request failed",
            status_code=response.status_code,
        )

    return payload if isinstance(payload, dict) else {}, int(response.status_code)


def _is_publish_eligible(url: str, policy_mode: str) -> bool:
    if policy_mode != DEFAULT_POLICY_MODE:
        return True
    normalized = url.lower()
    return any(token in normalized for token in ("/job", "/jobs", "/live", "/livestream"))


def refresh_search_console_ctr_cache(
    db: Session,
    *,
    blog: Blog,
    days: int = 28,
    row_limit: int = 250,
    trigger_mode: str = "auto",
) -> dict[str, Any]:
    site_url = (blog.search_console_site_url or "").strip()
    if not site_url:
        return {"status": "skipped", "reason": "search_console_not_connected", "blog_id": blog.id, "rows": 0}

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=max(days - 1, 0))
    encoded_site = quote(site_url, safe="")
    request_payload = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "type": "web",
        "dimensions": ["page"],
        "rowLimit": max(1, min(row_limit, 1000)),
    }
    response = authorized_google_request(
        db,
        "POST",
        SEARCH_CONSOLE_QUERY_URL.format(site_url=encoded_site),
        json=request_payload,
        timeout=60.0,
    )
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"raw": response.text}

    if not response.is_success:
        error_message = _response_detail(payload if isinstance(payload, dict) else {}, response.text)
        _record_request_log(
            db,
            blog_id=blog.id,
            url=site_url,
            request_type="ctr_refresh",
            trigger_mode=trigger_mode,
            is_force=False,
            success=False,
            http_status=response.status_code,
            request_payload=request_payload,
            response_payload=payload if isinstance(payload, dict) else {"raw": str(payload)},
            error_message=error_message,
        )
        db.commit()
        raise BloggerOAuthError(
            "Search Console 페이지 CTR 갱신에 실패했습니다.",
            detail=error_message,
            status_code=response.status_code,
        )

    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    next_fetch_at = datetime.now(timezone.utc)
    upserted = 0

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        keys = row.get("keys", []) or []
        url = _normalize_url(keys[0] if keys else "")
        if not url:
            continue
        item = db.execute(
            select(SearchConsolePageMetric).where(
                SearchConsolePageMetric.blog_id == blog.id,
                SearchConsolePageMetric.url == url,
            )
        ).scalar_one_or_none()
        if item is None:
            item = SearchConsolePageMetric(blog_id=blog.id, url=url)
            db.add(item)

        item.clicks = float(row.get("clicks", 0) or 0)
        item.impressions = float(row.get("impressions", 0) or 0)
        item.ctr = float(row.get("ctr", 0) or 0) if row.get("ctr") is not None else None
        item.position = float(row.get("position", 0) or 0) if row.get("position") is not None else None
        item.start_date = start_date
        item.end_date = end_date
        item.fetched_at = next_fetch_at
        item.payload = row if isinstance(row, dict) else {}
        upserted += 1

    _record_request_log(
        db,
        blog_id=blog.id,
        url=site_url,
        request_type="ctr_refresh",
        trigger_mode=trigger_mode,
        is_force=False,
        success=True,
        http_status=response.status_code,
        request_payload=request_payload,
        response_payload={"rows": upserted},
    )
    db.commit()
    return {
        "status": "ok",
        "blog_id": blog.id,
        "rows": upserted,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


def _apply_state_payloads(
    *,
    state: GoogleIndexUrlState,
    inspection_payload: dict[str, Any] | None,
    metadata_payload: dict[str, Any] | None,
) -> None:
    inspection = inspection_payload or {}
    metadata = metadata_payload or {}

    if inspection:
        result = inspection.get("inspectionResult") if isinstance(inspection.get("inspectionResult"), dict) else {}
        index_result = result.get("indexStatusResult") if isinstance(result.get("indexStatusResult"), dict) else {}
        state.index_coverage_state = str(index_result.get("coverageState") or "").strip() or None
        state.index_state = str(index_result.get("indexingState") or "").strip() or None
        state.verdict = str(index_result.get("verdict") or "").strip() or None
        state.last_crawl_time = _parse_datetime(str(index_result.get("lastCrawlTime") or ""))
        state.last_inspection_time = datetime.now(timezone.utc)
        state.inspection_payload = inspection

    if metadata:
        state.metadata_payload = metadata
        notify_time = _pick_last_notify_time(metadata)
        if notify_time is not None:
            state.last_notify_time = notify_time

    state.index_status = _derive_index_status(
        coverage_state=state.index_coverage_state,
        index_state=state.index_state,
        verdict=state.verdict,
        last_notify_time=state.last_notify_time,
        last_publish_success=state.last_publish_success,
    )


def _serialize_action_result(state: GoogleIndexUrlState, *, status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "blog_id": state.blog_id,
        "url": state.url,
        "index_status": state.index_status,
        "index_coverage_state": state.index_coverage_state,
        "last_crawl_time": state.last_crawl_time.isoformat() if state.last_crawl_time else None,
        "last_notify_time": state.last_notify_time.isoformat() if state.last_notify_time else None,
        "next_eligible_at": state.next_eligible_at.isoformat() if state.next_eligible_at else None,
        "index_last_checked_at": state.last_checked_at.isoformat() if state.last_checked_at else None,
        "last_error": state.last_error,
    }


def refresh_single_url_state(
    db: Session,
    *,
    blog: Blog,
    url: str,
    trigger_mode: str,
) -> GoogleIndexUrlState:
    normalized_url = _normalize_url(url)
    if not normalized_url:
        raise ValueError("URL is required")

    state = _get_or_create_url_state(db, blog_id=blog.id, url=normalized_url)
    now = datetime.now(timezone.utc)
    metadata_payload: dict[str, Any] = {}
    inspection_payload: dict[str, Any] = {}
    errors: list[str] = []

    try:
        metadata_payload, _ = _fetch_indexing_metadata(db, blog_id=blog.id, url=normalized_url, trigger_mode=trigger_mode)
    except BloggerOAuthError as exc:
        errors.append(f"metadata:{exc.detail}")

    site_url = (blog.search_console_site_url or "").strip()
    if site_url:
        try:
            inspection_payload, _ = _fetch_url_inspection(
                db,
                blog_id=blog.id,
                site_url=site_url,
                url=normalized_url,
                trigger_mode=trigger_mode,
            )
        except BloggerOAuthError as exc:
            errors.append(f"inspection:{exc.detail}")
    else:
        errors.append("inspection:search_console_not_connected")

    _apply_state_payloads(state=state, inspection_payload=inspection_payload, metadata_payload=metadata_payload)
    state.last_checked_at = now
    state.last_error = " | ".join(errors) if errors else None
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def request_single_url_indexing(
    db: Session,
    *,
    blog: Blog,
    url: str,
    force: bool,
    trigger_mode: str,
    policy_mode: str,
    cooldown_days: int,
) -> dict[str, Any]:
    normalized_url = _normalize_url(url)
    if not normalized_url:
        raise ValueError("URL is required")

    state = _get_or_create_url_state(db, blog_id=blog.id, url=normalized_url)
    now = datetime.now(timezone.utc)
    state.last_checked_at = now
    state.next_eligible_at = _ensure_utc(state.next_eligible_at)

    if not force and state.next_eligible_at and state.next_eligible_at > now:
        db.add(state)
        db.commit()
        db.refresh(state)
        return _serialize_action_result(state, status="skipped", reason="cooldown")

    if not _is_publish_eligible(normalized_url, policy_mode):
        db.add(state)
        db.commit()
        db.refresh(state)
        return _serialize_action_result(state, status="skipped", reason="policy_ineligible")

    request_payload = {"url": normalized_url, "type": "URL_UPDATED"}
    response = authorized_google_request(
        db,
        "POST",
        INDEXING_PUBLISH_URL,
        json=request_payload,
        timeout=60.0,
    )
    try:
        response_payload = response.json() if response.content else {}
    except ValueError:
        response_payload = {"raw": response.text}

    success = response.is_success
    error_message = None
    if not success:
        error_message = _response_detail(response_payload if isinstance(response_payload, dict) else {}, response.text)

    _record_request_log(
        db,
        blog_id=blog.id,
        url=normalized_url,
        request_type="publish",
        trigger_mode=trigger_mode,
        is_force=force,
        success=success,
        http_status=response.status_code,
        request_payload=request_payload,
        response_payload=response_payload if isinstance(response_payload, dict) else {"raw": str(response_payload)},
        error_message=error_message,
    )

    state.last_publish_at = now
    state.last_publish_success = success
    state.last_publish_http_status = int(response.status_code)
    state.publish_payload = response_payload if isinstance(response_payload, dict) else {"raw": str(response_payload)}
    if success:
        if isinstance(response_payload, dict):
            metadata = response_payload.get("urlNotificationMetadata")
            if isinstance(metadata, dict):
                state.metadata_payload = metadata
                notify_time = _pick_last_notify_time(metadata)
                if notify_time is not None:
                    state.last_notify_time = notify_time
        state.next_eligible_at = now + timedelta(days=max(cooldown_days, 1))
        state.last_error = None
    else:
        state.last_error = error_message or "publish request failed"

    state.index_status = _derive_index_status(
        coverage_state=state.index_coverage_state,
        index_state=state.index_state,
        verdict=state.verdict,
        last_notify_time=state.last_notify_time,
        last_publish_success=state.last_publish_success,
    )
    db.add(state)
    db.commit()
    db.refresh(state)
    return _serialize_action_result(state, status="ok" if success else "failed", reason=error_message)


def refresh_indexing_status_for_blog(
    db: Session,
    *,
    blog: Blog,
    urls: list[str] | None = None,
    limit: int = DEFAULT_REFRESH_LIMIT,
    trigger_mode: str = "manual",
) -> dict[str, Any]:
    target_urls = [
        _normalize_url(item)
        for item in (urls or _list_candidate_urls(db, blog_id=blog.id, limit=limit))
        if _normalize_url(item)
    ]
    target_urls = target_urls[: max(1, limit)]

    refreshed = 0
    failed = 0
    results: list[dict[str, Any]] = []

    for url in target_urls:
        try:
            state = refresh_single_url_state(db, blog=blog, url=url, trigger_mode=trigger_mode)
            refreshed += 1
            results.append(_serialize_action_result(state, status="ok"))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            results.append(
                {
                    "status": "failed",
                    "reason": str(exc),
                    "blog_id": blog.id,
                    "url": url,
                }
            )

    return {
        "status": "ok" if failed == 0 else "partial",
        "blog_id": blog.id,
        "requested": len(target_urls),
        "refreshed": refreshed,
        "failed": failed,
        "results": results,
    }


def run_google_indexing_schedule(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    settings_map = get_settings_map(db)
    config = get_google_indexing_config(db)
    if not config.enabled:
        return {"status": "disabled", "reason": "automation_google_indexing_disabled"}
    if not has_required_indexing_scope(settings_map):
        return {"status": "skipped", "reason": "reauth_required_missing_indexing_scope"}

    blogs = db.execute(
        select(Blog)
        .where(Blog.is_active.is_(True))
        .order_by(Blog.id.asc())
    ).scalars().all()
    if not blogs:
        return {"status": "idle", "reason": "no_active_blogs"}

    remaining_quota = remaining_publish_quota_for_la_day(db, config.daily_quota, now=now)
    allocation = _blog_publish_allocation(
        blog_ids=[blog.id for blog in blogs],
        total_quota=remaining_quota,
        configured=config.blog_quota_map,
    )

    blog_results: list[dict[str, Any]] = []
    total_attempted = 0
    total_success = 0
    total_skipped = 0

    for blog in blogs:
        blog_result: dict[str, Any] = {
            "blog_id": blog.id,
            "blog_name": blog.name,
            "allocated": allocation.get(blog.id, 0),
            "attempted": 0,
            "success": 0,
            "skipped": 0,
            "results": [],
        }

        try:
            blog_result["ctr_cache"] = refresh_search_console_ctr_cache(db, blog=blog, trigger_mode="auto")
        except Exception as exc:  # noqa: BLE001
            blog_result["ctr_cache"] = {"status": "failed", "detail": str(exc)}

        refresh_limit = max(allocation.get(blog.id, 0) * 2, DEFAULT_REFRESH_LIMIT)
        blog_result["status_refresh"] = refresh_indexing_status_for_blog(
            db,
            blog=blog,
            limit=refresh_limit,
            trigger_mode="auto",
        )

        if remaining_quota <= 0 or allocation.get(blog.id, 0) <= 0:
            blog_results.append(blog_result)
            continue

        candidate_urls = _list_candidate_urls(db, blog_id=blog.id, limit=max(allocation.get(blog.id, 0) * 4, 100))
        for url in candidate_urls:
            if remaining_quota <= 0 or blog_result["attempted"] >= allocation.get(blog.id, 0):
                break
            result = request_single_url_indexing(
                db,
                blog=blog,
                url=url,
                force=False,
                trigger_mode="auto",
                policy_mode=config.policy_mode,
                cooldown_days=config.cooldown_days,
            )
            blog_result["results"].append(result)
            status = result.get("status")
            if status == "ok":
                blog_result["attempted"] += 1
                blog_result["success"] += 1
                total_attempted += 1
                total_success += 1
                remaining_quota -= 1
            elif status == "failed":
                blog_result["attempted"] += 1
                total_attempted += 1
                remaining_quota -= 1
            else:
                blog_result["skipped"] += 1
                total_skipped += 1

        blog_results.append(blog_result)

    return {
        "status": "ok" if total_attempted > 0 else "idle",
        "policy_mode": config.policy_mode,
        "daily_quota": config.daily_quota,
        "remaining_quota": remaining_quota,
        "attempted": total_attempted,
        "success": total_success,
        "skipped": total_skipped,
        "blogs": blog_results,
    }


def request_indexing_for_url(
    db: Session,
    *,
    blog_id: int,
    url: str,
    force: bool = False,
) -> dict[str, Any]:
    blog = db.execute(select(Blog).where(Blog.id == blog_id)).scalar_one_or_none()
    if blog is None:
        return {"status": "failed", "reason": "blog_not_found", "blog_id": blog_id, "url": _normalize_url(url)}

    settings_map = get_settings_map(db)
    if not has_required_indexing_scope(settings_map):
        return {
            "status": "skipped",
            "reason": "reauth_required_missing_indexing_scope",
            "blog_id": blog_id,
            "url": _normalize_url(url),
        }

    config = get_google_indexing_config(db)
    remaining_quota = remaining_publish_quota_for_la_day(db, config.daily_quota)
    if remaining_quota <= 0:
        return {
            "status": "skipped",
            "reason": "daily_quota_exhausted",
            "blog_id": blog_id,
            "url": _normalize_url(url),
            "daily_quota": config.daily_quota,
            "remaining_quota": 0,
        }
    return request_single_url_indexing(
        db,
        blog=blog,
        url=url,
        force=force,
        trigger_mode="manual",
        policy_mode=config.policy_mode,
        cooldown_days=config.cooldown_days,
    )


def refresh_indexing_for_blog(
    db: Session,
    *,
    blog_id: int,
    urls: list[str] | None = None,
    limit: int = DEFAULT_REFRESH_LIMIT,
) -> dict[str, Any]:
    blog = db.execute(select(Blog).where(Blog.id == blog_id)).scalar_one_or_none()
    if blog is None:
        return {"status": "failed", "reason": "blog_not_found", "blog_id": blog_id}

    refreshed = refresh_indexing_status_for_blog(db, blog=blog, urls=urls, limit=limit, trigger_mode="manual")
    try:
        ctr_result = refresh_search_console_ctr_cache(db, blog=blog, trigger_mode="manual")
    except Exception as exc:  # noqa: BLE001
        ctr_result = {"status": "failed", "detail": str(exc), "blog_id": blog.id}
    return {
        "status": refreshed.get("status", "ok"),
        "blog_id": blog_id,
        "refresh": refreshed,
        "ctr_cache": ctr_result,
    }


def _normalize_unique_urls(urls: list[str] | None) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for raw in urls or []:
        normalized = _normalize_url(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
    return items


def request_indexing_for_blog(
    db: Session,
    *,
    blog_id: int,
    count: int = 10,
    urls: list[str] | None = None,
    force: bool = False,
    run_test: bool = True,
    test_limit: int = 100,
) -> dict[str, Any]:
    blog = db.execute(select(Blog).where(Blog.id == blog_id)).scalar_one_or_none()
    if blog is None:
        return {"status": "failed", "reason": "blog_not_found", "blog_id": blog_id}

    settings_map = get_settings_map(db)
    if not has_required_indexing_scope(settings_map):
        return {
            "status": "skipped",
            "reason": "reauth_required_missing_indexing_scope",
            "blog_id": blog_id,
        }

    config = get_google_indexing_config(db)
    requested_count = max(int(count or 0), 1)
    remaining_quota_before = remaining_publish_quota_for_la_day(db, config.daily_quota)
    planned_count = min(requested_count, remaining_quota_before)

    candidate_urls = _normalize_unique_urls(urls)
    if not candidate_urls:
        candidate_urls = _list_candidate_urls(
            db,
            blog_id=blog_id,
            limit=max(planned_count * 6, requested_count * 3, 120),
        )

    if not candidate_urls:
        return {
            "status": "idle",
            "reason": "no_candidate_urls",
            "blog_id": blog_id,
            "requested_count": requested_count,
            "planned_count": planned_count,
            "daily_quota": config.daily_quota,
            "remaining_quota_before": remaining_quota_before,
            "remaining_quota_after": remaining_quota_before,
            "run_test": bool(run_test),
            "test": {"status": "skipped", "reason": "no_candidate_urls"},
            "results": [],
        }

    normalized_test_limit = max(1, min(int(test_limit or 100), 1000))
    test_result: dict[str, Any] | None = None
    if run_test:
        if urls:
            test_urls = candidate_urls[:normalized_test_limit]
        else:
            test_target = max(requested_count * 2, planned_count * 2, 20)
            test_urls = candidate_urls[: min(test_target, normalized_test_limit)]
        test_result = refresh_indexing_status_for_blog(
            db,
            blog=blog,
            urls=test_urls,
            limit=max(1, len(test_urls)),
            trigger_mode="manual",
        )

    if remaining_quota_before <= 0:
        return {
            "status": "skipped",
            "reason": "daily_quota_exhausted",
            "blog_id": blog_id,
            "requested_count": requested_count,
            "planned_count": 0,
            "daily_quota": config.daily_quota,
            "remaining_quota_before": remaining_quota_before,
            "remaining_quota_after": remaining_quota_before,
            "candidate_count": len(candidate_urls),
            "run_test": bool(run_test),
            "test": test_result or {"status": "skipped", "reason": "not_requested"},
            "results": [],
        }

    attempted = 0
    success = 0
    failed = 0
    skipped = 0
    results: list[dict[str, Any]] = []

    for url in candidate_urls:
        if attempted >= planned_count:
            break
        result = request_single_url_indexing(
            db,
            blog=blog,
            url=url,
            force=force,
            trigger_mode="manual",
            policy_mode=config.policy_mode,
            cooldown_days=config.cooldown_days,
        )
        results.append(result)
        status = str(result.get("status") or "")
        if status == "ok":
            attempted += 1
            success += 1
        elif status == "failed":
            attempted += 1
            failed += 1
        else:
            skipped += 1

    remaining_quota_after = remaining_publish_quota_for_la_day(db, config.daily_quota)

    status_value = "ok"
    if attempted == 0 and failed == 0 and success == 0:
        status_value = "idle"
    elif success == 0 and failed > 0:
        status_value = "failed"
    elif failed > 0 or skipped > 0:
        status_value = "partial"

    return {
        "status": status_value,
        "blog_id": blog_id,
        "requested_count": requested_count,
        "planned_count": planned_count,
        "candidate_count": len(candidate_urls),
        "attempted": attempted,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "daily_quota": config.daily_quota,
        "remaining_quota_before": remaining_quota_before,
        "remaining_quota_after": remaining_quota_after,
        "run_test": bool(run_test),
        "test": test_result or {"status": "skipped", "reason": "not_requested"},
        "results": results,
    }


def load_fact_enrichment_maps(
    db: Session,
    *,
    pairs: set[tuple[int, str]],
) -> tuple[dict[tuple[int, str], GoogleIndexUrlState], dict[tuple[int, str], SearchConsolePageMetric]]:
    if not pairs:
        return {}, {}

    normalized_pairs = {(blog_id, _normalize_url(url)) for blog_id, url in pairs if _normalize_url(url)}
    if not normalized_pairs:
        return {}, {}

    states = db.execute(
        select(GoogleIndexUrlState).where(tuple_(GoogleIndexUrlState.blog_id, GoogleIndexUrlState.url).in_(list(normalized_pairs)))
    ).scalars().all()
    ctr_rows = db.execute(
        select(SearchConsolePageMetric).where(tuple_(SearchConsolePageMetric.blog_id, SearchConsolePageMetric.url).in_(list(normalized_pairs)))
    ).scalars().all()

    state_map = {(item.blog_id, item.url): item for item in states}
    ctr_map = {(item.blog_id, item.url): item for item in ctr_rows}
    return state_map, ctr_map
