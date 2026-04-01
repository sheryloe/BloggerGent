import pytest

try:
    from app.tasks.pipeline import _is_blossom_topic_keyword, _quality_gate_fail_reasons, _would_exceed_blossom_cap
except ModuleNotFoundError:
    _is_blossom_topic_keyword = None
    _quality_gate_fail_reasons = None
    _would_exceed_blossom_cap = None


_SKIP_REASON = "celery or pipeline dependencies are not installed in this local python environment"


@pytest.mark.skipif(_quality_gate_fail_reasons is None, reason=_SKIP_REASON)
def test_quality_gate_fail_reasons_boundary() -> None:
    reasons = _quality_gate_fail_reasons(
        similarity_score=70.0,
        seo_score=59.0,
        geo_score=60.0,
        similarity_threshold=70.0,
        min_seo_score=60.0,
        min_geo_score=60.0,
    )
    assert "similarity_threshold" in reasons
    assert "seo_below_min" in reasons
    assert "geo_below_min" not in reasons


@pytest.mark.skipif(_would_exceed_blossom_cap is None, reason=_SKIP_REASON)
def test_blossom_cap_allows_first_blossom_during_bootstrap() -> None:
    counter = {"total_topics": 0, "blossom_topics": 0}
    assert _would_exceed_blossom_cap(counter=counter, is_blossom=True, cap_ratio=0.2) is False


@pytest.mark.skipif(_would_exceed_blossom_cap is None, reason=_SKIP_REASON)
def test_blossom_cap_allows_until_twenty_percent() -> None:
    counter = {"total_topics": 4, "blossom_topics": 0}
    assert _would_exceed_blossom_cap(counter=counter, is_blossom=True, cap_ratio=0.2) is False


@pytest.mark.skipif(_would_exceed_blossom_cap is None, reason=_SKIP_REASON)
def test_blossom_cap_blocks_after_twenty_percent() -> None:
    counter = {"total_topics": 4, "blossom_topics": 1}
    assert _would_exceed_blossom_cap(counter=counter, is_blossom=True, cap_ratio=0.2) is True


@pytest.mark.skipif(_is_blossom_topic_keyword is None, reason=_SKIP_REASON)
def test_blossom_keyword_detection_supports_korean_variants() -> None:
    assert _is_blossom_topic_keyword("서울 왕벚꽃 산책 코스") is True
    assert _is_blossom_topic_keyword("전주 겹벚꽃 명소 정리") is True
