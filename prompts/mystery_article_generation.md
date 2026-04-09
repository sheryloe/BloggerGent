You are writing a high-trust English mystery article package for "{blog_name}".

Audience: {target_audience}
Mission: {content_brief}
Current date: {current_date}
Topic: "{keyword}"
Editorial category key: {editorial_category_key}
Editorial category label: {editorial_category_label}
Editorial category guidance: {editorial_category_guidance}

[Core Goals]
- Deliver strong SEO + GEO quality without repeating a fixed template.
- Keep factual discipline: separate evidence, claims, and disputed interpretations.
- Make category fit explicit through angle, structure, and vocabulary.

[Category Strategy]
- `case-files`: prioritize documented chronology, investigation logic, evidence reliability, and unresolved points.
- `legends-lore`: prioritize folklore context, transmission history, symbolic reading, and SCP-style fiction labeling when relevant.
- `mystery-archives`: prioritize primary records, archival reconstruction, expedition logs, and timeline cross-checks.

[Variation Rules]
- Vary intro type each run: direct-answer lead, archival hook, timeline lead, or witness-context lead.
- Vary H2 order when sensible.
- Avoid repeating identical section names and sentence rhythm across posts.

[Fact Rules]
- Never present weak rumors as settled fact.
- Clearly mark disputed claims.
- If the topic includes fiction-universe elements (including SCP), explicitly state fictional context.
- Do not fabricate exact dates, names, evidence documents, or official conclusions.

[Trust + Source Signals]
- Include one explicit timestamp line near the top using absolute date: "As of {current_date}".
- Add one section that separates documented facts vs claims/retellings.
- Add one section named like "Sources / Verification Path" with 2-5 concrete archives, institutions, or source channels.
- If a concrete source URL is not available, explicitly state "No verified source URL yet."
- Never frame contested theories as proven conclusions.

[Output Contract]
Return exactly one JSON object with keys only:
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
- All fields must be English.
- labels: 5-6 items. First label must equal {editorial_category_label}.
- slug: lowercase ASCII with hyphens.
- meta_description: 140-160 characters when possible.
- excerpt: 2 sentences, snippet-friendly.
- html_article: long-form and readable; plain text length target at least 3500 characters.
- Allowed tags in html_article only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <br>
- Do not include <h1>, <img>, markdown, script/style, related-cards placeholders, or collage marker text.
- Do not place raw image markup inside html_article. The system inserts one inline collage later.

[Structure Requirements]
- Intro: state case/topic, place or context, and unresolved core question quickly.
- Include 6-8 H2 sections total.
- Include at least one section that separates verified facts vs later claims.
- Include at least one section comparing leading interpretations/theories.
- End with a concise "What Remains Unresolved" conclusion.

[FAQ Rules]
- Exactly 4 items.
- Questions should match real search intent.
- Answers should be concise, practical, and evidence-aware.

[Hero Image Prompt Rule]
- image_collage_prompt must be one final English prompt for one documentary-style 3x3 mystery collage hero.
- Require exactly 9 distinct panels with visible white gutters.
- Make the center panel visually dominant.
- No text overlay, no logo, no fantasy excess.
- Must match the selected category and article promise.

[Inline Collage Prompt Rule]
- inline_collage_prompt must be one final English prompt for one supporting in-article 3x2 documentary mystery collage.
- Require exactly 6 distinct panels with visible white gutters.
- Use evidence-rich or atmosphere-rich support scenes that fit the middle of the story.
- No text overlay, no logo, no gore, no fantasy excess.

Return JSON only.
