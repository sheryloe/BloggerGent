You are generating a complete Korean blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean SEO + GEO mystery article that is gripping, structured, and evidence-aware.

[Source Concept: Blogger Pair Pipeline]
- Treat this article as a Korean-localized reconstruction from 2 Blogger source posts (source pair).
- Keep verified facts and references stable, but reorganize narrative for Korean readers.
- Do not produce sentence-by-sentence translation tone.
- Explicitly show where two sources agree, diverge, and remain unverified.

[Output Contract]
Return one JSON object only with:
- title
- meta_description
- labels
- slug
- excerpt
- html_article
- faq_section
- image_collage_prompt
- inline_collage_prompt

[Body Image Rule]
- Do not insert raw image tags or markdown images in html_article.
- The system inserts one inline collage later.

[Accuracy Rule]
- Clearly separate documented facts, witness claims, later retellings, and unsupported lore.
- If the topic is fictional or SCP-related, say so explicitly.

[Trust Rule]
- Add one timestamp line near the top: "기준 시각: {current_date} (Asia/Seoul)".
- Include one section that separates "확인된 사실", "주장/증언", "미확인 추정".
- Include one "출처/확인 경로" section with 2~5개 concrete reference paths or official channels.
- If no concrete source URL is available, explicitly write: "확인 가능한 공식 URL 없음(작성 시점 기준)".
- Add one short note that the draft follows a 2-source pair pipeline from Blogger-origin records.

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5~7개
- excerpt: 1~2문장
- html_article tags: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>
- image_collage_prompt: English documentary hero 3x3 collage prompt with exactly 9 panels, visible white gutters, a dominant center panel, no gore, no text
- inline_collage_prompt: English documentary supporting 3x2 collage prompt with exactly 6 panels, visible white gutters, no gore, no text

Return the final JSON now.
