You are generating a complete Korean Nasdaq stock blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post about one real Nasdaq-listed company using a two-voice dialogue.

[Category Fit]
- This category is only for one real Nasdaq-listed company at a time.
- Never write a blog introduction, archive introduction, category introduction, or a generic market recap.
- Use exactly two speakers: 동그리 and 햄니.
- 동그리 is aggressive. 햄니 is conservative.

[Blog Style]
- Both voices should sound informed by Wall Street style company analysis, industry trend reading, valuation pressure, and risk control.
- Keep the tone analytical but readable, not like a pump post and not like an audit memo.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, or internal archive.

[Body Rules]
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <section>, <div>, <aside>, <blockquote>.
- The article must be 4000 to 4500 Korean characters.
- Use a clear two-voice dialogue structure with bordered comparison tables where useful.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- Place the TradingView chart as the last visual block after the written analysis.

[Content Requirements]
- Cover why this ticker matters today, what the company actually does, recent trend drivers, upside case, downside case, risk checkpoints, and what to watch next.
- Include one compact bordered table for checkpoints or comparison.
- FAQ is optional. If included, keep it short and only once.

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
- labels: 5 to 7 items
- excerpt: exactly 2 sentences
- series_variant: "us-stock-dialogue-v1"
- chart_provider: "tradingview"
- chart_interval: "1D"
- slide_sections: 6 to 8 items for hybrid slide rendering
- image_collage_prompt: English editorial market 3x3 collage prompt with exactly 9 panels
- inline_collage_prompt: English supporting market 3x2 collage prompt with exactly 6 panels

Return the final JSON now.
