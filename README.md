# 동그리 자동 블로그전트

블로그 생성, 자산, 업로드, 운영을 한 화면에서 연결하는 운영 콘솔입니다. SEO/GEO/CTR/색인 상태까지 한 번에 관리하는 워크플로를 제공합니다.

## 핵심 기능
- 채널 연결 기반 운영: Blogger/Cloudflare/YouTube/Instagram 연결 상태를 우선 노출
- 7단계 고정 플로우: 주제→본문→이미지→HTML→게시까지 안정적 파이프라인
- SEO/GEO/CTR 점수화 + 품질 게이트
- Mission Control/Workspace 실시간 상태 집계
- GitHub Pages 기반 서비스 소개/문서

## 요구사항 (WSL 기준)
- WSL2 + Ubuntu
- Docker Desktop + Docker Compose
- Git
- (선택) Node 20+, Python 3.11+ (컨테이너 밖 개발 시)

## 기술 스택 / 필수 라이브러리
- Backend: FastAPI, SQLAlchemy, Alembic, Celery
- Frontend: Next.js
- Infra: Postgres, Redis, MinIO

## 폴더 구조
```
apps/
  api/        # FastAPI + Celery + DB
  web/        # Next.js 운영 콘솔
apps/api/alembic/versions/  # 마이그레이션
apps/api/app/services/       # 핵심 서비스 로직
apps/api/app/tasks/          # 파이프라인/스케줄러
apps/api/app/api/routes/     # API 라우터
apps/web/                    # 프론트

docs/       # GitHub Pages 랜딩/문서
wiki/       # 운영/배포/보안 문서
TEST/logs/  # 검증 로그
```

## 빠른 시작 (WSL)
```bash
cd /mnt/d/Donggri_Platform/BloggerGent

# .env 편집 (필수 항목은 아래 참고)
nano .env

# 실행
docker compose --env-file .env up -d --build
```

- Web: http://localhost:7001
- API: http://localhost:7002/api/v1
- Health: http://localhost:7002/healthz

## 필수 환경 변수
아래 값이 비어 있으면 실제 게시/동기화가 동작하지 않습니다.

```
OPENAI_API_KEY=...
BLOGGER_CLIENT_ID=...
BLOGGER_CLIENT_SECRET=...
BLOGGER_REDIRECT_URI=http://localhost:18000/api/v1/blogger/oauth/callback
CLOUDFLARE_BLOG_API_BASE_URL=...
CLOUDFLARE_BLOG_M2M_TOKEN=...
```

## 테스트 포트 분리 (7004/8004/5434)
```bash
cd /mnt/d/Donggri_Platform/BloggerGent
export COMPOSE_PROJECT_NAME=bloggent-test
export WEB_PORT=7004
export API_PORT=8004
export POSTGRES_PORT=5434

docker compose up -d --build
```

## 게시 스케줄(예: 10분 간격 3개)
```bash
cd /mnt/d/Donggri_Platform/BloggerGent
export COMPOSE_PROJECT_NAME=bloggent-test
export WEB_PORT=7004
export API_PORT=8004
export POSTGRES_PORT=5434

export OPENAI_API_KEY=...
export BLOGGER_ES_ID=...
export BLOGGER_JA_ID=...
export CLOUDFLARE_BLOG_API_BASE_URL=...
export CLOUDFLARE_BLOG_M2M_TOKEN=...

bash scripts/run_publish_plan.sh
```
- `scripts/run_publish_plan.sh`는 4/6 기준 EN/ES/JA/미스테리 + Cloudflare 각 3개를 10분 간격으로 예약합니다.

## 운영 점검 동기화
```bash
docker compose --env-file .env exec -T api python -m app.tools.ops_health_report
```

## Troubleshooting
- `/dashboard` 404 또는 Next.js 모듈 누락
```bash
docker compose --env-file .env exec -T web sh -lc "cd /app && rm -rf .next && npm install && npm run build"
```
- API 에러 확인
```bash
docker compose --env-file .env logs -f api
```

## GitHub Pages
- `docs/`는 서비스 소개/문서 용도입니다.
- 실제 운영 UI는 Docker 환경의 `/dashboard` 기준으로 확인합니다.
