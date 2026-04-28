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
        - Category: 삶의 기름칠 (`삶의-기름칠`).
        - Minimum body length: 4000+ Korean characters excluding markup.
        - Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.
        - Keep the article useful to a real reader, not a system report.

        [allowed_article_patterns]
        1. `life-hack-tutorial` - Life Hack Tutorial: 생활비 절감이나 신청 절차를 단계별로 안내한다.
2. `benefit-audit-report` - Benefit Audit Report: 지원 제도의 자격, 금액, 실제 가치를 따진다.
3. `efficiency-tool-review` - Efficiency Tool Review: 신청/관리 도구, 앱, 조회 서비스를 리뷰한다.
4. `comparison-verdict` - Comparison Verdict: 비슷한 제도나 선택지를 비교해 결론을 준다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 정책, 지원금, 자격 조건, 신청 방법, 돈을 아끼는 제도를 이해하기 쉽게 정리한다.
        - Tone: 딱딱한 고지문이 아니라 누가, 언제, 무엇을 확인해야 하는지 먼저 말한다.

        [body_structure]
        - 대상 -> 조건 -> 신청 흐름 -> 놓치기 쉬운 지점 -> 마무리 기록.
        - `life-hack-tutorial`: ## 대상 확인 -> ## 신청 전 준비 -> ## 신청 순서 -> ## 확인할 것 -> ## 마무리 기록
- `benefit-audit-report`: ## 제도 개요 -> ## 자격 조건 -> ## 받을 수 있는 혜택 -> ## 주의점 -> ## 마무리 기록
- `efficiency-tool-review`: ## 도구 개요 -> ## 쓸모 있는 기능 -> ## 한계 -> ## 추천 대상 -> ## 마무리 기록
- `comparison-verdict`: ## 선택지 요약 -> ## 비교 기준 -> ## 상황별 결론 -> ## 신청 전략 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_prompt_policy]
        - 문서, 신청 화면, 상담, 자격 조건, 공공지원 안내가 보이는 신뢰감 있는 3x3 hero collage.
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

        [adsense_body_policy]
        - Do not output raw AdSense code inside `html_article`.
        - Forbidden in `html_article`: `<script`, `<ins class="adsbygoogle"`, `adsbygoogle`, `data-ad-client`, `data-ad-slot`, `ca-pub-`, `googlesyndication`, `doubleclick`, `<!--ADSENSE`, `[AD_SLOT`, and visible Korean text such as `?? ??`.
        - Do not invent AdSense client ids, slot ids, loader scripts, iframe widgets, ad labels, or visible ad placeholders.
        - Body ad placement is server-owned metadata only: `render_metadata.body_ads` is computed after generation and expanded by the public renderer.
        - Keep `html_article` as pure article content with no advertisement code or advertisement marker text.

