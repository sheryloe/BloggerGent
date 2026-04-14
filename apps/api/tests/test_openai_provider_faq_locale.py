from app.services.providers.openai import _coerce_article_payload


def test_coerce_article_payload_localizes_spanish_faq_fallback() -> None:
    payload = _coerce_article_payload(
        """{
          "title": "Guia de Yeonnam-dong para caminar sin prisas",
          "meta_description": "Una guia clara para recorrer Yeonnam-dong con ritmo lento, cafes tranquilos y paradas culturales utiles para un dia completo en Seul.",
          "labels": ["Seul", "Yeonnam-dong", "viaje", "cafes", "Corea"],
          "slug": "guia-yeonnam-dong-seul",
          "excerpt": "Primera frase util para orientar la lectura del recorrido completo en Seul. Segunda frase util para dejar claro el valor practico de las paradas y del ritmo de la ruta.",
          "html_article": "<h2>Ruta</h2><p>Texto suficiente para superar el minimo de longitud en las pruebas sin depender de contenido externo. Texto suficiente para superar el minimo de longitud en las pruebas sin depender de contenido externo. Texto suficiente para superar el minimo de longitud en las pruebas sin depender de contenido externo.</p>",
          "faq_section": [{"question": "", "answer": ""}],
          "image_collage_prompt": "editorial travel collage with nine panels, visible white gutters, dominant center panel, realistic Seoul neighborhood scenes",
          "inline_collage_prompt": "supporting travel collage with six panels, visible white gutters, realistic Seoul walking route scenes"
        }""",
        "Yeonnam-dong",
        "All reader-facing outputs must be in Spanish.",
    )

    assert payload.faq_section
    assert payload.faq_section[0].question.startswith("\u00bf")


def test_coerce_article_payload_localizes_japanese_faq_fallback() -> None:
    payload = _coerce_article_payload(
        """{
          "title": "\\u5ef6\\u5357\\u6d1e\\u306e\\u6563\\u6b69\\u30ac\\u30a4\\u30c9 2026",
          "meta_description": "\\u5ef6\\u5357\\u6d1e\\u3092\\u6b69\\u304f\\u524d\\u306b\\u62bc\\u3055\\u3048\\u3066\\u304a\\u304d\\u305f\\u3044\\u52d5\\u7dda\\u3001\\u4f11\\u61a9\\u5834\\u6240\\u3001\\u6587\\u5316\\u30b9\\u30dd\\u30c3\\u30c8\\u3092\\u4e00\\u5ea6\\u306b\\u78ba\\u8a8d\\u3067\\u304d\\u308b\\u65e5\\u672c\\u8a9e\\u30ac\\u30a4\\u30c9\\u3068\\u3057\\u3066\\u4f7f\\u3048\\u308b\\u3088\\u3046\\u306b\\u307e\\u3068\\u3081\\u305f\\u8a18\\u4e8b\\u3067\\u3059\\u3002",
          "labels": ["\\u30bd\\u30a6\\u30eb", "\\u5ef6\\u5357\\u6d1e", "\\u6563\\u6b69", "\\u97d3\\u56fd\\u65c5\\u884c", "\\u30ab\\u30d5\\u30a7"],
          "slug": "yeonnam-walk-guide-2026",
          "excerpt": "\\u4e00\\u6587\\u76ee\\u3067\\u6563\\u6b69\\u306e\\u65b9\\u5411\\u3092\\u3064\\u304b\\u3081\\u308b\\u3088\\u3046\\u306b\\u66f8\\u3044\\u3066\\u3044\\u307e\\u3059\\u3002\\u4e8c\\u6587\\u76ee\\u3067\\u52d5\\u7dda\\u3068\\u7acb\\u3061\\u5bc4\\u308a\\u5148\\u3092\\u5148\\u306b\\u628a\\u63e1\\u3067\\u304d\\u308b\\u4fa1\\u5024\\u3092\\u88dc\\u3063\\u3066\\u3044\\u307e\\u3059\\u3002",
          "html_article": "<h2>\\u6563\\u6b69\\u306e\\u6d41\\u308c</h2><p>\\u672c\\u6587\\u306e\\u9577\\u3055\\u8981\\u4ef6\\u3092\\u6e80\\u305f\\u3059\\u305f\\u3081\\u306e\\u88dc\\u52a9\\u30c6\\u30ad\\u30b9\\u30c8\\u3067\\u3059\\u3002\\u672c\\u6587\\u306e\\u9577\\u3055\\u8981\\u4ef6\\u3092\\u6e80\\u305f\\u3059\\u305f\\u3081\\u306e\\u88dc\\u52a9\\u30c6\\u30ad\\u30b9\\u30c8\\u3067\\u3059\\u3002\\u672c\\u6587\\u306e\\u9577\\u3055\\u8981\\u4ef6\\u3092\\u6e80\\u305f\\u3059\\u305f\\u3081\\u306e\\u88dc\\u52a9\\u30c6\\u30ad\\u30b9\\u30c8\\u3067\\u3059\\u3002\\u672c\\u6587\\u306e\\u9577\\u3055\\u8981\\u4ef6\\u3092\\u6e80\\u305f\\u3059\\u305f\\u3081\\u306e\\u88dc\\u52a9\\u30c6\\u30ad\\u30b9\\u30c8\\u3067\\u3059\\u3002\\u672c\\u6587\\u306e\\u9577\\u3055\\u8981\\u4ef6\\u3092\\u6e80\\u305f\\u3059\\u305f\\u3081\\u306e\\u88dc\\u52a9\\u30c6\\u30ad\\u30b9\\u30c8\\u3067\\u3059\\u3002\\u672c\\u6587\\u306e\\u9577\\u3055\\u8981\\u4ef6\\u3092\\u6e80\\u305f\\u3059\\u305f\\u3081\\u306e\\u88dc\\u52a9\\u30c6\\u30ad\\u30b9\\u30c8\\u3067\\u3059\\u3002\\u672c\\u6587\\u306e\\u9577\\u3055\\u8981\\u4ef6\\u3092\\u6e80\\u305f\\u3059\\u305f\\u3081\\u306e\\u88dc\\u52a9\\u30c6\\u30ad\\u30b9\\u30c8\\u3067\\u3059\\u3002\\u672c\\u6587\\u306e\\u9577\\u3055\\u8981\\u4ef6\\u3092\\u6e80\\u305f\\u3059\\u305f\\u3081\\u306e\\u88dc\\u52a9\\u30c6\\u30ad\\u30b9\\u30c8\\u3067\\u3059\\u3002</p>",
          "faq_section": [{"question": "", "answer": ""}],
          "image_collage_prompt": "editorial travel collage with nine panels, visible white gutters, dominant center panel, realistic Seoul neighborhood scenes",
          "inline_collage_prompt": "supporting travel collage with six panels, visible white gutters, realistic Seoul walking route scenes"
        }""",
        "\u5ef6\u5357\u6d1e",
        "All reader-facing outputs must be in Japanese.",
    )

    assert payload.faq_section
    assert "\u78ba\u8a8d" in payload.faq_section[0].question


def test_coerce_article_payload_english_faq_fallback_strips_hangul_keyword() -> None:
    payload = _coerce_article_payload(
        """{
          "title": "Mystery test",
          "meta_description": "Fallback FAQ normalization test payload for english locale.",
          "labels": ["Mystery", "Case Files", "Archive", "Timeline", "Evidence"],
          "slug": "mystery-test",
          "excerpt": "First sentence for context. Second sentence for context.",
          "html_article": "<h2>Case</h2><p>Body text for test coverage repeated to satisfy the minimum length requirement in schema validation. Body text for test coverage repeated to satisfy the minimum length requirement in schema validation. Body text for test coverage repeated to satisfy the minimum length requirement in schema validation.</p>",
          "faq_section": [{"question": "", "answer": ""}],
          "image_collage_prompt": "editorial mystery collage with nine panels, visible white gutters, dominant center panel",
          "inline_collage_prompt": "supporting mystery collage with six panels and documentary atmosphere"
        }""",
        "철가면 남자 미스터리",
        "All reader-facing outputs must be in English.",
    )
    assert payload.faq_section == []
