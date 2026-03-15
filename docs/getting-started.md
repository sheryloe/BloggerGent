---
title: Getting Started
---

# Getting Started

This page explains how to bring Bloggent up locally and connect it to a real Blogger setup.

## Requirements

- Docker Desktop
- a Google account with Blogger access
- OpenAI API key
- optional Gemini API key
- GitHub repository or GitHub Pages target for public images

## Boot the stack

```bash
docker compose up --build
```

After startup:

- dashboard: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`

## Minimum configuration

Open `/settings` and configure:

- OpenAI API key
- Google OAuth client ID
- Google OAuth client secret
- Google OAuth redirect URI
- public image delivery settings

Optional:

- Gemini API key for topic discovery

## Google OAuth flow

1. Create a Google OAuth client as a web application.
2. Add the redirect URI:

```text
http://localhost:8000/api/v1/blogger/oauth/callback
```

3. If the OAuth app is still in testing, add your Google account as a test user.
4. Connect the Google account from Bloggent settings.

## Import blogs

Once Google OAuth is connected, import the Blogger blogs you want to operate.
Each imported blog becomes a separate service blog with its own workflow, prompt logic, and monitoring state.

## First working loop

1. Import the blog
2. Adjust the blog workflow
3. Generate a topic or create one manually
4. Generate the article
5. Review it in `/articles`
6. Publish it manually
7. Verify SEO metadata on the public page
