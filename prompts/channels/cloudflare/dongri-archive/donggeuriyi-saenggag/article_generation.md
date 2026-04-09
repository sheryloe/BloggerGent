You are generating a complete Korean thought-piece blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post that starts from one clear scene, issue, or question and then explains what is happening, why people react that way, what pattern matters, and what takeaway remains.

[Blog Style]
- Write like a sharp Korean blog essay with practical observation.
- Keep the tone grounded, readable, and reflective.
- Do not write like a policy report, business memo, or quality audit.
- Do not use headings such as 체크리스트, 점수, 평가, 개선 과제, 진단 결과.

[Safety Rule]
- Do not invent survey data, official statements, or statistics.
- Distinguish facts from interpretation when certainty is limited.

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
- Cover: hook scene, issue definition, pattern reading, practical interpretation, closing takeaway.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5~7개
- excerpt: exactly 2 sentences
- image_collage_prompt: English editorial 3x3 collage prompt with exactly 9 panels
- inline_collage_prompt: English supporting 3x2 collage prompt with exactly 6 panels

Return the final JSON now.
