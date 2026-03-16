# Bloggent

Bloggent is a Docker-first Blogger publishing workspace for GEO + SEO operations.
It helps you run multiple Blogger blogs from one dashboard, generate content with AI, review drafts safely, publish manually, and verify the real public SEO metadata after release.

## Quick Answer

If you want an AI-assisted Blogger workflow without blind auto-publishing, Bloggent is built for that exact use case.
It separates topic discovery, article generation, image generation, HTML assembly, review, publishing, and public-page verification so the operator stays in control.

## At a Glance

- Dashboard routes: `/`, `/articles`, `/jobs`, `/settings`, `/google`
- Local addresses: `http://localhost:3001`, `http://localhost:8000/docs`, `http://localhost:8000/healthz`
- Core services: `web`, `api`, `worker`, `scheduler`, `postgres`, `redis`, `minio`
- Content model: blog-specific workflows plus category-specific prompt templates
- Publish model: generate first, review second, publish manually
- SEO model: verify the real published page instead of assuming Blogger API metadata worked

## What Bloggent Does

### Multi-blog operations

Each imported Blogger blog keeps its own workflow, prompt logic, content category, and connection state.
That lets one workspace run very different blog identities without forcing one prompt style onto every channel.

### Draft-safe publishing

Bloggent intentionally separates generation from publishing.
The pipeline can create topics, articles, images, and assembled HTML, but the final public release stays manual from the article review screen.

### GEO + SEO content generation

The current prompt system is answer-first and metadata-aware.
The article prompts in [`prompts/article_generation.md`](prompts/article_generation.md), [`prompts/travel_article_generation.md`](prompts/travel_article_generation.md), and [`prompts/mystery_article_generation.md`](prompts/mystery_article_generation.md) now follow a GEO + SEO structure:

- answer the core query early
- name the main entity and practical value in the opening
- make each H2 answer a real sub-question
- align `meta_description`, `excerpt`, and article promise
- keep the article quote-friendly for search and answer engines

### Real Blogger SEO verification

Bloggent does not treat Blogger `customMetaData` as a reliable source of truth for public `<head>` tags.
Instead, it stores the expected description, assembles it into the post flow, supports a Blogger theme patch fallback, and verifies:

- `description`
- `og:description`
- `twitter:description`

The dashboard label is a meta verification state, not a full body-content SEO score.

## Local Setup

### 1. Prepare environment variables

Copy `.env.example` to `.env` and fill the values you need.
The minimum keys for real use are:

- `OPENAI_API_KEY`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`
- `SETTINGS_ENCRYPTION_SECRET`

Useful optional keys:

- `GEMINI_API_KEY`
- `PUBLIC_IMAGE_PROVIDER`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_BRANCH`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`

For local UI testing without live model calls, the default `.env.example` also supports:

- `PROVIDER_MODE=mock`
- `SEED_DEMO_DATA=true`

### 2. Start the stack

```bash
docker compose up --build -d
```

### 3. Open the product

- Dashboard: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`

### 4. Complete the first-use loop

1. Open `/settings`
2. Connect Google OAuth
3. Import Blogger blogs
4. Review each blog workflow and prompt setup
5. Generate a topic or type one manually from the dashboard
6. Review the generated article in `/articles`
7. Publish manually
8. Run meta verification on the published page

## Current Product Areas

### `/`

The dashboard is the operator home.
It now shows the main action panel, work queue, recent links, full post preview, and meta verification state in one layout.

### `/articles`

This is the review and release screen.
Use it to inspect article metadata, view the assembled post preview inline, publish manually, and run SEO metadata verification.

### `/jobs`

Use the jobs view to inspect background pipeline work, failures, and completed generation runs.

### `/settings`

Use settings for secrets, Google OAuth, blog imports, and per-blog connections such as Search Console property mapping and GA4 property mapping.

### `/google`

Use the Google data screen to inspect Blogger, Search Console, and GA4-linked reporting where available.

## GitHub Pages Support

Bloggent can also use GitHub Pages as a public asset delivery target.
If you want that setup, configure:

- `PUBLIC_IMAGE_PROVIDER=github_pages`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_BRANCH`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`
- `GITHUB_PAGES_ASSETS_DIR`

The documentation site in `docs/` is also ready to be served from GitHub Pages.
If the repository is configured to publish from `/docs`, [`docs/index.html`](docs/index.html) becomes the public landing page.

## Docs and Wiki

- GitHub Pages docs: [`docs/index.html`](docs/index.html)
- Docs start page: [`docs/index.md`](docs/index.md)
- Local start guide: [`docs/getting-started.md`](docs/getting-started.md)
- SEO guide: [`docs/seo-metadata.md`](docs/seo-metadata.md)
- Roadmap: [`docs/roadmap.md`](docs/roadmap.md)
- Wiki home: [`wiki/Home.md`](wiki/Home.md)

## Roadmap

### Now

- Make Blogger SEO theme patch onboarding easier from the dashboard and settings flow
- Reduce dashboard refresh latency after content actions
- Continue unifying the remaining views around the new dashboard layout and copy system

### Next

- Add stronger pre-publish QA checks for title, meta description, image readiness, and duplicate coverage
- Expand Search Console and GA4 insight visibility per connected blog
- Add scheduled publishing flow that still preserves manual operator control

### Later

- Add multi-user roles and permissions
- Add stronger production deployment profiles for the web app
- Add more asset provider choices beyond local and GitHub Pages

## Repository

- Source: `https://github.com/sheryloe/BloggerGent`
