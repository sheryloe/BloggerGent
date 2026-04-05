# FAQ

## Q. 메인 화면이 어디인가요?
- `http://127.0.0.1:7001/` 접속 시 `/dashboard`로 이동합니다.

## Q. 브랜드 표기는 무엇인가요?
- 모든 기본 표기는 `동그리 자동 블로그전트`입니다.

## Q. Admin과 Integrations 차이는?
- Admin: 시스템 정책/자동화/품질 게이트
- Integrations: OAuth/API 키/플랫폼 연결

## Q. 운영 점검 리포트 시간이 과거로 보이면?
- `/ops-health`에서 `실시간 동기화` 실행
- 실패 시 수동 명령 실행:
```bash
docker compose --env-file .env exec -T api python -m app.tools.ops_health_report
```

