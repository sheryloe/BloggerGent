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
        - Category: 크립토의 흐름 (`크립토의-흐름`).
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
        1. `crypto-cartoon-summary` - Cartoon Summary: 크립토 이슈를 만화식 요약으로 쉽게 정리한다.
2. `crypto-on-chain-analysis` - On-chain Analysis: 온체인 데이터와 거래 흐름을 중심으로 분석한다.
3. `crypto-protocol-deep-dive` - Protocol Deep Dive: 프로토콜 구조, 업그레이드, 생태계 변화를 설명한다.
4. `crypto-regulatory-macro` - Regulatory Macro: 규제와 거시 환경이 크립토에 미치는 영향을 분석한다.
5. `crypto-market-sentiment` - Market Sentiment: 심리, 뉴스, 유동성, 리스크 시나리오를 점검한다.

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - 비트코인, 이더리움, 알트코인, 온체인, 규제, 거래소, DeFi 흐름을 분석한다.
        - Tone: 하이프 금지. 가격 예측보다 사건, 유동성, 규제, 네트워크 업데이트를 구분한다.

        [body_structure]
        - 시장 요약 -> 주요 코인/사건 -> 온체인/규제 -> 리스크 -> 다음 지점.
        - `crypto-cartoon-summary`: ## 만화 요약 -> ## 크립토 시장 요약 -> ## 주요 사건 -> ## 마무리 기록
- `crypto-on-chain-analysis`: ## 시장 요약 -> ## 온체인 신호 -> ## 거래소/유동성 -> ## 마무리 기록
- `crypto-protocol-deep-dive`: ## 프로토콜 개요 -> ## 업데이트/구조 -> ## 생태계 영향 -> ## 마무리 기록
- `crypto-regulatory-macro`: ## 규제/거시 환경 -> ## 시장 반응 -> ## 리스크 -> ## 마무리 기록
- `crypto-market-sentiment`: ## 시장 심리 -> ## 주요 뉴스 -> ## 리스크 시나리오 -> ## 마무리 기록

        [faq_policy]
        - Category default: optional.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_asset_plan]
        - layout_policy: `hero_only_crypto_market`
- allowed_image_roles: `hero`
- `hero` is the representative image for every Cloudflare category.
- `inline_1` and `inline_2` are not allowed.
- Do not output `data-cf-image-slot`, `<!--CF_IMAGE_SLOT:*-->`, `<img>`, `<figure>`, or markdown images.
- `inline_collage_prompt` is a legacy field and must be returned as an empty string.

        [image_prompt_policy]
        - Crypto market image. Only crypto-cartoon-summary may use a cyber 12-panel cartoon; all other patterns use on-chain/protocol/regulatory analysis boards.
        - Required visual anchors: reference date, coin/protocol, price zone, on-chain or exchange signal, regulatory risk.
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
