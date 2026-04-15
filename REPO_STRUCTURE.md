# REPO_STRUCTURE

## 상위 구조
- `apps/web`: Next.js 대시보드/UI
- `apps/api`: FastAPI, 서비스 로직, Alembic, 테스트, 운영 스크립트
- `prompts/channels`: 채널별 프롬프트 백업/운영 원본
- `infra`: 배포/인프라 설정
- `wiki`: 운영 매뉴얼
- `scripts`: 공용 운영 스크립트
- `refactoring`: 리팩토링/실험 전용 영역

## 실행 경로와 책임
- Web(`apps/web`): 운영 UI와 API 연동
- API(`apps/api/app`): 도메인 서비스, 라우트, 모델, 통합 연동
- Worker/Scheduler: API 서비스 계층을 호출해 비동기 작업 수행
- Prompts(`prompts/channels`): 채널 운영 프롬프트의 기준 데이터

## 운영 경로 vs 리팩토링 경로
- 운영 경로:
  - `apps/web`
  - `apps/api/app`
  - `apps/api/alembic`
  - `prompts/channels`
- 리팩토링 경로:
  - `refactoring/scripts`
  - `refactoring/tests`
  - `refactoring/codex_write`
  - `refactoring/reports|tmp|output`

## 의존 방향
- `apps/web` -> `apps/api` (HTTP API)
- `apps/api/app/api` -> `apps/api/app/services` -> `apps/api/app/models`
- 운영 코드에서 `refactoring/*` 참조 금지

## 저장소 위생 규칙
- 앱 내부 생성 산출물(`apps/api/storage/*`)은 기본 비추적
- 시크릿/DB 관련 파일은 비추적 유지
- 실험 결과물은 `refactoring/*` 또는 로컬 비추적 경로에만 저장
