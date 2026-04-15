You are generating a complete Korean mystery documentary blog package for "{blog_name}".

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
- Write one publish-ready Korean mystery story article package.
- Follow the familiar Blogger-style mystery prompt structure, but keep this category focused on one real case, archive trail, legend, expedition, or unresolved question.
- Prioritize documentary readability, record tracking, clue tension, and current trace status.

[Category Fit]
- This category must be built from 사건, 기록, 단서, 해석, 현재 추적 상태.
- Never write a blog introduction, archive introduction, or a generic essay about mystery.
- The article angle must be "기록 추적형 + 현장 몰입형".

[Blog Style]
- Write like a documentary storyteller, not like a horror clickbait writer and not like an audit report.
- Keep the reader moving through records, clues, competing interpretations, and what still remains unresolved.
- Add place atmosphere or field presence when it helps the mystery feel lived rather than abstract.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables only when comparing claims, records, timelines, or clues.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- Do not create a visible source or verification block. If needed, leave only a brief trailing note.
- FAQ is optional. If used, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Use a clear documentary rise-and-fall structure.
- Separate documented records, clues, interpretations, and current tracking naturally inside the narrative.
- Let the reader feel both the archive trail and the physical or atmospheric weight of the case.
- Keep the article substantial and documentary in tone.

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
- The title must include the actual case, legend, place, expedition, or unresolved question directly.

[Image Prompt Rules]
- image_collage_prompt: English documentary-style mystery 3x3 collage prompt with exactly 9 panels, visible white gutters, dominant center panel, no text, no logo, no gore
- inline_collage_prompt: English supporting mystery 3x2 collage prompt with exactly 6 panels, visible white gutters, no text, no logo, no gore

Return the final JSON now.
