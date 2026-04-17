from __future__ import annotations

import json
import re
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


def _create_channel_with_post(
    db: Session,
    *,
    category_slug: str,
    slug: str,
    remote_post_id: str = "remote-1",
) -> SyncedCloudflarePost:
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
        thumbnail_url="https://img.example.com/cover.webp",
        labels=["기존태그"],
        render_metadata={"chartSymbol": "TEST"},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _content_body(topic: str, inline_url: str) -> str:
    lead = (
        f"# {topic} 2026 | 실사용 기준으로 정리하는 체크포인트\n\n"
        f"<section><p>{topic}을 실제 공개 글 계약으로 맞추기 위한 테스트 본문이다. "
        + ("리드 섹션 다음에 HTML 섹션, 표, 인라인 이미지, FAQ, 마무리 기록이 순서대로 이어져야 한다. " * 12)
        + "</p></section>\n\n"
    )
    section_1 = (
        "<h2>지금 먼저 볼 기준</h2>\n"
        "<p>"
        + ("한 글 안에서 구조가 무너지지 않으려면 리드 문단 다음에 본문 섹션과 판단 포인트가 자연스럽게 이어져야 한다. " * 10)
        + "</p>\n\n"
    )
    table = (
        "<h2>비교 기준</h2>\n"
        "<table><thead><tr><th>항목</th><th>판단 기준</th></tr></thead><tbody>"
        "<tr><td>진입 시점</td><td>지금 실제 작업에서 반복되는 문제를 줄여 주는가</td></tr>"
        "<tr><td>보류 시점</td><td>검증 체계 없이 기대감만 앞서는가</td></tr>"
        "</tbody></table>\n"
        "<p>"
        + ("표가 한 번 들어간 뒤에도 문단 흐름이 끊기지 않아야 실제 공개 페이지에서 읽는 리듬이 살아난다. " * 10)
        + "</p>\n\n"
    )
    section_2 = (
        "<h2>실제 적용 순서</h2>\n"
        "<p>"
        + ("실제 적용에서는 어디까지 자동화하고 어디에서 사람이 최종 판단을 해야 하는지 선을 긋는 설명이 꼭 포함돼야 한다. " * 11)
        + "</p>\n\n"
    )
    inline_image = f"<p><img src=\"{inline_url}\" alt=\"{topic} 인라인 이미지\" /></p>\n\n"
    faq = (
        "<h2>자주 묻는 질문</h2>\n"
        "<h3>가장 먼저 확인할 것은 무엇인가</h3>\n"
        "<p>현재 반복되는 병목을 먼저 정리해야 도구나 경로 비교가 실제 판단으로 이어진다.</p>\n\n"
        "<h3>바로 유료로 전환해야 하는가</h3>\n"
        "<p>최소 조합으로 먼저 검증하고 실제 절감 시간을 확인한 뒤 고정하는 편이 안전하다.</p>\n\n"
        "<h3>팀에서 공통 기준은 어떻게 잡는가</h3>\n"
        "<p>누가 어떤 장면에서 어떤 도구를 쓰는지 문장으로 정리하면 리뷰 비용이 크게 줄어든다.</p>\n\n"
        "<h3>자동화 범위는 어디까지가 적절한가</h3>\n"
        "<p>초안과 구조 정리까지는 맡기고 최종 판단과 공개 직전 검수는 사람이 직접 잡는 편이 안정적이다.</p>\n\n"
    )
    closing = (
        "<h2>마무리 기록</h2>\n"
        "<p>"
        + ("결국 중요한 것은 보기 좋은 장식이 아니라 실제로 읽히고 유지되는 구조를 만드는 일이며, 그 기준이 분명할수록 다음 수정이 빨라진다. " * 10)
        + "</p>"
    )
    return lead + section_1 + table + section_2 + inline_image + faq + closing


def _package_payload(
    *,
    category_slug: str,
    slug: str,
    target_slug: str | None = None,
    entity_status: str = "verified",
) -> dict:
    inline_url = "https://img.example.com/inline.webp"
    return {
        "remote_post_id": "remote-1",
        "slug": slug,
        "original_slug": slug,
        "target_slug": target_slug or slug,
        "published_url": f"https://dongriarchive.com/ko/post/{slug}",
        "root_category_name": "동그리의 기록",
        "category_slug": category_slug,
        "category_name": category_slug,
        "category_folder": "sample",
        "prompt_version": "0414",
        "source_prompt_paths": [],
        "source_post": {},
        "title": "JetBrains Fleet 도입 판단 2026 | 지금 새로 깔 이유가 있는지 팀 기준으로 따져보기",
        "excerpt": "실제 도입 판단 기준과 검증 흐름을 먼저 정리한다. 기능 소개보다 운영 기준과 실패 지점을 먼저 본다.",
        "meta_description": "JetBrains Fleet 도입 여부를 실제 팀 기준으로 정리한다. 기능 소개보다 검증 흐름, 비교 기준, 실패 지점을 먼저 확인한다.",
        "seo_title": "JetBrains Fleet 도입 판단 2026",
        "content_body": _content_body("JetBrains Fleet 도입 판단", inline_url),
        "html_article": "",
        "faq_section": [],
        "tag_names": ["JetBrains", "Fleet", "개발과-프로그래밍"],
        "cover_image": {"url": "https://img.example.com/cover.webp", "alt": "JetBrains Fleet 커버"},
        "inline_image": {"url": inline_url, "alt": "JetBrains Fleet 인라인"},
        "render_metadata": {},
        "entity_validation": {
            "status": entity_status,
            "entity_type": "tool",
            "display_name": "JetBrains Fleet",
            "evidence_urls": ["https://www.jetbrains.com/fleet/"] if entity_status == "verified" else [],
            "evidence_note": "official page" if entity_status == "verified" else "",
        },
        "layout_template": "single-layout-0415",
        "publish_state": {"status": "seeded", "publish_mode": None, "last_published_at": None, "last_error": None},
    }


def test_export_codex_write_packages_writes_new_schema(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_channel_with_post(db, category_slug="여행과-기록", slug="gangneung-route")
    monkeypatch.setattr(cloudflare_codex_write_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "_fetch_integration_post_detail",
        lambda _db, remote_post_id: {
            "id": remote_post_id,
            "title": "강릉 사천해변 반나절 동선 2026 | 사천진항부터 바다 카페까지 걷는 순서",
            "excerpt": "강릉 사천해변을 반나절 기준으로 걷는 실제 순서를 정리한다.",
            "seoTitle": "강릉 사천해변 반나절 동선 2026",
            "seoDescription": "강릉 사천해변 반나절 동선을 실제 순서로 정리한다.",
            "publicUrl": "https://dongriarchive.com/ko/post/gangneung-route",
            "coverImage": "https://img.example.com/cover.webp",
            "coverAlt": "강릉 바다 커버",
            "content": _content_body("강릉 사천해변 반나절 동선", "https://img.example.com/inline.webp"),
            "tags": [{"name": "강릉"}, {"name": "사천해변"}],
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
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    assert payload["prompt_version"] == "0414"
    assert payload["original_slug"] == "gangneung-route"
    assert payload["target_slug"] == "gangneung-route"
    assert payload["entity_validation"]["status"] == "manual_review_required"
    assert "<h2>자주 묻는 질문</h2>" in payload["content_body"]


def test_publish_blocks_factual_category_without_verified_entity(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_channel_with_post(db, category_slug="여행과-기록", slug="fake-route")
    base_dir = tmp_path / "codex_write" / "cloudflare"
    package_dir = base_dir / "동그리의 기록" / "yeohaenggwa-girog"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / "fake-route.json"
    payload = _package_payload(category_slug="여행과-기록", slug="fake-route", entity_status="manual_review_required")
    payload["entity_validation"] = {
        "status": "manual_review_required",
        "entity_type": "place",
        "display_name": "가짜 장소",
        "evidence_urls": [],
        "evidence_note": "",
    }
    package_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "list_cloudflare_categories",
        lambda _db: [{"id": "cat-travel", "slug": "여행과-기록", "name": "여행과-기록", "isLeaf": True}],
    )

    result = cloudflare_codex_write_service.publish_codex_write_packages(
        db,
        category_slugs=["여행과-기록"],
        dry_run=False,
        sync_after=False,
        base_dir=base_dir,
    )

    assert result["failed_count"] == 1
    saved = json.loads(package_path.read_text(encoding="utf-8"))
    assert saved["publish_state"]["status"] == "failed"
    assert "entity_validation_not_verified" in saved["publish_state"]["last_error"]


def test_publish_updates_existing_post_when_slug_unchanged(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_channel_with_post(db, category_slug="개발과-프로그래밍", slug="fleet-adoption")
    base_dir = tmp_path / "codex_write" / "cloudflare"
    package_dir = base_dir / "동그리의 기록" / "gaebalgwa-peurogeuraeming"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / "fleet-adoption.json"
    package_path.write_text(
        json.dumps(_package_payload(category_slug="개발과-프로그래밍", slug="fleet-adoption"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    captured: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "list_cloudflare_categories",
        lambda _db: [{"id": "cat-dev", "slug": "개발과-프로그래밍", "name": "개발과-프로그래밍", "isLeaf": True}],
    )
    monkeypatch.setattr(cloudflare_codex_write_service, "_resolve_payload_images", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cloudflare_codex_write_service, "_validate_codex_write_package", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "_integration_request",
        lambda _db, *, method, path, json_payload=None, timeout=0, **_kwargs: captured.append((method, path, json_payload or {}))
        or {"data": {"id": "remote-1", "publicUrl": "https://dongriarchive.com/ko/post/fleet-adoption", "slug": "fleet-adoption"}},
    )
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
    assert captured[0][0] == "PUT"
    assert captured[0][1] == "/api/integrations/posts/remote-1"
    assert "<h2>자주 묻는 질문</h2>" in captured[0][2]["content"]
    assert "<img src=\"https://img.example.com/inline.webp\"" in captured[0][2]["content"]
    saved = json.loads(package_path.read_text(encoding="utf-8"))
    assert saved["publish_state"]["status"] == "published"
    assert saved["publish_state"]["publish_mode"] == "put_existing"


def test_publish_falls_back_to_create_delete_when_slug_change_not_reflected(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _create_channel_with_post(db, category_slug="여행과-기록", slug="dongrimokpan-fake", remote_post_id="remote-old")
    base_dir = tmp_path / "codex_write" / "cloudflare"
    package_dir = base_dir / "동그리의 기록" / "yeohaenggwa-girog"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / "dongrimokpan-fake.json"
    payload = _package_payload(
        category_slug="여행과-기록",
        slug="dongrimokpan-fake",
        target_slug="gangneung-sacheon-beach-day-route-2026",
    )
    payload["title"] = "강릉 사천해변 반나절 동선 2026 | 사천진항부터 바다 카페까지 걷는 순서"
    payload["excerpt"] = "강릉 사천해변 반나절 동선을 실제 순서대로 정리한다. 사천진항과 바다 카페를 한 흐름으로 묶는다."
    payload["meta_description"] = "강릉 사천해변 반나절 동선을 실제 순서대로 정리한다. 사천진항과 바다 카페를 한 흐름으로 묶어 살핀다."
    payload["content_body"] = _content_body("강릉 사천해변 반나절 동선", "https://img.example.com/inline.webp")
    payload["entity_validation"] = {
        "status": "verified",
        "entity_type": "place",
        "display_name": "강릉 사천해변",
        "evidence_urls": ["https://map.naver.com/", "https://www.gn.go.kr/"],
        "evidence_note": "map and city reference",
    }
    package_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    calls: list[tuple[str, str, dict | None]] = []
    monkeypatch.setattr(
        cloudflare_codex_write_service,
        "list_cloudflare_categories",
        lambda _db: [{"id": "cat-travel", "slug": "여행과-기록", "name": "여행과-기록", "isLeaf": True}],
    )
    monkeypatch.setattr(cloudflare_codex_write_service, "_resolve_payload_images", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cloudflare_codex_write_service, "_validate_codex_write_package", lambda *_args, **_kwargs: [])

    def _fake_request(_db, *, method: str, path: str, json_payload=None, timeout=0, **_kwargs):
        calls.append((method, path, json_payload))
        if method == "PUT":
            return {"data": {"id": "remote-old", "publicUrl": "https://dongriarchive.com/ko/post/dongrimokpan-fake", "slug": "dongrimokpan-fake"}}
        if method == "POST":
            return {"data": {"id": "remote-new", "publicUrl": "https://dongriarchive.com/ko/post/gangneung-sacheon-beach-day-route-2026", "slug": "gangneung-sacheon-beach-day-route-2026"}}
        if method == "DELETE":
            return {"data": {"ok": True}}
        raise AssertionError(method)

    monkeypatch.setattr(cloudflare_codex_write_service, "_integration_request", _fake_request)
    monkeypatch.setattr(cloudflare_codex_write_service, "_integration_data_or_raise", lambda payload: payload["data"])
    monkeypatch.setattr(cloudflare_codex_write_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: {"status": "ok"})

    result = cloudflare_codex_write_service.publish_codex_write_packages(
        db,
        category_slugs=["여행과-기록"],
        dry_run=False,
        sync_after=True,
        base_dir=base_dir,
    )

    assert result["updated_count"] == 1
    assert [call[0] for call in calls] == ["PUT", "POST", "DELETE"]
    saved = json.loads(package_path.read_text(encoding="utf-8"))
    assert saved["remote_post_id"] == "remote-new"
    assert saved["published_url"].endswith("/gangneung-sacheon-beach-day-route-2026")
    assert saved["publish_state"]["publish_mode"] == "create_delete_fallback"


def test_canonical_content_body_keeps_faq_inside_section_until_closing_record() -> None:
    payload = _package_payload(category_slug="?ы뻾怨?湲곕줉", slug="section-scope-check")

    canonical = cloudflare_codex_write_service._canonical_content_body(payload)

    assert canonical.count("<section") == 1
    assert canonical.count("</section>") == 1

    section_close = canonical.find("</section>")
    faq_match = re.search(r"(?is)<h2[^>]*>\s*자주 묻는 질문\s*</h2>", canonical)
    closing_match = re.search(r"(?is)<h2[^>]*>\s*마무리 기록\s*</h2>", canonical)

    assert faq_match is not None
    assert closing_match is not None
    assert section_close > faq_match.start()
    assert section_close < closing_match.start()


def test_canonical_content_body_wraps_closing_record_in_note_aside() -> None:
    payload = _package_payload(category_slug="개발과-프로그래밍", slug="closing-record-wrap")

    canonical = cloudflare_codex_write_service._canonical_content_body(payload)

    assert '<aside class="note-aside closing-record" style="' in canonical
    assert canonical.count('class="note-aside closing-record"') == 1
    assert 'text-align:left' in canonical
    assert 'box-shadow:none' in canonical


def test_extract_closing_record_paragraph_reads_from_closing_record_aside() -> None:
    body = (
        "# sample\n\n"
        "<section><p>lead</p></section>\n\n"
        "<h2>마무리 기록</h2>\n"
        '<aside class="note-aside closing-record"><p>첫 문장이다. 둘째 문장이다.</p></aside>'
    )

    paragraph = cloudflare_codex_write_service._extract_closing_record_paragraph(body)

    assert paragraph == "<p>첫 문장이다. 둘째 문장이다.</p>"


def test_daily_memo_topic_fit_blocks_mystery_offtopic_tokens() -> None:
    payload = {
        "category_slug": "일상과-메모",
        "generation_model": "gpt-5.4-mini-2026-03-17",
        "title": "미스터리 단서 추적 메모 루틴으로 사건 기록 정리하기",
        "excerpt": "저녁 메모를 정리하는 방식이라고 소개하지만 사건 중심 단어가 핵심에 들어간다.",
        "slug": "mystery-content-consumption-memo-system-2026",
        "original_slug": "mystery-content-consumption-memo-system-2026",
        "target_slug": "mystery-content-consumption-memo-system-2026",
    }
    content_body = _content_body("일상 메모 루틴", "https://img.example.com/inline.webp")
    headings = cloudflare_codex_write_service._extract_headings(content_body)

    errors = cloudflare_codex_write_service._validate_daily_memo_topic_fit(
        payload,
        content_body=content_body,
        headings=headings,
    )

    assert "daily_offtopic_mystery" in errors


def test_daily_memo_topic_fit_accepts_valid_commute_memo_topic() -> None:
    payload = {
        "category_slug": "일상과-메모",
        "generation_model": "gpt-5.4-mini-2026-03-17",
        "title": "출퇴근 5분 체크 메모 루틴으로 할 일 누락 줄이기",
        "excerpt": "버스 대기 5분에 체크 메모를 남기며 하루 우선순위를 정렬하는 실전 루틴을 다룬다.",
        "slug": "commute-5-minute-micro-workout-check-memo-2026",
        "original_slug": "commute-5-minute-micro-workout-check-memo-2026",
        "target_slug": "commute-5-minute-micro-workout-check-memo-2026",
    }
    content_body = _content_body("출퇴근 5분 체크 메모 루틴", "https://img.example.com/inline.webp")
    headings = cloudflare_codex_write_service._extract_headings(content_body)

    errors = cloudflare_codex_write_service._validate_daily_memo_topic_fit(
        payload,
        content_body=content_body,
        headings=headings,
    )

    assert "generation_model_mismatch" not in errors
    assert "daily_offtopic_mystery" not in errors
    assert "daily_topic_axis_missing" not in errors
