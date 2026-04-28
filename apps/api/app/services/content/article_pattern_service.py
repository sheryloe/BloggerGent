from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Article, SyncedCloudflarePost

ARTICLE_PATTERN_VERSION = 4
MYSTERIA_CATEGORY_SLUG = "미스테리아-스토리"
MYSTERIA_CATEGORY_SLUG_ALIASES = {
    MYSTERIA_CATEGORY_SLUG,
    "miseuteria-seutori",
    "미스테리아 스토리",
}


@dataclass(frozen=True, slots=True)
class ArticlePatternDefinition:
    pattern_id: str
    label: str
    summary: str
    html_hint: str


@dataclass(frozen=True, slots=True)
class ArticlePatternSelection:
    pattern_id: str
    pattern_version: int
    label: str
    summary: str
    html_hint: str
    allowed_pattern_ids: tuple[str, ...]
    recent_pattern_ids: tuple[str, ...]
    selection_note: str = "default_rotation"


ARTICLE_PATTERNS: dict[str, ArticlePatternDefinition] = {
    "experience-diary": ArticlePatternDefinition(
        pattern_id="experience-diary",
        label="Experience Diary",
        summary="A blog-style narrative that follows lived experience, movement, and reflection.",
        html_hint="section.callout, div.card-grid, aside.caution-box",
    ),
    "problem-solution": ArticlePatternDefinition(
        pattern_id="problem-solution",
        label="Problem Solution",
        summary="A practical structure that moves from problem definition to setup, solution, and applied tips.",
        html_hint="section.callout, div.comparison-table, section.route-steps",
    ),
    "route-timeline": ArticlePatternDefinition(
        pattern_id="route-timeline",
        label="Route Timeline",
        summary="A visit-oriented structure driven by time order, route flow, and checkpoints.",
        html_hint="section.timeline, section.route-steps, div.callout",
    ),
    "spot-card-grid": ArticlePatternDefinition(
        pattern_id="spot-card-grid",
        label="Spot Card Grid",
        summary="A comparison-led structure that breaks places or tools into clear cards.",
        html_hint="div.card-grid, div.fact-box, table.comparison-table",
    ),
    "case-timeline": ArticlePatternDefinition(
        pattern_id="case-timeline",
        label="Case Timeline",
        summary="Timeline-centered case reconstruction with dated movements, source records, and unresolved checkpoints.",
        html_hint="section.timeline-board, div.case-summary, table.evidence-table",
    ),
    "evidence-breakdown": ArticlePatternDefinition(
        pattern_id="evidence-breakdown",
        label="Evidence Breakdown",
        summary="Evidence-first structure that separates records, clues, competing theories, and their limits.",
        html_hint="table.evidence-table, table.interpretation-compare, aside.fact-box",
    ),
    "legend-context": ArticlePatternDefinition(
        pattern_id="legend-context",
        label="Legend Context",
        summary="Legend-focused structure connecting origin, transmission path, and modern reinterpretation.",
        html_hint="section.scene-intro, blockquote.quote-box, div.fact-box",
    ),
    "scene-investigation": ArticlePatternDefinition(
        pattern_id="scene-investigation",
        label="Scene Investigation",
        summary="Scene-driven investigation flow with location context, event progression, and uncertainty signals.",
        html_hint="section.scene-intro, div.scene-divider, aside.caution-box",
    ),
    "scp-dossier": ArticlePatternDefinition(
        pattern_id="scp-dossier",
        label="SCP Dossier",
        summary="File-style anomalous dossier using containment, logs, and evidence-aware reconstruction.",
        html_hint="section.case-summary, div.timeline-board, aside.note-aside",
    ),
    "claim-evidence-board": ArticlePatternDefinition(
        pattern_id="claim-evidence-board",
        label="Claim Evidence Board",
        summary="An evidence board structure that separates claims, records, counterpoints, and uncertainty.",
        html_hint="table.comparison-table, div.fact-box, aside.caution-box",
    ),
    "three-expert-chat": ArticlePatternDefinition(
        pattern_id="three-expert-chat",
        label="Three Expert Chat",
        summary="A three-voice chat structure that lets contrasting viewpoints surface naturally.",
        html_hint="div.chat-thread, aside.fact-box, table.comparison-table",
    ),
    "two-voice-market-chat": ArticlePatternDefinition(
        pattern_id="two-voice-market-chat",
        label="Two Voice Market Chat",
        summary="A two-voice market dialogue that frames one stock through aggressive and conservative viewpoints.",
        html_hint="div.chat-thread, table.comparison-table, aside.fact-box",
    ),
    "reflective-monologue": ArticlePatternDefinition(
        pattern_id="reflective-monologue",
        label="Reflective Monologue",
        summary="A reflective monologue that follows thought, feeling, and quiet insight.",
        html_hint="blockquote.quote-box, section.callout, aside.caution-box",
    ),
    "exhibition-field-guide": ArticlePatternDefinition(
        pattern_id="exhibition-field-guide",
        label="Exhibition Field Guide",
        summary="A field-guide structure that walks the reader through an exhibition, festival, or space.",
        html_hint="section.route-steps, div.card-grid, section.event-checklist",
    ),
    "policy-benefit-explainer": ArticlePatternDefinition(
        pattern_id="policy-benefit-explainer",
        label="Policy Benefit Explainer",
        summary="A policy explainer that breaks down eligibility, timing, amount, and application flow.",
        html_hint="section.policy-summary, div.fact-box, section.event-checklist",
    ),
    "nasdaq-macro-fundamental": ArticlePatternDefinition(
        pattern_id="nasdaq-macro-fundamental",
        label="Nasdaq Macro Fundamental",
        summary="Data-heavy institutional audit focusing on macroeconomic environment and fundamental financial quality.",
        html_hint="table.comparison-matrix, div.fact-box, section.policy-summary",
    ),
    "nasdaq-technical-precision": ArticlePatternDefinition(
        pattern_id="nasdaq-technical-precision",
        label="Nasdaq Technical Precision",
        summary="Technical analysis focus on price action, breakout levels, and specific trading setup signals.",
        html_hint="section.timeline, div.checkpoint-box, table.evidence-table",
    ),
    "nasdaq-growth-roadmap": ArticlePatternDefinition(
        pattern_id="nasdaq-growth-roadmap",
        label="Nasdaq Growth Roadmap",
        summary="Strategic long-term vision focusing on R&D, product innovation, and competitive moats.",
        html_hint="section.scene-intro, div.card-grid, blockquote.quote-box",
    ),
    "dev-troubleshoot-story": ArticlePatternDefinition(
        pattern_id="dev-troubleshoot-story",
        label="Dev Troubleshoot Story",
        summary="Narrative focused on the process of identifying, debugging, and solving a complex technical issue.",
        html_hint="section.case-summary, div.checkpoint-box, section.route-steps",
    ),
    "dev-tech-stack-review": ArticlePatternDefinition(
        pattern_id="dev-tech-stack-review",
        label="Dev Tech Stack Review",
        summary="Review of a specific technology stack or tool, including pros/cons and implementation guide.",
        html_hint="div.comparison-table, div.fact-box, section.callout",
    ),
    "dev-architecture-design": ArticlePatternDefinition(
        pattern_id="dev-architecture-design",
        label="Dev Architecture Design",
        summary="High-level system design, architectural patterns, and scalability considerations.",
        html_hint="section.scene-intro, div.card-grid, section.timeline-board",
    ),
    "daily-insight-memo": ArticlePatternDefinition(
        pattern_id="daily-insight-memo",
        label="Daily Insight Memo",
        summary="A short observation or memory that leads to a deeper philosophical or practical life lesson.",
        html_hint="blockquote.quote-box, section.callout, div.note-block",
    ),
    "daily-habit-tracker": ArticlePatternDefinition(
        pattern_id="daily-habit-tracker",
        label="Daily Habit Tracker",
        summary="Personal productivity, habit formation, and the psychological impact of daily routines.",
        html_hint="table.comparison-table, div.checkpoint-box, section.timeline",
    ),
    "daily-emotional-reflection": ArticlePatternDefinition(
        pattern_id="daily-emotional-reflection",
        label="Daily Emotional Reflection",
        summary="Reflective piece focusing on feelings, atmosphere, and sensory details of daily life.",
        html_hint="section.scene-intro, div.scene-divider, aside.fact-box",
    ),
    "info-deep-dive": ArticlePatternDefinition(
        pattern_id="info-deep-dive",
        label="Info Deep Dive",
        summary="Comprehensive all-in-one guide covering history, facts, and official details.",
        html_hint="section.policy-summary, table.comparison-table, div.fact-box",
    ),
    "curation-top-points": ArticlePatternDefinition(
        pattern_id="curation-top-points",
        label="Curation Top Points",
        summary="Selected top 5 highlights analyzed for maximum impact.",
        html_hint="div.card-grid, section.callout, aside.note-aside",
    ),
    "insider-field-guide": ArticlePatternDefinition(
        pattern_id="insider-field-guide",
        label="Insider Field Guide",
        summary="Practical master guide with hidden tips, best spots, and timing.",
        html_hint="section.route-steps, div.checkpoint-box, table.evidence-table",
    ),
    "expert-perspective": ArticlePatternDefinition(
        pattern_id="expert-perspective",
        label="Expert Perspective",
        summary="Artistic and cultural analysis from an expert's point of view.",
        html_hint="blockquote.quote-box, section.scene-intro, div.note-block",
    ),
    "experience-synthesis": ArticlePatternDefinition(
        pattern_id="experience-synthesis",
        label="Experience Synthesis",
        summary="Emotional narrative synthesized with practical review and ratings.",
        html_hint="section.callout, div.scene-divider, aside.fact-box",
    ),
    "life-hack-tutorial": ArticlePatternDefinition(
        pattern_id="life-hack-tutorial",
        label="Life Hack Tutorial",
        summary="Step-by-step practical guide to solving daily problems.",
        html_hint="section.route-steps, div.checkpoint-strip, section.callout",
    ),
    "benefit-audit-report": ArticlePatternDefinition(
        pattern_id="benefit-audit-report",
        label="Benefit Audit Report",
        summary="Thorough audit of benefits, eligibility, and application flows.",
        html_hint="table.comparison-matrix, section.policy-summary, div.fact-box",
    ),
    "efficiency-tool-review": ArticlePatternDefinition(
        pattern_id="efficiency-tool-review",
        label="Efficiency Tool Review",
        summary="Deep dive into tools or habits that improve productivity and quality of life.",
        html_hint="div.card-grid, div.note-block, table.comparison-table",
    ),
    "comparison-verdict": ArticlePatternDefinition(
        pattern_id="comparison-verdict",
        label="Comparison Verdict",
        summary="Multi-option comparison leading to a definitive 'best choice' verdict.",
        html_hint="table.comparison-matrix, div.checkpoint-box, section.callout",
    ),
"dev-info-deep-dive": ArticlePatternDefinition(
    pattern_id="dev-info-deep-dive",
    label="Dev Info Deep Dive",
    summary="기술의 역사, 공식 문서 기반 정보, 전체 컨텍스트를 다루는 포괄적 가이드.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"dev-curation-top-points": ArticlePatternDefinition(
    pattern_id="dev-curation-top-points",
    label="Dev Curation Top Points",
    summary="핵심 하이라이트 5가지를 선정해 실무 영향 중심으로 분석한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"dev-insider-field-guide": ArticlePatternDefinition(
    pattern_id="dev-insider-field-guide",
    label="Dev Insider Field Guide",
    summary="최적 설정, 타이밍, 트러블슈팅, 운영 팁을 담은 실전 마스터 가이드.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"dev-expert-perspective": ArticlePatternDefinition(
    pattern_id="dev-expert-perspective",
    label="Dev Expert Perspective",
    summary="개발자 관점에서 기술적, 사회적 영향과 아키텍처 선택을 비평한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"dev-experience-synthesis": ArticlePatternDefinition(
    pattern_id="dev-experience-synthesis",
    label="Dev Experience Synthesis",
    summary="실제 삽질 경험과 감정적 서사가 결합된 기술 리뷰.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"daily-01-reflective-monologue": ArticlePatternDefinition(
    pattern_id="daily-01-reflective-monologue",
    label="Reflective Monologue",
    summary="사유형 독백. 장면에서 질문으로 이어진다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"daily-02-insight-memo": ArticlePatternDefinition(
    pattern_id="daily-02-insight-memo",
    label="Insight Memo",
    summary="일상에서 발견한 작은 통찰을 적용 가능한 메모로 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"daily-03-habit-tracker": ArticlePatternDefinition(
    pattern_id="daily-03-habit-tracker",
    label="Habit Tracker",
    summary="루틴, 습관, 반복 기록을 재현 가능한 순서로 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"daily-04-emotional-reflection": ArticlePatternDefinition(
    pattern_id="daily-04-emotional-reflection",
    label="Emotional Reflection",
    summary="감정 회고를 구체적 장면과 문장으로 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"route-first-story": ArticlePatternDefinition(
    pattern_id="route-first-story",
    label="Route First Story",
    summary="이동 순서와 시간대가 중심인 루트형 기록.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"spot-focus-review": ArticlePatternDefinition(
    pattern_id="spot-focus-review",
    label="Spot Focus Review",
    summary="한 장소를 깊게 보고 방문 가치와 주의점을 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"seasonal-special": ArticlePatternDefinition(
    pattern_id="seasonal-special",
    label="Seasonal Special",
    summary="계절, 축제, 날씨, 혼잡이 중요한 방문 기록.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"logistics-budget": ArticlePatternDefinition(
    pattern_id="logistics-budget",
    label="Logistics Budget",
    summary="교통, 예약, 비용, 동선 효율을 중심으로 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"hidden-gem-discovery": ArticlePatternDefinition(
    pattern_id="hidden-gem-discovery",
    label="Hidden Gem Discovery",
    summary="덜 알려진 장소의 발견과 기록 가치를 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"thought-social-context": ArticlePatternDefinition(
    pattern_id="thought-social-context",
    label="Social Context",
    summary="사회적 사건과 분위기를 맥락으로 해석한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"thought-tech-culture": ArticlePatternDefinition(
    pattern_id="thought-tech-culture",
    label="Tech Culture",
    summary="기술 변화가 사람과 문화에 미치는 영향을 읽는다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"thought-generation-note": ArticlePatternDefinition(
    pattern_id="thought-generation-note",
    label="Generation Note",
    summary="세대, 관계, 감정의 변화를 기록한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"thought-personal-question": ArticlePatternDefinition(
    pattern_id="thought-personal-question",
    label="Personal Question",
    summary="개인적 질문으로 사회적 주제를 다시 본다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"stock-cartoon-summary": ArticlePatternDefinition(
    pattern_id="stock-cartoon-summary",
    label="Cartoon Summary",
    summary="시장 이슈를 만화식 요약으로 쉽게 풀어낸다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"stock-technical-analysis": ArticlePatternDefinition(
    pattern_id="stock-technical-analysis",
    label="Technical Analysis",
    summary="가격 흐름과 기술적 구간을 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"stock-macro-intelligence": ArticlePatternDefinition(
    pattern_id="stock-macro-intelligence",
    label="Macro Intelligence",
    summary="금리, 물가, 정책, 지표가 시장에 미치는 영향을 본다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"stock-corporate-event-watch": ArticlePatternDefinition(
    pattern_id="stock-corporate-event-watch",
    label="Corporate Event Watch",
    summary="실적, 이벤트, 기업 뉴스 중심 분석.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"stock-risk-timing": ArticlePatternDefinition(
    pattern_id="stock-risk-timing",
    label="Risk Timing",
    summary="진입/관망/리스크 타이밍을 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"crypto-cartoon-summary": ArticlePatternDefinition(
    pattern_id="crypto-cartoon-summary",
    label="Cartoon Summary",
    summary="크립토 이슈를 만화식 요약으로 쉽게 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"crypto-on-chain-analysis": ArticlePatternDefinition(
    pattern_id="crypto-on-chain-analysis",
    label="On-chain Analysis",
    summary="온체인 데이터와 거래 흐름을 중심으로 분석한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"crypto-protocol-deep-dive": ArticlePatternDefinition(
    pattern_id="crypto-protocol-deep-dive",
    label="Protocol Deep Dive",
    summary="프로토콜 구조, 업그레이드, 생태계 변화를 설명한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"crypto-regulatory-macro": ArticlePatternDefinition(
    pattern_id="crypto-regulatory-macro",
    label="Regulatory Macro",
    summary="규제와 거시 환경이 크립토에 미치는 영향을 분석한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"crypto-market-sentiment": ArticlePatternDefinition(
    pattern_id="crypto-market-sentiment",
    label="Market Sentiment",
    summary="심리, 뉴스, 유동성, 리스크 시나리오를 점검한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"nasdaq-cartoon-summary": ArticlePatternDefinition(
    pattern_id="nasdaq-cartoon-summary",
    label="Cartoon Summary",
    summary="나스닥 기업 이슈를 만화식 요약으로 정리한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"nasdaq-technical-deep-dive": ArticlePatternDefinition(
    pattern_id="nasdaq-technical-deep-dive",
    label="Technical Deep Dive",
    summary="가격 흐름과 기술적 구간을 정밀하게 본다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"nasdaq-macro-impact": ArticlePatternDefinition(
    pattern_id="nasdaq-macro-impact",
    label="Macro Impact",
    summary="금리, 달러, 실적 시즌, AI 투자 사이클 영향을 분석한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"nasdaq-big-tech-whale-watch": ArticlePatternDefinition(
    pattern_id="nasdaq-big-tech-whale-watch",
    label="Big Tech Whale Watch",
    summary="빅테크와 대형 자금 흐름을 추적한다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
"nasdaq-hypothesis-scenario": ArticlePatternDefinition(
    pattern_id="nasdaq-hypothesis-scenario",
    label="Hypothesis Scenario",
    summary="상승/하락/횡보 시나리오를 나누어 본다.",
    html_hint="section.callout, div.fact-box, table.comparison-table",
),
}


_MYSTERY_ALLOWED_PATTERN_IDS: tuple[str, ...] = (
    "case-timeline",
    "evidence-breakdown",
    "legend-context",
    "scene-investigation",
    "scp-dossier",
)


_BLOGGER_PATTERN_MAP: dict[tuple[str, str], tuple[str, ...]] = {
    ("korea_travel", "travel"): ("experience-diary", "route-timeline", "spot-card-grid"),
    ("korea_travel", "culture"): ("experience-diary", "route-timeline", "exhibition-field-guide"),
    ("korea_travel", "food"): ("experience-diary", "spot-card-grid", "route-timeline"),
    ("world_mystery", "case-files"): _MYSTERY_ALLOWED_PATTERN_IDS,
    ("world_mystery", "legends-lore"): _MYSTERY_ALLOWED_PATTERN_IDS,
    ("world_mystery", "mystery-archives"): _MYSTERY_ALLOWED_PATTERN_IDS,
}

_CLOUDFLARE_PATTERN_MAP: dict[str, tuple[str, ...]] = {
    "개발과-프로그래밍": ("dev-info-deep-dive", "dev-curation-top-points", "dev-insider-field-guide", "dev-expert-perspective", "dev-experience-synthesis",),
    "일상과-메모": ("daily-01-reflective-monologue", "daily-02-insight-memo", "daily-03-habit-tracker", "daily-04-emotional-reflection",),
    "여행과-기록": ("route-first-story", "spot-focus-review", "seasonal-special", "logistics-budget", "hidden-gem-discovery",),
    "삶을-유용하게": ("life-hack-tutorial", "benefit-audit-report", "efficiency-tool-review", "comparison-verdict",),
    "삶의-기름칠": ("life-hack-tutorial", "benefit-audit-report", "efficiency-tool-review", "comparison-verdict",),
    "동그리의-생각": ("thought-social-context", "thought-tech-culture", "thought-generation-note", "thought-personal-question",),
    "미스테리아-스토리": ("case-timeline", "evidence-breakdown", "legend-context", "scene-investigation", "scp-dossier",),
    "주식의-흐름": ("stock-cartoon-summary", "stock-technical-analysis", "stock-macro-intelligence", "stock-corporate-event-watch", "stock-risk-timing",),
    "크립토의-흐름": ("crypto-cartoon-summary", "crypto-on-chain-analysis", "crypto-protocol-deep-dive", "crypto-regulatory-macro", "crypto-market-sentiment",),
    "나스닥의-흐름": ("nasdaq-cartoon-summary", "nasdaq-technical-deep-dive", "nasdaq-macro-impact", "nasdaq-big-tech-whale-watch", "nasdaq-hypothesis-scenario",),
    "축제와-현장": ("info-deep-dive", "curation-top-points", "insider-field-guide", "expert-perspective", "experience-synthesis",),
    "문화와-공간": ("info-deep-dive", "curation-top-points", "insider-field-guide", "expert-perspective", "experience-synthesis",),
}

_CLOUDFLARE_PATTERN_MAP.update(
    {
        "개발과-프로그래밍": (
            "dev-info-deep-dive",
            "dev-curation-top-points",
            "dev-insider-field-guide",
            "dev-expert-perspective",
            "dev-experience-synthesis",
        ),
        "일상과-메모": (
            "daily-01-reflective-monologue",
            "daily-02-insight-memo",
            "daily-03-habit-tracker",
            "daily-04-emotional-reflection",
        ),
        "여행과-기록": (
            "route-first-story",
            "spot-focus-review",
            "seasonal-special",
            "logistics-budget",
            "hidden-gem-discovery",
        ),
        "삶을-유용하게": (
            "life-hack-tutorial",
            "benefit-audit-report",
            "efficiency-tool-review",
            "comparison-verdict",
        ),
        "삶의-기름칠": (
            "life-hack-tutorial",
            "benefit-audit-report",
            "efficiency-tool-review",
            "comparison-verdict",
        ),
        "동그리의-생각": (
            "thought-social-context",
            "thought-tech-culture",
            "thought-generation-note",
            "thought-personal-question",
        ),
        "미스테리아-스토리": (
            "case-timeline",
            "evidence-breakdown",
            "legend-context",
            "scene-investigation",
            "scp-dossier",
        ),
        "주식의-흐름": (
            "stock-cartoon-summary",
            "stock-technical-analysis",
            "stock-macro-intelligence",
            "stock-corporate-event-watch",
            "stock-risk-timing",
        ),
        "크립토의-흐름": (
            "crypto-cartoon-summary",
            "crypto-on-chain-analysis",
            "crypto-protocol-deep-dive",
            "crypto-regulatory-macro",
            "crypto-market-sentiment",
        ),
        "나스닥의-흐름": (
            "nasdaq-technical-deep-dive",
            "nasdaq-macro-impact",
            "nasdaq-big-tech-whale-watch",
            "nasdaq-hypothesis-scenario",
        ),
        "축제와-현장": (
            "info-deep-dive",
            "curation-top-points",
            "insider-field-guide",
            "expert-perspective",
            "experience-synthesis",
        ),
        "문화와-공간": (
            "info-deep-dive",
            "curation-top-points",
            "insider-field-guide",
            "expert-perspective",
            "experience-synthesis",
        ),
    }
)

_MYSTERIA_PATTERN_WEIGHTS: dict[str, float] = {
    "case-timeline": 30.0,
    "evidence-breakdown": 25.0,
    "legend-context": 15.0,
    "scene-investigation": 20.0,
    "scp-dossier": 10.0,
}

_MYSTERIA_ALLOWED_PATTERN_IDS: tuple[str, ...] = tuple(_MYSTERIA_PATTERN_WEIGHTS.keys())
_CLOUDFLARE_PATTERN_MAP[MYSTERIA_CATEGORY_SLUG] = _MYSTERIA_ALLOWED_PATTERN_IDS
for _alias in tuple(MYSTERIA_CATEGORY_SLUG_ALIASES):
    _CLOUDFLARE_PATTERN_MAP[_alias] = _MYSTERIA_ALLOWED_PATTERN_IDS


def _normalize_key(value: str | None) -> str:
    return str(value or "").strip().casefold()


def _resolve_pattern_definition(pattern_id: str) -> ArticlePatternDefinition:
    return ARTICLE_PATTERNS.get(pattern_id, ARTICLE_PATTERNS["problem-solution"])


def _normalize_allowed_ids(allowed_ids: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in allowed_ids:
        value = str(raw or "").strip()
        if not value:
            continue
        key = _normalize_key(value)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized


def _resolve_pattern_weight(pattern_id: str, *, weights: Mapping[str, float] | None) -> float:
    if not weights:
        return 1.0
    target = _normalize_key(pattern_id)
    for raw_key, raw_weight in weights.items():
        if _normalize_key(raw_key) == target:
            try:
                return max(float(raw_weight), 0.0)
            except (TypeError, ValueError):
                return 1.0
    return 1.0


def _blocked_threepeat_pattern_id(*, allowed_ids: Sequence[str], recent_ids: Sequence[str]) -> str | None:
    normalized_recent = [_normalize_key(item) for item in recent_ids if str(item or "").strip()]
    if len(normalized_recent) < 2 or normalized_recent[0] != normalized_recent[1]:
        return None
    blocked_norm = normalized_recent[0]
    for candidate in allowed_ids:
        if _normalize_key(candidate) == blocked_norm:
            return str(candidate)
    return None


def _pick_pattern(
    *,
    allowed_ids: Sequence[str],
    recent_ids: Sequence[str],
    rotation_seed: int = 0,
    weights: Mapping[str, float] | None = None,
    disallow_threepeat: bool = False,
) -> str:
    normalized_allowed = _normalize_allowed_ids(allowed_ids)
    if not normalized_allowed:
        return "problem-solution"

    blocked_threepeat = None
    if disallow_threepeat:
        blocked_threepeat = _blocked_threepeat_pattern_id(allowed_ids=normalized_allowed, recent_ids=recent_ids)
    candidate_pool = (
        [candidate for candidate in normalized_allowed if _normalize_key(candidate) != _normalize_key(blocked_threepeat)]
        if blocked_threepeat
        else list(normalized_allowed)
    )
    if not candidate_pool:
        candidate_pool = list(normalized_allowed)

    normalized_recent = [_normalize_key(item) for item in recent_ids if str(item or "").strip()]
    usage_counter = Counter(normalized_recent)
    recent_window = set(normalized_recent[:3])
    freshness_pool = [candidate for candidate in candidate_pool if _normalize_key(candidate) not in recent_window]
    if freshness_pool:
        candidate_pool = freshness_pool

    candidate_scores: dict[str, float] = {}
    for candidate in candidate_pool:
        key = _normalize_key(candidate)
        base_weight = _resolve_pattern_weight(candidate, weights=weights)
        usage_penalty = float(usage_counter.get(key, 0))
        score = base_weight / (1.0 + usage_penalty)
        if key in recent_window:
            score *= 0.5
        candidate_scores[candidate] = score

    max_score = max(candidate_scores.values()) if candidate_scores else 0.0
    winners = [candidate for candidate in candidate_pool if abs(candidate_scores[candidate] - max_score) < 1e-9]
    if not winners:
        winners = candidate_pool
    index = int(rotation_seed or 0) % len(winners)
    return winners[index]


def _recent_blogger_pattern_ids(
    db: Session,
    *,
    blog_id: int,
    editorial_category_key: str | None,
    limit: int = 3,
) -> tuple[str, ...]:
    statement = select(Article.article_pattern_id).where(Article.blog_id == blog_id, Article.article_pattern_id.is_not(None))
    normalized_editorial_key = str(editorial_category_key or "").strip()
    if normalized_editorial_key:
        statement = statement.where(Article.editorial_category_key == normalized_editorial_key)
    rows = db.execute(statement.order_by(Article.created_at.desc(), Article.id.desc()).limit(limit)).scalars().all()
    return tuple(str(item).strip() for item in rows if str(item or "").strip())


def _recent_cloudflare_pattern_ids(
    db: Session,
    *,
    category_slug: str | None,
    limit: int = 3,
) -> tuple[str, ...]:
    normalized_slug = str(category_slug or "").strip()
    statement = select(SyncedCloudflarePost.article_pattern_id).where(
        SyncedCloudflarePost.article_pattern_id.is_not(None)
    )
    if normalized_slug:
        statement = statement.where(
            (SyncedCloudflarePost.canonical_category_slug == normalized_slug)
            | (SyncedCloudflarePost.category_slug == normalized_slug)
        )
    rows = (
        db.execute(
            statement.order_by(
                SyncedCloudflarePost.published_at.desc().nullslast(),
                SyncedCloudflarePost.updated_at_remote.desc().nullslast(),
                SyncedCloudflarePost.id.desc(),
            ).limit(limit)
        )
        .scalars()
        .all()
    )
    return tuple(str(item).strip() for item in rows if str(item or "").strip())


def select_blogger_article_pattern(
    db: Session,
    *,
    blog_id: int,
    profile_key: str | None,
    editorial_category_key: str | None,
) -> ArticlePatternSelection:
    normalized_profile = str(profile_key or "").strip()
    normalized_editorial_key = str(editorial_category_key or "").strip()
    is_mystery_profile = normalized_profile == "world_mystery"
    allowed_ids = _BLOGGER_PATTERN_MAP.get(
        (normalized_profile, normalized_editorial_key),
        ("problem-solution", "spot-card-grid") if normalized_profile == "custom" else ("problem-solution",),
    )
    recent_ids = _recent_blogger_pattern_ids(
        db,
        blog_id=blog_id,
        editorial_category_key=normalized_editorial_key,
    )
    blocked_threepeat = (
        _blocked_threepeat_pattern_id(allowed_ids=allowed_ids, recent_ids=recent_ids)
        if is_mystery_profile
        else None
    )
    chosen_id = _pick_pattern(
        allowed_ids=allowed_ids,
        recent_ids=recent_ids,
        rotation_seed=len(recent_ids),
        weights=_MYSTERIA_PATTERN_WEIGHTS if is_mystery_profile else None,
        disallow_threepeat=is_mystery_profile,
    )
    definition = _resolve_pattern_definition(chosen_id)
    return ArticlePatternSelection(
        pattern_id=definition.pattern_id,
        pattern_version=ARTICLE_PATTERN_VERSION,
        label=definition.label,
        summary=definition.summary,
        html_hint=definition.html_hint,
        allowed_pattern_ids=tuple(allowed_ids),
        recent_pattern_ids=recent_ids,
        selection_note=(
            f"weighted_5_pattern_rotation;blocked_threepeat={blocked_threepeat or 'none'}"
            if is_mystery_profile
            else "default_rotation"
        ),
    )


def select_cloudflare_article_pattern(
    db: Session,
    *,
    category_slug: str | None,
) -> ArticlePatternSelection:
    normalized_slug = str(category_slug or "").strip()
    is_mysteria = normalized_slug in MYSTERIA_CATEGORY_SLUG_ALIASES
    allowed_ids = (
        _MYSTERIA_ALLOWED_PATTERN_IDS
        if is_mysteria
        else _CLOUDFLARE_PATTERN_MAP.get(normalized_slug, ("problem-solution", "spot-card-grid"))
    )
    recent_limit = 12 if is_mysteria else 3
    recent_ids = _recent_cloudflare_pattern_ids(
        db,
        category_slug=normalized_slug,
        limit=recent_limit,
    )
    total_posts = db.execute(
        select(func.count(SyncedCloudflarePost.id)).where(
            (SyncedCloudflarePost.canonical_category_slug == normalized_slug)
            | (SyncedCloudflarePost.category_slug == normalized_slug)
        )
    ).scalar_one()
    blocked_threepeat = (
        _blocked_threepeat_pattern_id(allowed_ids=allowed_ids, recent_ids=recent_ids)
        if is_mysteria
        else None
    )
    chosen_id = _pick_pattern(
        allowed_ids=allowed_ids,
        recent_ids=recent_ids,
        rotation_seed=int(total_posts or 0),
        weights=_MYSTERIA_PATTERN_WEIGHTS if is_mysteria else None,
        disallow_threepeat=is_mysteria,
    )
    definition = _resolve_pattern_definition(chosen_id)
    if is_mysteria:
        weight_summary = ", ".join(
            f"{pattern_id}:{int(weight)}"
            for pattern_id, weight in _MYSTERIA_PATTERN_WEIGHTS.items()
        )
        selection_note = (
            f"weighted_5_pattern_rotation;blocked_threepeat={blocked_threepeat or 'none'};"
            f"weights={weight_summary}"
        )
    else:
        selection_note = "default_rotation"
    return ArticlePatternSelection(
        pattern_id=definition.pattern_id,
        pattern_version=ARTICLE_PATTERN_VERSION,
        label=definition.label,
        summary=definition.summary,
        html_hint=definition.html_hint,
        allowed_pattern_ids=tuple(allowed_ids),
        recent_pattern_ids=recent_ids,
        selection_note=selection_note,
    )


def build_article_pattern_prompt_block(selection: ArticlePatternSelection) -> str:
    allowed = ", ".join(selection.allowed_pattern_ids)
    recent = ", ".join(selection.recent_pattern_ids) if selection.recent_pattern_ids else "none"
    return (
        "[Article pattern registry]\n"
        f"- Use this pattern for this draft: {selection.pattern_id} (v{selection.pattern_version}).\n"
        f"- Pattern summary: {selection.summary}.\n"
        f"- Preferred HTML structures: {selection.html_hint}.\n"
        f"- Allowed patterns for this category: {allowed}.\n"
        f"- Recent pattern history to avoid repeating when possible: {recent}.\n"
        f"- Selection rationale: {selection.selection_note or 'default_rotation'}.\n"
        "- Do not repeat the same pattern 3 runs in a row.\n"
        "- Return article_pattern_id and article_pattern_version in the JSON output.\n"
    )


def apply_pattern_defaults(output, selection: ArticlePatternSelection):
    allowed_norm = {_normalize_key(item) for item in selection.allowed_pattern_ids}
    current_pattern_id = str(getattr(output, "article_pattern_id", "") or "").strip()
    if not current_pattern_id or _normalize_key(current_pattern_id) not in allowed_norm:
        output.article_pattern_id = selection.pattern_id
    if getattr(output, "article_pattern_version", None) in {None, 0}:
        output.article_pattern_version = selection.pattern_version
    return output
