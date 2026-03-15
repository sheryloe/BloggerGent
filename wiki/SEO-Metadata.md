# SEO Metadata

## Blogger limitation

`customMetaData` is not a reliable public `<head>` metadata path for Blogger.

## Bloggent strategy

1. store expected description
2. embed it into the article body
3. use a Blogger theme patch in `<head>`
4. verify the public result

## Result

Bloggent verifies the real public page instead of assuming the API solved metadata correctly.
