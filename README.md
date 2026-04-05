# Donggr AutoBloggent

나만의 자동화 블로그 시스템을 넘어, **Blogger + YouTube + Instagram** 운영을 하나의 OS로 묶는 개인형 마케팅 워크스페이스입니다.  
핵심은 게시 자체가 아니라 **게시 → 측정 → 분석 → 수정 → 재배포** 루프 자동화입니다.

## v0.1 만드는 중

v0.1은 아래 항목을 우선 구현합니다.

- OAuth 콜백 + 토큰 갱신(플랫폼 자격 증명 저장 포함)
- YouTube 업로드 어댑터(메타데이터/썸네일/기본 private 흐름)
- Instagram capability-gated publish 어댑터(Professional 계정 전제)
- Search Console / GA4 수집 파이프라인 + SEO/CTR 피드백 큐
- 에이전트 런타임 추적(Claude CLI / Codex CLI / Gemini CLI)

## 서비스 구조

- 메인 진입: `/` → `/dashboard` 자동 리다이렉트
- 운영 콘솔: `/dashboard`
- 운영 하위 화면: `/planner`, `/content-ops`, `/analytics`, `/google`, `/settings`, `/ops-health`

### 운영 플로우

1. 콘텐츠 생성: 플랫폼별 에이전트 팩으로 초안/이미지/메타 생성
2. 게시 실행: 채널 어댑터로 발행 또는 예약
3. 성과 수집: Search Console, GA4, 플랫폼 지표 수집
4. 분석/점수화: SEO/CTR/성과 점수 계산
5. 수정/재배포: 리라이트/재큐잉 후 다시 배포

## 왜 Donggr AutoBloggent인가

- 단일 플랫폼 도구가 아니라 멀티 채널 운영 루프를 통합
- 무료 티어 + OAuth 중심으로 시작 가능한 구조
- CLI 기반 에이전트 실행 기록/상태/재시도 추적으로 운영 안정성 확보
- 루트 운영 진입(`/`)과 실제 콘솔(`/dashboard`) 흐름을 단순화

## GitHub Pages 운영 정리

### 목적

- GitHub Pages는 **문서/정적 공개 자산 배포 경로**로 사용합니다.
- 운영 메인 화면은 항상 `web` 서비스(`127.0.0.1:7001`)의 `/dashboard` 기준으로 봅니다.

### 현재 동작 기준

- 로컬 운영 진입: `http://127.0.0.1:7001/` → `/dashboard`
- 로컬 API 기준: `http://127.0.0.1:7002/api/v1`
- 정적 산출물 경로: `apps/web/out` (필요 시 export)
- 기본 공개 에셋 전략: Cloudflare R2 우선, GitHub Pages는 보조 정적 경로

### 운영 원칙

- 운영 대시보드/업무 플로우 문서는 `wiki/` 기준으로 유지합니다.
- GitHub Pages 자산 정리는 마이그레이션 검증 완료 후에만 수행합니다.
- 공개 URL 변경 시 README와 `wiki/Deployment`, `wiki/Getting-Started`를 동시에 갱신합니다.

## 파일 구조 (핵심)

```text
BloggerGent/
├─ README.md
├─ apps/
│  └─ web/
│     ├─ app/
│     │  ├─ page.tsx                      # 루트 리다이렉트 (/ -> /dashboard)
│     │  └─ (dashboard)/
│     │     ├─ layout.tsx
│     │     └─ dashboard/page.tsx         # 운영 홈 (/dashboard)
│     ├─ components/
│     │  ├─ dashboard/
│     │  └─ marketing/hero-collage-image.tsx
│     └─ public/marketing/hero-collage.svg
└─ docker-compose.yml
```

## WSL 실행 방법

```bash
cd /mnt/d/Donggri_Platform/BloggerGent
docker compose --env-file .env up -d
```

웹: `http://127.0.0.1:7001`  
API: `http://127.0.0.1:7002`

## TEST 트랙(7004) 원칙

- 기존 프로젝트와 병렬로 `TEST` 트랙을 운영
- `WEB_PORT=7004` 포함 별도 env/볼륨으로 격리
- 기존 운영 트랙과 충돌 없이 확장 기능 검증

## 필수 테스트 규칙

모든 검증은 **transient `testdocker`** 컨테이너에서 실행합니다.

```bash
cd /mnt/d/Donggri_Platform/BloggerGent
docker run -d --name testdocker -w /workspace node:20-bookworm-slim sleep infinity
docker cp . testdocker:/workspace/repo
docker exec testdocker bash -lc "cd /workspace/repo/apps/web && npm ci && GITHUB_ACTIONS=true npm run build"
docker rm -f testdocker
```

## SEO/CTR 운영 포인트

- Search Console `searchAnalytics.query`로 검색 성과 추적
- URL Inspection은 상태 점검 중심으로 사용
- GA4로 트래픽/행동 품질 신호를 수집
- 점수 기반으로 콘텐츠 리라이트 우선순위 자동화

## 홍보 문구(서비스 페이지/공유용)

Donggr AutoBloggent는 글 자동 생성 도구가 아닙니다.  
**당신만의 블로그·유튜브·인스타 운영 시스템**으로, 게시 이후의 성과 개선까지 자동화하는 Marketing OS입니다.