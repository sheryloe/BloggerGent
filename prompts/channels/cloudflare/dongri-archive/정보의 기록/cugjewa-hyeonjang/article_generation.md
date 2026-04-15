You are generating a complete Korean festival and field-guide blog package for "{blog_name}".

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
- Write one publish-ready Korean festival or field-event blog article package.
- Follow the familiar Blogger-style travel prompt structure, but keep this category centered on real event operations and a nearby course readers can actually use.
- Prioritize CTR, visit logistics, movement order, food and stay choices, and timing clarity.

[Category Fit]
- This category is for real festivals, fairs, local events, seasonal markets, night events, and field coverage readers can actually attend.
- Never write a blog introduction, archive introduction, category introduction, or an abstract essay about festivals.
- The article angle must be "현장 운영형 + 지역 코스형": how to go, how to move, what to eat, where to stay, and when to leave.

[Blog Style]
- Write like a seasoned Korean field blogger who either visited or planned the day in detail.
- Keep the tone vivid and practical, not like an event press release or audit memo.
- Make the reader feel guided through arrival, on-site choices, nearby food, and the way back home.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <a>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables when summarizing transport, budget, stay, food timing, or caution points.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ must appear only once in faq_section and should stay practical.

[Content Requirements]
- Include how to get there, best arrival window, movement order, crowd caution, nearby food, lodging idea, and return timing.
- If the event spreads across multiple zones, make the route logic explicit.
- The article must feel like a real day-of-visit guide, not a promotion page.
- Add one map link when a venue, station, food stop, or lodging anchor is important to the route.
- Prefer Naver Map search format first:
  <p><a href="https://map.naver.com/p/search/{Exact+Place+Name}" target="_blank" rel="noopener noreferrer">네이버 지도에서 보기</a></p>
- If Naver Map would be hard to resolve, use Google Maps:
  <p><a href="https://www.google.com/maps/search/?api=1&query={Exact+Place+Name}" target="_blank" rel="noopener noreferrer">구글맵에서 보기</a></p>

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
- The title must include the real event, festival, market, or field name directly.

[Image Prompt Rules]
- image_collage_prompt: English hero 3x3 festival collage prompt with exactly 9 panels, visible white gutters, dominant center panel, no text, no logo
- inline_collage_prompt: English supporting 3x2 festival collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
