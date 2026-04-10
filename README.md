# Bloggent

동그리 운영팀용 멀티채널 콘텐츠 운영 콘솔입니다.  
`Blogger + Cloudflare + YouTube + Instagram` 채널을 하나의 대시보드에서 운영하고, 플래너/품질/색인/자동화 루프를 통합 관리합니다.

**Quick Links**
- [What Is / Why](#what-is--why)
- [Install with AI](#install-with-ai)
- [Latest Release](#latest-release)
- [Quick Start (PowerShell)](#quick-start-powershell)
- [Telegram & Automation](#telegram--automation)
- [Security / Docs](#security--docs)

## What Is / Why
Bloggent는 단순 생성기가 아니라 운영 콘솔입니다.

- 월간 플래너(슬롯/브리프/생성)
- 콘텐츠 운영(리뷰 큐, 승인/적용, 재실행)
- 분석(SEO/GEO/CTR/Lighthouse/색인 상태)
- 채널별 프롬프트 플로우와 파일 백업 동기화
- Telegram 운영 제어(`/ops`, `/help`) + 자동화

운영 목적:
- 콘텐츠 생성 품질과 게시 성공률을 함께 관리
- 실시간 운영 리스크를 사전에 탐지
- 채널 확장 시에도 같은 운영 규칙으로 수평 확장

## Install with AI
아래 프롬프트를 AI 에이전트에 그대로 입력하면, 로컬 실행/검증 루프를 바로 시작할 수 있습니다.

```text
이 저장소를 Windows + PowerShell 기준으로 실행해.
요구사항:
1) .env.example을 .env로 복사
2) docker compose up -d --build
3) /healthz, /api/v1, /dashboard 확인
4) 실패 시 원인 로그(api/web/worker/scheduler) 정리 후 수정
5) 실행 결과와 수정 파일 목록을 보고
```

## Latest Release
**2026-04-10**

- LIVE(published) 기준 Lighthouse 동기화 경로 강화
- Help 카탈로그 API 추가: `GET /api/v1/help/topics`, `GET /api/v1/help/topics/{topic_id}`
- Telegram Phase 1/2 확장:
  - `/help`, `/help ops`, `/help settings`, `/help runbook <id>`, `/help search <keyword>`
  - `POST /api/v1/telegram/poll-now`
  - `GET/PUT /api/v1/telegram/subscriptions`
  - `GET /api/v1/telegram/telemetry`
- Telegram 운영 API 관리자 인증 의존성 추가
- `/help` 운영형 페이지 및 Settings Telegram 테스트 블록 추가

## Screenshots
![Dashboard](docs/assets/dashboard.png)

## Features
| 영역 | 핵심 기능 | 주요 엔드포인트/화면 |
| --- | --- | --- |
| Mission Control | 채널/런타임/경고 통합 모니터링 | `/dashboard`, `GET /api/v1/workspace/mission-control` |
| Planner | 월간 캘린더, 일간 브리프 분석/적용, 슬롯 생성 | `/planner`, `/api/v1/planner/*` |
| Content Ops | 리뷰 큐 승인/적용/재실행, 학습 루프 제어 | `/content-ops`, `/api/v1/content-ops/*` |
| Analytics | 월간 요약, 기사 팩트, Lighthouse/색인 상태 조회 | `/analytics`, `/api/v1/analytics/*` |
| Google | 색인 상태 새로고침, 수동 요청, 쿼터 확인 | `/google`, `/api/v1/google/*` |
| Prompt Flow | 채널별 단계 프롬프트 편집 + 백업 동기화 | `/settings`, `/api/v1/channels/{id}/prompt-flow` |
| Telegram Ops | `/ops`, `/help` 명령 운영, 수동 poll, 구독/텔레메트리 | `/api/v1/telegram/*`, `/help` |

## Tech Stack
| Layer | Stack |
| --- | --- |
| Web | Next.js 14, TypeScript, Tailwind |
| API | FastAPI, SQLAlchemy, Pydantic |
| Worker | Celery + Redis |
| DB | PostgreSQL 16 |
| Infra | Docker Compose |
| External | Blogger, Google Search Console/GA4, Cloudflare, OpenAI/Gemini, Telegram |

## Quick Start (PowerShell)
### 1) Clone + Env
```powershell
Set-Location D:\
git clone https://github.com/sheryloe/BloggerGent.git
Set-Location D:\Donggri_Platform\BloggerGent
Copy-Item .env.example .env -Force
```

### 2) Start
```powershell
Set-Location D:\Donggri_Platform\BloggerGent
docker compose up -d --build
```

### 3) Health Check
```powershell
Invoke-RestMethod http://localhost:8000/healthz
Invoke-RestMethod http://localhost:8000/api/v1/settings/model-policy
```

### 4) Optional Bootstrap
```powershell
Set-Location D:\Donggri_Platform\BloggerGent
docker compose --profile bootstrap run --rm bootstrap
```

## Run Modes
| Mode | 설명 | 권장 시점 |
| --- | --- | --- |
| `mock` | 외부 연동 최소화, 화면/흐름 검증 중심 | 초기 셋업 |
| `live` + `draft` | 실연동 + 초안 게시 | 운영 전 검증 |
| `live` + `publish` | 실게시 운영 | 검증 완료 후 |

핵심 환경값:
```dotenv
PROVIDER_MODE=live
DEFAULT_PUBLISH_MODE=draft
AUTOMATION_MASTER_ENABLED=false
AUTOMATION_TELEGRAM_ENABLED=true
AUTOMATION_GOOGLE_INDEXING_ENABLED=true
```

## Channel Workflows
### Blogger
`topic_discovery -> article_generation -> image_prompt_generation -> related_posts -> image_generation -> html_assembly -> publishing`

### Cloudflare
채널/카테고리 단위 7단계 프롬프트를 사용하고, 백업 디렉터리(`prompts/channels/cloudflare/...`)와 동기화합니다.

### YouTube / Instagram
플랫폼별 전용 단계(메타데이터/썸네일/패키징/게시/리뷰)로 분리 운영합니다.

## Telegram & Automation
### Phase 1
- 명령:
  - `/ops ...` (기존 계약 유지)
  - `/help`, `/help ops`, `/help settings`, `/help runbook <id>`, `/help search <keyword>`
- API:
  - `POST /api/v1/telegram/test`
  - `POST /api/v1/telegram/poll-now`
  - `GET /api/v1/help/topics`
  - `GET /api/v1/help/topics/{topic_id}`

### Phase 2
- 운영 API:
  - `GET/PUT /api/v1/telegram/subscriptions`
  - `GET /api/v1/telegram/telemetry?days=7`
- 운영 강화:
  - 인라인 메뉴(`/ops menu`)
  - 고위험 액션 2단계 확인(approve/apply)
  - delivery dedupe + rate-limit
- DB 테이블:
  - `telegram_chat_bindings`
  - `telegram_subscriptions`
  - `telegram_command_events`
  - `telegram_delivery_events`

### 운영 점검 명령 (PowerShell)
```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/telegram/test -ContentType "application/json" -Body '{"message":"ops test"}'
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/telegram/poll-now -ContentType "application/json" -Body '{}'
Invoke-RestMethod http://localhost:8000/api/v1/telegram/telemetry?days=7
```

## Troubleshooting
### API/WEB가 안 뜰 때
```powershell
Set-Location D:\Donggri_Platform\BloggerGent
docker compose logs -f api
docker compose logs -f web
docker compose logs -f worker
docker compose logs -f scheduler
```

### 마이그레이션 적용
```powershell
Set-Location D:\Donggri_Platform\BloggerGent
$env:DATABASE_URL='postgresql+psycopg2://bloggent:bloggent@localhost:15432/bloggent'
python -m alembic -c apps/api/alembic.ini upgrade heads
```

### 테스트 실행
```powershell
Set-Location D:\Donggri_Platform\BloggerGent
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_telegram_help_service.py -q
```

## Security / Docs
- 관리자 인증:
  - `admin_auth_enabled`, `admin_auth_username`, `admin_auth_password`
  - Telegram 관리 API는 관리자 인증 의존성 적용
- 문서:
  - [`wiki/Getting-Started.md`](wiki/Getting-Started.md)
  - [`wiki/Workflow.md`](wiki/Workflow.md)
  - [`wiki/Deployment.md`](wiki/Deployment.md)
  - [`wiki/Security.md`](wiki/Security.md)
