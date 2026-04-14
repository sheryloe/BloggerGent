from scripts.verify_blogger_r2_layout import _canonical_media_key, _is_api_image_url, parse_args


def test_canonical_media_key_strips_assets_prefix_layers() -> None:
    key = _canonical_media_key(
        "https://api.dongriarchive.com/assets/assets/media/google-blogger/the-midnight-archives/mystery/2026/04/post/cover-a1b2c3d4e5f6.webp"
    )
    assert key == "media/google-blogger/the-midnight-archives/mystery/2026/04/post/cover-a1b2c3d4e5f6.webp"


def test_is_api_image_url_accepts_api_assets_images() -> None:
    assert _is_api_image_url(
        "https://api.dongriarchive.com/assets/assets/media/google-blogger/the-midnight-archives/mystery/2026/04/post/cover-a1b2c3d4e5f6.webp"
    )
    assert not _is_api_image_url("https://example.com/assets/image.webp")


def test_verify_parse_args_supports_blog_filters() -> None:
    args = parse_args(["--source", "all", "--blog-id", "34", "--blog-slug", "the-midnight-archives", "--timeout", "10"])
    assert args.source == "all"
    assert args.blog_id == [34]
    assert args.blog_slug == ["the-midnight-archives"]
    assert args.timeout == 10
