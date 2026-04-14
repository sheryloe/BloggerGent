# Source Usage Report Guide

## 목적
- `D:\Donggri_Platform\BloggerGent` 전체 경로를 스캔해 소스 사용성을 `Active / Review / Inactive`로 분류한다.
- 결과를 정리 의사결정용 리포트로 제공한다(삭제/이동 자동 수행 없음).

## 생성 파일
- `docs/reports/source-usage-report.json`
- `docs/reports/source-usage-tree.txt`
- `docs/reports/source-usage-report.html`

## 실행 방법 (PowerShell)
```powershell
Set-Location D:\Donggri_Platform\BloggerGent
powershell -ExecutionPolicy Bypass -File scripts/analyze_source_usage.ps1
```

## 분류 기준
- `Active`
  - Docker Compose / CI workflow seed 경로
  - seed에서 도달 가능한 Python import 그래프 경로
  - compose/workflow에서 직접 참조된 경로
- `Review`
  - 문서/스크립트/운영보조 성격 경로(삭제 리스크 존재)
  - tracked 이지만 reachability 근거가 약한 경로
- `Inactive`
  - 캐시/백업/생성물/로컬 보조 경로
  - 실행 경로와 무관한 ignored 로컬 경로

## 후속 정리 절차 (권장)
1. HTML 리포트에서 `Inactive` 후보를 우선 검토한다.
2. `tracked=true` 또는 `risk=high` 항목은 별도 검증 후 처리한다.
3. `Review` 항목은 운영자 확인을 거쳐 Active/Inactive로 확정한다.
4. 실제 삭제/이동은 별도 배치 스크립트로 분리 실행한다.

