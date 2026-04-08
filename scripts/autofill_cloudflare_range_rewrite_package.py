#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from package_common import (
    REWRITE_PACKAGE_ROOT,
    collect_markdown_asset_refs,
    extract_html_outline,
    extract_html_paragraphs,
    normalize_space,
    parse_tag_string,
    read_csv_utf8,
    write_csv_utf8,
    write_json,
    write_text_utf8,
)


MARKDOWN_H2_RE = re.compile(r"^\s*##\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_H3_RE = re.compile(r"^\s*###\s+(.+?)\s*$", re.MULTILINE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\([^)]+\)")
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]+`")
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")

BLOCKED_HEADINGS = (
    "기준 시각",
    "핵심 요약",
    "확인된 사실",
    "미확인 정보",
    "출처/확인 경로",
    "전개 시나리오",
    "행동 체크리스트",
    "sources / verification path",
    "confirmed facts",
    "unverified",
)

CANONICAL_MANIFEST_FIELDS = [
    "review_status",
    "published_local_date",
    "source_slug",
    "source_url",
    "post_id",
    "current_title",
    "new_title",
    "current_excerpt",
    "new_excerpt",
    "current_seo_title",
    "new_seo_title",
    "current_seo_description",
    "new_seo_description",
    "current_category",
    "target_category",
    "action",
    "tags",
    "published_at",
    "status",
    "cover_image",
    "inline_asset_count",
    "notes",
    "markdown_path",
    "snapshot_json_path",
]

CATEGORY_PROFILE: dict[str, str] = {
    "개발과 프로그래밍": "tech",
    "크립토의 흐름": "market",
    "주식의 흐름": "market",
    "여행과 기록": "travel",
    "축제와 현장": "travel",
    "문화와 공간": "travel",
    "미스테리아 스토리": "mystery",
    "삶을 유용하게": "life",
    "삶의 기름칠": "life",
    "일상과 메모": "essay",
    "동그리의 생각": "essay",
}

PROFILE_TEXT = {
    "tech": {
        "focus": "도구 도입의 효과를 숫자로 검증하고, 보안과 협업 규칙을 함께 고정하는 것",
        "risk": ["보안 정책 미정", "효과 측정 지표 부재", "팀 규칙 없이 개인별 사용"],
        "metrics": ["작업 리드타임", "리뷰 코멘트 밀도", "배포 후 결함 빈도"],
        "tags": ["실무 가이드", "도입 전략", "체크리스트", "생산성 개선"],
    },
    "market": {
        "focus": "가격보다 조건을 먼저 보고, 시나리오별 대응을 미리 정하는 것",
        "risk": ["과도한 추격 매수", "손실 제한 규칙 부재", "단일 지표 의존"],
        "metrics": ["손익비", "최대 낙폭", "시나리오 적중률"],
        "tags": ["시장 분석", "리스크 관리", "시나리오", "투자 체크포인트"],
    },
    "travel": {
        "focus": "동선과 대기 시간을 줄여 체감 만족도를 높이는 것",
        "risk": ["혼잡 시간 미확인", "이동 동선 과다", "현장 마감 시간 누락"],
        "metrics": ["대기 시간", "이동 거리", "예산 대비 만족도"],
        "tags": ["여행 계획", "현장 팁", "동선 최적화", "예산 관리"],
    },
    "mystery": {
        "focus": "사실과 해석을 분리해 읽고, 과장된 결론을 피하는 것",
        "risk": ["단일 출처 과신", "시대 맥락 누락", "추정과 사실 혼동"],
        "metrics": ["근거 출처 수", "가정 명시율", "해석 일관성"],
        "tags": ["사건 분석", "기록 해석", "맥락 읽기", "검증 포인트"],
    },
    "life": {
        "focus": "조건을 정확히 확인하고, 신청·실행 과정의 실수를 줄이는 것",
        "risk": ["자격 요건 오해", "증빙 서류 누락", "마감 시간 착오"],
        "metrics": ["처리 소요 시간", "반려율", "재신청 횟수"],
        "tags": ["실전 팁", "신청 가이드", "준비 서류", "실수 방지"],
    },
    "essay": {
        "focus": "핵심 질문을 좁히고, 바로 실행 가능한 결론으로 연결하는 것",
        "risk": ["질문이 넓어 행동으로 연결되지 않음", "기록 없이 즉흥 판단", "우선순위 미정"],
        "metrics": ["완료한 행동 수", "재검토 횟수", "의사결정 속도"],
        "tags": ["생각 정리", "실행 루틴", "메모 템플릿", "회고"],
    },
}

KOREAN_STOPWORDS = {
    "그리고",
    "그러나",
    "하지만",
    "가이드",
    "실전",
    "완벽",
    "바로",
    "지금",
    "위한",
    "대한",
    "으로",
    "에서",
    "까지",
    "하는",
    "하기",
    "되는",
    "정리",
    "분석",
    "체크리스트",
    "전략",
    "포인트",
    "기준",
    "방법",
}


@dataclass
class RewriteResult:
    slug: str
    status: str
    reason: str
    markdown_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Autofill a cloudflare-range-rewrite package with deterministic Korean rewrites "
            "(no external LLM / no OpenAI API)."
        )
    )
    parser.add_argument("--package-date", required=True, help="Package folder name under storage/rewrite-packages.")
    parser.add_argument("--apply", action="store_true", help="Write drafts + update manifest (sets review_status=approved).")
    parser.add_argument("--dry-run", action="store_true", help="Validate only (default when --apply is absent).")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise ValueError("--apply and --dry-run cannot be used together.")
    return args


def _compact_plain_text(markdown: str) -> str:
    text = markdown or ""
    text = CODE_FENCE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = MARKDOWN_IMAGE_RE.sub(" ", text)
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = WHITESPACE_RE.sub("", text)
    return text.strip()


def _strip_markdown_html(value: str) -> str:
    text = value or ""
    text = CODE_FENCE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = MARKDOWN_IMAGE_RE.sub(" ", text)
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _has_blocked_heading(markdown: str) -> bool:
    headings = [normalize_space(item) for item in MARKDOWN_H2_RE.findall(markdown or "")]
    headings.extend(normalize_space(item) for item in MARKDOWN_H3_RE.findall(markdown or ""))
    lowered = [h.casefold() for h in headings if h]
    return any(token.casefold() in h for token in BLOCKED_HEADINGS for h in lowered)


def _count_headings(markdown: str) -> tuple[int, int]:
    return len(MARKDOWN_H2_RE.findall(markdown or "")), len(MARKDOWN_H3_RE.findall(markdown or ""))


def _count_faq_questions(markdown: str) -> int:
    text = markdown or ""
    marker = re.search(r"^\s*##\s*(FAQ|자주\s*묻는\s*질문)\s*$", text, flags=re.MULTILINE | re.IGNORECASE)
    if not marker:
        return 0
    tail = text[marker.end() :]
    return len(MARKDOWN_H3_RE.findall(tail))


def _pick_profile(category: str) -> str:
    return CATEGORY_PROFILE.get(normalize_space(category), "essay")


def _strip_trailing_punct(value: str) -> str:
    return normalize_space(value).rstrip("?!.:,;")


def _extract_source_material(content: str) -> tuple[list[str], list[str]]:
    outlines = [normalize_space(item.get("heading")) for item in extract_html_outline(content) if isinstance(item, dict)]
    outlines = [item for item in outlines if item]

    paragraphs = [normalize_space(item) for item in extract_html_paragraphs(content, limit=18)]
    if not paragraphs:
        plain = _strip_markdown_html(content)
        raw_sentences = SENTENCE_SPLIT_RE.split(plain)
        paragraphs = [normalize_space(item) for item in raw_sentences if len(normalize_space(item)) >= 40]

    sentence_pool: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        for sentence in SENTENCE_SPLIT_RE.split(paragraph):
            normalized = normalize_space(sentence)
            if len(normalized) < 28:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            sentence_pool.append(normalized)
            if len(sentence_pool) >= 14:
                break
        if len(sentence_pool) >= 14:
            break

    if not sentence_pool:
        fallback = _strip_markdown_html(content)
        if fallback:
            sentence_pool = [fallback[:220]]
    return outlines[:8], sentence_pool


def _extract_keywords(title: str, tags: list[str], headings: list[str]) -> list[str]:
    tokens = TOKEN_RE.findall(f"{title} {' '.join(tags)} {' '.join(headings)}")
    score: dict[str, int] = {}
    for token in tokens:
        word = normalize_space(token)
        if len(word) < 2:
            continue
        lowered = word.casefold()
        if lowered in KOREAN_STOPWORDS:
            continue
        score[word] = score.get(word, 0) + 1
    ranked = sorted(score.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [word for word, _ in ranked[:8]]


def _fit_meta_length(value: str) -> str:
    text = normalize_space(value)
    additions = [
        "핵심 흐름, 우선순위, 리스크 대응을 한 번에 정리해 읽고 바로 적용할 수 있게 구성했습니다.",
        "실행 순서와 검증 포인트까지 포함해 시행착오를 줄이도록 설계했습니다.",
    ]
    for addon in additions:
        if len(text) >= 120:
            break
        text = normalize_space(f"{text} {addon}")
    if len(text) > 160:
        text = normalize_space(text[:160]).rstrip(" .,")
    if len(text) < 120:
        text = normalize_space(
            f"{text} 지금 필요한 체크리스트와 FAQ를 통해 핵심 결정만 빠르게 마무리할 수 있습니다."
        )
    if len(text) > 160:
        text = normalize_space(text[:160]).rstrip(" .,")
    return text


def _finalize_excerpt(title: str, excerpt: str, category: str) -> str:
    value = normalize_space(excerpt)
    if len(value) >= 60:
        return value[:220].rstrip(" .")
    title_clean = _strip_trailing_punct(title) or title
    fallback = normalize_space(
        f"'{title_clean}' 주제를 {category} 관점에서 다시 정리했습니다. 핵심 흐름, 실수 방지 포인트, 실행 체크리스트까지 "
        "한 번에 확인할 수 있도록 구성했습니다."
    )
    return fallback[:220].rstrip(" .")


def _finalize_meta(title: str, excerpt: str, category: str) -> str:
    base = normalize_space(excerpt)
    if not base:
        title_clean = _strip_trailing_punct(title) or title
        base = normalize_space(
            f"'{title_clean}' 주제를 {category} 관점에서 실전형으로 정리했습니다. 핵심 흐름, 우선순위, 리스크 대응, FAQ를 통해 "
            "지금 필요한 결정을 빠르게 내릴 수 있도록 구성했습니다."
        )
    return _fit_meta_length(base)


def _finalize_tags(category: str, raw_tags: str, keywords: list[str], profile: str) -> list[str]:
    defaults = PROFILE_TEXT[profile]["tags"]
    existing = parse_tag_string(raw_tags)
    out: list[str] = []
    seen: set[str] = set()

    def push(value: str) -> None:
        tag = normalize_space(value)
        if not tag:
            return
        key = tag.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(tag)

    push(category)
    for item in existing:
        push(item)
    for item in defaults:
        push(item)
    for keyword in keywords:
        push(keyword)
    return out[:8]


def _render_asset_block(title: str, asset_urls: list[str]) -> str:
    if not asset_urls:
        return ""
    lines = ["## 참고 이미지"]
    for index, url in enumerate(asset_urls, start=1):
        alt = normalize_space(f"{title} 관련 이미지 {index}")
        lines.append(f"![{alt}]({url})")
    return "\n\n".join(lines).strip()


def _render_faq(title: str, profile: str, keywords: list[str]) -> str:
    topic = _strip_trailing_punct(title) or title
    kw = keywords[0] if keywords else "핵심 조건"

    if profile == "market":
        qa = [
            (f"{topic}에서 지금 가장 먼저 확인할 지표는?", "가격 하나만 보지 말고 거래량, 변동성, 유동성 조건을 같이 확인하세요. "
             "세 지표가 같은 방향인지 본 뒤에 진입 시나리오를 선택해야 손실 구간을 줄일 수 있습니다."),
            ("손실을 줄이기 위한 최소 규칙은?", "진입 전 손절 기준과 비중 한도를 먼저 고정하세요. 규칙을 먼저 정하면 감정 추격매수나 과도한 물타기를 막을 수 있습니다."),
            ("초보자가 가장 자주 하는 실수는?", "상승 구간에서 근거 없이 레버리지를 키우는 실수입니다. 조건을 충족한 구간에서만 단계적으로 접근해야 생존 확률이 올라갑니다."),
            ("이 글의 체크리스트는 어떻게 써야 하나?", "장 시작 전 3분 점검용으로 쓰면 좋습니다. 지표 확인, 시나리오 선택, 손실 제한 규칙만 체크해도 의사결정 품질이 달라집니다."),
        ]
    elif profile == "travel":
        qa = [
            (f"{topic} 일정은 언제가 가장 효율적인가?", "오픈 직후나 마감 전 1~2시간이 비교적 여유롭습니다. 혼잡 시간대를 피하면 같은 동선으로 더 많은 장소를 볼 수 있습니다."),
            ("동선 최적화의 핵심은?", "메인 스팟 2~3곳을 먼저 고정하고 주변 코스를 묶으세요. 이동 수단을 최소화하면 체력과 시간을 동시에 아낄 수 있습니다."),
            ("예산은 어떻게 잡는 게 좋은가?", "무료 구간과 유료 구간을 나눠서 계획하세요. 핵심 체험 1~2개만 선택해도 만족도를 유지하면서 과소비를 막을 수 있습니다."),
            ("당일 실수 방지 한 가지는?", "마감 시간과 입장 정책을 먼저 확인하세요. 대부분의 시행착오는 현장 도착 후 운영 시간을 몰라 발생합니다."),
        ]
    elif profile == "tech":
        qa = [
            (f"{topic}을 도입할 때 첫 단계는?", "전사 도입보다 반복 작업이 많은 파일/업무부터 시작하세요. 작은 범위에서 효과를 계측해야 팀 확산 시 실패 확률이 낮아집니다."),
            ("보안 관점에서 반드시 정할 규칙은?", "어떤 코드/데이터를 도구에 입력할 수 있는지 문장으로 고정해야 합니다. 권한과 검토 절차까지 포함해야 운영 사고를 막을 수 있습니다."),
            ("생산성 효과는 어떻게 측정하나?", "작업 리드타임, 리뷰 코멘트 수, 배포 후 결함 수를 전후 비교하세요. 숫자 없이 체감만으로 판단하면 도입 성공 여부를 놓치기 쉽습니다."),
            (f"{kw}을 놓치지 않으려면?", "팀 체크리스트를 PR 템플릿에 넣고 매 스프린트마다 동일 기준으로 검토하세요. 규칙이 문서화되어야 개인 편차가 줄어듭니다."),
        ]
    else:
        qa = [
            (f"{topic}을 빠르게 이해하는 방법은?", "조건-리스크-실행 순서로 읽으면 핵심을 빠르게 잡을 수 있습니다. 전체를 외우기보다 먼저 실행할 항목을 고정하세요."),
            ("가장 흔한 실패 패턴은?", "조건 검증 없이 바로 실행하는 패턴입니다. 체크리스트를 먼저 통과시키면 대부분의 실수를 줄일 수 있습니다."),
            ("오늘 바로 할 한 가지는?", "가장 영향이 큰 한 단계를 정해 바로 실행하세요. 작은 실행 1건이 계획 10개보다 결과를 빠르게 만듭니다."),
            ("내일 무엇으로 결과를 판단하면 되나?", "시간 절감, 오류 감소, 완료한 행동 수를 확인하세요. 숫자로 확인해야 다음 액션을 정확히 고를 수 있습니다."),
        ]

    lines = ["## FAQ"]
    for index, (q, a) in enumerate(qa, start=1):
        lines.append(f"### Q{index}. {q}")
        lines.append(f"A. {normalize_space(a)}")
    return "\n".join(lines).strip()


def _build_expansion_sections(title: str, profile: str, keywords: list[str], points: list[str]) -> list[str]:
    keyword_a = keywords[0] if keywords else "핵심 조건"
    keyword_b = keywords[1] if len(keywords) > 1 else "실행 순서"
    point = points[0] if points else f"{title}에서 가장 중요한 조건을 먼저 확인하세요."
    focus = PROFILE_TEXT[profile]["focus"]

    return [
        "\n\n".join(
            [
                "## 의사결정 메모 템플릿",
                f"- 오늘 확인한 핵심 신호: {keyword_a}",
                f"- 오늘 미룬 항목과 이유: {keyword_b}",
                "- 바로 실행할 1단계: 실행 시간 20분 이내로 제한",
                "- 실행 후 검증 항목: 수치 1개 + 체감 1개",
                "메모를 남기면 다음 판단이 빨라집니다. 특히 같은 주제를 반복 다루는 경우, "
                "실패 패턴과 성공 패턴이 누적되어 의사결정 품질이 안정적으로 올라갑니다.",
                "또한 팀 단위로 공유되는 주제라면, 개인 메모 형식을 통일해야 인수인계가 쉬워집니다. "
                "메모 포맷이 일정하면 누가 이어받아도 동일한 기준으로 판단할 수 있어 콘텐츠 품질 편차를 줄일 수 있습니다.",
            ]
        ).strip(),
        "\n\n".join(
            [
                "## 놓치기 쉬운 변수와 대응",
                f"{point}",
                f"{focus}를 기준으로 보면, 눈에 띄는 지표보다 실행 조건의 명확성이 더 중요합니다. "
                "조건이 불명확하면 좋은 정보가 있어도 결과가 흔들립니다. "
                "반대로 조건을 고정하면 데이터가 일부 부족해도 안정적인 결정을 유지할 수 있습니다.",
                "특히 마감 시간, 운영 정책, 권한 범위처럼 사소해 보이는 요소가 실제 실패율을 크게 좌우합니다. "
                "본문의 체크리스트를 실행 전에 먼저 통과시키면, 동일한 실수를 반복할 가능성을 현저히 줄일 수 있습니다.",
            ]
        ).strip(),
        "\n\n".join(
            [
                "## 내일 결과를 판단하는 기준",
                "내일은 결과 자체보다 결정 품질이 개선됐는지 먼저 보세요. "
                "체크리스트를 지켰는지, 리스크를 사전에 줄였는지, 실행 후 기록을 남겼는지가 핵심입니다.",
                "이 세 가지가 유지되면 단기 성과 변동이 있더라도 장기적으로 시행착오 비용이 줄어듭니다.",
                "좋은 결과라도 우연일 수 있고, 나쁜 결과라도 올바른 프로세스 위에서 나온 값이면 다음 시도에서 개선 가능합니다. "
                "그래서 결과 점검은 숫자와 과정 기록을 함께 보는 방식으로 운영해야 합니다.",
            ]
        ).strip(),
        "\n\n".join(
            [
                "## 재현 가능한 운영 루틴 만들기",
                "한 번 잘된 글보다 매번 일정 품질을 내는 운영이 더 중요합니다. "
                "주제 선정, 구조 작성, 메타 최적화, 검증, 배포를 같은 순서로 반복하면 품질이 안정됩니다.",
                "루틴은 복잡할 필요가 없습니다. 시작 전 5분 점검, 작성 후 10분 검증, 배포 전 최종 확인의 세 단계만 고정해도 "
                "CTR과 체류 시간 같은 핵심 지표의 변동 폭을 줄일 수 있습니다.",
                "이 방식은 단기 속도를 약간 희생하더라도 장기 누적 성과를 높여줍니다.",
            ]
        ).strip(),
        "\n\n".join(
            [
                "## 우선순위 충돌이 날 때 결정하는 법",
                f"{keyword_a}와 {keyword_b}가 충돌할 때는 영향도와 복구 비용을 기준으로 우선순위를 정하세요. "
                "영향도는 사용자 체감, 복구 비용은 시간과 리스크로 계산하면 됩니다.",
                "이 기준을 쓰면 감정이나 선호보다 결과 중심으로 의사결정을 할 수 있습니다. "
                "또한 결정 근거를 문장으로 남기면 다음 주제에서 같은 논쟁을 반복하지 않게 됩니다.",
                "실무에서는 완벽한 선택보다 손실을 통제 가능한 선택이 더 높은 성과를 만듭니다.",
            ]
        ).strip(),
        "\n\n".join(
            [
                "## 롤백 기준과 재시도 조건",
                "모든 실행에는 실패 가능성이 있으므로 롤백 기준을 먼저 정해두어야 합니다. "
                "예를 들어 핵심 지표가 특정 임계치 아래로 떨어지면 즉시 원복하고 원인 로그를 남기는 식입니다.",
                "재시도는 같은 방식으로 반복하지 말고, 변경 변수 하나만 바꿔 테스트하세요. "
                "변수를 하나씩 바꿔야 개선 효과를 정확히 측정할 수 있습니다.",
                "이 방식은 단기 성과보다 장기 운영 안정성에 강하며, 팀 협업 환경에서 특히 효과적입니다.",
            ]
        ).strip(),
    ]


def generate_markdown(
    *,
    title: str,
    category: str,
    excerpt: str,
    tags: list[str],
    asset_urls: list[str],
    source_headings: list[str],
    source_points: list[str],
) -> str:
    title_clean = _strip_trailing_punct(title) or title
    profile = _pick_profile(category)
    profile_cfg = PROFILE_TEXT[profile]
    keywords = _extract_keywords(title, tags, source_headings)
    keyword_a = keywords[0] if keywords else "핵심 조건"
    keyword_b = keywords[1] if len(keywords) > 1 else "우선순위"
    keyword_c = keywords[2] if len(keywords) > 2 else "실행 순서"

    source_a = source_points[0] if source_points else f"{title} 관련 자료에서 핵심 조건을 먼저 확인하세요."
    source_b = source_points[1] if len(source_points) > 1 else "단일 신호만으로 결론을 내리기보다 보조 지표를 교차 검증해야 합니다."
    source_c = source_points[2] if len(source_points) > 2 else "실행 전에 리스크 한도를 문장으로 정해두면 감정 개입을 줄일 수 있습니다."
    heading_a = source_headings[0] if source_headings else f"{keyword_a}의 의미"
    heading_b = source_headings[1] if len(source_headings) > 1 else f"{keyword_b}에서 갈리는 선택"

    checklist_lines = [
        f"- {profile_cfg['risk'][0]} 여부를 시작 전에 확인",
        f"- {profile_cfg['risk'][1]}를 체크리스트 항목으로 고정",
        f"- {profile_cfg['risk'][2]}를 막기 위한 리뷰 루틴 설정",
        "- 실행 후 10분 안에 결과 메모 작성",
    ]
    metric_line = ", ".join(profile_cfg["metrics"])

    sections: list[str] = [
        f"# {title}",
        excerpt,
        "\n".join(
            [
                "## 이 글에서 바로 가져갈 것",
                f"'{normalize_space(title_clean)}' 주제를 다룰 때 가장 중요한 기준은 {profile_cfg['focus']}입니다. "
                "아래 구조는 정보 요약이 아니라 실행 우선순위를 정하기 위한 프레임입니다.",
                f"- 먼저 볼 것: {keyword_a}",
                f"- 다음으로 볼 것: {keyword_b}",
                f"- 마지막으로 확정할 것: {keyword_c}",
            ]
        ),
        "\n".join(
            [
                "## 상황 진단: 지금 어디서 판단이 갈리는가",
                f"### {heading_a}",
                f"{source_a}",
                "같은 주제라도 사람마다 결론이 다른 이유는 기준이 다르기 때문입니다. "
                "조건, 데이터, 실행 시점을 분리해 보면 과장된 해석을 줄이고 판단 일관성을 높일 수 있습니다.",
                f"### {heading_b}",
                f"{source_b}",
                "핵심은 단일 근거로 단정하지 않는 것입니다. 보조 근거를 최소 2개 이상 붙이면 "
                "과잉 확신과 과도한 보수성을 동시에 줄일 수 있습니다.",
            ]
        ),
        "\n".join(
            [
                "## 실행 전략: 우선순위 3단계",
                "### 1단계: 조건 고정",
                f"{keyword_a}와 관련된 조건을 문장으로 먼저 고정하세요. 조건이 없으면 정보가 많아도 실행이 흔들립니다.",
                "### 2단계: 범위 축소",
                "한 번에 모든 항목을 바꾸지 말고 영향도가 큰 20%부터 적용하세요. "
                "작은 범위에서 검증한 뒤 확장하면 실패 비용이 낮아집니다.",
                "### 3단계: 결과 기록",
                "실행 후 결과를 숫자 1개와 메모 1개로 남기세요. 기록이 쌓이면 다음 결정 속도와 정확도가 함께 올라갑니다.",
            ]
        ),
        "\n".join(
            [
                "## 리스크를 줄이는 운영 규칙",
                source_c,
                "대부분의 문제는 정보 부족보다 규칙 부재에서 시작됩니다. "
                "실행 전 기준, 실행 중 점검, 실행 후 회고를 분리하면 예외 상황에서도 흔들림이 줄어듭니다.",
                *checklist_lines,
            ]
        ),
        "\n".join(
            [
                "## 7일 액션 플랜",
                "1일차: 목표와 금지 조건 정의",
                "2~3일차: 핵심 지표 점검 및 소규모 실행",
                "4~5일차: 결과 수집, 실패 원인 분리",
                "6일차: 루틴 수정, 자동화 가능 항목 정리",
                "7일차: 다음 주 계획 확정",
                "이 루틴은 성과를 빠르게 만드는 데 목적이 있습니다. "
                "복잡한 계획보다 짧은 검증 주기를 유지하는 것이 CTR/SEO 운영에서도 더 높은 재현성을 만듭니다.",
            ]
        ),
        "\n".join(
            [
                "## 성과 판정 지표",
                f"이 주제에서는 {metric_line}를 기본 지표로 사용하세요.",
                "지표는 완벽한 예측 도구가 아니라 방향 확인 장치입니다. "
                "숫자와 메모를 함께 남기면, 단기 변동이 있어도 다음 행동의 품질을 안정적으로 높일 수 있습니다.",
            ]
        ),
        "\n".join(
            [
                "## 실행 전 준비물과 권한 점검",
                "좋은 전략도 준비가 누락되면 현장에서 멈춥니다. 시작 전에 필요한 도구, 접근 권한, "
                "검증 경로를 먼저 확정해야 실행 중 중단을 줄일 수 있습니다.",
                "- 필수 자료: 최신 기준 문서, 직전 실행 로그, 비교할 기준값",
                "- 필수 권한: 수정 권한, 검수 권한, 배포/게시 권한",
                "- 필수 정책: 금지 표현, 검증 책임자, 롤백 조건",
                "이 세 가지를 선행 점검하면 같은 실수를 반복하는 빈도가 크게 줄어듭니다.",
            ]
        ),
        "\n".join(
            [
                "## 실패 신호를 조기에 발견하는 방법",
                "실패는 갑자기 발생하지 않고 초기 신호를 남깁니다. "
                "예를 들어 검증 기록이 줄어들거나, 수정 횟수는 늘지만 핵심 지표가 개선되지 않는다면 즉시 원인 분리가 필요합니다.",
                "초기 신호를 발견했을 때는 범위를 줄이고, 한 번에 하나의 변수만 바꿔 다시 측정하세요. "
                "무리하게 여러 항목을 동시에 수정하면 원인 추적이 어려워져 품질 회복 시간이 길어집니다.",
                "따라서 조기 경보 기준을 미리 정해두는 것이 운영 안정성의 핵심입니다.",
            ]
        ),
        "\n".join(
            [
                "## 한 줄 결론과 다음 행동",
                f"결론적으로 '{title_clean}' 주제에서 중요한 것은 복잡한 정보량이 아니라 실행 가능한 기준을 먼저 고정하는 것입니다. "
                "오늘은 한 단계만 실행하고, 내일 같은 기준으로 다시 측정하세요.",
                "이 방식은 단기간에 극적인 변화보다 안정적인 개선을 만듭니다. "
                "결정 품질을 꾸준히 높이면 CTR, 체류시간, 재방문 같은 결과 지표도 함께 따라옵니다.",
            ]
        ),
    ]

    asset_block = _render_asset_block(title, asset_urls)
    if asset_block:
        sections.append(asset_block)

    sections.append(_render_faq(title, profile, keywords))
    body = "\n\n".join(section.strip() for section in sections if section and section.strip()).strip()

    expansions = _build_expansion_sections(title, profile, keywords, source_points)
    compact_len = len(_compact_plain_text(body))
    idx = 0
    while compact_len < 3000 and idx < len(expansions):
        body = f"{body}\n\n{expansions[idx]}".strip()
        idx += 1
        compact_len = len(_compact_plain_text(body))
    return body


def _validate(markdown: str, excerpt: str, meta: str, tags: list[str]) -> tuple[bool, str]:
    if _has_blocked_heading(markdown):
        return False, "blocked_heading"

    compact_len = len(_compact_plain_text(markdown))
    if compact_len < 3000:
        return False, f"body_too_short_no_ws:{compact_len}"

    h2, h3 = _count_headings(markdown)
    if h2 < 5:
        return False, f"insufficient_h2:{h2}"
    if h3 < 2:
        return False, f"insufficient_h3:{h3}"

    faq_q = _count_faq_questions(markdown)
    if faq_q < 3:
        return False, f"faq_too_short:{faq_q}"

    excerpt_len = len(normalize_space(excerpt))
    if excerpt_len < 60:
        return False, f"excerpt_too_short:{excerpt_len}"

    meta_len = len(normalize_space(meta))
    if not (120 <= meta_len <= 160):
        return False, f"meta_len_out_of_range:{meta_len}"

    if len(tags) < 5:
        return False, f"tags_too_few:{len(tags)}"
    if len(tags) > 8:
        return False, f"tags_too_many:{len(tags)}"
    return True, "ok"


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    package_root = (REWRITE_PACKAGE_ROOT / args.package_date).resolve()
    metadata_path = package_root / "package-metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"package-metadata.json not found: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    kind = normalize_space(str(metadata.get("kind") or ""))
    if kind != "cloudflare-range-rewrite":
        raise ValueError(f"Unsupported package kind: {kind or '<empty>'} (expected cloudflare-range-rewrite)")

    manifest_path = package_root / "dongri-archive" / "manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.csv not found: {manifest_path}")

    raw_rows = read_csv_utf8(manifest_path)
    rows: list[dict[str, str]] = []
    for row in raw_rows:
        cleaned: dict[str, str] = {}
        for key, value in row.items():
            normalized_key = normalize_space((key or "").lstrip("\ufeff"))
            if not normalized_key:
                continue
            if normalized_key in cleaned and normalize_space(cleaned.get(normalized_key)):
                continue
            cleaned[normalized_key] = value
        rows.append(cleaned)
    if not rows:
        raise ValueError("manifest.csv has no rows.")

    results: list[RewriteResult] = []
    updated_rows: list[dict[str, Any]] = []
    stats: dict[str, int] = {"ok": 0, "failed": 0}

    for row in rows:
        slug = normalize_space(row.get("source_slug"))
        markdown_path = normalize_space(row.get("markdown_path"))
        snapshot_path = normalize_space(row.get("snapshot_json_path"))
        if not slug or not markdown_path or not snapshot_path:
            results.append(
                RewriteResult(
                    slug=slug or "<missing>",
                    status="failed",
                    reason="missing_paths",
                    markdown_path=markdown_path,
                )
            )
            stats["failed"] += 1
            updated_rows.append(row)
            continue

        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        snapshot_content = str(snapshot.get("content") or "")
        source_headings, source_points = _extract_source_material(snapshot_content)
        asset_urls = collect_markdown_asset_refs(snapshot_content)

        category = normalize_space(row.get("target_category") or row.get("current_category") or "동그리 아카이브")
        title = normalize_space(row.get("new_title") or row.get("current_title") or slug)
        profile = _pick_profile(category)
        seed_tags = parse_tag_string(row.get("tags") or "")
        keywords = _extract_keywords(title, seed_tags, source_headings)

        excerpt = _finalize_excerpt(title, row.get("new_excerpt") or row.get("current_excerpt") or "", category)
        tags = _finalize_tags(category, row.get("tags") or "", keywords, profile)
        meta = _finalize_meta(title, row.get("new_seo_description") or row.get("current_seo_description") or "", category)
        markdown = generate_markdown(
            title=title,
            category=category,
            excerpt=excerpt,
            tags=tags,
            asset_urls=asset_urls,
            source_headings=source_headings,
            source_points=source_points,
        )

        ok, reason = _validate(markdown, excerpt, meta, tags)
        if not ok:
            results.append(RewriteResult(slug=slug, status="failed", reason=reason, markdown_path=markdown_path))
            stats["failed"] += 1
            updated_rows.append(row)
            continue

        if args.apply:
            write_text_utf8(Path(markdown_path), markdown + "\n")

        row["review_status"] = "approved" if args.apply else (row.get("review_status") or "draft")
        row["new_title"] = title
        row["new_excerpt"] = excerpt
        row["new_seo_title"] = title
        row["new_seo_description"] = meta
        row["tags"] = "|".join(tags)
        updated_rows.append(row)

        results.append(RewriteResult(slug=slug, status="ok", reason="generated", markdown_path=markdown_path))
        stats["ok"] += 1

    report_path = package_root / f"autofill-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    write_json(
        report_path,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "package_date": args.package_date,
            "package_kind": kind,
            "mode": "apply" if args.apply else "dry-run",
            "stats": stats,
            "results": [r.__dict__ for r in results],
        },
    )

    if args.apply:
        write_csv_utf8(manifest_path, updated_rows, CANONICAL_MANIFEST_FIELDS)

    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "package_root": str(package_root),
                "target_count": len(rows),
                "stats": stats,
                "report": str(report_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
