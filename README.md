# Bloggent

Bloggent는 Blogger 운영을 위한 GEO + SEO 중심 콘텐츠 워크스페이스입니다. 주제 발굴부터 글 생성, 이미지, HTML 조립, 수동 발행, 공개 메타 검증까지 한 흐름으로 관리합니다.

## 핵심 기능

- 다중 블로그 워크플로 분리 운영
- 주제 발굴, 글 패키지 생성, 이미지 생성 자동화
- 수동 발행 보호와 발행 후 공개 메타 검증
- GEO + SEO 구조를 반영한 콘텐츠 패키징
- 운영 로그, 작업 큐, 상태 모니터링

## 아키텍처 개요

- 여러 Blogger 블로그를 한 번에 관리하고 싶은 운영자
- 초안 자동화는 원하지만 공개 결정은 직접 하고 싶은 사람
- GEO + SEO 구조로 제목, 메타, 본문 약속을 맞추고 싶은 팀
- Blogger 공개 페이지의 실제 메타 반영 상태까지 확인하고 싶은 사용자

## 핵심 가치

### 블로그별 워크플로 분리

여행 블로그와 미스터리 블로그는 같은 프롬프트로 운영하면 품질이 쉽게 흐려집니다.
Bloggent는 블로그별 워크플로, 프롬프트, 카테고리 정체성, Google 연결 상태를 따로 유지합니다.

### 생성과 발행 분리

초안을 잘 만드는 것과, 공개해도 되는 글을 고르는 것은 다른 일입니다.
Bloggent는 생성 이후 검토와 수동 발행 단계를 분리해 운영 리스크를 낮춥니다.

### 주제 발굴 공급자 전환

Bloggent는 주제 발굴을 Gemini에만 고정하지 않습니다.
설정에서 `topic_discovery_provider`를 `gemini` 또는 `openai`로 바꿔 운영 상황에 맞게 선택할 수 있습니다.

- 2026-03-31까지는 Gemini 위주 운영
- 2026-04-01부터는 GPT 위주 운영
- 기본 워크플로의 주제 발굴 단계도 OpenAI 텍스트 모델 기준으로 전환 가능

### GEO + SEO 글 패키지

현재 글 생성 프롬프트는 검색엔진과 답변엔진 모두를 고려하는 구조를 목표로 합니다.

- 도입부에서 핵심 답을 먼저 제시
- 본문 H2마다 실제 하위 질문 해결
- `meta_description`, `excerpt`, 본문 약속 정렬
- FAQ와 이미지 문맥까지 함께 생성

관련 프롬프트:

- [`prompts/article_generation.md`](prompts/article_generation.md)
- [`prompts/travel_article_generation.md`](prompts/travel_article_generation.md)
- [`prompts/mystery_article_generation.md`](prompts/mystery_article_generation.md)

### 공개 메타 실검증

Bloggent는 Blogger API 응답만으로 메타 반영을 끝났다고 보지 않습니다.
발행 후 공개 페이지 기준으로 아래 메타 상태를 다시 검증합니다.

- `description`
- `og:description`
- `twitter:description`

대시보드의 메타 상태는 “본문 SEO 점수”가 아니라 “공개 메타 검증 상태”입니다.

## 주요 화면

- `/` 대시보드: 글 시작 액션, 작업 상태, 대표 프리뷰, 메타 상태 요약
- `/articles` 글 보관함: 제목, 메타, HTML, 최종 프리뷰, 수동 발행, 메타 검증
- `/jobs` 작업 목록: 백그라운드 상태, 실패, 재시도 이력 확인
- `/settings` 설정: Google OAuth, Blogger 가져오기, 블로그별 워크플로와 연결 값 관리
  오른쪽 플로팅 위젯으로 OpenAI 무료 토큰 사용량과 잔량 확인
- `/google` Google 데이터: Blogger, Search Console, GA4 기반 연결 상태와 일부 리포팅 확인

## 시스템 구성

- Web: Next.js 대시보드
- API: FastAPI
- Worker / Scheduler: Celery
- Data: PostgreSQL, Redis
- Asset Storage: MinIO
- Runtime: Docker Engine + Docker Compose

## 빠른 시작

1. `.env.example`을 `.env`로 복사하고 필수 값을 입력합니다.
2. 로컬 스택을 실행합니다.
3. 대시보드에서 블로그를 연결하고 주제를 발굴합니다.

### 로컬 실행

Windows:

```bat
start-server.bat
```

Mac/Linux:

```bash
docker compose up --build -d
```

접속:

- Web: `http://localhost:3001`
- API Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/healthz`

## 필수 환경 변수

- `SETTINGS_ENCRYPTION_SECRET`
- `OPENAI_API_KEY`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`

## 선택 환경 변수

- `GEMINI_API_KEY`
- `OPENAI_ADMIN_API_KEY`
- `PUBLIC_IMAGE_PROVIDER`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_BRANCH`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`
- `GITHUB_PAGES_ASSETS_DIR`

초기 부팅 권장 값:

- `PROVIDER_MODE=mock`
- `SEED_DEMO_DATA=true`

OpenAI 무료 토큰 위젯까지 쓰려면 아래 값도 선택적으로 설정할 수 있습니다.

- `OPENAI_ADMIN_API_KEY`

이 키는 조직 사용량 조회 API가 일반 프로젝트 키로 막히는 계정에서만 필요할 수 있습니다.

### 2. 스택 실행

```bash
docker compose up --build -d
```

### 3. 첫 운영 루프

1. `/settings`에서 Google OAuth를 연결합니다.
2. Blogger 블로그를 가져옵니다.
3. 블로그별 워크플로와 프롬프트를 확인합니다.
4. 필요하면 Search Console과 GA4 연결 값을 블로그별로 매핑합니다.
5. 대시보드에서 직접 주제를 넣거나 AI 주제 발굴을 실행합니다.
6. `/articles`에서 글 패키지와 최종 프리뷰를 검토합니다.
7. 수동으로 발행합니다.
8. 공개 메타 검증을 실행합니다.

## OpenAI 무료 토큰 위젯

`/settings` 화면 오른쪽에는 드래그 가능한 플로팅 위젯이 표시됩니다.
이 위젯은 오늘 UTC 기준 OpenAI 사용량을 읽어 아래 값을 보여줍니다.

- 대형 모델 사용량: `GPT-4o`, `o3` 등 무료 100만 토큰/일 그룹
- 소형 모델 사용량: `mini`, `nano` 등 무료 1천만 토큰/일 그룹
- 계산 방식: `input_tokens + output_tokens`
- 표시 값: 사용량, 남은 무료 토큰, 사용 비율

주의:

- 무료 토큰은 OpenAI 데이터 공유 활성화 트래픽에만 적용됩니다.
- 조직 사용량 조회 API는 계정에 따라 `OPENAI_ADMIN_API_KEY`가 필요할 수 있습니다.
## GitHub Pages

문서 사이트는 `docs/` 기반으로 GitHub Pages에 배포됩니다. 이미지 자산을 Pages로 서비스하려면 아래 변수를 설정합니다.

- `PUBLIC_IMAGE_PROVIDER=github_pages`
- `GITHUB_PAGES_OWNER`
- `GITHUB_PAGES_REPO`
- `GITHUB_PAGES_BRANCH`
- `GITHUB_PAGES_TOKEN`
- `GITHUB_PAGES_BASE_URL`
- `GITHUB_PAGES_ASSETS_DIR`

## 문서와 위키

- 문서: `docs/index.md`
- 위키: `wiki/Home.md`

## 레포 구조

- `apps/web`: 대시보드 UI
- `apps/api`: FastAPI + Worker
- `prompts`: 프롬프트 템플릿
- `docs`: GitHub Pages 문서
- `scripts`: 운영 보조 스크립트

## 보안 메모

- `SETTINGS_ENCRYPTION_SECRET`는 필수입니다.
- `GITHUB_PAGES_TOKEN`은 이미지 Pages 배포 시에만 필요합니다.
