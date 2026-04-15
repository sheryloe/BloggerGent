from scripts.r2_cleanup_legacy_unused import _extract_image_urls, _extract_live_hits_total, parse_args


def test_cleanup_extract_image_urls_ignores_onerror_tail_pollution() -> None:
    html = """
    <img src="https://api.dongriarchive.com/assets/assets/media/posts/2026/04/sample.webp&#x27;;return;}if(this.dataset.fb1!==&#x27;1&#x27;" />
    """
    urls = _extract_image_urls(html)
    assert urls == ["https://api.dongriarchive.com/assets/assets/media/posts/2026/04/sample.webp"]


def test_cleanup_extract_image_urls_skips_non_http_candidates() -> None:
    html = "<img src=\"javascript:alert('xss')\" />"
    assert _extract_image_urls(html) == []


def test_cleanup_parse_args_supports_new_gate_options() -> None:
    args = parse_args(
        [
            "--apply",
            "--legacy-prefix",
            "assets/media/posts/2026/",
            "--ignore-grace",
            "--existing-only",
            "--abort-if-live-hit",
            "--live-check-report-path",
            "/tmp/live.json",
        ]
    )
    assert args.apply is True
    assert args.legacy_prefix == "assets/media/posts/2026/"
    assert args.ignore_grace is True
    assert args.existing_only is True
    assert args.abort_if_live_hit is True
    assert args.live_check_report_path == "/tmp/live.json"


def test_cleanup_extract_live_hits_total_prefers_summary_key() -> None:
    payload = {"summary": {"live_hits_total": 3, "with_needle": 1}}
    assert _extract_live_hits_total(payload) == 3
