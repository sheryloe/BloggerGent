You are generating a complete Korean culture-and-space blog package for "{blog_name}".

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
- Write one publish-ready Korean culture-and-space blog article package.
- Follow the familiar Blogger-style travel prompt structure, but keep this category focused on one real exhibition, artist, venue, or cultural space readers can actually visit.
- Prioritize CTR, viewing order clarity, representative works, and readable cultural interpretation.

[Category Fit]
- This category must stay with real exhibitions, artists, representative works, curatorial points, and viewing flow.
- Never write a blog introduction, archive introduction, or a vague article about how to enjoy culture.
- The article angle must be "관람 포인트형 + 작가/전문가 해설형".

[Blog Style]
- Write like a Korean culture blogger with strong field-guide instincts.
- Blend atmosphere with substance: why this space matters, who made the work, what to look at first, and how to move through the venue.
- If artist background is thin, strengthen the article with 큐레이터 or art-expert interpretation instead of leaving the read shallow.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <a>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables only when they improve readability for representative works, viewing points, artist notes, or visit planning.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional and should appear only once if used.

[Content Requirements]
- Include why this exhibition or space matters, artist or expert context, representative works or sections, viewing order, and practical visit tips.
- Keep the article grounded in one concrete venue, exhibition, or space.
- Make it feel like a real cultural field note, not a museum brochure.
- If a venue or gallery is hard to find, add one clickable map link below the first relevant mention using Naver Map first and Google Maps only when needed.

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
- The title must include the real venue, exhibition, or artist name directly.

[Image Prompt Rules]
- image_collage_prompt: English hero 3x3 culture collage prompt with exactly 9 panels, visible white gutters, dominant center panel, no text, no logo
- inline_collage_prompt: English supporting 3x2 culture collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
