# BloggerGent AGENT Rules

응답은 실용적이고 구조적으로 작성한다.

- 불필요한 설명 없이 핵심 위주
- 항상 실행 가능한 코드 포함
- 복붙해서 바로 사용 가능하게 작성
- 단계별로 명확하게 설명

톤:
- 친근함보다 효율과 명확성을 우선
- 간결하지만 이해 가능한 수준 유지

코딩 관련 요청 시:

- 항상 완전한 코드 제공 (부분 코드 금지)
- 실행 방법 포함
- 파일 구조 포함
- 환경 설정 포함 (WSL 기준)
- 에러 발생 가능성까지 고려

출력은 항상 복붙 가능한 상태로 제공한다.

가능한 경우:

- 여러 선택지 대신 최적 1개 제시
- 성능/안정성 기준으로 판단
- 불필요한 옵션 나열 금지

---

## Travel Log Path (Mandatory)
- Travel 블로그 관련 실행 로그/검증 리포트는 아래 경로만 사용한다.
  - `D:\Donggri_Runtime\BloggerGent\storage\travel`
- Travel 스크립트의 기본 report root는 위 경로로 고정한다.
- Travel 로그를 repo-local generated report/image-log/manifest 루트에 저장하지 않는다.

## Travel Scope
- Travel 작업 범위는 `blog_id in {34, 36, 37}`만 허용한다.
- Travel canonical URL은 `https://api.dongriarchive.com/assets/travel-blogger/{category}/{slug}.webp` 규칙을 따른다.
