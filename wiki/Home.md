# Bloggent 위키

Bloggent는 AI가 글을 써 주는 기능에서 끝나지 않고, 멀티 블로그 운영, 수동 발행 보호, 공개 메타 검증까지 이어지는 Blogger 운영 워크스페이스입니다.

## 빠른 답변

위키는 “지금 이 제품이 어떻게 움직이는지”를 가장 짧게 이해하기 위한 운영 문서 허브입니다.
처음 보는 경우에는 아래 순서로 읽으면 됩니다.

1. 로컬 스택을 띄웁니다.
2. Google OAuth를 연결합니다.
3. Blogger 블로그를 가져옵니다.
4. 주제를 발굴하거나 직접 넣습니다.
5. `/articles`에서 글을 검토합니다.
6. 수동 발행합니다.
7. 공개 메타를 검증합니다.

## 시작 문서

- [시작하기](Getting-Started)
- [워크플로](Workflow)
- [SEO 메타데이터](SEO-Metadata)
- [배포](Deployment)
- [보안](Security)
- [FAQ](FAQ)
- [서비스 로드맵](Service-Roadmap)

## 제품 핵심 포인트

- 블로그별 워크플로와 프롬프트를 분리합니다.
- 생성과 발행을 분리해 운영 리스크를 줄입니다.
- GEO + SEO 구조로 제목, 메타, 본문 약속을 맞춥니다.
- Blogger API 응답이 아니라 공개 페이지 기준으로 메타를 검증합니다.

## 주요 화면

- `/` 대시보드: 글 시작 액션, 작업 상태, 대표 프리뷰, 메타 상태
- `/articles`: 제목, 메타, HTML, 최종 프리뷰, 수동 발행, 메타 검증
- `/jobs`: 백그라운드 작업 큐와 실패 이력
- `/settings`: Google OAuth, 블로그 가져오기, 연결 값, 워크플로 설정

## 참고 링크

- 저장소: `https://github.com/sheryloe/BloggerGent`
- GitHub Pages: `https://sheryloe.github.io/BloggerGent/`
