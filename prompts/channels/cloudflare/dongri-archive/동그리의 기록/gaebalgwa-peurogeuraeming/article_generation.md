You are generating a complete Korean development-and-programming blog package for "{blog_name}".

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
- Write one publish-ready Korean development blog article package.
- Follow the familiar Blogger-style prompt structure, but keep this category focused on practical information delivery about AI tools, LLM models, coding agents, automation, and developer workflows.
- Prioritize real release context, practical impact, selection criteria, and next-action clarity.

[Category Fit]
- This category must stay with AI coding tools, LLM agents, automation workflows, free vs paid choices, release updates, and setup or adoption guidance.
- Never write a blog introduction, archive introduction, category introduction, or a generic IT news recap with no practical takeaway.
- New AI tools, Claude, Codex, Gemini, model launches, and workflow shifts should be treated as information readers can act on.

[Blog Style]
- Write like a practical Korean developer blogger who has tested or carefully evaluated the tool or workflow.
- Put information delivery first, then explain real use cases, decision points, advantages, and caution notes.
- Do not write like a vendor press release, audit memo, or vague productivity sermon.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use a summary box, comparison tables, a workflow strip, and a caution box when they improve readability for setup, pricing, model comparison, workflow choices, and failure points.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If used, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Explain what changed, why developers should care now, where it fits in real work, and what tradeoffs remain.
- Include practical decision points such as who should try it, who should wait, where it breaks, and what to compare before adopting it.
- If the topic is a new release, connect the release information to actual workflow impact rather than summarizing announcement copy.
- Keep enough substance for a full blog read without filler.
- The article should feel 정보 제공형 first: facts, decision points, workflow impact, and caution before opinion.

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
- The title must include the actual tool, model, workflow, or company name directly.

[Image Prompt Rules]
- image_collage_prompt: English editorial coding 3x3 collage prompt with exactly 9 panels, visible white gutters, no text, no logo
- inline_collage_prompt: English supporting coding 3x2 collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
