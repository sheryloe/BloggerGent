from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from textwrap import dedent


REPO = Path(r"D:\Donggri_Platform\BloggerGent")
PROMPT_ROOT = REPO / "prompts" / "channels" / "cloudflare" / "dongri-archive"
PATTERN_SERVICE = REPO / "apps" / "api" / "app" / "services" / "content" / "article_pattern_service.py"
ROOL_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\Rool\30-cloudflare")
CATEGORY_ROOT = ROOL_ROOT / "categories"


@dataclass(frozen=True)
class Pattern:
    id: str
    label: str
    summary: str
    structure: str
    image: str
    faq: str = "optional"
    html_hint: str = "section.callout, div.fact-box, table.comparison-table"


@dataclass(frozen=True)
class Category:
    slug: str
    label: str
    group: str
    folder: str
    focus: str
    tone: str
    body: str
    image_policy: str
    patterns: tuple[Pattern, ...]
    faq_policy: str = "optional"
    min_chars: int = 4000


CATEGORIES: tuple[Category, ...] = (
    Category(
        "개발과-프로그래밍",
        "개발과 프로그래밍",
        "동그리의 기록",
        "gaebalgwa-peurogeuraeming",
        "개발 도구, AI 에이전트, 자동화, 배포, 관측성, 비용 통제, 실무 워크플로를 다룬다.",
        "실무 메모 + 개발자 해설. 과장된 생산성 찬양이나 입문 튜토리얼은 금지한다.",
        "Markdown only. 첫 제목은 ##. ## 핵심 요약 포함. 마지막은 ## 마무리 기록.",
        "기술 문서, 개발 도구, 워크플로, 아키텍처 보드, 운영 대시보드 중심의 3x3 hero collage.",
        (
            Pattern("dev-info-deep-dive", "Dev Info Deep Dive", "기술의 역사, 공식 문서 기반 정보, 전체 컨텍스트를 다루는 포괄적 가이드.", "## 핵심 요약 -> ## 배경과 변화 -> ## 공식 문서로 보는 핵심 -> ## 실무 적용 기준 -> ## 마무리 기록", "공식 문서, 코드 에디터, 아키텍처 보드, 릴리스 노트가 함께 놓인 개발자 데스크.", "none"),
            Pattern("dev-curation-top-points", "Dev Curation Top Points", "핵심 하이라이트 5가지를 선정해 실무 영향 중심으로 분석한다.", "## 핵심 요약 -> ## 지금 볼 5가지 포인트 -> ## 팀 워크플로 영향 -> ## 적용 우선순위 -> ## 마무리 기록", "5개 기술 포인트 카드, 체크리스트, 워크플로 보드가 보이는 편집형 기술 콜라주.", "none"),
            Pattern("dev-insider-field-guide", "Dev Insider Field Guide", "최적 설정, 타이밍, 트러블슈팅, 운영 팁을 담은 실전 마스터 가이드.", "## 핵심 요약 -> ## 실제 설정 기준 -> ## 자주 막히는 지점 -> ## 트러블슈팅 순서 -> ## 마무리 기록", "터미널, 설정 파일, 로그 패널, 문제 해결 체크포인트가 보이는 실전 개발 장면.", "none"),
            Pattern("dev-expert-perspective", "Dev Expert Perspective", "개발자 관점에서 기술적, 사회적 영향과 아키텍처 선택을 비평한다.", "## 핵심 요약 -> ## 기술적 의미 -> ## 아키텍처 관점 -> ## 팀 운영 관점 -> ## 마무리 기록", "시스템 다이어그램, 팀 리뷰 보드, 코드 구조와 의사결정 메모가 결합된 장면.", "none"),
            Pattern("dev-experience-synthesis", "Dev Experience Synthesis", "실제 삽질 경험과 감정적 서사가 결합된 기술 리뷰.", "## 핵심 요약 -> ## 직접 부딪힌 장면 -> ## 해결 과정 -> ## 남은 불편과 장점 -> ## 마무리 기록", "밤의 개발 책상, 에러 로그, 수정된 코드, 개인 메모가 함께 있는 현실적인 기술 리뷰 장면."),
        ),
    ),
    Category(
        "일상과-메모", "일상과 메모", "동그리의 기록", "ilsanggwa-memo",
        "일상 장면을 기록하되 감상 나열로 끝내지 않고 생각과 실천으로 이어지는 메모형 글.",
        "조용한 관찰, 과장 없는 문장, 구체적인 생활 장면.",
        "HTML body는 h2/h3/p 중심. FAQ 기본 금지. 마지막은 <h2>마무리 기록</h2>.",
        "노트, 책상, 산책, 루틴, 창가, 감정 회고가 드러나는 조용한 3x3 hero collage.",
        (
            Pattern("daily-01-reflective-monologue", "Reflective Monologue", "사유형 독백. 장면에서 질문으로 이어진다.", "## 장면 -> ## 생각 -> ## 남은 질문 -> ## 마무리 기록", "책상 위 노트와 조용한 빛이 있는 일상 사유 장면.", "none"),
            Pattern("daily-02-insight-memo", "Insight Memo", "일상에서 발견한 작은 통찰을 적용 가능한 메모로 정리한다.", "## 장면 -> ## 문제를 다시 보기 -> ## 적용할 수 있는 통찰 -> ## 작은 체크리스트 -> ## 마무리 기록", "생활 도구와 메모 카드가 정돈된 인사이트 장면.", "none"),
            Pattern("daily-03-habit-tracker", "Habit Tracker", "루틴, 습관, 반복 기록을 재현 가능한 순서로 정리한다.", "## 장면 -> ## 루틴의 목적 -> ## 실행 순서 -> ## 작은 체크리스트 -> ## 마무리 기록", "아침 루틴 체크리스트와 캘린더가 보이는 차분한 생활 장면.", "none"),
            Pattern("daily-04-emotional-reflection", "Emotional Reflection", "감정 회고를 구체적 장면과 문장으로 정리한다.", "## 장면 -> ## 감정의 흐름 -> ## 내가 붙잡은 문장 -> ## 실천 -> ## 마무리 기록", "창가, 노트, 부드러운 그림자가 있는 감정 회고 장면.", "none"),
        ),
        faq_policy="none",
        min_chars=3000,
    ),
    Category(
        "여행과-기록", "여행과 기록", "동그리의 기록", "yeohaenggwa-girog",
        "Cloudflare 내부 여행 기록. Blogger Travel 운영과 분리한다. 장소, 동선, 시간, 비용, 현장 판단을 다룬다.",
        "여행 에세이가 아니라 독자가 움직일 수 있는 현장 기록.",
        "동선, 시간대, 비용, 혼잡, 지도 확인 포인트를 포함한다. 마지막은 <h2>마무리 기록</h2>.",
        "국내 장소, 이동 동선, 현장 표지, 지도 노트, 사진 기록이 보이는 3x3 hero collage.",
        (
            Pattern("route-first-story", "Route First Story", "이동 순서와 시간대가 중심인 루트형 기록.", "## 여행 개요 -> ## 이동 순서 -> ## 시간대별 기록 -> ## 현장 체크포인트 -> ## 마무리 기록", "지도, 골목, 교통수단, 도보 동선이 연결된 여행 루트 장면."),
            Pattern("spot-focus-review", "Spot Focus Review", "한 장소를 깊게 보고 방문 가치와 주의점을 정리한다.", "## 장소 개요 -> ## 볼만한 지점 -> ## 머무는 방법 -> ## 주의할 점 -> ## 마무리 기록", "하나의 장소를 중심으로 입구, 내부, 주변 장면이 나뉜 콜라주."),
            Pattern("seasonal-special", "Seasonal Special", "계절, 축제, 날씨, 혼잡이 중요한 방문 기록.", "## 계절 포인트 -> ## 추천 시간 -> ## 현장 분위기 -> ## 준비물 -> ## 마무리 기록", "계절감, 사람 흐름, 날씨와 현장 분위기가 보이는 장면."),
            Pattern("logistics-budget", "Logistics Budget", "교통, 예약, 비용, 동선 효율을 중심으로 정리한다.", "## 이동과 예약 -> ## 비용 정리 -> ## 시간 절약법 -> ## 실패 줄이는 체크리스트 -> ## 마무리 기록", "교통표, 예약 화면, 비용 메모, 지도 체크리스트가 있는 여행 준비 장면."),
            Pattern("hidden-gem-discovery", "Hidden Gem Discovery", "덜 알려진 장소의 발견과 기록 가치를 정리한다.", "## 발견한 이유 -> ## 숨어 있는 포인트 -> ## 가는 법 -> ## 기록할 장면 -> ## 마무리 기록", "조용한 골목, 작은 표지, 로컬 장소, 카메라 노트가 있는 장면."),
        ),
    ),
    Category(
        "삶을-유용하게", "삶을 유용하게", "생활의 기록", "salmeul-yuyonghage",
        "건강 습관, 앱 워크플로, 루틴 개선, 생활 효율을 실제 순서로 정리한다.",
        "실용적이고 경험 기반. 동기부여 문장보다 실행 순서를 우선한다.",
        "문제 -> 실행 순서 -> 비교/체크리스트 -> 적용 팁 -> 마무리 기록.",
        "생활 개선, 루틴, 앱/도구, 체크리스트, 집/책상/모바일 화면 중심의 3x3 hero collage.",
        (
            Pattern("life-hack-tutorial", "Life Hack Tutorial", "생활 문제를 해결하는 단계별 실용 가이드.", "## 문제 상황 -> ## 준비물 -> ## 실행 순서 -> ## 체크리스트 -> ## 마무리 기록", "일상 도구와 단계별 실행 카드가 보이는 생활 개선 장면."),
            Pattern("benefit-audit-report", "Benefit Audit Report", "혜택/서비스의 자격, 가치, 신청 흐름을 점검한다.", "## 혜택 개요 -> ## 대상과 조건 -> ## 실제 가치 -> ## 신청 체크 -> ## 마무리 기록", "혜택 안내 문서, 체크리스트, 상담 장면 중심."),
            Pattern("efficiency-tool-review", "Efficiency Tool Review", "생산성/생활 품질을 높이는 도구나 습관 리뷰.", "## 도구 개요 -> ## 써볼 만한 이유 -> ## 장점과 한계 -> ## 추천 대상 -> ## 마무리 기록", "앱 화면, 루틴 노트, 생활 도구가 정리된 장면."),
            Pattern("comparison-verdict", "Comparison Verdict", "여러 선택지를 비교해 독자에게 맞는 결론을 준다.", "## 선택지 요약 -> ## 비교 기준 -> ## 상황별 추천 -> ## 최종 선택 -> ## 마무리 기록", "비교표, 선택 카드, 생활 상황별 도구가 보이는 콜라주."),
        ),
    ),
    Category(
        "삶의-기름칠", "삶의 기름칠", "생활의 기록", "salmyi-gireumcil",
        "정책, 지원금, 자격 조건, 신청 방법, 돈을 아끼는 제도를 이해하기 쉽게 정리한다.",
        "딱딱한 고지문이 아니라 누가, 언제, 무엇을 확인해야 하는지 먼저 말한다.",
        "대상 -> 조건 -> 신청 흐름 -> 놓치기 쉬운 지점 -> 마무리 기록.",
        "문서, 신청 화면, 상담, 자격 조건, 공공지원 안내가 보이는 신뢰감 있는 3x3 hero collage.",
        (
            Pattern("life-hack-tutorial", "Life Hack Tutorial", "생활비 절감이나 신청 절차를 단계별로 안내한다.", "## 대상 확인 -> ## 신청 전 준비 -> ## 신청 순서 -> ## 확인할 것 -> ## 마무리 기록", "신청 절차와 문서 준비가 보이는 실용 장면."),
            Pattern("benefit-audit-report", "Benefit Audit Report", "지원 제도의 자격, 금액, 실제 가치를 따진다.", "## 제도 개요 -> ## 자격 조건 -> ## 받을 수 있는 혜택 -> ## 주의점 -> ## 마무리 기록", "공공지원 안내문, 계산기, 조건표가 보이는 장면."),
            Pattern("efficiency-tool-review", "Efficiency Tool Review", "신청/관리 도구, 앱, 조회 서비스를 리뷰한다.", "## 도구 개요 -> ## 쓸모 있는 기능 -> ## 한계 -> ## 추천 대상 -> ## 마무리 기록", "모바일 신청 화면, 체크리스트, 상담 데스크 장면."),
            Pattern("comparison-verdict", "Comparison Verdict", "비슷한 제도나 선택지를 비교해 결론을 준다.", "## 선택지 요약 -> ## 비교 기준 -> ## 상황별 결론 -> ## 신청 전략 -> ## 마무리 기록", "여러 제도 카드와 비교표가 놓인 공공정보 장면."),
        ),
    ),
    Category(
        "동그리의-생각", "동그리의 생각", "세상의 기록", "donggeuriyi-saenggag",
        "사회 사건, 문화, 기술 트렌드, 관계와 감정을 동그리의 관점으로 해석한다.",
        "다크 라이브러리 톤. 단정 대신 맥락과 질문을 남긴다.",
        "문제 제기 -> 맥락 -> 놓치기 쉬운 것 -> 질문/실천 -> 마무리 기록.",
        "다크 라이브러리, 생각 노트, 사회 장면, 창가, 책상, 기록물 중심의 3x3 hero collage.",
        (
            Pattern("thought-social-context", "Social Context", "사회적 사건과 분위기를 맥락으로 해석한다.", "## 문제를 다시 바라보기 -> ## 맥락과 변화 -> ## 우리가 놓치기 쉬운 것 -> ## 남은 질문 -> ## 마무리 기록", "도시 군중, 신문, 노트, 밤의 책상이 결합된 사유 장면.", "none"),
            Pattern("thought-tech-culture", "Tech Culture", "기술 변화가 사람과 문화에 미치는 영향을 읽는다.", "## 기술이 만든 장면 -> ## 문화적 변화 -> ## 불편과 가능성 -> ## 마무리 기록", "스마트폰, 온라인 연결, 책상 위 메모가 있는 기술 문화 장면.", "none"),
            Pattern("thought-generation-note", "Generation Note", "세대, 관계, 감정의 변화를 기록한다.", "## 익숙한 장면 -> ## 세대의 감각 -> ## 달라진 관계 -> ## 마무리 기록", "서로 다른 세대의 물건, 메시지, 노트가 함께 놓인 장면.", "none"),
            Pattern("thought-personal-question", "Personal Question", "개인적 질문으로 사회적 주제를 다시 본다.", "## 내가 붙잡은 질문 -> ## 장면과 배경 -> ## 생각의 방향 -> ## 마무리 기록", "창가, 노트, 어두운 서재, 질문 카드가 있는 장면.", "none"),
        ),
        faq_policy="none",
        min_chars=3000,
    ),
    Category(
        "미스테리아-스토리", "미스테리아 스토리", "세상의 기록", "miseuteria-seutori",
        "미해결 사건, 도시 괴담, 실종 사건, 기록 기반 미스터리를 사건 파일처럼 정리한다.",
        "다크 아카이브. 자극적 단정 금지, 기록과 해석의 경계를 분리한다.",
        "H1 금지. 사건 개요 -> 인물/증거 -> 연대기 -> 가설 -> 마무리 기록. FAQ 3개 허용.",
        "다큐멘터리 사건 기록소 톤. hero-only. 3x3 grid collage로 통일한다.",
        (
            Pattern("case-timeline", "Case Timeline", "시간순 사건 재구성.", "## 사건 개요 -> ## 연대기 -> ## 남은 공백 -> ## 마무리 기록", "날짜 기록, 지도, 오래된 문서, 사건 현장 단서가 보이는 다크 아카이브."),
            Pattern("evidence-breakdown", "Evidence Breakdown", "증거와 반론을 나누어 분석한다.", "## 사건 개요 -> ## 증거 목록 -> ## 반론과 한계 -> ## 마무리 기록", "증거 보드, 문서, 사진 조각, 조사 노트가 있는 장면."),
            Pattern("legend-context", "Legend Context", "전설/괴담의 발생과 전파 맥락을 정리한다.", "## 전설의 시작 -> ## 전파 경로 -> ## 현대적 해석 -> ## 마무리 기록", "오래된 지도, 민속 기록, 밤의 거리, 아카이브 카드."),
            Pattern("scene-investigation", "Scene Investigation", "장소와 장면을 중심으로 사건을 추적한다.", "## 현장 묘사 -> ## 동선과 시간 -> ## 이상한 지점 -> ## 마무리 기록", "어두운 현장 지도, 손전등, 기록 노트, 장면 분할."),
            Pattern("scp-dossier", "SCP Dossier", "파일형 이상 현상 기록 구조.", "## 파일 개요 -> ## 관찰 기록 -> ## 위험 신호 -> ## 마무리 기록", "기밀 파일, 격리 구역, 조사 카드, 차가운 조명."),
        ),
        min_chars=3000,
    ),
    Category(
        "주식의-흐름", "주식의 흐름", "시장의 기록", "jusigyi-heureum",
        "글로벌 증시, 섹터, 기업 실적, 투자심리, 정책 변수를 분석한다.",
        "투자 조언이 아니라 시장 관찰과 리스크 정리.",
        "시장 요약 -> 주요 뉴스/지표 -> 섹터 관찰 -> 리스크 -> 다음 일정.",
        "패턴1은 12컷 만화형, 나머지는 금융 리포트형 3x3 hero collage.",
        (
            Pattern("stock-cartoon-summary", "Cartoon Summary", "시장 이슈를 만화식 요약으로 쉽게 풀어낸다.", "## 만화 요약 -> ## 오늘의 시장 흐름 -> ## 주요 이슈 -> ## 마무리 기록", "12-panel sequential manga grid about market participants and chart tension."),
            Pattern("stock-technical-analysis", "Technical Analysis", "가격 흐름과 기술적 구간을 정리한다.", "## 오늘의 시장 흐름 -> ## 기술적 구간 -> ## 확인할 지표 -> ## 마무리 기록", "차트, 지지/저항, 섹터 보드, 리스크 메모가 보이는 금융 장면."),
            Pattern("stock-macro-intelligence", "Macro Intelligence", "금리, 물가, 정책, 지표가 시장에 미치는 영향을 본다.", "## 거시 환경 -> ## 시장 반응 -> ## 투자심리 -> ## 마무리 기록", "금리표, 경제지표, 글로벌 뉴스 보드가 있는 리포트 장면."),
            Pattern("stock-corporate-event-watch", "Corporate Event Watch", "실적, 이벤트, 기업 뉴스 중심 분석.", "## 기업 이벤트 -> ## 실적/뉴스 포인트 -> ## 리스크 -> ## 마무리 기록", "실적표, 기업 뉴스, 섹터 카드가 보이는 시장 분석 장면."),
            Pattern("stock-risk-timing", "Risk Timing", "진입/관망/리스크 타이밍을 정리한다.", "## 현재 위치 -> ## 리스크 신호 -> ## 확인할 일정 -> ## 마무리 기록", "리스크 경고, 일정표, 시장 흐름 보드가 있는 장면."),
        ),
    ),
    Category(
        "크립토의-흐름", "크립토의 흐름", "시장의 기록", "keuribtoyi-heureum",
        "비트코인, 이더리움, 알트코인, 온체인, 규제, 거래소, DeFi 흐름을 분석한다.",
        "하이프 금지. 가격 예측보다 사건, 유동성, 규제, 네트워크 업데이트를 구분한다.",
        "시장 요약 -> 주요 코인/사건 -> 온체인/규제 -> 리스크 -> 다음 지점.",
        "패턴1은 12컷 사이버 만화형, 나머지는 분석형 3x3 hero collage.",
        (
            Pattern("crypto-cartoon-summary", "Cartoon Summary", "크립토 이슈를 만화식 요약으로 쉽게 정리한다.", "## 만화 요약 -> ## 크립토 시장 요약 -> ## 주요 사건 -> ## 마무리 기록", "12-panel cyberpunk manga grid about crypto market tension."),
            Pattern("crypto-on-chain-analysis", "On-chain Analysis", "온체인 데이터와 거래 흐름을 중심으로 분석한다.", "## 시장 요약 -> ## 온체인 신호 -> ## 거래소/유동성 -> ## 마무리 기록", "온체인 대시보드, 지갑 흐름, 거래소 데이터가 보이는 장면."),
            Pattern("crypto-protocol-deep-dive", "Protocol Deep Dive", "프로토콜 구조, 업그레이드, 생태계 변화를 설명한다.", "## 프로토콜 개요 -> ## 업데이트/구조 -> ## 생태계 영향 -> ## 마무리 기록", "블록체인 노드, 프로토콜 다이어그램, 개발자 문서 장면."),
            Pattern("crypto-regulatory-macro", "Regulatory Macro", "규제와 거시 환경이 크립토에 미치는 영향을 분석한다.", "## 규제/거시 환경 -> ## 시장 반응 -> ## 리스크 -> ## 마무리 기록", "규제 문서, 글로벌 지도, 크립토 차트가 결합된 장면."),
            Pattern("crypto-market-sentiment", "Market Sentiment", "심리, 뉴스, 유동성, 리스크 시나리오를 점검한다.", "## 시장 심리 -> ## 주요 뉴스 -> ## 리스크 시나리오 -> ## 마무리 기록", "심리 지표, 뉴스 보드, 가격 차트가 있는 분석 장면."),
        ),
    ),
    Category(
        "나스닥의-흐름", "나스닥의 흐름", "시장의 기록", "naseudagyi-heureum",
        "나스닥 상장 기업, AI, 반도체, 클라우드, 플랫폼 기업, 실적, 밸류에이션을 분석한다.",
        "개별 기업과 섹터를 실적/사업/리스크로 나누어 본다.",
        "기업/섹터 개요 -> 최근 흐름 -> 핵심 관찰 포인트 -> 리스크 -> 다음 체크리스트.",
        "기업/AI/반도체/실적/리스크 보드 중심의 3x3 hero collage. 필요 시 만화형 패턴만 별도.",
        (
            Pattern("nasdaq-cartoon-summary", "Cartoon Summary", "나스닥 기업 이슈를 만화식 요약으로 정리한다.", "## 만화 요약 -> ## 기업/섹터 개요 -> ## 최근 흐름 -> ## 마무리 기록", "12-panel manga grid about tech investors, earnings and AI market tension."),
            Pattern("nasdaq-technical-deep-dive", "Technical Deep Dive", "가격 흐름과 기술적 구간을 정밀하게 본다.", "## 기업/섹터 개요 -> ## 기술적 흐름 -> ## 확인할 구간 -> ## 마무리 기록", "나스닥 차트, 지지/저항, 기술 지표가 있는 장면."),
            Pattern("nasdaq-macro-impact", "Macro Impact", "금리, 달러, 실적 시즌, AI 투자 사이클 영향을 분석한다.", "## 거시 환경 -> ## 기업 영향 -> ## 밸류에이션 변수 -> ## 마무리 기록", "금리표, AI 서버, 기업 실적 보드가 결합된 장면."),
            Pattern("nasdaq-big-tech-whale-watch", "Big Tech Whale Watch", "빅테크와 대형 자금 흐름을 추적한다.", "## 대형주 흐름 -> ## 자금과 뉴스 -> ## 리스크 -> ## 마무리 기록", "빅테크 로고 없는 기업 카드, 자금 흐름, 실적표 장면."),
            Pattern("nasdaq-hypothesis-scenario", "Hypothesis Scenario", "상승/하락/횡보 시나리오를 나누어 본다.", "## 현재 위치 -> ## 시나리오별 조건 -> ## 확인할 변수 -> ## 마무리 기록", "시나리오 보드, 체크리스트, 시장 지표가 있는 장면."),
        ),
    ),
    Category(
        "축제와-현장", "축제와 현장", "정보의 기록", "cugjewa-hyeonjang",
        "실제 축제, 지역 행사, 계절 이벤트, 현장 동선과 준비를 다룬다.",
        "브로셔가 아니라 현장 가이드. 시간, 대기, 교통, 먹거리, 주의점 중심.",
        "행사 개요 -> 볼거리 -> 동선/시간 -> 현장 팁 -> 마무리 기록.",
        "현장 운영, 동선, 대기줄, 부스, 교통, 방문 팁이 보이는 3x3 hero collage.",
        (
            Pattern("info-deep-dive", "Info Deep Dive", "행사 배경, 공식 정보, 전체 맥락을 포괄적으로 정리한다.", "## 행사 개요 -> ## 배경과 공식 정보 -> ## 현장 구성 -> ## 마무리 기록", "행사 안내판, 공식 정보, 현장 구성도가 보이는 장면."),
            Pattern("curation-top-points", "Curation Top Points", "방문자가 놓치지 말아야 할 핵심 5가지를 고른다.", "## 핵심 요약 -> ## 놓치면 아쉬운 5가지 -> ## 동선 팁 -> ## 마무리 기록", "5개 현장 포인트 카드와 방문자 동선이 보이는 장면."),
            Pattern("insider-field-guide", "Insider Field Guide", "최적 시간, 자리, 대기 회피, 준비물을 알려준다.", "## 현장 기본 정보 -> ## 최적 시간과 위치 -> ## 대기 줄이는 법 -> ## 마무리 기록", "대기줄, 부스, 교통 표지, 준비물 카드가 있는 장면."),
            Pattern("expert-perspective", "Expert Perspective", "행사의 문화적/지역적 의미를 분석한다.", "## 행사의 맥락 -> ## 문화적 의미 -> ## 현장에서 볼 지점 -> ## 마무리 기록", "축제 장면과 지역 문화 요소가 기록물처럼 배치된 장면."),
            Pattern("experience-synthesis", "Experience Synthesis", "방문 경험과 실용 평가를 함께 정리한다.", "## 현장에 도착하며 -> ## 좋았던 점과 불편한 점 -> ## 다시 간다면 -> ## 마무리 기록", "방문자 시선의 현장 사진, 메모, 평점 카드가 있는 장면."),
        ),
    ),
    Category(
        "문화와-공간", "문화와 공간", "정보의 기록", "munhwawa-gonggan",
        "전시, 미술관, 갤러리, 팝업, 작가, 문화 공간을 관람 동선과 맥락으로 정리한다.",
        "공간과 작품을 보는 순서, 관람 포인트, 분위기를 설명한다.",
        "공간 개요 -> 관람 흐름 -> 대표 포인트 -> 방문 팁 -> 마무리 기록.",
        "전시실, 갤러리, 작품 관람 흐름, 공간 조명, 관람자 동선 중심의 3x3 hero collage.",
        (
            Pattern("info-deep-dive", "Info Deep Dive", "공간/전시의 배경, 공식 정보, 전체 맥락을 정리한다.", "## 공간 개요 -> ## 배경과 공식 정보 -> ## 관람 맥락 -> ## 마무리 기록", "전시 안내, 공간 지도, 작품 설명 카드가 있는 장면."),
            Pattern("curation-top-points", "Curation Top Points", "관람자가 집중해야 할 핵심 5가지를 고른다.", "## 핵심 요약 -> ## 관람 포인트 5가지 -> ## 놓치기 쉬운 장면 -> ## 마무리 기록", "5개 작품/공간 포인트가 카드처럼 정리된 장면."),
            Pattern("insider-field-guide", "Insider Field Guide", "관람 순서, 시간대, 예약, 포토존, 혼잡 회피를 안내한다.", "## 관람 전 확인 -> ## 추천 동선 -> ## 시간과 예약 팁 -> ## 마무리 기록", "관람 동선 지도, 갤러리 입구, 조용한 전시실 장면."),
            Pattern("expert-perspective", "Expert Perspective", "작품, 공간, 큐레이션을 문화적 관점으로 분석한다.", "## 공간의 첫인상 -> ## 큐레이션의 의미 -> ## 작품을 보는 관점 -> ## 마무리 기록", "작품 앞 관람자, 조명, 큐레이션 노트가 있는 장면."),
            Pattern("experience-synthesis", "Experience Synthesis", "관람 경험과 실용 평가를 함께 정리한다.", "## 들어가며 -> ## 인상 깊은 장면 -> ## 좋았던 점과 아쉬운 점 -> ## 마무리 기록", "전시 티켓, 관람 메모, 갤러리 장면이 결합된 장면."),
        ),
    ),
)

STAGES = (
    ("topic_discovery", "주제 발굴", "topic_discovery.md"),
    ("article_generation", "본문 생성", "article_generation.md"),
    ("html_assembly", "HTML 조립", "html_assembly.md"),
    ("image_prompt_generation", "이미지 프롬프트", "image_prompt_generation.md"),
    ("image_generation", "이미지 생성", "image_generation.md"),
    ("publishing", "발행", "publishing.md"),
    ("related_posts", "관련글", "related_posts.md"),
)


def cat_dir(cat: Category) -> Path:
    return PROMPT_ROOT / cat.group / cat.folder


def rel(cat: Category, filename: str) -> str:
    return f"channels/cloudflare/dongri-archive/{cat.group}/{cat.folder}/{filename}"


def pattern_list(cat: Category) -> str:
    return "\n".join(f"{i}. `{p.id}` - {p.label}: {p.summary}" for i, p in enumerate(cat.patterns, 1))


def structure_list(cat: Category) -> str:
    return "\n".join(f"- `{p.id}`: {p.structure}" for p in cat.patterns)


def article_prompt(cat: Category) -> str:
    return dedent(
        f"""
        [Input]
        - Topic: {{keyword}}
        - Current date: {{current_date}}
        - Target audience: {{target_audience}}
        - Blog focus: {{content_brief}}
        - Planner brief:
        {{planner_brief}}
        - Editorial category key: {{editorial_category_key}}
        - Editorial category label: {{editorial_category_label}}
        - Editorial category guidance: {{editorial_category_guidance}}
        - Selected article pattern id: {{article_pattern_id}}

        [Mission]
        - Write one publish-ready Korean article package for Dongri Archive Cloudflare channel.
        - Category: {cat.label} (`{cat.slug}`).
        - Minimum body length: {cat.min_chars}+ Korean characters excluding markup.
        - Use the planner brief, but never expose planner wording, internal archive operations, score reports, or prompt notes.
        - Keep the article useful to a real reader, not a system report.

        [allowed_article_patterns]
        {pattern_list(cat)}

        [pattern_selection_rule]
        - Use only one pattern from `allowed_article_patterns`.
        - If `article_pattern_id` is provided and valid, follow it.
        - If it is missing or invalid, choose the best pattern from the topic and expose the selected id only in the JSON field.
        - Return `article_pattern_version = 4`.

        [category_focus]
        - {cat.focus}
        - Tone: {cat.tone}

        [body_structure]
        - {cat.body}
        {structure_list(cat)}

        [faq_policy]
        - Category default: {cat.faq_policy}.
        - Pattern-level FAQ policy must be respected.
        - Do not add FAQ just to fill space.

        [image_prompt_policy]
        - {cat.image_policy}
        - `image_collage_prompt` must be English.
        - Cloudflare is hero-only: create one representative hero image prompt only.
        - Do not request body images, inline images, multiple generated assets, logos, readable text, or watermarks.

        [forbidden_outputs]
        - No body-level H1.
        - Do not insert `<img>`, markdown images, scripts, iframes, or raw external widgets inside `html_article`.
        - Do not include `meta_description` or `excerpt` visibly inside `html_article`.
        - Do not mention Antigravity, Codex, Gemini, BloggerGent, pipeline, score, audit, or internal planner unless the topic itself is explicitly about those tools.
        - Do not move outside the category topic just because the keyword is broad.

        [Output JSON]
        Return valid JSON only with these fields:
        - title
        - meta_description
        - excerpt
        - labels
        - html_article
        - faq_section
        - image_collage_prompt
        - inline_collage_prompt: return an empty string
        - article_pattern_id
        - article_pattern_version
        """
    ).strip() + "\n"


def image_prompt(cat: Category) -> str:
    directions = "\n".join(f"- `{p.id}`: {p.image}" for p in cat.patterns)
    return dedent(
        f"""
        You are the Cloudflare hero image prompt optimizer for Dongri Archive.

        [Input]
        - Korean title: {{title}}
        - Category: {cat.label} (`{cat.slug}`)
        - Selected article pattern id: {{article_pattern_id}}
        - Article summary: {{excerpt}}

        [Category Image Policy]
        - {cat.image_policy}
        - Generate one final English prompt for a single hero image.
        - Use a composite 3x3 grid collage with exactly 9 panels unless this category pattern explicitly says 12-panel manga.
        - Keep visible panel separation, editorial composition, no text overlays, no logos, no watermark.
        - Cloudflare is hero-only. Do not ask for inline images or body images.

        [Pattern Visual Directions]
        {directions}

        [Output]
        Return one English image prompt only.
        """
    ).strip() + "\n"


def topic_prompt(cat: Category) -> str:
    return dedent(
        f"""
        You are the topic discovery editor for Dongri Archive Cloudflare category `{cat.label}`.

        [Category Scope]
        - {cat.focus}
        - Do not generate duplicate topics already covered by the same category.
        - Do not generate article text, image prompts, images, DB rows, or publish payloads.

        [Allowed Patterns]
        {pattern_list(cat)}

        [Output]
        Return topic candidates with: topic, search_intent, recommended_pattern_id, duplicate_risk, image_cue.
        """
    ).strip() + "\n"


def stage_prompt(cat: Category, stage: str) -> str:
    if stage == "html_assembly":
        body = "Preserve meaning and category structure. No body-level H1, images, scripts, iframes, or external widgets."
    elif stage == "image_generation":
        body = "Generate exactly one hero image from image_collage_prompt. No inline image generation."
    elif stage == "publishing":
        body = "Publish only after title, excerpt, body, category, and hero image URL are verified. Do not create /assets/assets/ URLs."
    elif stage == "related_posts":
        body = "Prefer same category and non-duplicate subject. Do not cross-link to unrelated Blogger channels."
    else:
        body = "Follow the Cloudflare category contract."
    return f"Cloudflare {stage} rule for `{cat.label}`.\n- {body}\n"


def channel_json(cat: Category) -> dict:
    return {
        "channel_id": f"cloudflare:dongriarchive::{cat.slug}",
        "root_channel_id": "cloudflare:dongriarchive",
        "channel_name": f"Dongri Archive | {cat.group} | {cat.label}",
        "provider": "cloudflare",
        "backup_directory": f"channels/cloudflare/dongri-archive/{cat.group}/{cat.folder}",
        "allowed_article_patterns": [p.id for p in cat.patterns],
        "image_layout_policy": "hero_only_3x3_collage",
        "hero_only": True,
        "inline_images": False,
        "backup_files": [rel(cat, filename) for _, _, filename in STAGES],
        "steps": [
            {
                "id": f"{cat.slug}::{stage}",
                "stage_type": stage,
                "stage_label": label,
                "name": f"{cat.label} | {label}",
                "role_name": "Cloudflare Category Agent",
                "objective": f"{cat.label} 카테고리 규칙에 맞게 {label} 단계를 수행합니다.",
                "provider_hint": "image_generation" if stage == "image_generation" else "openai_text",
                "provider_model": None,
                "is_enabled": True,
                "is_required": stage in {"article_generation", "publishing"},
                "prompt_enabled": True,
                "sort_order": idx * 10,
                "backup_relative_path": rel(cat, filename),
            }
            for idx, (stage, label, filename) in enumerate(STAGES, 1)
        ],
    }


def write_rool_docs(cat: Category) -> None:
    d = CATEGORY_ROOT / cat.folder
    d.mkdir(parents=True, exist_ok=True)
    article = [
        f"# {cat.label} article patterns",
        "",
        f"- category_slug: `{cat.slug}`",
        f"- source_folder: `{cat.group}/{cat.folder}`",
        f"- minimum_characters: `{cat.min_chars}`",
        f"- faq_policy: `{cat.faq_policy}`",
        "",
        "## Category Focus",
        cat.focus,
        "",
        "## Tone",
        cat.tone,
        "",
        "## Allowed Patterns",
    ]
    for p in cat.patterns:
        article += ["", f"### {p.id}", f"- label: {p.label}", f"- summary: {p.summary}", f"- structure: {p.structure}", f"- faq: {p.faq}", f"- html_hint: {p.html_hint}"]
    (d / "article-patterns.md").write_text("\n".join(article).strip() + "\n", encoding="utf-8", newline="\n")

    image = [f"# {cat.label} image prompt policy", "", f"- category_slug: `{cat.slug}`", "- hero_only: `true`", "- inline_images: `false`", "", "## Base Policy", cat.image_policy, "", "## Pattern Directions"]
    for p in cat.patterns:
        image += ["", f"### {p.id}", p.image]
    image += ["", "## Forbidden", "- No text overlays.", "- No logos.", "- No body or inline image requests.", "- No unrelated category imagery."]
    (d / "image-prompt-policy.md").write_text("\n".join(image).strip() + "\n", encoding="utf-8", newline="\n")

    checklist = dedent(
        f"""
        # {cat.label} generation checklist

        - [ ] Category slug is `{cat.slug}`.
        - [ ] Selected `article_pattern_id` is one of: {', '.join(p.id for p in cat.patterns)}.
        - [ ] Body stays inside category focus: {cat.focus}
        - [ ] Body has no H1, image tags, scripts, iframes, or internal pipeline notes.
        - [ ] Final section is `마무리 기록`.
        - [ ] Image prompt is hero-only and category-specific.
        - [ ] `inline_collage_prompt` is empty or ignored.
        - [ ] No Travel/Blogger/Mystery Blogger cross-channel assumptions.
        """
    ).strip() + "\n"
    (d / "generation-checklist.md").write_text(checklist, encoding="utf-8", newline="\n")


def patch_pattern_service() -> None:
    text = PATTERN_SERVICE.read_text(encoding="utf-8")
    additions: list[str] = []
    seen: set[str] = set()
    for cat in CATEGORIES:
        for p in cat.patterns:
            if p.id in seen:
                continue
            seen.add(p.id)
            if f'"{p.id}": ArticlePatternDefinition(' in text:
                continue
            additions.append(
                dedent(
                    f'''\
                    "{p.id}": ArticlePatternDefinition(
                        pattern_id="{p.id}",
                        label="{p.label}",
                        summary="{p.summary}",
                        html_hint="{p.html_hint}",
                    ),
                    '''
                )
            )
    if additions:
        marker = "\n}\n\n\n_MYSTERY_ALLOWED_PATTERN_IDS"
        text = text.replace(marker, "\n" + "".join(additions) + "}\n\n\n_MYSTERY_ALLOWED_PATTERN_IDS", 1)

    lines = ["_CLOUDFLARE_PATTERN_MAP: dict[str, tuple[str, ...]] = {"]
    for cat in CATEGORIES:
        ids = ", ".join(f'"{p.id}"' for p in cat.patterns)
        lines.append(f'    "{cat.slug}": ({ids},),')
    lines.append("}")
    start = text.index("_CLOUDFLARE_PATTERN_MAP: dict[str, tuple[str, ...]] = {")
    end = text.index("\n\n_MYSTERIA_PATTERN_WEIGHTS", start)
    text = text[:start] + "\n".join(lines) + text[end:]
    PATTERN_SERVICE.write_text(text, encoding="utf-8", newline="\n")


def write_reports() -> None:
    ROOL_ROOT.mkdir(parents=True, exist_ok=True)
    pattern_rows: list[dict[str, str]] = []
    image_rows: list[dict[str, str]] = []
    for cat in CATEGORIES:
        for p in cat.patterns:
            pattern_rows.append(
                {
                    "category_slug": cat.slug,
                    "category_label": cat.label,
                    "group": cat.group,
                    "folder": cat.folder,
                    "pattern_id": p.id,
                    "pattern_label": p.label,
                    "summary": p.summary,
                    "faq_policy": p.faq,
                    "structure": p.structure,
                }
            )
            image_rows.append(
                {
                    "category_slug": cat.slug,
                    "pattern_id": p.id,
                    "image_direction": p.image,
                    "hero_only": "true",
                    "inline_images": "false",
                }
            )
    for path, rows in (
        (ROOL_ROOT / "category-pattern-audit-latest.csv", pattern_rows),
        (ROOL_ROOT / "category-image-prompt-audit-latest.csv", image_rows),
    ):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": str(PROMPT_ROOT),
        "categories": [
            {
                "slug": cat.slug,
                "label": cat.label,
                "group": cat.group,
                "folder": cat.folder,
                "patterns": [p.id for p in cat.patterns],
                "hero_only": True,
                "inline_images": False,
            }
            for cat in CATEGORIES
        ],
    }
    (ROOL_ROOT / "category-pattern-audit-latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    (ROOL_ROOT / "pattern-source-conflicts.md").write_text(
        dedent(
            f"""
            # Cloudflare pattern source conflicts

            Generated: {datetime.now().isoformat(timespec='seconds')}

            ## Resolved Decisions
            - Operational prompt source is `{PROMPT_ROOT}`.
            - `apps/api/prompts/channels/cloudflare/dongri-archive` is treated as Antigravity reference material, not runtime source.
            - Category `channel.json` files must be Cloudflare-only and must not reference `blogger:35` or `The Midnight Archives`.
            - Cloudflare image generation is hero-only. Inline image prompt fields may exist for compatibility, but generation instructions are disabled.

            ## Main Conflicts Fixed
            - Development patterns were split between Rool `dev-01..dev-07`, backend dev patterns, and Antigravity prompt prose. Final development IDs now use `dev-*` prefixed five-pattern taxonomy.
            - Festival and culture keep the shared information/curation/field-guide/expert/experience taxonomy.
            - Daily memo keeps the four Rool daily patterns.
            - Market categories now use channel-specific IDs instead of generic `problem-solution` or single chat patterns.
            """
        ).strip() + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (ROOL_ROOT / "deprecated-api-prompts-map.md").write_text(
        dedent(
            f"""
            # Deprecated API prompts map

            - Deprecated reference root: `D:\\Donggri_Platform\\BloggerGent\\apps\\api\\prompts\\channels\\cloudflare\\dongri-archive`
            - Operational source root: `{PROMPT_ROOT}`

            Use Antigravity changes from the deprecated root only after copying the intended rule into the operational source root. Do not let generation read mixed prompt roots.
            """
        ).strip() + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    for cat in CATEGORIES:
        d = cat_dir(cat)
        d.mkdir(parents=True, exist_ok=True)
        (d / "article_generation.md").write_text(article_prompt(cat), encoding="utf-8", newline="\n")
        (d / "image_prompt_generation.md").write_text(image_prompt(cat), encoding="utf-8", newline="\n")
        (d / "topic_discovery.md").write_text(topic_prompt(cat), encoding="utf-8", newline="\n")
        for stage, _, filename in STAGES:
            if filename in {"article_generation.md", "image_prompt_generation.md", "topic_discovery.md"}:
                continue
            (d / filename).write_text(stage_prompt(cat, stage), encoding="utf-8", newline="\n")
        (d / "channel.json").write_text(json.dumps(channel_json(cat), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        write_rool_docs(cat)

    root_data = json.loads((PROMPT_ROOT / "channel.json").read_text(encoding="utf-8-sig"))
    root_data["channel_id"] = "cloudflare:dongriarchive"
    root_data["channel_name"] = "Dongri Archive"
    root_data["provider"] = "cloudflare"
    root_data["backup_directory"] = "channels/cloudflare/dongri-archive"
    root_data["backup_files"] = [rel(cat, filename) for cat in CATEGORIES for _, _, filename in STAGES]
    root_data["allowed_category_slugs"] = [cat.slug for cat in CATEGORIES]
    root_data["hero_only"] = True
    root_data["inline_images"] = False
    (PROMPT_ROOT / "channel.json").write_text(json.dumps(root_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    patch_pattern_service()
    write_reports()
    print(json.dumps({"updated_categories": len(CATEGORIES), "source_root": str(PROMPT_ROOT), "rool_root": str(ROOL_ROOT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
