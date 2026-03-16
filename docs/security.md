---
title: Security
---

# Security

Bloggent is an operator tool, so safe workflow choices and secret handling both matter.

## Quick Answer

The product already protects secrets, blocks some unsafe publishing mistakes, and keeps review in the loop before public release.

## Current protections

### Secret storage

Sensitive settings such as API keys and refresh tokens are encrypted before they are stored.

Protected values include:

- OpenAI API key
- Gemini API key
- GitHub token
- Blogger refresh token

### Publish safety

The service is built around manual release.
That reduces the risk of weak drafts going public without human review.

### Overwrite protection

The pipeline is designed to avoid blindly overwriting already public Blogger posts.

### Topic safety

Duplicate-topic checks reduce the chance of repeatedly generating the same angle across the same blog.

## Operational safety notes

For real deployments, keep these in mind:

- set a strong `SETTINGS_ENCRYPTION_SECRET`
- restrict who can access the running dashboard
- treat Blogger OAuth credentials like production secrets
- verify public metadata after publishing instead of assuming the API succeeded

## Remaining limitations

Some limitations are platform-level, not only code-level.
Blogger metadata still needs verification and sometimes theme-level fallback logic.

That is why Bloggent emphasizes:

- manual review
- publish separation
- live metadata verification
