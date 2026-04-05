# Deployment

## 배포 전 체크
1. 브랜드 문자열이 `동그리 자동 블로그전트`인지 확인
2. `/` -> `/dashboard` 리다이렉트 확인
3. `Admin / Integrations / Ops Monitor` 분리 동작 확인
4. UTF-8 한글 깨짐 여부 확인

## 운영 검증
```bash
docker compose --env-file .env exec -T web sh -lc "cd /app && npm run build"
docker compose --env-file .env exec -T api python -m pytest apps/api/tests/test_workspace_platform_services.py apps/api/tests/test_planner_service.py
```

## 런타임 확인
```bash
docker compose --env-file .env exec -T api python - <<'PY'
import json, urllib.request
u='http://127.0.0.1:8000/api/v1/workspace/mission-control'
print(json.load(urllib.request.urlopen(u)).get('workspace_label'))
PY
```

## Ops 동기화
- 화면: `/ops-health` -> 실시간 동기화
- CLI 폴백:
```bash
docker compose --env-file .env exec -T api python -m app.tools.ops_health_report
```

