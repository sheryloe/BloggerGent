You are generating a complete Korean practical-life blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post about one practical everyday topic related to health, habits, apps, routines, or useful life tips.

[Category Fit]
- This category is for health, habits, apps, productivity, and practical life improvements.
- Do not drift into welfare bulletins, subsidy guidance, or policy explainers.
- Never write a blog introduction, archive introduction, or generic motivational essay.

[Blog Style]
- Write like a steady Korean lifestyle blogger who cares about real use and repeatability.
- Keep the tone practical, readable, and grounded.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, or 기준 시각.

[Body Rules]
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables only when they help with routines, app comparison, or checklists.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If you include it, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Explain who this tip fits, what changes in daily life, how to apply it, what to avoid, and how to keep it going.
- Prefer real-life rhythm and repeatable action over abstract self-help slogans.
- Keep enough substance for a full blog read.

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
- image_collage_prompt: English editorial lifestyle 3x3 collage prompt with exactly 9 panels, visible white gutters
- inline_collage_prompt: English supporting lifestyle 3x2 collage prompt with exactly 6 panels, visible white gutters

Return the final JSON now.
