# Getting Started

## Local boot

```bash
docker compose up --build
```

## Main addresses

- dashboard: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/healthz`

## Minimum setup

- OpenAI API key
- Google OAuth client ID / secret
- Google OAuth redirect URI
- public image delivery target

## Flow

1. connect Google
2. import Blogger blogs
3. adjust blog workflow
4. generate content
5. review articles
6. publish manually
