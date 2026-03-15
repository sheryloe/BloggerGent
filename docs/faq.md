---
title: FAQ
---

# FAQ

## Is Bloggent fully automatic?

No.
Generation is automated, but public release is intentionally manual from the article list.

## Why not auto-publish everything?

Because Blogger posts are public-facing content.
The safest workflow is generate first, review second, publish third.

## Why is SEO metadata handled with a theme patch?

Because Blogger API metadata fields do not reliably turn into real public `<head>` tags.
The theme patch is the practical fallback that Bloggent can actually verify.

## Can different blogs use different prompt styles?

Yes.
That is one of the core design decisions.
Each imported blog has its own workflow and prompt configuration.

## Does Bloggent support only travel blogs?

No.
It can operate very different channel types as long as the workflow and prompts match the blog identity.
