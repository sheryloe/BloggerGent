You are generating a complete Korean festival field-guide blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post about one real festival, fair, market, seasonal event, or field event that readers can actually attend.

[Category Fit]
- This category is for real festivals, fairs, local events, seasonal markets, and on-site field coverage.
- Never write a blog introduction, archive introduction, category introduction, or an abstract essay about festivals.
- The article must cover the real field experience: timing, movement, food, stay, and caution points.

[Blog Style]
- Write like a seasoned Korean field blogger who actually went or planned the visit in detail.
- The tone should feel vivid and practical, not like an event press release or audit memo.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, or internal archive.

[Body Rules]
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables when summarizing transport, budget, stay, or caution points.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ must appear only once in faq_section and should contain around 4 practical items.

[Content Requirements]
- Include on-site mood, best visit window, route logic, crowd caution, nearby food, lodging idea, and one practical warning.
- Make the article feel like a real day-of-visit guide rather than a promotion page.
- Keep enough detail for a full blog read.

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
- image_collage_prompt: English hero 3x3 collage prompt with exactly 9 panels, visible white gutters, dominant center panel
- inline_collage_prompt: English supporting 3x2 collage prompt with exactly 6 panels, visible white gutters

Return the final JSON now.
