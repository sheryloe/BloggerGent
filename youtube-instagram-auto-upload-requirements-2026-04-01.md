# YouTube / Instagram 자동 업로드 요구사항 식별

작성일: 2026-04-01

## 목적

이 문서는 BloggerGent를 `블로그 중심 자동화`에서 `YouTube + Instagram까지 포함한 멀티채널 자동 게시 운영도구`로 확장하기 위해 필요한 항목을 식별한 요구사항 리스트다.

대상 시나리오:

- YouTube:
  - 운영자가 영상 파일을 올리면
  - 시스템이 CTR 관점의 제목, 구조화된 설명문, 태그, 썸네일 보조 문안을 생성하고
  - 자동 업로드와 예약 게시까지 수행
- Instagram:
  - 운영자가 PPT 또는 PDF를 올리면
  - 페이지별 이미지로 분리하고
  - 인스타 비율에 맞게 재가공한 뒤
  - CTR 관점의 첫 문장, 캡션, 해시태그, CTA를 생성하고
  - 자동 업로드와 예약 게시까지 수행

## 현재 코드 기준 식별

현재 BloggerGent는 아직 YouTube / Instagram 업로드 엔진을 갖고 있지 않다.

현재 실제로 구현된 축:

- Blogger 중심 파이프라인
- topic discovery -> article generation -> image generation -> html assembly -> Blogger publish queue
- OpenAI / Gemini / Mock provider 분기
- Blogger OAuth 및 Blogger publish

현재 관련 코드 위치:

- 파이프라인 본체: `apps/api/app/tasks/pipeline.py`
- provider 선택: `apps/api/app/services/providers/factory.py`
- 텍스트 / 이미지 provider: `apps/api/app/services/providers/openai.py`
- Blogger 게시 큐: `apps/api/app/services/publishing_service.py`
- 블로그 workflow 정의: `apps/api/app/services/blog_service.py`
- 설정 저장: `apps/api/app/services/settings_service.py`
- 설정 UI: `apps/web/components/dashboard/settings-form.tsx`
- 블로그 workflow UI: `apps/web/components/dashboard/blog-settings-manager.tsx`

즉, YouTube / Instagram은 아직 “문서 설계 상태”이며, 실제 업로드 경로는 추가 구현이 필요하다.

## 핵심 결론

YouTube / Instagram 자동 업로드를 위해 필요한 것은 단순히 프롬프트 몇 개가 아니다.

최소 8개 축이 필요하다.

1. 채널 / 계정 / 인증 구조
2. 입력 자산 수집 구조
3. 채널별 메타데이터 생성 규칙
4. 미디어 전처리 파이프라인
5. 업로드 실행기
6. 예약 / 재시도 / 상태조회
7. 로컬 DB 기록 구조
8. 운영 UI / 승인 플로우

## 1. 공통 선행 요구사항

### 1.1 채널 개념 도입

필요 항목:

- `blogger`
- `youtube`
- `instagram`

채널별로 분리돼야 하는 것:

- 계정
- 인증 상태
- 기본 게시 모드
- 기본 모델
- 예약 정책
- 실패 로그

### 1.2 계정 단위 관리

YouTube / Instagram은 블로그 주소 단위가 아니라 계정 단위 관리가 필요하다.

필요 항목:

- 계정 식별자
- 표시명
- 채널 ID 또는 인스타 Professional 계정 ID
- OAuth 상태
- 마지막 인증 시각
- 토큰 만료 시각
- 업로드 가능 여부

### 1.3 게시 단위 엔티티

블로그 `Article`만으로는 부족하다.

필요 항목:

- `ContentProject`
  - 블로그 글, 유튜브 영상, 인스타 캐러셀을 묶는 상위 단위
- `Publication`
  - 채널별 게시 결과
- `MediaAsset`
  - 원본 / 파생 자산
- `PublishAttempt`
  - 게시 시도 이력

### 1.4 승인 정책

완전 자동 게시 전에 승인 지점이 필요하다.

필요 정책:

- `draft_only`
- `auto_prepare_manual_publish`
- `auto_schedule_after_approval`
- `publish_now`

### 1.5 UTF-8 / 한글 보존

필수 대상:

- YouTube 제목
- YouTube 설명
- YouTube 태그
- Instagram 캡션
- Instagram 해시태그
- CTA 링크 문안

## 2. YouTube 자동 업로드 요구사항

### 2.1 입력 요구사항

필요 입력:

- 원본 영상 파일 경로
- 영상 제목 초안 또는 주제
- 대표 블로그 URL 또는 연결 예정 상태
- 업로드 계정
- 예약 시각
- 썸네일 원본 또는 썸네일 생성 요청 여부

권장 추가 입력:

- 영상 길이
- 언어
- 카테고리
- 공개 범위
- 대상 국가 / 대상 독자

### 2.2 메타데이터 생성 요구사항

자동 생성 대상:

- CTR 관점 제목 3~5안
- 최종 업로드 제목 1안
- 구조화된 설명문
- 태그
- 챕터 초안
- 고정 댓글 초안
- 블로그 유입용 CTA 문안

설명문 구조 예시:

1. 첫 2줄 hook
2. 영상 요약
3. 핵심 포인트 목록
4. 대표 블로그 링크
5. 관련 채널 링크
6. 해시태그 또는 검색 태그

CTR 품질 체크 대상:

- 첫 문장 hook 강도
- 제목 길이
- 키워드 전진 배치
- 숫자 / 시기 / 문제 해결 표현 여부
- 제목과 썸네일 문구 일관성

### 2.3 썸네일 요구사항

필요 항목:

- 썸네일 생성 또는 업로드
- 16:9 비율 규격
- 제목과 일관된 hook 문안
- 얼굴 / 사물 / 장소 강조 규칙
- 로컬 파일 저장
- 업로드 후 원격 연결 상태 기록

### 2.4 업로드 실행 요구사항

필요 기능:

- 계정 선택
- 영상 업로드
- 제목 입력
- 설명 입력
- 태그 입력
- 썸네일 업로드
- 공개 범위 설정
- 예약 시각 설정
- 업로드 결과 URL 회수

실행 방식 후보:

- v1: 브라우저 자동화
- v2: YouTube OAuth / API

### 2.5 업로드 후 기록 요구사항

필요 저장값:

- remote video id
- video url
- scheduled_for
- published_at
- title_final
- description_final
- tags_final
- thumbnail_path
- upload status
- last error

### 2.6 운영 검증 요구사항

필요 검증:

- 제목 100자 이하 정책 확인
- 설명문 링크 형식 확인
- 예약 시각 미래 여부
- 한글 깨짐 여부
- 업로드 실패 시 재시도 여부
- 중복 업로드 방지용 idempotency key

## 3. Instagram 자동 업로드 요구사항

### 3.1 입력 요구사항

필요 입력:

- PPT 또는 PDF 파일
- 또는 이미지 세트
- 업로드 계정
- 게시 목적
- 대표 블로그 URL 또는 연결 예정 상태
- 예약 시각

권장 추가 입력:

- 게시 언어
- 타깃 독자
- 브랜드 톤
- CTA 우선순위

### 3.2 문서 전처리 요구사항

PPT / PDF는 바로 업로드할 수 없으므로 전처리가 필요하다.

필요 기능:

- PPT -> PDF 변환 또는 이미지 렌더링
- PDF 페이지 분리
- 페이지 순서 유지
- 페이지별 이미지 파일명 규칙 부여
- 해상도 표준화
- 폰트 깨짐 확인
- 비율 불일치 시 클롭 / 패딩 / 리사이즈 규칙 적용

권장 출력:

- `page-01.png`
- `page-02.png`
- `page-03.png`
- `carousel_manifest.json`

### 3.3 인스타 캐러셀 가공 요구사항

필요 항목:

- 4:5 또는 1:1 비율 기준 선택
- 커버 슬라이드 판단
- 텍스트 안전영역 고려
- 잘림 방지 규칙
- 고정 여백 규칙
- 슬라이드 순서 점검
- 첫 장 hook 강화

### 3.4 캡션 생성 요구사항

자동 생성 대상:

- CTR 관점 첫 문장 hook
- 본문 캡션
- CTA 문안
- 해시태그 세트
- 링크 유도 문안

캡션 구조 예시:

1. 첫 문장 hook
2. 핵심 요약 2~4줄
3. 슬라이드 읽는 이유
4. 대표 블로그 링크 CTA
5. 관련 YouTube 링크 또는 예고
6. 해시태그

해시태그 요구사항:

- 대형 / 중형 / 니치 태그 조합
- 주제 태그
- 문제 해결 태그
- 브랜드 태그
- 반복 태그 과다 사용 방지

### 3.5 업로드 실행 요구사항

필요 기능:

- Professional 계정 연결
- 캐러셀 이미지 업로드
- 캡션 입력
- 예약 또는 즉시 게시
- 결과 post URL 회수

실행 방식 후보:

- v1: 브라우저 자동화
- v2: Meta / Instagram 공식 API

### 3.6 업로드 후 기록 요구사항

필요 저장값:

- remote post id
- remote post url
- scheduled_for
- published_at
- caption_final
- hashtags_final
- carousel file list
- cover index
- upload status
- last error

### 3.7 운영 검증 요구사항

필요 검증:

- 페이지 수 제한 검증
- 이미지 순서 검증
- 비율 검증
- 캡션 길이 검증
- 링크 삽입 정책 검증
- 한글 / 특수문자 깨짐 검증
- 동일 자산 중복 게시 방지

## 4. 공통 미디어 처리 요구사항

### 4.1 로컬 저장소 구조

필요 디렉터리:

- `inputs/youtube`
- `inputs/instagram`
- `processed/youtube`
- `processed/instagram`
- `staging/instagram`
- `staging/youtube`

### 4.2 자산 메타 저장

필요 항목:

- 원본 경로
- 파생 경로
- mime type
- byte size
- width / height
- duration
- page index
- checksum
- generator type

### 4.3 retention 정책

필요 정책:

- 원본 영상 / PDF / PPT 보관일수
- 파생 썸네일 / 캐러셀 이미지 보관일수
- 게시 성공 후만 삭제 여부
- URL 메타는 영구 보존

## 5. 인증 / 업로드 연결 요구사항

### 5.1 YouTube

필요 항목:

- 계정별 인증
- 채널 선택
- 업로드 권한
- 예약 게시 권한
- 상태 조회 권한

### 5.2 Instagram

필요 항목:

- Professional 계정 여부 확인
- 계정 연결 상태 저장
- 업로드 권한
- 예약 / 게시 상태 조회

### 5.3 공통

필요 항목:

- 토큰 만료 감지
- 재인증 유도
- 계정별 분리 저장
- 계정 A / B 혼선 방지

## 6. 스케줄링 / 운영 요구사항

### 6.1 예약 정책

필요 항목:

- 채널별 기본 예약 간격
- 같은 계정 동시 업로드 방지
- 같은 브랜드의 블로그 / 유튜브 / 인스타 순차 게시
- 게시 실패 시 재시도 규칙

### 6.2 실행 주체

권장 구조:

- 메타 생성: Codex CLI
- 미디어 전처리: MCP 또는 로컬 툴
- 업로드 실행: 브라우저 자동화 또는 플랫폼 API
- 예약 큐 / 상태 기록: 로컬 DB

### 6.3 운영 로그

필요 로그:

- 입력 파일
- 사용 모델
- 생성된 제목 / 캡션 / 태그
- 업로드 시각
- 예약 시각
- 원격 URL
- 에러 코드
- 재시도 횟수

## 7. UI 요구사항

필요 화면:

- 계정 연결 상태
- 업로드 대기함
- 예약 목록
- 실패 목록
- 채널별 최근 게시물
- 파일 입력 화면
- 메타 생성 미리보기
- 승인 / 수정 / 재실행 버튼

채널별 입력 UX:

- YouTube: 영상 파일 + 제목 초안 + 예약 시각
- Instagram: PPT/PDF 업로드 + 비율 옵션 + 예약 시각

## 8. DB / API 요구사항

### 8.1 DB

필요 엔티티:

- `channel_accounts`
- `content_projects`
- `publications`
- `media_assets`
- `publish_attempts`
- `retention_policies`

### 8.2 API

필요 API 축:

- 파일 등록
- 메타 생성
- publish package 생성
- 업로드 실행
- 예약 등록
- 상태 조회
- 실패 재시도

## 9. 구현 우선순위

### 1차 우선 구현

- YouTube 메타 자동 생성
- YouTube 업로드 / 예약
- Instagram PDF 분리
- Instagram 캐러셀 이미지 생성
- Instagram 캡션 / 해시태그 생성
- 양 채널 결과 URL DB 저장

### 2차 구현

- 썸네일 고도화
- Instagram 커버 최적화
- 크로스링크 자동 sync
- 실패 재시도 고도화
- retention 자동 삭제

### 3차 구현

- 성과 데이터 기반 제목 재학습
- CTR 패턴 분석
- 계정별 A/B 테스트

## 10. 바로 필요한 구현 항목 체크리스트

- [ ] YouTube 계정 인증 구조
- [ ] Instagram Professional 계정 인증 구조
- [ ] 채널별 계정 저장 테이블
- [ ] 영상 업로드 입력 화면
- [ ] PPT / PDF 업로드 입력 화면
- [ ] PDF 페이지 분리 엔진
- [ ] PPT 변환 전략
- [ ] 캐러셀 이미지 리사이즈 규칙
- [ ] 썸네일 생성 규칙
- [ ] YouTube 제목 / 설명 / 태그 생성 프롬프트
- [ ] Instagram 캡션 / 해시태그 / CTA 생성 프롬프트
- [ ] 예약 게시 큐
- [ ] 업로드 성공 URL 회수
- [ ] 실패 로그 및 재시도 정책
- [ ] 로컬 자산 retention 정책
- [ ] 블로그 / 유튜브 / 인스타 cross-link 저장 구조

## 11. 최종 판단

YouTube와 Instagram 자동 업로드를 붙이려면 필요한 것은 아래 4개 묶음이다.

1. 생성:
   - 제목, 설명, 태그, 캡션, 해시태그, CTA
2. 자산:
   - 영상, 썸네일, PDF/PPT 분리, 캐러셀 이미지
3. 업로드:
   - 인증, 예약, 결과 URL 회수, 재시도
4. 운영:
   - 계정, DB, 로그, 승인, retention, cross-link

즉 “프롬프트 생성”만 구현해서는 부족하고, 실제로는 `채널 계정 + 미디어 전처리 + 업로드 실행기 + 상태 기록`까지 같이 들어가야 YouTube / Instagram 자동 게시가 완성된다.
