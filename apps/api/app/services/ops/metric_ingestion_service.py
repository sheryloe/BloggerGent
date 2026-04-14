from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Blog, ContentItem, GoogleIndexUrlState, ManagedChannel, MetricFact, SearchConsolePageMetric
from app.services.blogger.blogger_oauth_service import BloggerOAuthError
from app.services.integrations.google_indexing_service import refresh_indexing_for_blog
from app.services.integrations.google_reporting_service import query_analytics_overview, query_search_console_performance
from app.services.platform.platform_oauth_service import PlatformOAuthError, authorized_platform_request
from app.services.platform.platform_service import get_managed_channel_by_channel_id
from app.services.integrations.settings_service import get_settings_map

YOUTUBE_ANALYTICS_REPORTS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
INSTAGRAM_GRAPH_BASE_URL = "https://graph.facebook.com/{version}"
SUPPORTED_METRIC_PROVIDERS = {"blogger", "youtube", "instagram"}
LAST_SCORE_KEYS = ("seo_ctr", "watch_quality", "engagement_quality", "traffic_quality", "indexing_quality")
LEGACY_SCORE_KEY_MAP = {
    "ctr": "seo_ctr",
    "traffic": "traffic_quality",
    "indexing": "indexing_quality",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_url(value: str | None) -> str:
    return str(value or "").strip()


def _coerce_float(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return fallback


def _score_ratio(value: float | None, *, multiplier: float = 100.0) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(value * multiplier, 100.0)), 2)


def _score_relative(value: float | None, maximum: float) -> float | None:
    if value is None or maximum <= 0:
        return None
    return round(max(0.0, min((value / maximum) * 100.0, 100.0)), 2)


def _average_score(*values: float | None) -> float | None:
    valid = [float(value) for value in values if value is not None]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 2)


def _score_index_status(status: str | None) -> float:
    return {
        "indexed": 100.0,
        "submitted": 72.0,
        "pending": 45.0,
        "unknown": 20.0,
        "failed": 10.0,
        "blocked": 0.0,
    }.get(str(status or "").strip().lower(), 20.0)


def _resolve_absolute_url(base_url: str | None, page_path: str | None) -> str:
    raw_path = _normalize_url(page_path)
    if not raw_path:
        return ""
    if raw_path.startswith("http://") or raw_path.startswith("https://"):
        return raw_path
    base = _normalize_url(base_url)
    if not base:
        return raw_path
    if not raw_path.startswith("/"):
        raw_path = f"/{raw_path}"
    return urljoin(f"{base.rstrip('/')}/", raw_path.lstrip("/"))


def _content_item_url_map(db: Session, *, channel: ManagedChannel) -> dict[str, ContentItem]:
    items = (
        db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.publication_records))
            .where(ContentItem.managed_channel_id == channel.id)
        )
        .scalars()
        .unique()
        .all()
    )
    mapping: dict[str, ContentItem] = {}
    for item in items:
        latest_publication = item.publication_records[0] if item.publication_records else None
        remote_url = _normalize_url(latest_publication.remote_url if latest_publication else "")
        if remote_url:
            mapping[remote_url] = item
    return mapping


def _content_item_publication_maps(db: Session, *, channel: ManagedChannel) -> tuple[dict[str, ContentItem], dict[str, ContentItem]]:
    items = (
        db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.publication_records))
            .where(ContentItem.managed_channel_id == channel.id)
        )
        .scalars()
        .unique()
        .all()
    )
    by_remote_id: dict[str, ContentItem] = {}
    by_remote_url: dict[str, ContentItem] = {}
    for item in items:
        latest_publication = item.publication_records[0] if item.publication_records else None
        if latest_publication is None:
            continue
        remote_id = _normalize_url(latest_publication.remote_id)
        remote_url = _normalize_url(latest_publication.remote_url)
        if remote_id:
            by_remote_id[remote_id] = item
        if remote_url:
            by_remote_url[remote_url] = item
    return by_remote_id, by_remote_url


def _safe_response_json(response) -> dict:
    try:
        payload = response.json() if response.content else {}
    except Exception:  # noqa: BLE001
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _response_detail(payload: dict, fallback: str) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or fallback)
    if isinstance(error, str):
        return error
    return str(payload.get("message") or fallback)


def _youtube_date_range(days: int) -> tuple[str, str]:
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=max(days - 1, 0))
    return start_date.isoformat(), end_date.isoformat()


def _youtube_rows(payload: dict) -> list[dict[str, str | float]]:
    headers = list(payload.get("columnHeaders") or [])
    rows = list(payload.get("rows") or [])
    if not headers or not rows:
        return []
    header_names = [str(header.get("name") or "").strip() for header in headers]
    normalized: list[dict[str, str | float]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        mapped: dict[str, str | float] = {}
        for index, header_name in enumerate(header_names):
            if not header_name:
                continue
            value = row[index] if index < len(row) else None
            if isinstance(value, (int, float)):
                mapped[header_name] = float(value)
            else:
                mapped[header_name] = str(value or "")
        normalized.append(mapped)
    return normalized


def _normalize_percentage(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 1.0:
        return _score_relative(value, 100.0)
    return _score_ratio(value)


def _instagram_graph_url(path: str, *, version: str) -> str:
    return f"{INSTAGRAM_GRAPH_BASE_URL.format(version=version)}{path}"


def _instagram_insight_metric_names(media_type: str) -> str:
    normalized = str(media_type or "").strip().upper()
    if normalized in {"REELS", "VIDEO"}:
        return "impressions,reach,saved,likes,comments,shares,video_views"
    return "impressions,reach,saved,likes,comments,shares"


def _extract_instagram_insight_values(payload: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    for item in list(payload.get("data") or []):
        if not isinstance(item, dict):
            continue
        metric_name = str(item.get("name") or "").strip()
        metric_values = list(item.get("values") or [])
        if not metric_name or not metric_values:
            continue
        first_value = metric_values[0] if isinstance(metric_values[0], dict) else {}
        values[metric_name] = _coerce_float(first_value.get("value"))
    return values


def _append_metric_fact(
    facts: list[MetricFact],
    *,
    channel: ManagedChannel,
    content_item_id: int | None,
    metric_scope: str,
    metric_name: str,
    value: float,
    normalized_score: float | None,
    dimension_key: str | None,
    dimension_value: str | None,
    snapshot_at: datetime,
    payload: dict,
) -> None:
    facts.append(
        MetricFact(
            managed_channel_id=channel.id,
            content_item_id=content_item_id,
            provider=channel.provider,
            metric_scope=metric_scope,
            metric_name=metric_name,
            value=value,
            normalized_score=normalized_score,
            dimension_key=dimension_key,
            dimension_value=dimension_value,
            snapshot_at=snapshot_at,
            metric_payload=payload,
        )
    )


def _normalize_last_score_payload(payload: dict[str, float]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key, raw_value in payload.items():
        target_key = LEGACY_SCORE_KEY_MAP.get(key, key)
        value = _coerce_float(raw_value, fallback=0.0)
        if target_key in LAST_SCORE_KEYS:
            normalized[target_key] = round(max(0.0, min(value, 100.0)), 2)
    return normalized


def _apply_last_scores(db: Session, *, scores: dict[int, dict[str, float]]) -> int:
    updated = 0
    for item_id, payload in scores.items():
        item = db.get(ContentItem, item_id)
        if item is None:
            continue
        normalized_payload = _normalize_last_score_payload(payload)
        if not normalized_payload:
            continue
        merged = dict(item.last_score or {})
        merged.update(normalized_payload)
        score_values = [merged[key] for key in LAST_SCORE_KEYS if isinstance(merged.get(key), (int, float))]
        merged["composite"] = round(sum(score_values) / len(score_values), 2) if score_values else None
        merged["updated_at"] = _utcnow().isoformat()
        item.last_score = merged
        db.add(item)
        updated += 1
    return updated


def _update_channel_sync_state(
    db: Session,
    *,
    channel: ManagedChannel,
    snapshot_at: datetime,
    facts_written: int,
    warnings: list[str],
) -> None:
    quota_state = dict(channel.quota_state or {})
    quota_state.update(
        {
            "last_metric_sync_at": snapshot_at.isoformat(),
            "metric_fact_count": facts_written,
            "last_metric_sync_warning_count": len(warnings),
        }
    )
    channel.quota_state = quota_state
    db.add(channel)


def _raise_platform_metric_error(message: str, *, response) -> None:
    payload = _safe_response_json(response)
    raise PlatformOAuthError(
        message,
        detail=_response_detail(payload, response.text),
        status_code=response.status_code,
    )


def sync_blogger_channel_metrics(
    db: Session,
    *,
    channel_id: str,
    days: int = 28,
    refresh_indexing: bool = True,
) -> dict:
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise ValueError("Channel not found")
    if channel.provider != "blogger" or channel.linked_blog is None:
        raise ValueError("Metric sync is supported only for linked Blogger channels")

    blog: Blog = channel.linked_blog
    snapshot_at = _utcnow()
    warnings: list[str] = []
    facts: list[MetricFact] = []
    content_scores: dict[int, dict[str, float]] = {}
    content_map = _content_item_url_map(db, channel=channel)
    indexing_result: dict | None = None
    search_console_payload: dict | None = None
    analytics_payload: dict | None = None

    if refresh_indexing:
        indexing_result = refresh_indexing_for_blog(db, blog_id=blog.id)

    try:
        if (blog.search_console_site_url or "").strip():
            search_console_payload = query_search_console_performance(db, blog.search_console_site_url, days=days, row_limit=25)
        else:
            warnings.append("search_console_not_configured")
    except BloggerOAuthError as exc:
        warnings.append(f"search_console:{exc.detail}")

    try:
        if (blog.ga4_property_id or "").strip():
            analytics_payload = query_analytics_overview(db, blog.ga4_property_id, days=days, row_limit=25)
        else:
            warnings.append("ga4_not_configured")
    except BloggerOAuthError as exc:
        warnings.append(f"ga4:{exc.detail}")

    relevant_urls: set[str] = set(content_map)
    if search_console_payload:
        totals = dict(search_console_payload.get("totals") or {})
        for metric_name, metric_value in (
            ("search_console_clicks", _coerce_float(totals.get("clicks"))),
            ("search_console_impressions", _coerce_float(totals.get("impressions"))),
            ("search_console_ctr", _coerce_float(totals.get("ctr"))),
            ("search_console_position", _coerce_float(totals.get("position"))),
        ):
            _append_metric_fact(
                facts,
                channel=channel,
                content_item_id=None,
                metric_scope="channel",
                metric_name=metric_name,
                value=metric_value,
                normalized_score=_score_ratio(metric_value) if metric_name == "search_console_ctr" else None,
                dimension_key=None,
                dimension_value=None,
                snapshot_at=snapshot_at,
                payload={"source": "search_console_totals", **totals},
            )

        top_pages = list(search_console_payload.get("top_pages") or [])
        max_clicks = max((_coerce_float(row.get("clicks")) for row in top_pages), default=0.0)
        for row in top_pages:
            page_url = _normalize_url((row.get("keys") or [""])[0])
            if not page_url:
                continue
            relevant_urls.add(page_url)
            content_item = content_map.get(page_url)
            ctr_score = _score_ratio(_coerce_float(row.get("ctr")))
            click_score = _score_relative(_coerce_float(row.get("clicks")), max_clicks)
            for metric_name, value, normalized_score in (
                ("search_console_clicks", _coerce_float(row.get("clicks")), click_score),
                ("search_console_impressions", _coerce_float(row.get("impressions")), None),
                ("search_console_ctr", _coerce_float(row.get("ctr")), ctr_score),
                ("search_console_position", _coerce_float(row.get("position")), None),
            ):
                _append_metric_fact(
                    facts,
                    channel=channel,
                    content_item_id=content_item.id if content_item else None,
                    metric_scope="content",
                    metric_name=metric_name,
                    value=value,
                    normalized_score=normalized_score,
                    dimension_key="page",
                    dimension_value=page_url,
                    snapshot_at=snapshot_at,
                    payload={"source": "search_console_page", **row},
                )
            if content_item and ctr_score is not None:
                content_scores.setdefault(content_item.id, {})["seo_ctr"] = ctr_score

    if analytics_payload:
        totals = dict(analytics_payload.get("totals") or {})
        for metric_name, metric_value in (
            ("ga4_screen_page_views", _coerce_float(totals.get("screenPageViews"))),
            ("ga4_sessions", _coerce_float(totals.get("sessions"))),
            ("ga4_active_users", _coerce_float(totals.get("activeUsers"))),
        ):
            _append_metric_fact(
                facts,
                channel=channel,
                content_item_id=None,
                metric_scope="channel",
                metric_name=metric_name,
                value=metric_value,
                normalized_score=None,
                dimension_key=None,
                dimension_value=None,
                snapshot_at=snapshot_at,
                payload={"source": "ga4_totals", **totals},
            )

        top_pages = list(analytics_payload.get("top_pages") or [])
        max_views = max((_coerce_float(row.get("screenPageViews")) for row in top_pages), default=0.0)
        for row in top_pages:
            absolute_url = _resolve_absolute_url(blog.blogger_url or channel.base_url, row.get("page_path"))
            if not absolute_url:
                continue
            relevant_urls.add(absolute_url)
            content_item = content_map.get(absolute_url)
            traffic_score = _score_relative(_coerce_float(row.get("screenPageViews")), max_views)
            for metric_name, value, normalized_score in (
                ("ga4_screen_page_views", _coerce_float(row.get("screenPageViews")), traffic_score),
                ("ga4_sessions", _coerce_float(row.get("sessions")), None),
            ):
                _append_metric_fact(
                    facts,
                    channel=channel,
                    content_item_id=content_item.id if content_item else None,
                    metric_scope="content",
                    metric_name=metric_name,
                    value=value,
                    normalized_score=normalized_score,
                    dimension_key="page",
                    dimension_value=absolute_url,
                    snapshot_at=snapshot_at,
                    payload={"source": "ga4_page", **row, "absolute_url": absolute_url},
                )
            if content_item and traffic_score is not None:
                item_scores = content_scores.setdefault(content_item.id, {})
                item_scores["traffic_quality"] = traffic_score
                item_scores.setdefault("engagement_quality", traffic_score)

    if relevant_urls:
        url_states = (
            db.execute(
                select(GoogleIndexUrlState).where(
                    GoogleIndexUrlState.blog_id == blog.id,
                    GoogleIndexUrlState.url.in_(sorted(relevant_urls)),
                )
            )
            .scalars()
            .all()
        )
        for state in url_states:
            state_url = _normalize_url(state.url)
            if not state_url:
                continue
            content_item = content_map.get(state_url)
            index_score = _score_index_status(state.index_status)
            _append_metric_fact(
                facts,
                channel=channel,
                content_item_id=content_item.id if content_item else None,
                metric_scope="content",
                metric_name="index_status_score",
                value=index_score,
                normalized_score=index_score,
                dimension_key="page",
                dimension_value=state_url,
                snapshot_at=snapshot_at,
                payload={
                    "source": "indexing_state",
                    "index_status": state.index_status,
                    "coverage_state": state.index_coverage_state,
                    "last_checked_at": state.last_checked_at.isoformat() if state.last_checked_at else None,
                },
            )
            if content_item:
                content_scores.setdefault(content_item.id, {})["indexing_quality"] = index_score

        ctr_cache_rows = (
            db.execute(
                select(SearchConsolePageMetric).where(
                    SearchConsolePageMetric.blog_id == blog.id,
                    SearchConsolePageMetric.url.in_(sorted(relevant_urls)),
                )
            )
            .scalars()
            .all()
        )
        for row in ctr_cache_rows:
            content_item = content_map.get(_normalize_url(row.url))
            if content_item is None or row.ctr is None:
                continue
            content_scores.setdefault(content_item.id, {}).setdefault("seo_ctr", _score_ratio(row.ctr) or 0.0)

    if facts:
        db.add_all(facts)
    updated_items = _apply_last_scores(db, scores=content_scores)
    _update_channel_sync_state(
        db,
        channel=channel,
        snapshot_at=snapshot_at,
        facts_written=len(facts),
        warnings=warnings,
    )
    db.commit()

    return {
        "status": "ok",
        "channel_id": channel.channel_id,
        "provider": channel.provider,
        "snapshot_at": snapshot_at.isoformat(),
        "facts_written": len(facts),
        "content_items_updated": updated_items,
        "search_console_connected": bool((blog.search_console_site_url or "").strip()),
        "ga4_connected": bool((blog.ga4_property_id or "").strip()),
        "indexing_refresh": indexing_result,
        "warnings": warnings,
    }


def sync_youtube_channel_metrics(
    db: Session,
    *,
    channel_id: str,
    days: int = 28,
) -> dict:
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise ValueError("Channel not found")
    if channel.provider != "youtube":
        raise ValueError("YouTube metric sync is supported only for youtube channels")

    snapshot_at = _utcnow()
    warnings: list[str] = []
    facts: list[MetricFact] = []
    content_scores: dict[int, dict[str, float]] = {}
    by_remote_id, _by_remote_url = _content_item_publication_maps(db, channel=channel)
    start_date, end_date = _youtube_date_range(days)

    totals_response = authorized_platform_request(
        db,
        channel_id=channel.channel_id,
        method="GET",
        url=YOUTUBE_ANALYTICS_REPORTS_URL,
        params={
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": "views,impressions,impressionsCtr,estimatedMinutesWatched,averageViewPercentage",
        },
        timeout=120.0,
    )
    totals_payload = _safe_response_json(totals_response)
    if not totals_response.is_success:
        _raise_platform_metric_error("YouTube analytics totals request failed.", response=totals_response)

    totals_rows = _youtube_rows(totals_payload)
    totals = totals_rows[0] if totals_rows else {}
    for metric_name, metric_value, normalized_score in (
        ("youtube_views", _coerce_float(totals.get("views")), None),
        ("youtube_impressions", _coerce_float(totals.get("impressions")), None),
        ("youtube_ctr", _coerce_float(totals.get("impressionsCtr")), _normalize_percentage(_coerce_float(totals.get("impressionsCtr")))),
        ("youtube_estimated_minutes_watched", _coerce_float(totals.get("estimatedMinutesWatched")), None),
        (
            "youtube_average_view_percentage",
            _coerce_float(totals.get("averageViewPercentage")),
            _normalize_percentage(_coerce_float(totals.get("averageViewPercentage"))),
        ),
    ):
        _append_metric_fact(
            facts,
            channel=channel,
            content_item_id=None,
            metric_scope="channel",
            metric_name=metric_name,
            value=metric_value,
            normalized_score=normalized_score,
            dimension_key=None,
            dimension_value=None,
            snapshot_at=snapshot_at,
            payload={"source": "youtube_channel_totals", **totals},
        )

    video_response = authorized_platform_request(
        db,
        channel_id=channel.channel_id,
        method="GET",
        url=YOUTUBE_ANALYTICS_REPORTS_URL,
        params={
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": "video",
            "sort": "-views",
            "maxResults": "50",
            "metrics": "views,impressions,impressionsCtr,estimatedMinutesWatched,averageViewPercentage",
        },
        timeout=120.0,
    )
    video_payload = _safe_response_json(video_response)
    if not video_response.is_success:
        _raise_platform_metric_error("YouTube analytics video request failed.", response=video_response)

    video_rows = _youtube_rows(video_payload)
    max_views = max((_coerce_float(row.get("views")) for row in video_rows), default=0.0)
    max_minutes = max((_coerce_float(row.get("estimatedMinutesWatched")) for row in video_rows), default=0.0)
    for row in video_rows:
        video_id = str(row.get("video") or "").strip()
        if not video_id:
            continue
        content_item = by_remote_id.get(video_id)
        ctr_score = _normalize_percentage(_coerce_float(row.get("impressionsCtr")))
        retention_score = _normalize_percentage(_coerce_float(row.get("averageViewPercentage")))
        watch_minutes_score = _score_relative(_coerce_float(row.get("estimatedMinutesWatched")), max_minutes)
        watch_quality = _average_score(retention_score, watch_minutes_score)
        engagement_score = _score_relative(_coerce_float(row.get("views")), max_views)

        for metric_name, value, normalized_score in (
            ("youtube_views", _coerce_float(row.get("views")), engagement_score),
            ("youtube_impressions", _coerce_float(row.get("impressions")), None),
            ("youtube_ctr", _coerce_float(row.get("impressionsCtr")), ctr_score),
            ("youtube_estimated_minutes_watched", _coerce_float(row.get("estimatedMinutesWatched")), watch_minutes_score),
            ("youtube_average_view_percentage", _coerce_float(row.get("averageViewPercentage")), retention_score),
        ):
            _append_metric_fact(
                facts,
                channel=channel,
                content_item_id=content_item.id if content_item else None,
                metric_scope="content",
                metric_name=metric_name,
                value=value,
                normalized_score=normalized_score,
                dimension_key="video_id",
                dimension_value=video_id,
                snapshot_at=snapshot_at,
                payload={"source": "youtube_video", **row},
            )

        if content_item:
            item_scores = content_scores.setdefault(content_item.id, {})
            if ctr_score is not None:
                item_scores["seo_ctr"] = ctr_score
            if watch_quality is not None:
                item_scores["watch_quality"] = watch_quality
            if engagement_score is not None:
                item_scores.setdefault("engagement_quality", engagement_score)

    if facts:
        db.add_all(facts)
    updated_items = _apply_last_scores(db, scores=content_scores)
    _update_channel_sync_state(
        db,
        channel=channel,
        snapshot_at=snapshot_at,
        facts_written=len(facts),
        warnings=warnings,
    )
    db.commit()

    return {
        "status": "ok",
        "channel_id": channel.channel_id,
        "provider": channel.provider,
        "snapshot_at": snapshot_at.isoformat(),
        "facts_written": len(facts),
        "content_items_updated": updated_items,
        "warnings": warnings,
        "lookback_days": days,
    }


def sync_instagram_channel_metrics(
    db: Session,
    *,
    channel_id: str,
    days: int = 28,
) -> dict:
    del days  # Media insights endpoint is list-based in this v0.1 path.
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise ValueError("Channel not found")
    if channel.provider != "instagram":
        raise ValueError("Instagram metric sync is supported only for instagram channels")

    snapshot_at = _utcnow()
    warnings: list[str] = []
    facts: list[MetricFact] = []
    content_scores: dict[int, dict[str, float]] = {}
    by_remote_id, by_remote_url = _content_item_publication_maps(db, channel=channel)

    remote_account_id = _normalize_url(channel.remote_resource_id)
    if not remote_account_id:
        raise ValueError("Instagram channel is missing a remote business account id")

    settings_map = get_settings_map(db)
    graph_version = str(settings_map.get("meta_graph_api_version") or "v23.0").strip() or "v23.0"
    media_response = authorized_platform_request(
        db,
        channel_id=channel.channel_id,
        method="GET",
        url=_instagram_graph_url(f"/{remote_account_id}/media", version=graph_version),
        params={"fields": "id,caption,media_type,media_product_type,permalink,timestamp", "limit": "50"},
        timeout=120.0,
    )
    media_payload = _safe_response_json(media_response)
    if not media_response.is_success:
        _raise_platform_metric_error("Instagram media listing request failed.", response=media_response)

    media_items = [item for item in list(media_payload.get("data") or []) if isinstance(item, dict)]
    normalized_media_rows: list[dict] = []
    for media_item in media_items:
        media_id = _normalize_url(str(media_item.get("id") or ""))
        if not media_id:
            continue
        media_type = _normalize_url(str(media_item.get("media_product_type") or media_item.get("media_type") or "")).upper()
        insight_response = authorized_platform_request(
            db,
            channel_id=channel.channel_id,
            method="GET",
            url=_instagram_graph_url(f"/{media_id}/insights", version=graph_version),
            params={"metric": _instagram_insight_metric_names(media_type)},
            timeout=120.0,
        )
        insight_payload = _safe_response_json(insight_response)
        if not insight_response.is_success:
            warnings.append(f"instagram_insights:{media_id}:{_response_detail(insight_payload, insight_response.text)}")
            continue
        insight_values = _extract_instagram_insight_values(insight_payload)
        if not insight_values:
            continue

        permalink = _normalize_url(str(media_item.get("permalink") or ""))
        content_item = by_remote_id.get(media_id) or by_remote_url.get(permalink)
        likes = _coerce_float(insight_values.get("likes"))
        comments = _coerce_float(insight_values.get("comments"))
        shares = _coerce_float(insight_values.get("shares"))
        saved = _coerce_float(insight_values.get("saved"))
        reach = _coerce_float(insight_values.get("reach"))
        impressions = _coerce_float(insight_values.get("impressions"))
        video_views = _coerce_float(insight_values.get("video_views"))
        engagement = likes + comments + shares + saved
        engagement_rate = (engagement / reach) if reach > 0 else 0.0

        normalized_media_rows.append(
            {
                "media_id": media_id,
                "media_type": media_type or "IMAGE",
                "permalink": permalink,
                "impressions": impressions,
                "reach": reach,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "saved": saved,
                "video_views": video_views,
                "engagement": engagement,
                "engagement_rate": engagement_rate,
                "content_item_id": content_item.id if content_item else None,
            }
        )

    max_reach = max((_coerce_float(item.get("reach")) for item in normalized_media_rows), default=0.0)
    max_video_views = max((_coerce_float(item.get("video_views")) for item in normalized_media_rows), default=0.0)
    max_engagement = max((_coerce_float(item.get("engagement")) for item in normalized_media_rows), default=0.0)
    total_impressions = 0.0
    total_reach = 0.0
    total_engagement = 0.0
    total_video_views = 0.0

    for row in normalized_media_rows:
        media_id = str(row["media_id"])
        content_item_id = int(row["content_item_id"]) if row.get("content_item_id") is not None else None
        reach = _coerce_float(row.get("reach"))
        impressions = _coerce_float(row.get("impressions"))
        likes = _coerce_float(row.get("likes"))
        comments = _coerce_float(row.get("comments"))
        shares = _coerce_float(row.get("shares"))
        saved = _coerce_float(row.get("saved"))
        video_views = _coerce_float(row.get("video_views"))
        engagement = _coerce_float(row.get("engagement"))
        engagement_rate = _coerce_float(row.get("engagement_rate"))
        reach_score = _score_relative(reach, max_reach)
        engagement_score = _score_relative(engagement, max_engagement)
        engagement_rate_score = _score_ratio(engagement_rate)
        watch_score = _score_relative(video_views, max_video_views) if video_views > 0 else None

        for metric_name, value, normalized_score in (
            ("instagram_impressions", impressions, None),
            ("instagram_reach", reach, reach_score),
            ("instagram_likes", likes, None),
            ("instagram_comments", comments, None),
            ("instagram_shares", shares, None),
            ("instagram_saved", saved, None),
            ("instagram_engagement", engagement, engagement_score),
            ("instagram_engagement_rate", engagement_rate, engagement_rate_score),
            ("instagram_video_views", video_views, watch_score if video_views > 0 else None),
        ):
            if metric_name == "instagram_video_views" and video_views <= 0:
                continue
            _append_metric_fact(
                facts,
                channel=channel,
                content_item_id=content_item_id,
                metric_scope="content",
                metric_name=metric_name,
                value=value,
                normalized_score=normalized_score,
                dimension_key="media_id",
                dimension_value=media_id,
                snapshot_at=snapshot_at,
                payload={"source": "instagram_media_insights", **row},
            )

        if content_item_id is not None:
            item_scores = content_scores.setdefault(content_item_id, {})
            engagement_quality = _average_score(engagement_rate_score, engagement_score)
            if engagement_quality is not None:
                item_scores["engagement_quality"] = engagement_quality
            if watch_score is not None:
                item_scores["watch_quality"] = watch_score

        total_impressions += impressions
        total_reach += reach
        total_engagement += engagement
        total_video_views += video_views

    channel_engagement_rate = (total_engagement / total_reach) if total_reach > 0 else 0.0
    for metric_name, value, normalized_score in (
        ("instagram_impressions", total_impressions, None),
        ("instagram_reach", total_reach, None),
        ("instagram_engagement", total_engagement, None),
        ("instagram_engagement_rate", channel_engagement_rate, _score_ratio(channel_engagement_rate)),
        ("instagram_video_views", total_video_views, None),
    ):
        _append_metric_fact(
            facts,
            channel=channel,
            content_item_id=None,
            metric_scope="channel",
            metric_name=metric_name,
            value=value,
            normalized_score=normalized_score,
            dimension_key=None,
            dimension_value=None,
            snapshot_at=snapshot_at,
            payload={"source": "instagram_channel_aggregate", "media_count": len(normalized_media_rows)},
        )

    if facts:
        db.add_all(facts)
    updated_items = _apply_last_scores(db, scores=content_scores)
    _update_channel_sync_state(
        db,
        channel=channel,
        snapshot_at=snapshot_at,
        facts_written=len(facts),
        warnings=warnings,
    )
    db.commit()

    return {
        "status": "ok",
        "channel_id": channel.channel_id,
        "provider": channel.provider,
        "snapshot_at": snapshot_at.isoformat(),
        "facts_written": len(facts),
        "content_items_updated": updated_items,
        "warnings": warnings,
        "media_count": len(normalized_media_rows),
    }


def sync_channel_metrics(
    db: Session,
    *,
    channel_id: str,
    days: int = 28,
    refresh_indexing: bool = True,
) -> dict:
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise ValueError("Channel not found")
    if channel.provider == "blogger":
        return sync_blogger_channel_metrics(
            db,
            channel_id=channel.channel_id,
            days=days,
            refresh_indexing=refresh_indexing,
        )
    if channel.provider == "youtube":
        return sync_youtube_channel_metrics(
            db,
            channel_id=channel.channel_id,
            days=days,
        )
    if channel.provider == "instagram":
        return sync_instagram_channel_metrics(
            db,
            channel_id=channel.channel_id,
            days=days,
        )
    raise ValueError("Metric sync is not supported for this provider")


def sync_all_blogger_channel_metrics(
    db: Session,
    *,
    days: int = 28,
    refresh_indexing: bool = False,
) -> dict:
    channels = (
        db.execute(
            select(ManagedChannel)
            .options(selectinload(ManagedChannel.linked_blog))
            .where(ManagedChannel.provider == "blogger", ManagedChannel.is_enabled.is_(True))
            .order_by(ManagedChannel.created_at.asc(), ManagedChannel.id.asc())
        )
        .scalars()
        .unique()
        .all()
    )
    results: list[dict] = []
    for channel in channels:
        if channel.linked_blog is None:
            continue
        results.append(
            sync_blogger_channel_metrics(
                db,
                channel_id=channel.channel_id,
                days=days,
                refresh_indexing=refresh_indexing,
            )
        )
    return {
        "status": "ok",
        "channels": results,
        "processed_count": len(results),
    }


def run_workspace_metric_sync_schedule(
    db: Session,
    *,
    now: datetime | None = None,
    force: bool = False,
    refresh_indexing: bool = False,
) -> dict:
    settings_map = get_settings_map(db)
    if str(settings_map.get("workspace_metrics_sync_enabled") or "true").strip().lower() != "true":
        return {"status": "disabled", "reason": "workspace_metrics_sync_disabled"}

    try:
        interval_hours = max(int(str(settings_map.get("workspace_metrics_sync_interval_hours") or "6").strip()), 1)
    except (TypeError, ValueError):
        interval_hours = 6
    try:
        lookback_days = max(int(str(settings_map.get("workspace_metrics_lookback_days") or "28").strip()), 1)
    except (TypeError, ValueError):
        lookback_days = 28

    current = now or _utcnow()
    channels = (
        db.execute(
            select(ManagedChannel)
            .options(selectinload(ManagedChannel.linked_blog))
            .where(ManagedChannel.provider.in_(tuple(sorted(SUPPORTED_METRIC_PROVIDERS))))
            .where(ManagedChannel.is_enabled.is_(True))
            .order_by(ManagedChannel.created_at.asc(), ManagedChannel.id.asc())
        )
        .scalars()
        .unique()
        .all()
    )

    results: list[dict] = []
    processed = 0
    failed = 0
    for channel in channels:
        if channel.provider == "blogger" and channel.linked_blog is None:
            continue
        last_sync_raw = str((channel.quota_state or {}).get("last_metric_sync_at") or "").strip()
        should_run = force
        if not should_run and last_sync_raw:
            try:
                last_sync = datetime.fromisoformat(last_sync_raw.replace("Z", "+00:00"))
                if last_sync.tzinfo is None:
                    last_sync = last_sync.replace(tzinfo=UTC)
                should_run = current >= (last_sync + timedelta(hours=interval_hours))
            except ValueError:
                should_run = True
        elif not should_run:
            should_run = True
        if not should_run:
            continue

        processed += 1
        try:
            results.append(
                sync_channel_metrics(
                    db,
                    channel_id=channel.channel_id,
                    days=lookback_days,
                    refresh_indexing=refresh_indexing if channel.provider == "blogger" else False,
                )
            )
        except (ValueError, BloggerOAuthError, PlatformOAuthError) as exc:
            failed += 1
            detail = exc.detail if hasattr(exc, "detail") else str(exc)
            results.append(
                {
                    "status": "failed",
                    "channel_id": channel.channel_id,
                    "provider": channel.provider,
                    "detail": detail,
                }
            )

    return {
        "status": "partial_failed" if failed else "ok",
        "processed_count": processed,
        "failed_count": failed,
        "channels": results,
        "interval_hours": interval_hours,
        "lookback_days": lookback_days,
        "forced": force,
    }
