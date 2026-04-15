from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from app.db.base import Base
from app.models.entities import ManagedChannel, SyncedCloudflarePost
from refactoring.codex_write.service import cloudflare_codex_write_service


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _create_channel_with_post(db: Session, *, category_slug: str, slug: str) -> SyncedCloudflarePost:
    channel = ManagedChannel(
        provider="cloudflare",
        channel_id="cloudflare:dongriarchive",
        display_name="Dongri Archive",
        status="active",
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)

    row = SyncedCloudflarePost(
        managed_channel_id=channel.id,
        remote_post_id="remote-1",
        slug=slug,
        title="원본 제목",
        url=f"https://dongriarchive.com/ko/post/{slug}",
        status="published",
        category_slug=category_slug,
        canonical_category_slug=category_slug,
        category_name=category_slug,
        canonical_category_name=category_slug,
        excerpt_text="원본 요약",
        thumbnail_url="https://img.example.com/cover.webp",
        labels=["태그1"],
        render_metadata={"chartSymbol": "TEST"},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_export_codex_write_packages_writes_seed_json_under_upper_category_path(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_channel_with_post(db, category_slug="여행과-기록", slug="gangneung-route")
    monkeypatch.setattr(cloudflare_codex_write_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "_fetch_integration_post_detail",
        lambda _db, remote_post_id: {
            "id": remote_post_id,
            "title": "강릉 사천해변 당일 코스",
            "excerpt": "강릉 해변 동선 요약",
            "seoTitle": "강릉 사천해변 당일 코스",
            "seoDescription": "강릉 사천해변을 하루에 걷는 동선 가이드",
            "publicUrl": "https://dongriarchive.com/ko/post/gangneung-route",
            "coverImage": "https://img.example.com/cover.webp",
            "coverAlt": "강릉 해변 커버",
            "contentMarkdown": "<h2>도입</h2><p>본문</p>![inline](https://img.example.com/inline.webp)",
            "tags": [{"name": "강릉"}, {"name": "해변"}],
        },
    )

    result = cloudflare_codex_write_service.export_codex_write_packages(
        db,
        category_slugs=["여행과-기록"],
        overwrite=True,
        sync_before=True,
        base_dir=tmp_path / "codex_write" / "cloudflare",
    )

    assert result["created_count"] == 1
    package_path = tmp_path / "codex_write" / "cloudflare" / "동그리의 기록" / "yeohaenggwa-girog" / "gangneung-route.json"
    assert package_path.exists()
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    assert payload["prompt_version"] == "0414"
    assert payload["cover_image"]["url"] == "https://img.example.com/cover.webp"
    assert payload["inline_image"]["url"] == "https://img.example.com/inline.webp"
    assert payload["source_prompt_paths"] == [
        "prompts/channels/cloudflare/dongri-archive/동그리의 기록/yeohaenggwa-girog/topic_discovery.md",
        "prompts/channels/cloudflare/dongri-archive/동그리의 기록/yeohaenggwa-girog/article_generation.md",
        "prompts/channels/cloudflare/dongri-archive/동그리의 기록/yeohaenggwa-girog/image_prompt_generation.md",
    ]


def test_publish_codex_write_packages_builds_put_payload_and_updates_state(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_channel_with_post(db, category_slug="개발과-프로그래밍", slug="codex-agent-setup")
    base_dir = tmp_path / "codex_write" / "cloudflare"
    package_dir = base_dir / "동그리의 기록" / "gaebalgwa-peurogeuraeming"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / "codex-agent-setup.json"
    long_body = (
        "<h2>도입</h2><p>"
        + ("코덱스 워크플로를 팀에 붙일 때 판단 기준을 먼저 정한다. " * 50)
        + "</p><h2>비교표</h2><p>"
        + ("도구별 장단점을 비교하고 경계선을 먼저 문서화한다. " * 50)
        + "</p><h2>마무리 기록</h2><p>"
        + ("결국 자동화 범위보다 책임 경계가 먼저다. " * 15)
        + "</p>"
    )
    package_path.write_text(
        json.dumps(
            {
                "remote_post_id": "remote-1",
                "slug": "codex-agent-setup",
                "published_url": "https://dongriarchive.com/ko/post/codex-agent-setup",
                "root_category_name": "동그리의 기록",
                "category_slug": "개발과-프로그래밍",
                "category_name": "개발과-프로그래밍",
                "category_folder": "gaebalgwa-peurogeuraeming",
                "prompt_version": "0414",
                "source_prompt_paths": [],
                "source_post": {},
                "title": "코덱스 에이전트 셋업 2026 | 역할 분리와 검증 루프를 먼저 고정하는 이유",
                "excerpt": "코덱스 에이전트 셋업에서 먼저 정해야 할 역할 분리와 검증 루프를 정리한 글.",
                "meta_description": "코덱스 에이전트 셋업에서 역할 분리와 검증 루프를 먼저 고정하는 실무 기준.",
                "seo_title": "코덱스 에이전트 셋업 2026",
                "html_article": long_body,
                "faq_section": [{"question": "무엇부터 정하나?", "answer": "책임 경계부터 정한다."}],
                "tag_names": ["Codex", "AI 도구"],
                "cover_image": {"url": "https://img.example.com/cover.webp", "alt": "커버"},
                "inline_image": {"url": "https://img.example.com/inline.webp", "alt": "인라인"},
                "render_metadata": {},
                "publish_state": {"status": "seeded", "last_published_at": None, "last_error": None},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "list_cloudflare_categories",
        lambda _db: [{"id": "cat-dev", "slug": "개발과-프로그래밍", "name": "개발과-프로그래밍", "isLeaf": True}],
    )

    def _fake_request(_db, *, method: str, path: str, json_payload: dict[str, object], timeout: float):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = json_payload
        captured["timeout"] = timeout
        return {"data": {"id": "remote-1", "publicUrl": "https://dongriarchive.com/ko/post/codex-agent-setup"}}

    monkeypatch.setattr(cloudflare_codex_write_service, "_integration_request", _fake_request)
    monkeypatch.setattr(cloudflare_codex_write_service, "_integration_data_or_raise", lambda payload: payload["data"])
    monkeypatch.setattr(cloudflare_codex_write_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: {"status": "ok"})

    result = cloudflare_codex_write_service.publish_codex_write_packages(
        db,
        category_slugs=["개발과-프로그래밍"],
        dry_run=False,
        sync_after=True,
        base_dir=base_dir,
    )

    assert result["updated_count"] == 1
    assert captured["method"] == "PUT"
    assert captured["path"] == "/api/integrations/posts/remote-1"
    update_payload = captured["payload"]
    assert update_payload["categoryId"] == "cat-dev"
    assert update_payload["coverImage"] == "https://img.example.com/cover.webp"
    assert update_payload["coverAlt"] == "커버"
    assert "https://img.example.com/inline.webp" in update_payload["content"]

    updated_package = json.loads(package_path.read_text(encoding="utf-8"))
    assert updated_package["publish_state"]["status"] == "published"
    assert updated_package["publish_state"]["last_error"] is None
