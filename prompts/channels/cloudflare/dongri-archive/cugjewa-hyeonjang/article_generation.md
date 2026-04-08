You are generating a complete Korean blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean SEO + GEO-ready article that helps readers decide whether to go, when to go, how to get there, and how to move through the place efficiently.

[Output Contract]
Return one JSON object only with these keys:
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

[Fact Rule]
- Never invent schedules, fees, transport changes, or opening hours.
- If uncertain, tell readers to recheck official information before visiting.

[Trust Rule]
- Add one timestamp line near the top: "기준 시각: {current_date} (Asia/Seoul)".
- Add one section that separates "확인된 사실" and "미확인 정보".
- Add one "출처/확인 경로" section with 2~5개의 공식 채널 또는 검증 경로.
- If no concrete source URL is available, explicitly write: "확인 가능한 공식 URL 없음(작성 시점 기준)".

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- meta_description: 130~160자
- labels: 5~7개
- excerpt: 정확히 2문장
- html_article tags: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>
- image_collage_prompt: English hero 3x3 collage prompt with exactly 9 panels, visible white gutters, and a dominant center panel
- inline_collage_prompt: English supporting 3x2 collage prompt with exactly 6 panels and visible white gutters

Return the final JSON now.
