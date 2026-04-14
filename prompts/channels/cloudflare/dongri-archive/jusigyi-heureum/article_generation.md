You are generating a complete Korean stock-market blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post that explains one market theme or stock-market flow through a three-voice conversation.

[Category Fit]
- This category is for broader market flow, sector rotation, and stock context.
- Keep the A/B/C three-voice structure here.
- Do not use the Nasdaq-only two-voice format in this category.

[Blog Style]
- Write like a calm Korean market blog, not a trading room alert.
- Avoid sensational prediction headlines, audit wording, and score-style sections.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, or internal archive.

[Body Rules]
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <section>, <div>, <aside>, <blockquote>.
- Use a visible conversation structure with A, B, and C viewpoints.
- The final body section title must be exactly <h2>마무리 기록</h2>.

[Content Requirements]
- Cover what moved, why it mattered, what risks remain, and what to watch next.
- Keep the article substantial enough to exceed 5000 Korean characters without filler.

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

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5 to 7 items
- excerpt: exactly 2 sentences
- image_collage_prompt: English editorial market 3x3 collage prompt with exactly 9 panels
- inline_collage_prompt: English supporting market 3x2 collage prompt with exactly 6 panels

Return the final JSON now.
