---
title: Security
---

# Security

Bloggent is still a practical operator tool, but it now includes basic safety measures that matter in real use.

## Secret storage

Settings such as API keys and refresh tokens are encrypted before they are stored in the database.

Protected values include:

- OpenAI API key
- Gemini API key
- GitHub token
- Blogger refresh token

## Publish safety

The service blocks accidental overwrite of public posts.
Publishing is manual from the article list so that operators can inspect the final result first.

## Topic safety

Duplicate-topic checks reduce the chance of generating the same subject repeatedly across existing content.

## Remaining limitation

Blogger metadata still has platform limitations.
The SEO strategy therefore uses verification and theme-level fallback logic rather than promising API-perfect metadata behavior.
