# 시작하기

이 문서는 Bloggent를 로컬에서 띄우고 실제 Blogger 운영 루프까지 도달하는 가장 빠른 경로를 설명합니다.

## 빠른 답변

1. `.env`를 채웁니다.
2. Docker Compose를 실행합니다.
3. `/settings`를 엽니다.
4. Google OAuth를 연결합니다.
5. Blogger 블로그를 가져옵니다.
6. 주제를 발굴하거나 직접 입력합니다.
7. `/articles`에서 글을 검토합니다.
8. 수동 발행합니다.
9. 공개 메타를 검증합니다.

## 주요 주소

- 대시보드: `http://localhost:3001`
- API 문서: `http://localhost:8000/docs`
- API 헬스체크: `http://localhost:8000/healthz`

## 최소 환경 변수

- `OPENAI_API_KEY`
- `BLOGGER_CLIENT_ID`
- `BLOGGER_CLIENT_SECRET`
- `BLOGGER_REDIRECT_URI`
- `SETTINGS_ENCRYPTION_SECRET`

선택적으로 유용한 값:

- `GEMINI_API_KEY`
- GitHub Pages 자산 관련 설정

## 실행 명령

```bash
docker compose up --build -d
```

## 첫 사용 흐름

1. `/settings`를 엽니다.
2. Google 계정을 연결합니다.
3. Blogger 블로그를 가져옵니다.
4. 블로그별 워크플로와 프롬프트를 확인합니다.
5. 필요하면 Search Console과 GA4 값을 블로그별로 매핑합니다.
6. 대시보드에서 직접 주제를 넣거나 주제 발굴을 실행합니다.
7. `/articles`에서 최종 포스트 프리뷰와 메타를 검토합니다.
8. 수동 발행합니다.
9. 공개 메타 검증을 실행합니다.
