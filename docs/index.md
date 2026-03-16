---
title: Bloggent Docs
---

# Bloggent Docs

Bloggent is a Blogger publishing workspace for operators who want AI assistance without losing review control.
It supports multi-blog workflows, GEO + SEO content generation, manual publishing, and public-page metadata verification.

## Quick Answer

Use Bloggent if you need one place to manage Blogger content operations end to end:

- connect Google and import blogs
- discover topics or enter them manually
- generate articles and images
- review assembled posts before release
- publish manually
- verify real public SEO metadata after publishing

## At a Glance

- Product routes: `/`, `/articles`, `/jobs`, `/settings`, `/google`
- Local web: `http://localhost:3001`
- Local API docs: `http://localhost:8000/docs`
- Main stack: Next.js, FastAPI, Celery, PostgreSQL, Redis, Docker Compose
- Public docs landing page: `index.html`

## Start Here

- [Getting Started](getting-started.html)
- [Workflow Model](workflow.html)
- [SEO Metadata Strategy](seo-metadata.html)
- [Architecture](architecture.html)
- [Deployment](deployment.html)
- [Security](security.html)
- [FAQ](faq.html)
- [Roadmap](roadmap.html)

## Current Focus

The product currently emphasizes three ideas:

1. Blog-specific workflows instead of one global prompt setup
2. Manual-safe publishing instead of blind auto-release
3. Real public-page SEO verification instead of trusting Blogger metadata blindly

## GEO + SEO Content Model

The current writing prompts are answer-first and metadata-aware.
They are designed so the opening answers the query fast, each section solves a real sub-question, and the metadata promise matches the body.

## Read the Public Landing Page

If GitHub Pages is configured to publish from `/docs`, the visual landing page for this documentation is:

- [Landing Page](index.html)
