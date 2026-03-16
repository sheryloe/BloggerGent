---
title: 시작하기
---

# 시작하기

이 문서는 Bloggent를 로컬에서 띄우고, 실제로 Blogger 글 생성과 발행 검토 루프까지 도달하는 가장 빠른 경로를 설명합니다.

## 빠른 답변

1. `.env`를 채웁니다.
2. Docker Compose를 실행합니다.
3. `/settings`를 엽니다.
4. Google 계정을 연결합니다.
5. Blogger 블로그를 가져옵니다.
6. 글을 생성하고 검토합니다.
7. 수동 발행합니다.
8. 공개 메타를 검증합니다.

## 한눈에 보기

- 웹: `http://localhost:3001`
- API 문서: `http://localhost:8000/docs`
- API 헬스체크: `http://localhost:8000/healthz`
- 주요 서비스: `web`, `api`, `worker`, `scheduler`, `postgres`, `redis`, `minio`

## 준비물

- Docker 또는 호환되는 로컬 컨테이너 런타임
- Blogger 접근 권한이 있는 Google 계정
- 실제 글 생성을 위한 OpenAI API 키
- 선택 사항인 Gemini API 키
- 안전한 `SETTINGS_ENCRYPTION_SECRET`

## 1. `.env` 준비

`.env.example`을 기준으로 `.env`를 작성합니다.
실사용 기준 최소 핵심 값은 아래와 같습니다.

- `OPENAI_API_KEY`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`
- `SETTINGS_ENCRYPTION_SECRET`

있으면 좋은 값:

- `GEMINI_API_KEY`
- `PUBLIC_IMAGE_PROVIDER`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`

데모 확인용으로는 아래 값도 사용할 수 있습니다.

- `PROVIDER_MODE=mock`
- `SEED_DEMO_DATA=true`

## 2. 스택 실행

```bash
docker compose up --build -d
```

웹과 API만 바꿨다면 보통 아래 정도로도 충분합니다.

```bash
docker compose up --build -d api worker scheduler web
```

## 3. 서비스 확인

실행 후 아래 주소를 확인합니다.

- 대시보드: `http://localhost:3001`
- API 문서: `http://localhost:8000/docs`
- API 헬스체크: `http://localhost:8000/healthz`

터미널에서 헬스체크를 바로 보려면:

```bash
curl http://localhost:8000/healthz
```

예상 응답:

```json
{"status":"ok"}
```

## 4. Google OAuth 연결

Google OAuth 웹 애플리케이션을 만들고 아래 redirect URI를 등록합니다.

```text
http://localhost:8000/api/v1/blogger/oauth/callback
```

OAuth 앱이 테스트 상태라면, 사용하는 Google 계정을 테스트 사용자로 추가해야 합니다.
그다음 `/settings`에서 계정을 연결합니다.

## 5. Blogger 블로그 가져오기

Google 연결이 끝나면 운영할 Blogger 블로그를 가져옵니다.
가져온 각 블로그는 아래 정보를 따로 가집니다.

- 워크플로
- 프롬프트 체인
- 카테고리 정체성
- Google 연결 매핑

## 6. 블로그별 설정 점검

가져온 블로그마다 워크플로와 프롬프트를 확인합니다.
현재 제품에서는 아래 같은 Google 매핑도 블로그별로 설정할 수 있습니다.

- Search Console 속성
- GA4 속성 ID

이 값들은 Google 데이터 화면과 리포팅 카드에 직접 영향을 줍니다.

## 7. 글 생성

대시보드에서는 두 가지 방식이 있습니다.

- 직접 주제 입력
- 선택한 블로그 기준 AI 주제 발굴

이후 파이프라인이 글 패키지를 생성하고, 설정된 생성 흐름에 맞춰 이어서 처리합니다.

## 8. `/articles`에서 검토

글 보관함 화면에서는 아래를 확인할 수 있습니다.

- 제목
- 메타 설명
- excerpt
- 라벨
- 조립된 HTML
- 전체 포스트 프리뷰
- SEO 메타 검증 패널

Bloggent는 발행을 일부러 수동으로 남겨 두기 때문에, 최종 공개 전 마지막 판단을 운영자가 직접 할 수 있습니다.

## 9. 수동 발행

글이 준비되면 글 검토 화면에서 수동으로 발행합니다.
이렇게 해야 “AI가 쓴 약한 초안이 바로 공개되는” Blogger 운영 리스크를 줄일 수 있습니다.

## 10. SEO 메타 검증

발행 후에는 글 화면에서 메타 검증을 실행합니다.
현재 검증 대상은 아래 3가지입니다.

- `description`
- `og:description`
- `twitter:description`

주의:
대시보드 메타 상태는 “글 전체 품질 점수”가 아니라 “공개 메타 검증 상태”입니다.

## 11. GitHub Pages 이미지 전달 선택

공개 이미지 전달을 GitHub Pages로 하고 싶다면 아래 값을 설정합니다.

- `PUBLIC_IMAGE_PROVIDER=github_pages`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_BRANCH`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`
- `GITHUB_PAGES_ASSETS_DIR`

## 다음 문서

- [워크플로 구조](workflow.html)
- [SEO 메타데이터 전략](seo-metadata.html)
- [배포](deployment.html)
- [로드맵](roadmap.html)
