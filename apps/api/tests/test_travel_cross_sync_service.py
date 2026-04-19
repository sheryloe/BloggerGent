from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Article, Blog, ContentPlanDay, ContentPlanSlot, Image, Job, Topic
from app.services.content.travel_cross_sync_service import (
    TravelSyncBacklogItem,
    assign_backlog_schedule_slots,
    build_missing_target_daily_quota_map,
    build_travel_sync_groups,
    enqueue_travel_cross_sync_jobs,
    seed_travel_weekly_planner_slots,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _create_blog(db: Session, *, blog_id: int, slug: str, language: str) -> Blog:
    row = Blog(
        id=blog_id,
        name=f"Travel-{language}",
        slug=slug,
        content_category="travel",
        primary_language=language,
        profile_key="korea_travel",
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _create_article(
    db: Session,
    *,
    article_id: int,
    job_id: int,
    blog: Blog,
    slug: str,
    title: str,
    hero_url: str,
    source_article_id: int | None = None,
) -> Article:
    job = Job(id=job_id, blog_id=blog.id, keyword_snapshot=title)
    db.add(job)
    db.flush()
    article = Article(
        id=article_id,
        job_id=job.id,
        blog_id=blog.id,
        title=title,
        meta_description="desc",
        labels=["Travel", "Guide"],
        slug=slug,
        excerpt="excerpt",
        html_article="<p>body</p>",
        faq_section=[],
        image_collage_prompt="prompt",
        editorial_category_key="travel",
        travel_sync_source_article_id=source_article_id,
        render_metadata={},
    )
    db.add(article)
    db.flush()
    db.add(
        Image(
            job_id=job.id,
            article_id=article.id,
            prompt="prompt",
            file_path=f"D:/tmp/{slug}.webp",
            public_url=hero_url,
            width=1024,
            height=1024,
            provider="mock",
            image_metadata={},
        )
    )
    db.commit()
    db.refresh(article)
    return article


def test_build_travel_sync_groups_uses_hero_url_and_reports_missing_languages(db: Session) -> None:
    en_blog = _create_blog(db, blog_id=34, slug="travel-en", language="en")
    es_blog = _create_blog(db, blog_id=36, slug="travel-es", language="es")
    ja_blog = _create_blog(db, blog_id=37, slug="travel-ja", language="ja")
    _create_article(
        db,
        article_id=101,
        job_id=201,
        blog=en_blog,
        slug="busan-night-guide",
        title="Busan Night Guide",
        hero_url="https://api.dongriarchive.com/assets/travel-blogger/travel/busan-night-guide.webp",
    )
    _create_article(
        db,
        article_id=102,
        job_id=202,
        blog=es_blog,
        slug="guia-nocturna-busan",
        title="Guia Nocturna de Busan",
        hero_url="https://api.dongriarchive.com/assets/travel-blogger/travel/busan-night-guide.webp",
    )
    _create_article(
        db,
        article_id=103,
        job_id=203,
        blog=ja_blog,
        slug="jeju-night-market-guide",
        title="済州ナイトマーケットガイド",
        hero_url="https://api.dongriarchive.com/assets/travel-blogger/food/jeju-night-market-guide.webp",
    )

    groups, backlog, summary = build_travel_sync_groups(db)

    assert summary["article_count"] == 3
    assert summary["group_count"] >= 2
    assert any(item.target_language == "ja" for item in backlog)
    assert any(item.target_language == "en" for item in backlog)
    assert any(item.target_language == "es" for item in backlog)
    assert any(group.hero_url.endswith("busan-night-guide.webp") for group in groups)


def test_assign_backlog_schedule_slots_respects_min_gap(db: Session) -> None:
    backlog = [
        TravelSyncBacklogItem(
            group_key="travel-sync-a",
            source_article_id=1,
            source_blog_id=34,
            source_language="en",
            source_slug="a",
            source_title="A",
            source_hero_url="https://api.dongriarchive.com/assets/travel-blogger/travel/a.webp",
            category_key="travel",
            target_language="es",
            target_blog_id=36,
        ),
        TravelSyncBacklogItem(
            group_key="travel-sync-b",
            source_article_id=2,
            source_blog_id=34,
            source_language="en",
            source_slug="b",
            source_title="B",
            source_hero_url="https://api.dongriarchive.com/assets/travel-blogger/travel/b.webp",
            category_key="travel",
            target_language="es",
            target_blog_id=36,
        ),
    ]

    assigned = assign_backlog_schedule_slots(db, backlog=backlog, min_schedule_gap_minutes=10)
    assert assigned[0].scheduled_for is not None
    assert assigned[1].scheduled_for is not None
    assert (assigned[1].scheduled_for - assigned[0].scheduled_for).total_seconds() >= 600


def test_enqueue_travel_cross_sync_jobs_creates_job_with_route_payload(db: Session) -> None:
    en_blog = _create_blog(db, blog_id=34, slug="travel-en", language="en")
    _create_blog(db, blog_id=36, slug="travel-es", language="es")
    source = _create_article(
        db,
        article_id=201,
        job_id=301,
        blog=en_blog,
        slug="busan-hidden-cafe-guide",
        title="Busan Hidden Cafe Guide",
        hero_url="https://api.dongriarchive.com/assets/travel-blogger/food/busan-hidden-cafe-guide.webp",
    )
    backlog = [
        TravelSyncBacklogItem(
            group_key="travel-sync-group-1",
            source_article_id=source.id,
            source_blog_id=34,
            source_language="en",
            source_slug=source.slug,
            source_title=source.title,
            source_hero_url="https://api.dongriarchive.com/assets/travel-blogger/food/busan-hidden-cafe-guide.webp",
            category_key="food",
            target_language="es",
            target_blog_id=36,
            scheduled_for=datetime(2026, 4, 20, 1, 0, tzinfo=UTC),
        )
    ]

    result = enqueue_travel_cross_sync_jobs(
        db,
        backlog=backlog,
        text_generation_route="gemini_cli",
        publish_mode="scheduled",
        max_items_per_run=10,
        retry_failed_only=False,
    )

    assert result["created_count"] == 1
    created = result["created"][0]
    job = db.execute(select(Job).where(Job.id == int(created["job_id"]))).scalar_one()
    assert isinstance(job.raw_prompts, dict)
    assert job.raw_prompts["travel_sync"]["group_key"] == "travel-sync-group-1"
    assert job.raw_prompts["travel_sync"]["text_generation_route"] == "gemini_cli"
    assert "pipeline_schedule" in job.raw_prompts
    assert "planner_brief" in job.raw_prompts
    topic = db.execute(select(Topic).where(Topic.id == int(created["topic_id"]))).scalar_one()
    assert topic.blog_id == 36


def test_build_missing_target_daily_quota_map_uses_largest_remainder() -> None:
    quotas = build_missing_target_daily_quota_map(
        missing_targets={"en": 23, "es": 148, "ja": 146},
        days=7,
    )

    assert quotas["en"] == [4, 4, 3, 3, 3, 3, 3]
    assert quotas["es"] == [22, 21, 21, 21, 21, 21, 21]
    assert quotas["ja"] == [21, 21, 21, 21, 21, 21, 20]


def test_seed_travel_weekly_planner_slots_assigns_backlog_and_keeps_non_travel_scope(db: Session) -> None:
    _create_blog(db, blog_id=34, slug="travel-en", language="en")
    _create_blog(db, blog_id=36, slug="travel-es", language="es")
    _create_blog(db, blog_id=37, slug="travel-ja", language="ja")

    start = date(2026, 4, 20)
    other_day = ContentPlanDay(
        channel_id="blogger:1",
        blog_id=None,
        plan_date=start,
        target_post_count=1,
        status="planned",
    )
    db.add(other_day)
    db.flush()
    db.add(
        ContentPlanSlot(
            plan_day_id=int(other_day.id),
            scheduled_for=datetime(2026, 4, 20, 0, 0, tzinfo=UTC),
            slot_order=1,
            status="brief_ready",
            result_payload={},
        )
    )
    db.commit()

    backlog: list[TravelSyncBacklogItem] = []
    seq = 0
    for language, total in (("en", 3), ("es", 5), ("ja", 4)):
        target_blog_id = {"en": 34, "es": 36, "ja": 37}[language]
        for index in range(total):
            seq += 1
            backlog.append(
                TravelSyncBacklogItem(
                    group_key=f"g-{language}-{index}",
                    source_article_id=seq,
                    source_blog_id=34,
                    source_language="en",
                    source_slug=f"s-{seq}",
                    source_title=f"title-{seq}",
                    source_hero_url=f"https://api.dongriarchive.com/assets/travel-blogger/travel/s-{seq}.webp",
                    category_key="travel",
                    target_language=language,
                    target_blog_id=target_blog_id,
                )
            )

    assigned, summary = seed_travel_weekly_planner_slots(
        db,
        backlog=backlog,
        days=2,
        slot_seed_mode="append",
        slot_gap_minutes=10,
        slot_start_times_by_language={"en": "11:00", "es": "13:00", "ja": "15:00"},
        start_date=start,
        commit=True,
    )

    assert len(assigned) == len(backlog)
    assert summary["daily_quota"]["en"] == [2, 1]
    assert summary["daily_quota"]["es"] == [3, 2]
    assert summary["daily_quota"]["ja"] == [2, 2]
    assert int(summary["created_slot_count"]) == len(backlog)

    second_day = date.fromordinal(start.toordinal() + 1)
    travel_days = db.execute(
        select(ContentPlanDay)
        .where(ContentPlanDay.channel_id.in_(("blogger:34", "blogger:36", "blogger:37")))
        .where(ContentPlanDay.plan_date.in_((start, second_day)))
    ).scalars().all()
    assert travel_days
    travel_slot_count = int(
        db.execute(
            select(func.count(ContentPlanSlot.id))
            .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
            .where(ContentPlanDay.channel_id.in_(("blogger:34", "blogger:36", "blogger:37")))
            .where(ContentPlanDay.plan_date.in_((start, second_day)))
        ).scalar_one()
        or 0
    )
    assert travel_slot_count >= len(backlog)

    untouched_count = db.execute(
        select(ContentPlanSlot).join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id).where(
            ContentPlanDay.channel_id == "blogger:1"
        )
    ).scalars().all()
    assert len(untouched_count) == 1
