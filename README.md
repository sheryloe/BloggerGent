# Bloggent

`Bloggent`는 여러 개의 Google Blogger 블로그를 하나의 대시보드에서 운영하기 위한 서비스형 자동화 워크스페이스입니다.
단순 생성기가 아니라, 실제 발행 과정에서 필요한 안전장치와 SEO 검증까지 포함하는 것이 목표입니다.

- 저장소: `https://github.com/sheryloe/BloggerGent`

## 서비스 개요

- 블로그별 워크플로와 프롬프트를 분리해 운영합니다.
- 생성과 발행을 분리해 공개 포스트를 실수로 덮어쓰지 않도록 설계합니다.
- Blogger, Search Console, GA4를 함께 묶는 운영 흐름을 지향합니다.

## 핵심 기능

- Blogger 블로그 가져오기
- 블로그별 프롬프트/워크플로 설정
- 토픽 생성, 글 작성, 이미지 생성, HTML 조립
- 수동 발행 큐
- 발행 후 공용 페이지 기준 SEO 메타 검증

## 아키텍처

- Frontend: Next.js 14, TypeScript, Tailwind CSS
- Backend: FastAPI, SQLAlchemy, Alembic, Pydantic
- Worker/Infra: Celery, Redis, PostgreSQL, Docker Compose

## 실행 방법

```bash
docker compose up --build
```

기본 주소:

- 대시보드: `http://localhost:3001`
- API 문서: `http://localhost:8000/docs`
- 헬스체크: `http://localhost:8000/healthz`

## 추천 운영 흐름

1. `/settings`에서 공통 자격증명을 입력합니다.
2. Google 계정을 연결합니다.
3. Blogger 블로그를 가져옵니다.
4. 블로그별 워크플로를 설정합니다.
5. 토픽과 글을 생성합니다.
6. 생성된 글 목록에서 수동으로 발행합니다.

## 다음 단계

- 예약 발행과 캘린더 뷰 추가
- 운영자 승인 큐와 QA 체크리스트 강화
- 다중 블로그 운영자를 위한 사용량/요금제 개념 설계
