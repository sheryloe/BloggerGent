from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Blog, BlogAgentConfig, PublishMode, WorkflowStageType
from app.schemas.api import PromptFlowStepUpdate
from app.services import channel_prompt_service
from app.services.platform_service import ensure_managed_channels
from app.services.settings_service import get_settings_map


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")
    monkeypatch.setattr(channel_prompt_service, "_prompt_root", lambda: tmp_path / "prompts")
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)

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


def _create_blog(
    db: Session,
    *,
    blog_id: int,
    slug: str,
    name: str,
    profile_key: str = "custom",
    content_category: str = "custom",
) -> Blog:
    blog = Blog(
        id=blog_id,
        name=name,
        slug=slug,
        content_category=content_category,
        primary_language="ko",
        profile_key=profile_key,
        publish_mode=PublishMode.DRAFT,
        is_active=True,
        blogger_blog_id=f"remote-{blog_id}",
        blogger_url=f"https://{slug}.example.com",
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def _create_step(
    db: Session,
    *,
    blog_id: int,
    agent_key: str,
    stage_type: WorkflowStageType,
    prompt_template: str,
    sort_order: int,
    is_required: bool = False,
) -> None:
    db.add(
        BlogAgentConfig(
            blog_id=blog_id,
            agent_key=agent_key,
            stage_type=stage_type,
            name=agent_key.replace("_", " ").title(),
            role_name=f"{agent_key}-agent",
            objective=f"{agent_key} objective",
            prompt_template=prompt_template,
            provider_hint="codex_cli",
            provider_model="gpt-5",
            is_enabled=True,
            is_required=is_required,
            sort_order=sort_order,
        )
    )
    db.commit()


def test_build_prompt_flow_syncs_blogger_backups(db: Session, tmp_path: Path) -> None:
    blog = _create_blog(db, blog_id=101, slug="hidden-korea", name="Hidden Korea")
    _create_step(
        db,
        blog_id=blog.id,
        agent_key="topic_discovery",
        stage_type=WorkflowStageType.TOPIC_DISCOVERY,
        prompt_template="Find strong topics",
        sort_order=10,
        is_required=True,
    )
    _create_step(
        db,
        blog_id=blog.id,
        agent_key="article_generation",
        stage_type=WorkflowStageType.ARTICLE_GENERATION,
        prompt_template="Write the article",
        sort_order=20,
        is_required=True,
    )

    flow = channel_prompt_service.build_prompt_flow(db, f"blogger:{blog.id}", sync_backup=True)

    assert flow.backup_directory == "channels/blogger/hidden-korea"
    assert flow.steps[0].backup_relative_path == "channels/blogger/hidden-korea/topic_discovery.md"
    assert flow.steps[0].backup_exists is True
    assert (tmp_path / "prompts" / "channels" / "blogger" / "hidden-korea" / "channel.json").exists()
    assert (
        tmp_path / "prompts" / "channels" / "blogger" / "hidden-korea" / "article_generation.md"
    ).read_text(encoding="utf-8") == "Write the article\n"


def test_save_platform_prompt_step_persists_and_syncs_backup(db: Session, tmp_path: Path) -> None:
    ensure_managed_channels(db)

    initial_flow = channel_prompt_service.build_prompt_flow(db, "youtube:main", sync_backup=True)
    initial_step = initial_flow.steps[0]
    assert initial_step.prompt_enabled is True
    assert initial_step.backup_relative_path == "channels/youtube/youtube-studio/video_metadata_generation.md"

    channel_prompt_service.save_platform_prompt_step(
        db,
        channel_id="youtube:main",
        step_id=initial_step.id,
        payload=PromptFlowStepUpdate(
            name="Metadata Writer",
            objective="Generate title, description, tags, and chapter output",
            prompt_template="Create a sharp metadata package",
            provider_model="gpt-5-mini",
            is_enabled=False,
        ),
    )
    updated_flow = channel_prompt_service.build_prompt_flow(db, "youtube:main", sync_backup=True)
    updated_step = updated_flow.steps[0]

    assert updated_step.name == "Metadata Writer"
    assert updated_step.objective == "Generate title, description, tags, and chapter output"
    assert updated_step.prompt_template == "Create a sharp metadata package\n"
    assert updated_step.provider_model == "gpt-5-mini"
    assert updated_step.is_enabled is False
    assert (
        tmp_path / "prompts" / "channels" / "youtube" / "youtube-studio" / "video_metadata_generation.md"
    ).read_text(encoding="utf-8") == "Create a sharp metadata package\n"


def test_sync_all_channel_prompt_backups_includes_disconnected_platform_channels(db: Session, tmp_path: Path) -> None:
    _create_blog(db, blog_id=202, slug="midnight-archives", name="Midnight Archives")
    _create_step(
        db,
        blog_id=202,
        agent_key="topic_discovery",
        stage_type=WorkflowStageType.TOPIC_DISCOVERY,
        prompt_template="Prompt A",
        sort_order=10,
        is_required=True,
    )
    ensure_managed_channels(db)

    flows = channel_prompt_service.sync_all_channel_prompt_backups(db, include_disconnected=True)
    channel_ids = {flow.channel_id for flow in flows}

    assert "blogger:202" in channel_ids
    assert "youtube:main" in channel_ids
    assert "instagram:main" in channel_ids
    assert (tmp_path / "prompts" / "channels" / "instagram" / "instagram-studio" / "channel.json").exists()


def test_build_prompt_flow_syncs_cloudflare_backups_to_channel_name_dir(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        channel_prompt_service,
        "get_cloudflare_overview",
        lambda _db: {"channel_name": "Dongri Archive", "site_title": "Dongri Archive"},
    )
    monkeypatch.setattr(
        channel_prompt_service,
        "get_cloudflare_prompt_bundle",
        lambda _db: {
            "stages": ["topic_discovery"],
            "categories": [{"slug": "mystery", "name": "Mystery"}],
            "templates": [
                {
                    "id": "mystery-topic",
                    "categorySlug": "mystery",
                    "categoryName": "Mystery",
                    "stage": "topic_discovery",
                    "name": "Mystery Topic Agent",
                    "objective": "Find mystery topics",
                    "content": "Investigate unexplained stories",
                    "providerModel": "gpt-5",
                    "isEnabled": True,
                }
            ],
        },
    )

    flow = channel_prompt_service.build_prompt_flow(db, "cloudflare:dongriarchive", sync_backup=True)

    assert flow.backup_directory == "channels/cloudflare/dongri-archive"
    assert [step.stage_type for step in flow.steps] == [
        "topic_discovery",
        "article_generation",
        "image_prompt_generation",
        "related_posts",
        "image_generation",
        "html_assembly",
        "publishing",
    ]
    assert flow.steps[0].backup_relative_path == "channels/cloudflare/dongri-archive/mystery/topic_discovery.md"
    assert (
        tmp_path / "prompts" / "channels" / "cloudflare" / "dongri-archive" / "mystery" / "topic_discovery.md"
    ).read_text(encoding="utf-8") == "Investigate unexplained stories\n"
    assert (
        tmp_path / "prompts" / "channels" / "cloudflare" / "dongri-archive" / "mystery" / "article_generation.md"
    ).exists()
    assert (
        tmp_path / "prompts" / "channels" / "cloudflare" / "dongri-archive" / "mystery" / "image_prompt_generation.md"
    ).exists()
    assert (
        tmp_path / "prompts" / "channels" / "cloudflare" / "dongri-archive" / "mystery" / "publishing.md"
    ).read_text(encoding="utf-8").startswith("[Cloudflare System Step Backup]\n")


def test_travel_blogger_backup_includes_profile_prompt_files_and_inline_prompt(db: Session, tmp_path: Path) -> None:
    (tmp_path / "prompts" / "travel_inline_collage_prompt.md").write_text("Inline travel prompt\n", encoding="utf-8")

    blog = _create_blog(
        db,
        blog_id=303,
        slug="travel-korea",
        name="Travel Korea",
        profile_key="korea_travel",
        content_category="travel",
    )
    _create_step(
        db,
        blog_id=blog.id,
        agent_key="topic_discovery",
        stage_type=WorkflowStageType.TOPIC_DISCOVERY,
        prompt_template="Travel topic prompt",
        sort_order=10,
        is_required=True,
    )
    _create_step(
        db,
        blog_id=blog.id,
        agent_key="article_generation",
        stage_type=WorkflowStageType.ARTICLE_GENERATION,
        prompt_template="Travel article prompt",
        sort_order=20,
        is_required=True,
    )
    _create_step(
        db,
        blog_id=blog.id,
        agent_key="image_prompt_generation",
        stage_type=WorkflowStageType.IMAGE_PROMPT_GENERATION,
        prompt_template="Travel collage prompt",
        sort_order=30,
        is_required=False,
    )

    flow = channel_prompt_service.build_prompt_flow(db, f"blogger:{blog.id}", sync_backup=True)

    assert flow.steps[0].backup_relative_path == "channels/blogger/travel-korea/travel_topic_discovery.md"
    assert (
        tmp_path / "prompts" / "channels" / "blogger" / "travel-korea" / "travel_article_generation.md"
    ).read_text(encoding="utf-8") == "Travel article prompt\n"
    assert (
        tmp_path / "prompts" / "channels" / "blogger" / "travel-korea" / "travel_collage_prompt.md"
    ).read_text(encoding="utf-8") == "Travel collage prompt\n"
    assert (
        tmp_path / "prompts" / "channels" / "blogger" / "travel-korea" / "travel_inline_collage_prompt.md"
    ).read_text(encoding="utf-8") == "Inline travel prompt\n"
