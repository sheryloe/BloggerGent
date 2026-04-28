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
        - Category: 삶을 유용하게 (`삶을-유용하게`).
        - Target body length: 4000+ Korean characters excluding markup.

        [minimum_korean_body_gate]
        - Hard gate: 순수 한글 본문 2000글자 이상. Count only complete Korean syllables `[가-힣]` after removing HTML, Markdown, code blocks, URLs, image captions, numbers, English, symbols, and spaces.
        - Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.
        - Keep the article useful to a real reader, not a system report.

        [adsense_body_policy]
        - Do not output raw AdSense code inside `html_article`.
        - Forbidden in `html_article`: `<script`, `<ins class="adsbygoogle"`, `adsbygoogle`, `data-ad-client`, `data-ad-slot`, `ca-pub-`, `googlesyndication`, `doubleclick`, `<!--ADSENSE`, `[AD_SLOT`, and visible Korean text such as `광고 위치`.
        - Do not invent AdSense client ids, slot ids, loader scripts, iframe widgets, ad labels, or visible ad placeholders.

        [allowed_article_patterns]
        1. `life-hack-tutorial` - Life Hack Tutorial: 생활 문제를 해결하는 단계별 실용 가이드.
2. `benefit-audit-report` - Benefit Audit Report: 혜택/서비스의 자격, 가치, 신청 흐름을 점검한다.
3. `efficiency-tool-review` - Efficiency Tool Review: 생산성/생활 품질을 높이는 도구나 습관 리뷰.
4. `comparison-verdict` - Comparison Verdict: 여러 선택지를 비교해 독자에게 맞는 결론을 준다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 건강 습관, 앱 워크플로, 루틴 개선, 생활 효율을 실제 순서로 정리한다.
        - Tone: 실용적이고 경험 기반. 동기부여 문장보다 실행 순서를 우선한다.

        [body_structure]
        - 문제 -> 실행 순서 -> 비교/체크리스트 -> 적용 팁 -> 마무리 기록.
        - `life-hack-tutorial`: ## 문제 상황 -> ## 준비물 -> ## 실행 순서 -> ## 체크리스트 -> ## 마무리 기록
- `benefit-audit-report`: ## 혜택 개요 -> ## 대상과 조건 -> ## 실제 가치 -> ## 신청 체크 -> ## 마무리 기록
- `efficiency-tool-review`: ## 도구 개요 -> ## 써볼 만한 이유 -> ## 장점과 한계 -> ## 추천 대상 -> ## 마무리 기록
- `comparison-verdict`: ## 선택지 요약 -> ## 비교 기준 -> ## 상황별 추천 -> ## 최종 선택 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_asset_plan]
        - layout_policy: `hero_only_life_utility`
- allowed_image_roles: `hero`
- `hero` is the representative image for every Cloudflare category.
- `inline_1` and `inline_2` are not allowed.
- Do not output `data-cf-image-slot`, `<!--CF_IMAGE_SLOT:*-->`, `<img>`, `<figure>`, or markdown images.
- `inline_collage_prompt` is a legacy field and must be returned as an empty string.

        [image_prompt_policy]
        - Practical life utility: app/tool, routine, checklist, daily problem-solving scene. Welfare/government benefit topics must route to salmyi-gireumcil.
        - Required visual anchors: target user, tool or service, cost/benefit, preparation item, caution point.
        - `image_collage_prompt` must be English and must describe the `hero` role only.
        - Do not request logos, readable text, watermarks, unrelated category imagery, or fake official emblems.

        [forbidden_outputs]
        - No body-level H1.
        - Do not insert `<img>`, `<figure>`, markdown images, scripts, iframes, or raw external widgets inside `html_article`.
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
