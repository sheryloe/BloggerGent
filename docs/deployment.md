---
title: Deployment
---

# Deployment

Bloggent is designed to run well in Docker-first local environments.

## Services

- `web`
- `api`
- `worker`
- `scheduler`
- `postgres`
- `redis`
- optional public asset support via GitHub Pages

## Commands

```bash
docker compose up --build -d
```

Rebuild after code changes:

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

## Verification commands

```bash
python -m compileall apps/api/app
```

```bash
cd apps/web
npm run build
```
