---
title: 보안 운영 기준
---

# 보안 운영 기준

이 문서는 BloggerGent 저장소의 보안 기준을 코드/운영으로 분리해 관리하기 위한 기준이다.

## 1. 레포 코드로 강제되는 보안

다음 항목은 저장소에 포함된 파일로 자동 강제된다.

- CI 보안 게이트: `.github/workflows/ci-security.yml`
  - Dependency Review
  - Secret Scan(gitleaks)
  - API/Web 빌드 및 기본 테스트
- 정적 분석(CodeQL): `.github/workflows/codeql.yml`
- 종속성 자동 업데이트: `.github/dependabot.yml`
- PR 보안 체크리스트: `.github/pull_request_template.md`
- 코드 오너 승인 경로: `.github/CODEOWNERS`
- 로컬/CI 시크릿 스캔 규칙:
  - `.gitleaks.toml`
  - `.pre-commit-config.yaml`

## 2. GitHub UI/API에서만 가능한 보안

다음 항목은 저장소 파일만으로는 강제되지 않는다.

- 브랜치 보호(직접 푸시 금지, 필수 상태 체크, 리뷰 필수)
- Secret Scanning / Push Protection 활성화
- Dependabot Alerts 정책
- 코드 스캐닝 경고 dismiss 정책

이 항목은 `scripts/apply_github_security_baseline.ps1`로 자동 적용할 수 있다.

## 3. 인프라 자격증명 기준

`docker-compose.yml`은 약한 기본 비밀번호를 허용하지 않는다.

- `POSTGRES_PASSWORD` 필수
- `MINIO_ROOT_USER` 필수
- `MINIO_ROOT_PASSWORD` 필수

환경변수가 없으면 `docker compose config` 단계에서 즉시 실패한다.

## 4. 시크릿 관리 원칙

- API 키/토큰/암호는 코드에 하드코딩하지 않는다.
- `.env`, `secrets/`, 인증서(`*.pem`, `*.key`, `*.p12`, `*.pfx`)는 git 추적 금지.
- 유출이 의심되면 즉시 폐기(revoke) 후 교체한다.

## 5. 운영 점검 절차

### 로컬

```powershell
Set-Location D:\Donggri_Platform\BloggerGent
docker compose config
pre-commit run --all-files
```

### GitHub

- PR에서 `CI Security Gate`, `CodeQL` 상태 확인
- Dependabot PR 자동 생성 확인
- 브랜치 보호 규칙에 상태 체크 필수 연결 확인
