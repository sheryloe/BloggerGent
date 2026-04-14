from scripts.r2_live_relayout_webp import (
    _cloudflare_blog_group,
    _extract_image_urls,
    _is_target_path,
    _normalize_candidate_url,
    _normalize_target_key_for_layout,
    parse_args,
)


def test_parse_args_supports_source_and_blog_filters() -> None:
    args = parse_args(
        [
            "--source",
            "blogger-only",
            "--blog-id",
            "34",
            "--blog-id",
            "35",
            "--blog-slug",
            "the-midnight-archives",
            "--mode",
            "canary",
            "--canary-count",
            "2",
        ]
    )
    assert args.source == "blogger-only"
    assert args.blog_id == [34, 35]
    assert args.blog_slug == ["the-midnight-archives"]
    assert args.mode == "canary"
    assert args.canary_count == 2


def test_normalize_target_key_for_layout_collapses_double_assets_prefix() -> None:
    normalized = _normalize_target_key_for_layout(
        "assets/assets/media/google-blogger/the-midnight-archives/mystery/2026/04/post/cover-1234567890ab.webp"
    )
    assert normalized == "assets/media/google-blogger/the-midnight-archives/mystery/2026/04/post/cover-1234567890ab.webp"


def test_is_target_path_accepts_normalized_double_assets_key() -> None:
    assert _is_target_path(
        key="assets/assets/media/google-blogger/donggri-el-alma-de-corea/travel/2026/04/seoul-day-route/cover-aabbccddeeff.webp",
        blog_group="google-blogger/donggri-el-alma-de-corea",
        category_key="travel",
        post_slug="seoul-day-route",
    )


def test_normalize_candidate_url_strips_script_tail() -> None:
    normalized = _normalize_candidate_url(
        "https://api.dongriarchive.com/assets/assets/media/posts/2026/04/sample.webp&#x27;;return;}if(this.dataset.fb1!==&#x27;1&#x27;"
    )
    assert normalized == "https://api.dongriarchive.com/assets/assets/media/posts/2026/04/sample.webp"


def test_extract_image_urls_ignores_onerror_tail_pollution() -> None:
    html = """
    <img src="https://api.dongriarchive.com/assets/assets/media/posts/2026/04/sample.webp&#x27;;return;}if(this.dataset.fb1!==&#x27;1&#x27;" />
    """
    urls = _extract_image_urls(html)
    assert urls == ["https://api.dongriarchive.com/assets/assets/media/posts/2026/04/sample.webp"]


def test_cloudflare_blog_group_uses_channel_slug() -> None:
    assert _cloudflare_blog_group("Dongri Archive") == "cloudflare/dongri-archive"
