# 배포

## 기본 서비스

- `web`
- `api`
- `worker`
- `scheduler`
- `postgres`
- `redis`
- `minio`

## Cloudflare R2 체크리스트

- `PUBLIC_IMAGE_PROVIDER=cloudflare_r2`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_R2_BUCKET`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`
- `CLOUDFLARE_R2_PUBLIC_BASE_URL`
- `CLOUDFLARE_R2_PREFIX`

## 검증

```bash
curl http://localhost:8000/healthz
```

```bash
cd apps/web
npm run build
```

## 운영 메모

- 원본은 R2에 1장만 저장하고, delivery는 Cloudflare 변형 URL을 사용합니다.
- hero/card/thumb 최적화는 `/cdn-cgi/image` URL이 실제 HTML에 렌더링될 때만 동작합니다.
- 마이그레이션 완료 전 기존 GitHub Pages / Cloudinary 자산 삭제 금지.
