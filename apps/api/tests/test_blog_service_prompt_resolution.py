from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.entities import Blog, PublishMode
from app.services import blog_service


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    prompt_root = tmp_path / "prompts"
    monkeypatch.setattr(blog_service, "_prompt_roots", lambda: (prompt_root,))
    blog_service._blogger_prompt_folder_map.cache_clear()

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        blog_service._blogger_prompt_folder_map.cache_clear()


def _seed_blog(
    db: Session,
    *,
    blog_id: int,
    slug: str,
    name: str,
    profile_key: str = "korea_travel",
    blogger_blog_id: str | None = None,
    is_active: bool = True,
) -> Blog:
    blog = Blog(
        id=blog_id,
        name=name,
        slug=slug,
        content_category="custom",
        primary_language="ko",
        profile_key=profile_key,
        publish_mode=PublishMode.DRAFT,
        is_active=is_active,
        blogger_blog_id=blogger_blog_id,
        blogger_url=f"https://example.com/{slug}",
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def test_prompt_path_uses_channel_json_mapping_for_blogger_blog(db: Session, tmp_path: Path) -> None:
    prompts_root = tmp_path / "prompts" / "channels" / "blogger" / "donggri-ri-han-fu-fu-nohan-guo-rokaruan-nei"
    prompts_root.mkdir(parents=True, exist_ok=True)
    (prompts_root / "channel.json").write_text(
        json.dumps({"channel_id": "blogger:37"}, ensure_ascii=False),
        encoding="utf-8",
    )
    expected = prompts_root / "travel_topic_discovery.md"
    expected.write_text("mapped prompt", encoding="utf-8")

    blog = _seed_blog(
        db,
        blog_id=37,
        slug="donggri",
        name="Donggri｜日韓夫婦の韓国ローカル案内",
        blogger_blog_id="remote-37",
    )

    resolved = blog_service._prompt_path("travel_topic_discovery.md", blog=blog)

    assert resolved == expected


def test_ensure_all_blog_workflows_skips_inactive_demo_and_warn_skips_missing_prompt(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_blog(
        db,
        blog_id=1,
        slug="korea-travel-and-events",
        name="Korea Travel & Events",
        blogger_blog_id=None,
        is_active=False,
    )
    active_a = _seed_blog(db, blog_id=34, slug="travel", name="Travel", blogger_blog_id="remote-34")
    active_b = _seed_blog(db, blog_id=35, slug="mystery", name="Mystery", blogger_blog_id="remote-35")

    attempted: list[int] = []

    def fake_ensure(_db: Session, blog: Blog) -> None:
        attempted.append(blog.id)
        if blog.id == active_a.id:
            raise FileNotFoundError("missing prompt")

    monkeypatch.setattr(blog_service, "ensure_blog_workflow_steps", fake_ensure)

    blog_service.ensure_all_blog_workflows(db)

    assert attempted == [active_a.id, active_b.id]
