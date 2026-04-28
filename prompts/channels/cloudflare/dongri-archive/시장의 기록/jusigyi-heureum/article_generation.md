[Input]
        - Topic: {keyword}
        - Current date: {current_date}
        - Target audience: {target_audience}
        - Blog focus: {content_brief}
        - Planner brief:
        {planner_brief}
        - Editorial category key: {editorial_category_key}
        - Editorial category label: {editorial_category_label}
        - Editorial category guidance: {editorial_category_guidance}
        - Selected article pattern id: {article_pattern_id}

        [Mission]
        - Write one publish-ready Korean article package for Dongri Archive Cloudflare channel.
        - Category: 주식의 흐름 (`주식의-흐름`).
        - Minimum body length: 4000+ Korean characters excluding markup.
        [minimum_korean_body_gate]
        - Hard gate: 순수 한글 본문 2000글자 이상.
        - Count only complete Hangul syllables `[가-힣]` after removing HTML tags, Markdown syntax, code blocks, URLs, image alt/caption text, numbers, English, symbols, and whitespace.
        - Do not treat byte length, markup length, Markdown length, or whitespace-included string length as the passing standard.
        - Category target length can be higher, but any output below 2000 pure Korean body syllables must be considered invalid.

        [adsense_body_policy]
        - Do not output raw AdSense code inside `html_article`.
        - Forbidden in `html_article`: `<script`, `<ins class="adsbygoogle"`, `adsbygoogle`, `data-ad-client`, `data-ad-slot`, `ca-pub-`, `googlesyndication`, `doubleclick`, `<!--ADSENSE`, `[AD_SLOT`, and visible Korean text such as `?? ??`.
        - Do not invent AdSense client ids, slot ids, loader scripts, iframe widgets, ad labels, or visible ad placeholders.
        - Body ad placement is server-owned metadata only: `render_metadata.body_ads` is computed after generation and expanded by the public renderer.
        - Keep `html_article` as pure article content with no advertisement code or advertisement marker text.
        - Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.
        - Keep the article useful to a real reader, not a system report.

        [allowed_article_patterns]
        1. `stock-cartoon-summary` - Cartoon Summary: 시장 이슈를 만화식 요약으로 쉽게 풀어낸다.
2. `stock-technical-analysis` - Technical Analysis: 가격 흐름과 기술적 구간을 정리한다.
3. `stock-macro-intelligence` - Macro Intelligence: 금리, 물가, 정책, 지표가 시장에 미치는 영향을 본다.
4. `stock-corporate-event-watch` - Corporate Event Watch: 실적, 이벤트, 기업 뉴스 중심 분석.
5. `stock-risk-timing` - Risk Timing: 진입/관망/리스크 타이밍을 정리한다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 글로벌 증시, 섹터, 기업 실적, 투자심리, 정책 변수를 분석한다.
        - Tone: 투자 조언이 아니라 시장 관찰과 리스크 정리.

        [body_structure]
        - 시장 요약 -> 주요 뉴스/지표 -> 섹터 관찰 -> 리스크 -> 다음 일정.
        - `stock-cartoon-summary`: ## 만화 요약 -> ## 오늘의 시장 흐름 -> ## 주요 이슈 -> ## 마무리 기록
- `stock-technical-analysis`: ## 오늘의 시장 흐름 -> ## 기술적 구간 -> ## 확인할 지표 -> ## 마무리 기록
- `stock-macro-intelligence`: ## 거시 환경 -> ## 시장 반응 -> ## 투자심리 -> ## 마무리 기록
- `stock-corporate-event-watch`: ## 기업 이벤트 -> ## 실적/뉴스 포인트 -> ## 리스크 -> ## 마무리 기록
- `stock-risk-timing`: ## 현재 위치 -> ## 리스크 신호 -> ## 확인할 일정 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_prompt_policy]
        - 패턴1은 12컷 만화형, 나머지는 금융 리포트형 3x3 hero collage.
        - `image_collage_prompt` must be English.
        - Cloudflare is hero-only: create one representative hero image prompt only.
        - Do not request body images, inline images, multiple generated assets, logos, readable text, or watermarks.

        [forbidden_outputs]
        - No body-level H1.
        - Do not insert `<img>`, markdown images, scripts, iframes, or raw external widgets inside `html_article`.
        - Do not include `meta_description` or `excerpt` visibly inside `html_article`.
        - Do not mention Antigravity, Codex, Gemini, BloggerGent, pipeline, score, audit, or internal planner unless the topic itself is explicitly about those tools.
        - Do not move outside the category topic just because the keyword is broad.

        [Output JSON]
        Return valid JSON only with these fields:
        - title
        - meta_description
        - excerpt
        - labels
        - html_article
        - faq_section
        - image_collage_prompt
        - inline_collage_prompt: return an empty string
        - article_pattern_id
        - article_pattern_version
