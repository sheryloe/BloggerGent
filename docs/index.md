---
title: Bloggent 문서
---

# Bloggent 문서

Bloggent는 여러 개의 Blogger 블로그를 한 화면에서 운영할 수 있게 만든 GEO + SEO 중심 퍼블리싱 워크스페이스입니다.
AI로 글을 만들되, 최종 공개 전 검토와 실제 메타 검증까지 운영자가 직접 통제하는 흐름을 기준으로 설계되어 있습니다.

## 빠른 답변

Bloggent는 아래 흐름이 필요한 사람에게 맞습니다.

- Google 연결과 Blogger 블로그 가져오기
- 주제 발굴 또는 직접 주제 입력
- 글, 이미지, HTML 조립 생성
- `/articles`에서 최종 글 검토
- 수동 발행
- 공개 페이지 메타데이터 검증

## 한눈에 보기

- 주요 화면: `/`, `/articles`, `/jobs`, `/settings`, `/google`
- 로컬 웹: `http://localhost:3001`
- API 문서: `http://localhost:8000/docs`
- 주요 스택: Next.js, FastAPI, Celery, PostgreSQL, Redis, Docker Compose
- 공개 랜딩 페이지: `index.html`

## 문서 바로가기

- [시작하기](getting-started.html)
- [워크플로 구조](workflow.html)
- [SEO 메타데이터 전략](seo-metadata.html)
- [아키텍처](architecture.html)
- [배포](deployment.html)
- [보안](security.html)
- [FAQ](faq.html)
- [로드맵](roadmap.html)

## 현재 제품 방향

지금 Bloggent는 아래 3가지를 가장 중요하게 보고 있습니다.

1. 모든 블로그에 같은 프롬프트를 쓰지 않고 블로그별 워크플로를 분리할 것
2. 생성과 발행을 분리해서 약한 초안이 그대로 공개되지 않게 할 것
3. Blogger API만 믿지 않고 실제 공개 페이지 기준으로 메타데이터를 검증할 것

## GEO + SEO 글 구조

현재 글 생성 프롬프트는 답을 먼저 주고, 메타 설명과 본문 약속을 맞추며, 검색엔진과 답변형 엔진이 모두 읽기 쉬운 구조를 목표로 합니다.
즉 “예쁘게만 긴 글”보다 “질문에 빨리 답하고, 섹션별로 의미가 분명한 글”을 우선합니다.

## 랜딩 페이지 보기

GitHub Pages가 `/docs` 기준으로 배포되어 있다면, 실제 공개 랜딩은 아래 페이지입니다.

- [랜딩 페이지](index.html)
