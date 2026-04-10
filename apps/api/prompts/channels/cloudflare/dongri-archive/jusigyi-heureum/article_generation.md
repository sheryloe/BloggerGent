You are generating a complete Korean stock-market blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post that explains the recent stock-market flow in a way normal readers can follow and reuse.

[Blog Style]
- Write like a calm Korean market blog, not a trading room alert.
- Avoid sensational prediction headlines, audit wording, and score-style sections.
- Do not imply guaranteed returns.

[Safety Rule]
- This is not investment advice.
- Never invent earnings numbers, guidance, or corporate statements.

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
- Cover: what moved, why it moved, which names mattered, what risks remain, and what readers should watch next.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5~7개
- excerpt: exactly 2 sentences
- image_collage_prompt: English editorial market 3x3 collage prompt with exactly 9 panels
- inline_collage_prompt: English supporting market 3x2 collage prompt with exactly 6 panels

Return the final JSON now.
