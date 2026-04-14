from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.db.session import SessionLocal
from app.services.cloudflare.cloudflare_channel_service import (
    _fetch_integration_post_detail,
    _integration_data_or_raise,
    _integration_request,
    _prepare_markdown_body,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts


PACKAGE_DATE = "20260414"
RETROFIT_ROOT = Path("D:/Donggri_Platform/BloggerGent/storage/retrofit/cloudflare") / PACKAGE_DATE


POSTS = [
    {
        "remote_id": "e9b53bcf-35d9-4d67-98e3-197a3e679684",
        "title": "CodeMate 실무 적용 2026 | 초안 생성은 어디까지, PR 전 검토는 어디서 끊을까",
        "excerpt": "CodeMate를 팀에 붙일 때 초안 생성, 테스트 정리, PR 전 검토까지 어디까지 맡기고 어디서 사람이 끊어야 하는지 실무 기준으로 정리한 글.",
        "seo_description": "CodeMate 실무 적용 범위를 정할 때 초안 생성, 테스트 정리, PR 전 검토, 운영 책임을 어떻게 나눌지 표와 단계 흐름으로 정리한 2026 가이드.",
        "cover_alt": "CodeMate를 실무 워크플로에 넣을 때 사람 검토 경계를 정리한 개발팀 작업 장면",
        "body": """
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>도입 요약</th></tr>
  <tr><td>CodeMate 같은 AI 코딩 보조 도구는 속도를 올리는 데는 분명히 도움이 된다. 다만 실무에서 중요한 건 “무엇을 잘하느냐”보다 “어디서 끊느냐”다. 이 글은 초안 생성, 반복 수정, 테스트 정리, PR 전 검토까지를 기준으로 CodeMate를 어디까지 맡겨도 되는지, 그리고 사람이 끝까지 붙잡아야 하는 경계를 표와 흐름으로 정리한다.</td></tr>
</table>

<p>개발팀이 AI 도구를 붙일 때 가장 많이 하는 실수는 성능 데모를 보고 곧바로 운영 범위를 넓혀 버리는 것이다. 처음에는 모든 것이 빨라 보이지만, 몇 주가 지나면 같은 문제가 반복된다. 초안은 빨리 나오는데 의도와 다른 코드가 섞이고, 검토자는 더 많은 문맥을 다시 읽어야 하며, 보안이나 권한 경계가 걸린 수정은 누가 책임질지 흐릿해진다. 그래서 CodeMate를 잘 쓰는 팀은 기능 목록보다 먼저 경계선을 그린다. 생성은 빠르게 받되, 승인과 책임은 사람 손에 둔다.</p>
<p>실무 기준으로 보면 CodeMate의 강점은 세 가지로 정리된다. 첫째, 요구사항이 이미 정리된 뒤의 초안 생성이 빠르다. 둘째, 반복되는 패턴 정리와 테스트 뼈대 작성에 강하다. 셋째, 이미 방향이 정해진 수정에서 탐색 비용을 줄여 준다. 반대로 약한 지점도 분명하다. 도메인 의미를 바꾸는 로직, 외부 공개 문서의 최종 문장, 운영 리스크가 큰 권한 처리, 결제나 인증 흐름처럼 실패 비용이 큰 구간은 사람이 직접 끝까지 읽어야 한다.</p>

<h2>먼저 정할 기준: 맡기는 일과 남기는 일</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>구간</th>
      <th>CodeMate에 맡기기 좋은 일</th>
      <th>사람이 끝까지 잡아야 할 일</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>초안 생성</td>
      <td>테스트 뼈대, 반복 함수 분리, 문서 초안, 리팩토링 후보 제안</td>
      <td>요구사항 해석, 예외 규칙 확정, 도메인 의미 판단</td>
    </tr>
    <tr>
      <td>수정 정리</td>
      <td>이름 정리, import 정리, 타입 보강, 반복 문장 압축</td>
      <td>성능 영향, 권한 경계, 운영 장애 가능성 확인</td>
    </tr>
    <tr>
      <td>PR 전 검토</td>
      <td>체크리스트 생성, 로그 요약, 누락 테스트 후보 제안</td>
      <td>최종 승인, merge 판단, 배포 리스크 책임</td>
    </tr>
  </tbody>
</table>

<p>이 표의 핵심은 AI 도구를 “리뷰 대체자”가 아니라 “리뷰 전 가속기”로 두는 것이다. 팀 리뷰를 통과하는 기준은 사람이 정하고, CodeMate는 그 기준까지 빠르게 데려가는 역할만 맡는 편이 안전하다. 이 선을 지키면 도구는 팀 생산성을 올리고, 선이 흐려지면 팀 검토 품질을 갉아먹는다.</p>

<h2>실무 적용 순서: 4단계 흐름으로 붙이기</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>단계</th>
      <th>해야 할 일</th>
      <th>멈춰야 하는 기준</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1단계</td>
      <td>반복 수정과 테스트 초안 같은 낮은 위험 구간에만 적용</td>
      <td>도메인 로직을 직접 바꾸는 제안이 나오면 바로 사람이 검토</td>
    </tr>
    <tr>
      <td>2단계</td>
      <td>PR 전 체크리스트, 변경점 요약, 누락 테스트 후보 생성</td>
      <td>보안, 권한, 결제, 인증 관련 제안은 자동 반영 금지</td>
    </tr>
    <tr>
      <td>3단계</td>
      <td>팀 공통 프롬프트와 금지 규칙을 AGENTS 규칙으로 고정</td>
      <td>지시가 길어질수록 책임 구간이 흐려지면 범위를 다시 축소</td>
    </tr>
    <tr>
      <td>4단계</td>
      <td>실제 리뷰 시간, 반려 원인, 재작업 비율을 주간 단위로 기록</td>
      <td>속도는 빨라졌는데 반려가 늘면 즉시 운영 범위를 줄임</td>
    </tr>
  </tbody>
</table>

<p>이 흐름에서 가장 중요한 건 한 번에 많이 맡기지 않는 것이다. CodeMate는 “많이 붙일수록 좋다”가 아니라 “잘라 붙일수록 오래 간다”에 가깝다. 초안 생성과 반복 정리처럼 성공과 실패가 눈에 잘 보이는 구간부터 시작해야 운영 기준을 만들 수 있다. 팀마다 코드베이스와 리뷰 문화가 다르기 때문에, 도구 성능보다 팀 규칙이 더 중요해지는 이유도 여기에 있다.</p>

<figure>
  <img src="__INLINE_IMAGE__" alt="CodeMate로 초안을 정리하고 사람이 PR 전 검토를 마무리하는 개발 워크플로" />
</figure>

<h2>실패가 나는 지점: 빠르지만 검증이 비는 순간</h2>
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>주의</th></tr>
  <tr><td>CodeMate를 도입한 뒤 리뷰 피로가 커졌다면, 도구가 과하게 개입하고 있다는 신호다. 생성물의 양은 늘었지만 검증 기준이 같이 고정되지 않은 경우가 대부분이다. 이때는 프롬프트를 더 길게 쓰기보다 적용 범위를 줄이는 편이 낫다.</td></tr>
</table>

<p>실무에서 흔한 실패는 세 가지다. 첫째, 사람이 할 판단까지 도구에 넘기는 경우다. 둘째, 초안과 최종본의 경계를 문서로 남기지 않는 경우다. 셋째, 비용과 호출량을 따로 보지 않는 경우다. CodeMate는 매번 도움을 주는 것처럼 보이기 때문에 호출이 쉽게 늘어난다. 하지만 반복 호출이 쌓이면 비용도 늘고, 팀원별 품질 편차도 커진다. 그래서 운영자는 최소한 주간 호출량, 리뷰 반려 사유, 재작업 시간을 함께 봐야 한다.</p>

<h2>팀 기준표: 도입 전에 합의해야 할 질문</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>질문</th>
      <th>합의 기준</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>어디까지 자동으로 제안받을 것인가</td>
      <td>초안, 반복 정리, 테스트 보강까지만 허용</td>
    </tr>
    <tr>
      <td>누가 최종 승인하는가</td>
      <td>PR 승인 권한자는 사람이 유지</td>
    </tr>
    <tr>
      <td>금지 영역은 무엇인가</td>
      <td>인증, 권한, 결제, 외부 공개 문구는 수동 검토 필수</td>
    </tr>
    <tr>
      <td>성공을 무엇으로 볼 것인가</td>
      <td>PR 준비 시간 단축 + 반려 증가 없음</td>
    </tr>
  </tbody>
</table>

<p>결국 CodeMate를 잘 쓰는 팀은 더 많이 자동화하는 팀이 아니라, 더 선명하게 경계를 적는 팀이다. 초안을 빠르게 받는 건 이제 어렵지 않다. 문제는 그 초안이 누구의 책임 아래 어디까지 올라갈 수 있느냐다. 그 선이 분명하면 도구는 팀을 돕고, 그 선이 흐리면 도구는 팀의 피로를 늘린다.</p>

<h2>마무리 기록</h2>
<p>동그리 아카이브는 CodeMate 같은 코딩 도구를 “정답을 대신 내는 도구”로 보지 않는다. 오히려 사람이 더 중요한 판단에 시간을 쓰게 만드는 앞단의 보조자로 본다. 초안 생성은 과감하게 맡기고, 운영 책임은 끝까지 사람이 지는 구조. 실무에서 오래 버티는 방식은 결국 이 균형에 가깝다.</p>

<h2>자주 묻는 질문</h2>
<details>
  <summary>CodeMate를 바로 팀 전체에 붙여도 될까요?</summary>
  <p>권장하지 않는다. 반복 수정과 테스트 초안처럼 위험이 낮은 구간부터 시작하고, 반려 사유와 재작업 시간을 먼저 기록하는 편이 안전하다.</p>
</details>
<details>
  <summary>PR 리뷰도 CodeMate에 맡기면 되나요?</summary>
  <p>리뷰 전 체크리스트와 변경점 요약까지는 도움을 줄 수 있지만, 승인과 운영 리스크 판단은 사람이 맡아야 한다.</p>
</details>
""",
    },
    {
        "remote_id": "3455a792-f5dd-4011-9f48-92784c01f45c",
        "title": "인사동 산책 가이드 2026 | 골목 공방과 찻집, 갤러리를 반나절에 묶는 동선",
        "excerpt": "인사동을 처음 걷는 사람도 골목 공방, 전통 찻집, 갤러리를 반나절 안에 자연스럽게 묶을 수 있도록 동선과 쉬는 포인트를 정리한 글.",
        "seo_description": "인사동 반나절 산책 동선을 기준으로 공방, 전통 찻집, 작은 갤러리, 붐비는 시간, 쉬어가기 포인트를 표와 흐름으로 정리한 2026 가이드.",
        "cover_alt": "인사동 골목에서 공방과 갤러리, 전통 찻집을 차례로 둘러보는 산책 장면",
        "body": """
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>도입 카드</th></tr>
  <tr><td>인사동은 유명한 거리라는 이유만으로 가면 쉽게 지친다. 메인 거리만 걷고 나오면 비슷한 기념품 가게만 본 듯한 인상으로 끝나기 쉽기 때문이다. 이 글은 처음 가는 사람도 골목 공방, 조용한 찻집, 작은 갤러리를 반나절 안에 자연스럽게 묶을 수 있도록 순서를 다시 잡는다. 핵심은 많이 보는 것이 아니라, 분위기가 잘 이어지는 흐름으로 걷는 것이다.</td></tr>
</table>

<p>인사동의 매력은 한 번에 드러나지 않는다. 대로변에는 사람과 간판이 먼저 보이지만, 한 블록만 안으로 들어가면 종이 냄새가 나는 공방, 유리창 안쪽에서 조용히 작업 중인 금속 공예점, 나무 마루가 있는 찻집, 전시 규모는 작아도 오래 서 있게 만드는 갤러리가 이어진다. 그래서 인사동은 체크리스트보다 동선이 중요하다. 어디서 시작해 어느 골목으로 빠지고, 어느 시점에 쉬고, 언제 다시 메인 거리로 나올지를 정해 두면 같은 거리도 훨씬 다르게 읽힌다.</p>

<h2>반나절 동선: 메인 거리보다 골목을 먼저 읽기</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>순서</th>
      <th>구간</th>
      <th>보는 포인트</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1</td>
      <td>안국역 쪽 진입</td>
      <td>사람이 몰리기 전 골목 분위기를 먼저 익힌다</td>
    </tr>
    <tr>
      <td>2</td>
      <td>공방 골목</td>
      <td>한지, 금속, 도자 계열 작업실과 소형 편집 상점</td>
    </tr>
    <tr>
      <td>3</td>
      <td>전통 찻집 구간</td>
      <td>걸음을 늦추고 소음이 적은 곳에서 쉬어간다</td>
    </tr>
    <tr>
      <td>4</td>
      <td>소형 갤러리</td>
      <td>작품 수보다 동선 밀도가 좋은 전시를 고른다</td>
    </tr>
    <tr>
      <td>5</td>
      <td>메인 거리 재진입</td>
      <td>기념품 구간은 마지막에 짧게 훑는 편이 덜 지친다</td>
    </tr>
  </tbody>
</table>

<p>이 순서를 추천하는 이유는 단순하다. 메인 거리부터 들어가면 사람과 상점 정보가 너무 많아 골목에 들어갈 집중력이 빨리 떨어진다. 반대로 안국역 쪽에서 시작해 공방 골목을 먼저 보면 인사동이 왜 여전히 걸어 볼 가치가 있는지 더 빨리 느끼게 된다. 전통적인 풍경을 보러 가는 것이 아니라, 손으로 만든 물건과 천천히 머물 수 있는 공간이 아직 남아 있다는 사실을 확인하게 되는 것이다.</p>

<h2>멈춰 볼 구간: 화려한 곳보다 오래 머무는 곳</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>구간</th>
      <th>추천 이유</th>
      <th>머무는 시간</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>공방 골목</td>
      <td>상점보다 작업 분위기가 살아 있는 구간이 많다</td>
      <td>30~40분</td>
    </tr>
    <tr>
      <td>전통 찻집</td>
      <td>걷는 속도를 늦추고 다음 동선을 정리하기 좋다</td>
      <td>20~30분</td>
    </tr>
    <tr>
      <td>소형 갤러리</td>
      <td>크지 않아도 전시 흐름이 분명한 곳이 많다</td>
      <td>25~35분</td>
    </tr>
  </tbody>
</table>

<figure>
  <img src="__INLINE_IMAGE__" alt="인사동 골목의 공방과 작은 갤러리 사이를 걷는 장면" />
</figure>

<p>인사동에서 만족도가 높았던 시간은 대체로 “예상보다 조용했던 구간”에서 나왔다. 한지 노트나 도자 잔을 구경하는 몇 분, 작은 전시 설명문을 천천히 읽는 몇 분, 차 한 잔을 놓고 다음 골목을 정하는 몇 분이 계속 이어지면 인사동은 관광지가 아니라 기록이 남는 거리로 바뀐다. 그래서 반나절 코스라면 먹거리 욕심을 크게 내기보다, 걷기와 쉬기를 번갈아 넣는 편이 더 좋다.</p>

<h2>주의사항: 사람이 몰리는 시간과 피로가 쌓이는 지점</h2>
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>주의 박스</th></tr>
  <tr><td>주말 오후에는 메인 거리 체류 시간을 짧게 잡는 편이 낫다. 사진을 찍기 위해 멈춰 선 사람과 단체 이동이 겹치면 골목으로 빠지기 전부터 피로가 올라간다. 가능하면 오전 늦게 들어가 공방 골목과 찻집 구간을 먼저 보고, 메인 거리는 마지막 20분 정도만 쓰는 편이 만족도가 높다.</td></tr>
</table>

<p>또 하나 기억할 점은 인사동이 “많이 사는 거리”가 아니라 “무엇을 남길지 고르는 거리”라는 점이다. 기념품점은 많지만, 실제로 기억에 남는 건 대개 작은 골목에서 본 작업실 풍경과 조용히 쉬었던 찻집이다. 이런 구조를 알고 가면 반나절 안에서도 충분히 밀도 있는 산책이 가능하다.</p>

<h2>같이 보면 좋은 포인트 표</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>상황</th>
      <th>추천 선택</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>처음 방문</td>
      <td>메인 거리보다 안국역 쪽 골목 진입을 먼저 선택</td>
    </tr>
    <tr>
      <td>비 오는 날</td>
      <td>찻집과 실내 갤러리 비중을 높이고 골목 구간은 짧게</td>
    </tr>
    <tr>
      <td>사진 위주 방문</td>
      <td>사람 적은 시간대에 골목과 한옥 마감 구간 중심</td>
    </tr>
  </tbody>
</table>

<h2>마무리 기록</h2>
<p>인사동은 익숙한 이름이지만, 실제로 기억에 남는 건 번화한 대로보다 골목의 공기다. 동그리 아카이브는 인사동을 “볼거리 많은 거리”보다 “속도를 낮출 때 비로소 읽히는 거리”로 기억한다. 반나절만 있어도 충분하다. 다만 그 반나절을 어디서 시작하느냐가 전체 인상을 바꾼다.</p>

<h2>자주 묻는 질문</h2>
<details>
  <summary>인사동은 처음 가도 반나절이면 충분할까요?</summary>
  <p>충분하다. 다만 메인 거리부터 오래 머물기보다 공방 골목과 찻집, 소형 갤러리를 먼저 묶는 편이 더 만족스럽다.</p>
</details>
<details>
  <summary>주말에도 갈 만한가요?</summary>
  <p>가능하다. 대신 오후 피크 시간대 메인 거리 체류를 짧게 잡고, 골목 진입을 먼저 하는 것이 좋다.</p>
</details>
""",
    },
    {
        "remote_id": "6939bf7e-0827-410d-9f2c-8f6b50543941",
        "title": "진해군항제 하루 코스 2026 | 여좌천 시작, 경화역 마감, 저녁 복귀까지 무리 없는 순서",
        "excerpt": "진해군항제를 하루에 돌 때 여좌천, 경화역, 식사, 복귀 시간을 무리 없이 묶을 수 있도록 현장 동선 중심으로 정리한 가이드.",
        "seo_description": "진해군항제 하루 코스를 기준으로 여좌천 시작, 경화역 마감, 식사 위치, 붐비는 시간, 복귀 동선을 표와 체크포인트로 정리한 2026 현장 가이드.",
        "cover_alt": "진해군항제 벚꽃 구간을 하루 동선으로 묶어 걷는 현장 풍경",
        "body": """
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>도입 카드</th></tr>
  <tr><td>진해군항제는 사진 한 장으로 기억되는 축제가 아니라, 어디서 시작하고 어디서 끝낼지에 따라 체력과 만족도가 크게 달라지는 현장이다. 이 글은 여좌천을 먼저 보고 경화역을 나중에 묶는 하루 코스를 기준으로, 식사와 대기 시간을 줄이고 저녁 복귀까지 무리 없이 마칠 수 있는 순서를 정리한다.</td></tr>
</table>

<p>진해군항제를 처음 가면 가장 많이 하는 실수가 “유명한 곳을 아무 순서 없이 다 가 보자”는 계획이다. 문제는 여좌천과 경화역이 같은 벚꽃 명소처럼 보이지만, 현장에서 느끼는 체력 소모와 이동 피로는 꽤 다르다는 점이다. 사람 밀도가 높은 시간대에 동선을 잘못 잡으면 이동 자체가 행사가 되고, 정작 벚꽃을 보는 시간은 줄어든다. 그래서 하루 코스라면 출발 시간과 이동 순서를 먼저 정해야 한다.</p>

<h2>하루 흐름: 여좌천을 먼저 보고 경화역을 늦게 묶기</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>순서</th>
      <th>구간</th>
      <th>이유</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1</td>
      <td>오전 진해 진입</td>
      <td>도착 지연이 생겨도 핵심 구간을 오전에 확보할 수 있다</td>
    </tr>
    <tr>
      <td>2</td>
      <td>여좌천</td>
      <td>빛이 올라오기 전에 천변 구간을 먼저 보는 편이 덜 붐빈다</td>
    </tr>
    <tr>
      <td>3</td>
      <td>중간 식사와 휴식</td>
      <td>한낮 혼잡 시간에 이동 대신 체력 회복에 쓰는 편이 낫다</td>
    </tr>
    <tr>
      <td>4</td>
      <td>경화역</td>
      <td>오후 후반에 가면 사진 구도와 체류 시간이 정리되기 쉽다</td>
    </tr>
    <tr>
      <td>5</td>
      <td>저녁 복귀</td>
      <td>축제 종료 직전 혼잡을 피하고 무리 없이 빠져나올 수 있다</td>
    </tr>
  </tbody>
</table>

<p>여좌천을 먼저 보는 이유는 단순하다. 축제 초행자에게 가장 부담이 큰 것은 사람을 비집고 이동하는 일인데, 그 피로가 오전부터 시작되면 하루 전체가 무너진다. 반면 오전의 여좌천은 비교적 천천히 걸을 수 있고, 물가를 따라 흐르는 벚꽃 구간이 길어 처음 도착한 사람도 리듬을 잡기 좋다. 경화역은 상징성이 크지만 체류 인원이 몰리는 시간이 분명하므로, 하루 끝쪽에 두는 편이 낫다.</p>

<h2>현장 포인트: 어디서 멈추고 어디서는 오래 머물지 말아야 하나</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>구간</th>
      <th>멈출 포인트</th>
      <th>오래 머물지 말아야 할 이유</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>여좌천</td>
      <td>다리 근처보다 천변의 연결 구간</td>
      <td>대표 포인트만 고집하면 이동 흐름이 끊긴다</td>
    </tr>
    <tr>
      <td>식사 구간</td>
      <td>메인 동선에서 한 블록 빠진 곳</td>
      <td>줄이 짧아 체력 회복 시간이 확보된다</td>
    </tr>
    <tr>
      <td>경화역</td>
      <td>플랫폼 진입 직전과 측면 시야</td>
      <td>한 지점에 오래 서 있으면 복귀 시간이 늦어진다</td>
    </tr>
  </tbody>
</table>

<figure>
  <img src="__INLINE_IMAGE__" alt="진해군항제 벚꽃 구간을 따라 걷는 축제 현장 풍경" />
</figure>

<h2>먹거리와 휴식: 축제는 걷기보다 쉬는 타이밍이 중요하다</h2>
<p>진해군항제에서 만족도가 높은 사람들은 대체로 쉬는 시간을 먼저 확보한다. 점심을 너무 늦게 먹으면 경화역 구간에서 집중력이 떨어지고, 줄이 긴 메인 구역에만 머물면 발걸음이 무거워진다. 축제 현장은 많이 보는 것보다 “언제 앉고 언제 다시 걷느냐”가 더 중요하다. 메인 구간에서 한 블록만 벗어나도 훨씬 조용한 식사 자리가 생기고, 그 30분의 차이가 저녁 복귀 피로를 크게 줄인다.</p>

<h2>주의사항: 사진 욕심보다 복귀 시간 계산이 먼저</h2>
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>주의 박스</th></tr>
  <tr><td>진해군항제는 마지막 구간에서 욕심을 내기 쉽다. 하지만 해가 질 무렵의 사진을 더 찍겠다고 머무는 시간이 길어지면 복귀 동선이 급격히 무거워진다. 특히 대중교통 이용자는 경화역 체류 시간을 미리 정해 두는 편이 좋다. 좋은 하루 코스는 마지막 10분까지 즐기는 코스가 아니라, 무리 없이 돌아오는 코스다.</td></tr>
</table>

<h2>하루 코스를 정할 때 체크할 질문</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>질문</th>
      <th>권장 답</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>처음 간다면 어디부터?</td>
      <td>여좌천</td>
    </tr>
    <tr>
      <td>사진 명소는 언제?</td>
      <td>오전은 여좌천, 오후 후반은 경화역</td>
    </tr>
    <tr>
      <td>식사는 어디서?</td>
      <td>메인 밀집 구간에서 한 블록 빠진 곳</td>
    </tr>
    <tr>
      <td>복귀는 언제 끊을까?</td>
      <td>해가 완전히 진 뒤보다 조금 이른 시점</td>
    </tr>
  </tbody>
</table>

<h2>마무리 기록</h2>
<p>진해군항제는 벚꽃의 밀도만으로 남는 축제가 아니다. 어디서 시작하고, 어디서 쉬고, 어디서 욕심을 멈추는지가 하루의 인상을 결정한다. 동그리 아카이브는 여좌천의 흐름으로 시작해 경화역의 상징성으로 마무리하는 구성이 가장 덜 지치고 오래 기억에 남는다고 본다.</p>

<h2>자주 묻는 질문</h2>
<details>
  <summary>진해군항제는 하루에 다 보기 어려운가요?</summary>
  <p>모든 명소를 다 보는 것은 어렵지만, 여좌천과 경화역을 중심으로 동선을 잡으면 핵심 분위기는 하루에도 충분히 담을 수 있다.</p>
</details>
<details>
  <summary>경화역을 먼저 가면 안 되나요?</summary>
  <p>가능하지만 초행자라면 이동 피로가 빨리 올라올 수 있다. 여좌천을 먼저 보고 경화역을 뒤에 두는 편이 하루 흐름이 안정적이다.</p>
</details>
""",
    },
    {
        "remote_id": "9eccfb8e-e1c3-443c-b1db-b29913b41751",
        "title": "경주 고분 미스터리 2026 | 봉분 아래 기록, 발굴 공백, 끝내 남는 세 가지 질문",
        "excerpt": "경주 고분을 둘러싼 기록과 발굴 공백, 도굴 흔적, 해석 충돌을 시간순으로 정리하고 지금도 남아 있는 질문을 좇아가는 글.",
        "seo_description": "경주 고분 미스터리를 사건 개요, 발굴 기록, 도굴 흔적, 해석 충돌, 현재 남은 질문까지 표와 타임라인 중심으로 정리한 2026 글.",
        "cover_alt": "경주 고분 봉분과 발굴 기록을 단서처럼 추적하는 미스터리 다큐멘터리 분위기의 장면",
        "body": """
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>사건 개요 박스</th></tr>
  <tr><td>경주의 고분은 관광 명소이면서 동시에 늘 질문을 남기는 장소다. 봉분의 크기와 위치, 발굴 시기의 공백, 도굴 흔적, 기록이 남지 않은 유물 이동까지 겹치면 하나의 무덤이 아니라 기록의 미로처럼 보이기 시작한다. 이 글은 특정 전설을 덧씌우지 않고, 실제로 남아 있는 기록과 공백을 나란히 놓아 경주 고분 미스터리가 왜 반복해서 호출되는지 따라간다.</td></tr>
</table>

<p>경주 고분이 미스터리로 남는 이유는 ‘모르는 것이 많아서’가 아니다. 오히려 알려진 사실과 빠진 기록이 너무 가까이 붙어 있기 때문이다. 발굴 연도는 남아 있는데 현장 사진이 빠져 있고, 봉분의 구조 설명은 있는데 유물 이동 경로가 빈칸으로 남아 있고, 도굴 흔적은 언급되는데 정확한 훼손 시점은 흐려지는 식이다. 이런 공백은 시간이 지날수록 상상을 부르지만, 동시에 문헌을 더 꼼꼼히 읽게 만든다.</p>

<h2>타임라인: 무엇이 남았고 어디가 비어 있는가</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>시점</th>
      <th>기록으로 확인되는 사실</th>
      <th>여전히 빈칸인 부분</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>초기 조사기</td>
      <td>봉분 위치와 대략적 규모 기록</td>
      <td>당시 현장 훼손 여부의 구체 기록 부족</td>
    </tr>
    <tr>
      <td>발굴기</td>
      <td>내부 구조와 일부 유물 정리</td>
      <td>왜 특정 구간 기록이 빠졌는지 불명확</td>
    </tr>
    <tr>
      <td>정비기</td>
      <td>관람 동선과 안내 체계 정비</td>
      <td>초기 훼손 흔적과 현재 복원 범위의 경계가 흐림</td>
    </tr>
  </tbody>
</table>

<p>이 타임라인에서 중요한 건 극적인 전설보다 행정 기록의 빈칸이다. 관광 안내문만 읽으면 고분은 안정적으로 보존된 장소처럼 보이지만, 조사 보고서와 현장 정비 이력을 함께 보면 생각보다 많은 구간이 “정확히 언제, 어떤 상태였는지”가 흐릿하다. 미스터리는 바로 그 흐릿함에서 생긴다.</p>

<h2>단서 표: 자주 언급되지만 쉽게 지나치는 지점</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>단서</th>
      <th>왜 중요한가</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>봉분 외곽 훼손 흔적</td>
      <td>자연 훼손인지 인위적 개입인지 해석이 갈린다</td>
    </tr>
    <tr>
      <td>유물 기록의 불균형</td>
      <td>어떤 유물은 세밀하고 어떤 유물은 지나치게 간략하다</td>
    </tr>
    <tr>
      <td>발굴 공백기</td>
      <td>현장 통제가 느슨했던 시기 추정과 연결된다</td>
    </tr>
  </tbody>
</table>

<figure>
  <img src="__INLINE_IMAGE__" alt="경주 고분 봉분과 발굴 기록을 함께 추적하는 미스터리 다큐멘터리 장면" />
</figure>

<h2>해석 비교: 음모론보다 기록의 틈을 봐야 하는 이유</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>해석</th>
      <th>근거</th>
      <th>한계</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>단순한 시간 손실</td>
      <td>초기 조사 체계가 지금보다 거칠었다</td>
      <td>일부 누락은 단순 실수로 보기 어렵다</td>
    </tr>
    <tr>
      <td>도굴 또는 인위적 이동</td>
      <td>봉분 훼손 흔적과 기록 불균형</td>
      <td>정확한 시점과 범위를 단정할 자료가 부족하다</td>
    </tr>
    <tr>
      <td>정비 과정의 재구성</td>
      <td>현재 모습과 초기 기록 사이 차이</td>
      <td>복원이 어디까지였는지 세부 설명이 모자란다</td>
    </tr>
  </tbody>
</table>

<p>경주 고분 미스터리의 흥미로운 지점은 “무언가 숨겼다”는 자극적인 상상보다, 왜 이 정도로 중요한 장소에서 기록의 연속성이 매끄럽지 않았는가에 있다. 문헌의 빈칸은 언제나 전설을 부르지만, 동시에 더 정확한 질문을 가능하게 한다. 무엇이 빠졌는가, 왜 그 시점의 사진과 서술이 모자라는가, 현재의 안내는 어느 정도까지 복원된 상태를 보여 주는가. 이 질문이 남아 있는 한 고분은 완전히 닫힌 과거가 되지 않는다.</p>

<h2>현재 추적 상태: 지금 다시 보면 보이는 것</h2>
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>현재 추적 상태</th></tr>
  <tr><td>지금 기준으로 경주 고분의 미스터리를 다시 읽는 가장 좋은 방법은 현장 감상과 기록 대조를 분리하는 것이다. 현장에서는 봉분의 배치와 규모, 시선의 흐름을 보고, 기록에서는 발굴과 정비의 공백을 따로 읽어야 한다. 둘을 한꺼번에 보면 오히려 설명이 많아 보여 질문이 흐려진다.</td></tr>
</table>

<h2>마무리 기록</h2>
<p>동그리 아카이브는 경주 고분을 “정답이 없는 장소”라기보다 “기록을 끝까지 읽게 만드는 장소”로 본다. 봉분은 조용하지만, 그 아래를 둘러싼 서술은 여전히 완전히 닫히지 않았다. 그래서 이 미스터리는 낭설보다 기록의 빈칸을 오래 바라보게 만든다.</p>

<h2>자주 묻는 질문</h2>
<details>
  <summary>경주 고분 미스터리는 실제 음모론에 가까운 이야기인가요?</summary>
  <p>과장된 음모론으로만 보기보다, 발굴 기록과 훼손 흔적, 누락된 자료가 만든 해석 충돌로 보는 편이 더 정확하다.</p>
</details>
<details>
  <summary>현장에 가면 무엇을 중점적으로 보면 좋을까요?</summary>
  <p>봉분의 배치와 규모, 복원된 안내 체계, 기록상 공백이 언급되는 지점을 함께 보는 것이 좋다.</p>
</details>
""",
    },
    {
        "remote_id": "94b7caf7-687c-4492-b1d9-88d8c85413ad",
        "title": "AI 코딩 도구 선택 기준 2026 | 자동완성, 탐색, 수정 제안을 팀 규칙에 맞추는 법",
        "excerpt": "AI 코딩 도구를 고를 때 자동완성, 코드 탐색, 수정 제안을 무엇 기준으로 나눠야 하는지 팀 운영 관점에서 정리한 글.",
        "seo_description": "AI 코딩 도구를 고를 때 자동완성, 코드 탐색, 수정 제안, 권한 통제, 비용을 어떤 순서로 판단해야 하는지 비교표와 단계 흐름으로 정리한 2026 가이드.",
        "cover_alt": "AI 코딩 도구를 비교하며 팀 규칙과 개발 워크플로를 맞추는 장면",
        "body": """
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>도입 요약 박스</th></tr>
  <tr><td>AI 코딩 도구를 비교할 때 많은 팀이 모델 이름과 데모 속도부터 본다. 하지만 실제로 오래 쓰는 기준은 자동완성의 품질만이 아니다. 코드 탐색이 얼마나 안정적인지, 수정 제안을 어디까지 신뢰할 수 있는지, 권한과 비용을 팀 규칙에 맞게 묶을 수 있는지가 더 중요하다. 이 글은 그 판단 순서를 실무 기준으로 다시 정리한다.</td></tr>
</table>

<p>2026년의 개발 도구 시장은 충분히 화려하다. 자동완성, 채팅, 코드 검색, 테스트 보강, PR 요약, 문서 초안까지 대부분 비슷해 보인다. 그래서 오히려 선택이 더 어려워졌다. 기능 목록만 비교하면 어떤 도구든 다 쓸 만해 보이지만, 실제 운영에서는 도구가 팀 규칙을 얼마나 잘 따라오는지가 성패를 가른다. 누구는 빠른 자동완성이 중요하고, 누구는 저장소 전체 탐색이 중요하고, 누구는 수정 제안의 검증 가능성이 더 중요하다. 이 세 축을 나눠 보지 않으면 도구 선택은 늘 애매해진다.</p>

<h2>세 갈래로 나누면 판단이 쉬워진다</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>축</th>
      <th>질문</th>
      <th>왜 중요한가</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>자동완성</td>
      <td>짧은 반복 작업을 얼마나 줄여 주는가</td>
      <td>개인 생산성 체감에 가장 직접적이다</td>
    </tr>
    <tr>
      <td>코드 탐색</td>
      <td>저장소 문맥을 얼마나 안정적으로 읽는가</td>
      <td>대형 저장소일수록 탐색 품질 차이가 크게 난다</td>
    </tr>
    <tr>
      <td>수정 제안</td>
      <td>리팩토링과 패치 제안을 어디까지 믿을 수 있는가</td>
      <td>팀 리뷰 기준과 운영 책임에 직접 연결된다</td>
    </tr>
  </tbody>
</table>

<p>이 세 갈래를 구분하면 도구를 훨씬 현실적으로 볼 수 있다. 자동완성이 좋은 도구가 저장소 탐색까지 잘하는 것은 아니다. 반대로 코드 탐색이 좋은 도구가 팀 수정 제안을 안전하게 만들어 주는 것도 아니다. 그래서 팀 단위로는 “우리에게 가장 자주 아픈 구간이 무엇인지”부터 정리해야 한다. 반복 코딩이 문제라면 자동완성 축이 먼저고, 저장소 이해가 느리다면 탐색 축이 먼저며, PR 전 수정 품질이 흔들린다면 수정 제안 축을 먼저 봐야 한다.</p>

<h2>선택 기준 비교표</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>비교 기준</th>
      <th>체크 포인트</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>권한 통제</td>
      <td>저장소 접근 범위를 팀 규칙에 맞게 제한할 수 있는가</td>
    </tr>
    <tr>
      <td>비용 구조</td>
      <td>seat 비용과 호출 비용이 예측 가능한가</td>
    </tr>
    <tr>
      <td>검증 루프</td>
      <td>도구가 만든 수정안을 팀 리뷰 기준으로 다시 걸러낼 수 있는가</td>
    </tr>
    <tr>
      <td>문맥 유지</td>
      <td>파일 단위가 아니라 저장소 단위 이해가 가능한가</td>
    </tr>
  </tbody>
</table>

<figure>
  <img src="__INLINE_IMAGE__" alt="AI 코딩 도구를 비교하며 자동완성, 탐색, 수정 제안을 나눠 보는 개발팀 장면" />
</figure>

<h2>도입 단계 흐름: 빠른 체험보다 운영 기준부터</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>단계</th>
      <th>해야 할 일</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1단계</td>
      <td>반복 작업, 탐색 병목, 리뷰 병목 중 무엇이 제일 큰지 팀이 먼저 합의</td>
    </tr>
    <tr>
      <td>2단계</td>
      <td>한 도구에 모든 기대를 몰지 않고 축별로 장단점을 비교</td>
    </tr>
    <tr>
      <td>3단계</td>
      <td>권한, 비용, 로그, 승인 단계를 문서로 고정</td>
    </tr>
    <tr>
      <td>4단계</td>
      <td>주간 단위로 반려 사유와 재작업 시간을 확인하며 범위 조정</td>
    </tr>
  </tbody>
</table>

<h2>실패/주의 박스</h2>
<table border="1" cellpadding="10" cellspacing="0">
  <tr><th>주의</th></tr>
  <tr><td>팀이 도구를 고른 뒤에도 계속 불편하다면 성능이 아니라 기대치가 잘못 배치된 경우가 많다. 자동완성 도구에 저장소 탐색을 기대하거나, 탐색형 도구에 최종 수정 책임까지 맡기면 금방 피로가 쌓인다. 선택 기준은 늘 “무엇을 대신하게 할 것인가”보다 “무엇은 끝까지 사람 손에 남길 것인가”에서 출발해야 한다.</td></tr>
</table>

<p>실무에서 오래 가는 선택은 늘 단순하다. 빠른 자동완성이 필요하면 그 축에 맞는 도구를 고르고, 저장소 이해가 중요하면 탐색 축에 맞는 도구를 고른다. 그리고 어떤 도구를 쓰더라도 수정 책임과 승인 책임은 사람 기준으로 묶는다. 이 원칙을 지키면 도구는 팀 규칙을 돕고, 그렇지 않으면 팀 규칙을 흐린다.</p>

<h2>실무 판단 표</h2>
<table border="1" cellpadding="8" cellspacing="0">
  <thead>
    <tr>
      <th>팀 상황</th>
      <th>우선 봐야 할 축</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>반복 코딩이 많다</td>
      <td>자동완성</td>
    </tr>
    <tr>
      <td>저장소가 크고 문맥 파악이 느리다</td>
      <td>코드 탐색</td>
    </tr>
    <tr>
      <td>PR 품질 편차가 크다</td>
      <td>수정 제안 + 검증 루프</td>
    </tr>
  </tbody>
</table>

<h2>마무리 기록</h2>
<p>동그리 아카이브는 AI 코딩 도구를 “좋은 도구 하나를 고르는 문제”보다 “각 도구를 어디에 두는가”의 문제로 본다. 자동완성, 탐색, 수정 제안을 같은 바구니에 넣지 않으면 선택은 훨씬 선명해진다. 팀 규칙을 먼저 세우고 그 다음에 도구를 붙이는 편이 결국 오래 간다.</p>

<h2>자주 묻는 질문</h2>
<details>
  <summary>도구 하나로 자동완성과 탐색, 수정 제안을 모두 해결할 수 있나요?</summary>
  <p>가능한 경우도 있지만, 실무에서는 축별 강점이 다르기 때문에 역할을 나눠 보는 편이 더 안정적이다.</p>
</details>
<details>
  <summary>비용은 언제부터 따져야 하나요?</summary>
  <p>도입 전부터다. 사용자가 늘어난 뒤 비용을 보려 하면 호출 습관이 먼저 굳어 버려 조정이 어렵다.</p>
</details>
""",
    },
]


def _extract_first_inline_image(content: str) -> str:
    matches = re.findall(r'<img[^>]+src="([^"]+)"', content or "", flags=re.IGNORECASE)
    return matches[0].strip() if matches else ""


def _korean_char_len(text: str) -> int:
    return len(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", text or "")))


def main() -> None:
    RETROFIT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    with SessionLocal() as db:
        for item in POSTS:
            detail = _fetch_integration_post_detail(db, item["remote_id"])
            inline_image = _extract_first_inline_image(str(detail.get("content") or ""))
            if not inline_image:
                raise RuntimeError(f"inline image not found for {item['remote_id']}")
            body_html = str(item["body"]).replace("__INLINE_IMAGE__", inline_image).strip()
            category = detail.get("category") or {}
            payload = {
                "title": item["title"],
                "content": _prepare_markdown_body(item["title"], body_html),
                "excerpt": item["excerpt"],
                "seoTitle": item["title"],
                "seoDescription": item["seo_description"],
                "tagNames": [str(tag.get("name") or "").strip() for tag in (detail.get("tags") or []) if str(tag.get("name") or "").strip()],
                "categoryId": str(category.get("id") or "").strip(),
                "status": "published",
                "coverImage": str(detail.get("coverImage") or "").strip(),
                "coverAlt": item["cover_alt"],
            }
            package = {
                "remote_post_id": item["remote_id"],
                "slug": detail.get("slug"),
                "title": item["title"],
                "excerpt": item["excerpt"],
                "seo_description": item["seo_description"],
                "category": {
                    "id": category.get("id"),
                    "slug": category.get("slug"),
                    "name": category.get("name"),
                },
                "cover_image": detail.get("coverImage"),
                "inline_image": inline_image,
                "body_char_len": _korean_char_len(body_html),
                "payload": payload,
            }
            package_path = RETROFIT_ROOT / f"{detail.get('slug')}.json"
            package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")

            response = _integration_request(
                db,
                method="PUT",
                path=f"/api/integrations/posts/{item['remote_id']}",
                json_payload=payload,
                timeout=120.0,
            )
            updated = _integration_data_or_raise(response)
            results.append(
                {
                    "remote_post_id": item["remote_id"],
                    "slug": updated.get("slug"),
                    "title": updated.get("title"),
                    "public_url": updated.get("publicUrl"),
                    "body_char_len": package["body_char_len"],
                    "inline_image": inline_image,
                    "package_path": str(package_path),
                }
            )

        sync_result = sync_cloudflare_posts(db, include_non_published=True)

    print(json.dumps({"updated": results, "sync_result": sync_result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if not os.environ.get("SETTINGS_ENCRYPTION_SECRET"):
        raise RuntimeError("SETTINGS_ENCRYPTION_SECRET is required.")
    main()
