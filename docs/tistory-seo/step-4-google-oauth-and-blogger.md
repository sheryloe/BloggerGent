# Step 4. Google OAuth와 Blogger 연결에서 실제로 막히는 포인트

## 추천 제목

1. Blogger API 연결할 때 가장 많이 막히는 Google OAuth 설정 정리
2. Google OAuth Testing, Redirect URI, Test Users까지 한 번에 정리한 Blogger 연동 가이드
3. Blogger 자동화에서 OAuth가 중요한 이유와 실제 설정 순서

## 검색 설명

Google OAuth와 Blogger API를 연결할 때 가장 자주 막히는 Redirect URI, Testing 모드, Test users, 토큰 저장 문제를 실전 기준으로 정리했다.

## 추천 태그

`#GoogleOAuth #BloggerAPI #RedirectURI #TestUsers #GoogleCloudConsole #Blogger연동`

## 본문

Blogger 자동화에서 가장 먼저 부딪히는 진짜 벽은 AI 모델이 아니라 Google OAuth다. 글 생성 로직은 나중 문제고, 일단 Blogger 블로그 목록을 읽어오고 발행 권한을 얻으려면 OAuth부터 정확히 맞아야 한다. 여기서 한 번 삐끗하면 403, access denied, test users, redirect mismatch 같은 에러가 끝없이 나온다.

핵심은 세 가지다. 첫째, Google Cloud Console에서 OAuth Client를 `Web application` 타입으로 만들어야 한다. 둘째, Redirect URI를 정확하게 등록해야 한다. 셋째, 앱이 Testing 상태라면 실제로 로그인할 Google 계정을 Test users에 추가해야 한다. 이 세 가지 중 하나라도 빠지면 연결이 되지 않는다.

Redirect URI는 특히 자주 틀린다. 로컬 개발 기준이라면 `http://localhost:8000/api/v1/blogger/oauth/callback`처럼 백엔드가 실제로 콜백을 받을 주소와 완전히 일치해야 한다. 대문자 하나, 포트 하나가 달라도 실패한다. 또 사람들은 종종 프론트 주소를 넣는데, 실제 콜백을 처리하는 주체가 API 서버라면 백엔드 주소를 써야 한다.

Testing 상태의 함정도 크다. 본인 계정으로는 잘 될 줄 알았는데, 막상 Google이 허용한 테스트 사용자 목록에 들어 있지 않으면 곧바로 차단된다. 그래서 “왜 분명히 Client ID와 Secret은 맞는데 로그인 후 막히지?”라는 상황이 자주 발생한다. 이 부분은 문서보다 직접 겪고 나서야 구조가 이해되는 경우가 많다.

토큰 저장도 단순하지 않다. 액세스 토큰은 만료되고, 실제 운영에서는 refresh token이 중요하다. BloggerGent에서는 이 값을 설정 테이블에 그대로 평문으로 넣는 대신 암호화해서 저장하도록 바꿨다. 혼자 쓰는 도구라도, 토큰이 그대로 남는 구조는 나중에 로컬 백업이나 DB 유출 상황에서 꽤 위험할 수 있기 때문이다.

연결이 완료되면 Blogger 블로그 목록을 실제로 불러오고, 그중 필요한 블로그만 서비스용 블로그로 import하는 단계로 넘어간다. 이때부터 비로소 “한 계정에 여러 블로그가 있을 때 각각 다른 워크플로를 운영하는 구조”가 시작된다. 결국 OAuth는 단순 로그인 절차가 아니라, 블로그 자동화 서비스의 입구이자 권한 모델 전체를 결정하는 핵심 단계다.

## HTML 예시

```html
<h2>OAuth 설정 핵심</h2>
<ul>
  <li>Web application 타입으로 Client 생성</li>
  <li>Redirect URI를 정확히 등록</li>
  <li>Testing 상태면 Test users 추가</li>
</ul>

<h2>실무 포인트</h2>
<p>액세스 토큰보다 중요한 것은 refresh token이다. 운영형 도구라면 토큰 저장 방식까지 같이 설계해야 한다.</p>
```
