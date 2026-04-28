[Category delta]
- Keep the article centered on one concrete workflow, routine, or field note that a Korean reader can use immediately.
- Turn vague observations into a clear practical takeaway with one main subject.
- Avoid meta blog talk and archive-introduction wording.

[Output reminders]
- All reader-facing text in the JSON body must be Korean.
- Keep html_article free of raw image tags.
- image_collage_prompt and inline_collage_prompt must be English realistic collage prompts.
- Return JSON only.

        [adsense_body_policy]
        - Do not output raw AdSense code inside `html_article`.
        - Forbidden in `html_article`: `<script`, `<ins class="adsbygoogle"`, `adsbygoogle`, `data-ad-client`, `data-ad-slot`, `ca-pub-`, `googlesyndication`, `doubleclick`, `<!--ADSENSE`, `[AD_SLOT`, and visible Korean text such as `?? ??`.
        - Do not invent AdSense client ids, slot ids, loader scripts, iframe widgets, ad labels, or visible ad placeholders.
        - Body ad placement is server-owned metadata only: `render_metadata.body_ads` is computed after generation and expanded by the public renderer.
        - Keep `html_article` as pure article content with no advertisement code or advertisement marker text.

