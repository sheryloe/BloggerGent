#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"

if not Path("/.dockerenv").exists():
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://bloggent:bloggent@localhost:15432/bloggent")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ContentReviewItem, Job, JobStatus, PublishQueueItem  # noqa: E402
from app.services.settings_service import get_settings_map  # noqa: E402

SEOUL_TZ = ZoneInfo("Asia/Seoul")
REPORT_DIR = ROOT / "storage" / "reports"
ACTIVE_JOB_STATUSES = {
    JobStatus.PENDING,
    JobStatus.DISCOVERING_TOPICS,
    JobStatus.GENERATING_ARTICLE,
    JobStatus.GENERATING_IMAGE_PROMPT,
    JobStatus.GENERATING_IMAGE,
    JobStatus.FINDING_RELATED_POSTS,
    JobStatus.ASSEMBLING_HTML,
    JobStatus.PUBLISHING,
}
CODE_FILES = (
    ROOT / "apps" / "api" / "app" / "core" / "celery_app.py",
    ROOT / "apps" / "api" / "app" / "tasks" / "scheduler.py",
    ROOT / "apps" / "api" / "app" / "tasks" / "pipeline.py",
    ROOT / "apps" / "api" / "app" / "services" / "cloudflare_channel_service.py",
    ROOT / "apps" / "api" / "app" / "services" / "publishing_service.py",
)
BEAT_SCHEDULE = (
    {"name": "run-scheduler-tick", "task": "app.tasks.scheduler.run_scheduler_tick", "seconds": 60.0},
    {"name": "process-publish-queue", "task": "app.tasks.scheduler.process_publish_queue", "seconds": 30.0},
    {"name": "run-content-ops-scan", "task": "app.tasks.scheduler.run_content_ops_scan", "seconds": 300.0},
    {"name": "poll-telegram-ops", "task": "app.tasks.scheduler.poll_telegram_ops", "seconds": 15.0},
)


@dataclass(frozen=True)
class LaneSlot:
    hour: int
    minute: int
    label: str
    state: str
    note: str


@dataclass(frozen=True)
class LaneSummary:
    title: str
    start_time: str
    interval_hours: int
    topic_count: int | None
    latest_marker: str
    slots: list[LaneSlot]


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def is_true(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def parse_json(raw: str | None, default: object) -> tuple[object, bool]:
    if not (raw or "").strip():
        return default, False
    try:
        return json.loads(raw), False
    except json.JSONDecodeError:
        return default, True


def parse_time(raw: str | None, fallback: str) -> tuple[int, int]:
    value = (raw or fallback or "").strip() or fallback
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        return max(0, min(int(hour_text), 23)), max(0, min(int(minute_text), 59))
    except (ValueError, TypeError):
        return 0, 0


def parse_marker(raw: str | None) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SEOUL_TZ)
    return parsed.astimezone(SEOUL_TZ)


def fmt_time(value: datetime | None) -> str:
    return "미실행" if value is None else value.astimezone(SEOUL_TZ).strftime("%H:%M KST")


def fmt_datetime(value: datetime | None) -> str:
    return "미실행" if value is None else value.astimezone(SEOUL_TZ).strftime("%Y-%m-%d %H:%M KST")


def topic_mix(raw: str | None, today: str) -> tuple[dict[str, int], bool]:
    payload, degraded = parse_json(raw, {})
    if not isinstance(payload, dict) or str(payload.get("date") or "") != today:
        return {"total_topics": 0, "blossom_topics": 0}, degraded
    return {
        "total_topics": max(safe_int(payload.get("total_topics"), 0), 0),
        "blossom_topics": max(safe_int(payload.get("blossom_topics"), 0), 0),
    }, degraded


def named_counts(raw: str | None, today: str) -> tuple[dict[str, int], bool]:
    payload, degraded = parse_json(raw, {})
    if not isinstance(payload, dict) or str(payload.get("date") or "") != today:
        return {}, degraded
    counts = payload.get("counts")
    if not isinstance(counts, dict):
        return {}, True
    return {str(key): max(safe_int(value, 0), 0) for key, value in counts.items()}, degraded


def slot_times(start_time: str, interval_hours: int) -> list[tuple[int, int]]:
    hour, minute = parse_time(start_time, "00:00")
    interval = max(interval_hours, 1)
    seen: set[tuple[int, int]] = set()
    result: list[tuple[int, int]] = []
    cursor = (hour * 60) + minute
    for _ in range(math.ceil(24 / interval) + 2):
        slot = ((cursor // 60) % 24, cursor % 60)
        if slot in seen:
            break
        seen.add(slot)
        result.append(slot)
        cursor += interval * 60
    return sorted(result)


def pill(label: str, tone: str) -> str:
    return f'<span class="pill pill-{tone}">{esc(label)}</span>'


def ratio_text(counter: dict[str, int]) -> str:
    total = max(counter.get("total_topics", 0), 0)
    blossom = max(counter.get("blossom_topics", 0), 0)
    if total <= 0:
        return "0 / 0 (0%)"
    return f"{blossom} / {total} ({round((blossom / total) * 100):.0f}%)"


def beat_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in BEAT_SCHEDULE:
        name = str(item["name"])
        seconds = safe_float(item["seconds"], 0.0)
        if seconds < 60:
            frequency = f"{int(seconds)}초"
        elif seconds % 60 == 0:
            frequency = f"{int(seconds // 60)}분"
        else:
            frequency = f"{seconds:.0f}초"
        rows.append({"name": name, "task": str(item["task"]), "frequency": frequency})
    return rows


def active_job_profile_counts(db) -> dict[str, int]:
    from app.models.entities import Blog  # noqa: WPS433

    rows = db.execute(
        select(Blog.profile_key, func.count(Job.id))
        .join(Job, Job.blog_id == Blog.id)
        .where(Job.status.in_(tuple(ACTIVE_JOB_STATUSES)))
        .group_by(Blog.profile_key)
    ).all()
    return {str(profile_key or ""): int(count) for profile_key, count in rows}


def today_status_distribution(db, today: str) -> dict[str, int]:
    rows = db.execute(
        select(Job.status, func.count(Job.id))
        .where(func.date(func.timezone("Asia/Seoul", Job.created_at)) == today)
        .group_by(Job.status)
    ).all()
    return {str(status.value if hasattr(status, "value") else status): int(count) for status, count in rows}


def metrics(db, today: str) -> dict[str, object]:
    active_profiles = active_job_profile_counts(db)
    return {
        "active_publish_queue": int(
            db.scalar(
                select(func.count(PublishQueueItem.id)).where(
                    PublishQueueItem.status.in_(("queued", "scheduled", "processing"))
                )
            )
            or 0
        ),
        "failed_publish_queue_today": int(
            db.scalar(
                select(func.count(PublishQueueItem.id)).where(
                    PublishQueueItem.status == "failed",
                    func.date(func.timezone("Asia/Seoul", PublishQueueItem.created_at)) == today,
                )
            )
            or 0
        ),
        "pending_review": int(
            db.scalar(select(func.count(ContentReviewItem.id)).where(ContentReviewItem.approval_status == "pending"))
            or 0
        ),
        "apply_failed": int(
            db.scalar(select(func.count(ContentReviewItem.id)).where(ContentReviewItem.apply_status == "failed")) or 0
        ),
        "low_risk": int(
            db.scalar(select(func.count(ContentReviewItem.id)).where(ContentReviewItem.risk_level == "low")) or 0
        ),
        "active_jobs": int(db.scalar(select(func.count(Job.id)).where(Job.status.in_(tuple(ACTIVE_JOB_STATUSES)))) or 0),
        "status_distribution": today_status_distribution(db, today),
        "active_profiles": active_profiles,
    }


def quality_thresholds(settings_map: dict[str, str]) -> dict[str, object]:
    return {
        "enabled": is_true(settings_map.get("quality_gate_enabled"), True),
        "similarity_threshold": safe_float(settings_map.get("quality_gate_similarity_threshold"), 70.0),
        "min_seo_score": safe_float(settings_map.get("quality_gate_min_seo_score"), 60.0),
        "min_geo_score": safe_float(settings_map.get("quality_gate_min_geo_score"), 60.0),
    }


def lane_for_blogger(
    title: str,
    start_time: str,
    interval_hours: int,
    topic_count: int,
    latest_raw: str | None,
    now: datetime,
    active_jobs: int,
) -> LaneSummary:
    latest = parse_marker(latest_raw)
    slots: list[LaneSlot] = []
    for hour, minute in slot_times(start_time, interval_hours):
        slot_dt = datetime.combine(now.date(), time(hour=hour, minute=minute), tzinfo=SEOUL_TZ)
        if latest and slot_dt == latest and active_jobs > 0:
            state, note = "in-progress", f"active {active_jobs}"
        elif latest and slot_dt <= latest:
            state, note = "ok", "completed"
        elif slot_dt <= now:
            state, note = "idle", "not completed"
        else:
            state, note = "upcoming", "future"
        slots.append(LaneSlot(hour, minute, f"{hour:02d}:{minute:02d}", state, note))
    return LaneSummary(title, start_time, interval_hours, topic_count, fmt_time(latest), slots)


def lane_for_cloudflare(
    start_time: str,
    interval_hours: int,
    latest_raw: str | None,
    now: datetime,
    daily_created: int,
    daily_quota: int,
) -> LaneSummary:
    latest = parse_marker(latest_raw)
    slots: list[LaneSlot] = []
    for hour, minute in slot_times(start_time, interval_hours):
        slot_dt = datetime.combine(now.date(), time(hour=hour, minute=minute), tzinfo=SEOUL_TZ)
        if latest and slot_dt <= latest:
            state, note = "ok", "successful"
        elif slot_dt <= now and daily_quota > 0 and daily_created >= daily_quota:
            state, note = "idle", "quota reached"
        elif slot_dt <= now:
            state, note = "partial", "due but open"
        else:
            state, note = "upcoming", "future"
        slots.append(LaneSlot(hour, minute, f"{hour:02d}:{minute:02d}", state, note))
    return LaneSummary("Cloudflare Daily", start_time, interval_hours, None, fmt_time(latest), slots)


def collect_snapshot() -> dict[str, object]:
    db = SessionLocal()
    try:
        settings_map = get_settings_map(db)
        now_dt = datetime.now(SEOUL_TZ)
        today = now_dt.date().isoformat()
        degraded: list[str] = []

        travel_counter, bad = topic_mix(settings_map.get("travel_daily_topic_mix_counts"), today)
        if bad:
            degraded.append("travel_daily_topic_mix_counts")
        cloudflare_counter, bad = topic_mix(settings_map.get("cloudflare_daily_topic_mix_counts"), today)
        if bad:
            degraded.append("cloudflare_daily_topic_mix_counts")
        travel_editorial_counts, bad = named_counts(settings_map.get("travel_editorial_daily_counts"), today)
        if bad:
            degraded.append("travel_editorial_daily_counts")
        mystery_editorial_counts, bad = named_counts(settings_map.get("mystery_editorial_daily_counts"), today)
        if bad:
            degraded.append("mystery_editorial_daily_counts")
        cloudflare_daily_counts, bad = named_counts(settings_map.get("cloudflare_daily_category_counts"), today)
        if bad:
            degraded.append("cloudflare_daily_category_counts")

        cloudflare_created = sum(cloudflare_daily_counts.values())
        cloudflare_quota = (
            max(safe_int(settings_map.get("cloudflare_daily_publish_sunday_quota"), 7), 0)
            if now_dt.weekday() == 6
            else max(safe_int(settings_map.get("cloudflare_daily_publish_weekday_quota"), 9), 0)
        )
        metrics_data = metrics(db, today)
        travel_lane = lane_for_blogger(
            "Travel Blogger",
            (settings_map.get("travel_schedule_time") or "00:00").strip() or "00:00",
            max(safe_int(settings_map.get("travel_schedule_interval_hours"), 2), 1),
            max(safe_int(settings_map.get("travel_topics_per_run"), 1), 1),
            settings_map.get("last_schedule_run_on_travel"),
            now_dt,
            safe_int(metrics_data["active_profiles"].get("korea_travel"), 0),
        )
        mystery_lane = lane_for_blogger(
            "Mystery Blogger",
            (settings_map.get("mystery_schedule_time") or "01:00").strip() or "01:00",
            max(safe_int(settings_map.get("mystery_schedule_interval_hours"), 2), 1),
            max(safe_int(settings_map.get("mystery_topics_per_run"), 1), 1),
            settings_map.get("last_schedule_run_on_mystery"),
            now_dt,
            safe_int(metrics_data["active_profiles"].get("world_mystery"), 0),
        )
        cloudflare_lane = lane_for_cloudflare(
            (settings_map.get("cloudflare_daily_publish_time") or "00:00").strip() or "00:00",
            max(safe_int(settings_map.get("cloudflare_daily_publish_interval_hours"), 2), 1),
            settings_map.get("cloudflare_daily_last_run_slot"),
            now_dt,
            cloudflare_created,
            cloudflare_quota,
        )

        return {
            "today": today,
            "now": fmt_datetime(now_dt),
            "now_dt": now_dt,
            "degraded": degraded,
            "beat": beat_rows(),
            "metrics": metrics_data,
            "travel_counter": travel_counter,
            "cloudflare_counter": cloudflare_counter,
            "travel_editorial_counts": travel_editorial_counts,
            "mystery_editorial_counts": mystery_editorial_counts,
            "travel_lane": travel_lane,
            "mystery_lane": mystery_lane,
            "cloudflare_lane": cloudflare_lane,
            "lanes": [travel_lane, mystery_lane, cloudflare_lane],
            "cloudflare_created": cloudflare_created,
            "cloudflare_quota": cloudflare_quota,
            "blogger_playwright_enabled": is_true(settings_map.get("blogger_playwright_enabled"), False),
            "blogger_playwright_auto_sync": is_true(settings_map.get("blogger_playwright_auto_sync"), False),
            "content_ops_scan_enabled": is_true(settings_map.get("content_ops_scan_enabled"), True),
            "publish_daily_limit_per_blog": safe_int(settings_map.get("publish_daily_limit_per_blog"), 0),
            "publish_min_interval_seconds": safe_int(settings_map.get("publish_min_interval_seconds"), 0),
            "sheet_sync_day": (settings_map.get("sheet_sync_day") or "SUNDAY").strip().upper() or "SUNDAY",
            "sheet_sync_time": (settings_map.get("sheet_sync_time") or "13:00").strip() or "13:00",
            "sheet_sync_last": (settings_map.get("last_sheet_sync_on") or "미실행").strip() or "미실행",
            "quality_thresholds": quality_thresholds(settings_map),
        }
    finally:
        db.close()


def timeline_row(lane: LaneSummary) -> str:
    slot_cells = []
    for slot in lane.slots:
        slot_cells.append(
            f"""
            <div class="slot slot-{esc(slot.state)}" title="{esc(slot.label)} | {esc(slot.note)}">
              <span class="slot-time">{esc(slot.label)}</span>
              <span class="slot-note">{esc(slot.note)}</span>
            </div>
            """
        )
    topic_text = "해당 없음" if lane.topic_count is None else f"런당 {lane.topic_count}개"
    return f"""
    <div class="timeline-row">
      <div class="timeline-side">
        <div class="timeline-title">{esc(lane.title)}</div>
        <div class="timeline-meta">시작 {esc(lane.start_time)} · {esc(lane.interval_hours)}시간 간격 · {esc(topic_text)}</div>
        <div class="timeline-latest">마지막 마커 {esc(lane.latest_marker)}</div>
      </div>
      <div class="timeline-grid">
        {''.join(slot_cells)}
      </div>
    </div>
    """


def flow_arrow() -> str:
    return """
    <div class="flow-arrow" aria-hidden="true">
      <svg viewBox="0 0 100 16" preserveAspectRatio="none">
        <path d="M2 8H92" />
        <path d="M82 2L98 8L82 14" />
      </svg>
    </div>
    """


def stage_box(title: str, note: str, tone: str = "default") -> str:
    return f"""
    <div class="stage stage-{esc(tone)}">
      <div class="stage-title">{esc(title)}</div>
      <div class="stage-note">{esc(note)}</div>
    </div>
    """


def swimlane(title: str, tone: str, stages: list[tuple[str, str, str]]) -> str:
    blocks: list[str] = []
    for index, stage in enumerate(stages):
        blocks.append(stage_box(stage[0], stage[1], stage[2]))
        if index < len(stages) - 1:
            blocks.append(flow_arrow())
    return f"""
    <section class="swimlane swimlane-{esc(tone)}">
      <div class="swimlane-head">
        <h3>{esc(title)}</h3>
      </div>
      <div class="swimlane-track">
        {''.join(blocks)}
      </div>
    </section>
    """


def failure_table_rows(snapshot: dict[str, object]) -> str:
    quality = snapshot["quality_thresholds"]
    rows = [
        (
            "Blogger Topic Discovery",
            "topic_selection_incomplete",
            "재생성 반복 후에도 목표 수량만큼 주제를 확보하지 못함",
            "Google Sheet 제외 + 중복 차단 + runtime blocked + 카테고리 조건이 동시에 강할 때",
        ),
        (
            "Travel / Cloudflare Topic Guard",
            "blossom_cap_blocked",
            "벚꽃 계열이 당일 전체 게시글 대비 20% cap을 초과해 차단됨",
            f"현재 Travel {ratio_text(snapshot['travel_counter'])} / Cloudflare {ratio_text(snapshot['cloudflare_counter'])}",
        ),
        (
            "Generation Quality Gate",
            "quality_gate_failed",
            "본문 품질이 게이트 기준을 못 넘겨 게시 전 중단됨",
            (
                f"enabled={quality['enabled']} · "
                f"SEO≥{quality['min_seo_score']:.0f} · "
                f"GEO≥{quality['min_geo_score']:.0f} · "
                f"Similarity≤{quality['similarity_threshold']:.0f}"
            ),
        ),
        (
            "Cloudflare Publish",
            "generation_created_zero",
            "생성 루프는 돌았지만 실제 원격 게시물 생성 건수가 0임",
            f"오늘 Cloudflare {snapshot['cloudflare_created']} / {snapshot['cloudflare_quota']}개",
        ),
        (
            "Blogger Publish / Queue",
            "publish_failed",
            "Blogger 인증, 원격 업데이트, queue 처리 실패로 게시가 완료되지 않음",
            (
                f"active queue {snapshot['metrics']['active_publish_queue']} · "
                f"failed today {snapshot['metrics']['failed_publish_queue_today']}"
            ),
        ),
    ]
    return "".join(
        f"""
        <tr>
          <td>{esc(stage)}</td>
          <td><code>{esc(code)}</code></td>
          <td>{esc(meaning)}</td>
          <td>{esc(trigger)}</td>
        </tr>
        """
        for stage, code, meaning, trigger in rows
    )


def snapshot_cards(snapshot: dict[str, object]) -> str:
    status_distribution = snapshot["metrics"]["status_distribution"]
    return "".join(
        [
            f"""
            <article class="metric-card">
              <span class="metric-label">Travel Blossom Mix</span>
              <strong class="metric-value">{esc(ratio_text(snapshot['travel_counter']))}</strong>
              <span class="metric-note">당일 total 대비 20% cap</span>
            </article>
            """,
            f"""
            <article class="metric-card">
              <span class="metric-label">Cloudflare Quota</span>
              <strong class="metric-value">{esc(f"{snapshot['cloudflare_created']} / {snapshot['cloudflare_quota']}")}</strong>
              <span class="metric-note">오늘 생성 수 / 당일 quota</span>
            </article>
            """,
            f"""
            <article class="metric-card">
              <span class="metric-label">Travel Rotation</span>
              <strong class="metric-value">{esc(', '.join(f'{k}:{v}' for k, v in snapshot['travel_editorial_counts'].items()) or '없음')}</strong>
              <span class="metric-note">travel / culture / food</span>
            </article>
            """,
            f"""
            <article class="metric-card">
              <span class="metric-label">Mystery Rotation</span>
              <strong class="metric-value">{esc(', '.join(f'{k}:{v}' for k, v in snapshot['mystery_editorial_counts'].items()) or '없음')}</strong>
              <span class="metric-note">case-files / archives / lore</span>
            </article>
            """,
            f"""
            <article class="metric-card">
              <span class="metric-label">Google Sheet Sync</span>
              <strong class="metric-value">{esc(f"{snapshot['sheet_sync_day']} {snapshot['sheet_sync_time']}")}</strong>
              <span class="metric-note">마지막 동기화 {esc(snapshot['sheet_sync_last'])}</span>
            </article>
            """,
            f"""
            <article class="metric-card">
              <span class="metric-label">Content Ops / Queue</span>
              <strong class="metric-value">{esc(f"pending {snapshot['metrics']['pending_review']} · queue {snapshot['metrics']['active_publish_queue']}")}</strong>
              <span class="metric-note">{esc(f"scan {'ON' if snapshot['content_ops_scan_enabled'] else 'OFF'} · apply failed {snapshot['metrics']['apply_failed']}")}</span>
            </article>
            """,
            f"""
            <article class="metric-card">
              <span class="metric-label">Blogger Meta Sync</span>
              <strong class="metric-value">{esc('ON' if snapshot['blogger_playwright_enabled'] else 'OFF')}</strong>
              <span class="metric-note">{esc('auto_sync ON' if snapshot['blogger_playwright_auto_sync'] else 'auto_sync OFF')}</span>
            </article>
            """,
            f"""
            <article class="metric-card">
              <span class="metric-label">Today Job Status</span>
              <strong class="metric-value">{esc(', '.join(f'{k}:{v}' for k, v in status_distribution.items()) or '없음')}</strong>
              <span class="metric-note">오늘 생성된 Job 상태 분포</span>
            </article>
            """,
        ]
    )


def code_links() -> str:
    links = []
    for path in CODE_FILES:
        href = "file:///" + str(path).replace("\\", "/")
        links.append(f'<a href="{esc(href)}">{esc(path.name)}</a>')
    return " · ".join(links)


def legend_html() -> str:
    chips = [
        pill("ok", "ok"),
        pill("idle", "idle"),
        pill("partial", "partial"),
        pill("failed", "failed"),
        pill("in-progress", "progress"),
        pill("upcoming", "upcoming"),
        pill("draft", "idle"),
        pill("scheduled", "partial"),
        pill("published", "ok"),
    ]
    return "".join(chips)


def render_html(snapshot: dict[str, object]) -> str:
    beat_cards = "".join(
        f"""
        <article class="beat-card">
          <span class="beat-name">{esc(row['name'])}</span>
          <strong class="beat-frequency">{esc(row['frequency'])}</strong>
          <span class="beat-task">{esc(row['task'])}</span>
        </article>
        """
        for row in snapshot["beat"]
    )
    degraded = snapshot["degraded"]
    degraded_html = (
        f'<div class="degraded-note">{pill("degraded", "failed")} {esc(", ".join(degraded))}</div>' if degraded else ""
    )
    blogger_swimlane = swimlane(
        "Blogger Pipeline",
        "blogger",
        [
            ("Scheduler Slot", "Travel / Mystery 시간표에 따라 슬롯 진입", "default"),
            ("Topic Discovery", "프롬프트 생성 + Sheet 제외 + 중복 차단", "default"),
            ("Queue / Job", "주제 확정 후 Job 생성", "progress"),
            ("Generation", "본문 생성 + Quality Gate + 이미지 생성", "default"),
            ("Publish", "Blogger draft / scheduled / published", "ok"),
        ],
    )
    cloudflare_swimlane = swimlane(
        "Cloudflare Pipeline",
        "cloudflare",
        [
            ("Daily Slot", "당일 due slot 계산, quota 확인", "default"),
            ("Topic Retry Loop", "카테고리 맞춤 주제 재생성 + blossom cap", "default"),
            ("Generation", "본문 + 품질 게이트 + 이미지 생성", "progress"),
            ("Integration POST", "원격 API 생성 요청", "default"),
            ("Slot Consume", "created_count >= 1일 때만 슬롯 소비", "ok"),
        ],
    )
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>운영 파이프라인 대시보드 - {esc(snapshot['today'])}</title>
    <style>
      :root {{
        --bg: #f5f1e8;
        --paper: #fffdf9;
        --card: #ffffff;
        --ink: #1c2733;
        --muted: #5b6774;
        --line: #d8d2c5;
        --teal: #0f766e;
        --navy: #12304a;
        --ok: #166534;
        --ok-soft: #dcfce7;
        --idle: #475569;
        --idle-soft: #e2e8f0;
        --partial: #b45309;
        --partial-soft: #ffedd5;
        --failed: #b91c1c;
        --failed-soft: #fee2e2;
        --progress: #1d4ed8;
        --progress-soft: #dbeafe;
        --upcoming: #7c3aed;
        --upcoming-soft: #ede9fe;
        --shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background:
          radial-gradient(circle at top left, rgba(15, 118, 110, 0.08), transparent 28rem),
          linear-gradient(180deg, #faf8f2 0%, var(--bg) 100%);
        color: var(--ink);
        font-family: "Segoe UI", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
        line-height: 1.5;
      }}
      .page {{
        width: min(1440px, calc(100% - 28px));
        margin: 18px auto 40px;
      }}
      .hero {{
        display: grid;
        grid-template-columns: 2fr 1fr;
        gap: 18px;
        padding: 28px;
        border-radius: 28px;
        background: linear-gradient(140deg, var(--teal), #0f5f69 58%, var(--navy));
        color: #f8fafc;
        box-shadow: var(--shadow);
      }}
      .hero h1 {{
        margin: 0 0 10px;
        font-size: clamp(30px, 4vw, 52px);
        line-height: 1.06;
        letter-spacing: -0.03em;
      }}
      .hero-copy p {{
        margin: 0;
        max-width: 760px;
        color: rgba(248, 250, 252, 0.86);
      }}
      .meta-stack {{
        display: grid;
        gap: 12px;
      }}
      .hero-card {{
        padding: 16px 18px;
        border: 1px solid rgba(255,255,255,0.18);
        border-radius: 18px;
        background: rgba(255,255,255,0.1);
      }}
      .hero-label, .section-label {{
        display: inline-block;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: rgba(248,250,252,0.72);
      }}
      .hero-value {{
        display: block;
        margin-top: 8px;
        font-size: 18px;
        font-weight: 700;
      }}
      .generated {{
        margin-top: 14px;
        font-size: 13px;
        color: rgba(248,250,252,0.74);
      }}
      .summary-strip {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin-top: 18px;
      }}
      .summary-card {{
        padding: 16px 18px;
        border-radius: 18px;
        background: rgba(255,255,255,0.12);
        border: 1px solid rgba(255,255,255,0.16);
      }}
      .summary-card strong {{
        display: block;
        margin-top: 8px;
        font-size: 18px;
      }}
      .summary-card span:last-child {{
        display: block;
        margin-top: 6px;
        font-size: 13px;
        color: rgba(248,250,252,0.84);
      }}
      .section {{
        margin-top: 22px;
        padding: 24px;
        background: var(--paper);
        border: 1px solid var(--line);
        border-radius: 24px;
        box-shadow: var(--shadow);
      }}
      .section-head {{
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 16px;
      }}
      .section h2 {{
        margin: 0;
        font-size: 24px;
        line-height: 1.2;
        letter-spacing: -0.02em;
      }}
      .section-copy {{
        color: var(--muted);
        font-size: 14px;
      }}
      .pill {{
        display: inline-flex;
        align-items: center;
        padding: 6px 10px;
        margin: 0 8px 8px 0;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 700;
      }}
      .pill-ok {{ background: var(--ok-soft); color: var(--ok); }}
      .pill-idle {{ background: var(--idle-soft); color: var(--idle); }}
      .pill-partial {{ background: var(--partial-soft); color: var(--partial); }}
      .pill-failed {{ background: var(--failed-soft); color: var(--failed); }}
      .pill-progress {{ background: var(--progress-soft); color: var(--progress); }}
      .pill-upcoming {{ background: var(--upcoming-soft); color: var(--upcoming); }}
      .timeline-wrap {{
        overflow-x: auto;
        padding-bottom: 4px;
      }}
      .timeline-scale, .timeline-grid {{
        display: grid;
        grid-template-columns: repeat(12, minmax(96px, 1fr));
        gap: 8px;
      }}
      .timeline-scale {{
        margin-left: 260px;
        margin-bottom: 10px;
      }}
      .timeline-scale span {{
        font-size: 12px;
        font-weight: 700;
        color: var(--muted);
      }}
      .timeline-row {{
        display: grid;
        grid-template-columns: 248px 1fr;
        gap: 12px;
        align-items: start;
        margin-bottom: 14px;
      }}
      .timeline-side {{
        padding: 14px 16px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: var(--card);
      }}
      .timeline-title {{
        font-size: 18px;
        font-weight: 800;
      }}
      .timeline-meta, .timeline-latest {{
        margin-top: 6px;
        font-size: 13px;
        color: var(--muted);
      }}
      .slot {{
        min-height: 74px;
        padding: 10px 12px;
        border-radius: 16px;
        border: 1px solid transparent;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }}
      .slot-time {{ font-size: 13px; font-weight: 800; }}
      .slot-note {{ font-size: 12px; color: var(--muted); }}
      .slot-ok {{ background: var(--ok-soft); border-color: rgba(22,101,52,0.12); }}
      .slot-idle {{ background: var(--idle-soft); border-color: rgba(71,85,105,0.12); }}
      .slot-partial {{ background: var(--partial-soft); border-color: rgba(180,83,9,0.12); }}
      .slot-in-progress {{ background: var(--progress-soft); border-color: rgba(29,78,216,0.12); }}
      .slot-upcoming {{ background: var(--upcoming-soft); border-color: rgba(124,58,237,0.12); }}
      .legend-box, .beats-grid, .snapshot-grid {{
        display: grid;
        gap: 12px;
      }}
      .legend-box {{
        grid-template-columns: 1.2fr 1fr;
      }}
      .legend-card, .beat-card, .metric-card, .rule-card {{
        padding: 16px 18px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: var(--card);
      }}
      .beat-card {{
        min-height: 120px;
      }}
      .beats-grid {{
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }}
      .beat-name, .metric-label {{
        display: block;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .beat-frequency, .metric-value {{
        display: block;
        margin-top: 10px;
        font-size: 22px;
        line-height: 1.2;
      }}
      .beat-task, .metric-note {{
        display: block;
        margin-top: 8px;
        font-size: 13px;
        color: var(--muted);
      }}
      .swimlanes {{
        display: grid;
        gap: 16px;
      }}
      .swimlane {{
        border: 1px solid var(--line);
        border-radius: 22px;
        background: linear-gradient(180deg, #fffefb 0%, #fffdfa 100%);
        padding: 18px;
      }}
      .swimlane h3 {{
        margin: 0 0 14px;
        font-size: 19px;
      }}
      .swimlane-track {{
        display: flex;
        align-items: stretch;
        gap: 12px;
        overflow-x: auto;
        padding-bottom: 2px;
      }}
      .stage {{
        flex: 0 0 220px;
        min-height: 120px;
        padding: 16px;
        border-radius: 18px;
        border: 1px solid var(--line);
        background: var(--card);
      }}
      .stage-default {{ background: linear-gradient(180deg, #ffffff 0%, #f8fbfb 100%); }}
      .stage-ok {{ background: linear-gradient(180deg, #f6fff9 0%, #ecfdf5 100%); }}
      .stage-progress {{ background: linear-gradient(180deg, #f4f8ff 0%, #eff6ff 100%); }}
      .stage-title {{
        font-size: 15px;
        font-weight: 800;
      }}
      .stage-note {{
        margin-top: 8px;
        font-size: 13px;
        color: var(--muted);
      }}
      .flow-arrow {{
        flex: 0 0 70px;
        display: flex;
        align-items: center;
        justify-content: center;
      }}
      .flow-arrow svg {{
        width: 100%;
        height: 16px;
        stroke: #90a4ae;
        fill: none;
        stroke-width: 2.5;
        stroke-linecap: round;
        stroke-linejoin: round;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        overflow: hidden;
        border-radius: 18px;
      }}
      th, td {{
        text-align: left;
        padding: 14px 16px;
        border-bottom: 1px solid var(--line);
        vertical-align: top;
      }}
      th {{
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
        background: #faf7f1;
      }}
      tr:last-child td {{ border-bottom: none; }}
      code {{
        display: inline-block;
        padding: 3px 8px;
        border-radius: 8px;
        background: #f3f4f6;
        font-family: Consolas, "SFMono-Regular", monospace;
        font-size: 12px;
      }}
      .rule-grid {{
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 16px;
      }}
      .rule-card.warn {{
        background: linear-gradient(180deg, #fffdf5 0%, #fffbeb 100%);
        border-color: #f3d6a2;
      }}
      .snapshot-grid {{
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }}
      .degraded-note {{
        margin-top: 14px;
        color: #fff7ed;
        font-size: 13px;
      }}
      .footer-links {{
        margin-top: 18px;
        font-size: 13px;
        color: var(--muted);
      }}
      .footer-links a {{
        color: var(--teal);
        text-decoration: none;
      }}
      .footer-links a:hover {{ text-decoration: underline; }}
      @media (max-width: 1100px) {{
        .hero, .legend-box, .rule-grid {{ grid-template-columns: 1fr; }}
        .summary-strip, .beats-grid, .snapshot-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      }}
      @media (max-width: 720px) {{
        .page {{ width: min(100%, calc(100% - 16px)); margin: 10px auto 24px; }}
        .hero, .section {{ padding: 18px; border-radius: 20px; }}
        .summary-strip, .beats-grid, .snapshot-grid {{ grid-template-columns: 1fr; }}
        .timeline-scale {{ margin-left: 0; min-width: 1200px; }}
        .timeline-row {{ grid-template-columns: 1fr; }}
        .timeline-grid {{ min-width: 1200px; }}
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <section class="hero">
        <div class="hero-copy">
          <span class="hero-label">Operations Dashboard</span>
          <h1>운영 파이프라인 대시보드</h1>
          <p>주제 생성부터 게시 완료까지의 자동화 흐름을 오늘 스냅샷 기준으로 압축한 운영 리포트입니다. 시간표, 상태값, 실패지점, quota, 벚꽃 cap 규칙을 한 화면에 정리했습니다.</p>
          <div class="summary-strip">
            <article class="summary-card">
              <span class="hero-label">Travel</span>
              <strong>{esc(snapshot['travel_lane'].latest_marker)}</strong>
              <span>시작 {esc(snapshot['travel_lane'].start_time)} · {esc(snapshot['travel_lane'].interval_hours)}시간 간격</span>
            </article>
            <article class="summary-card">
              <span class="hero-label">Mystery</span>
              <strong>{esc(snapshot['mystery_lane'].latest_marker)}</strong>
              <span>시작 {esc(snapshot['mystery_lane'].start_time)} · {esc(snapshot['mystery_lane'].interval_hours)}시간 간격</span>
            </article>
            <article class="summary-card">
              <span class="hero-label">Cloudflare</span>
              <strong>{esc(snapshot['cloudflare_lane'].latest_marker)}</strong>
              <span>성공 슬롯 기준 · {esc(snapshot['cloudflare_created'])}/{esc(snapshot['cloudflare_quota'])}</span>
            </article>
            <article class="summary-card">
              <span class="hero-label">Scheduler Beat</span>
              <strong>{esc(next((row['frequency'] for row in snapshot['beat'] if row['name'] == 'scheduler_tick'), '60초'))}</strong>
              <span>run_scheduler_tick() 기준</span>
            </article>
          </div>
        </div>
        <div class="meta-stack">
          <div class="hero-card">
            <span class="hero-label">Generated from live DB snapshot</span>
            <strong class="hero-value">{esc(snapshot['now'])}</strong>
          </div>
          <div class="hero-card">
            <span class="hero-label">Timezone</span>
            <strong class="hero-value">Asia/Seoul · KST</strong>
          </div>
          <div class="hero-card">
            <span class="hero-label">Active Jobs</span>
            <strong class="hero-value">{esc(snapshot['metrics']['active_jobs'])}</strong>
          </div>
          <div class="hero-card">
            <span class="hero-label">Quality Gate</span>
            <strong class="hero-value">{esc('ON' if snapshot['quality_thresholds']['enabled'] else 'OFF')}</strong>
          </div>
          <div class="generated">Generated from live DB snapshot · {esc(snapshot['now'])}</div>
          {degraded_html}
        </div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <span class="section-label" style="color: var(--muted);">24H Timeline</span>
            <h2>운영 시간표</h2>
          </div>
          <div class="section-copy">00~23시 KST 기준 슬롯 상태</div>
        </div>
        <div class="timeline-wrap">
          <div class="timeline-scale">
            <span>00-02</span><span>02-04</span><span>04-06</span><span>06-08</span><span>08-10</span><span>10-12</span>
            <span>12-14</span><span>14-16</span><span>16-18</span><span>18-20</span><span>20-22</span><span>22-24</span>
          </div>
          {timeline_row(snapshot['travel_lane'])}
          {timeline_row(snapshot['mystery_lane'])}
          {timeline_row(snapshot['cloudflare_lane'])}
        </div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <span class="section-label" style="color: var(--muted);">State Legend</span>
            <h2>상태값과 스케줄 비트</h2>
          </div>
          <div class="section-copy">JobStatus / PostStatus / Cloudflare slot status</div>
        </div>
        <div class="legend-box">
          <div class="legend-card">
            <div>{legend_html()}</div>
            <p class="section-copy">`ok=성공`, `idle=미실행 또는 quota 도달`, `partial=due but open`, `failed=오류`, `in-progress=진행중`, `upcoming=미래 슬롯`</p>
            <p class="section-copy">Blogger PostStatus는 `draft`, `scheduled`, `published` 로 운영되고, JobStatus는 `PENDING → DISCOVERING_TOPICS → GENERATING_* → PUBLISHING → COMPLETED/FAILED` 흐름입니다.</p>
          </div>
          <div class="legend-card">
            <span class="metric-label">Publish Guard</span>
            <strong class="metric-value">{esc(f"daily_limit {snapshot['publish_daily_limit_per_blog']} · min_interval {snapshot['publish_min_interval_seconds']}s")}</strong>
            <span class="metric-note">현재 publish queue 가드 설정 요약</span>
          </div>
        </div>
        <div class="beats-grid" style="margin-top: 14px;">
          {beat_cards}
        </div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <span class="section-label" style="color: var(--muted);">Pipeline Swimlanes</span>
            <h2>자동화 파이프라인</h2>
          </div>
          <div class="section-copy">Blogger / Cloudflare 주요 단계</div>
        </div>
        <div class="swimlanes">
          {blogger_swimlane}
          {cloudflare_swimlane}
        </div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <span class="section-label" style="color: var(--muted);">Failure Hotspots</span>
            <h2>실패 지점</h2>
          </div>
          <div class="section-copy">Stage → Error → Meaning → Current Trigger</div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Stage</th>
              <th>Error</th>
              <th>Meaning</th>
              <th>Current Trigger</th>
            </tr>
          </thead>
          <tbody>
            {failure_table_rows(snapshot)}
          </tbody>
        </table>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <span class="section-label" style="color: var(--muted);">Blossom Policy</span>
            <h2>벚꽃 cap 규칙</h2>
          </div>
          <div class="section-copy">Travel / Cloudflare only</div>
        </div>
        <div class="rule-grid">
          <article class="rule-card warn">
            <span class="metric-label">Rule</span>
            <strong class="metric-value">벚꽃 계열 전체 20% cap</strong>
            <span class="metric-note">벚꽃 / 왕벚꽃 / 겹벚꽃 / 봄꽃 / cherry blossom / sakura 를 같은 blossom bucket 으로 계산합니다.</span>
          </article>
          <article class="rule-card">
            <span class="metric-label">Bootstrap</span>
            <strong class="metric-value">첫 blossom 1건 허용</strong>
            <span class="metric-note">당일 total이 0일 때 1건은 허용하고, 이후부터 total 대비 20% 초과 시 차단합니다.</span>
          </article>
        </div>
      </section>

      <section class="section">
        <div class="section-head">
          <div>
            <span class="section-label" style="color: var(--muted);">Today Snapshot</span>
            <h2>오늘 운영 수치</h2>
          </div>
          <div class="section-copy">카운터, rotation, sync, review, queue 요약</div>
        </div>
        <div class="snapshot-grid">
          {snapshot_cards(snapshot)}
        </div>
        <div class="footer-links">
          코드 기준점: {code_links()}
        </div>
      </section>
    </main>
  </body>
</html>
"""


def main() -> int:
    snapshot = collect_snapshot()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"ops-pipeline-dashboard-{snapshot['today']}.html"
    report_path.write_text(render_html(snapshot), encoding="utf-8", newline="\n")
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
