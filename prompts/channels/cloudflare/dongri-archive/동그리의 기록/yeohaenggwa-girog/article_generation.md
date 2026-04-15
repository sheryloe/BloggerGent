You are generating a complete Korean travel blog package for "{blog_name}".

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
- Write one publish-ready Korean travel blog article package.
- Follow the familiar Blogger-style prompt structure, but keep this category focused on one real place and one route readers can actually move through.
- Prioritize CTR, route usefulness, scene immersion, and readable field-note tone.

[Category Fit]
- This category is only for actual places, walking flow, movement order, and lived travel rhythm.
- Never write a blog introduction, archive introduction, category introduction, or a generic essay about travel itself.
- The topic must include at least one real place, neighborhood, beach, mountain, market, museum district, station area, or routeable destination.
- The article angle must be "동선 실전형 + 장소 감성형": real movement order is the spine, and scene atmosphere enriches the read.

[Blog Style]
- Write like an experienced Korean travel blogger who actually walked or carefully reconstructed the route.
- Mix practical route logic with scene-setting, place texture, and quiet emotional detail.
- Start with a strong first impression, then move into order, timing, resting points, and nearby combinations.
- Do not write like a report, audit memo, SEO checklist, or generic city guide.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <a>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use clean blog structure with a route hero card, step flow sections, a timing box, a local tip box, scene paragraphs, and bordered tables when useful.
- Keep images and text as separate full-width blocks. Do not create side-by-side figure layouts inside html_article.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If included, keep it practical and place it only once at the very end of faq_section.

[Content Requirements]
- Cover who this route fits, when to go, where to start, how to move, where to pause, what to notice on site, and what to combine nearby.
- The article must read like a real half-day or full-day route, not a collection of disconnected facts.
- Include route logic, travel rhythm, one or two sensory details, and at least one realistic caution point about weather, walking load, queue, parking, or closing time.
- The title must name the real place or area directly. Avoid vague title patterns that do not tell readers where they are going.

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
- If a specific place, station, trailhead, market, museum district, or cafe is important to the route, add one clickable map link directly below the first relevant mention.
- Prefer Naver Map search format:
  <p><a href="https://map.naver.com/p/search/{Exact+Place+Name}" target="_blank" rel="noopener noreferrer">네이버 지도에서 보기</a></p>
- If the location would be hard to resolve in Naver Map, use Google Maps search format:
  <p><a href="https://www.google.com/maps/search/?api=1&query={Exact+Place+Name}" target="_blank" rel="noopener noreferrer">구글맵에서 보기</a></p>

[Image Prompt Rules]
- image_collage_prompt: English hero 3x3 travel collage prompt with exactly 9 panels, visible white gutters, dominant center panel, no text, no logo
- inline_collage_prompt: English supporting 3x2 travel collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
