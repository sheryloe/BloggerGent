from __future__ import annotations

from app.services.cloudflare.cloudflare_channel_service import _sanitize_cloudflare_public_body


def test_sanitize_cloudflare_public_body_removes_centered_wrapper_without_inline_styles() -> None:
    body = """
<section class="route-hero-card" style="max-width:860px;margin:0 auto;text-align:center;box-shadow:0 10px 20px rgba(0,0,0,.1);">
  <h2>도입</h2>
  <p>본문</p>
</section>
"""
    rendered = _sanitize_cloudflare_public_body(
        body,
        category_slug="여행과-기록",
        title="강릉 사천해변 반나절 동선 2026",
        layout_template="route-hero-card",
    )

    assert "max-width:860px" not in rendered
    assert "margin:0 auto" not in rendered
    assert "text-align:center" not in rendered
    assert "style=" not in rendered
    assert 'class="route-hero-card"' in rendered
    assert "마무리 기록" in rendered
