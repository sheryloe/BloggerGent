# Bloggent

Bloggent는 Google Blogger를 운영하는 사람을 위한 반자동 SEO 블로그 운영 시스템입니다.
주제 발굴, 글 생성, 이미지 생성, HTML 조립, Blogger 게시, Google 성과 확인까지 한 화면에서 관리할 수 있게 구성했습니다.

핵심 목표는 단순합니다.

- 주제만 던지면 SEO 구조에 맞는 글을 만든다
- 대표 이미지를 자동으로 생성하고 공개 URL로 연결한다
- 글 목록에서 검토 후 원하는 글만 공개 게시한다
- Search Console, GA4, Blogger 데이터를 한곳에서 확인한다

## 주요 기능

- Blogger 계정에서 실제 블로그를 가져와 서비스용 블로그로 등록
- 블로그별 워크플로 단계와 프롬프트 관리
- OpenAI 기반 본문 생성, 이미지 프롬프트 생성, 이미지 생성
- Gemini 기반 자동 주제 발굴
- GitHub Pages 기반 공개 이미지 업로드
- 수동 공개 게시 및 재게시
- Search Console / GA4 / Blogger 데이터 모니터링

## 기술 스택

### Frontend
- Next.js 14
- TypeScript
- TailwindCSS

### Backend
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic

### Worker / Infra
- Celery
- Redis
- PostgreSQL
- Docker Compose

## 실행

```bash
docker compose up --build
```

실행 후 접속 주소:

- 대시보드: `http://localhost:3001`
- API 문서: `http://localhost:8000/docs`
- API 헬스체크: `http://localhost:8000/healthz`

## 이 프로젝트는 완전 자동이 아니라 반자동 운영형입니다

초기 1회는 사람이 연결과 설정을 끝내야 합니다.

- OpenAI API Key 입력
- Google OAuth Client ID / Secret 등록
- Google 계정 OAuth 승인
- Blogger 블로그 가져오기
- GitHub Pages 또는 공개 이미지 호스팅 설정

이 초기 세팅이 끝나면 이후부터는 주제 입력, 초안 검토, 게시 운영을 훨씬 빠르게 반복할 수 있습니다.

## 처음 사용하는 순서

### 1. 전역 설정 입력
`/settings`에서 아래 항목을 먼저 입력합니다.

필수:
- `OpenAI API Key`
- `Google OAuth Client ID`
- `Google OAuth Client Secret`
- `Google OAuth Redirect URI`
- `공개 이미지 방식`

선택:
- `Gemini API Key`
  - 자동 주제 발굴을 쓸 때만 필요합니다.

### 2. Google OAuth 연결
설정 페이지에서 `Google 계정 연결하기`를 누르면 Blogger / Search Console / GA4 권한 승인을 진행합니다.

### 3. Blogger 블로그 가져오기
Google 계정에 연결된 실제 Blogger 블로그 목록을 불러오고, 그중 운영할 블로그를 서비스용 블로그로 가져옵니다.

### 4. 블로그별 연결 매핑
가져온 블로그마다 아래 항목을 연결합니다.

- Blogger 블로그
- Search Console 속성
- GA4 속성

### 5. 블로그별 워크플로 / 프롬프트 정리
블로그별로 다음 항목을 정리합니다.

- 블로그 이름
- 설명
- 타깃 독자
- 운영 브리프
- 워크플로 단계 순서
- 단계별 프롬프트
- 공용 프롬프트 템플릿

### 6. 주제 실행
다음 두 방식 중 하나를 사용합니다.

- 수동 키워드 입력
- Gemini 자동 주제 발굴

### 7. 글 확인 후 게시
`/articles`에서 아래를 확인합니다.

- HTML 미리보기
- 대표 이미지
- 메타 설명
- Blogger 링크

문제가 없으면 글 목록의 `공개 게시` 버튼을 눌러 최종 게시합니다.

## 다른 사람이 이 프로젝트를 쓰려면 무엇을 입력해야 하나요?

다른 사람이 Bloggent를 사용하려면 아래 입력값이 필요합니다.

### A. OpenAI
- `OpenAI API Key`

### B. Google OAuth
- `Client ID`
- `Client Secret`
- `Redirect URI`

### C. 공개 이미지 호스팅
권장:
- `GitHub Pages`

필요한 값:
- `github_pages_owner`
- `github_pages_repo`
- `github_pages_branch`
- `github_pages_token`
- `github_pages_base_url`

### D. 선택 항목
- `Gemini API Key`

## Google OAuth 설정 방법

### Google Cloud에서 해야 하는 일
1. Google Cloud Console에서 프로젝트를 만듭니다.
2. `Google Auth Platform` 또는 `APIs & Services`에서 OAuth Client를 생성합니다.
3. 타입은 `Web application`으로 만듭니다.
4. Redirect URI에 아래 주소를 등록합니다.

```text
http://localhost:8000/api/v1/blogger/oauth/callback
```

### Testing 상태일 때
OAuth 앱이 `Testing` 상태면 실제 로그인할 Google 계정을 `Test users`에 추가해야 합니다.

추가하지 않으면 이런 오류가 납니다.

- `403 access_denied`
- `앱은 현재 테스트 중이며 개발자가 승인한 테스터만 액세스할 수 있습니다`

### 다른 사람도 쓰게 하려면
다른 사람이 자기 Google 계정으로 이 프로젝트를 쓰게 하려면 아래 둘 중 하나가 필요합니다.

1. 당신이 만든 OAuth 앱에 그 사람 Google 계정을 `Test users`로 추가
2. OAuth 앱을 `Production`으로 전환

장기 운영이나 다수 사용자 기준으로는 `Production` 전환을 권장합니다.

## GitHub Pages 이미지 설정

대표 이미지가 Blogger 공개 글에서 보이려면 `localhost`가 아니라 외부에서 접근 가능한 공개 URL이어야 합니다.
Bloggent는 현재 GitHub Pages 업로드를 지원합니다.

### 준비
1. public 저장소 생성
2. GitHub Pages 활성화
3. Fine-grained token 생성
4. 권한:
   - `Contents: Read and write`

### Bloggent에 넣을 값
```text
github_pages_owner=...
github_pages_repo=...
github_pages_branch=main
github_pages_token=...
github_pages_base_url=https://username.github.io/repo
```

이후 이미지는 날짜별 폴더로 자동 업로드됩니다.

## 페이지 안내

- `/`
  - 대시보드
- `/guide`
  - 사용 가이드
- `/settings`
  - 전역 설정, Google OAuth, Blogger import, 블로그별 워크플로, 프롬프트 설정
- `/articles`
  - 생성 글 목록, HTML 미리보기, 수동 공개 게시
- `/jobs`
  - 작업 상태와 감사 로그
- `/google`
  - Blogger / Search Console / GA4 모니터링

## 권장 운영 방식

### 여행 / 축제 / 행사 블로그
- OpenAI 본문 생성
- OpenAI 이미지 생성
- Gemini 주제 발굴
- 생성 후 검토, 공개 게시 버튼으로 최종 게시

### 미스터리 / 다큐 / 전설 블로그
- 수동 주제 입력 비중 높음
- 프롬프트 관리 중요
- 초안 검토 후 게시 권장

## 검증 명령

```bash
python -m compileall apps/api/app
```

```bash
cd apps/web
npm run build
```

## 주의 사항

- 비밀값은 UI에서 입력하면 DB `settings` 테이블에 저장됩니다.
- 비밀 입력칸을 비워두고 저장하면 기존 값은 유지됩니다.
- OAuth 앱이 Testing 상태면 테스트 사용자 등록이 필요합니다.
- 공개 이미지 URL이 없으면 Blogger 썸네일이 깨집니다.
- 같은 Google 계정 안에 여러 Blogger 블로그가 있어도 import 후 각각 따로 운영할 수 있습니다.

## 요약

Bloggent는 Blogger 운영자가 매번 손으로 글 작성, 이미지 연결, 게시, 성과 확인을 반복하지 않도록,

`주제 입력 -> 글 생성 -> 이미지 생성 -> 게시 -> 성과 확인`

흐름을 하나의 로컬 대시보드에 묶어 둔 반자동 운영형 프로젝트입니다.
