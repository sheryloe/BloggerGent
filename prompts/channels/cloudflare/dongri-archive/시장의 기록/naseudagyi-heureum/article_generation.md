You are generating a complete Korean Nasdaq stock blog package for "{blog_name}".

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
- Write one publish-ready Korean Nasdaq stock article package.
- Follow the familiar Blogger-style prompt structure, but keep this category focused on a two-voice analysis of one real Nasdaq-listed company.
- Prioritize 티키타카 dialogue, company analysis depth, risk checkpoints, and chart-linked readability.

[Category Fit]
- This category is only for one real Nasdaq-listed company at a time.
- Never write a blog introduction, archive introduction, category introduction, or a generic market recap.
- Use exactly two speakers: 동그리 and 햄니.
- 동그리 is aggressive. 햄니 is conservative.
- The article must feel like "2인 티키타카 분석형" rather than a dry report.

[Blog Style]
- Both voices should sound informed by Wall Street style company analysis, industry trend reading, valuation pressure, and risk control.
- Keep the tone analytical but lively. The back-and-forth must feel real, not like two separate monologues pasted together.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, 기준 시각, or internal archive.

[Body Rules]
- The Korean body must be 4000 to 4500 characters.
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use a clear two-voice dialogue structure with bordered comparison tables where useful.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- Place the TradingView chart as the last visual block after the written analysis.
- FAQ is optional. If included, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Cover why this ticker matters today, what the company actually does, recent trend drivers, upside case, downside case, risk checkpoints, and what to watch next.
- Include one compact bordered table for checkpoints or comparison.
- Keep the dialogue tight and responsive so the two voices genuinely react to each other.

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
- series_variant
- company_name
- ticker
- exchange
- chart_provider
- chart_symbol
- chart_interval
- slide_sections

[Output Rules]
- title/meta_description/labels/excerpt/html_article/faq_section: Korean
- labels: 5 to 7 items, and the first label must equal {editorial_category_label}
- slug: lowercase ASCII with hyphens only
- excerpt: exactly 2 sentences
- meta_description: 130 to 160 characters recommended
- Do not output visible meta_description or excerpt lines inside html_article.
- The title must include the actual company name and ticker directly.
- series_variant: "us-stock-dialogue-v1"
- chart_provider: "tradingview"
- chart_interval: "1D"
- slide_sections: 6 to 8 items for hybrid slide rendering

[Image Prompt Rules]
- image_collage_prompt: English editorial market 3x3 collage prompt with exactly 9 panels, visible white gutters, no text, no logo
- inline_collage_prompt: English supporting market 3x2 collage prompt with exactly 6 panels, visible white gutters, no text, no logo

Return the final JSON now.
