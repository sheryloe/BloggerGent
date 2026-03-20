# Bloggent Wiki

이 위키는 BloggerGent 운영자가 실제 서비스 설정과 운영 절차를 따라갈 수 있게 정리한 문서 모음입니다.

현재 기본 이미지 전략은 `Cloudflare R2 + img.<domain> custom hostname + /cdn-cgi/image` 입니다. 원본을 R2에 저장하고, Blogger 본문과 커스텀 블로그 허브/카드에서 같은 이미지를 다른 크기로 재사용하는 구조를 전제로 설명합니다.

## 먼저 읽을 문서

1. [Getting-Started](Getting-Started)
2. [Deployment](Deployment)
3. [Workflow](Workflow)
4. [SEO-Metadata](SEO-Metadata)

## 핵심 운영 원칙

- generated article 이미지만 자동 마이그레이션 대상입니다.
- synced-only 외부 Blogger 글은 자동 치환하지 않습니다.
- `Image.public_url`은 기본 hero optimized URL입니다.
- hero/card/thumb 최적화는 Cloudflare 변형 URL을 렌더링할 때만 적용됩니다.
- 마이그레이션 검증 전에는 GitHub Pages, Cloudinary 기존 자산을 삭제하지 않습니다.

## Cloudflare R2 구조 요약

- 원본 저장: Cloudflare R2 bucket
- 운영 도메인: `img.<domain>`
- 원본 경로: `https://img.<domain>/<prefix>/<slug>.png`
- 렌더링 URL:
  - hero: `https://img.<domain>/cdn-cgi/image/format=auto,fit=scale-down,width=1600,quality=85/<prefix>/<slug>.png`
  - card: `https://img.<domain>/cdn-cgi/image/format=auto,fit=cover,width=640,height=360,quality=75/<prefix>/<slug>.png`
  - thumb: `https://img.<domain>/cdn-cgi/image/format=auto,fit=cover,width=160,height=160,quality=70/<prefix>/<slug>.png`

## 비용 메모

- 2026-03-20 기준 R2 Standard storage: `10 GB-month free`, 이후 `US$0.015/GB-month`
- 이미지 변형 비용은 R2 저장 비용과 별도입니다.
- `Cloudflare Images`와 `R2 + /cdn-cgi/image`는 같은 제품이 아닙니다.

## 관련 링크

- [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [Cloudflare R2 S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/)
- [Transform images via URL](https://developers.cloudflare.com/images/transform-images/transform-via-url/)
