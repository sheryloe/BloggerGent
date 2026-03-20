# Bloggent

Bloggent는 Blogger 운영 자동화를 위한 워크스페이스입니다. 주제 발굴, 글 생성, 이미지 생성, HTML 조립, 수동 검수, Blogger 발행, 메타 검증까지 한 흐름으로 연결합니다.

현재 공개 이미지 기본 전략은 `Cloudflare R2 + img.<domain> + /cdn-cgi/image` 입니다. 원본은 R2에 1장만 저장하고, 실제 화면에는 hero/card/thumb 변형 URL을 사용합니다. 이 구조를 쓰면 Blogger 본문과 앞으로 만들 커스텀 허브 페이지, 카드 썸네일이 같은 원본 이미지를 재사용할 수 있습니다.

## 빠른 시작

1. `.env.example`을 복사해서 `.env`를 만듭니다.
2. 최소 필수값을 채웁니다.
   - `SETTINGS_ENCRYPTION_SECRET`
   - `OPENAI_API_KEY`
   - `BLOGGER_CLIENT_ID`
   - `BLOGGER_CLIENT_SECRET`
   - `BLOGGER_REDIRECT_URI`
   - `CLOUDFLARE_ACCOUNT_ID`
   - `CLOUDFLARE_R2_BUCKET`
   - `CLOUDFLARE_R2_ACCESS_KEY_ID`
   - `CLOUDFLARE_R2_SECRET_ACCESS_KEY`
   - `CLOUDFLARE_R2_PUBLIC_BASE_URL`
3. 스택을 올립니다.

```bash
docker compose up --build -d
```

4. `/settings`에서 Google OAuth, Blogger 연결, Cloudflare R2 이미지 전달 설정을 확인합니다.

## Cloudflare R2 기준 이미지 구조

- `public_image_provider=cloudflare_r2`
- 업로드는 API가 R2 S3 호환 API로 직접 수행합니다.
- 원본 참조 URL은 `cloudflare_r2_public_base_url/<prefix>/<slug>.png` 구조입니다.
- 실제 렌더링은 Cloudflare 변형 URL을 사용합니다.
  - hero: `format=auto,fit=scale-down,width=1600,quality=85`
  - hero srcset: `640, 960, 1280, 1600`
  - card: `format=auto,fit=cover,width=640,height=360,quality=75`
  - thumb: `format=auto,fit=cover,width=160,height=160,quality=70`
- `Image.public_url`은 기본 hero optimized URL로 유지됩니다.
- `image_metadata.delivery`에는 `provider`, `cloudflare.bucket`, `object_key`, `public_base_url`, `original_url`, `etag`, `presets`, `srcset.hero`가 저장됩니다.

## 비용 메모

- 2026-03-20 기준 Cloudflare R2 Standard storage는 `10 GB-month free`, 이후 `US$0.015/GB-month` 입니다.
- Cloudflare CDN 캐싱과 Cloudflare 이미지 변형 과금은 별개입니다.
- `/cdn-cgi/image` 기반 최적화는 Cloudflare Images transformation quota/과금 정책 영향을 받습니다.
- `Cloudflare Images` 제품과 `R2 + 변형 URL`은 같은 것이 아닙니다. 이 저장소는 `R2를 원본 저장소`, `Cloudflare 변형 URL을 delivery 엔진`으로 사용하는 쪽으로 맞춰져 있습니다.

## 마이그레이션 API

기존 generated article 이미지가 GitHub Pages나 Cloudinary를 사용 중이라면 아래 관리자 API로 Cloudflare R2로 전환할 수 있습니다.

```http
POST /api/v1/admin/image-migrations/cloudflare-r2
Content-Type: application/json

{
  "mode": "dry_run",
  "blog_id": 1,
  "limit": 20
}
```

- `dry_run`: DB, Blogger, R2 변경 없이 대상과 예상 URL만 반환합니다.
- `execute`: 글 단위로 업로드, metadata 갱신, HTML 재조립, Blogger `update_post`, audit log 기록까지 수행합니다.
- 실패한 글은 이전 URL을 유지하고 다음 글로 계속 진행합니다.

## 운영 주의사항

- `cloudflare_r2_public_base_url`은 운영용으로 `img.<domain>` 전용 호스트를 권장합니다.
- Cloudflare를 쓴다고 해서 자동으로 최적화되는 것은 아닙니다. HTML이 변형 URL을 렌더링해야 hero/card/thumb 경량화가 실제로 적용됩니다.
- GitHub Pages나 Cloudinary 기존 원격 자산은 마이그레이션 검증 완료 전 삭제하면 안 됩니다.
- synced-only 외부 Blogger 글은 자동 치환 대상이 아닙니다.

## 문서

- [wiki/Home.md](wiki/Home.md)
- [wiki/Getting-Started.md](wiki/Getting-Started.md)
- [wiki/Deployment.md](wiki/Deployment.md)
- [docs/getting-started.md](docs/getting-started.md)
