# Security

## Current protections

- encrypted secret storage
- manual publish step
- published-post overwrite protection
- duplicate-topic blocking

## Practical note

Bloggent is an operator tool, so workflow safety matters as much as code-level protection.
Use a strong `SETTINGS_ENCRYPTION_SECRET`, protect dashboard access, and verify live metadata after publishing.
