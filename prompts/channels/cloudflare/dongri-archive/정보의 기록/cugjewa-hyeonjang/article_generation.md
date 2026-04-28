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
- Keep the article useful to a real visitor. This category is a field guide, not a mood essay.
- Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.

[required_event_facts]
Every article must state these facts near the beginning of `html_article`:
- 행사명 또는 축제명
- 개최 장소와 정확한 지역
- 개최 기간
- 운영 시간 또는 주요 프로그램 시간
- 가장 혼잡한 시간대
- 추천 방문 시간대
- 접근 동선: 대중교통, 주차, 입구, 이동 순서
- 현장 리스크: 대기줄, 우천, 야간 이동, 매진/예약, 교통 통제

If the period is unknown, write `기간 미확인` or `공식 확인 필요`. If the event has already ended, write it as `방문 기록` or `다음 회차 참고`, never as if it is currently running.

[allowed_article_patterns]
1. `info-deep-dive` - 기간, 장소, 공식 정보, 행사 배경, 운영 구성을 전체 맥락으로 정리한다.
2. `curation-top-points` - 방문 전 확인할 핵심 5가지에 기간, 장소, 시간, 교통, 현장 리스크를 포함한다.
3. `insider-field-guide` - 최적 방문 시간, 입장 위치, 대기 회피, 교통, 준비물 중심의 현장 가이드다.
4. `expert-perspective` - 행사와 지역 문화의 의미를 기간, 장소, 운영 방식과 연결해 분석한다.
5. `experience-synthesis` - 방문 흐름, 시간대별 체감, 다시 간다면 바꿀 점을 정리한다.

[pattern_selection_rule]
- Use only one pattern from `allowed_article_patterns`.
- If `article_pattern_id` is provided and valid, follow it.
- If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
- Return `article_pattern_version = 4`.

[body_structure]
- Start with `## 핵심 요약` or the first pattern-specific H2. Never use body-level H1.
- `info-deep-dive`: `## 행사 개요` -> `## 기간과 장소` -> `## 현장 구성` -> `## 방문 동선` -> `## 마무리 기록`
- `curation-top-points`: `## 핵심 요약` -> `## 놓치면 아쉬운 5가지` -> `## 시간대별 방문 전략` -> `## 이동과 대기` -> `## 마무리 기록`
- `insider-field-guide`: `## 현장 기본 정보` -> `## 최적 시간과 위치` -> `## 대기 줄이는 법` -> `## 교통과 준비물` -> `## 마무리 기록`
- `expert-perspective`: `## 행사의 맥락` -> `## 장소가 만드는 의미` -> `## 현장에서 볼 지점` -> `## 방문 판단 기준` -> `## 마무리 기록`
- `experience-synthesis`: `## 현장에 들어서며` -> `## 시간대별 체감` -> `## 좋았던 점과 불편했던 점` -> `## 다시 간다면` -> `## 마무리 기록`

[faq_policy]
- Category default: optional.
- Add FAQ only when it helps with 일정, 교통, 입장, 준비물, 우천, 예약 questions.
- Do not add FAQ just to fill space.

[image_prompt_policy]
- `image_collage_prompt` must be English.
- Cloudflare is hero-only: create one representative hero image prompt only.
- Include event scene, visitor route, queue, booth/stage, entrance/transport, and time-of-day mood.
- Do not request body images, inline images, multiple generated assets, logos, readable text, or watermarks.

[forbidden_outputs]
- No body-level H1.
- Do not insert `<img>`, markdown images, scripts, iframes, or raw external widgets inside `html_article`.
- Do not include `meta_description` or `excerpt` visibly inside `html_article`.
- Do not mention Antigravity, Codex, Gemini, BloggerGent, pipeline, score, audit, or internal planner unless the topic itself is explicitly about those tools.
- Do not write an event as currently available unless the period is confirmed.
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