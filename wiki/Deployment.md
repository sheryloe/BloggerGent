# Deployment

이 문서는 Cloudflare R2 기준 운영 배포 체크리스트입니다.

## 서비스 구성

- `web`
- `api`
- `worker`
- `scheduler`
- `postgres`
- `redis`
- `minio`

`minio`는 로컬 저장/개발용 경로와 generated artifact 보관에 계속 남아 있을 수 있지만, 공개 이미지 기본 delivery는 Cloudflare R2 기준으로 봅니다.

## 필수 환경 변수

### Blogger / OpenAI

- `OPENAI_API_KEY`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`
- `SETTINGS_ENCRYPTION_SECRET`

### Cloudflare R2

- `PUBLIC_IMAGE_PROVIDER=cloudflare_r2`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_R2_BUCKET`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`
- `CLOUDFLARE_R2_PUBLIC_BASE_URL`
- `CLOUDFLARE_R2_PREFIX`

## 배포 전 검증

### R2 / 도메인

1. `img.<domain>`이 Cloudflare에 연결돼 있는지
2. R2 key가 write 권한을 가지는지
3. 업로드 후 원본 URL이 `https://img.<domain>/<prefix>/...` 형태로 열리는지
4. 변형 URL이 `https://img.<domain>/cdn-cgi/image/...` 형태로 응답하는지

### 앱

```bash
curl http://localhost:8000/healthz
```

```bash
cd apps/web
npm run build
```

## 마이그레이션 운영 절차

1. 신규 업로드가 Cloudflare R2로 들어가는지 먼저 검증합니다.
2. 관리자 API `dry_run`으로 대상 글과 예상 URL을 확인합니다.
3. 소량 `execute`로 먼저 마이그레이션합니다.
4. Blogger 본문, archive, related card 썸네일이 정상인지 확인합니다.
5. 전체 execute를 진행합니다.
6. 검증이 끝난 뒤에만 GitHub Pages/Cloudinary 자산 정리를 검토합니다.

## 롤백 관점

- 마이그레이션 실패 시 글 단위로 기존 URL을 유지합니다.
- 새로 업로드된 R2 object는 best-effort delete 대상입니다.
- 이미 원격 Blogger 본문이 바뀐 뒤 로컬 commit에서 실패하면 서비스가 이전 HTML로 되돌리기를 시도합니다.
- synced-only 외부 Blogger 글은 자동 마이그레이션 대상이 아니므로 별도 운영 판단이 필요합니다.
