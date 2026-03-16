---
title: Getting Started
---

# Getting Started

This guide shows how to bring Bloggent up locally and reach a real working Blogger loop.

## Quick Answer

1. Fill `.env`
2. Start Docker Compose
3. Open `/settings`
4. Connect Google
5. Import blogs
6. Generate and review content
7. Publish manually
8. Verify public metadata

## At a Glance

- Web: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`
- Core services: `web`, `api`, `worker`, `scheduler`, `postgres`, `redis`, `minio`

## Requirements

- Docker or a compatible local container runtime
- A Google account with Blogger access
- An OpenAI API key for live generation
- Optional Gemini API key for topic discovery
- A secure `SETTINGS_ENCRYPTION_SECRET`

## 1. Prepare `.env`

Start from `.env.example`.
For a real setup, the main keys are:

- `OPENAI_API_KEY`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`
- `SETTINGS_ENCRYPTION_SECRET`

Optional but useful:

- `GEMINI_API_KEY`
- `PUBLIC_IMAGE_PROVIDER`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`

For a safe demo loop, the repository also supports:

- `PROVIDER_MODE=mock`
- `SEED_DEMO_DATA=true`

## 2. Start the stack

```bash
docker compose up --build -d
```

If you only changed the web and API apps, a narrower rebuild is enough:

```bash
docker compose up --build -d api worker scheduler web
```

## 3. Verify the services

Open these addresses after startup:

- Dashboard: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`

You can also test health from the terminal:

```bash
curl http://localhost:8000/healthz
```

Expected response:

```json
{"status":"ok"}
```

## 4. Connect Google OAuth

Create a Google OAuth web application and add this redirect URI:

```text
http://localhost:8000/api/v1/blogger/oauth/callback
```

If the OAuth app is still in testing, add your Google account as a test user.
Then connect the account from `/settings`.

## 5. Import Blogger blogs

After Google OAuth succeeds, import the Blogger blogs you want to operate.
Each imported blog keeps its own:

- workflow
- prompt template chain
- category identity
- connection mapping

## 6. Configure each blog

Review the workflow and prompt setup for each imported blog.
The current product also supports per-blog Google mappings such as:

- Search Console property
- GA4 property ID

Those settings matter for the Google data screens and reporting cards.

## 7. Create content

From the dashboard, you can either:

- enter a topic manually
- let AI discover topics for the selected blog

The pipeline then creates the article package and sends it through the configured generation flow.

## 8. Review in `/articles`

Use the article screen to inspect:

- title
- meta description
- excerpt
- labels
- assembled HTML
- full inline post preview
- SEO metadata verification panel

Bloggent keeps publishing manual on purpose so you can approve the final result yourself.

## 9. Publish manually

Publish from the article review flow when the post is ready.
This reduces the biggest Blogger risk in AI workflows: weak drafts going live without review.

## 10. Verify SEO metadata

After publishing, run SEO verification from the article page.
The current verification checks:

- `description`
- `og:description`
- `twitter:description`

Important:
The dashboard state is a metadata verification state, not a full article quality score.

## 11. Optional GitHub Pages image delivery

If you want GitHub Pages for public images, configure:

- `PUBLIC_IMAGE_PROVIDER=github_pages`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_BRANCH`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`
- `GITHUB_PAGES_ASSETS_DIR`

## Next Reads

- [Workflow Model](workflow.html)
- [SEO Metadata Strategy](seo-metadata.html)
- [Deployment](deployment.html)
- [Roadmap](roadmap.html)
