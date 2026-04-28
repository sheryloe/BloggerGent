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
        - Category: 동그리의 생각 (`동그리의-생각`).
        - Target body length: 3000+ Korean characters excluding markup.

        [minimum_korean_body_gate]
        - Hard gate: 순수 한글 본문 2000글자 이상. Count only complete Korean syllables `[가-힣]` after removing HTML, Markdown, code blocks, URLs, image captions, numbers, English, symbols, and spaces.
        - Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.
        - Keep the article useful to a real reader, not a system report.

        [adsense_body_policy]
        - Do not output raw AdSense code inside `html_article`.
        - Forbidden in `html_article`: `<script`, `<ins class="adsbygoogle"`, `adsbygoogle`, `data-ad-client`, `data-ad-slot`, `ca-pub-`, `googlesyndication`, `doubleclick`, `<!--ADSENSE`, `[AD_SLOT`, and visible Korean text such as `광고 위치`.
        - Do not invent AdSense client ids, slot ids, loader scripts, iframe widgets, ad labels, or visible ad placeholders.

        [allowed_article_patterns]
        1. `thought-social-context` - Social Context: 사회적 사건과 분위기를 맥락으로 해석한다.
2. `thought-tech-culture` - Tech Culture: 기술 변화가 사람과 문화에 미치는 영향을 읽는다.
3. `thought-generation-note` - Generation Note: 세대, 관계, 감정의 변화를 기록한다.
4. `thought-personal-question` - Personal Question: 개인적 질문으로 사회적 주제를 다시 본다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 사회 사건, 문화, 기술 트렌드, 관계와 감정을 동그리의 관점으로 해석한다.
        - Tone: 다크 라이브러리 톤. 단정 대신 맥락과 질문을 남긴다.

        [body_structure]
        - 문제 제기 -> 맥락 -> 놓치기 쉬운 것 -> 질문/실천 -> 마무리 기록.
        - `thought-social-context`: ## 문제를 다시 바라보기 -> ## 맥락과 변화 -> ## 우리가 놓치기 쉬운 것 -> ## 남은 질문 -> ## 마무리 기록
- `thought-tech-culture`: ## 기술이 만든 장면 -> ## 문화적 변화 -> ## 불편과 가능성 -> ## 마무리 기록
- `thought-generation-note`: ## 익숙한 장면 -> ## 세대의 감각 -> ## 달라진 관계 -> ## 마무리 기록
- `thought-personal-question`: ## 내가 붙잡은 질문 -> ## 장면과 배경 -> ## 생각의 방향 -> ## 마무리 기록

        [faq_policy]
        - Category default: none.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_asset_plan]
        - layout_policy: `hero_only_reflective_context`
- allowed_image_roles: `hero`
- `hero` is the representative image for every Cloudflare category.
- `inline_1` and `inline_2` are not allowed.
- Do not output `data-cf-image-slot`, `<!--CF_IMAGE_SLOT:*-->`, `<img>`, `<figure>`, or markdown images.
- `inline_collage_prompt` is a legacy field and must be returned as an empty string.

        [image_prompt_policy]
        - Reflective social note: dark library, observation scene, notebook, cultural context, unresolved question. Avoid infographic/report visuals.
        - Required visual anchors: social event, personal question, generation or culture context, observation scene, closing question.
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
