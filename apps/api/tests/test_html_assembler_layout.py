from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from app.services.content.html_assembler import assemble_article_html


def test_assemble_article_html_uses_left_aligned_wrapper_without_centered_card() -> None:
    article = SimpleNamespace(
        title="실제 장소 가이드",
        html_article="<h2>동선</h2><p>본문입니다.</p>",
        faq_section=[{"question": "무엇을 보나?", "answer": "순서를 먼저 봅니다."}],
        meta_description="실제 장소를 기준으로 순서를 정리한 안내.",
        excerpt="첫 문장. 둘째 문장.",
        inline_media=[],
        image=None,
        blog=SimpleNamespace(name="Donggri Travel", content_category="travel", primary_language="ko"),
    )

    assembled = assemble_article_html(article, hero_image_url="", related_posts=[])

    assert "max-width:860px" not in assembled
    assert "margin:0 auto" not in assembled
    assert "box-shadow:" not in assembled
    assert "background:transparent" in assembled
    assert "text-align:left" in assembled
    assert "align-items:flex-start" in assembled
