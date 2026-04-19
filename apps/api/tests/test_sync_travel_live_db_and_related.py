from __future__ import annotations

from scripts.travel.sync_travel_live_db_and_related import (
    count_related_png_fallback_tokens,
    is_stale_published_url,
    normalize_blogger_url_key,
)


def test_normalize_blogger_url_key_equates_http_https_www_and_trailing_slash() -> None:
    a = normalize_blogger_url_key("http://www.donggri-korea.blogspot.com/2026/04/sample-post/")
    b = normalize_blogger_url_key("https://donggri-korea.blogspot.com/2026/04/sample-post")
    c = normalize_blogger_url_key("https://donggri-korea.blogspot.com/2026/04/sample-post?m=1")

    assert a == "donggri-korea.blogspot.com/2026/04/sample-post"
    assert b == "donggri-korea.blogspot.com/2026/04/sample-post"
    assert c == "donggri-korea.blogspot.com/2026/04/sample-post"
    assert a == b == c


def test_is_stale_published_url_detects_missing_live_key() -> None:
    live_keys = {
        "donggri-korea.blogspot.com/2026/04/live-post-a",
        "donggri-korea.blogspot.com/2026/04/live-post-b",
    }

    assert (
        is_stale_published_url(
            "https://www.donggri-korea.blogspot.com/2026/04/live-post-a/",
            live_keys,
        )
        is False
    )
    assert (
        is_stale_published_url(
            "https://donggri-korea.blogspot.com/2026/04/deleted-post",
            live_keys,
        )
        is True
    )


def test_count_related_png_fallback_tokens_scans_related_block_only() -> None:
    html = """
    <article>
      <img src="https://example.com/body.webp" onerror="this.src='https://example.com/body-fallback.png'" />
      <section class="related-posts">
        <img src="https://example.com/related.webp" onerror="this.src='https://example.com/related-fallback.jpg'" />
      </section>
    </article>
    """

    assert count_related_png_fallback_tokens(html) == 0


def test_count_related_png_fallback_tokens_targets_onerror_only() -> None:
    html = """
    <article>
      <section class="related-posts">
        <img src="https://example.com/related-card.png" />
        <img src="https://example.com/related.webp" onerror="this.src='https://example.com/related-fallback.png';return;" />
      </section>
    </article>
    """

    assert count_related_png_fallback_tokens(html) == 1
