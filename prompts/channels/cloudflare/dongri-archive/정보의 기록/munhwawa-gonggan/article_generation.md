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
        [minimum_korean_body_gate]

        [adsense_body_policy]
        - Do not output raw AdSense code inside `html_article`.
        - Forbidden in `html_article`: `<script`, `<ins class="adsbygoogle"`, `adsbygoogle`, `data-ad-client`, `data-ad-slot`, `ca-pub-`, `googlesyndication`, `doubleclick`, `<!--ADSENSE`, `[AD_SLOT`, and visible Korean text such as `?? ??`.
        - Do not invent AdSense client ids, slot ids, loader scripts, iframe widgets, ad labels, or visible ad placeholders.
        - Body ad placement is server-owned metadata only: `render_metadata.body_ads` is computed after generation and expanded by the public renderer.
        - Keep `html_article` as pure article content with no advertisement code or advertisement marker text.

        - Hard gate: 순수 한글 본문 2000글자 이상.
        - Count only complete Hangul syllables `[가-힣]` after removing HTML tags, Markdown syntax, code blocks, URLs, image alt/caption text, numbers, English, symbols, and whitespace.
        - Do not treat byte length, markup length, Markdown length, or whitespace-included string length as the passing standard.
        - Category target length can be higher, but any output below 2000 pure Korean body syllables must be considered invalid.
- Keep the article useful to a real visitor. This category is a culture-space guide, not a vague impression essay.
- Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.

[required_space_facts]
Every article must state these facts near the beginning of `html_article`:
- 전시명 또는 공간명
- 정확한 장소와 지역
- 운영 기간 또는 상설 여부
- 운영 시간 또는 관람 가능 시간
- 예약/입장 조건
- 추천 관람 시간대
- 관람 동선: 입구, 주요 구역, 작품/공간 흐름, 주변 연계
- 관람 리스크: 휴관일, 매진/예약, 촬영 제한, 혼잡 시간, 접근성

If the period is unknown, write `기간 미확인`. If the space is permanent, write `상설`. If official confirmation is needed, write `공식 확인 필요`. Do not present uncertain information as confirmed.

[allowed_article_patterns]
1. `info-deep-dive` - 공간/전시의 배경, 공식 정보, 기간, 장소, 전체 관람 맥락을 정리한다.
2. `curation-top-points` - 관람자가 집중해야 할 핵심 5가지에 기간, 장소, 예약, 동선, 관람 포인트를 포함한다.
3. `insider-field-guide` - 관람 순서, 추천 시간대, 예약, 사진 촬영, 혼잡 회피를 안내한다.
4. `expert-perspective` - 작품, 공간, 큐레이션을 문화적 관점으로 분석하되 기간과 장소 맥락을 놓치지 않는다.
5. `experience-synthesis` - 관람 경험과 실용 평가를 함께 정리한다.

[pattern_selection_rule]
- Use only one pattern from `allowed_article_patterns`.
- If `article_pattern_id` is provided and valid, follow it.
- If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
- Return `article_pattern_version = 4`.

[body_structure]
- Start with `## 핵심 요약` or the first pattern-specific H2. Never use body-level H1.
- `info-deep-dive`: `## 공간 개요` -> `## 기간과 장소` -> `## 관람 맥락` -> `## 추천 동선` -> `## 마무리 기록`
- `curation-top-points`: `## 핵심 요약` -> `## 관람 포인트 5가지` -> `## 놓치기 쉬운 장면` -> `## 시간과 예약` -> `## 마무리 기록`
- `insider-field-guide`: `## 관람 전 확인` -> `## 추천 동선` -> `## 시간과 예약 팁` -> `## 혼잡을 피하는 법` -> `## 마무리 기록`
- `expert-perspective`: `## 공간의 첫인상` -> `## 큐레이션의 의미` -> `## 작품을 보는 관점` -> `## 방문 판단 기준` -> `## 마무리 기록`
- `experience-synthesis`: `## 들어가며` -> `## 인상 깊은 장면` -> `## 좋았던 점과 아쉬운 점` -> `## 다시 간다면` -> `## 마무리 기록`

[faq_policy]
- Category default: optional.
- Add FAQ only when it helps with 기간, 위치, 예약, 관람 시간, 촬영, 혼잡 questions.
- Do not add FAQ just to fill space.

[image_prompt_policy]
- `image_collage_prompt` must be English.
- Cloudflare is hero-only: create one representative hero image prompt only.
- Include exhibition/cultural venue, entrance or route flow, artwork arrangement, visitor movement, lighting, and admission/reservation mood.
- Do not request body images, inline images, multiple generated assets, logos, readable text, or watermarks.

[forbidden_outputs]
- No body-level H1.
- Do not insert `<img>`, markdown images, scripts, iframes, or raw external widgets inside `html_article`.
- Do not include `meta_description` or `excerpt` visibly inside `html_article`.
- Do not mention Antigravity, Codex, Gemini, BloggerGent, pipeline, score, audit, or internal planner unless the topic itself is explicitly about those tools.
- Do not write uncertain period/place/admission information as confirmed.
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