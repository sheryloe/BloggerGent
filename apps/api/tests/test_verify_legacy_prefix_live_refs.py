from scripts.verify_legacy_prefix_live_refs import parse_args


def test_verify_legacy_prefix_parse_args() -> None:
    args = parse_args(
        [
            "--needle",
            "/assets/media/posts/2026/",
            "--timeout",
            "15",
            "--report-path",
            "/tmp/verify.json",
        ]
    )
    assert args.needle == "/assets/media/posts/2026/"
    assert args.timeout == 15
    assert args.report_path == "/tmp/verify.json"
