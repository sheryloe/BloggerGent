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
        - Category: 문화와 공간 (`문화와-공간`).
        - Minimum body length: 4000+ Korean characters excluding markup.
        - Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.
        - Keep the article useful to a real reader, not a system report.

        [allowed_article_patterns]
        1. `info-deep-dive` - Info Deep Dive: 공간/전시의 배경, 공식 정보, 전체 맥락을 정리한다.
2. `curation-top-points` - Curation Top Points: 관람자가 집중해야 할 핵심 5가지를 고른다.
3. `insider-field-guide` - Insider Field Guide: 관람 순서, 시간대, 예약, 포토존, 혼잡 회피를 안내한다.
4. `expert-perspective` - Expert Perspective: 작품, 공간, 큐레이션을 문화적 관점으로 분석한다.
5. `experience-synthesis` - Experience Synthesis: 관람 경험과 실용 평가를 함께 정리한다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 전시, 미술관, 갤러리, 팝업, 작가, 문화 공간을 관람 동선과 맥락으로 정리한다.
        - Tone: 공간과 작품을 보는 순서, 관람 포인트, 분위기를 설명한다.

        [body_structure]
        - 공간 개요 -> 관람 흐름 -> 대표 포인트 -> 방문 팁 -> 마무리 기록.
        - `info-deep-dive`: ## 공간 개요 -> ## 배경과 공식 정보 -> ## 관람 맥락 -> ## 마무리 기록
- `curation-top-points`: ## 핵심 요약 -> ## 관람 포인트 5가지 -> ## 놓치기 쉬운 장면 -> ## 마무리 기록
- `insider-field-guide`: ## 관람 전 확인 -> ## 추천 동선 -> ## 시간과 예약 팁 -> ## 마무리 기록
- `expert-perspective`: ## 공간의 첫인상 -> ## 큐레이션의 의미 -> ## 작품을 보는 관점 -> ## 마무리 기록
- `experience-synthesis`: ## 들어가며 -> ## 인상 깊은 장면 -> ## 좋았던 점과 아쉬운 점 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_prompt_policy]
        - 전시실, 갤러리, 작품 관람 흐름, 공간 조명, 관람자 동선 중심의 3x3 hero collage.
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

