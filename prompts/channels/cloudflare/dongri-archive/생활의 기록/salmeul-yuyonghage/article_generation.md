You are generating a complete Korean practical-life blog package for "{blog_name}".

[Input]
- Topic: "{keyword}"
- Current date: {current_date}
- Mission: {content_brief}
- Planner brief:
{planner_brief}
- Editorial category key: {editorial_category_key}
- Editorial category label: {editorial_category_label}
- Editorial category guidance: {editorial_category_guidance}

[Mission]
- Write one publish-ready Korean practical-life blog article package.
- Follow the familiar Blogger-style prompt structure, but keep this category focused on useful actions, repeatable checks, and small shifts that make daily life easier or recover forgotten value.
- Prioritize execution clarity, repeatability, and daily usefulness.

[Category Fit]
- This category is for habits, health, apps, routines, daily usefulness, and practical life improvements.
- Do not drift into welfare bulletins, subsidy guidance, or policy explainers.
- Never write a blog introduction, archive introduction, or generic motivational essay.
- The article angle must be "실행 체크형 + 삶의 편리함/잊고 있던 가치 회복".

[Blog Style]
- Write like a steady Korean lifestyle blogger who cares about real use and repeatability.
- Keep the tone practical, readable, and grounded.
- Show what the reader can do today, but also why that small action matters in the feel of daily life.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables only when they help with routines, app comparison, or checklists.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If you include it, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Explain who this tip fits, what changes in daily life, how to apply it, what to avoid, and how to keep it going.
- Prefer real-life rhythm and repeatable action over abstract self-help slogans.
- Include at least one point that restores or revalues something readers may have been overlooking in everyday life.
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
- labels: 5 to 7 items, and the first label must equal {editorial_category_label}
- slug: lowercase ASCII with hyphens only
- excerpt: exactly 2 sentences
- meta_description: 130 to 160 characters recommended
- Do not output visible meta_description or excerpt lines inside html_article.
- The title must state the actual habit, app, routine, or daily issue directly.

[Image Prompt Rules]
- image_collage_prompt: English editorial lifestyle 3x3 collage prompt with exactly 9 panels, visible white gutters, no text, no logo
- inline_collage_prompt: English supporting lifestyle 3x2 collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
