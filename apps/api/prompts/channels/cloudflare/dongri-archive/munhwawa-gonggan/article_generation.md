You are generating a complete Korean culture blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post that helps readers decide whether the exhibition, popup, or culture space is worth visiting and how to experience it well.

[Blog Style]
- Write like a polished Korean Blogger post with atmosphere and practical value.
- Avoid report-style sections, score talk, or audit phrasing.
- Do not use headings like "점수 높이기", "체크리스트", or "품질 진단 결과".

[Fact Safety]
- Never invent dates, reservation rules, ticket prices, or operating policies.
- If details may change, tell readers to recheck the official page.

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
- Cover: what kind of place it is, why it matters now, what to see, how long to stay, reservation/waiting tips, photo or visit etiquette, and nearby spots.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5~7개
- excerpt: exactly 2 sentences
- meta_description: 130~160자 권장
- image_collage_prompt: English hero 3x3 collage prompt with exactly 9 panels, visible white gutters, and a dominant center panel
- inline_collage_prompt: English supporting 3x2 collage prompt with exactly 6 panels and visible white gutters

Return the final JSON now.
