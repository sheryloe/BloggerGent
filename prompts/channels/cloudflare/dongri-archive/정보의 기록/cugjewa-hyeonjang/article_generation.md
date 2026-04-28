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
        - Category: 축제와 현장 (`축제와-현장`).
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
        1. `info-deep-dive` - Info Deep Dive: 행사 배경, 공식 정보, 전체 맥락을 포괄적으로 정리한다.
2. `curation-top-points` - Curation Top Points: 방문자가 놓치지 말아야 할 핵심 5가지를 고른다.
3. `insider-field-guide` - Insider Field Guide: 최적 시간, 자리, 대기 회피, 준비물을 알려준다.
4. `expert-perspective` - Expert Perspective: 행사의 문화적/지역적 의미를 분석한다.
5. `experience-synthesis` - Experience Synthesis: 방문 경험과 실용 평가를 함께 정리한다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 실제 축제, 지역 행사, 계절 이벤트, 현장 동선과 준비를 다룬다.
        - Tone: 브로셔가 아니라 현장 가이드. 시간, 대기, 교통, 먹거리, 주의점 중심.

        [body_structure]
        - 행사 개요 -> 볼거리 -> 동선/시간 -> 현장 팁 -> 마무리 기록.
        - `info-deep-dive`: ## 행사 개요 -> ## 배경과 공식 정보 -> ## 현장 구성 -> ## 마무리 기록
- `curation-top-points`: ## 핵심 요약 -> ## 놓치면 아쉬운 5가지 -> ## 동선 팁 -> ## 마무리 기록
- `insider-field-guide`: ## 현장 기본 정보 -> ## 최적 시간과 위치 -> ## 대기 줄이는 법 -> ## 마무리 기록
- `expert-perspective`: ## 행사의 맥락 -> ## 문화적 의미 -> ## 현장에서 볼 지점 -> ## 마무리 기록
- `experience-synthesis`: ## 현장에 도착하며 -> ## 좋았던 점과 불편한 점 -> ## 다시 간다면 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_asset_plan]
        - layout_policy: `hero_plus_two_inline_event`
- allowed_image_roles: `hero`, `inline_1`, `inline_2`
- `hero` is the representative image for every Cloudflare category.
- `inline_1` and `inline_2` are allowed only through inert DOM slot placeholders.
- Use `<div class="cf-image-slot" data-cf-image-slot="inline_1"></div>` and `<div class="cf-image-slot" data-cf-image-slot="inline_2"></div>`; do not insert `<img>`, `<figure>`, markdown images, or comment-based image slots.
- `inline_1` must support route/access/viewing-flow explanation.
- `inline_2` must support highlight/risk/time-context explanation.
- `inline_collage_prompt` is a legacy field and must be returned as an empty string.

        [image_prompt_policy]
        - Festival/event field guide: hero for atmosphere, inline_1 for access/queue/route, inline_2 for time-of-day/risk/booth-stage context.
        - Required visual anchors: official site, venue, event period, operating hours, recommended visit time, access route, field risk.
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
