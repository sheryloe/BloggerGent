[Category delta]
- Build the article around one real festival, local event, seasonal field visit, or venue-based crowd situation.
- Focus on timing, route, queue, transport, food, stay, and on-site caution points.
- Make the article feel like field guidance, not a brochure.

[Length & Language Rule]
- **Target Length**: The article must be a minimum of **4,000 pure Korean characters** (excluding spaces and HTML tags).
- Pressure the AI to describe every detail, sensory experience, and professional tip to reach this length.

[Pattern Specification]
You must write according to the selected pattern (passed as `article_pattern_id`):
1. **`info-deep-dive`**: Comprehensive guide covering history, official info, and full context.
2. **`curation-top-points`**: Analyze top 5 highlights for maximum impact.
3. **`insider-field-guide`**: Practical master tips (best spots, timing, avoiding crowds).
4. **`expert-perspective`**: Artistic, cultural, or social analysis from an expert's viewpoint.
5. **`experience-synthesis`**: Emotional narrative combined with practical ratings/reviews.

[Output reminders]
- All reader-facing text in the JSON body must be Korean.
- Keep html_article free of raw image tags.
- Use ## and ### for headings. No # allowed.
- Final section must be ## 마무리 기록.
- image_collage_prompt and inline_collage_prompt must be English, describing a **MANDATORY 3x3 grid collage (9 panels)**.
- Return JSON only.

        [adsense_body_policy]
        - Do not output raw AdSense code inside `html_article`.
        - Forbidden in `html_article`: `<script`, `<ins class="adsbygoogle"`, `adsbygoogle`, `data-ad-client`, `data-ad-slot`, `ca-pub-`, `googlesyndication`, `doubleclick`, `<!--ADSENSE`, `[AD_SLOT`, and visible Korean text such as `?? ??`.
        - Do not invent AdSense client ids, slot ids, loader scripts, iframe widgets, ad labels, or visible ad placeholders.
        - Body ad placement is server-owned metadata only: `render_metadata.body_ads` is computed after generation and expanded by the public renderer.
        - Keep `html_article` as pure article content with no advertisement code or advertisement marker text.

