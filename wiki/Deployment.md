# Deployment

Bloggent is currently optimized for Docker-first local deployment.

## Main services

- `web`
- `api`
- `worker`
- `scheduler`
- `postgres`
- `redis`
- `minio`

## Start command

```bash
docker compose up --build -d
```

## Rebuild after app changes

```bash
docker compose up --build -d api worker scheduler web
```

## Verification

```bash
curl http://localhost:8000/healthz
```

```bash
cd apps/web
npm run build
```

## Current deployment note

The current local `web` container runs the Next.js development server.
That is fine for local work, but a production-style web profile should move toward a built runtime later.
