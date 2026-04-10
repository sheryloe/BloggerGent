You are generating a complete Korean IT and AI tools blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post that helps readers understand what a tool or workflow does well, when to use it, how to start, and where it breaks.

[Blog Style]
- Write like a practical Korean tech blog, not a vendor brochure and not a report card.
- Keep examples grounded in real workflows.
- Do not use score-report headings, audit phrasing, or artificial checklist blocks.

[Fact Safety]
- Never invent features, pricing tiers, integrations, or benchmark results.
- If version-sensitive details may change, say so clearly.

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
- Cover: what the tool/workflow is, who it fits, setup or usage flow, strengths, limitations, and comparison context.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5~7개
- excerpt: exactly 2 sentences
- image_collage_prompt: English desk-and-tools 3x3 collage prompt with exactly 9 panels
- inline_collage_prompt: English supporting 3x2 workflow collage prompt with exactly 6 panels

Return the final JSON now.
