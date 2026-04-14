from app.services.cloudflare.cloudflare_channel_service import _sanitize_cloudflare_public_body


def test_sanitize_cloudflare_public_body_removes_english_faq_boilerplate() -> None:
    source = """
<h2>よくある質問（FAQ）</h2>
<p>What should readers know about 延南洞の文化スポット紹介?</p>
<p>This section summarizes the essential context, expectations, and constraints around 延南洞の文化スポット紹介 so readers can act with confidence.</p>
<p>How can readers apply 延南洞の文化スポット紹介 effectively?</p>
<p>Use a short checklist and the key steps in this article to plan, evaluate, and execute 延南洞の文化スポット紹介 without missing critical details.</p>
<h2>본문</h2>
<p>현장 팁 본문.</p>
""".strip()

    cleaned = _sanitize_cloudflare_public_body(
        source,
        category_slug="여행과-기록",
        title="연남동 문화 스팟",
    )

    assert "What should readers know about" not in cleaned
    assert "How can readers apply" not in cleaned
    assert "Use a short checklist and the key steps" not in cleaned
    assert "<h2>마무리 기록</h2>" in cleaned

