from __future__ import annotations

from app.services.content.content_ops_service import compute_seo_geo_scores, compute_similarity_analysis


def test_compute_similarity_analysis_detects_near_duplicate_pair() -> None:
    items = [
        {
            "key": "a",
            "title": "The Flannan Isles Lighthouse Disappearance Timeline",
            "body_html": (
                "<h2>Incident timeline</h2><p>In 1900 three keepers vanished from Eilean Mor lighthouse. "
                "The official records describe a storm warning and an interrupted logbook entry.</p>"
                "<h3>Investigation notes</h3><p>Rescue crews found a stopped clock, missing oilskins, and no survivors.</p>"
            ),
            "url": "https://example.com/a",
        },
        {
            "key": "b",
            "title": "Flannan Isles Keepers Case: Timeline and Evidence",
            "body_html": (
                "<h2>Incident timeline</h2><p>In 1900, three lighthouse keepers disappeared on Eilean Mor. "
                "Official log entries mention severe weather and an unfinished final note.</p>"
                "<h3>Investigation notes</h3><p>Search teams reported a stopped clock, oilskins missing from hooks, and no trace.</p>"
            ),
            "url": "https://example.com/b",
        },
        {
            "key": "c",
            "title": "Cherry Blossom Transit Guide in Seoul",
            "body_html": (
                "<h2>Route planning</h2><p>This guide covers subway transfers, walking loops, and local blossom festivals.</p>"
            ),
            "url": "https://example.com/c",
        },
    ]

    result = compute_similarity_analysis(items)
    assert result["a"]["most_similar_key"] == "b"
    assert float(result["a"]["similarity_score"]) > 35.0
    assert float(result["c"]["similarity_score"]) < 50.0


def test_compute_seo_geo_scores_rewards_structured_content() -> None:
    strong_html = (
        "<h2>What happened in 1900</h2>"
        "<p>This article explains what happened at Eilean Mor lighthouse, why the timeline still matters, and how records were preserved.</p>"
        "<h2>Timeline and evidence</h2>"
        "<p>According to archive records from 1900 and 1901, investigators documented weather alerts, witness statements, and official reports.</p>"
        "<h3>Checklist for readers</h3>"
        "<p>Use this checklist: review the timeline, compare theories, and verify each source link before conclusion.</p>"
        "<p>Related source: <a href='https://dongriarchive.com/ko/post/flannan-isles'>internal reference</a>.</p>"
    )
    weak_html = "<p>Interesting mystery. Nobody knows what happened. It is still mysterious.</p>"

    strong = compute_seo_geo_scores(
        title="Flannan Isles Lighthouse Disappearance Explained",
        html_body=strong_html,
        excerpt="A structured review of timeline, evidence, and theories.",
        faq_section=[
            {"question": "What is the core event?", "answer": "Three lighthouse keepers vanished in 1900."},
            {"question": "Why is it still debated?", "answer": "Evidence is fragmentary and interpretations diverge."},
        ],
    )
    weak = compute_seo_geo_scores(
        title="Mystery Story",
        html_body=weak_html,
        excerpt="Short note.",
        faq_section=[],
    )

    assert 0 <= strong["seo_score"] <= 100
    assert 0 <= strong["geo_score"] <= 100
    assert strong["seo_score"] > weak["seo_score"]
    assert strong["geo_score"] > weak["geo_score"]


def test_compute_seo_geo_scores_supports_korean_geo_signals() -> None:
    korean_html = (
        "<h2>서울 종로구 북촌 한옥마을 동선</h2>"
        "<p>이 글은 서울 종로구 북촌 한옥마을을 방문할 때 필요한 일정, 교통, 동선, 예약, 운영시간을 정리합니다.</p>"
        "<h2>2026년 4월 전시 일정과 위치</h2>"
        "<p>국립현대미술관과 인사동 전시 공간 위치를 기준으로 오전·오후 코스를 나눕니다. 출처와 공식 자료를 함께 확인합니다.</p>"
        "<h3>체크리스트</h3>"
        "<p>준비물, 입장 순서, 이동 시간, 예산, 안전 주의사항을 단계별로 안내합니다.</p>"
        "<p>관련 링크: <a href='https://dongriarchive.com/ko/post/seoul-culture-route'>내부 참고</a>.</p>"
    )

    scores = compute_seo_geo_scores(
        title="서울 문화 공간 하루 동선 가이드",
        html_body=korean_html,
        excerpt="서울 문화 공간 방문을 위한 실전 동선과 체크리스트 요약.",
        faq_section=[
            {"question": "어디부터 시작하면 좋나요?", "answer": "북촌 한옥마을에서 시작해 인사동으로 이동하면 동선이 효율적입니다."},
            {"question": "교통은 어떻게 준비하나요?", "answer": "지하철과 도보 이동 기준으로 시간대를 나눠 계획하세요."},
        ],
    )

    assert scores["geo_score"] >= 60
