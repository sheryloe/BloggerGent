---
title: 배포
---

# 배포

Bloggent는 Docker 중심 로컬 배포와 빠른 재기동 흐름에 맞춰 설계되어 있습니다.

## 빠른 답변

로컬에서는 `.env`를 채우고 Docker Compose를 실행한 뒤, 웹과 API가 살아 있는지 확인하고, 변경한 서비스만 골라 재빌드하면 됩니다.

## 한눈에 보기

현재 compose 스택 서비스:

- `postgres`
- `redis`
- `minio`
- `api`
- `worker`
- `scheduler`
- `web`

주요 로컬 주소:

- 웹: `http://localhost:3001`
- API 문서: `http://localhost:8000/docs`
- API 헬스체크: `http://localhost:8000/healthz`

## 전체 로컬 부팅

```bash
docker compose up --build -d
```

## 앱만 재빌드

애플리케이션 레이어만 바꿨다면 보통 아래로 충분합니다.

```bash
docker compose up --build -d api worker scheduler web
```

## 헬스체크

```bash
curl http://localhost:8000/healthz
```

예상 응답:

```json
{"status":"ok"}
```

## 환경변수 묶음

### 핵심 앱 설정

- `DATABASE_URL`
- `REDIS_URL`
- `PUBLIC_API_BASE_URL`
- `PUBLIC_WEB_BASE_URL`
- `SETTINGS_ENCRYPTION_SECRET`

### 모델 공급자

- `OPENAI_API_KEY`
- `OPENAI_TEXT_MODEL`
- `OPENAI_IMAGE_MODEL`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `PROVIDER_MODE`

### Blogger OAuth

- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`
- `BLOGGER_REFRESH_TOKEN`

### GitHub Pages 에셋

- `PUBLIC_IMAGE_PROVIDER`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_BRANCH`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`
- `GITHUB_PAGES_ASSETS_DIR`

## 현재 로컬 실행 주의점

지금 `docker-compose.yml`의 `web` 서비스는 Next.js 개발 서버(`npm run dev`)로 뜹니다.
로컬 UI 작업에는 편하지만, 프로덕션 기준 가장 빠른 실행 방식은 아닙니다.

나중에는 `next build + next start`에 가까운 프로필로 분리하는 것이 좋습니다.

## 검증 명령

API 검증:

```bash
python -m compileall apps/api/app
```

웹 검증:

```bash
cd apps/web
npm run build
```

## 실전 배포 체크리스트

1. `.env`를 채웁니다.
2. 전체 스택을 실행합니다.
3. 헬스체크를 확인합니다.
4. 대시보드를 엽니다.
5. Google OAuth를 테스트합니다.
6. 블로그를 가져옵니다.
7. 테스트용 초안을 생성합니다.
8. 안전한 테스트 글 한 개를 발행합니다.
9. 공개 메타를 검증합니다.
