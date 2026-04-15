# Bloggent

Blogger/Cloudflare 멀티 채널 콘텐츠 운영 플랫폼입니다.
운영 기준과 구조 문서를 먼저 확인한 뒤 기능 작업을 진행하세요.

## Quick Links
- [운영 기준 (AGENT)](AGENT.md)
- [저장소 구조 (REPO_STRUCTURE)](REPO_STRUCTURE.md)
- [서비스 구조](apps/api/app/services/STRUCTURE.md)
- [위키 시작 가이드](wiki/Getting-Started.md)

## 실행 구조
- Web: `apps/web` (Next.js)
- API: `apps/api/app` (FastAPI)
- DB Migration: `apps/api/alembic`
- Prompt Source: `prompts/channels`
- Refactoring Workspace: `refactoring`

## Quick Start (PowerShell)
```powershell
Set-Location D:\Donggri_Platform\BloggerGent
Copy-Item .env.example .env -Force
docker compose up -d --build
Invoke-RestMethod http://localhost:8000/healthz
```

## 운영 원칙
- 운영 브랜치는 `main` 기준
- DB/시크릿/로컬 산출물은 git 비추적
- 리팩토링/실험 코드는 `refactoring/`에서만 작업

## 참고
- 자세한 기능/운영 절차는 `wiki/` 문서를 기준으로 관리합니다.
