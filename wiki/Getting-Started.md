# Getting Started

## 1. 환경 준비
```bash
cd /mnt/d/Donggri_Platform/BloggerGent
docker compose --env-file .env up -d
```

## 2. 접속 확인
- Web: `http://127.0.0.1:7001`
- API: `http://127.0.0.1:7002/api/v1`

확인 항목:
1. `/` 접속 시 `/dashboard`로 이동
2. 타이틀에 `동그리 자동 블로그전트` 표시
3. Mission Control에 `Multi-Platform Marketing OS` 문구 표시

## 3. 연동 설정
1. `/settings`에서 OAuth/API 키 연결
2. `/admin`에서 운영 정책/자동화 값 점검
3. `/ops-health`에서 운영 점검 동기화 실행

## 4. 필수 빌드/테스트
```bash
docker compose --env-file .env exec -T web sh -lc "cd /app && npm run build"
docker compose --env-file .env exec -T api python -m pytest apps/api/tests/test_workspace_platform_services.py apps/api/tests/test_planner_service.py
```

