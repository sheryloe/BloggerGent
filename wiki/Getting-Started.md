# Getting Started

이 문서는 Donggr AutoBloggent를 처음 세팅할 때 필요한 최소 순서를 정리합니다.

## 1. 준비물

- Docker / Docker Compose
- Blogger 운영용 Google 계정
- OpenAI API key
- Cloudflare 계정 (R2 사용 시)
- `SETTINGS_ENCRYPTION_SECRET`

## 2. `.env` 기본 확인

핵심 값 확인:

```env
WEB_PORT=7001
API_PORT=7002
NEXT_PUBLIC_API_BASE_URL=http://localhost:7002/api/v1
API_INTERNAL_URL=http://api:8000/api/v1
BLOGGER_REDIRECT_URI=http://localhost:7002/api/v1/blogger/oauth/callback
PUBLIC_IMAGE_PROVIDER=cloudflare_r2
SETTINGS_ENCRYPTION_SECRET=
```

## 3. 실행

```bash
cd /mnt/d/Donggri_Platform/BloggerGent
docker compose --env-file .env up -d
```

확인 주소:

- Web: `http://127.0.0.1:7001`
- API docs: `http://127.0.0.1:7002/docs`
- Health: `http://127.0.0.1:7002/healthz`

## 4. 초기 점검 체크리스트

1. `/` 접속 시 `/dashboard`로 이동되는지 확인
2. 대시보드 타이틀이 `Donggr AutoBloggent`인지 확인
3. 대시보드에 `생성/자산/업로드/운영` 4개 묶음이 보이는지 확인
4. `/api/v1/workspace/mission-control`의 `workspace_label` 값 확인

## 5. OAuth 연결

1. Google Cloud Console에서 OAuth Web Client 생성
2. Redirect URI 등록

```text
http://localhost:7002/api/v1/blogger/oauth/callback
```

3. `/settings`에서 Google 연결 수행
4. Blogger 블로그 import

## 6. 운영 시작 순서

1. Planner에서 게시 슬롯/큐 확인
2. Content Ops에서 초안/자산 정리
3. Dashboard에서 런타임/알림 확인
4. Analytics/Google에서 성과 확인