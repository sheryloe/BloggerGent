---
title: SEO Metadata Strategy
---

# SEO Metadata Strategy

Blogger SEO metadata looks simple until you verify the real public page.

## Quick Answer

Bloggent does not assume Blogger API metadata is enough.
It verifies the real published page and checks whether the expected description is visible in:

- `description`
- `og:description`
- `twitter:description`

## At a Glance

- The dashboard state is not a full SEO quality score
- It is a metadata verification state
- Blogger `customMetaData` is not a reliable public `<head>` source
- A theme patch fallback may still be needed
- Verification should happen after publishing

## The Blogger limitation

At first glance, Blogger API appears to support metadata through `customMetaData`.
In practice, that field does not reliably become the final public `<head>` output that crawlers read.

That means this assumption is unsafe:

```json
{
  "title": "Post title",
  "content": "<article>...</article>",
  "customMetaData": "Expected SEO description"
}
```

The post may still render with:

- no `meta[name="description"]`
- no `og:description`
- no `twitter:description`
- or only a blog-wide fallback description

## What Bloggent does instead

Bloggent uses a more practical verification-first strategy:

1. store the expected article description
2. keep the article metadata aligned with the generation prompt
3. embed fallback metadata markers into the assembled post flow
4. support a Blogger theme patch in `<head>`
5. verify the live public result after publishing

## What the dashboard status means

The current dashboard card is best read as a metadata verification state.

### `Not verified`

No live verification has been run yet, or the article is not yet public.
This does not automatically mean the content is low quality.

### `Warning`

Some public tags do not match the expected description.
Usually this points to:

- theme patch missing
- old blog-wide metadata winning
- search description not yet synced

### `OK`

The expected description matches the public tags Bloggent checks.

## Article-level vs blog-level verification

Bloggent works at two levels:

### Article level

This verifies the published article URL and compares the expected description with the live metadata on that page.

### Blog level

This checks whether the broader theme-patch path is in place for the blog.
If the patch is missing, article verification may still warn even when the article copy itself is good.

## How to improve the result

If the metadata state is weak, the fix is usually operational, not only prompt-related:

1. write a clear `meta_description`
2. keep `excerpt` aligned with that promise
3. sync the search description if needed
4. install the Blogger theme patch fallback
5. re-run live verification

## How GEO + SEO prompts help

The new GEO + SEO prompts improve metadata quality by making the article promise clearer from the start.
They now push the model to:

- answer the core query early
- define the main entity sooner
- keep section structure easier to summarize
- align the public snippet with the actual article body

Prompt files:

- `prompts/article_generation.md`
- `prompts/travel_article_generation.md`
- `prompts/mystery_article_generation.md`

## Practical takeaway

Do not read a low dashboard number as "the article body is bad."
Read it as "the live public metadata path still needs verification or repair."
