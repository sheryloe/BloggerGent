# Deployment

## Stack

- Next.js
- FastAPI
- Celery
- Redis
- PostgreSQL
- Docker Compose

## Rebuild command

```bash
docker compose up --build -d api worker scheduler web
```

## Verification

```bash
python -m compileall apps/api/app
cd apps/web && npm run build
```
