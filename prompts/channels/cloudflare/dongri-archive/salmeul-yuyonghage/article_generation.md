You are generating a complete Korean practical-life blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post that helps readers finish a real task, understand eligibility, or make a better everyday decision.

[Blog Style]
- Write like a useful Korean 생활 블로그, not a bureaucratic notice and not an audit report.
- Keep the tone clear, warm, and immediately actionable.
- Do not use score, checklist-for-score, or quality-diagnosis headings.

[Fact Safety]
- Never invent eligibility rules, support amounts, required documents, or deadlines.
- If policies can change, tell readers to verify with the official source.

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
- Cover: who this is for, what to prepare, how to do it step by step, mistakes to avoid, and what changes readers should expect.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5~7개
- excerpt: exactly 2 sentences
- image_collage_prompt: English daily-life 3x3 collage prompt with exactly 9 panels
- inline_collage_prompt: English supporting 3x2 daily-life collage prompt with exactly 6 panels

Return the final JSON now.
