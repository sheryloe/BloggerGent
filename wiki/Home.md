# Donggr AutoBloggent Wiki

이 위키는 Donggr AutoBloggent 운영자가 실제 서비스 설정과 운영 절차를 빠르게 따라갈 수 있도록 정리한 문서 모음입니다.

## 먼저 읽을 문서

1. [Getting-Started](Getting-Started)
2. [Deployment](Deployment)
3. [Workflow](Workflow)
4. [SEO-Metadata](SEO-Metadata)
5. [Security](Security)

## 운영 핵심 원칙

- 운영 메인 진입은 `/`가 아니라 **`/dashboard`** 입니다.
- 플로우는 **생성 → 자산 → 업로드 → 운영** 4개 묶음으로 관리합니다.
- 자동화는 강하게, 공개 발행은 보수적으로 운영합니다.
- 공개 자산 경로 변경 시 README + 위키를 동시에 갱신합니다.

## 기본 접속 정보 (`.env` 기준)

- Web: `http://127.0.0.1:7001`
- API: `http://127.0.0.1:7002`
- API Docs: `http://127.0.0.1:7002/docs`
- Health: `http://127.0.0.1:7002/healthz`

## 문서 갱신 규칙

- 경로/포트/브랜드 변경 발생 시 아래 문서를 함께 수정합니다.
  - README.md
  - wiki/Getting-Started.md
  - wiki/Deployment.md
  - wiki/FAQ.md