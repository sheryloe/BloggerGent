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
        - Category: 여행과 기록 (`여행과-기록`).
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
        1. `route-first-story` - Route First Story: 이동 순서와 시간대가 중심인 루트형 기록.
2. `spot-focus-review` - Spot Focus Review: 한 장소를 깊게 보고 방문 가치와 주의점을 정리한다.
3. `seasonal-special` - Seasonal Special: 계절, 축제, 날씨, 혼잡이 중요한 방문 기록.
4. `logistics-budget` - Logistics Budget: 교통, 예약, 비용, 동선 효율을 중심으로 정리한다.
5. `hidden-gem-discovery` - Hidden Gem Discovery: 덜 알려진 장소의 발견과 기록 가치를 정리한다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - Cloudflare 내부 여행 기록. Blogger Travel 운영과 분리한다. 장소, 동선, 시간, 비용, 현장 판단을 다룬다.
        - Tone: 여행 에세이가 아니라 독자가 움직일 수 있는 현장 기록.

        [body_structure]
        - 동선, 시간대, 비용, 혼잡, 지도 확인 포인트를 포함한다. 마지막은 <h2>마무리 기록</h2>.
        - `route-first-story`: ## 여행 개요 -> ## 이동 순서 -> ## 시간대별 기록 -> ## 현장 체크포인트 -> ## 마무리 기록
- `spot-focus-review`: ## 장소 개요 -> ## 볼만한 지점 -> ## 머무는 방법 -> ## 주의할 점 -> ## 마무리 기록
- `seasonal-special`: ## 계절 포인트 -> ## 추천 시간 -> ## 현장 분위기 -> ## 준비물 -> ## 마무리 기록
- `logistics-budget`: ## 이동과 예약 -> ## 비용 정리 -> ## 시간 절약법 -> ## 실패 줄이는 체크리스트 -> ## 마무리 기록
- `hidden-gem-discovery`: ## 발견한 이유 -> ## 숨어 있는 포인트 -> ## 가는 법 -> ## 기록할 장면 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_prompt_policy]
        - 국내 장소, 이동 동선, 현장 표지, 지도 노트, 사진 기록이 보이는 3x3 hero collage.
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
