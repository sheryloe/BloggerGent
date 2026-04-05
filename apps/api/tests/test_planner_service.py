from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Blog, BlogTheme, ContentItem, ContentPlanDay, ContentPlanSlot, PublicationRecord, PublishMode, WorkflowStageType
from app.services import planner_service
from app.services.blog_service import ensure_blog_workflow_steps, get_workflow_step, stage_supports_prompt
from app.services.platform_service import ensure_managed_channels
from app.services.settings_service import get_settings_map, upsert_settings


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    get_settings_map(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_blog(db: Session, *, blog_id: int, name: str, slug: str, profile_key: str) -> Blog:
    blog = Blog(
        id=blog_id,
        name=name,
        slug=slug,
        content_category="custom",
        primary_language="ko",
        profile_key=profile_key,
        publish_mode=PublishMode.DRAFT,
        is_active=True,
        blogger_blog_id=f"remote-{blog_id}",
        blogger_url=f"https://example.com/{slug}",
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def test_blogger_travel_categories_follow_editorial_weights(db: Session) -> None:
    blog = _seed_blog(db, blog_id=34, name="Travel", slug="travel", profile_key="korea_travel")
    upsert_settings(db, {"travel_editorial_weights": "Travel:50,Culture:30,Food:20"})

    categories = planner_service.list_categories(db, channel_id=f"blogger:{blog.id}")

    assert [item.key for item in categories] == ["travel", "culture", "food"]
    assert [item.weight for item in categories] == [50, 30, 20]


def test_blogger_mystery_categories_use_real_profile(db: Session) -> None:
    blog = _seed_blog(db, blog_id=35, name="Mystery", slug="mystery", profile_key="world_mystery")

    categories = planner_service.list_categories(db, channel_id=f"blogger:{blog.id}")

    assert [item.key for item in categories] == ["case-files", "mystery-archives", "legends-lore"]


def test_cloudflare_categories_use_leaf_category_weights(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner_service, "get_cloudflare_overview", lambda _db: {"channel_id": "dongriarchive", "channel_name": "Dongri Archive"})
    monkeypatch.setattr(
        planner_service,
        "list_cloudflare_categories",
        lambda _db: [
            {"id": "travel", "slug": "여행과-기록", "name": "여행과 기록", "isLeaf": True},
            {"id": "culture", "slug": "문화와-공간", "name": "문화와 공간", "isLeaf": True},
            {"id": "root", "slug": "root", "name": "Root", "isLeaf": False},
        ],
    )

    categories = planner_service.list_categories(db, channel_id="cloudflare:dongriarchive")

    assert [item.key for item in categories] == ["여행과-기록", "문화와-공간"]
    assert [item.weight for item in categories] == [10, 12]


def test_month_plan_accepts_legacy_blog_id_alias(db: Session) -> None:
    blog = _seed_blog(db, blog_id=34, name="Travel", slug="travel", profile_key="korea_travel")

    calendar = planner_service.create_month_plan(db, channel_id=None, blog_id=blog.id, month="2026-04", overwrite=True)

    assert calendar.channel_id == f"blogger:{blog.id}"
    assert calendar.blog_id == blog.id
    assert calendar.days


def test_get_calendar_normalizes_legacy_theme_slots(db: Session) -> None:
    blog = _seed_blog(db, blog_id=34, name="Travel", slug="travel", profile_key="korea_travel")
    legacy_theme = BlogTheme(
        blog_id=blog.id,
        key="insight",
        name="Insight",
        weight=100,
        color="#2563eb",
        sort_order=1,
        is_active=True,
    )
    db.add(legacy_theme)
    db.flush()

    plan_day = ContentPlanDay(
        channel_id=f"blogger:{blog.id}",
        blog_id=blog.id,
        plan_date=date(2026, 4, 1),
        target_post_count=1,
        status="planned",
    )
    db.add(plan_day)
    db.flush()

    db.add(
        ContentPlanSlot(
            plan_day_id=plan_day.id,
            theme_id=legacy_theme.id,
            category_key="insight",
            category_name="Insight",
            category_color="#2563eb",
            scheduled_for=datetime(2026, 4, 1, 9, 0, 0),
            slot_order=1,
            status="planned",
            result_payload={},
        )
    )
    db.commit()

    calendar = planner_service.get_calendar(db, channel_id=f"blogger:{blog.id}", month="2026-04")

    assert calendar.days[0].slots[0].category_key == "travel"
    assert calendar.days[0].slots[0].category_name == "Travel"


def test_slot_create_update_and_generate_use_category_key(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _seed_blog(db, blog_id=34, name="Travel", slug="travel", profile_key="korea_travel")
    calendar = planner_service.create_month_plan(db, channel_id=f"blogger:{blog.id}", blog_id=None, month="2026-04", overwrite=True)
    plan_day = calendar.days[0]

    created = planner_service.create_slot(
        db,
        planner_service.PlannerSlotCreate(
            plan_day_id=plan_day.id,
            category_key="culture",
            scheduled_for=f"{plan_day.plan_date}T10:00:00",
            brief_topic="서울 전시 일정",
            brief_audience="주말에 볼거리를 찾는 독자",
        ),
    )
    assert created.category_key == "culture"

    updated = planner_service.update_slot(
        db,
        created.id,
        planner_service.PlannerSlotUpdate(category_key="food", brief_topic="성수 브런치 추천"),
    )
    assert updated.category_key == "food"

    monkeypatch.setattr(planner_service, "create_job", lambda *args, **kwargs: SimpleNamespace(id=99))
    monkeypatch.setattr(planner_service.run_job, "delay", lambda *_args: None)

    generated = planner_service.run_slot_generation(db, updated.id)

    assert generated.job_id == 99
    assert generated.category_key == "food"
    assert generated.status == "queued"


def test_publishing_stage_stays_non_prompt() -> None:
    assert stage_supports_prompt(WorkflowStageType.PUBLISHING) is False


def test_run_slot_generation_routes_youtube_to_workspace_queue(db: Session) -> None:
    ensure_managed_channels(db)
    plan_day = ContentPlanDay(
        channel_id="youtube:main",
        blog_id=None,
        plan_date=date(2026, 4, 2),
        target_post_count=1,
        status="planned",
    )
    db.add(plan_day)
    db.flush()
    slot = ContentPlanSlot(
        plan_day_id=plan_day.id,
        category_key="long-form",
        category_name="Long-form",
        scheduled_for=datetime(2026, 4, 2, 12, 0, 0),
        slot_order=1,
        status="brief_ready",
        brief_topic="AI workflow automation",
        brief_audience="solo operator",
        result_payload={},
    )
    db.add(slot)
    db.commit()

    generated = planner_service.run_slot_generation(db, slot.id)
    assert generated.status == "generated"
    assert generated.result_status == "blocked_asset"
    refreshed_slot = db.query(ContentPlanSlot).filter(ContentPlanSlot.id == slot.id).one()
    content_item_id = int(refreshed_slot.result_payload["content_item_id"])

    content_item = db.get(ContentItem, content_item_id)
    assert content_item is not None
    assert content_item.content_type == "youtube_video"
    assert content_item.lifecycle_status == "blocked_asset"
    assert content_item.blocked_reason == "missing_video_file_path"

    publication = (
        db.query(PublicationRecord)
        .filter(PublicationRecord.content_item_id == content_item_id)
        .order_by(PublicationRecord.id.desc())
        .first()
    )
    assert publication is None


def test_run_slot_generation_routes_instagram_reel_to_workspace_queue(db: Session) -> None:
    ensure_managed_channels(db)
    plan_day = ContentPlanDay(
        channel_id="instagram:main",
        blog_id=None,
        plan_date=date(2026, 4, 3),
        target_post_count=1,
        status="planned",
    )
    db.add(plan_day)
    db.flush()
    slot = ContentPlanSlot(
        plan_day_id=plan_day.id,
        category_key="reel",
        category_name="Reels",
        scheduled_for=datetime(2026, 4, 3, 15, 0, 0),
        slot_order=1,
        status="brief_ready",
        brief_topic="short-form teaser",
        brief_audience="social followers",
        result_payload={},
    )
    db.add(slot)
    db.commit()

    generated = planner_service.run_slot_generation(db, slot.id)
    assert generated.status == "generated"
    assert generated.result_status == "blocked_asset"
    refreshed_slot = db.query(ContentPlanSlot).filter(ContentPlanSlot.id == slot.id).one()
    content_item_id = int(refreshed_slot.result_payload["content_item_id"])

    content_item = db.get(ContentItem, content_item_id)
    assert content_item is not None
    assert content_item.content_type == "instagram_reel"
    assert content_item.lifecycle_status == "blocked_asset"
    assert content_item.blocked_reason == "missing_instagram_video_url"


def test_multilingual_slot_generation_disables_topic_discovery_and_sets_bundle_payload(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blog = _seed_blog(
        db,
        blog_id=90,
        name="Donggri Kankoku",
        slug="donggri-kankoku",
        profile_key="korea_travel",
    )
    blog.blogger_url = "https://donggri-kankoku.blogspot.com/"
    db.add(blog)
    db.commit()
    db.refresh(blog)
    blog = ensure_blog_workflow_steps(db, blog)

    plan_day = ContentPlanDay(
        channel_id=f"blogger:{blog.id}",
        blog_id=blog.id,
        plan_date=date(2026, 4, 8),
        target_post_count=1,
        status="planned",
    )
    db.add(plan_day)
    db.flush()
    slot = ContentPlanSlot(
        plan_day_id=plan_day.id,
        category_key="travel",
        category_name="Travel",
        scheduled_for=datetime(2026, 4, 8, 9, 12, 0),
        slot_order=1,
        status="brief_ready",
        brief_topic="Jeju coastal evening route guide",
        brief_audience="",
        brief_extra_context="bundle_key: jeju-evening-route-2026-04-08\nfacts: shuttle from city hall",
        result_payload={},
    )
    db.add(slot)
    db.commit()

    captured: dict[str, object] = {}

    def _fake_create_job(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=777)

    monkeypatch.setattr(planner_service, "create_job", _fake_create_job)
    monkeypatch.setattr(planner_service.run_job, "delay", lambda *_args: None)

    generated = planner_service.run_slot_generation(db, slot.id)

    refreshed_blog = db.get(Blog, blog.id)
    refreshed_slot = db.get(ContentPlanSlot, slot.id)
    topic_step = get_workflow_step(refreshed_blog, WorkflowStageType.TOPIC_DISCOVERY)
    article_step = get_workflow_step(refreshed_blog, WorkflowStageType.ARTICLE_GENERATION)
    image_prompt_step = get_workflow_step(refreshed_blog, WorkflowStageType.IMAGE_PROMPT_GENERATION)
    publishing_step = get_workflow_step(refreshed_blog, WorkflowStageType.PUBLISHING)

    assert generated.job_id == 777
    assert topic_step is not None and topic_step.is_enabled is False
    assert article_step is not None and article_step.is_enabled is True
    assert image_prompt_step is not None and image_prompt_step.is_enabled is True
    assert publishing_step is not None and publishing_step.is_enabled is True
    assert refreshed_slot is not None
    assert refreshed_slot.scheduled_for is not None
    assert refreshed_slot.scheduled_for.minute == 30
    assert captured["raw_prompts"]["planner_brief"]["bundle_key"] == "jeju-evening-route-2026-04-08"
    assert captured["raw_prompts"]["planner_brief"]["language"] == "ja"
    assert captured["raw_prompts"]["planner_brief"]["facts"] == ["shuttle from city hall"]
