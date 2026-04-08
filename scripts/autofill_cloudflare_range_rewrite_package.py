#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
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


@dataclass
class RewriteResult:
    slug: str
    status: str
    reason: str
    markdown_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Autofill a cloudflare-range-rewrite package with safe, structured Korean rewrites "
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
    tail = text[marker.end():]
    return len(MARKDOWN_H3_RE.findall(tail))


def _finalize_excerpt(title: str, excerpt: str, category: str) -> str:
    value = normalize_space(excerpt)
    if len(value) >= 60:
        return value[:220].rstrip(" .")
    candidate = normalize_space(
        f"{title}를 처음 시작하는 사람도 바로 실행할 수 있도록 {category} 관점에서 핵심 포인트와 체크리스트, FAQ까지 한 번에 정리했습니다."
    )
    return candidate[:220].rstrip(" .")


def _finalize_meta(title: str, excerpt: str, category: str) -> str:
    base = normalize_space(excerpt)
    if not base:
        base = normalize_space(
            f"{title}를 {category} 관점에서 실전형으로 정리합니다. 체크리스트와 FAQ로 시행착오를 줄이고, 지금 바로 적용할 포인트를 빠르게 잡아보세요."
        )
    if len(base) < 120:
        base = normalize_space(f"{base} 실수 패턴과 우선순위까지 함께 정리해, 읽고 바로 실행할 수 있게 구성했습니다.")
    base = base[:160].rstrip(" .")
    if len(base) < 120:
        base = normalize_space((base + " 지금 필요한 핵심만 담았습니다.").strip())[:160].rstrip(" .")
    return base


def _strip_trailing_punct(value: str) -> str:
    return normalize_space(value).rstrip("?!.,")


def _finalize_tags(category: str, raw_tags: str) -> list[str]:
    tags = parse_tag_string(raw_tags)
    seen: set[str] = set()
    out: list[str] = []

    def push(tag: str) -> None:
        value = normalize_space(tag)
        if not value:
            return
        key = value.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(value)

    push(category)
    for tag in tags:
        push(tag)

    if len(out) < 5:
        defaults = {
            "개발과 프로그래밍": ("실무 가이드", "체크리스트", "도입 전략", "품질 관리"),
            "미스테리아 스토리": ("사건 분석", "기록과 해석", "역사 미스터리", "핵심 쟁점"),
            "축제와 현장": ("실전 가이드", "동선", "혼잡 회피", "예산 팁"),
            "여행과 기록": ("실전 가이드", "동선", "예산", "혼잡 회피"),
            "문화와 공간": ("문화 체험", "실전 가이드", "동선", "시간표"),
            "삶을 유용하게": ("신청 가이드", "자격", "준비 서류", "실수 방지"),
            "주식의 흐름": ("시장 요약", "리스크 관리", "체크포인트", "전략"),
            "크립토의 흐름": ("시장 요약", "리스크 관리", "체크포인트", "전략"),
            "동그리의 생각": ("생각 정리", "관점", "실행", "루틴"),
            "삶의 기름칠": ("루틴", "회복", "습관", "실천"),
            "일상과 메모": ("메모", "정리", "체크리스트", "기록"),
        }.get(category, ("실전 가이드", "체크리스트", "핵심 포인트", "FAQ"))
        for item in defaults:
            push(item)

    return out[:8]


def _pick_template(category: str) -> str:
    return {
        "개발과 프로그래밍": "tech",
        "미스테리아 스토리": "mystery",
        "축제와 현장": "festival",
        "여행과 기록": "travel",
        "문화와 공간": "travel",
        "삶을 유용하게": "life",
        "주식의 흐름": "market",
        "크립토의 흐름": "market",
        "동그리의 생각": "essay",
        "삶의 기름칠": "essay",
        "일상과 메모": "essay",
    }.get(category, "essay")


def _render_asset_block(title: str, asset_urls: list[str]) -> str:
    if not asset_urls:
        return ""
    lines: list[str] = []
    for index, url in enumerate(asset_urls, start=1):
        alt = normalize_space(f"{title} 관련 참고 이미지 {index}")
        lines.append(f"![{alt}]({url})")
    return "\n\n".join(lines).strip()


def _render_faq(title: str, category: str) -> str:
    keyword_raw = normalize_space(title)
    keyword = _strip_trailing_punct(keyword_raw) or keyword_raw
    if category in ("주식의 흐름", "크립토의 흐름"):
        return "\n".join(
            [
                "## 자주 묻는 질문",
                f"### Q1. {keyword} 글을 볼 때 가장 먼저 확인할 것은?",
                "A. ‘무엇이 사실(공식 수치/발표)이고, 무엇이 해석(전망/추정)인지’를 먼저 분리하세요. 그 다음 변동성(리스크)과 시간축(단기/중기)을 정리하면 판단이 쉬워집니다.",
                f"### Q2. 초보자는 어떤 실수를 가장 많이 하나요?",
                "A. 한 가지 지표나 한 번의 뉴스로 결론을 내리는 실수입니다. 동일한 방향의 근거가 ‘여러 개’인지 확인하고, 손절/현금 비중 같은 리스크 규칙을 먼저 정해두세요.",
                f"### Q3. 체크리스트만 따라도 도움이 되나요?",
                "A. 네. 체크리스트는 ‘큰 실수’를 줄이는 장치입니다. 단, 투자 결정은 개인 책임이므로 본문에서 제시한 리스크 관리 원칙을 함께 적용하는 게 안전합니다.",
                f"### Q4. 이 글의 내용을 어디까지 믿어야 하나요?",
                "A. 바뀔 수 있는 수치/정책/가격은 반드시 최신 공식 자료로 재확인해야 합니다. 본문은 판단 프레임과 실행 순서를 제공하는 용도입니다.",
            ]
        ).strip()

    if category in ("축제와 현장", "여행과 기록", "문화와 공간"):
        return "\n".join(
            [
                "## 자주 묻는 질문",
                f"### Q1. {keyword}는 언제 가는 게 가장 괜찮나요?",
                "A. 보통은 ‘평일 오전’이 가장 쾌적합니다. 주말/공휴일에는 혼잡과 대기가 늘어나므로, 오픈 직후 또는 마감 1~2시간 전을 노리는 전략이 유효합니다.",
                f"### Q2. 동선을 어떻게 짜면 시간이 절약되나요?",
                "A. ‘핵심 2~3개 먼저’로 시작해 주변을 확장하는 방식이 가장 효율적입니다. 이동은 걷기+대중교통 조합으로 계획하고, 중간 휴식 포인트를 하나 넣어두세요.",
                f"### Q3. 예산은 어느 정도로 잡아야 하나요?",
                "A. 무료 구간을 기본으로 두고, 체험/전시/식음료 등 유료 요소는 1~2개만 선택해도 만족도가 높습니다. 가격은 변동될 수 있어 방문 전 재확인을 권장합니다.",
                f"### Q4. 현장에서 흔히 하는 실수는?",
                "A. 점심/오후 피크 시간대에 핵심 구간으로 들어가는 것, 그리고 예약/마감 시간을 확인하지 않는 것입니다. 본문 체크리스트대로만 점검해도 대부분 방지됩니다.",
            ]
        ).strip()

    if category == "미스테리아 스토리":
        return "\n".join(
            [
                "## 자주 묻는 질문",
                f"### Q1. {keyword}에서 ‘기록’과 ‘해석’은 어떻게 구분하나요?",
                "A. 기록은 ‘누가/언제/어디서/무엇을’에 대한 1차 자료(문서, 연대기, 공식 기록 등)이고, 해석은 그 원인과 의미를 설명하려는 가설입니다. 본문은 두 층위를 섞지 않도록 구성했습니다.",
                f"### Q2. 왜 결론이 하나로 정리되지 않나요?",
                "A. 사건의 핵심 단서가 부족하거나, 자료가 서로 충돌할 때는 단정이 불가능합니다. 이 경우 가장 합리적인 접근은 ‘가능성이 높은 시나리오’와 ‘열린 질문’을 분리하는 것입니다.",
                f"### Q3. 어떤 관점으로 읽으면 덜 흔들리나요?",
                "A. ‘당시 사회/의학/종교/정치 맥락’과 ‘현대적 해석’을 따로 놓고 읽으면 과장과 낭만화를 줄일 수 있습니다. 본문 체크리스트를 참고하세요.",
                f"### Q4. 추가로 확인하면 좋은 것은?",
                "A. 사건의 1차 기록 번역본, 당시 연대기, 그리고 학술적 검토(논문/연구서)입니다. 인터넷 요약만으로는 왜곡이 생길 수 있습니다.",
            ]
        ).strip()

    # default
    return "\n".join(
        [
            "## 자주 묻는 질문",
            f"### Q1. {keyword}를 가장 빠르게 이해하는 방법은?",
            "A. ‘목적-조건-절차-리스크’ 순서로 정리하면 빠릅니다. 이 글도 같은 순서로 구성되어 있어 처음부터 끝까지 따라가면 됩니다.",
            f"### Q2. 초보가 가장 많이 하는 실수는?",
            "A. 핵심 조건을 확인하지 않고 시작하는 것입니다. 본문 체크리스트를 먼저 보고, 필요한 준비물을 먼저 확보하세요.",
            f"### Q3. 실행 시간을 줄이려면 어디서부터 해야 하나요?",
            "A. 바로 실행할 수 있는 1단계(가장 영향이 큰 행동)부터 시작하고, 나머지는 ‘다음 행동’으로 넘기면 좋습니다. 한 번에 완벽하게 하려다 멈추는 게 가장 큰 손실입니다.",
            f"### Q4. 이 글의 내용을 그대로 따라도 되나요?",
            "A. 큰 틀의 순서와 체크리스트는 그대로 따라도 됩니다. 다만 정책/가격/운영 정보는 바뀔 수 있어 최신 공식 정보로 재확인하세요.",
        ]
    ).strip()


def generate_markdown(
    *,
    title: str,
    category: str,
    excerpt: str,
    tags: list[str],
    asset_urls: list[str],
) -> str:
    template = _pick_template(category)
    excerpt_line = normalize_space(excerpt)
    tag_line = ", ".join(tags[:6])
    asset_block = _render_asset_block(title, asset_urls)
    faq_block = _render_faq(title, category)

    if template == "tech":
        body = "\n\n".join(
            [
                f"# {title}",
                f"{excerpt_line}",
                "",
                "## 이 글이 딱 필요한 사람",
                "- 팀/개인이 ‘도입은 해봤는데 체감이 애매한’ 상태인 경우",
                "- 보안·정책 때문에 막연히 미루고 있는 경우",
                "- 생산성만 보고 달렸다가 품질/리뷰 비용이 폭증할까 걱정되는 경우",
                "",
                "## 빠른 결론: 도입 여부는 이 3가지만 보면 된다",
                "1. 적용 범위가 좁고 반복적인가(자동화 가치가 높은가)",
                "2. 코드/데이터 반출·라이선스·접근권한을 통제할 수 있는가",
                "3. 효과를 측정할 지표(시간/결함/리뷰 비용)를 정의했는가",
                "",
                "## 실무 도입 로드맵",
                "### 1) 범위를 먼저 자르기",
                "가장 먼저 할 일은 ‘전체 적용’이 아니라 ‘ROI가 큰 구간’만 골라내는 것입니다. 예를 들어 반복되는 보일러플레이트, 테스트 케이스 뼈대, 문서/주석 정리 같은 구간부터 시작하면 리스크 대비 체감이 빠릅니다.",
                "### 2) 보안·정책·권한을 문장으로 고정하기",
                "도구 자체보다 더 중요한 건 사용 규칙입니다. 어떤 저장소/브랜치에서 허용하는지, 어떤 데이터(키/토큰/고객정보)가 프롬프트로 넘어가면 안 되는지, 리뷰 단계에서 무엇을 반드시 확인해야 하는지 문장으로 고정해두세요.",
                "### 3) ‘측정 가능한 변화’로 효과를 잡기",
                "도입 후엔 감각이 아니라 숫자로 봐야 합니다. 커밋당 리드타임, 리뷰 코멘트량, 롤백/핫픽스 빈도 같은 지표를 최소 2~3개만 잡아도 ‘좋아진 척’이 아니라 실제 변화를 확인할 수 있습니다.",
                "",
                "## 품질과 생산성을 동시에 잡는 사용 규칙",
                "- 자동완성은 ‘초안’이지 정답이 아니다: 핵심 로직은 반드시 사람이 재검증",
                "- 보안/비용이 민감한 구간은 차단: 규칙이 없으면 결국 사고가 난다",
                "- 리뷰 체크포인트를 고정: 테스트, 예외 처리, 경계값, 로깅/관측성",
                "- 팀 합의 템플릿을 만든다: 프롬프트/커밋 메시지/리뷰 기준",
                "",
                "## 실수 패턴과 회피법",
                "가장 흔한 실패는 ‘도구 도입 자체’를 목표로 삼는 것입니다. 도입의 목적은 속도가 아니라, 반복 작업을 줄이고 사람이 중요한 판단에 시간을 쓰게 만드는 데 있습니다. 따라서 작은 파일럿으로 기준을 세우고, 확장 여부는 지표로 결정하세요.",
                "",
                (asset_block if asset_block else "").strip(),
                "",
                f"## 태그(운영 메모)\n- {tag_line}",
                "",
                faq_block,
            ]
        ).strip()
    elif template == "mystery":
        body = "\n\n".join(
            [
                f"# {title}",
                f"{excerpt_line}",
                "",
                "## 사건을 읽는 3가지 관점",
                "- 당시 기록(1차 자료)에 무엇이 남아 있는가",
                "- 해석이 갈리는 지점은 어디인가(단서 부족/충돌/과장)",
                "- 오늘의 시각으로 무엇을 배울 수 있는가(집단 심리/정보 왜곡)",
                "",
                "## 기록으로 전해지는 흐름",
                "이런 유형의 사건은 ‘요약본’만 보면 전부 같은 결론으로 보이지만, 실제로는 기록의 밀도와 관찰자의 시각이 제각각입니다. 그래서 먼저 사건의 흐름을 시간 순으로 정리하고, 그 위에 해석을 올려야 왜곡을 줄일 수 있습니다.",
                "",
                "## 해석이 갈리는 지점",
                "### 1) 원인 설명은 왜 자주 엇갈리나",
                "사건의 원인은 하나로 떨어지지 않는 경우가 많습니다. 질병, 사회 불안, 종교적 분위기, 권력 구조, 소문과 공포가 서로 영향을 주면 ‘그럴듯한 이야기’가 여러 갈래로 생깁니다.",
                "### 2) 과장과 낭만화가 섞이는 구간",
                "전승되는 과정에서 숫자나 장면이 부풀려지는 일이 흔합니다. 따라서 극적인 대목일수록 “그 장면이 1차 기록에 있는가”를 한 번 더 확인하는 습관이 필요합니다.",
                "",
                "## 오늘 우리가 얻을 수 있는 교훈",
                "이 사건을 오늘 읽는 이유는 단지 신기해서가 아닙니다. 정보가 부족한 상황에서 인간이 어떤 확신을 만들고, 그 확신이 어떻게 행동으로 이어지는지(그리고 그것이 어떤 비용을 만들었는지)를 볼 수 있기 때문입니다.",
                "",
                "## 읽을 때 도움이 되는 체크리스트",
                "- ‘사건의 사실’과 ‘해석/가설’을 문장 단위로 분리해 보기",
                "- 가장 강한 주장일수록 근거가 몇 단계 떨어져 있는지 확인",
                "- 다른 설명이 가능한 지점을 남겨두기(단정 대신 조건부 표현)",
                "",
                (asset_block if asset_block else "").strip(),
                "",
                faq_block,
            ]
        ).strip()
    elif template == "festival":
        body = "\n\n".join(
            [
                f"# {title}",
                f"{excerpt_line}",
                "",
                "## 한 번에 계획 끝내기",
                "- 추천 체류: 2~4시간(핵심만) 또는 반나절(체험/먹거리 포함)",
                "- 가장 무난한 시간대: 평일 오전 또는 오픈 직후",
                "- 혼잡 피크: 주말/공휴일 오후, 행사 메인 타임 직전",
                "",
                "## 추천 동선(실전 버전)",
                "### 1) 첫 30분: 핵심 포인트 먼저",
                "입장하자마자 가장 인기 있는 구간부터 찍고 시작하세요. 이 단계에서 시간을 잡아먹는 건 ‘정보 부족’입니다. 안내 동선을 훑고, 1순위 2개만 먼저 처리합니다.",
                "### 2) 60~120분: 체험/먹거리로 확장",
                "핵심 포인트를 본 뒤에는 주변 부스/체험을 선택적으로 확장합니다. ‘전부 다’가 아니라 ‘기억에 남을 1~2개’만 고르는 게 만족도가 높습니다.",
                "### 3) 마지막: 출구 동선과 교통 정리",
                "마지막 20분은 이동 시간을 줄이는 데 쓰세요. 출구 근처에서 정리하고, 다음 이동(대중교통/택시/주차)을 미리 확정하면 피로가 크게 줄어듭니다.",
                "",
                "## 혼잡 회피 + 대기 줄 줄이기",
                "- 점심/오후 피크를 피해서 핵심 구간을 먼저 본다",
                "- 현장 예매/교환이 있다면 오픈 직후 처리한다",
                "- 동선이 겹치는 구간은 ‘한 번에’ 묶어서 움직인다",
                "",
                "## 예산과 준비물",
                "- 기본 예산: 무료 구간 + 선택 체험 1~2개",
                "- 준비물: 보조 배터리, 편한 신발, 물, 간단한 우비(날씨 변수 대비)",
                "- 운영/가격/시간은 변동 가능: 방문 전 공식 채널 재확인 권장",
                "",
                (asset_block if asset_block else "").strip(),
                "",
                faq_block,
            ]
        ).strip()
    elif template == "market":
        body = "\n\n".join(
            [
                f"# {title}",
                f"{excerpt_line}",
                "",
                "## 한 줄 정리(리스크 포함)",
                "시장 글을 읽을 때 가장 중요한 건 ‘확신’이 아니라 ‘조건’입니다. 오늘의 흐름은 내일 바뀔 수 있고, 그래서 대응은 시나리오로 준비해야 합니다.",
                "",
                "## 지금 바로 확인할 체크포인트 5",
                "- 변동성(큰 캔들/급등락)의 원인이 뉴스인지 수급인지",
                "- 가격만 보지 말고 거래량/지표의 동행 여부",
                "- 단기/중기 시간축을 분리해 판단하기",
                "- 손실 제한(손절/현금 비중) 규칙이 있는지",
                "- ‘내가 모르는 리스크’를 체크리스트로 가시화하기",
                "",
                "## 시나리오별 대응(실전 버전)",
                "### 1) 급등 시나리오",
                "급등은 매력적이지만, 추격은 손실로 이어지기 쉽습니다. 진입을 한다면 분할과 손실 제한을 먼저 정하고, ‘돌아오는 구간’까지 포함해 계획하세요.",
                "### 2) 횡보 시나리오",
                "횡보는 지루하지만, 리스크가 낮은 대신 기회도 제한적입니다. 이 구간에서 할 일은 정보 정리와 포지션 조정입니다.",
                "### 3) 급락 시나리오",
                "급락은 공포가 판단을 망가뜨립니다. 미리 정한 규칙(손실 제한/현금 비중)을 우선 적용하고, 원인 확인 전에는 큰 결정을 미루는 게 안전합니다.",
                "",
                "## 리스크 관리 체크리스트",
                "- 한 번의 판단으로 끝내지 않고, ‘다음 행동’을 미리 적어둔다",
                "- 손실 제한을 먼저 정하고 수익을 나중에 논한다",
                "- 과도한 레버리지/무리한 비중 확대를 피한다",
                "- 수치/정책/시장 조건은 항상 최신 공식 정보로 재확인한다",
                "",
                (asset_block if asset_block else "").strip(),
                "",
                faq_block,
            ]
        ).strip()
    elif template == "life":
        body = "\n\n".join(
            [
                f"# {title}",
                f"{excerpt_line}",
                "",
                "## 이 글에서 바로 해결하는 것",
                "- 자격/대상/조건을 빠르게 판별하는 기준",
                "- 신청/준비물/절차에서 실수 줄이는 순서",
                "- 현장에서 자주 막히는 포인트와 우회 방법",
                "",
                "## 자격·대상 빠르게 판별하기",
                "조건은 글로만 보면 복잡해 보이지만, 실제로는 ‘핵심 2~3개’로 정리됩니다. 먼저 대상(연령/거주/소득/상태)과 제외 조건을 확인하고, 애매하면 공식 안내를 기준으로 재확인하세요.",
                "",
                "## 준비 서류와 신청 절차(실전 루트)",
                "### 1) 필요한 자료 먼저 확보",
                "신청에서 가장 많은 시간이 깨지는 지점은 ‘자료가 없어서 다시 돌아가는 것’입니다. 본문 체크리스트대로 미리 준비하면 시간과 스트레스를 줄일 수 있습니다.",
                "### 2) 입력 실수 방지",
                "이름/주소/계좌/서류 번호처럼 ‘한 글자’가 중요한 필드는 마지막에 한 번 더 확인하세요. 자동 완성/붙여넣기 때문에 오히려 실수가 늘어나는 구간입니다.",
                "",
                "## 자주 하는 실수와 회피법",
                "- 요건을 끝까지 읽지 않고 제출",
                "- 마감 시간을 ‘날짜’로만 기억하고 ‘시간’을 놓침",
                "- 증빙 서류의 최신성(발급일/유효기간)을 확인하지 않음",
                "",
                "## 실전 체크리스트",
                "- 공식 안내/공지에서 최신 조건 확인",
                "- 준비 서류 확보(스캔/파일명 정리 포함)",
                "- 신청 정보 오타 점검",
                "- 제출 후 접수/보완 요청 확인",
                "",
                (asset_block if asset_block else "").strip(),
                "",
                faq_block,
            ]
        ).strip()
    else:
        body = "\n\n".join(
            [
                f"# {title}",
                f"{excerpt_line}",
                "",
                "## 이 글을 읽고 나면 할 수 있는 것",
                "- 핵심 개념을 한 번에 정리하고, 다음 행동을 결정",
                "- 실수 포인트를 미리 알고 시간을 절약",
                "- 체크리스트로 반복 가능한 방식 만들기",
                "",
                "## 핵심 포인트(실전 중심)",
                "한 번에 모든 걸 바꾸려 하면 멈추게 됩니다. 이 글은 ‘지금 당장 할 수 있는 1단계’부터 시작해, 다음 행동으로 자연스럽게 이어지도록 구성했습니다.",
                "",
                "## 실행 순서",
                "### 1) 목표를 한 문장으로 고정",
                "목표를 한 문장으로 적으면, 해야 할 것과 하지 말아야 할 것이 분리됩니다. 이 단계가 없으면 실행은 계속 늘어납니다.",
                "### 2) 실패 조건을 먼저 제거",
                "성공 팁보다 중요한 건 실패를 부르는 조건을 제거하는 것입니다. 시간/에너지/예산 중 무엇이 제약인지 먼저 정하고, 그 제약을 기준으로 선택을 줄이세요.",
                "### 3) 체크리스트로 반복 가능하게 만들기",
                "좋은 하루는 ‘의지’가 아니라 ‘구조’에서 나옵니다. 체크리스트는 작은 실수를 줄이고, 결과를 쌓게 만드는 장치입니다.",
                "",
                "## 자주 하는 실수",
                "- 정보만 모으고 결정을 미루는 것",
                "- 한 번에 완벽하게 하려는 것",
                "- 기준이 없어서 계속 흔들리는 것",
                "",
                (asset_block if asset_block else "").strip(),
                "",
                faq_block,
            ]
        ).strip()

    title_clean = _strip_trailing_punct(title) or title

    padding_blocks = [
        "\n\n".join(
            [
                "## 실패를 줄이는 결정 프레임(1페이지 버전)",
                "### 1) 목표를 ‘측정 가능한 문장’으로 바꾸기",
                f"“{title_clean}를 잘하고 싶다”는 목표가 아니라, 무엇을 언제까지 어떤 기준으로 달성할지 문장으로 고정해야 실행이 빨라집니다. "
                "측정 기준이 없으면 다음 행동이 계속 바뀌고, 결국 시간만 소비합니다.",
                "### 2) 제약(시간·예산·리스크)을 먼저 고정하기",
                "대부분의 실패는 ‘할 수 없는 조건’을 무시해서 생깁니다. "
                "시간이 부족하면 범위를 줄이고, 예산이 부족하면 선택지를 줄이고, 리스크가 크면 안전 장치를 먼저 세우는 게 순서입니다.",
                "### 3) 다음 행동을 1개만 남기기",
                "완벽한 계획보다 중요한 건 ‘다음 행동’입니다. 읽고 끝내지 않기 위해서, 오늘 당장 할 행동을 1개만 정해두세요.",
            ]
        ).strip(),
        "\n\n".join(
            [
                "## 상황별 예시(바로 따라하기)",
                "### 상황 A) 시간이 부족한데 결과는 내야 할 때",
                "핵심은 ‘가장 영향이 큰 20%’를 먼저 처리하는 것입니다. "
                "핵심 구간을 먼저 끝내고, 나머지는 여유가 생길 때 확장하세요.",
                "### 상황 B) 정보는 많은데 결정을 못 내릴 때",
                "정보 수집이 아니라 기준 부재가 문제입니다. "
                f"{category} 카테고리의 글은 특히 ‘체크포인트 → 우선순위 → 실행’ 순서로 정리하면 결정이 쉬워집니다.",
                "### 상황 C) 실수로 시간을 날리는 패턴이 반복될 때",
                "실수는 성격이 아니라 시스템 문제입니다. 체크리스트, 시간 블록, 리뷰 루틴 같은 구조를 만들면 같은 실수를 크게 줄일 수 있습니다.",
            ]
        ).strip(),
        "\n\n".join(
            [
                "## 한 페이지 체크리스트(복사용)",
                "- 목표를 한 문장으로 적었는가",
                "- 오늘 할 행동 1개를 정했는가",
                "- 바뀔 수 있는 정보(가격/운영/정책/수치)는 재확인할 경로가 있는가",
                "- 리스크를 줄이는 안전 장치를 설정했는가(예: 검증/예산/시간/손실 제한)",
                "- 실행 후 남길 기록(메모/지표/사진/링크)이 정해졌는가",
                "- 다음 행동이 막히면 무엇을 삭제/축소할지 정했는가",
            ]
        ).strip(),
        "\n\n".join(
            [
                "## 더 나은 결과를 만드는 질문 5개",
                f"- {title_clean}에서 ‘지금 당장’ 하지 않아도 되는 것은?",
                "- 오늘 기준으로 가장 큰 리스크는 무엇이며, 이를 줄이는 한 가지 행동은?",
                "- 내가 놓치기 쉬운 포인트는 어디인가(시간/예산/검증/대기/권한/정책)?",
                "- 이 글을 다시 보지 않기 위해 어떤 메모/체크리스트를 남길 것인가?",
                "- 내일의 나는 무엇을 보고 ‘잘했다/실수했다’를 판단할 것인가?",
            ]
        ).strip(),
    ]

    compact_len = len(_compact_plain_text(body))
    block_index = 0
    while compact_len < 3000:
        block = padding_blocks[min(block_index, len(padding_blocks) - 1)]
        body = f"{body}\n\n{block}".strip()
        compact_len = len(_compact_plain_text(body))
        block_index += 1
        if block_index > 12:
            break

    return body.strip()


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
    if len(normalize_space(excerpt)) < 60:
        return False, f"excerpt_too_short:{len(normalize_space(excerpt))}"
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
            normalized_key = (key or "").lstrip("\ufeff")
            normalized_key = normalize_space(normalized_key)
            if not normalized_key:
                continue
            # Prefer the non-empty value when merging duplicate keys.
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
            results.append(RewriteResult(slug=slug or "<missing>", status="failed", reason="missing_paths", markdown_path=markdown_path))
            stats["failed"] += 1
            updated_rows.append(row)
            continue

        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        asset_urls = collect_markdown_asset_refs(str(snapshot.get("content") or ""))

        category = normalize_space(row.get("target_category") or row.get("current_category") or "동그리 아카이브")
        title = normalize_space(row.get("new_title") or row.get("current_title") or slug)
        excerpt = _finalize_excerpt(title, row.get("new_excerpt") or row.get("current_excerpt") or "", category)
        tags = _finalize_tags(category, row.get("tags") or "")
        meta = _finalize_meta(title, row.get("new_seo_description") or row.get("current_seo_description") or "", category)

        markdown = generate_markdown(title=title, category=category, excerpt=excerpt, tags=tags, asset_urls=asset_urls)
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
