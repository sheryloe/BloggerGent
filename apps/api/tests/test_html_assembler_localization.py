from types import SimpleNamespace

from app.services.content.html_assembler import assemble_article_html, render_faq_html


def test_render_faq_html_uses_toggle_markup() -> None:
    html = render_faq_html(
        [{"question": "Pregunta", "answer": "Respuesta"}],
        section_title="Preguntas frecuentes",
        heading="#111827",
        body="#334155",
        card_background="#ffffff",
        card_border="#cbd5e1",
    )

    assert "<details" in html
    assert "<summary" in html
    assert "Preguntas frecuentes" in html


def test_assemble_article_html_localizes_faq_and_related_titles_for_spanish() -> None:
    article = SimpleNamespace(
        title="Ruta por Yeonnam-dong",
        html_article="<h2>Ruta</h2><p>Texto principal.</p><table><tr><th>Hora</th><td>10:00</td></tr></table>",
        faq_section=[{"question": "¿Qué conviene saber primero?", "answer": "Conviene empezar por la ruta principal."}],
        meta_description="Guía breve para recorrer Yeonnam-dong con ritmo claro y paradas útiles.",
        excerpt="Primera frase. Segunda frase.",
        inline_media=[],
        image=None,
        blog=SimpleNamespace(name="Donggri ES", content_category="travel", primary_language="es"),
    )

    assembled = assemble_article_html(article, hero_image_url="", related_posts=[])

    assert "Preguntas frecuentes" in assembled
    assert "Lecturas relacionadas" in assembled
    assert "<details" in assembled
    assert "border:1px solid" in assembled


def test_assemble_article_html_localizes_faq_title_for_japanese() -> None:
    article = SimpleNamespace(
        title="延南洞の散歩ガイド",
        html_article="<h2>散歩の流れ</h2><p>本文です。</p>",
        faq_section=[{"question": "最初に何を確認すればいいですか？", "answer": "駅からの動線を先に確認すると楽です。"}],
        meta_description="延南洞を歩く前に押さえておきたい動線と立ち寄り先をまとめたガイドです。",
        excerpt="一文目です。二文目です。",
        inline_media=[],
        image=None,
        blog=SimpleNamespace(name="Donggri JP", content_category="travel", primary_language="ja"),
    )

    assembled = assemble_article_html(article, hero_image_url="", related_posts=[])

    assert "よくある質問（FAQ）" in assembled
    assert "関連記事" in assembled


def test_assemble_article_html_mystery_forces_english_ui_and_light_theme() -> None:
    article = SimpleNamespace(
        title="Mystery dossier",
        html_article="<h2>Case outline</h2><p>Body text.</p><table><tr><th>Fact</th><td>Detail</td></tr></table>",
        faq_section=[{"question": "질문", "answer": "답변"}],
        meta_description="Short summary for mystery page.",
        excerpt="First sentence. Second sentence.",
        inline_media=[],
        image=None,
        blog=SimpleNamespace(name="Mystery Blog", content_category="mystery", primary_language="ko"),
    )

    assembled = assemble_article_html(article, hero_image_url="", related_posts=[])

    assert "Frequently Asked Questions" in assembled
    assert "Related Mystery Stories" in assembled
    assert "color:#0f172a" in assembled
    assert "background:#ffffff" in assembled


def test_assemble_article_html_mystery_english_strips_hangul_from_body_and_faq() -> None:
    article = SimpleNamespace(
        title="Iron Mask Mystery",
        html_article="<h2>Case outline</h2><p>철가면 남자 사건 기록</p>",
        faq_section=[{"question": "철가면 남자 핵심은?", "answer": "철저한 사건 기록을 확인하세요."}],
        meta_description="A mystery story summary.",
        excerpt="First sentence. Second sentence.",
        inline_media=[],
        image=None,
        blog=SimpleNamespace(name="Mystery Blog", content_category="mystery", primary_language="en"),
    )

    assembled = assemble_article_html(article, hero_image_url="", related_posts=[])

    assert "철가면" not in assembled
    assert "사건 기록" not in assembled
