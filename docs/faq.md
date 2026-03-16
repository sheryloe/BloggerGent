---
title: FAQ
---

# FAQ

## Is Bloggent fully automatic?

No.
Generation is automated, but public release is intentionally manual from the article review flow.

## Why not auto-publish everything?

Because Blogger posts are public-facing content.
The safer workflow is generate first, review second, publish third.

## Is the dashboard SEO number a full content score?

No.
The current dashboard label is a metadata verification state.
It reflects live checks for `description`, `og:description`, and `twitter:description`, not a complete body-quality evaluation.

## Why does Blogger SEO still need a theme patch?

Because Blogger API metadata fields do not reliably become the final public `<head>` tags.
The theme patch is the practical fallback that Bloggent can verify on the live page.

## Can different blogs use different prompts?

Yes.
That is one of the core design decisions.
Each imported blog has its own workflow and prompt configuration.

## Does Bloggent support only travel blogs?

No.
The current prompt system includes general, travel, and mystery-focused article generation paths.
The model is meant to support multiple blog identities through per-blog workflows.

## Can I use GitHub Pages with this project?

Yes.
The project supports GitHub Pages as an asset delivery target, and the `docs/` folder is also ready to be published as a GitHub Pages documentation site.

## What should I do if metadata verification stays weak?

Check these in order:

1. Is the article public yet?
2. Is the meta description clear and aligned with the article?
3. Was search description sync run?
4. Is the Blogger theme patch installed?
5. Did live verification run after publishing?
