from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from app.db.base import Base
from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.cloudflare import cloudflare_codex_write_service


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


@pytest.fixture(autouse=True)
def _stub_asset_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "_resolve_reachable_asset_url",
        lambda url, public_base_url="": str(url or "").strip(),
    )


def _create_post(db: Session, *, category_slug: str, slug: str, remote_post_id: str = "remote-1") -> None:
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
        remote_post_id=remote_post_id,
        slug=slug,
        title="기존 제목",
        url=f"https://dongriarchive.com/ko/post/{slug}",
        status="published",
        category_slug=category_slug,
        canonical_category_slug=category_slug,
        category_name=category_slug,
        canonical_category_name=category_slug,
        excerpt_text="기존 요약",
        thumbnail_url="https://assets.example.com/current-cover.webp",
        labels=["태그"],
        render_metadata={},
    )
    db.add(row)
    db.commit()


def _content_body(topic: str, inline_url: str) -> str:
    return (
        f"# {topic} 2026 | 공개 구조 검증용 본문\n\n"
        f"<section><p>{topic} 공개 구조를 검증하기 위한 테스트 본문이다. "
        + ("리드 문단, HTML 표, 인라인 이미지, FAQ, 마무리 기록이 한 계약 안에 모두 들어가야 한다. " * 20)
        + "</p></section>\n\n"
        + "<h2>중복 차단 기준</h2>\n"
        + "<p>"
        + ("같은 이미지를 반복 사용하면 공개 페이지의 주제 구분이 흐려지고, 자산 검증과 게시 결과가 같이 무너진다. " * 14)
        + "</p>\n\n"
        + "<h2>체크 기준</h2>\n"
        + "<table><thead><tr><th>항목</th><th>판단</th></tr></thead><tbody>"
        + "<tr><td>글 내부</td><td>cover와 inline은 반드시 달라야 한다</td></tr>"
        + "<tr><td>블로그 전체</td><td>이미 다른 공개글에서 쓰는 자산은 다시 쓰지 않는다</td></tr>"
        + "</tbody></table>\n"
        + "<p>"
        + ("이미지 경로와 검증 흐름을 분리해 두면 배치 게시 중간의 실수를 많이 줄일 수 있다. " * 16)
        + "</p>\n\n"
        + f"<p><img src=\"{inline_url}\" alt=\"{topic} 인라인 이미지\" /></p>\n\n"
        + "<h2>자주 묻는 질문</h2>\n"
        + "<h3>왜 글 내부 이미지 중복을 막아야 하나</h3>\n"
        + "<p>cover와 inline이 같으면 글 구조가 단조롭게 보여 가독성과 품질 신호가 함께 무너진다.</p>\n\n"
        + "<h3>왜 블로그 전체 중복도 막아야 하나</h3>\n"
        + "<p>같은 이미지를 여러 글에 올리면 주제 구분이 흐려지고 자산 관리 기준이 무너진다.</p>\n\n"
        + "<h3>백업 JSON URL 복구는 언제 쓰나</h3>\n"
        + "<p>R2 미사용 자산과 로컬 원본이 없을 때 마지막 실용 경로로 쓴다.</p>\n\n"
        + "<h3>복구에 실패하면 어떻게 되나</h3>\n"
        + "<p>manual_review_required로 멈추고 억지 게시를 막는 편이 낫다.</p>\n\n"
        + "<h2>마무리 기록</h2>\n"
        + "<p>이미지 정책의 핵심은 예쁜 장식이 아니라 공개 품질을 지키는 최소 기준을 먼저 세우는 데 있다. 그 기준이 단단해야 본문 구조와 게시 결과도 함께 안정적으로 유지된다.</p>"
    )


def _base_payload(*, category_slug: str, slug: str) -> dict:
    inline_url = "https://assets.example.com/current-inline.webp"
    return {
        "remote_post_id": "remote-1",
        "slug": slug,
        "original_slug": slug,
        "target_slug": slug,
        "published_url": f"https://dongriarchive.com/ko/post/{slug}",
        "root_category_name": "동그리의 기록",
        "category_slug": category_slug,
        "category_name": category_slug,
        "category_folder": "sample",
        "prompt_version": "0414",
        "source_prompt_paths": [],
        "source_post": {
            "title": "기존 제목",
            "excerpt": "기존 요약",
            "content_markdown": "",
            "current_cover_image_url": "https://assets.example.com/current-cover.webp",
            "current_inline_image_urls": ["https://assets.example.com/current-inline.webp"],
        },
        "title": "JetBrains Fleet 도입 판단 2026 | 지금 새로 깔 이유가 있는지 팀 기준으로 따져보기",
        "excerpt": "실제 도입 판단 기준과 검증 흐름을 먼저 정리한다. 기능 소개보다 운영 기준과 실패 지점을 먼저 본다.",
        "meta_description": "JetBrains Fleet 도입 여부를 실제 팀 기준으로 정리한다. 기능 소개보다 검증 흐름, 운영 기준, 실패 지점을 먼저 확인한다.",
        "seo_title": "JetBrains Fleet 도입 판단 2026",
        "content_body": _content_body("JetBrains Fleet 도입 판단", inline_url),
        "html_article": "",
        "faq_section": [],
        "tag_names": ["JetBrains", "Fleet"],
        "cover_image": {
            "url": "https://assets.example.com/current-cover.webp",
            "alt": "커버",
            "source": "current_live",
            "asset_key": "current-cover.webp",
        },
        "inline_image": {
            "url": inline_url,
            "alt": "인라인",
            "source": "current_live",
            "asset_key": "current-inline.webp",
        },
        "image_uniqueness": {
            "cover_hash_or_key": "current-cover.webp",
            "inline_hash_or_key": "current-inline.webp",
            "is_distinct_within_post": True,
            "is_distinct_across_blog": False,
        },
        "backup_image_resolution": {
            "status": "pending",
            "searched_roots": ["backup", "storage", "storage-clone"],
            "candidate_count": 0,
            "cover": {},
            "inline": {},
            "notes": [],
        },
        "render_metadata": {},
        "entity_validation": {
            "status": "verified",
            "entity_type": "tool",
            "display_name": "JetBrains Fleet",
            "evidence_urls": ["https://www.jetbrains.com/fleet/"],
            "evidence_note": "official",
        },
        "layout_template": "single-layout-0415",
        "publish_state": {"status": "seeded", "publish_mode": None, "last_published_at": None, "last_error": None},
    }


def test_publish_blocks_duplicate_images_within_post(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_post(db, category_slug="개발과-프로그래밍", slug="fleet-adoption")
    base_dir = tmp_path / "codex_write" / "cloudflare"
    package_dir = base_dir / "동그리의 기록" / "gaebalgwa-peurogeuraeming"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / "fleet-adoption.json"
    payload = _base_payload(category_slug="개발과-프로그래밍", slug="fleet-adoption")
    payload["cover_image"]["url"] = "https://assets.example.com/same.webp"
    payload["cover_image"]["asset_key"] = "same.webp"
    payload["inline_image"]["url"] = "https://assets.example.com/same.webp"
    payload["inline_image"]["asset_key"] = "same.webp"
    package_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "list_cloudflare_categories",
        lambda _db: [{"id": "cat-dev", "slug": "개발과-프로그래밍", "name": "개발과-프로그래밍", "isLeaf": True}],
    )
    monkeypatch.setattr(cloudflare_codex_write_service, "_build_backup_json_index", lambda _repo_root: [])
    monkeypatch.setattr(cloudflare_codex_write_service, "_build_local_backup_image_index", lambda _repo_root: [])
    monkeypatch.setattr(cloudflare_codex_write_service, "_collect_live_image_inventory", lambda *_args, **_kwargs: {"urls": set(), "asset_keys": set()})

    result = cloudflare_codex_write_service.publish_codex_write_packages(
        db,
        category_slugs=["개발과-프로그래밍"],
        dry_run=False,
        sync_after=False,
        base_dir=base_dir,
    )

    assert result["failed_count"] == 1
    saved = json.loads(package_path.read_text(encoding="utf-8"))
    assert saved["publish_state"]["status"] == "failed"
    assert "duplicate_image_within_post" in saved["publish_state"]["last_error"]
    assert "backup_image_unresolved" in saved["publish_state"]["last_error"]


def test_publish_resolves_backup_json_url_and_uploads_webp(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_post(db, category_slug="여행과-기록", slug="real-route")
    base_dir = tmp_path / "codex_write" / "cloudflare"
    package_dir = base_dir / "동그리의 기록" / "yeohaenggwa-girog"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / "real-route.json"
    payload = _base_payload(category_slug="여행과-기록", slug="real-route")
    payload["title"] = "구례 화엄사 반나절 동선 2026 | 일주문에서 각황전까지 실제로 걷는 순서"
    payload["excerpt"] = "구례 화엄사 반나절 동선을 실제 순서대로 정리한다. 일주문과 각황전을 한 흐름으로 묶어 본다."
    payload["meta_description"] = "구례 화엄사 반나절 동선을 실제 순서대로 정리한다. 일주문에서 각황전까지의 흐름과 휴식 지점을 함께 살핀다."
    payload["content_body"] = _content_body("구례 화엄사 반나절 동선", "https://assets.example.com/current-inline.webp")
    payload["entity_validation"] = {
        "status": "verified",
        "entity_type": "place",
        "display_name": "구례 화엄사",
        "evidence_urls": ["https://map.naver.com/"],
        "evidence_note": "listing",
    }
    payload["cover_image"]["url"] = "https://assets.example.com/dup.webp"
    payload["cover_image"]["asset_key"] = "dup.webp"
    payload["inline_image"]["url"] = "https://assets.example.com/dup.webp"
    payload["inline_image"]["asset_key"] = "dup.webp"
    package_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "list_cloudflare_categories",
        lambda _db: [{"id": "cat-travel", "slug": "여행과-기록", "name": "여행과-기록", "isLeaf": True}],
    )
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "_build_backup_json_index",
        lambda _repo_root: [
            {
                "backup_path": "backup/real-route-after.json",
                "slug": "real-route",
                "title": "구례 화엄사 반나절 동선",
                "cover_url": "https://legacy.example.com/route-cover.png",
                "inline_urls": ["https://legacy.example.com/route-inline.png"],
            }
        ],
    )
    monkeypatch.setattr(cloudflare_codex_write_service, "_build_local_backup_image_index", lambda _repo_root: [])
    monkeypatch.setattr(cloudflare_codex_write_service, "_collect_live_image_inventory", lambda *_args, **_kwargs: {"urls": set(), "asset_keys": set()})
    monkeypatch.setattr(cloudflare_codex_write_service, "_download_binary", lambda _url: b"fake-png-binary")
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "_normalize_binary_for_filename",
        lambda *, content, filename, force_webp=False: content,
    )

    upload_calls: list[str] = []

    def _fake_upload(_db, *, filename: str, content: bytes, object_key=None):
        upload_calls.append(filename)
        resolved_key = str(object_key or f"assets/media/cloudflare/dongri-archive/yeohaenggwa-girog/2026/04/real-route/{Path(filename).stem}.webp")
        return (
            f"https://api.dongriarchive.com/{resolved_key}",
            {"object_key": resolved_key},
            {"cloudflare": {"original_url": f"https://api.dongriarchive.com/{resolved_key}"}},
        )

    monkeypatch.setattr(cloudflare_codex_write_service, "upload_binary_to_cloudflare_r2", _fake_upload)
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "_integration_request",
        lambda _db, *, method, path, json_payload=None, timeout=0, **_kwargs: {
            "data": {"id": "remote-1", "publicUrl": "https://dongriarchive.com/ko/post/real-route", "slug": "real-route"}
        },
    )
    monkeypatch.setattr(cloudflare_codex_write_service, "_integration_data_or_raise", lambda payload: payload["data"])
    monkeypatch.setattr(cloudflare_codex_write_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: {"status": "ok"})

    result = cloudflare_codex_write_service.publish_codex_write_packages(
        db,
        category_slugs=["여행과-기록"],
        dry_run=False,
        sync_after=False,
        base_dir=base_dir,
    )

    assert result["updated_count"] == 1
    assert len(upload_calls) == 2
    saved = json.loads(package_path.read_text(encoding="utf-8"))
    assert saved["cover_image"]["source"] == "backup_json_url"
    assert saved["inline_image"]["source"] == "backup_json_url"
    assert saved["cover_image"]["url"] != saved["inline_image"]["url"]
    assert saved["cover_image"]["asset_key"] != saved["inline_image"]["asset_key"]
    assert saved["backup_image_resolution"]["status"] == "resolved"
    assert saved["image_uniqueness"]["is_distinct_within_post"] is True
    assert saved["image_uniqueness"]["is_distinct_across_blog"] is True
    assert "<img src=\"https://api.dongriarchive.com/assets/media/cloudflare/" in saved["content_body"]
