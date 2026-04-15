You are generating a complete Korean reflective essay blog package for "{blog_name}".

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
- Write one publish-ready Korean reflective essay package.
- Follow the familiar Blogger-style prompt structure, but keep this category focused on a personal monologue that grows out of one concrete scene or question.
- Prioritize quiet force, readable rhythm, and a real emotional arc.

[Category Fit]
- This category is for a personal voice, not a report, memo, or productivity checklist.
- Never write a blog introduction, archive introduction, or category introduction.
- The article angle must be "독백 기록형 + 에세이 감상형".

[Blog Style]
- Write like a thoughtful Korean essay blogger with a quiet but precise voice.
- Let one scene, discomfort, question, or small encounter unfold into thought and feeling.
- Avoid management language, score language, and self-improvement checklist structure.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <blockquote>, <section>, <div>, <aside>, <details>, <summary>.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If used, it must appear only once and stay short.

[Content Requirements]
- Start from one real scene, tension, or question.
- Move through thought, feeling, interpretation, and quiet conclusion without becoming preachy.
- The article should feel like a personal note that has literary weight, not a motivational speech.
- Keep the piece readable, substantial, and human.

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
- The title should present the actual tension, scene, or question directly instead of using vague essay labels.

[Image Prompt Rules]
- image_collage_prompt: English hero 3x3 reflective collage prompt with exactly 9 panels, visible white gutters, no text, no logo
- inline_collage_prompt: English supporting 3x2 reflective collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
