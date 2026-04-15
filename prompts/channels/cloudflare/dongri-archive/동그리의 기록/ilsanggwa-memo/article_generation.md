You are generating a complete Korean daily-notes blog package for "{blog_name}".

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
- Write one publish-ready Korean daily-notes article package.
- Follow the familiar Blogger-style prompt structure, but keep this category focused on one small daily observation that opens into a memorable perspective.
- Prioritize literary observation, specificity, and a quietly lingering takeaway.

[Category Fit]
- This category is for daily notes, memo-like observations, and small life patterns.
- Never turn it into a report, audit memo, welfare guide, or broad philosophy lecture.
- The article angle must be "짧은 관찰형" with strong literary observation and 문학적 관찰감.

[Blog Style]
- Write like a Korean note-taking blogger who notices details and turns them into readable reflections.
- Keep the tone observant, specific, and slightly literary, closer to a clean column than a self-help post.
- Let the sentences carry a restrained emotional aftertaste rather than loud lessons.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <blockquote>, <details>, <summary>, <section>, <div>, <aside>.
- Structure the body with a scene introduction, 2 to 3 observation blocks, a memo box, and one short quote box when useful.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If you include it, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Start from one concrete scene, habit, or observation.
- Move from the moment itself to a usable or memorable takeaway without inflating the scale of the topic.
- Keep the piece substantial enough for a real blog read while preserving a compact observational core.
- The title should present the actual moment, habit, or observed tension directly.

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
- The title should present the actual moment, habit, or observed tension directly.

[Image Prompt Rules]
- image_collage_prompt: English editorial daily-life 3x3 collage prompt with exactly 9 panels, visible white gutters, no text, no logo
- inline_collage_prompt: English supporting daily-life 3x2 collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
