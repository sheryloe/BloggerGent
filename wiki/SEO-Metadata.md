# SEO Metadata

Bloggent treats Blogger SEO metadata as a live verification problem, not as a solved API field.

## Quick Answer

The dashboard state is not a full SEO body score.
It is a metadata verification state for:

- `description`
- `og:description`
- `twitter:description`

## Why this exists

Blogger `customMetaData` does not reliably become the final public `<head>` output.
That is why Bloggent stores the expected description, supports a theme patch fallback, and verifies the live page after publishing.

## What to do if the result is weak

1. check whether the article is public
2. confirm the meta description matches the article promise
3. run search description sync if needed
4. install the Blogger theme patch
5. run live verification again
