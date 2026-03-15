---
title: Architecture
---

# Architecture

Bloggent is split into a dashboard app, an API app, and background services.

## Frontend

The dashboard is built with Next.js and TypeScript.
It handles:

- settings
- blog workflow views
- jobs
- generated article review
- SEO verification panels

## Backend

The FastAPI backend handles:

- blog import
- prompt and workflow configuration
- article generation orchestration
- HTML assembly
- Blogger publishing
- metadata verification

## Background processing

Celery workers handle queued or scheduled work.
Redis is used for broker and state transport.
PostgreSQL stores the persistent operating data.

## Data boundaries

The system separates:

- blog configuration
- article outputs
- publish records
- job records
- secret settings

That makes it possible to review drafts and publishing state without mixing them into one table or one step.
