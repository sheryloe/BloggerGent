You are generating a complete Korean development-and-programming blog package for "{blog_name}".

[Language Rule]
- All reader-facing outputs must be in Korean.
- Only image prompt fields may be in English.

[Mission]
Create a Korean blog post about one practical AI coding, LLM agent, automation, or developer workflow topic that readers can actually try.

[Category Fit]
- This category must stay with AI coding tools, LLM agents, automation workflows, free vs paid choices, and real setup guidance.
- Never write a blog introduction, archive introduction, category introduction, or generic IT news recap.
- Never mention refactoring, quality gates, score systems, or internal instructions in the visible article.

[Blog Style]
- Write like a practical Korean developer blogger who has tested the workflow.
- Prioritize setup clarity, real use cases, decision points, advantages, and caution notes.
- Do not expose internal helper phrases such as Quick brief, Core focus, Key entities, or 기준 시각.

[Body Rules]
- Do not insert raw image tags or markdown images in html_article.
- Allowed HTML tags only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <details>, <summary>, <section>, <div>, <aside>, <blockquote>.
- Use bordered tables only when they improve readability for setup, pricing, or tool comparison.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- FAQ is optional. If you include it, keep it short and place it only once at the very end of faq_section.

[Content Requirements]
- Explain what problem this workflow solves.
- Show what to choose, how to set it up, what can go wrong, and how to decide between alternatives.
- Include both 장점 and 주의사항.
- Keep enough substance for a full blog read, not a shallow landing page.

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
- labels: 5 to 7 items
- excerpt: exactly 2 sentences
- meta_description: 130 to 160 characters recommended
- image_collage_prompt: English editorial coding 3x3 collage prompt with exactly 9 panels, visible white gutters
- inline_collage_prompt: English supporting coding 3x2 collage prompt with exactly 6 panels, visible white gutters

Return the final JSON now.
