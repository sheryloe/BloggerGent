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
        - Category: 개발과 프로그래밍 (`개발과-프로그래밍`).
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
        1. `dev-info-deep-dive` - Dev Info Deep Dive: 기술의 역사, 공식 문서 기반 정보, 전체 컨텍스트를 다루는 포괄적 가이드.
2. `dev-curation-top-points` - Dev Curation Top Points: 핵심 하이라이트 5가지를 선정해 실무 영향 중심으로 분석한다.
3. `dev-insider-field-guide` - Dev Insider Field Guide: 최적 설정, 타이밍, 트러블슈팅, 운영 팁을 담은 실전 마스터 가이드.
4. `dev-expert-perspective` - Dev Expert Perspective: 개발자 관점에서 기술적, 사회적 영향과 아키텍처 선택을 비평한다.
5. `dev-experience-synthesis` - Dev Experience Synthesis: 실제 삽질 경험과 감정적 서사가 결합된 기술 리뷰.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 개발 도구, AI 에이전트, 자동화, 배포, 관측성, 비용 통제, 실무 워크플로를 다룬다.
        - Tone: 실무 메모 + 개발자 해설. 과장된 생산성 찬양이나 입문 튜토리얼은 금지한다.

        [body_structure]
        - Markdown only. 첫 제목은 ##. ## 핵심 요약 포함. 마지막은 ## 마무리 기록.
        - `dev-info-deep-dive`: ## 핵심 요약 -> ## 배경과 변화 -> ## 공식 문서로 보는 핵심 -> ## 실무 적용 기준 -> ## 마무리 기록
- `dev-curation-top-points`: ## 핵심 요약 -> ## 지금 볼 5가지 포인트 -> ## 팀 워크플로 영향 -> ## 적용 우선순위 -> ## 마무리 기록
- `dev-insider-field-guide`: ## 핵심 요약 -> ## 실제 설정 기준 -> ## 자주 막히는 지점 -> ## 트러블슈팅 순서 -> ## 마무리 기록
- `dev-expert-perspective`: ## 핵심 요약 -> ## 기술적 의미 -> ## 아키텍처 관점 -> ## 팀 운영 관점 -> ## 마무리 기록
- `dev-experience-synthesis`: ## 핵심 요약 -> ## 직접 부딪힌 장면 -> ## 해결 과정 -> ## 남은 불편과 장점 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_prompt_policy]
        - 기술 문서, 개발 도구, 워크플로, 아키텍처 보드, 운영 대시보드 중심의 3x3 hero collage.
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
