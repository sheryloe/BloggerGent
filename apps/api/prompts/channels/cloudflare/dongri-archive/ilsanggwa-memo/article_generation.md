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
        - Category: 일상과 메모 (`일상과-메모`).
        - Minimum body length: 3000+ Korean characters excluding markup.
        - Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.
        - Keep the article useful to a real reader, not a system report.

        [allowed_article_patterns]
        1. `daily-01-reflective-monologue` - Reflective Monologue: 사유형 독백. 장면에서 질문으로 이어진다.
2. `daily-02-insight-memo` - Insight Memo: 일상에서 발견한 작은 통찰을 적용 가능한 메모로 정리한다.
3. `daily-03-habit-tracker` - Habit Tracker: 루틴, 습관, 반복 기록을 재현 가능한 순서로 정리한다.
4. `daily-04-emotional-reflection` - Emotional Reflection: 감정 회고를 구체적 장면과 문장으로 정리한다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 일상 장면을 기록하되 감상 나열로 끝내지 않고 생각과 실천으로 이어지는 메모형 글.
        - Tone: 조용한 관찰, 과장 없는 문장, 구체적인 생활 장면.

        [body_structure]
        - HTML body는 h2/h3/p 중심. FAQ 기본 금지. 마지막은 <h2>마무리 기록</h2>.
        - `daily-01-reflective-monologue`: ## 장면 -> ## 생각 -> ## 남은 질문 -> ## 마무리 기록
- `daily-02-insight-memo`: ## 장면 -> ## 문제를 다시 보기 -> ## 적용할 수 있는 통찰 -> ## 작은 체크리스트 -> ## 마무리 기록
- `daily-03-habit-tracker`: ## 장면 -> ## 루틴의 목적 -> ## 실행 순서 -> ## 작은 체크리스트 -> ## 마무리 기록
- `daily-04-emotional-reflection`: ## 장면 -> ## 감정의 흐름 -> ## 내가 붙잡은 문장 -> ## 실천 -> ## 마무리 기록

        [faq_policy]
        - Category default: none.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_prompt_policy]
        - 노트, 책상, 산책, 루틴, 창가, 감정 회고가 드러나는 조용한 3x3 hero collage.
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

