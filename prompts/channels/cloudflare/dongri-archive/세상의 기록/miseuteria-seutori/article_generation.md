        [minimum_korean_body_gate]

        [adsense_body_policy]
        - Do not output raw AdSense code inside `html_article`.
        - Forbidden in `html_article`: `<script`, `<ins class="adsbygoogle"`, `adsbygoogle`, `data-ad-client`, `data-ad-slot`, `ca-pub-`, `googlesyndication`, `doubleclick`, `<!--ADSENSE`, `[AD_SLOT`, and visible Korean text such as `?? ??`.
        - Do not invent AdSense client ids, slot ids, loader scripts, iframe widgets, ad labels, or visible ad placeholders.
        - Body ad placement is server-owned metadata only: `render_metadata.body_ads` is computed after generation and expanded by the public renderer.
        - Keep `html_article` as pure article content with no advertisement code or advertisement marker text.

        - Hard gate: 순수 한글 본문 2000글자 이상.
        - Count only complete Hangul syllables `[가-힣]` after removing HTML tags, Markdown syntax, code blocks, URLs, image alt/caption text, numbers, English, symbols, and whitespace.
        - Do not treat byte length, markup length, Markdown length, or whitespace-included string length as the passing standard.
        - Category target length can be higher, but any output below 2000 pure Korean body syllables must be considered invalid.
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
- Selected article pattern id: {article_pattern_id}

[Mission]
- Write one publish-ready Korean article package for Dongri Archive Cloudflare mystery channel.
- Category: ????? ???.
- The final visible body must target 3200~4200 plain-text Korean characters and must never fall below 3000 after HTML stripping and whitespace normalization.
- Keep the article useful to a real reader, not an internal system report.
- Do not expose planner wording, internal archive operations, scores, audits, prompts, or tool names.

[Allowed 5 Patterns Only]
1. case-timeline
   - ?? ??? ?? ???
2. evidence-breakdown
   - ??, ??, ??, ??? ??? ??
3. legend-context
   - ??, ??, ??, ?? ?? ??
4. scene-investigation
   - ?? ??, ??, ?? ?? ?? ??
5. scp-dossier
   - ?? ?? ??? ?? ??

[Pattern Rules]
- Use only one pattern.
- If article_pattern_id is provided and valid, follow it.
- If it is missing or invalid, choose the best one from the 5 allowed patterns.
- Return article_pattern_id and article_pattern_version.
- Return article_pattern_version = 3.

[Writing Rules]
- All reader-facing text must be Korean.
- Do not emit any body-level <h1>.
- Use 4 or 5 H2 sections. H3 is optional.
- Separate confirmed records, interpretations, and open questions in distinct blocks.
- FAQ must contain exactly 3 case-specific Q/A items.
- Labels: 4 to 6 items. First label must be ????? ???.
- Excerpt: exactly 2 sentences.
- Title policy:
  - Optimize for CTR and search intent.
  - Do not echo the raw topic string as a flat title.
  - Do not use templates like "[??] ????", "X ??", "???", "?? ??".
  - Make the reader understand why this case is worth opening now.
- Include a short sources/references block near the end when the topic is record-based.
- Use safe simple HTML only: h2, h3, p, ul, ol, li, blockquote, strong, em, a.
- Do not include img, iframe, script, style, table, or custom wrapper elements inside html_article.

[Image Rules]
- One hero image prompt only.
- No inline/body image requests.
- image_collage_prompt must describe one single flattened 5x4 panel grid collage image.
- Use visible white gutters and a clean grid layout.
- Keep it suitable for one 1024x1024 hero image.
- Do not ask for 20 separate images.

[Output]
Return one JSON object only with these keys:
- title
- meta_description
- excerpt
- labels
- html_article
- faq_section
- image_collage_prompt
- inline_collage_prompt: null
- article_pattern_id
- article_pattern_version

Return JSON only.
