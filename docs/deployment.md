---
title: Deployment
---

# Deployment

Bloggent is designed for Docker-first local deployment and operator-friendly rebuilds.

## Quick Answer

For local use, fill `.env`, start Docker Compose, verify web and API health, and rebuild only the services you changed.

## At a Glance

Services in the current compose stack:

- `postgres`
- `redis`
- `minio`
- `api`
- `worker`
- `scheduler`
- `web`

Main local addresses:

- Web: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`

## Full local boot

```bash
docker compose up --build -d
```

## Narrow rebuild after app changes

If you changed only the application layers, this is usually enough:

```bash
docker compose up --build -d api worker scheduler web
```

## Health checks

```bash
curl http://localhost:8000/healthz
```

Expected:

```json
{"status":"ok"}
```

## Environment groups

### Core app

- `DATABASE_URL`
- `REDIS_URL`
- `PUBLIC_API_BASE_URL`
- `PUBLIC_WEB_BASE_URL`
- `SETTINGS_ENCRYPTION_SECRET`

### Model providers

- `OPENAI_API_KEY`
- `OPENAI_TEXT_MODEL`
- `OPENAI_IMAGE_MODEL`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `PROVIDER_MODE`

### Blogger OAuth

- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`
- `BLOGGER_REFRESH_TOKEN`

### GitHub Pages assets

- `PUBLIC_IMAGE_PROVIDER`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_BRANCH`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`
- `GITHUB_PAGES_ASSETS_DIR`

## Current local note

The current `web` service in `docker-compose.yml` runs the Next.js development server.
That is convenient for local UI work, but it is not the fastest production profile.

For production-style deployment later, the web container should move toward a build plus `next start` style setup.

## Verification commands

API verification:

```bash
python -m compileall apps/api/app
```

Web verification:

```bash
cd apps/web
npm run build
```

## Practical deployment checklist

1. Fill `.env`
2. Start the full stack
3. Verify the health endpoint
4. Open the dashboard
5. Test Google OAuth
6. Import a blog
7. Generate a draft
8. Publish one safe test article
9. Verify metadata on the live page
