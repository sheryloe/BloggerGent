from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HelpTopic:
    topic_id: str
    title: str
    summary: str
    tags: tuple[str, ...]
    related_screens: tuple[str, ...]
    commands: tuple[str, ...]
    deep_links: tuple[str, ...]
    runbook: str | None = None


HELP_TOPICS: tuple[HelpTopic, ...] = (
    HelpTopic(
        topic_id="ops-overview",
        title="운영 제어 개요",
        summary="대시보드에서 운영 상태, 대기열, 동기화 상태를 빠르게 확인하는 기본 운영 토픽입니다.",
        tags=("ops", "운영", "모니터"),
        related_screens=("/dashboard", "/ops-health", "/admin"),
        commands=("/ops status", "/ops queue", "/ops sync-now"),
        deep_links=("/dashboard", "/ops-health", "/admin"),
        runbook="ops-overview",
    ),
    HelpTopic(
        topic_id="ops-commands",
        title="Telegram 운영 명령",
        summary="텔레그램에서 콘텐츠 운영 제어, 리뷰 확인/적용을 수행하는 명령 모음입니다.",
        tags=("telegram", "ops", "명령"),
        related_screens=("/settings", "/help"),
        commands=(
            "/ops status",
            "/ops queue",
            "/ops review <id>",
            "/ops approve <id>",
            "/ops apply <id>",
            "/ops reject <id>",
            "/ops rerun <id>",
            "/ops menu",
        ),
        deep_links=("/help?topic=ops-commands", "/settings"),
        runbook="telegram-ops",
    ),
    HelpTopic(
        topic_id="settings-telegram",
        title="Telegram 연결 설정",
        summary="봇 토큰, 채팅 ID 설정과 테스트 발송/수동 poll 실행 순서를 정리한 토픽입니다.",
        tags=("telegram", "settings", "runbook"),
        related_screens=("/settings", "/help"),
        commands=(
            "POST /api/v1/telegram/test",
            "POST /api/v1/telegram/poll-now",
            "GET /api/v1/telegram/subscriptions",
            "PUT /api/v1/telegram/subscriptions",
        ),
        deep_links=("/settings", "/help?topic=settings-telegram"),
        runbook="telegram-connectivity",
    ),
    HelpTopic(
        topic_id="planner-monthly",
        title="월간 플래너 운영",
        summary="채널 기준 월간 슬롯 생성, 브리프 분석, 실행 상태 점검 절차를 정리합니다.",
        tags=("planner", "월간", "콘텐츠"),
        related_screens=("/planner", "/content-ops"),
        commands=(
            "POST /api/v1/planner/month-plan",
            "POST /api/v1/planner/days/{plan_day_id}/brief-analysis",
            "POST /api/v1/planner/days/{plan_day_id}/brief-apply",
        ),
        deep_links=("/planner", "/help?topic=planner-monthly"),
        runbook="planner-monthly-execution",
    ),
    HelpTopic(
        topic_id="analytics-lighthouse-indexing",
        title="Lighthouse + 색인 동기화",
        summary="LIVE(published) 게시글 기준 Lighthouse 점수와 색인 상태를 동기화하는 운영 점검 토픽입니다.",
        tags=("analytics", "lighthouse", "indexing"),
        related_screens=("/analytics/blogger", "/analytics"),
        commands=(
            "python scripts/sync_lighthouse_scores.py --published-only --form-factor mobile",
            "POST /api/v1/analytics/indexing/refresh",
            "POST /api/v1/google/indexing/status-refresh",
        ),
        deep_links=("/analytics/blogger", "/analytics", "/help?topic=analytics-lighthouse-indexing"),
        runbook="live-published-lighthouse-indexing-sync",
    ),
)


def _contains_keyword(topic: HelpTopic, keyword: str) -> bool:
    query = keyword.strip().lower()
    if not query:
        return True
    bag = " ".join(
        (
            topic.topic_id,
            topic.title,
            topic.summary,
            " ".join(topic.tags),
            " ".join(topic.commands),
            " ".join(topic.related_screens),
        )
    ).lower()
    return query in bag


def _matches_tag(topic: HelpTopic, tag: str) -> bool:
    query = tag.strip().lower()
    if not query:
        return True
    return any(entry.strip().lower() == query for entry in topic.tags)


def serialize_help_topic(topic: HelpTopic) -> dict:
    return {
        "topic_id": topic.topic_id,
        "title": topic.title,
        "summary": topic.summary,
        "tags": list(topic.tags),
        "related_screens": list(topic.related_screens),
        "commands": list(topic.commands),
        "deep_links": list(topic.deep_links),
        "runbook": topic.runbook,
    }


def list_help_topics(*, keyword: str | None = None, tag: str | None = None) -> list[dict]:
    items: list[dict] = []
    for topic in HELP_TOPICS:
        if keyword and not _contains_keyword(topic, keyword):
            continue
        if tag and not _matches_tag(topic, tag):
            continue
        items.append(serialize_help_topic(topic))
    return items


def get_help_topic(topic_id: str) -> dict | None:
    target = str(topic_id or "").strip()
    if not target:
        return None
    for topic in HELP_TOPICS:
        if topic.topic_id == target:
            return serialize_help_topic(topic)
    return None


def search_help_topics(keyword: str, *, limit: int = 5) -> list[dict]:
    if limit <= 0:
        return []
    return list_help_topics(keyword=keyword)[:limit]
