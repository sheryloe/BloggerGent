# Getting Started

이 문서는 Bloggent를 처음 세팅할 때 필요한 순서를 Cloudflare R2 기준으로 정리합니다.

## 1. 준비물

- Docker 또는 로컬 실행 환경
- Blogger 운영용 Google 계정
- OpenAI API key
- Cloudflare 계정
- Cloudflare R2 bucket
- Cloudflare R2 access key / secret key
- `img.<domain>` 용 커스텀 호스트
- `SETTINGS_ENCRYPTION_SECRET`

## 2. `.env` 기본값 채우기

최소 권장값은 아래와 같습니다.

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

## 3. Cloudflare 쪽 선행 설정

1. R2 bucket을 생성합니다.
2. bucket public access 또는 custom domain 연결이 가능한 상태인지 확인합니다.
3. R2 access key를 생성합니다.
4. `img.<domain>` 커스텀 호스트를 Cloudflare에서 연결합니다.
5. 브라우저에서 `https://img.<domain>`이 Cloudflare 앞단으로 응답하는지 확인합니다.

## 4. 앱 실행

```bash
docker compose up --build -d
```

확인 주소:

- Web: `http://localhost:3001`
- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/healthz`

## 5. Settings 화면에서 확인할 것

`/settings`에서 아래를 점검합니다.

### Global providers

- `public_image_provider=cloudflare_r2`
- `cloudflare_account_id`
- `cloudflare_r2_bucket`
- `cloudflare_r2_access_key_id`
- `cloudflare_r2_secret_access_key`
- `cloudflare_r2_public_base_url`
- `cloudflare_r2_prefix`

### Google OAuth

- `blogger_client_id`
- `blogger_client_secret`
- `blogger_redirect_uri`

## 6. Google OAuth 연결

1. Google Cloud Console에서 OAuth web client를 생성합니다.
2. Redirect URI에 다음 값을 등록합니다.

```text
http://localhost:8000/api/v1/blogger/oauth/callback
```

3. `/settings`에서 Google 연결을 수행합니다.
4. Blogger 블로그를 import 합니다.

## 7. 이미지 전달 검증

generated article 1건을 만든 뒤 아래를 확인합니다.

1. `Image.public_url`이 원본 R2 URL이 아니라 hero 변형 URL인지
2. `image_metadata.delivery.cloudflare.object_key`가 저장됐는지
3. assembled HTML의 hero `<img>`에 `srcset`과 `sizes`가 들어갔는지
4. archive 썸네일이 작은 thumb variant를 쓰는지

## 8. 기존 generated 글 마이그레이션

Dry-run:

```http
POST /api/v1/admin/image-migrations/cloudflare-r2
Content-Type: application/json

{
  "mode": "dry_run",
  "blog_id": 1,
  "limit": 20
}
```

Execute:

```http
POST /api/v1/admin/image-migrations/cloudflare-r2
Content-Type: application/json

{
  "mode": "execute",
  "blog_id": 1,
  "limit": 20
}
```

## 9. 운영 주의사항

- 마이그레이션 전 GitHub Pages / Cloudinary 자산 삭제 금지
- synced-only 외부 Blogger 글은 자동 치환 대상 제외
- `img.<domain>` 대신 메인 도메인 경로를 쓰면 캐시/라우팅 관리가 더 복잡해집니다
- Cloudflare를 쓴다고 해서 자동 최적화가 되는 것이 아니라, HTML이 변형 URL을 렌더링해야 합니다
