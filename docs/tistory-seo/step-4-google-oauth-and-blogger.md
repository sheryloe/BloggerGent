# Step 4. Google OAuth와 Blogger API 연동 정리

## 추천 제목
- Google OAuth로 Blogger 자동 게시 붙이는 방법 정리
- Blogger API는 왜 OAuth가 필요한가? 직접 붙여본 실전 기록
- 구글 블로그 자동 게시 만들기: OAuth, Blogger, Search Console, GA4 연결

## 검색 설명
Google OAuth와 Blogger API를 연결해 실제 블로그 목록 조회와 자동 게시를 가능하게 만든 과정을 정리한 실전 글입니다.

## 추천 태그
`GoogleOAuth`, `BloggerAPI`, `SearchConsoleAPI`, `GA4API`, `구글연동`

## 글 구조
- Blogger 게시에 왜 OAuth가 필요한가
- Client ID, Secret만으로는 왜 안 되는가
- Test users와 Production 전환 이슈
- 여러 Blogger 블로그를 같은 계정에서 가져오는 흐름

## 본문 샘플

Blogger API는 공개 조회만으로 끝나는 서비스가 아닙니다. 실제 글을 쓰거나 내 계정의 블로그 목록을 읽으려면 반드시 OAuth 승인이 필요합니다.

즉 `Client ID`와 `Client Secret`만 저장한다고 끝나는 것이 아니라, 한 번은 실제 Google 계정으로 로그인하고 권한을 승인해야 합니다. 이 과정을 통과하면 `refresh token`을 저장해 이후 자동 게시가 가능해집니다.

## HTML 예시

```html
<h2>왜 Blogger API는 OAuth가 필요한가</h2>
<p>API Key만으로는 공개 데이터 조회 정도만 가능합니다.</p>
<p>하지만 내 Blogger 계정의 블로그 목록 조회, 글 작성, 발행은 계정 권한이 필요한 작업이라 OAuth가 필수입니다.</p>

<h2>실전에서 중요한 체크포인트</h2>
<ul>
  <li><strong>Redirect URI</strong>가 정확히 일치해야 합니다.</li>
  <li><strong>Testing</strong> 상태면 로그인 계정을 Test users에 추가해야 합니다.</li>
  <li><strong>refresh token</strong>이 저장되어야 이후 자동 발행이 가능합니다.</li>
</ul>
```

## 마무리 문장 예시

Google OAuth를 안정적으로 붙이고 나니, 이제 단순 생성이 아니라 실제 Blogger 운영 플로우가 완성되기 시작했습니다. 다음 글에서는 AI 글 생성, 이미지 생성, HTML 조립까지 이어지는 파이프라인을 정리하겠습니다.
