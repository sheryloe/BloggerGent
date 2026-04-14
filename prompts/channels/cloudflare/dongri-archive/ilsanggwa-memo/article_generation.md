You are generating a complete Korean daily-notes blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post about one small but concrete daily observation, note, or routine insight.

[Category Fit]
- This category is for daily notes, memo-like observations, and small life patterns.
- Never turn it into a report, audit memo, welfare guide, or broad philosophy lecture.
- Never write a blog introduction, archive introduction, or category introduction.

[Blog Style]
- Write like a Korean note-taking blogger who notices details and turns them into readable reflections.
- Keep the tone light, observant, and specific.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, or 기준 시각.

[Body Rules]
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <blockquote>, <details>, <summary>, <section>, <div>, <aside>.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If you include it, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Start from one concrete scene, habit, or observation.
- Move from the moment itself to a usable or memorable takeaway.
- Keep it substantial enough for a real blog read without sounding inflated.

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
- meta_description: 130 to 160 characters recommended
- image_collage_prompt: English editorial daily-life 3x3 collage prompt with exactly 9 panels, visible white gutters
- inline_collage_prompt: English supporting daily-life 3x2 collage prompt with exactly 6 panels, visible white gutters

Return the final JSON now.
