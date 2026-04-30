# PRD: BloggerGent ISO 9001 QMS 보완 4단계 구축

- 문서번호: PRD-QMS-ISO9001-2026-001
- 버전: 0.1
- 작성일: 2026-04-30
- 대상 레포: `D:\Donggri_Platform\BloggerGent`
- 참조 보고서: `docs/reports/iso-9001-gap-analysis-2026-04-30.md`
- 기준: ISO 9001:2015 + ISO 9001:2015/Amd 1:2024

## 1. 목적

BloggerGent를 단순 콘텐츠 자동화 도구가 아니라, 품질 목표·리스크·변경·부적합·감사·경영검토가 기록되는 ISO 9001형 품질경영시스템(QMS)으로 확장한다.

현재 BloggerGent는 다음 기반을 이미 갖고 있다.

- 콘텐츠 생성/게시 파이프라인
- Blogger/Cloudflare/Google/Search Console/R2 연동
- SEO/GEO/CTR/Lighthouse/PRN/Persona 품질 점수
- 테스트와 CI 보안 게이트
- Alembic 기반 DB 변경 이력
- 운영 문서와 스크립트

그러나 ISO 9001 관점에서는 `문서 통제`, `품질목표`, `리스크`, `CAPA`, `내부심사`, `경영검토`, `공급자 관리`, `릴리즈 승인 증적`이 별도 제품 기능과 운영 절차로 통제되어야 한다.

## 2. 제품 원칙

| 원칙 | 설명 |
|---|---|
| QMS는 독립 모듈 | 기존 admin/settings/analytics에 흩뿌리지 않고 `qms` 도메인으로 분리한다. |
| 운영 증적 우선 | 보기 좋은 화면보다 감사 추적 가능한 기록을 우선한다. |
| LIVE 기준 품질 | Blogger/Cloudflare 모두 LIVE/published 기준으로 KPI를 계산한다. |
| 문서 원본은 Git | QMS 절차/방침은 `docs/qms`, 운영 기록은 DB와 `storage/reports/qms`에 둔다. |
| 변경은 추적 가능해야 함 | 요구사항 ID, 변경 ID, 릴리즈 ID, CAPA ID를 서로 연결한다. |
| 자동화는 승인 흐름을 우회하지 않음 | 자동 게시/수정도 품질 목표와 부적합 기록 대상이다. |
| 기후변화 고려 포함 | ISO 9001:2015/Amd 1:2024에 맞춰 운영 장애/공급자/인프라 영향 판단을 기록한다. |

## 3. BloggerGent 구조 반영 방식

### 3.1 신규 경로

```text
apps/api/app/api/routes/qms.py
apps/api/app/services/qms/
apps/api/app/services/qms/qms_dashboard_service.py
apps/api/app/services/qms/qms_document_service.py
apps/api/app/services/qms/qms_risk_service.py
apps/api/app/services/qms/qms_capa_service.py
apps/api/app/services/qms/qms_audit_service.py
apps/api/app/services/qms/qms_supplier_service.py
apps/api/app/services/qms/qms_release_service.py
apps/api/app/schemas/qms.py
apps/api/tests/test_qms_*.py
apps/api/alembic/versions/0042_qms_core.py
apps/web/app/(dashboard)/qms/page.tsx
apps/web/components/dashboard/qms-workspace.tsx
docs/qms/
docs/prd/qms-iso9001-4-phase-prd.md
```

### 3.2 기존 경로와 연결

| 기존 구조 | QMS 연결 |
|---|---|
| `AnalyticsArticleFact`, `SyncedBloggerPost`, `SyncedCloudflarePost` | LIVE 품질 KPI 집계 소스 |
| `GoogleIndexUrlState` | 색인 known/indexed/unindexed KPI 소스 |
| `Job`, `PublicationRecord`, `ContentItem` | 게시 성공률, 실패율, 릴리즈 증적 소스 |
| `AuditLog` | QMS 이벤트 로그 보강 또는 참조 |
| `CloudflarePrnRun`, `CloudflareCategoryPersonaPack` | PRN/Persona 품질 목표와 리스크 증적 |
| `.github/workflows/*` | 변경관리/검증 증적 소스 |
| `.github/pull_request_template.md` | QMS 변경관리 체크리스트 반영 |
| `docs/qms/*` | 통제 문서 원본 |
| `storage/reports/qms/*` | 내부심사/경영검토/KPI 월간 기록 |

### 3.3 라우터 등록

`apps/api/app/api/router.py`에 추가한다.

```python
from app.api.routes import qms
api_router.include_router(qms.router, prefix="/qms", tags=["qms"])
```

### 3.4 UI 위치

대시보드 메뉴에 `QMS` 또는 `품질경영`을 추가한다.

```text
/qms
  - 품질 대시보드
  - 문서 통제
  - 리스크/기회
  - CAPA
  - 내부심사
  - 경영검토
  - 공급자
  - 릴리즈 기록
```

## 4. 4단계 구축 범위

## Phase 1. QMS 기반 문서화 + KPI 대시보드

### 목표

ISO 9001 인증 준비에 필요한 최소 QMS 뼈대를 만든다. 이 단계는 DB 기능보다 `범위/방침/목표/프로세스/문서 통제`를 고정하고, 현재 BloggerGent 데이터에서 품질 KPI를 읽어 대시보드로 보여주는 데 집중한다.

### 사용자 문제

운영자는 현재 SEO/GEO/CTR/Lighthouse/색인 상태를 볼 수 있지만, ISO 관점의 품질목표와 연결된 증적으로 볼 수 없다. 또한 문서가 깨져 있거나 분산되어 있어 “어떤 절차가 공식인지” 판단하기 어렵다.

### 주요 요구사항

| ID | 요구사항 | 우선순위 |
|---|---|---:|
| QMS-1-001 | `docs/qms`에 통제 문서 뼈대를 생성한다. | P0 |
| QMS-1-002 | 깨진 한글 문서(`AGENT.md`, `docs/*.md`)를 UTF-8 정상 한글로 복구한다. | P0 |
| QMS-1-003 | QMS 범위, 품질방침, 품질목표, 프로세스 맵, RACI를 작성한다. | P0 |
| QMS-1-004 | LIVE/published 기준 KPI를 계산하는 QMS dashboard API를 만든다. | P0 |
| QMS-1-005 | `/qms` UI에서 KPI, 결측, 리스크 placeholder, CAPA placeholder를 보여준다. | P0 |
| QMS-1-006 | PR 템플릿에 QMS 변경관리 체크리스트를 추가한다. | P1 |
| QMS-1-007 | ISO 9001:2015/Amd 1:2024 기후변화 관련성 판단 문서를 추가한다. | P1 |

### 문서 산출물

```text
docs/qms/quality-manual.md
docs/qms/qms-scope.md
docs/qms/quality-policy.md
docs/qms/quality-objectives.md
docs/qms/process-map.md
docs/qms/process-sipoc.md
docs/qms/role-responsibility-matrix.md
docs/qms/document-control-procedure.md
docs/qms/business-continuity-and-climate-context.md
docs/qms/evidence-index.md
```

### API

```text
GET /api/v1/qms/dashboard
GET /api/v1/qms/kpi/live-quality-completeness
GET /api/v1/qms/documents/catalog
```

### Dashboard KPI 정의

| KPI | 계산 기준 | 목표 |
|---|---|---:|
| LIVE SEO 점수 보유율 | published/live URL 중 `seo_score is not null` | 100% |
| LIVE GEO 점수 보유율 | published/live URL 중 `geo_score is not null` | 100% |
| LIVE CTR 점수 보유율 | published/live URL 중 `ctr/ctr_score is not null` | 100% |
| LIVE Lighthouse 점수 보유율 | published/live URL 중 `lighthouse_score is not null` | 100% |
| 색인 상태 known 비율 | LIVE URL 중 index status != unknown | 95% |
| 품질 게이트 통과율 | 최근 생성 건 quality_gate passed | 90% |
| 게시 성공률 | publication/job success | 98% |
| CAPA 기한 내 종료율 | Phase 2 전에는 N/A | 95% |

### DB 변경

Phase 1에서는 최소화한다. 문서 카탈로그는 파일 기반으로 시작한다. KPI는 기존 테이블에서 읽는다.

선택 DB:

```text
qms_kpi_snapshots
```

### 완료 기준

```powershell
Set-Location D:\Donggri_Platform\BloggerGent
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_qms_dashboard_service.py -q
python -m pytest apps/api/tests/test_qms_document_catalog.py -q
```

### 수용 기준

- `/api/v1/qms/dashboard`가 Blogger/Cloudflare LIVE 기준 품질 결측을 반환한다.
- `/qms` 화면에서 품질목표 대비 현재 상태가 보인다.
- QMS 문서에 문서번호, 버전, 소유자, 승인자, 시행일, 개정 이력이 있다.
- `AGENT.md`, 주요 `docs/*.md`의 mojibake가 제거된다.

## Phase 2. Risk Register + CAPA 시스템화

### 목표

품질 리스크와 부적합을 DB/API/UI에서 관리한다. 현재 수리 스크립트 중심 운영을 ISO 9001의 부적합/시정조치(CAPA) 흐름으로 바꾼다.

### 사용자 문제

문제가 발생하면 스크립트로 고치고 끝난다. 왜 발생했는지, 재발 방지는 무엇인지, 효과성 검증이 됐는지 추적되지 않는다.

### 주요 요구사항

| ID | 요구사항 | 우선순위 |
|---|---|---:|
| QMS-2-001 | QMS risk register DB/API/UI를 만든다. | P0 |
| QMS-2-002 | QMS CAPA DB/API/UI를 만든다. | P0 |
| QMS-2-003 | 품질 결측, 게시 실패, 색인 unknown, Lighthouse 누락을 CAPA 후보로 자동 제안한다. | P0 |
| QMS-2-004 | CAPA에 원인, 즉시조치, 시정조치, 재발방지, 효과성 검증을 기록한다. | P0 |
| QMS-2-005 | Risk와 CAPA를 요구사항/릴리즈/게시글/채널에 연결한다. | P1 |
| QMS-2-006 | 고위험 리스크는 Telegram 알림으로 보낸다. | P1 |
| QMS-2-007 | risk score = severity × likelihood × detectability로 산정한다. | P1 |

### DB

```text
qms_risks
qms_risk_reviews
qms_nonconformities
qms_corrective_actions
qms_capa_effectiveness_checks
qms_evidence_files
```

### API

```text
GET  /api/v1/qms/risks
POST /api/v1/qms/risks
PATCH /api/v1/qms/risks/{risk_id}
POST /api/v1/qms/risks/{risk_id}/review

GET  /api/v1/qms/capa
POST /api/v1/qms/capa
PATCH /api/v1/qms/capa/{capa_id}
POST /api/v1/qms/capa/{capa_id}/actions
POST /api/v1/qms/capa/{capa_id}/effectiveness-check
POST /api/v1/qms/capa/from-quality-gap
```

### UI

`/qms` 내 탭:

```text
리스크/기회
- 리스크 목록
- 점수/등급
- 담당자
- 통제 수단
- 다음 검토일

CAPA
- 부적합 목록
- 영향 채널/게시글
- 원인분석
- 시정조치
- 효과성 검증
- 종료 승인
```

### 자동 CAPA 후보 규칙

| 조건 | CAPA 후보 |
|---|---|
| LIVE 품질 점수 결측 1건 이상 | 품질 데이터 불완전 |
| 색인 unknown 비율 목표 초과 | 색인 상태 동기화 실패 |
| 게시 실패 2회 이상 반복 | 게시 프로세스 부적합 |
| PRN/persona 품질 점수 목표 미달 | 콘텐츠 패턴/페르소나 부적합 |
| Lighthouse 점수 70 미만 반복 | 공개 페이지 성능 부적합 |
| 시크릿 스캔 실패 | 보안 부적합 |

### 완료 기준

```powershell
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_qms_risk_service.py -q
python -m pytest apps/api/tests/test_qms_capa_service.py -q
```

### 수용 기준

- 품질 결측을 CAPA 후보로 생성할 수 있다.
- CAPA는 open/in_progress/effectiveness_pending/closed 상태를 가진다.
- CAPA 종료 시 효과성 검증 기록이 필수다.
- 리스크는 점수와 다음 검토일을 가진다.

## Phase 3. Change Control + Release Evidence + Supplier Control

### 목표

코드/DB/프롬프트/운영 설정 변경을 ISO 9001의 변경관리와 릴리즈 통제 흐름으로 관리한다. 외부 제공자(OpenAI, Google, Cloudflare, GitHub, Hugging Face)도 평가/리스크 대상으로 등록한다.

### 사용자 문제

현재 커밋/푸시/스크립트 실행은 빠르지만, ISO 심사에서 요구하는 변경 영향분석, 승인, 롤백, 릴리즈 증적이 부족하다.

### 주요 요구사항

| ID | 요구사항 | 우선순위 |
|---|---|---:|
| QMS-3-001 | 요구사항/변경 요청 레지스터를 만든다. | P0 |
| QMS-3-002 | 릴리즈 기록을 자동 생성한다. | P0 |
| QMS-3-003 | DB migration, API contract, prompt 변경 영향을 기록한다. | P0 |
| QMS-3-004 | 릴리즈별 테스트 증적과 rollback 계획을 저장한다. | P0 |
| QMS-3-005 | 외부 제공자 등록/평가/리뷰 기능을 만든다. | P1 |
| QMS-3-006 | Hugging Face/Nemotron persona 라이선스 attribution 기록을 관리한다. | P1 |
| QMS-3-007 | GitHub workflow 결과를 릴리즈 증적으로 연결한다. | P1 |

### DB

```text
qms_requirements
qms_change_requests
qms_release_records
qms_release_evidence
qms_suppliers
qms_supplier_reviews
qms_license_attributions
```

### API

```text
GET  /api/v1/qms/requirements
POST /api/v1/qms/requirements
PATCH /api/v1/qms/requirements/{requirement_id}

GET  /api/v1/qms/changes
POST /api/v1/qms/changes
PATCH /api/v1/qms/changes/{change_id}

GET  /api/v1/qms/releases
POST /api/v1/qms/releases/from-git
PATCH /api/v1/qms/releases/{release_id}

GET  /api/v1/qms/suppliers
POST /api/v1/qms/suppliers
PATCH /api/v1/qms/suppliers/{supplier_id}
POST /api/v1/qms/suppliers/{supplier_id}/review
```

### 변경 영향분석 필드

```text
change_id
requirement_id
change_type: code|db|prompt|config|data|workflow|docs
affected_paths
affected_apis
affected_tables
affected_channels
test_plan
rollback_plan
risk_ids
capa_ids
approval_status
approved_by
released_commit
released_at
```

### 공급자 관리 필드

```text
supplier_name
service_scope
criticality
risk_level
data_access_level
sla_or_dependency_notes
license_terms
last_reviewed_at
next_review_due_at
fallback_plan
```

### 완료 기준

```powershell
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_qms_change_control_service.py -q
python -m pytest apps/api/tests/test_qms_release_service.py -q
python -m pytest apps/api/tests/test_qms_supplier_service.py -q
```

### 수용 기준

- 커밋 SHA 기준 릴리즈 기록을 생성할 수 있다.
- DB migration 포함 변경은 rollback 계획 없이는 승인 완료가 불가하다.
- prompt 변경은 영향 채널/카테고리를 기록한다.
- 공급자 평가에는 criticality와 fallback plan이 필수다.

## Phase 4. Internal Audit + Management Review + Certification Evidence

### 목표

ISO 9001 심사에 필요한 주기적 내부심사, 경영검토, 증적 인덱스를 운영 가능하게 만든다.

### 사용자 문제

품질 활동은 있지만 월간 단위로 심사/검토/개선결정이 닫히지 않는다. 인증심사 시 “운영했다”는 증거가 부족하다.

### 주요 요구사항

| ID | 요구사항 | 우선순위 |
|---|---|---:|
| QMS-4-001 | 내부심사 계획/체크리스트/finding 기능을 만든다. | P0 |
| QMS-4-002 | 경영검토 회의록/action item 기능을 만든다. | P0 |
| QMS-4-003 | 월간 KPI snapshot을 저장한다. | P0 |
| QMS-4-004 | ISO 조항별 evidence index를 자동 생성한다. | P0 |
| QMS-4-005 | 감사 finding을 CAPA로 전환할 수 있다. | P0 |
| QMS-4-006 | 월간 PDF/Markdown 보고서를 생성한다. | P1 |
| QMS-4-007 | 인증심사 대응 export를 만든다. | P1 |

### DB

```text
qms_audit_programs
qms_audits
qms_audit_checklist_items
qms_audit_findings
qms_management_reviews
qms_management_review_actions
qms_kpi_snapshots
qms_evidence_index_items
```

### API

```text
GET  /api/v1/qms/audits
POST /api/v1/qms/audits
PATCH /api/v1/qms/audits/{audit_id}
POST /api/v1/qms/audits/{audit_id}/findings
POST /api/v1/qms/audit-findings/{finding_id}/convert-to-capa

GET  /api/v1/qms/management-reviews
POST /api/v1/qms/management-reviews
PATCH /api/v1/qms/management-reviews/{review_id}
POST /api/v1/qms/management-reviews/{review_id}/actions

POST /api/v1/qms/kpi/snapshot
GET  /api/v1/qms/evidence-index
POST /api/v1/qms/reports/monthly
```

### 내부심사 체크리스트 기본 항목

| ISO 조항 | 체크 항목 |
|---|---|
| 4.1 | 조직 상황/기후변화 관련성 검토 여부 |
| 4.2 | 이해관계자 요구사항 최신 여부 |
| 5.2 | 품질방침 게시/인지 여부 |
| 6.1 | 리스크 레지스터 검토 여부 |
| 6.2 | 품질목표 측정/미달 조치 여부 |
| 7.5 | 문서 개정/승인 통제 여부 |
| 8.5 | 게시 프로세스 증적 여부 |
| 8.7 | 부적합 출력 처리 여부 |
| 9.1 | KPI 분석 여부 |
| 9.2 | 내부심사 수행 여부 |
| 9.3 | 경영검토 수행 여부 |
| 10.2 | CAPA 효과성 검증 여부 |

### 경영검토 입력

```text
월간 KPI
품질목표 달성률
고객/운영자 피드백
부적합/CAPA 현황
리스크/기회 변화
공급자 이슈
보안/시크릿/CI 이슈
자동 게시 품질 문제
기후/인프라/외부 환경 이슈
개선 결정사항
```

### 보고서 출력

```text
storage/reports/qms/kpi-monthly-YYYY-MM.json
storage/reports/qms/internal-audit-YYYY-MM.md
storage/reports/qms/management-review-YYYY-MM.md
storage/reports/qms/evidence-index-YYYY-MM.md
```

### 완료 기준

```powershell
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_qms_audit_service.py -q
python -m pytest apps/api/tests/test_qms_management_review_service.py -q
python -m pytest apps/api/tests/test_qms_evidence_index_service.py -q
```

### 수용 기준

- 내부심사 finding을 CAPA로 전환할 수 있다.
- 경영검토 action item에 담당자/기한/상태가 있다.
- ISO 조항별 evidence index가 자동 생성된다.
- 월간 QMS 보고서가 Markdown 또는 JSON으로 저장된다.

## 5. 전체 데이터 모델 초안

```text
qms_documents
qms_document_revisions
qms_kpi_snapshots
qms_risks
qms_risk_reviews
qms_nonconformities
qms_corrective_actions
qms_capa_effectiveness_checks
qms_requirements
qms_change_requests
qms_release_records
qms_release_evidence
qms_suppliers
qms_supplier_reviews
qms_license_attributions
qms_audit_programs
qms_audits
qms_audit_checklist_items
qms_audit_findings
qms_management_reviews
qms_management_review_actions
qms_evidence_files
qms_evidence_index_items
```

## 6. 권한 정책

| 기능 | 권한 |
|---|---|
| QMS dashboard 조회 | 관리자 |
| 문서 카탈로그 조회 | 관리자 |
| 문서 승인/폐기 | 관리자 |
| Risk/CAPA 생성/수정 | 관리자 |
| CAPA 종료 | 관리자 + 효과성 검증 필수 |
| 릴리즈 승인 | 관리자 |
| 내부심사 finding 등록 | 관리자 |
| 경영검토 종료 | 관리자 |
| 보고서 export | 관리자 |

현재 `AdminMutationRoute`, `require_admin_auth` 패턴을 따른다.

## 7. 비기능 요구사항

| 항목 | 요구사항 |
|---|---|
| 감사 추적 | 모든 생성/수정/종료 이벤트는 `AuditLog` 또는 QMS event payload에 남긴다. |
| 데이터 보존 | QMS 기록은 삭제하지 않고 `archived` 상태로 보존한다. |
| 보안 | 외부 API 키, OAuth token, raw persona row는 QMS 기록에 저장하지 않는다. |
| 성능 | `/qms/dashboard`는 2초 이내 응답을 목표로 한다. |
| 호환성 | 기존 게시/분석/프롬프트 기능을 변경하지 않고 읽기 연결부터 시작한다. |
| 추적성 | Requirement → Change → Release → Risk/CAPA → Evidence 연결이 가능해야 한다. |
| 문서 인코딩 | 모든 QMS 문서는 UTF-8 한글 정상 표시를 필수로 한다. |

## 8. 구현 순서

```text
1. docs/qms 문서 뼈대 및 mojibake 복구
2. qms dashboard service + API + UI
3. qms core DB migration: risks, capa, kpi snapshots
4. Risk/CAPA UI
5. change/release/supplier DB + API
6. internal audit/management review DB + API
7. monthly report/evidence index generator
8. CI/PR template 강화
```

## 9. 테스트 전략

| 레벨 | 테스트 |
|---|---|
| Unit | QMS KPI 계산, risk score, CAPA state transition |
| API | `/api/v1/qms/*` 권한/응답 schema |
| DB | Alembic upgrade/downgrade, FK, soft archive |
| UI | `/qms` dashboard render, tab navigation |
| Regression | 기존 analytics/cloudflare/blogger 테스트 영향 없음 |
| Security | admin auth, secret redaction, raw persona 미저장 |

권장 테스트 명령:

```powershell
Set-Location D:\Donggri_Platform\BloggerGent
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/tests/test_qms_dashboard_service.py -q
python -m pytest apps/api/tests/test_qms_risk_service.py -q
python -m pytest apps/api/tests/test_qms_capa_service.py -q
python -m pytest apps/api/tests/test_qms_change_control_service.py -q
python -m pytest apps/api/tests/test_qms_audit_service.py -q
```

## 10. Phase별 성공 지표

| Phase | 성공 지표 |
|---|---|
| Phase 1 | QMS 문서 10개 이상 생성, `/qms/dashboard`에서 LIVE 품질 결측 표시 |
| Phase 2 | CAPA end-to-end 1건 생성/종료 가능, risk register 7건 이상 운영 |
| Phase 3 | 릴리즈 기록 1건 자동 생성, 공급자 5개 등록 |
| Phase 4 | 내부심사 1회, 경영검토 1회, evidence index 생성 |

## 11. 제외 범위

- 외부 인증기관 심사 예약/비용 관리
- ISO 9001 원문 전체 복제 또는 배포
- 전사 HR 시스템 수준의 교육관리
- 복잡한 전자서명 시스템
- QMS 기록의 물리 삭제 기능

## 12. 의사결정 필요사항

| 항목 | 기본 제안 |
|---|---|
| QMS UI 위치 | `/qms` 단일 워크스페이스 |
| QMS 문서 언어 | 한국어 |
| QMS 기록 삭제 정책 | 삭제 금지, archived 처리 |
| CAPA ID 포맷 | `CAPA-YYYY-NNN` |
| Risk ID 포맷 | `RISK-YYYY-NNN` |
| Requirement ID 포맷 | `REQ-YYYY-NNN` |
| Release ID 포맷 | `REL-YYYYMMDD-NN` |
| 월간 보고서 저장 | DB + `storage/reports/qms` |

## 13. Phase 1 바로 실행 체크리스트

```powershell
Set-Location D:\Donggri_Platform\BloggerGent

New-Item -ItemType Directory -Force docs\qms | Out-Null
New-Item -ItemType Directory -Force docs\prd | Out-Null
New-Item -ItemType Directory -Force storage\reports\qms | Out-Null

@(
  'quality-manual.md',
  'qms-scope.md',
  'quality-policy.md',
  'quality-objectives.md',
  'process-map.md',
  'process-sipoc.md',
  'role-responsibility-matrix.md',
  'document-control-procedure.md',
  'business-continuity-and-climate-context.md',
  'evidence-index.md'
) | ForEach-Object {
  $path = Join-Path docs\qms $_
  if (-not (Test-Path $path)) {
    @"
# $($_ -replace '.md','')

| 항목 | 값 |
|---|---|
| 문서번호 | QMS-TBD |
| 버전 | 0.1 |
| 소유자 | Quality Owner |
| 승인자 | Product Owner |
| 시행일 | 2026-04-30 |
| 상태 | Draft |

## 목적

## 적용 범위

## 절차/기준

## 기록

## 개정 이력

| 버전 | 일자 | 변경 내용 | 승인자 |
|---|---|---|---|
| 0.1 | 2026-04-30 | 초안 생성 | Product Owner |
"@ | Set-Content -Path $path -Encoding UTF8
  }
}
```
