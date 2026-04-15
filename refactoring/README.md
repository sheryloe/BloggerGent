# Refactoring Workspace

이 폴더는 운영 배포 경로와 분리된 리팩토링/실험 전용 작업 공간이다.

- `scripts/`: 실험/마이그레이션 보조 스크립트
- `tests/`: 실험 코드 검증 테스트
- `codex_write/`: codex_write 관련 실험 코드/패키지
- `reports/`, `tmp/`, `output/`: 로컬 실행 산출물(비추적)

운영 반영 시에는 검증된 최소 코드만 운영 경로로 이동한다.
