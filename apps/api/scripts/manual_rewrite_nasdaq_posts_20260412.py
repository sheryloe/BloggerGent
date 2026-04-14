from __future__ import annotations

import json

from app.db.session import SessionLocal
from app.services.cloudflare.cloudflare_channel_service import (
    _fetch_integration_post_detail,
    _integration_data_or_raise,
    _integration_request,
    _prepare_markdown_body,
)
from app.services.cloudflare.cloudflare_sync_service import list_synced_cloudflare_posts, sync_cloudflare_posts


IONQ_TITLE = "아이온큐 흐름 점검 2026-04-12 | 동그리 vs 햄니, IONQ를 지금 어디까지 믿을까"
IONQ_BODY = """
<section class="chat-thread">
<h2>오늘 왜 이 종목인가</h2>
<p>아이온큐를 볼 때 제일 먼저 확인할 것은 주가가 얼마나 급하게 움직였느냐보다, 시장이 이 회사를 어떤 서사로 다시 읽고 있느냐다. IONQ는 양자컴퓨팅이라는 거대한 미래 서사를 대표하는 이름이라서 한 번 기대가 붙으면 성장주 프리미엄이 빠르게 붙고, 반대로 실적 가시성이 흔들리면 프리미엄이 순식간에 줄어든다. 그래서 이 종목은 단순히 기술주 한 종목이 아니라, 아직 숫자가 작아도 미래 시장을 선점할 수 있는가라는 질문을 함께 끌고 다닌다.</p>
<p>지금 시점에서 다시 보는 이유도 여기에 있다. 클라우드 접근성, 정부 프로젝트, 기업 파트너십 같은 재료가 붙으면 시장은 아이온큐를 장기 서사의 앞줄에 세우려 하고, 반대로 수주 속도나 매출 인식이 기대보다 느리면 곧바로 밸류에이션 부담을 문제 삼는다. 결국 이 종목은 뉴스 한 줄보다도 기대가 실제 매출과 운영 지표로 얼마나 이어지는지, 그리고 그 간극을 시장이 얼마 동안 참아줄지를 같이 봐야 한다.</p>

<h2>기업 개요</h2>
<p>아이온큐는 trapped-ion 방식의 양자컴퓨팅 기술을 앞세우는 회사다. 시장이 이 회사를 흥미롭게 보는 이유는 순수 양자컴퓨팅 노출도가 높기 때문이다. 일반적인 소프트웨어 회사처럼 당장 현금흐름이 단단한 구조는 아니지만, 대신 양자컴퓨팅이 상업 단계로 가면 가장 먼저 재평가될 후보라는 상징성이 있다. 이 상징성은 장점이자 리스크다. 기대가 살아 있을 때는 강하지만, 기대를 뒷받침하는 숫자가 늦게 따라오면 낙폭도 커질 수 있다.</p>
<p>사업을 볼 때는 세 가지를 나눠서 봐야 한다. 첫째는 기술 경쟁력과 시스템 안정성, 둘째는 연구기관과 기업 고객이 실제 사용으로 이어지는 속도, 셋째는 그 과정에서 적자를 얼마나 통제할 수 있느냐다. 특히 이런 초기 시장의 회사는 좋은 기술이 있는가보다 그 기술이 반복 매출 구조로 넘어갈 길이 보이는가가 훨씬 중요하다. 아이온큐는 이 부분에서 늘 기대와 검증이 동시에 따라붙는다.</p>

<h2>동그리의 시선</h2>
<p><strong>동그리</strong> 나는 아이온큐를 아직 공격적으로 관찰할 가치가 있다고 본다. 이유는 간단하다. 양자컴퓨팅은 대중적 체감이 늦더라도, 시장은 대개 실제 대중화 직전이 아니라 상업화 가능성이 처음 구체화되는 구간부터 밸류에이션을 다시 매긴다. 아이온큐는 바로 그 기대를 가장 순수하게 받는 종목 중 하나다. 대형 클라우드, 국방·연구 프로젝트, 기업용 실험 수요 같은 키워드가 붙는 순간 서사가 다시 살아난다.</p>
<p><strong>동그리</strong> 또 하나는 시장 구조다. 이런 종목은 실적 숫자 자체보다도 다음 1년 동안 무슨 계약이 붙을 수 있느냐가 주가를 흔드는 경우가 많다. 그래서 단기 트레이딩 관점에서는 완벽한 숫자를 기다리기보다, 시장이 기대를 다시 올려잡는 순간을 놓치지 않는 편이 중요하다. 변동성은 크지만 그만큼 내러티브가 붙는 속도도 빠르다. 성장주가 다시 선택받는 국면에서는 아이온큐 같은 이름이 상단에서 가장 먼저 거론될 가능성이 높다.</p>
<p><strong>동그리</strong> 결국 공격적인 관점의 핵심은 하나다. 아이온큐는 아직 증명보다 기대가 앞서는 종목이지만, 그래서 오히려 리레이팅 구간의 폭이 크게 열릴 수 있다. 이익이 안정적인 회사를 찾는 매매가 아니라, 미래 시장의 입구를 누가 먼저 차지하느냐를 보는 매매라면 이 종목을 그냥 흘려보내기 어렵다.</p>

<h2>햄니의 시선</h2>
<p><strong>햄니</strong> 나는 이 종목을 볼 때마다 결국 같은 질문으로 돌아간다. 기대를 실적으로 얼마만큼, 얼마나 빨리 옮길 수 있는가. 양자컴퓨팅은 분명 매력적인 이야기지만, 시장이 오래 참아주는 분야는 아니다. 연구개발 중심 회사가 상업화 전환까지 가는 동안 가장 자주 무너지는 포인트가 바로 매출 가시성과 비용 통제다. 멀리 보면 산업은 커질 수 있지만, 지금 주가가 그 먼 미래를 너무 앞당겨 반영하고 있지는 않은지 냉정하게 봐야 한다.</p>
<p><strong>햄니</strong> 특히 아이온큐는 뉴스가 좋을 때 밸류에이션 부담이 잘 가려진다. 하지만 기대가 높을수록 작은 실망에도 흔들릴 수 있다. 실제 고객이 얼마나 반복적으로 쓰는지, 파일럿이 얼마나 상용화로 넘어가는지, 경쟁 기술 대비 어떤 우위를 유지하는지 같은 질문은 여전히 남는다. 이 질문들이 숫자로 정리되기 전까지는 멋진 이야기와 지속 가능한 사업을 같은 것으로 보면 안 된다.</p>
<p><strong>햄니</strong> 보수적인 관점에서는 분명한 원칙이 필요하다. 급등 구간을 억지로 따라가지 않고, 계약이나 매출 흐름이 확인될 때 비중을 늘리는 편이 맞다. 아이온큐를 완전히 배제할 필요는 없지만, 변동성 자체를 투자 아이디어로 착각하면 손실 관리가 무너질 수 있다. 이 종목은 확신보다 확인이 먼저다.</p>

<h2>쟁점 토론</h2>
<p><strong>동그리</strong> 그래도 시장은 늘 확인 뒤에 움직이지 않아. 확인이 끝났을 때는 이미 프리미엄이 많이 붙어 있을 수 있어.</p>
<p><strong>햄니</strong> 맞아. 그런데 아이온큐 같은 종목은 프리미엄이 붙은 뒤 조정 폭도 매우 큰 편이야. 그래서 선반영을 먹는 전략과 손실을 버티는 전략을 분리해서 생각해야 해.</p>
<p><strong>동그리</strong> 내 기준에서는 이 회사가 완성형이냐보다, 다음 분기와 다음 계약 뉴스에서 서사가 확장될 여지가 있느냐가 더 중요해. 시장은 미래 독점 후보를 좋아하니까.</p>
<p><strong>햄니</strong> 내 기준에서는 그 서사가 반복 매출 구조와 연결되는지 봐야 해. 상징성만으로 오래 버티는 종목은 생각보다 많지 않아. 특히 고평가 영역에서는 작은 실수 하나가 크다.</p>
<p><strong>동그리</strong> 그래서 결국 전략 차이네. 나는 눌림 때 관심을 유지하고, 재료가 붙는 순간 빠르게 반응하는 쪽이야.</p>
<p><strong>햄니</strong> 나는 확인 전 추격보다, 확인 이후에도 상승 논리가 남는지 본다. 종목이 아니라 과정에 기준을 두자는 거지.</p>

<h2>체크포인트</h2>
<p>아이온큐를 볼 때는 막연히 양자컴퓨팅이라서 좋다에서 멈추면 안 된다. 아래 표처럼 무엇이 주가를 다시 열고, 무엇이 기대를 꺾는지 분리해서 보는 편이 훨씬 낫다.</p>
<div class="table-wrap">
<table class="comparison-table">
<thead>
<tr><th>항목</th><th>동그리 체크</th><th>햄니 체크</th></tr>
</thead>
<tbody>
<tr><td>상승 재료</td><td>대형 계약, 클라우드 협업, 장기 성장주 심리 회복</td><td>반복 매출 증가가 실제로 확인되는지</td></tr>
<tr><td>경계 포인트</td><td>단기 과열 뒤 급락, 기대만 앞선 프리미엄</td><td>매출 가시성 부족, 비용 통제 실패, 일정 지연</td></tr>
<tr><td>숫자 확인</td><td>수주 뉴스와 시장 반응 강도</td><td>매출 인식 속도, 고객 다변화, 손익 구조</td></tr>
<tr><td>대응 방식</td><td>눌림 구간 분할 관찰, 재료 반응 확인</td><td>확인 후 비중 확대, 추격 매수 자제</td></tr>
</tbody>
</table>
</div>

<h2>마무리 기록</h2>
<p>아이온큐는 오늘 당장 결론을 내리기 쉬운 종목이 아니다. 다만 양자컴퓨팅이라는 긴 서사를 믿는 사람에게는 가장 먼저 화면에 올려둘 이름이고, 숫자 확인을 중시하는 사람에게는 끝까지 검증이 필요한 이름이기도 하다. 동그리의 기준으로 보면 아직 기회가 살아 있는 공격형 성장주이고, 햄니의 기준으로 보면 기대와 실적 사이 간격을 반드시 체크해야 하는 고변동 종목이다. 결국 이 종목의 핵심은 미래를 먼저 살 것인가, 확인을 기다릴 것인가라는 질문에 어떻게 답하느냐다.</p>
</section>
""".strip()

IONQ_METADATA = {
    "series_variant": "us-stock-dialogue-v1",
    "company_name": "IonQ",
    "ticker": "IONQ",
    "exchange": "NYSE",
    "chart_provider": "tradingview",
    "chart_symbol": "NYSE:IONQ",
    "chart_interval": "1D",
    "viewpoints": ["동그리", "햄니"],
    "slide_sections": [
        {
            "title": "오늘 왜 IONQ인가",
            "summary": "양자컴퓨팅 기대와 실적 가시성의 간극을 함께 보는 날이다.",
            "speaker": "동그리",
            "key_points": ["양자컴퓨팅", "성장 기대", "재평가 가능성"],
        },
        {
            "title": "기업 개요",
            "summary": "IonQ는 trapped-ion 방식의 양자컴퓨팅 기업으로 상업화 단계의 검증이 핵심이다.",
            "speaker": "햄니",
            "key_points": ["비즈니스 모델", "상업화", "반복 매출"],
        },
        {
            "title": "동그리의 시선",
            "summary": "성장주 프리미엄이 다시 붙을 때 가장 탄력이 큰 이름으로 본다.",
            "speaker": "동그리",
            "key_points": ["내러티브", "계약 기대", "리레이팅"],
        },
        {
            "title": "햄니의 시선",
            "summary": "매출 확인과 비용 통제가 동반되지 않으면 프리미엄이 오래가기 어렵다.",
            "speaker": "햄니",
            "key_points": ["확인 우선", "밸류에이션", "리스크"],
        },
        {
            "title": "쟁점 토론",
            "summary": "기대를 먼저 살지, 숫자를 확인하고 갈지 두 관점이 갈린다.",
            "speaker": "동그리",
            "key_points": ["선반영", "확인 후 대응", "전략 차이"],
        },
        {
            "title": "체크포인트",
            "summary": "계약, 매출 인식, 고객 다변화, 손익 구조를 함께 봐야 한다.",
            "speaker": "햄니",
            "key_points": ["수주", "매출", "비용"],
        },
        {
            "title": "마무리 기록",
            "summary": "미래를 먼저 살 것인지, 확인을 기다릴 것인지가 아이온큐 해석의 핵심이다.",
            "speaker": "햄니",
            "key_points": ["성장주", "검증", "관찰 메모"],
        },
    ],
}

SANDISK_TITLE = "샌디스크 흐름 점검 2026-04-12 | 동그리 vs 햄니, SNDK를 지금 어디서 봐야 하나"
SANDISK_BODY = """
<section class="chat-thread">
<h2>오늘 왜 이 종목인가</h2>
<p>샌디스크를 볼 때는 화려한 서사보다 사이클을 읽는 눈이 먼저 필요하다. 이 종목의 핵심은 낸드와 플래시 메모리 업황이 어느 국면에 들어와 있는지, 그리고 가격 회복이 실제 수익성으로 얼마나 이어질 수 있는지다. 그래서 샌디스크는 단기 뉴스 하나로 보기보다 메모리 가격, 재고, 기업용 수요, 소비자 저장장치 수요가 어떤 방향으로 겹치고 있는지를 같이 봐야 한다.</p>
<p>시장이 이 회사를 다시 보는 이유는 단순하다. 메모리 업황이 바닥에서 돌아설 때 관련 종목은 숫자보다 기대가 먼저 움직이기 때문이다. 반대로 회복이 생각보다 느리면 주가는 다시 사이클에 눌린다. 샌디스크는 회복이 시작됐는가를 묻는 종목이지, 이미 편안하게 성장하는 회사를 사는 느낌으로 접근할 이름은 아니다.</p>

<h2>기업 개요</h2>
<p>샌디스크는 낸드 플래시와 저장장치 시장에서 익숙한 브랜드이지만, 투자 포인트는 브랜드 인지도보다 업황 민감도에 있다. 소비자용 저장장치, 기업용 스토리지, 모바일과 PC 관련 수요, 메모리 가격 협상력이 모두 얽혀 있다. 결국 이 회사는 좋은 제품을 만드는지만으로 설명되지 않고, 메모리 산업의 공급과 수요 균형 안에서 읽어야 한다.</p>
<p>그래서 샌디스크를 볼 때는 회복 서사의 질을 따져야 한다. 단순히 가격이 반등하는 구간인지, 아니면 제품 믹스와 고객 구조가 좋아지면서 마진 체질까지 개선될 수 있는지, 그리고 그 과정에서 투자자들이 얼마나 오래 기다려줄지가 중요하다. 이런 종목은 좋아질 때는 생각보다 빠르게 좋아 보이고, 흔들릴 때는 숫자보다 심리가 먼저 무너진다.</p>

<h2>동그리의 시선</h2>
<p><strong>동그리</strong> 나는 샌디스크를 공격적으로 보는 쪽이다. 메모리 업종은 늘 완전히 편안해진 다음에는 기대수익이 줄어든다. 오히려 아직 논쟁이 남아 있고, 업황 바닥 통과 논리가 조금씩 강해지는 구간이 가장 재미있다. 샌디스크는 바로 그 경계선에 서 있는 종목처럼 보인다. 업황이 한 단계만 더 개선돼도 시장은 이 회사를 턴어라운드 후보로 다시 보기 시작할 가능성이 크다.</p>
<p><strong>동그리</strong> 특히 이런 종목은 숫자가 완벽하게 좋아진 뒤보다, 수급과 가격 지표가 먼저 돌아설 때 주가가 민감하게 움직인다. 메모리 가격, 재고 정상화, 기업용 수요 회복 같은 키워드가 함께 잡히면 생각보다 빠르게 리레이팅이 나온다. 샌디스크는 시장이 눈높이를 다시 올릴 여지가 있는 이름이다. 완성형 안정주가 아니라, 사이클 회복의 초입을 사는 관점에서 봐야 한다.</p>
<p><strong>동그리</strong> 그래서 공격적 관점의 핵심은 조금 이른가보다 회복의 방향이 맞는가다. 방향이 맞다면 주가는 실적 발표보다 먼저 반응한다. 메모리 종목은 늘 확인 전에 움직인다는 점을 잊지 않는 편이 좋다.</p>

<h2>햄니의 시선</h2>
<p><strong>햄니</strong> 나는 여기서 가장 중요한 것이 낸드 가격 반등 자체가 아니라, 그 반등이 얼마나 오래 지속될 수 있느냐라고 본다. 메모리 업황은 늘 좋아질 것처럼 보이다가도 공급이 다시 늘거나 수요가 약해지면 곧바로 흔들린다. 샌디스크 같은 종목은 특히 업황 회복 서사가 강할 때 기대가 앞서기 쉬운데, 그만큼 실망도 빠르게 반영된다.</p>
<p><strong>햄니</strong> 또 하나는 체력이다. 회복기 종목은 업황이 좋아진다는 말만으로 끝나지 않고, 실제로 제품 믹스가 개선되는지, 재고 부담이 줄어드는지, 고객 구조가 안정적인지까지 확인해야 한다. 낸드 가격이 반등해도 수익성 회복 속도가 느리면 시장은 금방 인내심을 잃는다. 이 종목을 너무 단순하게 메모리 반등 수혜주로만 보면 위험하다.</p>
<p><strong>햄니</strong> 보수적인 접근은 명확하다. 사이클 회복이 데이터로 확인될 때 비중을 늘리고, 단기 반등만 보고 추격하지 않는 것이다. 업황주는 빠르게 오르지만, 확인 없는 낙관은 빠르게 무너진다. 샌디스크는 좋아질 수 있지만, 무조건 빨라야 하는 종목은 아니다.</p>

<h2>쟁점 토론</h2>
<p><strong>동그리</strong> 결국 메모리 종목은 남들이 확신하기 전에 조금 빨리 보는 사람이 수익을 크게 가져가. 완벽한 데이터가 다 나오면 늦을 수 있어.</p>
<p><strong>햄니</strong> 동의해. 다만 메모리 업황은 기대가 과열되기 쉬워서, 회복 중과 회복 착시를 구분해야 해. 가격 반등만 보고 마진 구조까지 좋아질 거라고 단정하면 위험해.</p>
<p><strong>동그리</strong> 나는 샌디스크가 바로 그런 논쟁 속에서 기회가 생기는 종목이라고 봐. 방향이 좋아지면 시장은 생각보다 빨리 밸류를 다시 붙여.</p>
<p><strong>햄니</strong> 나는 그 방향이 숫자로 이어지는지를 먼저 본다. ASP, 재고, 고객 믹스, 기업용 수요가 같이 확인되면 그때 들어가도 늦지 않다고 생각해.</p>
<p><strong>동그리</strong> 결국 공격적 관점은 사이클의 앞부분을 사는 거고, 보수적 관점은 사이클의 지속성을 확인하는 거네.</p>
<p><strong>햄니</strong> 맞아. 그래서 이 종목은 성격상 둘 다 맞을 수 있지만, 자기 기준 없이 따라가면 흔들리기 쉽다.</p>

<h2>체크포인트</h2>
<p>샌디스크는 단순히 저장장치 브랜드라는 인상보다, 메모리 업황주로 읽어야 더 명확하다. 아래처럼 상승 논리와 경계 논리를 따로 적어 두면 판단이 한결 쉬워진다.</p>
<div class="table-wrap">
<table class="comparison-table">
<thead>
<tr><th>항목</th><th>동그리 체크</th><th>햄니 체크</th></tr>
</thead>
<tbody>
<tr><td>상승 재료</td><td>낸드 가격 반등 지속, 재고 정상화, 기업용 수요 회복</td><td>마진 개선이 실제 실적에 반영되는지</td></tr>
<tr><td>경계 포인트</td><td>업황 기대 과열, 단기 반등 후 되밀림</td><td>공급 증가, 수요 부진, 회복 속도 둔화</td></tr>
<tr><td>숫자 확인</td><td>가격 지표와 수급 반응</td><td>ASP, 재고 수준, 제품 믹스, 손익 체력</td></tr>
<tr><td>대응 방식</td><td>회복 초입 분할 관찰</td><td>실적 확인 후 비중 확대, 추격 자제</td></tr>
</tbody>
</table>
</div>

<h2>마무리 기록</h2>
<p>샌디스크는 오늘 당장 정답을 주는 종목이라기보다, 메모리 업황이 어느 방향으로 기울고 있는지 읽게 만드는 종목에 가깝다. 동그리의 관점에서는 아직 논쟁이 남아 있을 때 선제적으로 볼 이유가 있는 턴어라운드 후보이고, 햄니의 관점에서는 업황 회복이 실제 수익성으로 연결되는지 끝까지 확인해야 하는 보수형 종목이다. 결국 이 종목을 대하는 태도는 메모리 사이클을 얼마나 앞서서 믿을 것인지, 아니면 확인 뒤에 따라갈 것인지에 달려 있다.</p>
</section>
""".strip()

SANDISK_METADATA = {
    "series_variant": "us-stock-dialogue-v1",
    "company_name": "SanDisk",
    "ticker": "SNDK",
    "exchange": "NASDAQ",
    "chart_provider": "tradingview",
    "chart_symbol": "NASDAQ:SNDK",
    "chart_interval": "1D",
    "viewpoints": ["동그리", "햄니"],
    "slide_sections": [
        {
            "title": "오늘 왜 SNDK인가",
            "summary": "샌디스크는 메모리 업황 회복을 읽는 대표적인 사이클 종목이다.",
            "speaker": "동그리",
            "key_points": ["낸드", "업황", "턴어라운드"],
        },
        {
            "title": "기업 개요",
            "summary": "브랜드보다 낸드 가격, 재고, 수요 회복이 투자 포인트를 좌우한다.",
            "speaker": "햄니",
            "key_points": ["저장장치", "가격", "수익성"],
        },
        {
            "title": "동그리의 시선",
            "summary": "업황 바닥 통과 기대가 붙을 때 리레이팅 폭이 클 수 있다고 본다.",
            "speaker": "동그리",
            "key_points": ["초입 관찰", "리레이팅", "공격적 접근"],
        },
        {
            "title": "햄니의 시선",
            "summary": "ASP와 마진이 실제로 회복되는지 확인되기 전까지는 추격을 경계한다.",
            "speaker": "햄니",
            "key_points": ["확인 우선", "공급 리스크", "보수 대응"],
        },
        {
            "title": "쟁점 토론",
            "summary": "사이클을 앞서 살지, 지속성을 확인하고 들어갈지 관점이 갈린다.",
            "speaker": "동그리",
            "key_points": ["선반영", "확인 후 대응", "전략 차이"],
        },
        {
            "title": "체크포인트",
            "summary": "낸드 가격, 재고, 기업용 수요, 마진 구조를 함께 봐야 한다.",
            "speaker": "햄니",
            "key_points": ["ASP", "재고", "마진"],
        },
        {
            "title": "마무리 기록",
            "summary": "샌디스크는 메모리 사이클을 얼마나 앞서 믿을지 시험하는 종목이다.",
            "speaker": "햄니",
            "key_points": ["사이클", "턴어라운드", "관찰 메모"],
        },
    ],
}

POSTS = [
    {
        "remote_id": "2d3084d6-d92a-4173-8887-bf4a9a6d8ddd",
        "title": IONQ_TITLE,
        "excerpt": "아이온큐를 지금 다시 봐야 하는 이유를 동그리와 햄니의 대화로 정리했다. 양자컴퓨팅 기대, 상업화 속도, 밸류에이션 부담, 다음 체크포인트를 한 화면에서 읽을 수 있게 묶었다.",
        "seo_description": "아이온큐 IONQ를 지금 다시 봐야 하는 이유를 동그리와 햄니의 대화 형식으로 정리했다. 양자컴퓨팅 기대, 상업화 속도, 밸류에이션 부담, 다음 체크포인트까지 한 번에 읽을 수 있다.",
        "body": IONQ_BODY,
        "cover_alt": "아이온큐 IONQ의 양자컴퓨팅 성장 기대와 리스크를 동그리와 햄니의 두 관점으로 정리한 분석 글",
        "category_id": "cat-market-nasdaq",
        "tag_names": ["나스닥의 흐름", "아이온큐", "IONQ", "양자컴퓨팅", "미국주식", "성장주"],
        "metadata": IONQ_METADATA,
    },
    {
        "remote_id": "2206556b-e286-4ebe-9cbc-0fb630b9ce94",
        "title": SANDISK_TITLE,
        "excerpt": "샌디스크를 다시 볼 때 필요한 질문을 동그리와 햄니의 대화로 정리했다. 낸드 업황, 가격 사이클, 수익성 회복 속도, 보수적 대응 기준까지 한 번에 읽을 수 있게 구성했다.",
        "seo_description": "샌디스크 SNDK를 지금 어디서 봐야 할지 동그리와 햄니의 대화 형식으로 정리했다. 낸드 업황, 가격 사이클, 수익성 회복, 리스크와 체크포인트까지 한 화면에서 읽을 수 있다.",
        "body": SANDISK_BODY,
        "cover_alt": "샌디스크 SNDK의 낸드 업황과 회복 시나리오를 동그리와 햄니의 두 관점으로 정리한 분석 글",
        "category_id": "cat-market-nasdaq",
        "tag_names": ["나스닥의 흐름", "샌디스크", "SNDK", "낸드", "미국주식", "메모리"],
        "metadata": SANDISK_METADATA,
    },
]


def main() -> None:
    with SessionLocal() as db:
        updated_rows: list[dict[str, object]] = []
        for post in POSTS:
            detail = _fetch_integration_post_detail(db, remote_post_id=post["remote_id"])
            payload = {
                "title": post["title"],
                "content": _prepare_markdown_body(post["title"], post["body"]),
                "excerpt": post["excerpt"],
                "seoTitle": post["title"],
                "seoDescription": post["seo_description"],
                "tagNames": post["tag_names"],
                "categoryId": post["category_id"],
                "status": "published",
                "metadata": post["metadata"],
                "renderMetadata": post["metadata"],
                "coverImage": detail.get("coverImage"),
                "coverAlt": post["cover_alt"],
            }
            response = _integration_request(
                db,
                method="PUT",
                path=f"/api/integrations/posts/{post['remote_id']}",
                json_payload=payload,
                timeout=120.0,
            )
            updated = _integration_data_or_raise(response)
            updated_rows.append(
                {
                    "remote_id": post["remote_id"],
                    "title": updated.get("title"),
                    "public_url": updated.get("publicUrl"),
                    "category": updated.get("category"),
                    "metadata": updated.get("metadata"),
                    "renderMetadata": updated.get("renderMetadata"),
                }
            )

        sync_result = sync_cloudflare_posts(db, include_non_published=True)
        refreshed = [
            {
                "remote_id": row.get("remote_id"),
                "title": row.get("title"),
                "category_slug": row.get("category_slug"),
                "canonical_category_slug": row.get("canonical_category_slug"),
                "seo_score": row.get("seo_score"),
                "geo_score": row.get("geo_score"),
                "ctr": row.get("ctr"),
                "lighthouse_score": row.get("lighthouse_score"),
                "render_metadata": row.get("render_metadata"),
            }
            for row in list_synced_cloudflare_posts(db, include_non_published=True)
            if str(row.get("remote_id") or "").strip() in {post["remote_id"] for post in POSTS}
        ]

    print(
        json.dumps(
            {
                "updated_rows": updated_rows,
                "sync_result": sync_result,
                "refreshed": refreshed,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
