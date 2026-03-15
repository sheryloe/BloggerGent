# Step 3. Docker로 로컬 실행 환경 구축하기

## 추천 제목
- Docker Compose로 Blogger 자동화 프로젝트 로컬 환경 완성하기
- Next.js + FastAPI + Redis + PostgreSQL 로컬 실행기: 실전 Docker 구성
- 구글 블로그 반자동화 프로젝트, Docker 환경부터 잡았다

## 검색 설명
Docker Compose로 Next.js, FastAPI, Celery, Redis, PostgreSQL 기반 Blogger 자동화 프로젝트를 로컬에서 실행하는 과정을 정리합니다.

## 추천 태그
`DockerCompose`, `로컬개발환경`, `FastAPI`, `Nextjs`, `Celery`

## 글 구조
- 왜 Docker Compose를 선택했는가
- 어떤 컨테이너가 필요한가
- 로컬에서 바로 뜨게 만들 때 중요한 점
- API, 워커, 웹을 어떻게 연결했는가

## 본문 샘플

이 프로젝트는 다른 사람도 쉽게 실행할 수 있어야 했기 때문에, 설치 가이드를 길게 쓰는 대신 `docker compose up --build` 한 줄로 올라오게 맞추는 것이 중요했습니다.

웹, API, 워커, 스케줄러, 데이터베이스, Redis가 모두 연결되어야 해서 Docker Compose 구성이 자연스러운 선택이었습니다. 특히 로컬 테스트 단계에서는 서비스 간 주소를 고정하기 쉬운 점이 편했습니다.

## HTML 예시

```html
<h2>Docker Compose에 올린 서비스</h2>
<ul>
  <li><strong>web</strong>: Next.js 대시보드</li>
  <li><strong>api</strong>: FastAPI 백엔드</li>
  <li><strong>worker</strong>: Celery 워커</li>
  <li><strong>scheduler</strong>: Celery Beat</li>
  <li><strong>postgres</strong>: 메타데이터 저장</li>
  <li><strong>redis</strong>: 큐와 스케줄링</li>
</ul>

<h2>실행 명령</h2>
<p><strong>docker compose up --build</strong> 한 줄로 전체 환경이 올라오도록 맞췄습니다.</p>
```

## 마무리 문장 예시

로컬 환경이 안정적으로 올라오면 그다음부터는 외부 API 연결과 실제 게시 흐름을 붙일 수 있습니다. 다음 글에서는 가장 많은 시행착오가 있었던 Google OAuth와 Blogger 연동 과정을 정리하겠습니다.
