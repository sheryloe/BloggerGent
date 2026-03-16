# Getting Started

This page is the fastest path to a working local Bloggent loop.

## Quick Answer

1. Fill `.env`
2. Run Docker Compose
3. Open `/settings`
4. Connect Google OAuth
5. Import Blogger blogs
6. Generate content
7. Review in `/articles`
8. Publish manually
9. Verify metadata

## Main addresses

- dashboard: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`

## Minimum environment keys

- `OPENAI_API_KEY`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`
- `SETTINGS_ENCRYPTION_SECRET`

Optional:

- `GEMINI_API_KEY`
- GitHub Pages asset settings

## Boot command

```bash
docker compose up --build -d
```

## First-use flow

1. Open `/settings`
2. Connect Google
3. Import Blogger blogs
4. Review each blog workflow
5. Set Search Console and GA4 mappings if needed
6. Create a topic or run topic discovery
7. Review the post in `/articles`
8. Publish manually
9. Run live metadata verification
