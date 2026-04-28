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
        - Category: 나스닥의 흐름 (`나스닥의-흐름`).
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
        1. `nasdaq-technical-deep-dive` - Technical Deep Dive: 가격 흐름과 기술적 구간을 정밀하게 본다.
2. `nasdaq-macro-impact` - Macro Impact: 금리, 달러, 실적 시즌, AI 투자 사이클 영향을 분석한다.
3. `nasdaq-big-tech-whale-watch` - Big Tech Whale Watch: 빅테크와 대형 자금 흐름을 추적한다.
4. `nasdaq-hypothesis-scenario` - Hypothesis Scenario: 상승/하락/횡보 시나리오를 나누어 본다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 나스닥 상장 기업, AI, 반도체, 클라우드, 플랫폼 기업, 실적, 밸류에이션을 분석한다.
        - Tone: 개별 기업과 섹터를 실적/사업/리스크로 나누어 본다.

        [body_structure]
        - 기업/섹터 개요 -> 최근 흐름 -> 핵심 관찰 포인트 -> 리스크 -> 다음 체크리스트.
        - `nasdaq-technical-deep-dive`: ## 기업/섹터 개요 -> ## 기술적 흐름 -> ## 확인할 구간 -> ## 마무리 기록
- `nasdaq-macro-impact`: ## 거시 환경 -> ## 기업 영향 -> ## 밸류에이션 변수 -> ## 마무리 기록
- `nasdaq-big-tech-whale-watch`: ## 대형주 흐름 -> ## 자금과 뉴스 -> ## 리스크 -> ## 마무리 기록
- `nasdaq-hypothesis-scenario`: ## 현재 위치 -> ## 시나리오별 조건 -> ## 확인할 변수 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_asset_plan]
        - layout_policy: `hero_only_nasdaq_infographic`
- allowed_image_roles: `hero`
- `hero` is the representative image for every Cloudflare category.
- `inline_1` and `inline_2` are not allowed.
- Do not output `data-cf-image-slot`, `<!--CF_IMAGE_SLOT:*-->`, `<img>`, `<figure>`, or markdown images.
- `inline_collage_prompt` is a legacy field and must be returned as an empty string.

        [image_prompt_policy]
        - Nasdaq infographic or market analysis board: AI, semiconductor, earnings, guidance, rate/macro context, risk scenario. New rotation must not use cartoon style.
        - Required visual anchors: reference date, company/sector, earnings or guidance, AI/semiconductor context, risk scenario.
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
