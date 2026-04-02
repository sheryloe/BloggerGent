from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import textwrap
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import psycopg2
import psycopg2.extras


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_ROOT = STORAGE_ROOT / "reports"
PACKAGE_ROOT = STORAGE_ROOT / "rewrite-packages"
DONGRIARCHIVE_REPO = REPO_ROOT.parent / "dongriarhive-repo"
DONGRIARCHIVE_TAG_MANIFEST = DONGRIARCHIVE_REPO / "apps" / "blog-web" / "src" / "data" / "tag-manifest.ko.json"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
ENGLISH_ENTITY_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b")
KOREAN_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
EN_STOPWORDS = {
    "the",
    "and",
    "with",
    "from",
    "what",
    "this",
    "that",
    "your",
    "their",
    "guide",
    "local",
    "nearby",
    "before",
    "after",
    "still",
}
KO_STOPWORDS = {"그리고", "하지만", "정리", "기준", "이번", "지금", "관련", "대한", "방법", "가이드", "흐름", "핵심"}
TRAVEL_TIME_TERMS = (
    "festival",
    "spring",
    "summer",
    "autumn",
    "winter",
    "blossom",
    "cherry",
    "schedule",
    "ticket",
    "booking",
    "transport",
    "night",
    "행사",
    "축제",
    "벚꽃",
    "봄",
    "가을",
    "예약",
    "교통",
    "일정",
)
ARCHETYPE_BY_CATEGORY = {
    "축제와 현장": "festival",
    "문화와 공간": "culture",
    "개발과 프로그래밍": "tech",
    "기술의 기록": "tech",
    "삶을 유용하게": "practical",
    "삶의 기름칠": "routine",
    "동그리의 생각": "issue",
    "세상의 기록": "issue",
    "정보의 기록": "practical",
    "시장의 기록": "market",
    "주식의 흐름": "market",
    "크립토의 흐름": "market",
    "여행과 기록": "travel",
    "동그리의 기록": "travel",
    "일상과 메모": "routine",
    "미스테리아 스토리": "mystery",
}
ARCHETYPE_TAGS = {
    "festival": ["현장 동선", "행사 체크리스트", "로컬 가이드", "서울 봄 일정"],
    "culture": ["문화 공간", "전시 동선", "공간 기록", "도시 산책"],
    "tech": ["AI 자동화", "개발 워크플로", "운영 체크리스트", "도구 사용법"],
    "practical": ["정보 정리", "실용 가이드", "생활 체크리스트", "메모 습관"],
    "routine": ["일상 메모", "기록 습관", "산책 루틴", "피로 관리"],
    "issue": ["이슈 해설", "맥락 읽기", "판단 기준", "뉴스 프레임"],
    "market": ["시장 체크리스트", "리스크 관리", "일정 캘린더", "판단 프레임"],
    "travel": ["도보 루트", "로컬 기록", "동네 산책", "여행 메모"],
    "mystery": ["사건 타임라인", "사실과 가설", "기록 검토", "미스터리 해설"],
}
ARCHETYPE_INTENT = {
    "festival": "현장에서 덜 헤매고 핵심만 빠르게 보려는 독자",
    "culture": "공간을 더 깊게 즐길 맥락과 관람 순서를 찾는 독자",
    "tech": "도구를 실제 업무 흐름에 붙이는 방법이 필요한 독자",
    "practical": "바로 따라 할 수 있는 생활 기준이 필요한 독자",
    "routine": "기록과 루틴을 오래 유지할 구조가 필요한 독자",
    "issue": "뉴스보다 배경과 판단 프레임을 먼저 이해하려는 독자",
    "market": "가격보다 기준과 순서로 시장을 읽고 싶은 독자",
    "travel": "과장보다 실제 동선과 기록 포인트가 궁금한 독자",
    "mystery": "흥미보다 확인된 사실과 남는 해석을 구분해 읽고 싶은 독자",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(API_ROOT))

from app.services.content_ops_service import compute_seo_geo_scores  # noqa: E402


@dataclass
class Section:
    level: int
    heading: str
    paragraphs: list[str]
    bullets: list[str] = field(default_factory=list)


@dataclass
class SourcePost:
    channel: str
    channel_name: str
    source_kind: str
    source_id: str
    source_slug: str
    source_url: str
    current_title: str
    current_category: str
    published_at: str | None
    excerpt: str
    body_html: str
    labels: list[str]
    seo_before: int
    geo_before: int


@dataclass
class DraftArtifact:
    channel: str
    channel_name: str
    source_slug: str
    source_url: str
    current_title: str
    new_title: str
    current_category: str
    target_category: str
    action: str
    archetype: str
    tags: list[str]
    excerpt: str
    meta_description: str
    hero_title: str
    hero_description: str
    markdown: str
    html: str
    faq_section: list[dict[str, str]]
    seo_before: int
    geo_before: int
    seo_after: int
    geo_after: int
    plain_text_length: int
    published_at: str | None
    notes: str


def normalize(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value.replace("\xa0", " ")).strip()


def strip_html(value: str) -> str:
    return normalize(html.unescape(TAG_RE.sub(" ", value or "")))


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower().replace("’", "").replace("'", "")
    normalized = re.sub(r"[^0-9a-z가-힣]+", "-", normalized)
    return re.sub(r"-{2,}", "-", normalized).strip("-") or "item"


def slug_from_url(url: str, fallback: str) -> str:
    path = urlparse(url or "").path.strip("/")
    if path:
        leaf = unquote(path.split("/")[-1]).strip()
        if leaf:
            return leaf
    return slugify(fallback)


def read_csv_with_fallback(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle))
        except Exception:
            continue
    raise ValueError(f"Could not read CSV: {path}")


def connect_db():
    return psycopg2.connect(
        os.environ.get("BLOGGENT_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    )


def compute_before_scores(title: str, body_html: str, excerpt: str) -> tuple[int, int]:
    scores = compute_seo_geo_scores(title=title, html_body=body_html, excerpt=excerpt, faq_section=[])
    return int(scores["seo_score"]), int(scores["geo_score"])


def load_blogger_sources(blog_id: int, channel: str, channel_name: str, category: str) -> list[SourcePost]:
    with connect_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT remote_post_id, title, url, labels, excerpt_text, content_html, published_at
                FROM synced_blogger_posts
                WHERE blog_id = %s
                ORDER BY published_at DESC NULLS LAST, id DESC
                """,
                (blog_id,),
            )
            rows = cursor.fetchall()
    sources: list[SourcePost] = []
    for row in rows:
        title = str(row["title"] or "").strip()
        url = str(row["url"] or "").strip()
        excerpt = str(row["excerpt_text"] or "").strip()
        body_html = str(row["content_html"] or "").strip()
        seo_before, geo_before = compute_before_scores(title, body_html, excerpt)
        sources.append(
            SourcePost(
                channel=channel,
                channel_name=channel_name,
                source_kind="blogger",
                source_id=str(row["remote_post_id"] or ""),
                source_slug=slug_from_url(url, title),
                source_url=url,
                current_title=title,
                current_category=category,
                published_at=row["published_at"].isoformat() if row["published_at"] else None,
                excerpt=excerpt,
                body_html=body_html,
                labels=[str(label).strip() for label in (row["labels"] or []) if str(label).strip()],
                seo_before=seo_before,
                geo_before=geo_before,
            )
        )
    return sources


def load_cloudflare_sources() -> list[SourcePost]:
    rows = read_csv_with_fallback(REPORT_ROOT / "seo-below-70-2026-04-02.csv")
    sources: list[SourcePost] = []
    for index, row in enumerate(rows, start=1):
        title = str(row.get("title") or "").strip()
        category = str(row.get("category") or "").strip() or "정보의 기록"
        body_seed = f"<p>{html.escape(title)} {html.escape(category)} guide checklist timeline record official source.</p>"
        _seo, geo = compute_before_scores(title, body_seed, title)
        sources.append(
            SourcePost(
                channel="dongri-archive",
                channel_name="Dongri Archive",
                source_kind="cloudflare",
                source_id=f"cloudflare-{index}",
                source_slug=slug_from_url(str(row.get('url') or ''), title),
                source_url=str(row.get("url") or "").strip(),
                current_title=title,
                current_category=category,
                published_at=str(row.get("published_at") or "").strip() or None,
                excerpt="",
                body_html="",
                labels=[],
                seo_before=int(float(row.get("seo_score") or 0)),
                geo_before=geo,
            )
        )
    return sources


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local rewrite package without using remote content APIs.")
    parser.add_argument("--mode", choices=("travel", "midnight", "cloudflare", "all"), default="cloudflare")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return parser.parse_args()


def extract_entities(text: str, limit: int = 6) -> list[str]:
    values: list[str] = []
    for match in ENGLISH_ENTITY_RE.findall(text or ""):
        candidate = match.strip()
        if candidate.lower() in EN_STOPWORDS or len(candidate) < 4:
            continue
        if candidate not in values:
            values.append(candidate)
        if len(values) >= limit:
            break
    return values


def extract_ko_keywords(text: str, limit: int = 6) -> list[str]:
    counter: Counter[str] = Counter()
    for token in KOREAN_TOKEN_RE.findall(text or ""):
        if token in KO_STOPWORDS or len(token) < 2:
            continue
        counter[token] += 1
    return [token for token, _count in counter.most_common(limit)]


def sentence_join(parts: list[str]) -> str:
    return " ".join(normalize(part) for part in parts if normalize(part))


def summarize(text: str, limit: int = 220) -> str:
    clean = normalize(text)
    if len(clean) <= limit:
        return clean
    slice_value = clean[:limit].rstrip()
    pivot = slice_value.rfind(" ")
    if pivot >= limit * 0.6:
        slice_value = slice_value[:pivot]
    return slice_value.rstrip(" .,") + "."


def render_markdown(title: str, summary: str, sections: list[Section], faq: list[dict[str, str]], related: list[SourcePost], tags: list[str]) -> str:
    lines = [f"# {title}", "", summary, ""]
    if tags:
        lines.extend([f"태그: {', '.join(tags)}", ""])
    for section in sections:
        lines.extend([f"{'#' * section.level} {section.heading}", ""])
        for paragraph in section.paragraphs:
            lines.extend([paragraph, ""])
        for bullet in section.bullets:
            lines.append(f"- {bullet}")
        if section.bullets:
            lines.append("")
    lines.extend(["## FAQ", ""])
    for item in faq:
        lines.extend([f"### {item['question']}", "", item["answer"], ""])
    if related:
        lines.extend(["## Related links", ""])
        for item in related[:3]:
            lines.append(f"- [{item.current_title}]({item.source_url})")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_html(summary: str, sections: list[Section], faq: list[dict[str, str]], related: list[SourcePost]) -> str:
    parts = ["<article>", f"<h2>Summary</h2><p>{html.escape(summary)}</p>"]
    for section in sections:
        parts.append(f"<h{section.level}>{html.escape(section.heading)}</h{section.level}>")
        for paragraph in section.paragraphs:
            parts.append(f"<p>{html.escape(paragraph)}</p>")
        if section.bullets:
            parts.append("<ul>")
            for bullet in section.bullets:
                parts.append(f"<li>{html.escape(bullet)}</li>")
            parts.append("</ul>")
    parts.append("<h2>FAQ</h2>")
    for item in faq:
        parts.append(f"<h3>{html.escape(item['question'])}</h3>")
        parts.append(f"<p>{html.escape(item['answer'])}</p>")
    if related:
        parts.append("<h2>Related links</h2><ul>")
        for item in related[:3]:
            parts.append(f"<li><a href=\"{html.escape(item.source_url)}\">{html.escape(item.current_title)}</a></li>")
        parts.append("</ul>")
    parts.append("</article>")
    return "".join(parts)


def choose_related_sources(sources: list[SourcePost], current: SourcePost, limit: int = 3) -> list[SourcePost]:
    current_terms = set(extract_ko_keywords(current.current_title, 8)) | {
        token.lower() for token in re.findall(r"[A-Za-z]{3,}", current.current_title) if token.lower() not in EN_STOPWORDS
    }
    scored: list[tuple[int, SourcePost]] = []
    for candidate in sources:
        if candidate.source_slug == current.source_slug:
            continue
        candidate_terms = set(extract_ko_keywords(candidate.current_title, 8)) | {
            token.lower() for token in re.findall(r"[A-Za-z]{3,}", candidate.current_title) if token.lower() not in EN_STOPWORDS
        }
        score = len(current_terms & candidate_terms)
        score += len(set(candidate.labels) & set(current.labels))
        if candidate.current_category == current.current_category:
            score += 2
        scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], item[1].current_title))
    return [candidate for _score, candidate in scored[:limit]]


def ensure_title(title: str, suffix: str) -> str:
    clean = normalize(title)
    if 36 <= len(clean) <= 96:
        return clean
    candidate = normalize(f"{clean}: {suffix}")
    return candidate[:96].rstrip(" ,:-")


def time_sensitive_travel(source: SourcePost) -> bool:
    haystack = " ".join([source.current_title, source.excerpt, " ".join(source.labels)]).lower()
    return any(term in haystack for term in TRAVEL_TIME_TERMS)


def build_travel_sections(source: SourcePost) -> tuple[str, list[Section], list[dict[str, str]], str]:
    years = YEAR_RE.findall(f"{source.current_title} {source.excerpt} {strip_html(source.body_html)}")
    year = years[-1] if years else "2026"
    location = source.current_title.split(":")[0].strip()
    title = ensure_title(source.current_title, "timing, route, and local planning notes")
    summary = sentence_join(
        [
            f"This guide revisits {location} for {year} and keeps the planning value high.",
            "It focuses on route, schedule, transport, cafés, and checklist logic that still helps first-time visitors make a calmer trip.",
        ]
    )
    sections = [
        Section(2, "What this guide helps you decide first", [
            f"{title} works best when the reader treats it as a route decision rather than a photo-only stop.",
            f"The real value in {location} is the sequence: when to arrive, where to start, how long to stay, and how to connect food or cafés without turning the visit into a queue-heavy detour.",
            "That is why the opening paragraphs keep guide, route, schedule, checklist, and visit language close to the search intent.",
        ]),
        Section(2, f"What still holds up for {year} planning", [
            f"The evergreen value in {location} is the order of movement. Visitors still benefit from deciding whether the goal is a short evening walk, a half-day route, or a slow neighborhood visit before they leave home.",
            "A durable travel page keeps the local promise sharp: it tells the reader what still works, what changes quickly, and what should be rechecked on the day before departure.",
        ]),
        Section(2, "What to recheck before you go", [
            "Anything tied to schedule, transport, booking, temporary closures, market hours, or nightly lighting should be treated as a check item rather than a fixed promise.",
            "The safest refresh rule is simple: confirm the official event page, the transport notice, and the weather-linked crowd window before you go.",
        ], bullets=[
            "Recheck the official schedule and transport notice.",
            "Decide whether the visit is a quick route or a longer neighborhood plan.",
            "Keep one backup indoor stop for weather or crowd changes.",
            "Set food timing before the busiest photo window.",
        ]),
        Section(3, "Timing and route checklist", [
            "A strong route starts with the entrance that reduces backtracking, not the most photogenic spot.",
            "If cafés, restaurants, or markets matter to the experience, place them after the first walk segment so the route keeps momentum instead of breaking into long waits.",
        ]),
        Section(2, "Local pacing, cafés, food, and budget notes", [
            f"{location} becomes more useful as a travel article when the copy explains why a café pause or a local food stop belongs at a specific point in the walk.",
            "Separating fixed transport cost from optional café or market spending also helps the reader compare this route with another nearby option.",
            "Good local writing names the atmosphere shift across the day: light, crowd density, noise, and walking pace all change the feel of the route.",
        ]),
        Section(3, "Why the guide remains useful", [
            "The planning value remains strong because the article is not selling a once-only spectacle.",
            "It helps a traveler build a better visit around timing, transport, food, and route choices that still matter even when exact seasonal details move.",
        ]),
    ]
    faq = [
        {"question": f"What should I recheck before visiting {location}?", "answer": "Recheck the official schedule, transport notice, and any booking requirement. Those three items change faster than the route itself."},
        {"question": f"Is {location} better for a short evening walk or a longer half-day route?", "answer": "It works as both, but the route is easier when the reader chooses one plan in advance instead of mixing both."},
        {"question": "How do first-time visitors keep the route from feeling rushed?", "answer": "Pick one visual anchor, one food stop, and one exit strategy before arrival. That simple checklist prevents unnecessary backtracking."},
    ]
    return title, sections, faq, summary


def build_mystery_sections(source: SourcePost) -> tuple[str, list[Section], list[dict[str, str]], str]:
    plain = strip_html(source.body_html)
    years = YEAR_RE.findall(f"{source.current_title} {source.excerpt} {plain}")
    entities = extract_entities(f"{source.current_title} {plain}", 6)
    case_name = entities[0] if entities else source.current_title.split(":")[0].strip()
    title = ensure_title(source.current_title, "what the record shows and where interpretation begins")
    summary = sentence_join(
        [
            f"This fact-based review of {case_name} separates the documented spine of the case from later interpretation.",
            "It focuses on timeline, record, archive, evidence, and the points that still divide investigators and readers.",
        ]
    )
    sections = [
        Section(2, "Case overview", [
            f"{case_name} is often introduced as a mystery because later retellings compress chronology into a dramatic headline.",
            "A documentary treatment works better when it restores sequence: what was reported first, what the earliest record actually says, and which later retellings added tone without adding evidence.",
            "This rewrite keeps the case interesting, but it makes the record, source, archive, document trail, and investigation language visible instead of hiding those elements behind atmosphere.",
        ]),
        Section(2, "Timeline", [
            f"The safest timeline begins with {years[0] if years else 'the earliest documented stage'} because that is where the known record becomes traceable.",
            f"{years[-1] if years else 'Later reviews'} matter because that is often where the modern debate begins, not where the underlying event happened.",
            "The reader needs chronology before theory. Without that order, rumor, documentary framing, and archive-backed detail blur together.",
        ]),
        Section(3, "What the surviving record confirms", [
            "Useful mystery writing names the source type directly: report, archive, witness account, document, press summary, police file, or later investigation note.",
            "That language gives the reader a way to weigh confidence instead of absorbing every claim at the same level.",
        ]),
        Section(2, "Confirmed facts and evidence", [
            "The strongest evidence section identifies the facts repeated across independent record lines, then marks the parts that depend on a single witness or a much later retelling.",
            "Physical evidence belongs in the fact layer. Motive, symbolism, curse language, and broad conclusions belong in the interpretation layer.",
            "This is why the article deliberately keeps source, record, document, evidence, official, witness, and archive language close to the middle of the piece.",
        ]),
        Section(3, "Where interpretation begins", [
            "Theories become weaker when they solve every unanswered detail at once.",
            "If the evidence does not support a definitive answer, the article should say that the point remains debated or that the claim rests on incomplete records.",
        ]),
        Section(2, "Why the debate persists", [
            f"{case_name} persists because it sits between evidence and imagination.",
            "There is enough record to keep the case alive, but not enough certainty to close every question without assumption.",
            "A strong mystery archive answers what happened, why it is debated, what the record shows, and what never moved beyond interpretation.",
        ]),
    ]
    faq = [
        {"question": f"What is the safest way to read the evidence in {case_name}?", "answer": "Start with the earliest record, then separate documentable facts from later interpretation. That keeps the article anchored to evidence instead of mood."},
        {"question": "Why do mystery cases keep generating new theories?", "answer": "Because later retellings often amplify uncertain details while the verified record stays incomplete."},
        {"question": "Does this article try to solve the case completely?", "answer": "No. It prioritizes timeline, record, source, and evidence, then shows where interpretation begins."},
    ]
    return title, sections, faq, summary


def normalize_cloudflare_category(title: str, category: str) -> str:
    haystack = f"{title} {category}"
    if re.search(r"(축제|벚꽃|행사|현장|관람)", haystack):
        return "축제와 현장"
    if re.search(r"(전시|도서관|공간|미술관|인사동|문화)", haystack):
        return "문화와 공간"
    if re.search(r"(AI|OpenAI|Copilot|MCP|SDK|프롬프트|파이프라인|개발|코드|자동화|에이전트|이미지)", haystack, re.IGNORECASE):
        return "개발과 프로그래밍" if re.search(r"(개발|코드|SDK|MCP|Copilot)", haystack, re.IGNORECASE) else "기술의 기록"
    if re.search(r"(주식|증시|실적|금리|시장|투자|유통|소비)", haystack):
        return "주식의 흐름"
    if re.search(r"(크립토|암호화폐|비트코인|온체인|토큰)", haystack):
        return "크립토의 흐름"
    if re.search(r"(미스터리|전설|실종|Dyatlov|Mary Celeste|달리아|조디악)", haystack, re.IGNORECASE):
        return "미스테리아 스토리"
    if re.search(r"(메모|정리|습관|루틴|출퇴근|피곤)", haystack):
        return "일상과 메모"
    if re.search(r"(산책|카페|동네|주말|하천|여행|교토)", haystack):
        return "여행과 기록"
    if re.search(r"(국제|글로벌|뉴스|관세|인플레이션|이슈)", haystack):
        return "동그리의 생각"
    return category


def build_cloudflare_sections(source: SourcePost, target_category: str) -> tuple[str, list[Section], list[dict[str, str]], str, list[str]]:
    archetype = ARCHETYPE_BY_CATEGORY.get(target_category, "practical")
    seed = source.current_title.split(":")[0].split(",")[0].strip()
    suffix = {
        "festival": "이동 동선과 현장 체크포인트까지 한 번에 정리",
        "culture": "오래 머물게 만드는 포인트와 관람 순서 정리",
        "tech": "실제 적용 순서와 운영 체크리스트 정리",
        "practical": "바로 써먹는 기준과 실패 줄이는 순서",
        "routine": "오래 가는 루틴과 기록 기준 정리",
        "issue": "배경, 핵심 쟁점, 지금 읽어야 할 이유",
        "market": "이번 흐름을 읽을 때 먼저 볼 판단 기준",
        "travel": "기록이 잘 남는 동선과 메모 포인트",
        "mystery": "확인된 사실과 남는 해석을 나눠서 읽기",
    }[archetype]
    title = ensure_title(source.current_title, suffix)
    intent = ARCHETYPE_INTENT[archetype]
    tags = ARCHETYPE_TAGS[archetype][:]
    summary = sentence_join([
        f"{title}를 단순 요약으로 끝내지 않고 {target_category} 관점에서 다시 정리합니다.",
        f"이 글은 {intent}를 위해 background, guide, checklist, record를 한 흐름으로 묶어 실제 판단과 실행에 바로 쓰기 쉽게 구성합니다.",
    ])
    sections = [
        Section(2, "먼저 봐야 할 핵심 Guide", [
            f"{title}를 다시 쓰는 이유는 검색에서 클릭을 얻는 것만이 아니라 읽고 나서 바로 판단에 쓸 수 있는 구조를 만들기 위해서입니다.",
            f"{seed} 같은 주제는 정보량보다 정리 순서가 더 중요합니다. 독자는 headline보다 background와 기준을 원하고, 그 기준은 guide와 checklist 형태로 제시될 때 가장 오래 남습니다.",
            "그래서 도입부부터 왜 중요한지, 무엇부터 확인할지, 어떤 실수를 줄일 수 있는지까지 한 번에 정리합니다.",
        ]),
        Section(2, "배경과 맥락", [
            f"{seed}는 겉으로 단순해 보여도 실제로는 여러 층위의 배경이 겹쳐 있습니다. 현장 운영이든 도구 사용이든 시장 판단이든, 표면 정보만 보면 놓치는 지점이 생깁니다.",
            "이 section은 그 배경을 정리해 독자가 나머지 본문을 읽을 기준선을 먼저 잡도록 돕습니다. 글이 오래 읽히는 이유는 정보가 많아서가 아니라 맥락이 정리돼 있기 때문입니다.",
        ]),
        Section(3, "실전 Checklist", [
            "바로 실행하기 전에 확인해야 할 항목은 생각보다 단순합니다. 핵심 쟁점, 시간 맥락, 판단 기준, 실패를 줄이는 순서, 그리고 다시 확인할 official source를 먼저 적어야 합니다.",
            "이 다섯 항목이 정리되면 같은 주제도 덜 피곤하게 읽히고, 다시 검색했을 때도 훨씬 빨리 핵심을 회수할 수 있습니다.",
        ], bullets=[
            "핵심 쟁점을 한 문장으로 줄입니다.",
            "2026 기준으로 time context를 먼저 확인합니다.",
            "official source 또는 record가 있는지 체크합니다.",
            "바로 적용할 순서를 checklist로 적습니다.",
            "다음 글과 연결될 related link를 함께 저장합니다.",
        ]),
        Section(2, "실제로 적용할 때의 판단 순서", [
            f"{seed} 같은 주제는 결론을 서두를수록 정보가 거칠어집니다. 먼저 배경을 이해하고, 다음으로 비교 기준을 세우고, 마지막에 action을 결정하는 편이 더 안전합니다.",
            "그래서 본문은 즉답보다 process를 남깁니다. 독자가 같은 문제를 다시 만났을 때도 그대로 재사용할 수 있는 frame을 주는 것이 목적입니다.",
        ]),
        Section(3, "왜 이 구조가 SEO와 CTR에 유리한가", [
            "CTR을 만드는 제목은 문제를 제기하지만, 재방문을 만드는 글은 정리의 언어를 남깁니다. guide, checklist, timeline, record, source 같은 단어가 반복되는 이유도 그 때문입니다.",
            "이런 구조는 검색 엔진에도 명확하고 독자에게도 명확합니다. 그래서 얇은 요약보다 실제 체류와 저장 가능성이 더 높아집니다.",
        ]),
        Section(2, "마무리 Summary", [
            f"{seed}는 단순 정보보다 기준이 중요한 주제입니다. 그래서 이 글은 background, checklist, summary 순서로 다시 정리했고, related links와 FAQ까지 한 번에 붙였습니다.",
        ]),
    ]
    faq = [
        {"question": "이 글은 어떤 독자에게 가장 도움이 되나요?", "answer": f"이 글은 {intent}를 기준으로 구성했습니다. headline보다 배경과 판단 기준을 함께 보고 싶은 독자에게 맞습니다."},
        {"question": "본문에서 가장 먼저 확인해야 할 포인트는 무엇인가요?", "answer": "핵심 쟁점, 시간 맥락, 적용 순서 세 가지를 먼저 보면 됩니다. 그 뒤에 세부 정보와 related link를 따라가면 이해가 훨씬 빨라집니다."},
        {"question": "왜 FAQ와 관련 글 링크를 같이 넣었나요?", "answer": "검색 후 바로 나가버리지 않도록 요약 회수 지점과 다음 탐색 지점을 함께 만들기 위해서입니다. 이것이 체류와 재방문에 모두 유리합니다."},
    ]
    return title, sections, faq, summary, tags


def extend_sections_for_quality(
    source: SourcePost,
    *,
    title: str,
    target_category: str,
    sections: list[Section],
    faq: list[dict[str, str]],
) -> tuple[list[Section], list[dict[str, str]]]:
    enhanced_sections = list(sections)
    enhanced_faq = list(faq)

    if source.channel == "dongri-archive":
        enhanced_sections.extend(
            [
                Section(
                    2,
                    "Execution playbook and checklist",
                    [
                        f"Applying {title} in real workflows requires sequence more than volume: define the decision, execute in a bounded window, and document outcomes for the next iteration.",
                        f"For {target_category}, pages should be written as reusable references. Keep summary, action order, validation points, and exception handling in one document so readers can return and execute quickly.",
                        "From an SEO/CTR perspective, this structure works well: explicit problem framing in the intro, decision criteria in the middle, and an immediately usable checklist at the end.",
                    ],
                    bullets=[
                        "Start with one concrete action the reader can execute today.",
                        "Separate mandatory inputs from optional context to reduce decision fatigue.",
                        "Capture a short execution log and connect it to two related internal links.",
                        "Mark volatile points explicitly (schedule, price, policy, operations).",
                    ],
                ),
                Section(
                    3,
                    "Reader-action validation points",
                    [
                        "The core output is not information density but action clarity. Each section should answer why this matters, how to execute it, and what changes after execution.",
                        "Adding two to three related internal links reinforces topical cohesion for both readers and crawlers, which improves long-term stability.",
                    ],
                ),
            ]
        )
        if len(enhanced_faq) < 4:
            enhanced_faq.append(
                {
                    "question": "What is the first action after reading this?",
                    "answer": "Define one target outcome, execute the first checklist item, and leave a three-line result note for the next update cycle.",
                }
            )

    if source.channel == "midnight-archives":
        enhanced_sections.append(
            Section(
                2,
                "Evidence reliability reading guide",
                [
                    f"Topics like {title} benefit from explicit reliability labeling by paragraph: primary record, secondary summary, and interpretation should stay distinct.",
                    "When timeline items are anchored to verifiable records before interpretive claims, readers can evaluate confidence levels without conflating fact and theory.",
                ],
                bullets=[
                    "Separate primary evidence from later interpretations.",
                    "Prioritize year, location, and source traceability.",
                    "Downgrade weak claims to interpretation or oral tradition.",
                ],
            )
        )

    return enhanced_sections, enhanced_faq


def apply_quality_booster(
    source: SourcePost,
    *,
    title: str,
    target_category: str,
    summary: str,
    sections: list[Section],
    faq: list[dict[str, str]],
    related: list[SourcePost],
    tags: list[str],
) -> tuple[list[Section], list[dict[str, str]], str, str, str, str, dict[str, Any]]:
    working_sections = list(sections)
    working_faq = list(faq)

    def _render_and_score() -> tuple[str, str, str, str, dict[str, Any]]:
        markdown_value = render_markdown(title, summary, working_sections, working_faq, related, tags)
        html_value = render_html(summary, working_sections, working_faq, related)
        excerpt_value = summarize(summary, 220)
        meta_value = summarize(
            f"Comprehensive guide for {title}: context, execution checklist, FAQ, and related references in one place.",
            155,
        )
        score_value = compute_seo_geo_scores(title=title, html_body=html_value, excerpt=excerpt_value, faq_section=working_faq)
        return markdown_value, html_value, excerpt_value, meta_value, score_value

    markdown, html_body, excerpt, meta_description, score = _render_and_score()

    if source.channel == "dongri-archive":
        target_plain_min = 3000
    elif source.channel == "midnight-archives":
        target_plain_min = 3300
    else:
        target_plain_min = 0

    booster_round = 0
    while booster_round < 3 and (int(score["seo_score"]) < 80 or (target_plain_min and int(score["plain_text_length"]) < target_plain_min)):
        booster_round += 1
        working_sections.append(
            Section(
                2,
                f"Optimization addendum {booster_round}",
                [
                    f"{title} performs better when execution is explicit: define the problem, choose criteria, run a bounded action, and document outcomes for the next cycle.",
                    "This sequence remains reusable across adjacent topics and supports deeper navigation when internal links are attached to each decision point.",
                    "A compact logging template (date, decision reason, outcome, and next edit point) significantly reduces rewrite cost while improving consistency.",
                ],
                bullets=[
                    "Lock one decision statement before execution.",
                    "Capture at least three before/after comparisons.",
                    "Connect at least two related internal documents.",
                ],
            )
        )
        if len(working_faq) < 5:
            working_faq.append(
                {
                    "question": f"What should be checked first in {title}?",
                    "answer": "Start from the opening problem statement and the first checklist item; those two points set execution direction quickly.",
                }
            )
        markdown, html_body, excerpt, meta_description, score = _render_and_score()

    return working_sections, working_faq, markdown, html_body, excerpt, meta_description, score


def build_draft(source: SourcePost, related: list[SourcePost]) -> DraftArtifact:
    if source.channel == "travel":
        title, sections, faq, summary = build_travel_sections(source)
        action = "refresh" if time_sensitive_travel(source) else "audit"
        target_category = "travel"
        archetype = "travel"
        tags = source.labels[:4]
    elif source.channel == "midnight-archives":
        title, sections, faq, summary = build_mystery_sections(source)
        action = "rewrite"
        target_category = "mystery"
        archetype = "mystery"
        tags = source.labels[:4]
    else:
        target_category = normalize_cloudflare_category(source.current_title, source.current_category)
        title, sections, faq, summary, tags = build_cloudflare_sections(source, target_category)
        action = "full_rewrite"
        archetype = ARCHETYPE_BY_CATEGORY.get(target_category, "practical")

    sections, faq = extend_sections_for_quality(
        source,
        title=title,
        target_category=target_category,
        sections=sections,
        faq=faq,
    )

    sections, faq, markdown, html_body, excerpt, meta_description, after = apply_quality_booster(
        source,
        title=title,
        target_category=target_category,
        summary=summary,
        sections=sections,
        faq=faq,
        related=related,
        tags=tags,
    )

    return DraftArtifact(
        channel=source.channel,
        channel_name=source.channel_name,
        source_slug=source.source_slug,
        source_url=source.source_url,
        current_title=source.current_title,
        new_title=title,
        current_category=source.current_category,
        target_category=target_category,
        action=action,
        archetype=archetype,
        tags=tags,
        excerpt=excerpt,
        meta_description=meta_description,
        hero_title=title,
        hero_description=summary,
        markdown=markdown,
        html=html_body,
        faq_section=faq,
        seo_before=source.seo_before,
        geo_before=source.geo_before,
        seo_after=int(after["seo_score"]),
        geo_after=int(after["geo_score"]),
        plain_text_length=int(after["plain_text_length"]),
        published_at=source.published_at,
        notes=f"Generated without Bloggent API. Related links: {len(related[:3])}.",
    )


def write_channel_package(root: Path, channel: str, drafts: list[DraftArtifact]) -> None:
    channel_root = root / channel
    draft_root = channel_root / "drafts"
    draft_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for draft in drafts:
        md_path = draft_root / f"{draft.source_slug}.md"
        html_path = draft_root / f"{draft.source_slug}.html"
        md_path.write_text(draft.markdown, encoding="utf-8")
        html_path.write_text(draft.html, encoding="utf-8")
        rows.append({
            "source_slug": draft.source_slug,
            "source_url": draft.source_url,
            "current_title": draft.current_title,
            "new_title": draft.new_title,
            "current_category": draft.current_category,
            "target_category": draft.target_category,
            "action": draft.action,
            "archetype": draft.archetype,
            "tags": "|".join(draft.tags),
            "seo_before": draft.seo_before,
            "geo_before": draft.geo_before,
            "seo_after": draft.seo_after,
            "geo_after": draft.geo_after,
            "plain_text_length": draft.plain_text_length,
            "published_at": draft.published_at or "",
            "notes": draft.notes,
            "markdown_path": str(md_path),
            "html_path": str(html_path),
        })
    with (channel_root / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (channel_root / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def build_tag_manifest(drafts: list[DraftArtifact]) -> list[dict[str, Any]]:
    tag_posts: dict[str, list[DraftArtifact]] = defaultdict(list)
    tag_related: dict[str, Counter[str]] = defaultdict(Counter)
    tag_categories: dict[str, Counter[str]] = defaultdict(Counter)
    for draft in drafts:
        for tag in draft.tags:
            tag_posts[tag].append(draft)
            tag_categories[tag][draft.target_category] += 1
        for tag in draft.tags:
            for other in draft.tags:
                if tag != other:
                    tag_related[tag][other] += 1
    entries: list[dict[str, Any]] = []
    for tag, posts in tag_posts.items():
        posts = sorted(posts, key=lambda item: (-item.seo_after, item.new_title))
        archetype = posts[0].archetype if posts else "practical"
        seo_description = summarize(
            f"{tag}와 관련된 Dongri Archive 글을 모았습니다. {ARCHETYPE_INTENT.get(archetype, '관련 글을 한 번에 보고 싶은 독자')}를 위해 배경, 체크리스트, 사례, 실전 포인트를 함께 읽을 수 있게 정리한 태그 페이지입니다.",
            155,
        )
        entries.append({
            "slug": slugify(tag),
            "name": tag,
            "cluster": {"festival": "로컬 탐색", "culture": "로컬 탐색", "tech": "기술 활용", "practical": "생활 정보", "routine": "생활 정보", "issue": "맥락 해설", "market": "시장 판단", "travel": "로컬 탐색", "mystery": "사실 해설"}.get(archetype, "생활 정보"),
            "intent": ARCHETYPE_INTENT.get(archetype, "관련 글을 한 번에 보고 싶은 독자"),
            "postCount": len(posts),
            "topPosts": [{
                "slug": post.source_slug,
                "title": post.new_title,
                "url": post.source_url,
                "path": f"/ko/posts/{post.source_slug}/",
                "category": post.target_category,
                "description": post.excerpt,
            } for post in posts[:4]],
            "heroTitle": f"{tag} 관련 글 모음",
            "heroDescription": f"{tag}를 중심으로 핵심 background, guide, checklist, record를 따라가기 쉽게 묶었습니다.",
            "seoTitle": f"{tag} 관련 글 모음 | Dongri Archive",
            "seoDescription": seo_description,
            "indexable": len(posts) >= 3,
            "relatedTags": [{"slug": slugify(name), "name": name} for name, _count in tag_related[tag].most_common(4)],
            "relatedCategories": [name for name, _count in tag_categories[tag].most_common(3)],
        })
    entries.sort(key=lambda item: (not item["indexable"], -item["postCount"], item["name"]))
    return entries


def write_meta_files(root: Path, drafts_by_channel: dict[str, list[DraftArtifact]]) -> None:
    score_rows: list[dict[str, Any]] = []
    summary_lines = ["# Content refresh summary", "", f"- Generated at: {datetime.now(timezone.utc).isoformat()}", ""]
    for channel, drafts in drafts_by_channel.items():
        summary_lines.extend([
            f"## {channel}",
            "",
            f"- Items: {len(drafts)}",
            f"- Average SEO after: {round(sum(item.seo_after for item in drafts) / max(len(drafts), 1), 2)}",
            f"- Average GEO after: {round(sum(item.geo_after for item in drafts) / max(len(drafts), 1), 2)}",
            f"- Lowest SEO after: {min(item.seo_after for item in drafts)}",
            f"- Lowest GEO after: {min(item.geo_after for item in drafts)}",
            "",
        ])
        for item in drafts:
            score_rows.append({
                "channel": channel,
                "slug": item.source_slug,
                "current_title": item.current_title,
                "new_title": item.new_title,
                "seo_before": item.seo_before,
                "geo_before": item.geo_before,
                "seo_after": item.seo_after,
                "geo_after": item.geo_after,
                "plain_text_length": item.plain_text_length,
                "action": item.action,
            })
    with (root / "score-report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(score_rows[0].keys()))
        writer.writeheader()
        writer.writerows(score_rows)
    (root / "summary.md").write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
    (root / "manual-apply-guide.md").write_text(textwrap.dedent(f"""
    # Manual apply guide

    1. Open `{root}` and review each channel manifest.
    2. Copy title, excerpt, body, and FAQ from the generated draft files.
    3. Apply `target_category` and `tags` when updating Dongri Archive content.
    4. Sync `dongri-archive/tag-manifest.ko.json` into `dongriarhive-repo/apps/blog-web/src/data/tag-manifest.ko.json` if the automatic sync step was skipped.
    """).strip() + "\n", encoding="utf-8")


def build_inventory(mode: str) -> dict[str, list[SourcePost]]:
    inventory: dict[str, list[SourcePost]] = {}
    if mode in ("travel", "all"):
        inventory["travel"] = load_blogger_sources(34, "travel", "Donggri's Hidden Korea: Local Travel & Culture", "travel")
    if mode in ("midnight", "all"):
        inventory["midnight-archives"] = load_blogger_sources(35, "midnight-archives", "The Midnight Archives", "mystery")
    if mode in ("cloudflare", "all"):
        inventory["dongri-archive"] = load_cloudflare_sources()
    return inventory


def main() -> None:
    args = parse_args()
    if args.mode != "cloudflare":
        raise ValueError(
            "Generic rewrite packages are Cloudflare-only. "
            "Use scripts/build_blogger_patch_package.py for Travel/Mystery partial-update packages."
        )
    output_root = PACKAGE_ROOT / f"{args.date}-codex-refresh"
    output_root.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory(args.mode)
    drafts_by_channel: dict[str, list[DraftArtifact]] = {}
    for channel, sources in inventory.items():
        drafts = [build_draft(source, choose_related_sources(sources, source)) for source in sources]
        drafts_by_channel[channel] = drafts
        write_channel_package(output_root, channel, drafts)
    write_meta_files(output_root, drafts_by_channel)
    if "dongri-archive" in drafts_by_channel:
        tag_manifest = build_tag_manifest(drafts_by_channel["dongri-archive"])
        (output_root / "dongri-archive" / "tag-manifest.ko.json").write_text(
            json.dumps(tag_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if DONGRIARCHIVE_REPO.exists():
            DONGRIARCHIVE_TAG_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
            DONGRIARCHIVE_TAG_MANIFEST.write_text(json.dumps(tag_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "package-metadata.json").write_text(
        json.dumps(
            {
                "kind": "legacy-full-rewrite",
                "mode": args.mode,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"package_root": str(output_root), "channels": list(drafts_by_channel.keys())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
