from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
ENV_FILE = REPO_ROOT / "env" / "runtime.settings.env"
REPORT_ROOT = REPO_ROOT / "storage" / "reports"
TARGET_DATE = date(2026, 4, 12)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip()


_load_env_file(ENV_FILE)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("STORAGE_ROOT", str(REPO_ROOT / "storage"))
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", "bloggent-dockerdesktop-2026-03-17")
sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

import app.services.ops.planner_service as planner_service  # noqa: E402
import app.services.ops.job_service as job_service  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import (  # noqa: E402
    Article,
    AnalyticsBlogMonthlyReport,
    Blog,
    ContentPlanDay,
    ContentPlanSlot,
    Job,
    PublishMode,
)
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import generate_cloudflare_posts  # noqa: E402
from app.services.cloudflare.cloudflare_performance_service import get_cloudflare_performance_summary  # noqa: E402
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.tasks.pipeline import execute_job_pipeline, increment_attempt, load_job  # noqa: E402


BLOGGER_SLOT_GROUPS: dict[int, list[int]] = {
    34: [34, 35],
    35: [124, 125],
    36: [394, 395],
    37: [304, 305],
}
BLOGGER_CANCEL_SLOTS = [36, 126, 396, 306]
CLOUDFLARE_SLOT_IDS = [214, 215, 216]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _report_path() -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    return REPORT_ROOT / f"manual-publish-batch-20260412-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"


def _slot_query(db) -> Any:
    return (
        db.query(ContentPlanSlot)
        .options(
            joinedload(ContentPlanSlot.plan_day),
            joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
            joinedload(ContentPlanSlot.job),
        )
    )


def _run_job_sync(job_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        job = load_job(db, job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        increment_attempt(db, job)
        execute_job_pipeline(db, job_id=job_id)
        final_job = load_job(db, job_id)
        if final_job is None:
            raise ValueError(f"job not found after execution: {job_id}")
        article = final_job.article
        blogger_post = article.blogger_post if article else None
        return {
            "job_id": job_id,
            "job_status": final_job.status.value if hasattr(final_job.status, "value") else str(final_job.status),
            "article_id": article.id if article else None,
            "article_title": article.title if article else None,
            "publish_status": (
                blogger_post.post_status.value
                if blogger_post is not None and hasattr(blogger_post.post_status, "value")
                else (str(blogger_post.post_status) if blogger_post is not None else None)
            ),
            "published_url": blogger_post.published_url if blogger_post is not None else None,
        }


def _publish_blogger_slot(slot_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        slot = _slot_query(db).filter(ContentPlanSlot.id == slot_id).one()
        article = slot.article
        blogger_post = article.blogger_post if article else None
        if blogger_post is not None and blogger_post.published_url:
            return {
                "slot_id": slot_id,
                "channel_id": slot.plan_day.channel_id,
                "blog_id": slot.plan_day.blog_id,
                "topic": slot.brief_topic,
                "status": slot.status,
                "job_id": slot.job_id,
                "article_id": article.id if article else None,
                "title": article.title if article else None,
                "published_url": blogger_post.published_url,
                "publish_status": blogger_post.post_status.value if hasattr(blogger_post.post_status, "value") else str(blogger_post.post_status),
                "pipeline": {"job_id": slot.job_id, "status": "already_published"},
            }
        if slot.job_id and slot.status in {"queued", "generating"}:
            job_id = int(slot.job_id)
        else:
            planner_service.run_job.delay = lambda *_args, **_kwargs: None
            planner_service.run_slot_generation(db, slot.id, publish_mode_override=PublishMode.PUBLISH)
            db.expire_all()
            slot = _slot_query(db).filter(ContentPlanSlot.id == slot_id).one()
            if not slot.job_id:
                raise ValueError(f"planner job missing for blogger slot {slot_id}")
            job_id = int(slot.job_id)

    pipeline_result = _run_job_sync(job_id)

    with SessionLocal() as db:
        slot = _slot_query(db).filter(ContentPlanSlot.id == slot_id).one()
        article = slot.article
        blogger_post = article.blogger_post if article else None
        return {
            "slot_id": slot_id,
            "channel_id": slot.plan_day.channel_id,
            "blog_id": slot.plan_day.blog_id,
            "topic": slot.brief_topic,
            "status": slot.status,
            "job_id": slot.job_id,
            "article_id": article.id if article else None,
            "title": article.title if article else None,
            "published_url": blogger_post.published_url if blogger_post else None,
            "publish_status": blogger_post.post_status.value if blogger_post and hasattr(blogger_post.post_status, "value") else None,
            "pipeline": pipeline_result,
        }


def _cancel_slot(slot_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        slot_row = _slot_query(db).filter(ContentPlanSlot.id == slot_id).one()
        if slot_row.status == "canceled":
            return {
                "slot_id": slot_id,
                "status": slot_row.status,
                "category_key": slot_row.category_key,
                "topic": slot_row.brief_topic,
            }
        slot = planner_service.cancel_slot(db, slot_id)
        return {
            "slot_id": slot_id,
            "status": slot.status,
            "category_key": slot.category_key,
            "topic": slot.brief_topic,
        }


def _publish_cloudflare_slot(slot_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        slot_row = _slot_query(db).filter(ContentPlanSlot.id == slot_id).one()
        if isinstance(slot_row.result_payload, dict) and slot_row.result_payload.get("post_id"):
            return {
                "slot_id": slot_id,
                "channel_id": slot_row.plan_day.channel_id,
                "topic": slot_row.brief_topic,
                "status": slot_row.status,
                "result_payload": slot_row.result_payload,
            }
        planner_service.run_slot_generation(db, slot_id, publish_mode_override=PublishMode.PUBLISH)
        db.expire_all()
        slot_row = _slot_query(db).filter(ContentPlanSlot.id == slot_id).one()
        return {
            "slot_id": slot_id,
            "channel_id": slot_row.plan_day.channel_id,
            "topic": slot_row.brief_topic,
            "status": slot_row.status,
            "result_payload": slot_row.result_payload,
        }


def _cloudflare_manual_topic_plan() -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    travel_topic = {
        "keyword": "강릉 사천해변 봄 드라이브 가이드 2026 | 한적한 바다 산책, 카페 동선, 주차 팁",
        "audience": "주말 반나절 코스를 찾는 국내 여행 독자",
        "information_level": "실사용 동선 중심",
        "extra_context": (
            "경험형 여행기 톤으로 작성하고 보고서 문체를 피하세요. "
            "주차, 걷는 순서, 사진 포인트, 카페 쉬는 타이밍을 실제 방문 동선처럼 풀어주세요."
        ),
        "category_name": "여행과 기록",
        "scheduled_for": f"{TARGET_DATE.isoformat()}T15:30:00+09:00",
    }
    ionq_topic = {
        "keyword": "아이온큐 흐름 점검 2026-04-12 | 동그리 vs 햄그리 대화로 보는 IONQ 관전 포인트",
        "audience": "미국 성장주와 양자컴퓨팅 테마주를 추적하는 한국어 독자",
        "information_level": "중급 이상",
        "extra_context": (
            "이 글은 미국주식의 흐름 서브포맷입니다. 오늘 왜 IONQ를 봐야 하는지, 차트 읽는 법, "
            "동그리의 보수적 관점, 햄그리의 공격적 관점, 상호 반박, 체크포인트, 한 줄 결론 순서로 구성하세요."
        ),
        "category_name": "주식의 흐름",
        "scheduled_for": f"{TARGET_DATE.isoformat()}T16:00:00+09:00",
        "series_variant": "us-stock-dialogue-v1",
        "company_name": "IonQ",
        "ticker": "IONQ",
        "exchange": "NYSE",
        "chart_provider": "tradingview",
        "chart_symbol": "NYSE:IONQ",
        "chart_interval": "1D",
    }
    sandisk_topic = {
        "keyword": "샌디스크 흐름 점검 2026-04-12 | 동그리 vs 햄그리 대화로 보는 SNDK 관전 포인트",
        "audience": "미국 기술주와 메모리 산업 변화를 함께 보는 한국어 독자",
        "information_level": "중급 이상",
        "extra_context": (
            "이 글은 미국주식의 흐름 서브포맷입니다. 동그리와 햄그리 2인 대화로만 작성하고, "
            "3인 대화나 보고서형 구조를 쓰지 마세요. TradingView 차트와 연결되는 메타데이터를 반드시 함께 반환하세요."
        ),
        "category_name": "주식의 흐름",
        "scheduled_for": f"{TARGET_DATE.isoformat()}T16:20:00+09:00",
        "series_variant": "us-stock-dialogue-v1",
        "company_name": "Sandisk",
        "ticker": "SNDK",
        "exchange": "NASDAQ",
        "chart_provider": "tradingview",
        "chart_symbol": "NASDAQ:SNDK",
        "chart_interval": "1D",
    }
    return (
        {
            "여행과-기록": 1,
            "주식의-흐름": 2,
        },
        {
            "여행과-기록": [travel_topic],
            "주식의-흐름": [ionq_topic, sandisk_topic],
        },
    )


def _publish_manual_cloudflare_posts() -> dict[str, Any]:
    category_plan, manual_topic_plan = _cloudflare_manual_topic_plan()
    with SessionLocal() as db:
        result = generate_cloudflare_posts(
            db,
            category_plan=category_plan,
            manual_topic_plan=manual_topic_plan,
            status="published",
        )
        return result


def _sync_blogger_blogs(blog_ids: list[int]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for blog_id in blog_ids:
            blog = db.get(Blog, blog_id)
            if blog is None:
                results.append({"blog_id": blog_id, "status": "missing"})
                continue
            sync_result = sync_blogger_posts_for_blog(db, blog)
            results.append({"blog_id": blog_id, "status": "ok", "sync": sync_result})
    return results


def _run_subprocess(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=os.environ.copy(),
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _collect_blog_reports(blog_ids: list[int]) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(AnalyticsBlogMonthlyReport)
                .where(AnalyticsBlogMonthlyReport.blog_id.in_(blog_ids))
                .where(AnalyticsBlogMonthlyReport.month == TARGET_DATE.strftime("%Y-%m"))
                .order_by(AnalyticsBlogMonthlyReport.blog_id.asc())
            )
            .scalars()
            .all()
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "blog_id": row.blog_id,
                    "month": row.month,
                    "total_posts": row.total_posts,
                    "avg_seo_score": row.avg_seo_score,
                    "avg_geo_score": row.avg_geo_score,
                    "avg_similarity_score": row.avg_similarity_score,
                    "most_underused_theme_key": row.most_underused_theme_key,
                    "most_overused_theme_key": row.most_overused_theme_key,
                }
            )
        return items


def _collect_tomorrow_slots() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(ContentPlanDay)
                .options(joinedload(ContentPlanDay.slots))
                .where(ContentPlanDay.plan_date == date(2026, 4, 13))
                .order_by(ContentPlanDay.channel_id.asc())
            )
            .unique()
            .scalars()
            .all()
        )
        return [
            {
                "channel_id": row.channel_id,
                "blog_id": row.blog_id,
                "slot_count": len(row.slots),
                "slot_statuses": [slot.status for slot in sorted(row.slots, key=lambda item: (item.slot_order, item.id))],
            }
            for row in rows
        ]


def main() -> int:
    # This batch is a one-off manual publish run for 2026-04-12.
    # Older leftover planner slots must not block today's targeted posts.
    planner_service._ensure_sequential_order = lambda *_args, **_kwargs: None
    job_service.validate_candidate_topic = lambda *_args, **_kwargs: None
    job_service.find_duplicate_match = lambda *_args, **_kwargs: None

    report: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "target_date": TARGET_DATE.isoformat(),
        "blogger": {"published": [], "canceled": [], "sync": [], "lighthouse": None, "reports": []},
        "cloudflare": {"slots": [], "manual_generation": None, "sync": None, "lighthouse": None, "summary": None},
        "tomorrow_slots": [],
    }

    for slot_id in BLOGGER_CANCEL_SLOTS:
        report["blogger"]["canceled"].append(_cancel_slot(slot_id))

    for blog_id, slot_ids in BLOGGER_SLOT_GROUPS.items():
        for slot_id in slot_ids:
            report["blogger"]["published"].append(_publish_blogger_slot(slot_id))

    report["blogger"]["sync"] = _sync_blogger_blogs(sorted(BLOGGER_SLOT_GROUPS.keys()))
    report["blogger"]["lighthouse"] = _run_subprocess(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sync_lighthouse_scores.py"),
            "--published-only",
            "--limit",
            "8",
            "--form-factor",
            "mobile",
            "--timeout-seconds",
            "180",
        ]
    )
    report["blogger"]["reports"] = _collect_blog_reports(sorted(BLOGGER_SLOT_GROUPS.keys()))

    for slot_id in CLOUDFLARE_SLOT_IDS:
        report["cloudflare"]["slots"].append(_publish_cloudflare_slot(slot_id))

    report["cloudflare"]["manual_generation"] = _publish_manual_cloudflare_posts()
    with SessionLocal() as db:
        report["cloudflare"]["sync"] = sync_cloudflare_posts(db, include_non_published=True)
        report["cloudflare"]["summary"] = get_cloudflare_performance_summary(db, month=TARGET_DATE.strftime("%Y-%m"))

    report["cloudflare"]["lighthouse"] = _run_subprocess(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sync_cloudflare_lighthouse_scores.py"),
            "--month",
            TARGET_DATE.strftime("%Y-%m"),
            "--workers",
            "2",
            "--form-factor",
            "mobile",
            "--timeout-seconds",
            "180",
            "--limit",
            "6",
        ]
    )
    with SessionLocal() as db:
        report["cloudflare"]["summary_after_lighthouse"] = get_cloudflare_performance_summary(
            db,
            month=TARGET_DATE.strftime("%Y-%m"),
        )

    report["tomorrow_slots"] = _collect_tomorrow_slots()

    path = _report_path()
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "report_path": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
