# Bloggent

Bloggent is a service-oriented automation workspace for operating multiple Google Blogger blogs from a single dashboard.
It is designed for real publishing work, not just content generation demos.

The current stack covers:

- blog import from real Blogger accounts
- blog-specific workflow and prompt configuration
- AI-assisted topic discovery, article writing, image generation, and HTML assembly
- manual-safe publishing from the generated article list
- Google data connections for Blogger, Search Console, and GA4
- SEO metadata verification and Blogger theme patch guidance
- published-post protection, duplicate-topic prevention, and encrypted secret storage

## What Bloggent Solves

Running more than one Blogger blog usually means repeating the same cycle again and again:

1. find a topic
2. write the article
3. create an image
4. assemble publish-ready HTML
5. publish carefully without overwriting an existing post
6. verify whether the public page actually reflects the intended SEO state

Bloggent turns that manual loop into a controlled workflow.
It keeps blog-specific prompts separate, lets each blog use a different tone and pipeline, and leaves the final publish action in the article list so public posts are not overwritten by accident.

## Core Product Principles

### 1. Blog-specific workflows, not one global prompt
Each imported blog has its own workflow, visible stages, system stages, model selection, and prompt text.
This matters when one blog is an English Korea travel/festival guide and another is a dark documentary-style mystery blog.

### 2. Generate first, publish later
Bloggent treats generation and publishing as two different steps.
Draft generation finishes first, then the user checks the generated article list and manually presses the publish button only for the post they want to release.

### 3. Public posts must not be overwritten
Published Blogger posts are protected.
The service blocks accidental overwrites and also rejects obviously duplicated topics so the same subject is not regenerated carelessly.

### 4. SEO must be validated on the real public page
Blogger API metadata is not enough on its own.
Bloggent therefore verifies what is actually present on the public page and supports a practical Blogger theme patch strategy for description tags.

## Current Feature Set

### Blogger and Google integration
- import Blogger blogs from a connected Google account
- map each service blog to Search Console and GA4 data
- keep a separate operating profile for each imported blog

### AI pipeline
- optional topic discovery
- writing package stage
- optional image prompt refinement
- image generation
- HTML assembly
- manual publish queue

### Safety and operations
- duplicate topic detection
- published-post overwrite protection
- encrypted storage for secrets in the settings table
- blog-level and article-level SEO metadata verification
- dashboard, jobs, articles, settings, guide, and Google data views

### SEO metadata strategy
Bloggent no longer relies on `customMetaData` as the primary Blogger metadata path.
Instead, it:

- stores the expected article meta description in the app database
- embeds that value into the assembled article body
- uses a Blogger theme patch to upsert `description`, `og:description`, and `twitter:description`
- verifies the public result from the published page

This is the practical fallback path for Blogger because API-side metadata fields do not reliably become real `<head>` tags on public pages.

## Architecture Overview

### Frontend
- Next.js 14
- TypeScript
- Tailwind CSS

### Backend
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic

### Worker and infrastructure
- Celery
- Redis
- PostgreSQL
- Docker Compose

## Local Run

```bash
docker compose up --build
```

Main addresses:

- dashboard: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`

## Recommended Operating Flow

1. Open `/settings`
2. Add shared API credentials and Google OAuth values
3. Connect a Google account
4. Import Blogger blogs
5. Configure each blog workflow and prompt set
6. Generate topics and articles
7. Review the generated article list
8. Publish only the post you want to release
9. Verify SEO metadata on the public page

## Repository Guide

- `apps/api`
  FastAPI backend, workflow logic, Blogger integration, SEO verification, and scheduling
- `apps/web`
  dashboard, settings, jobs, articles, guide, and Google views
- `prompts`
  reusable prompt templates for travel, mystery, and shared stages
- `docs`
  GitHub Pages-ready project documentation and Tistory/Notion writing materials
- `scripts`
  operational helpers for local development and browser automation experiments

## Documentation

### GitHub Pages-ready docs

These docs focus only on the service and the codebase:

- [Project Overview](docs/index.md)
- [Getting Started](docs/getting-started.md)
- [Workflow Model](docs/workflow.md)
- [SEO Metadata Strategy](docs/seo-metadata.md)
- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Security](docs/security.md)
- [FAQ](docs/faq.md)

### Wiki-ready docs

Wiki markdown is stored under [`wiki/`](wiki) so it can be pushed to GitHub Wiki later if needed.

### Tistory / Notion writing series

The Korean writing series for implementation process, theory, and SEO-focused documentation lives under [`docs/tistory-seo`](docs/tistory-seo).

## Notes

- Publishing is intentionally manual from the article list.
- Public posts are protected against accidental overwrite.
- Secrets are encrypted before being stored in the settings table.
- Blogger SEO metadata needs theme-level help, so verification is done against the real public page.
- GitHub Pages image delivery is supported for public article images.

## Status

Bloggent is already usable as a practical Blogger operating workspace and continues to be refined around publishing safety, workflow clarity, and SEO verification quality.
