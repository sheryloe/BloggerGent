You are generating a complete Korean mystery blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean documentary-style mystery article that is gripping, readable, and clear about what is fact, what is claim, and what remains unresolved.

[Blog Style]
- Write like a strong Korean mystery blog post, not a cold report.
- Keep the narrative immersive but controlled.
- Do not use audit-style headings, score language, or artificial "품질 개선" sections.

[Trust Rule]
- Separate documented facts, later claims, and unresolved points naturally inside the article.
- If the topic is fictional, SCP-related, or heavily dramatized, state that clearly.
- Never fabricate dates, institutions, evidence, or source provenance.

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

[Body Rules]
- Do not insert raw image tags or markdown images in html_article.
- Cover: 사건 개요, 핵심 타임라인, 주요 단서, 대표 가설, 왜 아직 회자되는지.
- End with a short concluding section that explains what still matters to readers now.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5~7개
- excerpt: exactly 2 sentences
- meta_description: 130~160자 권장
- image_collage_prompt: English documentary hero 3x3 collage prompt with exactly 9 panels, visible white gutters, a dominant center panel, no gore, no text
- inline_collage_prompt: English documentary supporting 3x2 collage prompt with exactly 6 panels, visible white gutters, no gore, no text

Return the final JSON now.
