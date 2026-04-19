[Input]
- Topic: {keyword}
- Current date: {current_date}
- Target audience: {target_audience}
- Blog focus: {content_brief}
- Planner brief:
{planner_brief}
- Editorial category key: {editorial_category_key}
- Editorial category label: {editorial_category_label}
- Editorial category guidance: {editorial_category_guidance}

[Mission]
- Write one publish-ready Korean blog article package for Dongri Archive.
- Make the article useful to a real reader, not a report, audit memo, score sheet, or prompt explanation.
- Use the planner brief, but do not expose planner wording or internal archive operations.

[Category Fit]
- Quick brief: {content_brief}
- Core focus: keep the topic inside this category and anchor it to one concrete subject.
- Key entities: include the specific places, tools, companies, events, records, or people needed for reader trust.
- Treat this file as an internal archive instruction source only. Do not write an internal archive introduction.
- This category is only for actual places, products, events, cases, entities, or decisions that a reader can understand concretely.

[Category delta]
- Center the article on one market move, sector shift, listed-company cluster, or investable theme.
- Explain what moved, why the market cared, what risk remains, and what to watch next.
- Stay calm and decision-first. Avoid trading-room hype.
- Keep the market story tied to one sector, listed-company cluster, flow, risk, and reader decision point.

[Blog Style]
- Use natural Korean blog prose with clear section flow.
- Keep the tone experiential and practical; avoid generic roundup language.
- Do not expose any internal helper phrases, prompt notes, planner labels, model names, or quality-control labels unless the topic itself requires them.
- Do not create standalone source, verification, audit, or score-report sections.

[Body Rules]
- Start with a reader-facing lead that explains why this topic matters now.
- Use <h2> and <h3> section headings that sound like real blog headings.
- The final body section title must be exactly <h2>마무리 기록</h2>.
- Do not output visible meta_description or excerpt lines inside html_article.
- Do not insert image tags inside html_article.
- Keep FAQ only as a short final appendix when it genuinely helps.

[Content Requirements]
- Quick brief, Core focus, and Key entities must be reflected in the article naturally.
- Include concrete dates, places, tools, companies, or route details when relevant.
- Explain tradeoffs, timing, risk, or reader action instead of listing abstract facts.
- Keep the article inside the category; do not write a category introduction or operations memo.
- Preserve reader trust without adding a separate source-audit block.

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
- article_pattern_id
- article_pattern_version

[Output Rules]
- All reader-facing text in title, meta_description, excerpt, html_article, and FAQ answers must be Korean.
- labels: 5 to 7 items, first label should match the editorial category label when natural.
- slug: lowercase ASCII with hyphens only.
- excerpt: exactly 2 Korean sentences.
- Return JSON only.

[Image Prompt Rules]
- image_collage_prompt must be English, realistic editorial collage direction, no text, no logo.
- inline_collage_prompt must be English, realistic supporting collage direction, no text, no logo.
- Keep image prompts grounded in the actual topic, not abstract symbolism.
