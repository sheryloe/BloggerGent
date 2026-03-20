---
title: 시작하기
---

# 시작하기

Bloggent의 기본 공개 이미지 전략은 `Cloudflare R2 + img.<domain> + /cdn-cgi/image` 입니다. 원본은 R2에 저장하고, 화면에는 hero/card/thumb 최적화 URL을 사용합니다.

## 필수 설정

```env
PUBLIC_IMAGE_PROVIDER=cloudflare_r2
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_R2_BUCKET=
CLOUDFLARE_R2_ACCESS_KEY_ID=
CLOUDFLARE_R2_SECRET_ACCESS_KEY=
CLOUDFLARE_R2_PUBLIC_BASE_URL=https://img.example.com
CLOUDFLARE_R2_PREFIX=assets/images
OPENAI_API_KEY=
BLOGGER_CLIENT_ID=
BLOGGER_CLIENT_SECRET=
BLOGGER_REDIRECT_URI=http://localhost:8000/api/v1/blogger/oauth/callback
SETTINGS_ENCRYPTION_SECRET=
```

## 실행

```bash
docker compose up --build -d
```

## 순서

1. Cloudflare에서 R2 bucket 생성
2. R2 access key 발급
3. `img.<domain>` custom hostname 연결
4. `/settings`에서 Cloudflare R2 값 입력
5. Google OAuth 연결
6. Blogger 블로그 import
7. article 1건 생성 후 hero/card/thumb URL 검증
8. 필요 시 관리자 migration API 실행

## 마이그레이션 API

```http
POST /api/v1/admin/image-migrations/cloudflare-r2
```

- `mode=dry_run`: 변경 없음
- `mode=execute`: R2 업로드, DB 갱신, HTML 재조립, Blogger update 수행

## 주의사항

- Cloudflare를 쓴다고 자동 최적화되지 않습니다. HTML이 `/cdn-cgi/image` URL을 렌더링해야 합니다.
- synced-only 외부 Blogger 글은 자동 치환하지 않습니다.
- GitHub Pages / Cloudinary 기존 자산은 마이그레이션 검증 전 삭제하지 않습니다.
