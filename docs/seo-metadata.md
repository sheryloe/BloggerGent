---
title: SEO Metadata Strategy
---

# SEO Metadata Strategy

Blogger metadata is trickier than it looks.

## The `customMetaData` trap

At first glance, Blogger API appears to support post metadata through `customMetaData`.
In practice, that field does not reliably become real public `<head>` tags.

That means the following assumption is unsafe:

```json
{
  "title": "Post title",
  "content": "<article>...</article>",
  "customMetaData": "Expected SEO description"
}
```

Even if the API accepts that payload, the public page may still render:

- no `meta[name="description"]`
- no `og:description`
- only a blog-wide default description

## The practical fallback

Bloggent now uses a fallback strategy:

1. store the expected description in the database
2. embed it into the assembled article body
3. add a Blogger theme patch in `<head>`
4. let the theme script upsert the final meta tags at runtime

## Why this works

The app can fully control article body HTML.
It cannot fully control Blogger public-page `<head>` through the API alone.

So the theme patch bridges that gap.

## Verification

Bloggent verifies SEO metadata at the article level and blog level.
The app compares:

- expected description
- raw public-page meta tags
- fallback markers embedded into the published article

This allows verification to show a realistic status instead of pretending the API solved everything by itself.
