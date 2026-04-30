from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy import select


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

RUNTIME_ROOT = Path(os.getenv("BLOGGENT_RUNTIME_ROOT", r"D:\Donggri_Runtime\BloggerGent"))
ROOL_ROOT = RUNTIME_ROOT / "Rool" / "30-cloudflare"
P1_ROOT = ROOL_ROOT / "12-category-layout-refactor" / "p1-quality-80"
PACKET_ROOT = P1_ROOT / "packets"
PROMPT_ROOT = P1_ROOT / "codex-prompts"
RESULT_ROOT = P1_ROOT / "results"
VALIDATED_ROOT = P1_ROOT / "validated"
APPLY_ROOT = P1_ROOT / "apply"
RETRY_ROOT = P1_ROOT / "retry"
RENDERER_PERF_ROOT = P1_ROOT / "renderer_perf_required"
BACKUP_LOG_ROOT = RUNTIME_ROOT / "backup" / "작업log"

SEO_TARGET = 80
GEO_TARGET = 80
LIGHTHOUSE_TARGET = 80
MIN_KOREAN_SYLLABLES = 2000
PATTERN_VERSION = 4

FORBIDDEN_BODY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("h1", re.compile(r"<\s*h1\b|^\s*#\s+", re.I | re.S | re.M)),
    ("script", re.compile(r"<\s*script\b", re.I | re.S)),
    ("iframe", re.compile(r"<\s*iframe\b", re.I | re.S)),
    ("img", re.compile(r"<\s*img\b|!\[[^\]]*\]\([^)]+\)", re.I | re.S)),
    ("figure", re.compile(r"<\s*figure\b", re.I | re.S)),
    ("inline_style", re.compile(r"\sstyle\s*=", re.I | re.S)),
    ("adsense", re.compile(r"adsbygoogle|data-ad-client|ca-pub-|googlesyndication|doubleclick|<!--\s*adsense|\[ad_slot", re.I | re.S)),
)
TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+")
CODE_BLOCK_RE = re.compile(r"```.*?```", re.S)
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
H2_RE = re.compile(r"<h2\b[^>]*>|^\s*##\s+", re.I | re.S | re.M)
H3_RE = re.compile(r"<h3\b[^>]*>|^\s*###\s+", re.I | re.S | re.M)
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def _load_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = value
    os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@localhost:15432/bloggent")
    os.environ.setdefault("STORAGE_ROOT", str(RUNTIME_ROOT / "storage"))


_load_runtime_env()

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.content.content_ops_service import compute_seo_geo_scores  # noqa: E402
from app.services.platform.codex_cli_queue_service import submit_codex_text_job  # noqa: E402
from app.services.providers.base import RuntimeProviderConfig  # noqa: E402


CODEX_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "content": {"type": "string"},
        "excerpt": {"type": "string"},
        "seoTitle": {"type": "string"},
        "seoDescription": {"type": "string"},
        "tagNames": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 10},
        "articlePatternId": {"type": "string"},
        "articlePatternVersion": {"type": "integer"},
        "refactorNotes": {"type": "string"},
    },
    "required": [
        "title",
        "content",
        "excerpt",
        "seoTitle",
        "seoDescription",
        "tagNames",
        "articlePatternId",
        "articlePatternVersion",
        "refactorNotes",
    ],
}


CATEGORY_RULE_HINTS: dict[str, dict[str, Any]] = {
    "미스테리아-스토리": {
        "patterns": ["case-timeline", "evidence-breakdown", "legend-context", "scene-investigation", "scp-dossier"],
        "required_facts": ["사건 시점", "장소", "관련 인물", "기록 출처", "검증되지 않은 해석 구분", "남은 의문"],
        "layout": ["핵심 요약", "사건 개요", "타임라인", "증거와 해석", "검증 체크리스트", "FAQ"],
    },
    "개발과-프로그래밍": {
        "patterns": ["dev-info-deep-dive", "dev-curation-top-points", "dev-insider-field-guide", "dev-expert-perspective", "dev-experience-synthesis"],
        "required_facts": ["기준일", "도구 버전", "언어/런타임", "IDE/CLI", "공식 문서", "가격/플랜", "팀 적용 기준"],
        "layout": ["핵심 요약", "문제 정의", "원인과 배경", "실행 절차", "검증 기준", "운영 체크리스트"],
    },
    "일상과-메모": {
        "patterns": ["daily-01-reflective-monologue", "daily-02-insight-memo", "daily-03-habit-tracker", "daily-04-emotional-reflection"],
        "required_facts": ["장면", "시간대", "감정", "반복 행동", "실천 포인트", "작은 체크리스트"],
        "layout": ["핵심 요약", "오늘의 장면", "생각의 흐름", "실천 메모", "작은 체크리스트", "마무리 기록"],
    },
    "여행과-기록": {
        "patterns": ["route-first-story", "spot-focus-review", "seasonal-special", "logistics-budget", "hidden-gem-discovery"],
        "required_facts": ["장소", "지역", "방문 시간", "이동 동선", "계절/날씨", "비용/예약", "주변 연계"],
        "layout": ["핵심 요약", "장소와 동선", "방문 시간", "비용과 예약", "현장 체크리스트", "마무리 기록"],
    },
    "동그리의-생각": {
        "patterns": ["thought-social-context", "thought-tech-culture", "thought-generation-note", "thought-personal-question"],
        "required_facts": ["사회적 사건", "개인 질문", "세대/문화 맥락", "관찰 장면", "결론 질문"],
        "layout": ["핵심 요약", "문제의 장면", "생각의 맥락", "다르게 볼 지점", "남는 질문"],
    },
    "삶을-유용하게": {
        "patterns": ["life-hack-tutorial", "benefit-audit-report", "efficiency-tool-review", "comparison-verdict"],
        "required_facts": ["기준일", "제공 기관", "공식 사이트", "대상/조건", "비용/혜택", "준비물", "주의사항"],
        "layout": ["핵심 요약", "대상과 조건", "실행 절차", "주의할 점", "체크리스트", "FAQ"],
    },
    "삶의-기름칠": {
        "patterns": ["life-support-eligibility", "benefit-audit-report", "application-checklist", "comparison-verdict"],
        "required_facts": ["지원명", "주관 기관", "신청 기간", "자격 조건", "지원 금액/범위", "신청 경로", "제외 조건"],
        "layout": ["핵심 요약", "지원 대상", "신청 방법", "자격 조건", "준비 서류", "FAQ"],
    },
    "주식의-흐름": {
        "patterns": ["stock-cartoon-summary", "technical-analysis", "macro-intelligence", "corporate-event-watch", "risk-timing"],
        "required_facts": ["기준일", "종목/섹터", "가격 구간", "지표", "이벤트 일정", "리스크", "출처 최신성"],
        "layout": ["핵심 요약", "시장 상황", "핵심 지표", "리스크", "관찰 체크리스트", "다음 관찰 포인트"],
    },
    "크립토의-흐름": {
        "patterns": ["crypto-cartoon-summary", "on-chain-analysis", "protocol-deep-dive", "regulatory-macro", "market-sentiment"],
        "required_facts": ["기준일", "코인/프로토콜", "가격", "온체인 지표", "거래소/규제 이슈", "리스크"],
        "layout": ["핵심 요약", "시장 구조", "온체인 신호", "규제와 이벤트", "리스크", "다음 관찰 포인트"],
    },
    "나스닥의-흐름": {
        "patterns": ["technical-deep-dive", "macro-impact", "big-tech-whale-watch", "hypothesis-scenario"],
        "required_facts": ["기준일", "기업/섹터", "실적/가이던스", "금리/매크로", "AI/반도체 맥락", "리스크"],
        "layout": ["핵심 요약", "시장 배경", "기업과 섹터", "매크로 변수", "리스크", "다음 관찰 포인트"],
    },
    "문화와-공간": {
        "patterns": ["info-deep-dive", "curation-top-points", "insider-field-guide", "expert-perspective", "experience-synthesis"],
        "required_facts": ["최종 확인일", "공식 사이트", "예매/예약", "운영 상태", "장소", "기간", "운영 시간", "접근 경로", "현장 리스크"],
        "layout": ["핵심 요약", "공간 정보", "관람 동선", "작품과 포인트", "방문 체크리스트", "FAQ"],
    },
    "축제와-현장": {
        "patterns": ["info-deep-dive", "curation-top-points", "insider-field-guide", "expert-perspective", "experience-synthesis"],
        "required_facts": ["최종 확인일", "공식 사이트", "예매/예약", "운영 상태", "장소", "기간", "운영 시간", "혼잡 시간", "추천 방문 시간", "접근 동선"],
        "layout": ["핵심 요약", "행사 정보", "방문 동선", "혼잡과 리스크", "방문 체크리스트", "FAQ"],
    },
}


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _plain_textish(value: str | None) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    text = re.sub(r"(?is)<\s*(script|style)\b.*?</\s*\1\s*>", " ", text)
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_publish_description(value: Any, *, fallback: str) -> str:
    """Worker publish policy requires seoDescription/excerpt to be 90-170 chars."""
    description = _plain_textish(_safe_text(value))
    fallback_text = _plain_textish(fallback)
    if len(description) < 90 and fallback_text:
        description = f"{description} {fallback_text}".strip()
    while len(description) < 90:
        description = f"{description} 핵심 맥락과 실행 기준을 함께 정리합니다.".strip()
    if len(description) > 170:
        clipped = description[:170].rstrip()
        sentence_cut = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"), clipped.rfind("다."))
        if sentence_cut >= 90:
            clipped = clipped[: sentence_cut + (2 if clipped[sentence_cut : sentence_cut + 2] == "다." else 1)]
        description = clipped.rstrip(" ,;:·-")
    if len(description) < 90:
        description = (description + " 핵심 맥락과 실행 기준을 함께 정리합니다.")[:170].rstrip()
    return description


def _node_text(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name in {"script", "style", "img", "figure"}:
        return ""
    if node.name == "br":
        return "\n"
    return node.get_text(" ", strip=True)


def _inline_markdown(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    tag = (node.name or "").lower()
    if tag in {"script", "style", "img", "figure"}:
        return ""
    if tag == "br":
        return "\n"
    if tag == "a":
        text = " ".join(_inline_markdown(child).strip() for child in node.children).strip()
        href = _safe_text(node.get("href"))
        if text and href and not href.lower().startswith(("javascript:", "data:")):
            return f"[{text}]({href})"
        return text
    return " ".join(_inline_markdown(child).strip() for child in node.children).strip()


def _render_table_as_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [_node_text(cell).replace("|", "/").strip() for cell in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _html_to_markdown_body(html_body: str) -> str:
    """Convert validated inner HTML to the Worker integration's legacy Markdown body."""
    soup = BeautifulSoup(html_body or "", "html.parser")
    root = soup.body or soup
    lines: list[str] = []

    def emit(text: str = "") -> None:
        value = re.sub(r"[ \t]+", " ", text).strip()
        if value:
            lines.append(value)

    def walk(node: Tag | NavigableString) -> None:
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                emit(text)
            return
        if not isinstance(node, Tag):
            return
        tag = (node.name or "").lower()
        if tag in {"script", "style", "img", "figure", "h1"}:
            return
        if tag in {"h2", "h3", "h4", "h5", "h6"}:
            level = {"h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}[tag]
            emit(f"{level} {_inline_markdown(node)}")
            return
        if tag == "p":
            emit(_inline_markdown(node))
            return
        if tag in {"ul", "ol"}:
            for index, li in enumerate(node.find_all("li", recursive=False), start=1):
                marker = f"{index}." if tag == "ol" else "-"
                emit(f"{marker} {_inline_markdown(li)}")
            return
        if tag == "blockquote":
            for paragraph in node.get_text("\n", strip=True).splitlines():
                emit(f"> {paragraph.strip()}")
            return
        if tag == "table":
            rendered = _render_table_as_markdown(node)
            if rendered:
                lines.append(rendered)
            return
        if tag == "hr":
            lines.append("---")
            return
        for child in node.children:
            walk(child)

    for child in root.children:
        walk(child)

    markdown = "\n\n".join(line for line in lines if line.strip())
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    if re.search(r"(?im)^\s*#\s+", markdown):
        raise ValueError("Converted Markdown contains H1.")
    if re.search(r"(?is)<\s*[a-z][^>]*>", markdown):
        raise ValueError("Converted Markdown still contains HTML.")
    return markdown


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _strip_code_fences(text: str) -> str:
    value = _safe_text(text)
    match = JSON_BLOCK_RE.search(value)
    if match:
        return match.group(1).strip()
    return value


def _plain_text(value: str) -> str:
    stripped = CODE_BLOCK_RE.sub(" ", value or "")
    stripped = URL_RE.sub(" ", stripped)
    stripped = TAG_RE.sub(" ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def _body_korean_syllables(value: str) -> int:
    stripped = _plain_text(value)
    stripped = re.sub(r"[A-Za-z0-9\s\W_]", "", stripped)
    return len(HANGUL_RE.findall(stripped))


def _tag_names(detail: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for raw in detail.get("tagNames") or []:
        text = _safe_text(raw)
        if text and text not in values:
            values.append(text)
    for raw in detail.get("tags") or []:
        text = _safe_text(raw.get("name") if isinstance(raw, dict) else raw)
        if text and text not in values:
            values.append(text)
    return values[:20]


def _category_slug(detail: dict[str, Any], fallback: str = "") -> str:
    direct = _safe_text(detail.get("categorySlug"))
    if direct:
        return direct
    category = detail.get("category")
    if isinstance(category, dict):
        return _safe_text(category.get("slug") or category.get("categorySlug")) or fallback
    return fallback


def _result_name_from_packet(packet_path: Path) -> str:
    return packet_path.name


def _manifest_rows() -> list[dict[str, str]]:
    manifest = P1_ROOT / "p1-packet-manifest-latest.csv"
    if not manifest.exists():
        raise FileNotFoundError(f"P1 manifest not found: {manifest}")
    return _read_csv(manifest)


def _packet_path_from_row(row: dict[str, str]) -> Path:
    path = Path(_safe_text(row.get("packet_path")))
    if not path.exists():
        raise FileNotFoundError(f"Packet not found: {path}")
    return path


def _category_docs(category_slug: str) -> dict[str, str]:
    category_root = ROOL_ROOT / "categories" / category_slug
    docs: dict[str, str] = {}
    for name in ("article-patterns.md", "generation-checklist.md", "image-prompt-policy.md"):
        path = category_root / name
        docs[name] = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return docs


def _build_codex_prompt(packet: dict[str, Any]) -> str:
    detail = packet.get("remote_detail") if isinstance(packet.get("remote_detail"), dict) else {}
    source = packet.get("source_row") if isinstance(packet.get("source_row"), dict) else {}
    category_slug = _category_slug(detail, _safe_text(source.get("category_slug")))
    hints = CATEGORY_RULE_HINTS.get(category_slug, {})
    docs = _category_docs(category_slug)
    title = _safe_text(detail.get("title") or source.get("title") or packet.get("slug"))
    content = _safe_text(detail.get("content") or detail.get("contentMarkdown") or detail.get("html") or "")
    excerpt = _safe_text(detail.get("excerpt") or source.get("excerpt"))
    tag_names = _tag_names(detail)
    current_scores = packet.get("contract", {}).get("current_scores") if isinstance(packet.get("contract"), dict) else {}
    return f"""
You are refactoring one published Cloudflare blog post for quality scoring.
Return JSON only. Do not explain.

[Immutable fields]
remote_post_id: {_safe_text(detail.get("id") or source.get("remote_post_id"))}
slug: {_safe_text(detail.get("slug") or source.get("slug"))}
category_slug: {category_slug}
coverImage must not change.
URL must not change.

[Current scores]
SEO: {_safe_text((current_scores or {}).get("seo") or source.get("seo_score"))}
GEO: {_safe_text((current_scores or {}).get("geo") or source.get("geo_score"))}
Lighthouse: {_safe_text((current_scores or {}).get("lighthouse") or source.get("lighthouse_score"))}

[Allowed category patterns]
{json.dumps(hints.get("patterns") or [], ensure_ascii=False)}

[Required facts schema]
{json.dumps(hints.get("required_facts") or [], ensure_ascii=False)}

[Recommended body layout]
{json.dumps(hints.get("layout") or [], ensure_ascii=False)}

[Hard constraints]
- Rewrite only title, content, excerpt, seoTitle, seoDescription, tagNames, articlePatternId, articlePatternVersion, refactorNotes.
- Preserve the original subject. If slug and title conflict, follow the current title/content subject and mention the conflict in refactorNotes.
- content must be clean inner HTML for the public Cloudflare UI. Use only h2, h3, p, ul, ol, li, a, strong, em, table, thead, tbody, tr, th, td.
- Do not use h1, script, iframe, img, figure, markdown image, inline style, AdSense tokens, outer article/section/div wrappers.
- The first visible block must be <h2>핵심 요약</h2>.
- Use at least four h2 headings and at least two h3 headings.
- Include at least three internal links using /ko or /ko/category/... anchors where natural.
- Pure Korean body syllables must be at least 2600 after removing HTML, URLs, English, numbers, spaces, and punctuation. The validator hard gate is 2000, but this batch needs a safety margin.
- Target visible body length is 5500 to 7600 Korean-friendly characters.
- Include explicit sections for "검증 체크리스트", "출처와 한계", and "다음 행동 기준" when they fit the category. These sections must remain factual and must not invent unavailable facts.
- GEO readiness requires clear current 기준일/시점, named entities, evidence/source context, actionable checklist, and risk/limit statements in Korean.
- Add a compact FAQ section only when it helps the article; if used, keep it factual.
- Do not fabricate exact official URLs, dates, prices, locations, or source claims. If a fact is not present, write "확인 필요" rather than inventing it.
- For SEO/GEO, answer the reader's intent in the first 600 visible characters and separate facts, interpretation, action/checklist, and remaining risks.

[Rool article-patterns.md]
{docs.get("article-patterns.md", "")[:9000]}

[Rool generation-checklist.md]
{docs.get("generation-checklist.md", "")[:9000]}

[Current title]
{title}

[Current excerpt]
{excerpt}

[Current tagNames]
{json.dumps(tag_names, ensure_ascii=False)}

[Current content]
{content[:22000]}

[Output JSON shape]
{{
  "title": "Korean title. 36-96 characters preferred.",
  "content": "Clean inner HTML only. Starts with <h2>핵심 요약</h2>.",
  "excerpt": "Korean excerpt, 70-180 characters.",
  "seoTitle": "Korean SEO title, 36-96 characters.",
  "seoDescription": "Korean SEO description, 90-160 characters.",
  "tagNames": ["3 to 8 Korean tags"],
  "articlePatternId": "one allowed category pattern id",
  "articlePatternVersion": 4,
  "refactorNotes": "Short Korean note on what changed and any slug/title conflict."
}}
""".strip()


def _runtime() -> RuntimeProviderConfig:
    return RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="",
        openai_text_model="",
        openai_image_model="",
        topic_discovery_provider="codex_cli",
        topic_discovery_model="",
        gemini_api_key="",
        gemini_model="",
        blogger_access_token="",
        default_publish_mode="draft",
        text_runtime_kind="codex_cli",
        text_runtime_model="gpt-5.4",
        image_runtime_kind="none",
        codex_job_timeout_seconds=1200,
    )


def mode_generate_results(*, limit: int = 0, overwrite: bool = False, model: str = "gpt-5.4") -> dict[str, Any]:
    rows = _manifest_rows()
    if limit > 0:
        rows = rows[:limit]
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    PROMPT_ROOT.mkdir(parents=True, exist_ok=True)
    log_rows: list[dict[str, Any]] = []
    generated = 0
    failed = 0
    skipped = 0
    runtime = _runtime()
    for row in rows:
        packet_path = _packet_path_from_row(row)
        result_path = RESULT_ROOT / _result_name_from_packet(packet_path)
        prompt_path = PROMPT_ROOT / packet_path.with_suffix(".md").name
        item: dict[str, Any] = {
            "batch_order": row.get("batch_order"),
            "remote_post_id": row.get("remote_post_id"),
            "slug": row.get("slug"),
            "packet_path": str(packet_path),
            "result_path": str(result_path),
            "prompt_path": str(prompt_path),
        }
        if result_path.exists() and not overwrite:
            item["status"] = "skipped_existing"
            skipped += 1
            log_rows.append(item)
            continue
        try:
            packet = _load_json(packet_path)
            prompt = _build_codex_prompt(packet)
            prompt_path.write_text(prompt, encoding="utf-8")
            response = submit_codex_text_job(
                runtime=runtime,
                stage_name="cloudflare_p1_quality_refactor",
                model=model,
                prompt=prompt,
                response_kind="json_schema",
                response_schema=CODEX_RESULT_SCHEMA,
                timeout_seconds=1200,
                inline=True,
            )
            content = _strip_code_fences(_safe_text(response.get("content")))
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError("Codex response is not a JSON object.")
            payload["_packet_path"] = str(packet_path)
            payload["_generated_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(result_path, payload)
            item["status"] = "generated"
            item["log_path"] = response.get("log_path")
            generated += 1
        except Exception as exc:  # noqa: BLE001
            item["status"] = "failed"
            item["error"] = f"{type(exc).__name__}: {exc}"
            failed += 1
        log_rows.append(item)
    stamp = _stamp()
    _write_csv(P1_ROOT / f"p1-generation-{stamp}.csv", log_rows)
    _write_csv(P1_ROOT / "p1-generation-latest.csv", log_rows)
    summary = {
        "mode": "generate_results",
        "created_at": datetime.now().isoformat(),
        "generated_count": generated,
        "failed_count": failed,
        "skipped_count": skipped,
        "result_root": str(RESULT_ROOT),
    }
    _write_json(P1_ROOT / f"p1-generation-{stamp}.json", summary)
    _write_json(P1_ROOT / "p1-generation-latest.json", summary)
    return summary


def _load_packet_for_result(result_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    packet_ref = _safe_text(payload.get("_packet_path"))
    if packet_ref and Path(packet_ref).exists():
        return _load_json(Path(packet_ref))
    maybe = PACKET_ROOT / result_path.name
    if maybe.exists():
        return _load_json(maybe)
    raise FileNotFoundError(f"Packet for result not found: {result_path}")


def _normalize_result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tag_names = payload.get("tagNames")
    if not isinstance(tag_names, list):
        tag_names = []
    tag_names = [_safe_text(item).replace("#", "").strip() for item in tag_names if _safe_text(item)]
    normalized = {
        "title": _safe_text(payload.get("title")),
        "content": _safe_text(payload.get("content") or payload.get("html_article") or payload.get("body_html")),
        "excerpt": _safe_text(payload.get("excerpt")),
        "seoTitle": _safe_text(payload.get("seoTitle") or payload.get("seo_title") or payload.get("title")),
        "seoDescription": _safe_text(payload.get("seoDescription") or payload.get("seo_description") or payload.get("excerpt")),
        "tagNames": tag_names[:10],
        "articlePatternId": _safe_text(payload.get("articlePatternId") or payload.get("article_pattern_id")),
        "articlePatternVersion": int(payload.get("articlePatternVersion") or payload.get("article_pattern_version") or PATTERN_VERSION),
        "refactorNotes": _safe_text(payload.get("refactorNotes") or payload.get("refactor_notes")),
    }
    return normalized


def _validation_errors(payload: dict[str, Any], packet: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    body = _safe_text(payload.get("content"))
    if not payload.get("title"):
        errors.append("title_missing")
    if not body:
        errors.append("content_missing")
    if not payload.get("excerpt"):
        errors.append("excerpt_missing")
    if not payload.get("seoTitle"):
        errors.append("seoTitle_missing")
    if not payload.get("seoDescription"):
        errors.append("seoDescription_missing")
    if not payload.get("tagNames"):
        errors.append("tagNames_missing")
    for name, pattern in FORBIDDEN_BODY_PATTERNS:
        if pattern.search(body):
            errors.append(f"forbidden:{name}")
    if not body.lstrip().lower().startswith("<h2>핵심 요약</h2>"):
        errors.append("first_block_not_core_summary_h2")
    h2_count = len(H2_RE.findall(body))
    h3_count = len(H3_RE.findall(body))
    if h2_count < 4:
        errors.append(f"h2_count_below_4:{h2_count}")
    if h3_count < 2:
        errors.append(f"h3_count_below_2:{h3_count}")
    korean_count = _body_korean_syllables(body)
    if korean_count < MIN_KOREAN_SYLLABLES:
        errors.append(f"korean_syllable_count_below_{MIN_KOREAN_SYLLABLES}:{korean_count}")
    source = packet.get("source_row") if isinstance(packet.get("source_row"), dict) else {}
    detail = packet.get("remote_detail") if isinstance(packet.get("remote_detail"), dict) else {}
    category_slug = _category_slug(detail, _safe_text(source.get("category_slug")))
    hints = CATEGORY_RULE_HINTS.get(category_slug, {})
    plain = _plain_text(body)
    required_facts = hints.get("required_facts") or []
    required_hits = [fact for fact in required_facts if _safe_text(fact) and _safe_text(fact)[:2] in plain]
    if len(required_facts) >= 5 and len(required_hits) < max(3, len(required_facts) // 2):
        errors.append(f"required_fact_schema_weak:{len(required_hits)}/{len(required_facts)}")
    allowed_patterns = set(hints.get("patterns") or [])
    if allowed_patterns and _safe_text(payload.get("articlePatternId")) not in allowed_patterns:
        errors.append("article_pattern_not_allowed")
    if int(payload.get("articlePatternVersion") or 0) != PATTERN_VERSION:
        errors.append("article_pattern_version_not_4")
    score_payload = compute_seo_geo_scores(
        title=_safe_text(payload.get("seoTitle") or payload.get("title")),
        html_body=body,
        excerpt=_safe_text(payload.get("seoDescription") or payload.get("excerpt")),
        faq_section=[],
    )
    seo_score = int(score_payload.get("seo_score") or 0)
    geo_score = int(score_payload.get("geo_score") or 0)
    if seo_score < SEO_TARGET:
        errors.append(f"seo_below_{SEO_TARGET}:{seo_score}")
    if geo_score < GEO_TARGET:
        errors.append(f"geo_below_{GEO_TARGET}:{geo_score}")
    metrics = {
        "seo_score": seo_score,
        "geo_score": geo_score,
        "ctr_score": int(score_payload.get("ctr_score") or 0),
        "plain_text_length_reference": int(score_payload.get("plain_text_length") or len(plain)),
        "korean_syllable_count": korean_count,
        "h2_count": h2_count,
        "h3_count": h3_count,
        "score_payload": score_payload,
        "category_slug": category_slug,
        "required_fact_hits": required_hits,
    }
    return errors, metrics


def mode_validate_results() -> dict[str, Any]:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    VALIDATED_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    valid_count = 0
    failed_count = 0
    for result_path in sorted(RESULT_ROOT.glob("*.json")):
        row: dict[str, Any] = {"result_path": str(result_path), "status": "pending"}
        try:
            raw_payload = _load_json(result_path)
            payload = _normalize_result_payload(raw_payload)
            packet = _load_packet_for_result(result_path, raw_payload)
            errors, metrics = _validation_errors(payload, packet)
            status = "valid" if not errors else "failed"
            row.update(
                {
                    "status": status,
                    "errors": ";".join(errors),
                    "seo_score": metrics["seo_score"],
                    "geo_score": metrics["geo_score"],
                    "ctr_score": metrics["ctr_score"],
                    "korean_syllable_count": metrics["korean_syllable_count"],
                    "h2_count": metrics["h2_count"],
                    "h3_count": metrics["h3_count"],
                    "category_slug": metrics["category_slug"],
                    "slug": (packet.get("source_row") or {}).get("slug") if isinstance(packet.get("source_row"), dict) else "",
                    "remote_post_id": (packet.get("remote_detail") or {}).get("id") if isinstance(packet.get("remote_detail"), dict) else "",
                }
            )
            validated_payload = {"packet": packet, "result": payload, "metrics": metrics, "validation_errors": errors}
            target_root = VALIDATED_ROOT if status == "valid" else RETRY_ROOT
            _write_json(target_root / result_path.name, validated_payload)
            if status == "valid":
                valid_count += 1
            else:
                failed_count += 1
        except Exception as exc:  # noqa: BLE001
            row.update({"status": "failed", "errors": f"{type(exc).__name__}: {exc}"})
            failed_count += 1
        rows.append(row)
    stamp = _stamp()
    _write_csv(P1_ROOT / f"p1-result-validation-{stamp}.csv", rows)
    _write_csv(P1_ROOT / "p1-result-validation-latest.csv", rows)
    summary = {
        "mode": "validate_results",
        "created_at": datetime.now().isoformat(),
        "result_count": len(rows),
        "valid_count": valid_count,
        "failed_count": failed_count,
        "validated_root": str(VALIDATED_ROOT),
        "retry_root": str(RETRY_ROOT),
    }
    _write_json(P1_ROOT / f"p1-result-validation-{stamp}.json", summary)
    _write_json(P1_ROOT / "p1-result-validation-latest.json", summary)
    return summary


def _build_update_payload(detail: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    markdown_body = _html_to_markdown_body(_safe_text(result["content"]))
    description_fallback = " ".join(
        [
            _safe_text(result.get("title")),
            _plain_textish(_safe_text(result.get("content")))[:240],
        ]
    )
    publish_description = _normalize_publish_description(
        result.get("seoDescription") or result.get("excerpt"),
        fallback=description_fallback,
    )
    payload: dict[str, Any] = {
        "title": result["title"],
        "content": markdown_body,
        "excerpt": publish_description,
        "seoTitle": result["seoTitle"],
        "seoDescription": publish_description,
        "tagNames": result["tagNames"][:20],
        "status": _safe_text(detail.get("status") or "published") or "published",
    }
    cover_image = _safe_text(detail.get("coverImage"))
    cover_alt = _safe_text(detail.get("coverAlt"))
    category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    category_id = _safe_text(detail.get("categoryId") or category.get("id"))
    if cover_image:
        payload["coverImage"] = cover_image
    if cover_alt:
        payload["coverAlt"] = cover_alt
    if category_id:
        payload["categoryId"] = category_id
    return payload


def mode_apply_validated(*, limit: int = 0) -> dict[str, Any]:
    files = sorted(VALIDATED_ROOT.glob("*.json"))
    if limit > 0:
        files = files[:limit]
    APPLY_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    success_count = 0
    failed_count = 0
    with SessionLocal() as db:
        for path in files:
            item: dict[str, Any] = {"validated_path": str(path), "status": "pending"}
            try:
                payload = _load_json(path)
                packet = payload.get("packet")
                result = payload.get("result")
                metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
                if not isinstance(packet, dict) or not isinstance(result, dict):
                    raise ValueError("Validated file must contain packet/result objects.")
                detail = packet.get("remote_detail") if isinstance(packet.get("remote_detail"), dict) else {}
                remote_id = _safe_text(detail.get("id") or (packet.get("source_row") or {}).get("remote_post_id"))
                if not remote_id:
                    raise ValueError("remote_post_id missing.")
                latest_response = _integration_request(
                    db,
                    method="GET",
                    path=f"/api/integrations/posts/{quote(remote_id)}",
                    timeout=60.0,
                )
                latest_detail = _integration_data_or_raise(latest_response)
                if not isinstance(latest_detail, dict):
                    raise ValueError("remote detail response is not an object.")
                update_payload = _build_update_payload(latest_detail, result)
                response = _integration_request(
                    db,
                    method="PUT",
                    path=f"/api/integrations/posts/{quote(remote_id)}",
                    json_payload=update_payload,
                    timeout=120.0,
                )
                data = _integration_data_or_raise(response)
                post = db.execute(
                    select(SyncedCloudflarePost).where(SyncedCloudflarePost.remote_post_id == remote_id)
                ).scalar_one_or_none()
                if post is not None:
                    post.seo_score = float(metrics.get("seo_score") or 0)
                    post.geo_score = float(metrics.get("geo_score") or 0)
                    post.ctr = float(metrics.get("ctr_score") or 0)
                    post.quality_status = "p1_quality_refactored"
                    post.article_pattern_id = _safe_text(result.get("articlePatternId")) or post.article_pattern_id
                    post.article_pattern_version = PATTERN_VERSION
                    render_metadata = dict(post.render_metadata or {})
                    render_metadata["p1_quality_refactor"] = {
                        "applied_at": datetime.now(timezone.utc).isoformat(),
                        "seo_score": metrics.get("seo_score"),
                        "geo_score": metrics.get("geo_score"),
                        "ctr_score": metrics.get("ctr_score"),
                        "korean_syllable_count": metrics.get("korean_syllable_count"),
                    }
                    post.render_metadata = render_metadata
                db.commit()
                item.update(
                    {
                        "status": "applied",
                        "remote_post_id": remote_id,
                        "slug": _safe_text(latest_detail.get("slug") or (packet.get("source_row") or {}).get("slug")),
                        "updated_url": _safe_text(data.get("publicUrl") or data.get("url")) if isinstance(data, dict) else "",
                        "seo_score": metrics.get("seo_score"),
                        "geo_score": metrics.get("geo_score"),
                        "ctr_score": metrics.get("ctr_score"),
                    }
                )
                success_count += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                item.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
                failed_count += 1
            rows.append(item)
    stamp = _stamp()
    _write_csv(APPLY_ROOT / f"p1-apply-{stamp}.csv", rows)
    _write_csv(APPLY_ROOT / "p1-apply-latest.csv", rows)
    summary = {
        "mode": "apply_validated",
        "created_at": datetime.now().isoformat(),
        "input_count": len(files),
        "applied_count": success_count,
        "failed_count": failed_count,
        "apply_report": str(APPLY_ROOT / f"p1-apply-{stamp}.csv"),
    }
    _write_json(APPLY_ROOT / f"p1-apply-{stamp}.json", summary)
    _write_json(APPLY_ROOT / "p1-apply-latest.json", summary)
    return summary


def mode_sync_after_apply() -> dict[str, Any]:
    with SessionLocal() as db:
        result = sync_cloudflare_posts(db, include_non_published=True)
    summary = {
        "mode": "sync_after_apply",
        "created_at": datetime.now().isoformat(),
        "sync_result": result,
    }
    _write_json(P1_ROOT / f"p1-sync-after-apply-{_stamp()}.json", summary)
    _write_json(P1_ROOT / "p1-sync-after-apply-latest.json", summary)
    return summary


def _copy_if_exists(source: Path, dest_root: Path) -> None:
    if not source.exists():
        return
    if source.is_dir():
        target = dest_root / source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    else:
        dest_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest_root / source.name)


def mode_finalize_batch(*, remove_active_completed: bool = False) -> dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    backup_root = BACKUP_LOG_ROOT / today / "클라우드 품질 개선"
    backup_root.mkdir(parents=True, exist_ok=True)
    for source in (
        P1_ROOT / "p1-packet-manifest-latest.csv",
        P1_ROOT / "p1-packet-summary-latest.json",
        P1_ROOT / "p1-generation-latest.csv",
        P1_ROOT / "p1-generation-latest.json",
        P1_ROOT / "p1-result-validation-latest.csv",
        P1_ROOT / "p1-result-validation-latest.json",
        P1_ROOT / "p1-lighthouse-latest.csv",
        P1_ROOT / "p1-lighthouse-latest.json",
        APPLY_ROOT / "p1-apply-latest.csv",
        APPLY_ROOT / "p1-apply-latest.json",
        P1_ROOT / "p1-sync-after-apply-latest.json",
    ):
        _copy_if_exists(source, backup_root)
    _copy_if_exists(VALIDATED_ROOT, backup_root)
    _copy_if_exists(RETRY_ROOT, backup_root)
    _copy_if_exists(RENDERER_PERF_ROOT, backup_root)
    _copy_if_exists(P1_ROOT / "completed", backup_root)
    removed: list[str] = []
    if remove_active_completed and (APPLY_ROOT / "p1-apply-latest.csv").exists():
        rows = _read_csv(APPLY_ROOT / "p1-apply-latest.csv")
        if rows and all(_safe_text(row.get("status")) == "applied" for row in rows):
            for path in sorted(VALIDATED_ROOT.glob("*.json")):
                path.unlink(missing_ok=True)
                removed.append(str(path))
    summary = {
        "mode": "finalize_batch",
        "created_at": datetime.now().isoformat(),
        "backup_root": str(backup_root),
        "removed_active_files": removed,
    }
    _write_json(backup_root / "p1-finalize-summary.json", summary)
    _write_json(P1_ROOT / "p1-finalize-latest.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Cloudflare P1 quality 80 refactor batch.")
    parser.add_argument(
        "--mode",
        required=True,
        choices=("generate_results", "validate_results", "apply_validated", "sync_after_apply", "finalize_batch"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--remove-active-completed", action="store_true")
    args = parser.parse_args()

    if args.mode == "generate_results":
        result = mode_generate_results(limit=max(int(args.limit), 0), overwrite=bool(args.overwrite), model=args.model)
    elif args.mode == "validate_results":
        result = mode_validate_results()
    elif args.mode == "apply_validated":
        result = mode_apply_validated(limit=max(int(args.limit), 0))
    elif args.mode == "sync_after_apply":
        result = mode_sync_after_apply()
    else:
        result = mode_finalize_batch(remove_active_completed=bool(args.remove_active_completed))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
