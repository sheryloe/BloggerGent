# Content Ops Status

기준 시각: 2026-03-26 Asia/Seoul

## 현재 단계

- 현재 단계: `Phase 3 진행 중`
- 해석:
  - `Phase 1` 완료
  - `Phase 2` 완료
  - `Phase 3` 부분 완료

## 완료된 항목

### Phase 1

- Blogger 라이브 글 5분 동기화 스캔
- 변경 글 자동 분석 및 리뷰 항목 저장
- `content_review_items`, `content_review_actions` 영속 테이블 추가
- `/content-ops/status`, `/content-ops/reviews`, `/content-ops/sync-now` API 추가
- 대시보드 지표 추가
  - `review_queue_count`
  - `high_risk_count`
  - `auto_fix_applied_today`
  - `learning_snapshot_age`
- `/content-ops` 전용 UI 추가

### Phase 2

- 초안 리뷰 자동 트리거
- 초안 저위험 자동수정
  - `meta_description`
  - `excerpt`
  - `faq_section`
- 발행 후 메타 검증 자동 트리거
- 발행본 저위험 자동수정
  - `meta_description`
  - `search_description`
- Telegram ops 명령 추가
  - `/ops status`
  - `/ops queue`
  - `/ops review <id>`
  - `/ops approve <id>`
  - `/ops apply <id>`
  - `/ops reject <id>`
  - `/ops rerun <id>`
  - `/ops sync-now`
  - `/ops pause-learning`
  - `/ops resume-learning`
- 허용되지 않은 `chat_id` 명령 무시 및 로그 기록

### Phase 3

- curated learning snapshot JSONL 생성
- prompt memory JSON 생성
- `training_runs` dataset snapshot에 curated learning 합류
- learning pause/resume 설정값 및 Telegram 명령 반영
- training 완료/실패/paused Telegram 알림 반영

## 방금 검증한 운영 상태

- DB migration 적용 완료
  - revision: `0013_content_review_ops`
- API 정상 응답 확인
  - `/healthz`
  - `/api/v1/content-ops/status`
- scheduler 정상 동작 확인
  - `15초` Telegram polling 발행
  - `5분` live content scan 발행
- worker 정상 동작 확인
  - `poll_telegram_ops` 실행 성공
  - `run_content_ops_scan` 실행 성공
- 실데이터 반영 확인
  - 최근 live sync review 다수 생성
  - learning snapshot 생성됨

## 아직 안 된 항목

### PRD 기준 미완료

- prompt recommendation 생성 및 버전 관리
- prompt recommendation을 운영자가 검토할 수 있는 UI/API

### 운영 보강 기준 미완료

- `/content-ops` 화면에서 learning pause/resume 버튼 제공
- 리뷰 필터링 강화
  - blog
  - risk
  - approval
  - review kind
- Telegram 알림 메시지 포맷 고도화
- review/apply/reject 감사 로그 조회 UX 보강
- 실제 Telegram 명령 round-trip 수동 검증
- 실제 고위험 리뷰 케이스 수동 검증

## 현재 판단

- 지금 상태는 `실사용 가능한 MVP` 입니다.
- 이유:
  - 리뷰 생성
  - 자동수정
  - Telegram 승인 플로우
  - 학습 스냅샷 생성
  - scheduler 실동작
  - API/UI 연결
  - 여기까지는 돌아갑니다.
- 다만 `Phase 3 완료`로 보려면 prompt recommendation이 추가되어야 합니다.

## 다음 작업 우선순위

### 1순위

- Telegram 실명령 검증
  - `/ops status`
  - `/ops queue`
  - `/ops sync-now`
- 고위험 리뷰 샘플 1건 인위 생성 후
  - 승인 전 apply 차단 확인
  - 승인 후에도 live 본문 apply 차단 확인

### 2순위

- prompt recommendation 엔진 추가
  - 블로그별 추천안 생성
  - 버전 저장
  - 자동 반영 없이 제안만 저장

### 3순위

- `/content-ops` UI 보강
  - pause/resume 버튼
  - 필터/검색
  - 최근 action 타임라인

### 4순위

- 운영 안정화
  - alert rate limit
  - scheduler/worker observability
  - 실패 재시도 정책 정리

## 바로 실행할 일

1. 텔레그램에서 `/ops status`와 `/ops sync-now` 수동 검증
2. `/content-ops` 화면에서 review 목록/상태 확인
3. prompt recommendation 구현 시작
