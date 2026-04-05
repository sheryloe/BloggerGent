# Deployment

이 문서는 Donggr AutoBloggent 운영 배포 체크리스트입니다.

## 서비스 구성

- `web`
- `api`
- `worker` (profile)
- `scheduler` (profile)
- `postgres`
- `redis`
- `minio` (선택)

## 배포 전 필수 확인

### 환경 변수

- `WEB_PORT`, `API_PORT`
- `NEXT_PUBLIC_API_BASE_URL`, `API_INTERNAL_URL`
- `OPENAI_API_KEY`
- `BLOGGER_CLIENT_ID`, `BLOGGER_CLIENT_SECRET`, `BLOGGER_REDIRECT_URI`
- `SETTINGS_ENCRYPTION_SECRET`
- (R2 사용 시) `CLOUDFLARE_*`, `PUBLIC_IMAGE_PROVIDER=cloudflare_r2`

### 헬스 체크

```bash
curl http://127.0.0.1:7002/healthz
```

### 웹 빌드

```bash
docker compose --env-file .env exec -T web sh -lc "cd /app && npm run build"
```

## 운영 검증 시나리오

1. `http://127.0.0.1:7001/` → `/dashboard` 리다이렉트
2. 대시보드 4묶음(`생성/자산/업로드/운영`) 노출
3. API `workspace_label` = `Donggr AutoBloggent`
4. 주요 API 응답 오류/타임아웃 없음

## 배포 후 주의사항

- 마이그레이션/운영 검증 완료 전 공개 자산 삭제 금지
- 포트/경로 변경 시 README + 위키 동시 갱신
- 장애 재현 로그는 `TEST/logs`에 타임스탬프 파일로 저장