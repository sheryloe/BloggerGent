# 동그리 자동 블로그전트

동그리 자동 블로그전트는 블로그 중심의 생성, 자산, 업로드, 운영 흐름을 한 화면에서 관리하는 운영 콘솔입니다.

## 현재 구조
- 메인 진입: `/` -> `/dashboard`
- 운영 메인: `/dashboard`
- 연동 설정: `/settings`
- 관리자 설정: `/admin`
- 운영 모니터: `/ops-health`
- 가이드: `/guide`

## 주요 화면
- `/dashboard`: 생성 / 자산 / 업로드 / 운영 4묶음 중심 미션 컨트롤
- `/planner`: 타입 -> 채널 기준 게시 플래너
- `/content-ops`: 타입별 콘텐츠 운영 화면
- `/analytics`: 채널별 분석 화면
- `/google`: 연결된 블로그 기준 SEO / 색인 화면

## 로컬 실행
```bash
cd /mnt/d/Donggri_Platform/BloggerGent
docker compose --env-file .env up -d
```

- Web: [http://127.0.0.1:7001](http://127.0.0.1:7001)
- API: [http://127.0.0.1:7002/api/v1](http://127.0.0.1:7002/api/v1)
- 테스트 포트: `7004`

## GitHub Pages 정리
- GitHub Pages는 정적 문서와 공개 자산 확인 용도로만 사용합니다.
- 실제 운영 UI 기준 화면은 Docker 환경의 `/dashboard` 입니다.
- `apps/web/out`은 정적 산출물이며, 운영 검증은 Docker 컨테이너 안에서 수행합니다.

## 운영 점검 동기화
- UI: `/ops-health` 상단의 `실시간 동기화`
- 수동 명령:
```bash
docker compose --env-file .env exec -T api python -m app.tools.ops_health_report
```

## 기본 검증
```bash
docker compose --env-file .env exec -T web sh -lc "cd /app && rm -rf .next && npm run build"
docker compose --env-file .env exec -T api python -m pytest apps/api/tests/test_workspace_platform_services.py apps/api/tests/test_planner_service.py
docker compose --env-file .env exec -T api python - <<'PY'
import json, urllib.request
u='http://127.0.0.1:8000/api/v1/workspace/mission-control'
print(json.load(urllib.request.urlopen(u)).get('workspace_label'))
PY
```

## 문서
- 위키 시작: `wiki/Home.md`
- 운영, 배포, 보안, 워크플로 문서는 `wiki/` 아래에서 관리합니다.
