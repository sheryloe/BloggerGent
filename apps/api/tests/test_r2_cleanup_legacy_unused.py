from scripts.r2_cleanup_legacy_unused import _extract_image_urls


def test_cleanup_extract_image_urls_ignores_onerror_tail_pollution() -> None:
    html = """
    <img src="https://api.dongriarchive.com/assets/assets/media/posts/2026/04/sample.webp&#x27;;return;}if(this.dataset.fb1!==&#x27;1&#x27;" />
    """
    urls = _extract_image_urls(html)
    assert urls == ["https://api.dongriarchive.com/assets/assets/media/posts/2026/04/sample.webp"]


def test_cleanup_extract_image_urls_skips_non_http_candidates() -> None:
    html = "<img src=\"javascript:alert('xss')\" />"
    assert _extract_image_urls(html) == []
