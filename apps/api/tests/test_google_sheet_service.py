from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.integrations.google_sheet_service import (
    BLOGGER_SNAPSHOT_COLUMNS,
    CLOUDFLARE_SNAPSHOT_COLUMNS,
    COLUMN_LABELS_KO,
    QUALITY_COLUMNS,
    TopicHistoryEntry,
    _collect_sheet_exclusion_entries,
    _derive_priority_fields,
    _sort_sheet_records,
    assess_topic_novelty_against_history,
    merge_sheet_rows_with_existing,
    sync_google_sheet_quality_tab,
)


def _base_row(*, title: str, url: str, slug: str) -> dict[str, str]:
    row = {column: "" for column in BLOGGER_SNAPSHOT_COLUMNS}
    row.update(
        {
            "date_kst": "2026-03-28T00:00:00+09:00",
            "profile": "world_mystery",
            "blog": "The Midnight Archives",
            "title": title,
            "url": url,
            "slug": slug,
            "summary": "summary",
            "labels": "mystery",
            "status": "published",
            "published_at": "2026-03-28T00:00:00+09:00",
            "updated_at": "2026-03-28T00:00:00+09:00",
        }
    )
    row.update(
        {
            "topic_cluster": "flannan-isles",
            "topic_angle": "timeline",
            "similarity_score": "65.2",
            "most_similar_url": "",
            "seo_score": "82",
            "geo_score": "79",
            "quality_status": "ok",
            "rewrite_attempts": "0",
            "last_audited_at": "2026-03-28T01:00:00+09:00",
        }
    )
    return row


def test_merge_sheet_rows_with_existing_preserves_manual_columns_and_appends_missing_rows() -> None:
    existing_rows = [
        ["date_kst", "profile", "blog", "title", "url", "slug", "manual_note"],
        [
            "2026-03-20T00:00:00+09:00",
            "world_mystery",
            "The Midnight Archives",
            "Old title",
            "https://example.com/flannan",
            "flannan-old",
            "keep-manual",
        ],
    ]
    incoming_rows = [
        _base_row(title="Updated title", url="https://example.com/flannan", slug="flannan-isles"),
        _base_row(title="New article", url="https://example.com/dyatlov", slug="dyatlov-pass"),
    ]

    merged = merge_sheet_rows_with_existing(
        existing_rows=existing_rows,
        incoming_rows=incoming_rows,
        base_columns=BLOGGER_SNAPSHOT_COLUMNS,
        quality_columns=QUALITY_COLUMNS,
        key_columns=("url", "slug"),
    )

    header = merged[0]
    url_index = header.index(COLUMN_LABELS_KO["url"])
    title_index = header.index(COLUMN_LABELS_KO["title"])
    manual_index = header.index("manual_note")
    updated_row = next(row for row in merged[1:] if row[url_index] == "https://example.com/flannan")
    new_row = next(row for row in merged[1:] if row[url_index] == "https://example.com/dyatlov")

    assert "manual_note" in header
    assert COLUMN_LABELS_KO["similarity_score"] in header
    assert COLUMN_LABELS_KO["geo_score"] in header
    assert updated_row[title_index] == "Updated title"
    assert updated_row[manual_index] == "keep-manual"
    assert new_row[url_index] == "https://example.com/dyatlov"


def test_collect_sheet_exclusions_cloudflare_filters_noise_rows() -> None:
    rows = [
        ["title", "topic_cluster", "topic_angle", "status", "category"],
        ["A", "", "", "published", "문화와 공감"],
        ["B", "channel_post", "overview", "published", "문화와 공감"],
        ["C", "flannan isles", "", "published", "미스터리 스토리"],
        ["D", "flannan isles", "timeline", "published", "미스터리 스토리"],
        ["E", "dyatlov", "theory", "DISLIVE", "미스터리 스토리"],
    ]
    entries = _collect_sheet_exclusion_entries(
        rows=rows,
        require_cluster_angle=True,
        include_category=True,
        limit=20,
    )
    assert entries == ["미스터리 스토리 :: flannan isles | timeline"]


def test_merge_sheet_rows_with_existing_removes_duplicate_summary_columns() -> None:
    existing_rows = [
        [
            "작성일(KST)",
            "프로필",
            "블로그",
            "제목",
            "본문 URL",
            "슬러그",
            "내용 요약",
            "라벨",
            "검증상태",
            "공개일시",
            "수정일시",
            "콘텐츠 카테고리",
            "카테고리 키",
            "주제 클러스터",
            "주제 각도",
            "본문 유사율",
            "가장 유사한 글 URL",
            "SEO 점수",
            "GEO 점수",
            "품질 상태",
            "재작성 횟수",
            "마지막 점검일시",
            "excerpt",
            "manual_note",
        ],
        [
            "2026-03-20T00:00:00+09:00",
            "world_mystery",
            "The Midnight Archives",
            "Old title",
            "https://example.com/flannan",
            "flannan-old",
            "기존 요약",
            "mystery",
            "published",
            "2026-03-20T00:00:00+09:00",
            "2026-03-20T00:00:00+09:00",
            "Case Files",
            "case-files",
            "flannan-isles",
            "timeline",
            "63.2",
            "",
            "81",
            "80",
            "ok",
            "0",
            "2026-03-20T01:00:00+09:00",
            "중복 요약 컬럼",
            "keep-manual",
        ],
    ]
    incoming_rows = [_base_row(title="Updated title", url="https://example.com/flannan", slug="flannan-isles")]

    merged = merge_sheet_rows_with_existing(
        existing_rows=existing_rows,
        incoming_rows=incoming_rows,
        base_columns=BLOGGER_SNAPSHOT_COLUMNS,
        quality_columns=QUALITY_COLUMNS,
        key_columns=("url", "slug"),
    )

    header = merged[0]
    assert header.count(COLUMN_LABELS_KO["summary"]) == 1
    assert "excerpt" not in header
    assert "manual_note" in header


def test_derive_priority_fields_matches_operation_policy() -> None:
    now = datetime(2026, 3, 30, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    assert _derive_priority_fields(
        {"status": "scheduled", "due_at": "2026-03-30T20:00:00+09:00"},
        now=now,
    )[0] == 1
    assert _derive_priority_fields(
        {"status": "scheduled", "due_at": "2026-04-01T12:00:00+09:00"},
        now=now,
    )[0] == 2
    assert _derive_priority_fields({"status": "draft", "due_at": ""}, now=now)[0] == 2
    assert _derive_priority_fields({"status": "published", "quality_status": "rewrite_required"}, now=now)[0] == 3
    assert _derive_priority_fields({"status": "published", "seo_score": "55"}, now=now)[0] == 3
    assert _derive_priority_fields({"status": "published", "quality_status": "ok"}, now=now)[0] == 4
    assert _derive_priority_fields({"status": "deleted", "quality_status": "ok"}, now=now)[0] == 5


def test_sort_sheet_records_prioritizes_due_time_then_recency() -> None:
    records = [
        {"title": "p3-old", "priority_rank": "3", "published_at": "2026-03-28T08:00:00+09:00"},
        {"title": "p2-late", "priority_rank": "2", "due_at": "2026-04-02T08:00:00+09:00"},
        {"title": "p1-late", "priority_rank": "1", "due_at": "2026-03-30T23:00:00+09:00"},
        {"title": "p2-early", "priority_rank": "2", "due_at": "2026-03-31T08:00:00+09:00"},
        {"title": "p1-early", "priority_rank": "1", "due_at": "2026-03-30T10:00:00+09:00"},
        {"title": "p3-new", "priority_rank": "3", "published_at": "2026-03-29T08:00:00+09:00"},
    ]

    sorted_records = _sort_sheet_records(records)
    sorted_titles = [record["title"] for record in sorted_records]
    assert sorted_titles == ["p1-early", "p1-late", "p2-early", "p2-late", "p3-new", "p3-old"]


def test_merge_sheet_rows_with_existing_uses_cloudflare_key_priority() -> None:
    existing_rows = [
        [*CLOUDFLARE_SNAPSHOT_COLUMNS, "manual_note"],
        [
            "2026-03-30T10:00:00+09:00",
            "2026-03-30T08:00:00+09:00",
            "2026-03-30T09:00:00+09:00",
            "Culture",
            "culture-space",
            "remote-123",
            "Old title",
            "",
            "old excerpt",
            "",
            "published",
            "keep",
        ],
    ]
    incoming_rows = [
        {
            "remote_id": "remote-123",
            "published_at": "2026-03-30T11:00:00+09:00",
            "created_at": "2026-03-30T08:00:00+09:00",
            "updated_at": "2026-03-30T11:00:00+09:00",
            "category": "Culture",
            "category_slug": "culture-space",
            "title": "Updated title",
            "url": "",
            "excerpt": "new excerpt",
            "labels": "",
            "status": "published",
            "quality_status": "ok",
        }
    ]

    merged = merge_sheet_rows_with_existing(
        existing_rows=existing_rows,
        incoming_rows=incoming_rows,
        base_columns=CLOUDFLARE_SNAPSHOT_COLUMNS,
        quality_columns=QUALITY_COLUMNS,
        key_columns=("url", "remote_id", "title"),
    )

    header = merged[0]
    title_index = header.index(COLUMN_LABELS_KO["title"])
    manual_index = header.index("manual_note")
    assert len(merged) == 2
    assert merged[1][title_index] == "Updated title"
    assert merged[1][manual_index] == "keep"


def test_sync_google_sheet_quality_tab_applies_operational_format(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    sheet_id = "sheet-123"

    class _Response:
        def __init__(self, payload: dict[str, object] | None = None):
            self._payload = payload or {}
            self.content = b"{}"
            self.text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    def _fake_google_request(_db, method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        params = kwargs.get("params") if isinstance(kwargs.get("params"), dict) else {}
        if method == "GET" and url.endswith(sheet_id):
            fields = str(params.get("fields") or "")
            if "conditionalFormats" in fields:
                return _Response(
                    {
                        "sheets": [
                            {
                                "properties": {
                                    "title": "Quality",
                                    "sheetId": 101,
                                    "gridProperties": {"rowCount": 1000, "columnCount": 26},
                                },
                                "conditionalFormats": [{"dummy": True}],
                            }
                        ]
                    }
                )
            return _Response({"sheets": [{"properties": {"title": "Quality"}}]})
        if method == "GET" and "/values/" in url:
            return _Response({"values": []})
        return _Response({})

    monkeypatch.setattr("app.services.integrations.google_sheet_service.authorized_google_request", _fake_google_request)

    sync_google_sheet_quality_tab(
        db=object(),
        sheet_id=sheet_id,
        tab_name="Quality",
        incoming_rows=[_base_row(title="Row", url="https://example.com/one", slug="one")],
        base_columns=BLOGGER_SNAPSHOT_COLUMNS,
        quality_columns=QUALITY_COLUMNS,
        key_columns=("url", "slug"),
        auto_format_enabled=True,
    )

    batch_calls = [call for call in calls if call["method"] == "POST" and str(call["url"]).endswith(":batchUpdate")]
    assert len(batch_calls) == 1
    requests = batch_calls[0]["kwargs"]["json"]["requests"]  # type: ignore[index]

    assert any("updateSheetProperties" in item for item in requests)
    assert any("setBasicFilter" in item for item in requests)
    assert any("deleteConditionalFormatRule" in item for item in requests)

    add_rules = [item["addConditionalFormatRule"]["rule"] for item in requests if "addConditionalFormatRule" in item]
    labels = {rule["booleanRule"]["condition"]["values"][0]["userEnteredValue"] for rule in add_rules}
    assert labels == {"긴급", "확인", "일반", "보관"}


def test_collect_sheet_exclusions_applies_lookback_and_blog_scope() -> None:
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    rows = [
        ["date_kst", "profile", "blog", "title", "topic_cluster", "topic_angle", "status", "category"],
        [recent, "world_mystery", "The Midnight Archives", "Recent Match", "flannan", "timeline", "published", "Case Files"],
        [stale, "world_mystery", "The Midnight Archives", "Old Topic", "dyatlov", "theory", "published", "Case Files"],
        [recent, "korea_travel", "Travel Blog", "Other Profile", "seoul", "night-route", "published", "Travel"],
    ]

    entries = _collect_sheet_exclusion_entries(
        rows=rows,
        require_cluster_angle=False,
        include_category=False,
        limit=20,
        lookback_days=180,
        profile_key="world_mystery",
        blog_name="The Midnight Archives",
        source="sheet_blogger",
    )

    assert entries == ["flannan | timeline"]


def test_assess_topic_novelty_penalizes_same_cluster_similar_angle() -> None:
    history = [
        TopicHistoryEntry(
            keyword="Flannan Isles disappearance timeline",
            topic_cluster="flannan isles disappearance",
            topic_angle="timeline reconstruction",
            category="Case Files",
            profile="world_mystery",
            blog="The Midnight Archives",
            published_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            source="sheet_blogger",
        )
    ]

    novelty = assess_topic_novelty_against_history(
        keyword="Flannan Isles disappearance timeline deep dive",
        topic_cluster="flannan isles disappearance",
        topic_angle="timeline reconstruction",
        history_entries=history,
        cluster_threshold=0.85,
        angle_threshold=0.75,
    )

    assert int(novelty["penalty_points"]) >= 2
    assert novelty["matched_history_item"]


def test_assess_topic_novelty_allows_same_cluster_different_angle() -> None:
    history = [
        TopicHistoryEntry(
            keyword="Flannan Isles disappearance timeline",
            topic_cluster="flannan isles disappearance",
            topic_angle="timeline reconstruction",
            category="Case Files",
            profile="world_mystery",
            blog="The Midnight Archives",
            published_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            source="sheet_blogger",
        )
    ]

    novelty = assess_topic_novelty_against_history(
        keyword="Flannan Isles weather and rescue logistics analysis",
        topic_cluster="flannan isles disappearance",
        topic_angle="weather pattern and rescue logistics",
        history_entries=history,
        cluster_threshold=0.85,
        angle_threshold=0.75,
    )

    assert int(novelty["penalty_points"]) < 2
    assert "same_cluster_different_angle_allowed" in str(novelty["penalty_reason"])
