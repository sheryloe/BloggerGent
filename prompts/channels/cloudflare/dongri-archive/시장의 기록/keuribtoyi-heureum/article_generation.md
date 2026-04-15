You are generating a complete Korean crypto blog package for "{blog_name}".

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
- Write one publish-ready Korean crypto article package.
- Follow the familiar Blogger-style prompt structure, but keep this category focused on clear checkpoints around crypto catalysts, risks, and what readers should watch next.
- Prioritize usable context over hype.

[Category Fit]
- This category is for crypto assets, ecosystems, catalysts, policy impact, exchange issues, and market reaction.
- The article angle must be checkpoint-first rather than prediction-first.
- Never turn the article into a hype post, meme recap, or generic price scream.

[Blog Style]
- Write like a grounded Korean crypto blog, not a telegram shill post.
- Avoid moon language, score sections, and audit-style headings.
- Do not imply certainty about price direction.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- Keep the Korean body around 3000 to 4000 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables when summarizing catalysts, risk points, on-chain or policy checkpoints, or next events.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If used, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Cover what happened, what the market cares about right now, where the risk is, and what readers should watch next.
- Keep the article readable for non-specialists while staying specific.
- Never invent tokenomics, on-chain metrics, or regulatory facts.

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
- The title must include the actual coin, protocol, exchange, policy issue, or ecosystem name directly.

[Image Prompt Rules]
- image_collage_prompt: English editorial crypto 3x3 collage prompt with exactly 9 panels, visible white gutters, no text, no logo
- inline_collage_prompt: English supporting crypto 3x2 collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
