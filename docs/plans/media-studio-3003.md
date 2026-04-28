# Media Studio 3003 PRN

## 목적

`Media Studio`는 Instagram 카드뉴스와 YouTube 영상 운영을 기존 BloggerGent workspace DB에 연결하기 위한 3003 포트 독립 운영 랩이다. 3001 자동 블로그 운영 콘솔에 바로 붙이지 않고, 먼저 별도 포트에서 초안 작성, 중복 검사, 검수, 승인, 발행 큐 등록, 차단 사유 확인 흐름을 검증한다.

## 실행 구조

- 코드 위치: `apps/web`
- 독립 실행 URL: `http://localhost:3003/media-studio`
- Docker 서비스: `media-studio`
- 3003 루트 접속 시 `NEXT_PUBLIC_MEDIA_STUDIO_STANDALONE=true`이면 `/media-studio`로 이동한다.
- 3001 Attach 전까지 좌측 메뉴에는 노출하지 않는다.
- Windows에서 `PRN`은 예약 장치명이므로 공식 문서는 `docs/plans/media-studio-3003.md`에 둔다.

## 화면 범위

1. `운영 현황`
   - Instagram/YouTube별 전체, 검수, 실패, 발행, 자산 대기 상태를 확인한다.
2. `Instagram 카드뉴스`
   - 채널, 제목, 주제, 타깃, 카드 수, 비율, 카드 문구, 캡션, 해시태그, CTA를 입력한다.
   - 같은 채널/유형의 기존 콘텐츠와 중복 검사를 수행한다.
   - 중복 위험이 `high`이면 초안 생성을 막는다.
3. `YouTube`
   - 채널, 제목, 주제, 타깃, 영상 형식, 분량, 스크립트 브리프, 썸네일 프롬프트, 설명, 태그, 공개 상태를 입력한다.
   - 같은 채널/유형의 기존 콘텐츠와 중복 검사를 수행한다.
4. `검수 큐`
   - `draft`, `review`, `approved`, `ready_to_publish`, `queued`, `blocked_asset`, `published`, `failed` 상태를 확인한다.
   - 검수 요청, 승인, 초안 전환, 발행 큐 등록을 수행한다.

## DB/API 계약

- 주 리소스는 기존 `content_items`를 사용한다.
- Instagram 카드뉴스는 `content_type = instagram_image`로 저장한다.
- YouTube 영상은 `content_type = youtube_video`로 저장한다.
- Antigravity 식별값은 `created_by_agent = media-studio-3003` 또는 `brief_payload.studio = media-studio-3003`이다.
- 생성 지시값은 `brief_payload`에 저장한다.
- 필수 자산과 산출물 상태는 `asset_manifest`에 저장한다.
- 운영 상태는 `lifecycle_status`로 관리한다.

사용 API:

```text
GET    /api/v1/workspace/content-items?provider=instagram
GET    /api/v1/workspace/content-items?provider=youtube
POST   /api/v1/workspace/content-items
PATCH  /api/v1/workspace/content-items/{item_id}
POST   /api/v1/workspace/content-items/{item_id}/review
POST   /api/v1/workspace/content-items/{item_id}/publish
POST   /api/v1/workspace/content-items/duplicate-check
```

중복 검사 정책:

- 입력: `provider`, `channel_id`, `content_type`, `topic`, `title`
- 출력: `is_duplicate`, `risk_level`, `matched_items[]`
- 비교 범위: 같은 `channel_id + content_type` 내 `title`, `description`, `body_text`, `brief_payload`
- `high`: 생성 차단
- `medium`: 경고 후 생성 허용
- `low`: 생성 허용

## Antigravity Handoff

Antigravity는 `created_by_agent = media-studio-3003` 또는 `brief_payload.studio = media-studio-3003`인 항목을 우선 대상으로 삼는다.

Instagram 생성기는 아래 값을 읽는다.

- `brief_payload.cards`
- `brief_payload.caption`
- `brief_payload.hashtags`
- `brief_payload.cta`
- `brief_payload.aspect_ratio`

Instagram 생성 완료 후 아래 값을 채운다.

- `asset_manifest.image_url`

YouTube 생성기는 아래 값을 읽는다.

- `brief_payload.script_brief`
- `brief_payload.thumbnail_prompt`
- `brief_payload.tags`
- `brief_payload.privacy_status`

YouTube 생성 완료 후 최소 아래 값을 채운다.

- `asset_manifest.video_file_path`

자산이 없으면 큐 등록 시 `blocked_asset` 상태와 사람이 이해 가능한 `blocked_reason`을 남긴다. 자산이 채워지면 같은 항목을 다시 큐 등록할 수 있어야 한다.

## 3001 Attach 조건

- Instagram 1건과 YouTube 1건에서 `초안 생성 -> Antigravity 자산 반영 -> 큐 등록` 실경로가 통과해야 한다.
- `blocked_asset` 경로를 실제로 1회 이상 검증해야 한다.
- `brief_payload`와 `asset_manifest` 키가 문서, UI, Antigravity 구현에서 동일해야 한다.
- 3001에는 새 운영 허브를 만들지 않고, 검증 후 단일 메뉴 `미디어 운영`만 추가한다.
- 3001 기존 블로그 운영 콘솔은 3003 없이도 계속 정상 동작해야 한다.

## 운영 명령

Docker 실행:

```powershell
Set-Location D:\Donggri_Platform\BloggerGent
docker compose up -d media-studio
```

로컬 직접 실행:

```powershell
Set-Location D:\Donggri_Platform\BloggerGent\apps\web
$env:NEXT_PUBLIC_MEDIA_STUDIO_STANDALONE="true"
$env:NEXT_PUBLIC_API_BASE_URL="http://localhost:7002/api/v1"
npm run dev -- --hostname 0.0.0.0 --port 3003
```

검증 명령:

```powershell
Set-Location D:\Donggri_Platform\BloggerGent\apps\web
npm run build

Set-Location D:\Donggri_Platform\BloggerGent\apps\api
$env:PYTHONPATH="D:\Donggri_Platform\BloggerGent\apps\api"
pytest tests/test_workspace_platform_services.py -q
```

## 제외 범위

- 3003 안에서 이미지/영상 생성
- 카드 디자인 편집기
- 영상 타임라인 편집기
- 성과 분석
- A/B 테스트
- 3001 좌측 메뉴 즉시 통합
