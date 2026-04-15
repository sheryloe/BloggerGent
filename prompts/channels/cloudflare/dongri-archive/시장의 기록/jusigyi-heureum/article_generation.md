You are generating a complete Korean stock-market blog package for "{blog_name}".

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
- Write one publish-ready Korean stock-market blog article package.
- Follow the familiar Blogger-style prompt structure, but keep this category focused on clear market checkpoints and recent news context.
- Prioritize what moved, why the market cared, what risks remain, and what readers should check next.

[Category Fit]
- This category is for broader market flow, sector rotation, listed-company context, and investable themes.
- Do not use the Nasdaq-only two-voice format in this category.
- The article angle must balance "체크포인트형 + 뉴스 정리형".

[Blog Style]
- Write like a calm Korean market blog, not a trading-room alert or pump post.
- Avoid sensational prediction language, audit wording, and score-style sections.
- Keep the article readable for non-traders while still specific enough to be useful.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables when summarizing 핵심 변수, 실적 포인트, 일정, 뉴스, or 리스크.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If used, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Cover what moved, why it mattered, what recent news or events changed the tone, what risks remain, and what to watch next.
- Use checkpoints and comparison blocks when they help readers decide what matters now.
- Keep the article substantial without forcing exaggerated forecasts.

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
- The title must include the actual 시장 테마, 업종, 종목, or 핵심 변수 directly.

[Image Prompt Rules]
- image_collage_prompt: English editorial market 3x3 collage prompt with exactly 9 panels, visible white gutters, no text, no logo
- inline_collage_prompt: English supporting market 3x2 collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
