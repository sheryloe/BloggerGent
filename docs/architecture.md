---
title: Architecture
---

# Architecture

Bloggent is split into a web dashboard, an API app, and background workers so publishing operations stay observable and reviewable.

## Quick Answer

The product is designed as an operator workspace, not just a one-click content generator.
That is why UI, orchestration, publishing state, and verification logic are separated into services with clear boundaries.

## At a Glance

- Frontend: Next.js 14, TypeScript, Tailwind CSS
- Backend: FastAPI, SQLAlchemy, Alembic, Pydantic
- Background work: Celery worker plus Celery beat scheduler
- Data and queues: PostgreSQL and Redis
- Local runtime: Docker Compose
- Asset options: local storage plus GitHub Pages support

## Frontend responsibilities

The dashboard focuses on operational clarity.
Its current key views are:

- `/` for actions, queue, preview, and summary state
- `/articles` for review, publish, and metadata verification
- `/jobs` for pipeline execution visibility
- `/settings` for secrets, imports, and connections
- `/google` for connected reporting views

## Backend responsibilities

The FastAPI app handles:

- Blogger OAuth
- blog import
- workflow configuration
- prompt rendering
- content generation orchestration
- HTML assembly
- publishing
- SEO metadata verification

## Background processing

Long-running or scheduled work is delegated to Celery:

- `worker` processes generation jobs
- `scheduler` runs timed automation

This keeps the dashboard responsive while heavy generation and publishing tasks run in the background.

## Data boundaries

Bloggent separates several domains on purpose:

- blog configuration
- agent prompt configuration
- topics
- articles
- Blogger publish records
- jobs
- encrypted settings and tokens

That separation makes it easier to review drafts, prevent accidental overwrites, and inspect failures without collapsing everything into one record.

## Why manual publish is architectural, not cosmetic

Manual publish is not just a UI preference.
It is one of the core product boundaries.

The system intentionally treats these as different moments:

1. generate content
2. review content
3. publish content
4. verify live metadata

That prevents AI generation from automatically becoming public output without operator approval.

## Why Blogger SEO needs its own path

Blogger metadata is platform-constrained, so Bloggent treats SEO verification as a first-class service concern.
The app compares expected metadata with the real live page instead of trusting API acceptance as proof.
