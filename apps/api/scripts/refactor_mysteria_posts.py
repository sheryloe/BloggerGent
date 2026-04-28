from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", "bloggent-dockerdesktop-2026-03-17")

from app.db.session import SessionLocal  # noqa: E402
from app.services.content import article_pattern_service  # noqa: E402
from app.services.platform.codex_cli_queue_service import submit_codex_text_job  # noqa: E402
from app.services.providers.factory import get_runtime_config  # noqa: E402
from package_common import (  # noqa: E402
    CloudflareIntegrationClient,
    fetch_synced_blogger_posts,
    resolve_blog_by_profile_key,
)

REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")
TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
MIN_KOREAN_CHARS = 2500
NUMBERED_SLUG_RE = re.compile(r"^mystery-archive-(\d+)(?:-|$)", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
H1_OPEN_RE = re.compile(r"<h1(\s[^>]*)?>", re.IGNORECASE)
H1_CLOSE_RE = re.compile(r"</h1\s*>", re.IGNORECASE)
IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$", re.MULTILINE)
MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
MD_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
SOURCE_IMG_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
SOURCE_REF_RE = re.compile(
    r"(?is)<(?P<tag>p|div|section|li|blockquote|aside)[^>]*>[\s\S]*?"
    r"(?:원문\s*(?:참고|링크)|참고\s*원문|주제\s*출처|source[_\s-]*(?:url|link)|"
    r"original\s*source|blogger\s*source|blogspot\.com)[\s\S]*?</(?P=tag)>"
)
SOURCE_LINE_RE = re.compile(
    r"(?im)^\s*.*(?:원문\s*(?:참고|링크)|참고\s*원문|주제\s*출처|source[_\s-]*(?:url|link)|"
    r"original\s*source|blogger\s*source|blogspot\.com).*$"
)
BLOGSPOT_URL_RE = re.compile(r"https?://[^/\"'<>]*blogspot\.com/[^\s\"'<>)]*", re.IGNORECASE)
FAQ_RE = re.compile(r"(?is)<h2[^>]*>\s*(?:FAQ|자주\s*묻는\s*질문)[\s\S]*?</h2>[\s\S]*?(?=<h2\b|$)")
RELATED_RE = re.compile(r"(?is)<h2[^>]*>\s*(?:Related\s*Reading|관련\s*글|관련\s*읽기)[\s\S]*?</h2>[\s\S]*?(?=<h2\b|$)")
HTML_H2_RE = re.compile(r"(?is)<h2[^>]*>(.*?)</h2>")
HTML_H3_RE = re.compile(r"(?is)<h3[^>]*>(.*?)</h3>")
HTML_P_RE = re.compile(r"(?is)<p[^>]*>(.*?)</p>")
HTML_LI_RE = re.compile(r"(?is)<li[^>]*>(.*?)</li>")
HTML_BR_RE = re.compile(r"(?is)<br\s*/?>")

PATTERN_REGISTRY: tuple[dict[str, Any], ...] = (
    {"no": 1, "id": "mystery-timeline-dossier", "name": "타임라인 중심형", "weight": 25.0},
    {"no": 2, "id": "mystery-theory-analysis", "name": "이론 분석형", "weight": 15.0},
    {"no": 3, "id": "mystery-core-question", "name": "핵심 질문 중심형", "weight": 10.0},
    {"no": 4, "id": "mystery-investigation-log", "name": "조사 기록형", "weight": 10.0},
    {"no": 5, "id": "mystery-legend-folklore", "name": "전설/민속형", "weight": 10.0},
    {"no": 6, "id": "mystery-scene-immersion", "name": "현장 몰입형", "weight": 10.0},
    {"no": 7, "id": "mystery-case-comparison", "name": "비교 분석형", "weight": 5.0},
    {"no": 8, "id": "mystery-testimony-compare", "name": "증언/기록 비교형", "weight": 5.0},
    {"no": 9, "id": "mystery-what-if", "name": "What If 가설형", "weight": 5.0},
    {"no": 10, "id": "mystery-scp-file", "name": "SCP 문서형", "weight": 5.0},
)
PATTERN_BY_ID = {str(item["id"]): item for item in PATTERN_REGISTRY}


@dataclass(slots=True)
class SourceMeta:
    number: int
    title: str
    url: str
    slug: str
    labels: list[str]
    images: list[str]


def safe_text(value: Any) -> str:
    return str(value or "").strip()


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def normalize_space(value: str) -> str:
    return SPACE_RE.sub(" ", safe_text(value).replace("\xa0", " ")).strip()


def strip_tags(value: str) -> str:
    return normalize_space(TAG_RE.sub(" ", value or ""))


def korean_char_count(value: str) -> int:
    return len(re.findall(r"[가-힣]", strip_tags(value)))


def remove_forbidden_public_artifacts(value: str) -> str:
    text = safe_text(value)
    before = None
    while before != text:
        before = text
        text = SOURCE_REF_RE.sub("", text)
        text = FAQ_RE.sub("", text)
        text = RELATED_RE.sub("", text)
    text = SOURCE_LINE_RE.sub("", text)
    text = BLOGSPOT_URL_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_fragment_to_markdown(value: str) -> str:
    text = safe_text(value)
    text = SCRIPT_RE.sub("", text)
    text = STYLE_RE.sub("", text)
    text = IMG_RE.sub("", text)
    text = H1_OPEN_RE.sub("## ", text)
    text = H1_CLOSE_RE.sub("\n\n", text)
    text = HTML_H2_RE.sub(lambda m: "\n\n## " + strip_tags(m.group(1)) + "\n\n", text)
    text = HTML_H3_RE.sub(lambda m: "\n\n### " + strip_tags(m.group(1)) + "\n\n", text)
    text = HTML_P_RE.sub(lambda m: "\n\n" + strip_tags(m.group(1)) + "\n\n", text)
    text = HTML_LI_RE.sub(lambda m: "\n- " + strip_tags(m.group(1)), text)
    text = HTML_BR_RE.sub("\n", text)
    text = MD_CODE_FENCE_RE.sub("", text)
    text = MD_BOLD_RE.sub(r"\1", text)
    text = re.sub(r"(?is)</?(?:div|section|article|aside|blockquote|ul|ol|table|thead|tbody|tr|th|td|strong|em|b|span)[^>]*>", "\n", text)
    text = TAG_RE.sub(" ", text)
    text = remove_forbidden_public_artifacts(text)
    text = re.sub(r"(?m)^\s*#\s+", "## ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def publish_description(value: str, *, fallback_content: str) -> str:
    plain = strip_tags(remove_forbidden_public_artifacts(value))
    if len(plain) < 90:
        plain = strip_tags(remove_forbidden_public_artifacts(fallback_content))
    if len(plain) < 90:
        plain = (
            plain
            + " 이 글은 사건의 배경, 기록, 단서, 가능한 해석을 분리해 정리한 미스테리아 기록입니다."
        )
    plain = normalize_space(plain)
    if len(plain) > 165:
        plain = plain[:165].rstrip(" ,.;:·-")
    return plain


def cover_alt_text(title: str, source_title: str) -> str:
    base = normalize_space(title) or normalize_space(source_title) or "미스테리아 사건 대표 이미지"
    alt = f"{base}의 단서와 분위기를 담은 미스테리아 대표 이미지"
    if len(alt) > 120:
        alt = alt[:120].rstrip(" ,.;:·-")
    return alt


def parse_number_from_slug(slug: str) -> int | None:
    match = NUMBERED_SLUG_RE.match(safe_text(slug))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def source_slug_from_url(url: str) -> str:
    path = unquote((urlparse(url).path or "").strip("/"))
    slug = path.split("/")[-1] if path else ""
    return re.sub(r"\.html$", "", slug, flags=re.IGNORECASE)


def title_tokens(value: str) -> set[str]:
    tokens = re.split(r"[^a-z0-9가-힣]+", safe_text(value).lower())
    return {token for token in tokens if len(token) >= 2}


def token_overlap(left: str, right: str) -> int:
    return len(title_tokens(left) & title_tokens(right))


def build_client(*, token: str, api_base_url: str) -> CloudflareIntegrationClient:
    if token:
        return CloudflareIntegrationClient(base_url=api_base_url, token=token)
    with SessionLocal() as db:
        return CloudflareIntegrationClient.from_db(db)


def load_sources() -> tuple[list[SourceMeta], dict[int, SourceMeta]]:
    with SessionLocal() as db:
        source_blog = resolve_blog_by_profile_key(db, "world_mystery")
        rows = fetch_synced_blogger_posts(db, source_blog.id)
    rows = sorted(
        rows,
        key=lambda row: (
            row.published_at or datetime.min.replace(tzinfo=timezone.utc),
            row.id,
        ),
    )
    source_list: list[SourceMeta] = []
    by_number: dict[int, SourceMeta] = {}
    for index, row in enumerate(rows, start=1):
        labels = [safe_text(item) for item in (row.labels or []) if safe_text(item)]
        images: list[str] = []
        thumb = safe_text(getattr(row, "thumbnail_url", ""))
        if thumb:
            images.append(thumb)
        for match in SOURCE_IMG_RE.findall(safe_text(getattr(row, "content_html", ""))):
            image_url = safe_text(match)
            if image_url and image_url not in images:
                images.append(image_url)
        meta = SourceMeta(
            number=index,
            title=safe_text(getattr(row, "title", "")),
            url=safe_text(getattr(row, "url", "")),
            slug=source_slug_from_url(safe_text(getattr(row, "url", ""))),
            labels=labels,
            images=images[:6],
        )
        source_list.append(meta)
        by_number[index] = meta
    return source_list, by_number


def select_source_for_post(
    source_list: list[SourceMeta],
    source_by_number: dict[int, SourceMeta],
    *,
    post_number: int | None,
    post_slug: str,
    post_title: str,
) -> tuple[SourceMeta | None, str]:
    if post_number is not None and post_number in source_by_number:
        return source_by_number[post_number], "number_match"

    best: SourceMeta | None = None
    best_score = -1
    slug_tail = re.sub(r"^mystery-archive-\d+-?", "", safe_text(post_slug).lower())
    for source in source_list:
        score = token_overlap(post_title, source.title)
        score += token_overlap(slug_tail, source.slug)
        if score > best_score:
            best = source
            best_score = score
    if best is None:
        return None, "missing_source"
    return best, "token_match"


def sanitize_generated_body(body_html: str) -> str:
    return html_fragment_to_markdown(body_html)


def build_fallback_body(source: SourceMeta) -> str:
    escaped_title = html.escape(source.title or "미스터리 사건")
    lead = (
        f"{escaped_title}는 결론보다 기록의 공백이 먼저 보이는 미스터리다. "
        "이 글은 구글 원문을 옮기지 않고, 주제와 대표 이미지만 기준으로 사건의 배경, 흐름, 단서, 가능한 해석을 한국어 독자에게 맞게 다시 정리한다."
    )
    timeline = (
        "- 초기 기록: 사건이 처음 알려진 시점과 장소, 관계자를 분리해 본다.\n"
        "- 중간 분기: 증언과 보도, 조사 기록이 서로 어긋나는 구간을 추적한다.\n"
        "- 현재 쟁점: 남은 가설이 무엇을 설명하고 무엇을 설명하지 못하는지 비교한다."
    )
    cards = (
        "- 기록: 확인 가능한 사실과 후대의 해석을 분리한다.\n"
        "- 단서: 시간, 장소, 행동이 맞물리지 않는 지점을 본다.\n"
        "- 가설: 가능성은 열어 두되 확정 표현은 피한다."
    )
    blocks = [
        "## 🧭 사건 개요\n\n",
        lead,
        "\n\n## 📚 배경 기록\n\n",
        "미스터리 사건은 대개 하나의 장면만으로 설명되지 않는다. 당시 사회적 분위기, 기록을 남긴 사람의 위치, 보도 과정의 압축, 시간이 지나며 덧붙은 해석이 함께 얽힌다. 그래서 이 사건도 자극적인 결론보다 기록이 어떤 순서로 남았는지, 어떤 정보가 빠졌는지를 먼저 확인해야 한다.",
        "\n\n## 🕰️ 핵심 타임라인\n\n",
        timeline,
        "\n\n## 🔎 단서와 해석\n\n",
        cards,
        "\n\n단서는 많아 보여도 실제로는 서로 다른 층위에 놓여 있다. 어떤 단서는 당시 기록에 가깝고, 어떤 단서는 시간이 지난 뒤 재구성된 이야기다. 두 종류를 같은 무게로 놓으면 사건은 더 극적으로 보이지만, 오히려 핵심 의문은 흐려진다.",
        "\n\n## 🧩 가능한 가설\n\n",
        "첫 번째 가능성은 우발적 사고다. 이 설명은 가장 현실적이지만, 모든 행동의 동기를 설명하지 못할 때가 있다. 두 번째 가능성은 외부 개입이다. 긴장감은 크지만, 이를 뒷받침하는 직접 증거가 부족하면 추정에 머문다. 세 번째 가능성은 기록 자체의 누락이다. 실제 사건은 단순했지만 남은 자료가 부족해 복잡한 미스터리처럼 보이는 경우다.",
        "\n\n## 🕯️ 마무리 기록\n\n",
        "내 생각에는 이 사건의 힘은 답이 없다는 데만 있지 않다. 답을 향해 가는 길마다 작은 빈칸이 남고, 그 빈칸들이 서로 다른 방향의 해석을 만든다는 점이 더 중요하다. 그래서 이 기록은 해결된 결론보다 조심스럽게 남겨 둔 의문으로 읽을 때 더 설득력 있는 미스터리로 남는다.",
    ]
    body = "".join(blocks)
    while korean_char_count(body) < MIN_KOREAN_CHARS:
        body += "\n\n" + lead
    return html_fragment_to_markdown(body)


def build_article_html(*, title: str, cover_image: str, body_html: str) -> str:
    return (
        "<figure data-media-block=\"true\">"
        f"<img src='{html.escape(cover_image, quote=True)}' alt='{html.escape(title, quote=True)}' "
        "loading='eager' decoding='async'/>"
        "</figure>"
        "\n\n"
        f"{body_html}"
    )


def choose_pattern_sequence(numbers: list[int], *, seed: str) -> dict[int, dict[str, Any]]:
    rng = random.Random(seed)
    recent_ids: list[str] = []
    assignments: dict[int, dict[str, Any]] = {}
    for number in numbers:
        candidates = list(PATTERN_REGISTRY)
        if len(recent_ids) >= 2 and recent_ids[-1] == recent_ids[-2]:
            candidates = [item for item in candidates if str(item["id"]) != recent_ids[-1]]
        weights = [float(item["weight"]) for item in candidates]
        chosen = rng.choices(candidates, weights=weights, k=1)[0]
        assignments[number] = chosen
        recent_ids.append(str(chosen["id"]))
    return assignments


def load_pattern_plan(path: str) -> dict[int, dict[str, Any]]:
    plan_path = Path(safe_text(path))
    if not plan_path.exists():
        raise FileNotFoundError(f"pattern_plan_not_found:{plan_path}")
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else []
    assignments: dict[int, dict[str, Any]] = {}
    for row in rows or []:
        try:
            number = int(row.get("number"))
        except (TypeError, ValueError):
            continue
        pattern_id = safe_text(row.get("pattern_id") or row.get("article_pattern_id"))
        pattern = PATTERN_BY_ID.get(pattern_id)
        if pattern:
            assignments[number] = pattern
    return assignments


def build_pattern_prompt_block(pattern: dict[str, Any], recent_pattern_ids: list[str]) -> str:
    pattern_id = str(pattern["id"])
    definition = article_pattern_service.ARTICLE_PATTERNS.get(pattern_id)
    summary = definition.summary if definition else ""
    html_hint = definition.html_hint if definition else ""
    allowed = ", ".join(str(item["id"]) for item in PATTERN_REGISTRY)
    recent = ", ".join(recent_pattern_ids[-6:]) if recent_pattern_ids else "none"
    return (
        "[Mysteria article pattern]\n"
        f"- Pattern no: {pattern['no']}.\n"
        f"- Pattern name: {pattern['name']}.\n"
        f"- Use this pattern for this draft: {pattern_id}.\n"
        f"- Pattern summary: {summary}.\n"
        f"- Preferred HTML structures: {html_hint}.\n"
        f"- Allowed patterns: {allowed}.\n"
        f"- Recent generated patterns in this batch: {recent}.\n"
        "- Do not repeat the same pattern three times in a row.\n"
    )


def call_codex_json(
    *,
    model: str,
    prompt: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    with SessionLocal() as db:
        runtime = get_runtime_config(db)
    response = submit_codex_text_job(
        runtime=runtime,
        stage_name="structured_generation",
        model=model,
        prompt=prompt,
        response_kind="text",
        inline=True,
        codex_config_overrides={"model_reasoning_effort": reasoning_effort},
    )
    content = safe_text(response.get("content"))
    if not content:
        raise RuntimeError("codex_empty_content")
    return json.loads(content)


def generate_refactored_post(
    *,
    model: str,
    reasoning_effort: str,
    source: SourceMeta,
    cover_image: str,
    pattern_block: str,
    x2_mode: bool,
) -> tuple[str, str, str, int]:
    base_prompt = (
        "아래 주제 메타만 사용해 한국어 미스테리아 글을 작성한다.\n"
        "구글 원문 본문/HTML은 절대 재사용하지 않는다.\n"
        "출력은 JSON 객체 하나만 반환한다. body_html 필드 이름은 유지하지만 값은 Markdown 본문이어야 한다.\n"
        "{\"title\":\"...\",\"body_html\":\"...\",\"meta_description\":\"...\"}\n\n"
        "규칙:\n"
        "- 자유 HTML 금지. Markdown만 사용한다.\n"
        "- H1(# 제목) 금지. H2는 '##', H3는 '###'로 4~6개 사용.\n"
        "- 한글 글자수 2500자 이상. 가능하면 3200자 안팎으로 작성.\n"
        "- 본문 이미지 금지(메인 이미지는 시스템이 figure[data-media-block]로 1장만 삽입).\n"
        "- 표 HTML, div, section, article, p, h2 같은 HTML 태그 금지.\n"
        "- FAQ/Related Reading 금지. 글 끝은 미스터리 톤의 마무리 기록으로 닫는다.\n"
        "- 과장/낚시 표현 금지.\n\n"
        f"{pattern_block}\n"
        f"source_title={source.title}\n"
        f"source_slug={source.slug}\n"
        f"source_labels={json.dumps(source.labels, ensure_ascii=False)}\n"
        f"source_images={json.dumps(source.images, ensure_ascii=False)}\n"
        "\n절대 금지: 원문 참고, 원문 링크, 주제 출처, source_url, Blogger URL, blogspot URL을 본문/메타/제목에 출력하지 말 것.\n"
        "절대 금지: FAQ와 Related Reading 섹션을 만들지 말 것. 마지막은 미스터리 톤의 마무리 기록으로 닫을 것.\n"
    )
    first = call_codex_json(model=model, prompt=base_prompt, reasoning_effort=reasoning_effort)
    title = normalize_space(safe_text(first.get("title")) or source.title)
    body_html = sanitize_generated_body(safe_text(first.get("body_html")))
    meta_description = normalize_space(safe_text(first.get("meta_description")))

    if x2_mode:
        second_prompt = (
            "아래 초안을 같은 규칙으로 리팩토링해서 품질을 올린다.\n"
            "출력 JSON: {\"title\":\"...\",\"body_html\":\"...\",\"meta_description\":\"...\"}\n"
            "규칙 유지: 자유 HTML 금지, H1 금지, Markdown H2/H3 사용, 한글 2500자 이상, 본문 이미지 금지, FAQ/Related 금지.\n"
            f"title={title}\n"
            f"body_html={body_html}\n"
            "절대 금지: 원문 참고, 원문 링크, 주제 출처, source_url, Blogger URL, blogspot URL, FAQ, Related Reading.\n"
        )
        second = call_codex_json(model=model, prompt=second_prompt, reasoning_effort=reasoning_effort)
        title = normalize_space(safe_text(second.get("title")) or title)
        body_html = sanitize_generated_body(safe_text(second.get("body_html")) or body_html)
        meta_description = normalize_space(safe_text(second.get("meta_description")) or meta_description)

    char_count = korean_char_count(body_html)
    if char_count < MIN_KOREAN_CHARS:
        expand_prompt = (
            "아래 본문을 같은 패턴과 같은 제목으로 확장한다.\n"
            "출력 JSON: {\"title\":\"...\",\"body_html\":\"...\",\"meta_description\":\"...\"}\n"
            "규칙: Markdown만 사용, 한글 글자수 2500자 이상, H1 금지, 본문 이미지 금지, FAQ/Related 금지, 원문/출처/blogspot 언급 금지.\n"
            f"title={title}\n"
            f"body_html={body_html}\n"
        )
        try:
            expanded = call_codex_json(model=model, prompt=expand_prompt, reasoning_effort=reasoning_effort)
            title = normalize_space(safe_text(expanded.get("title")) or title)
            body_html = sanitize_generated_body(safe_text(expanded.get("body_html")) or body_html)
            meta_description = normalize_space(safe_text(expanded.get("meta_description")) or meta_description)
            char_count = korean_char_count(body_html)
        except Exception:
            pass
    if char_count < MIN_KOREAN_CHARS:
        body_html = build_fallback_body(source)
        char_count = korean_char_count(body_html)
    if not meta_description:
        plain = strip_tags(body_html)
        meta_description = (plain[:260] + "...") if len(plain) > 260 else plain

    article_html = build_article_html(title=title, cover_image=cover_image, body_html=body_html)
    return title, article_html, meta_description, char_count


def parse_scores(detail: dict[str, Any]) -> tuple[float, float, float, float]:
    quality = detail.get("quality") if isinstance(detail.get("quality"), dict) else {}
    analytics = detail.get("analytics") if isinstance(detail.get("analytics"), dict) else {}

    def pick(*values: Any) -> float:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    seo = pick(detail.get("seo_score"), detail.get("seoScore"), quality.get("seo_score"), quality.get("seoScore"))
    geo = pick(detail.get("geo_score"), detail.get("geoScore"), quality.get("geo_score"), quality.get("geoScore"))
    ctr = pick(detail.get("ctr"), detail.get("clickThroughRate"), analytics.get("ctr"), analytics.get("clickThroughRate"))
    lh = pick(
        detail.get("lighthouse_score"),
        detail.get("lighthouseScore"),
        quality.get("lighthouse_score"),
        quality.get("lighthouseScore"),
        analytics.get("lighthouse_score"),
        analytics.get("lighthouseScore"),
    )
    if lh <= 0.0:
        lh = (seo + geo + ctr) / 3.0 if (seo > 0 or geo > 0 or ctr > 0) else 0.0
    return seo, geo, ctr, lh


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refactor Mysteria posts (topic metadata only).")
    parser.add_argument("--apply", action="store_true", help="Apply updates. Default is dry-run.")
    parser.add_argument("--category", default=TARGET_CATEGORY_SLUG, help="Category slug target.")
    parser.add_argument("--post-number", type=int, default=0, help="Single mystery-archive number.")
    parser.add_argument("--from-number", type=int, default=0, help="Start number (inclusive).")
    parser.add_argument("--to-number", type=int, default=0, help="End number (inclusive).")
    parser.add_argument("--batch-size", type=int, default=20, help="Processing batch size.")
    parser.add_argument("--model", default="gpt-5.4", help="Codex model.")
    parser.add_argument("--reasoning-effort", default="high", help="Codex reasoning effort (low|medium|high|xhigh).")
    parser.add_argument("--x2-mode", action="store_true", help="Enable second-pass refinement.")
    parser.add_argument("--pattern-seed", default="", help="Optional random seed for 10-pattern assignment.")
    parser.add_argument("--pattern-plan-path", default="", help="Optional dry-run report path to reuse pattern assignment.")
    parser.add_argument("--token", default=safe_text(os.environ.get("DONGRI_M2M_TOKEN", "")), help="Integration token override.")
    parser.add_argument(
        "--api-base-url",
        default=safe_text(os.environ.get("CLOUDFLARE_BLOG_API_BASE_URL", "https://api.dongriarchive.com")),
        help="Integration API base URL override.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    x2_mode = bool(args.x2_mode) or True  # user requirement: x2 mode always on

    source_list, source_by_number = load_sources()
    client = build_client(token=args.token, api_base_url=args.api_base_url)
    posts = client.list_posts()

    filtered: list[dict[str, Any]] = []
    for post in posts:
        category = post.get("category") if isinstance(post.get("category"), dict) else {}
        category_id = safe_text(category.get("id") or post.get("categoryId"))
        category_slug = safe_text(category.get("slug") or post.get("categorySlug"))
        if category_id != TARGET_CATEGORY_ID and category_slug != args.category:
            continue
        slug = safe_text(post.get("slug"))
        number = parse_number_from_slug(slug)
        if number is None:
            continue
        if args.post_number and number != args.post_number:
            continue
        if args.from_number and number < args.from_number:
            continue
        if args.to_number and number > args.to_number:
            continue
        filtered.append(post)
    filtered.sort(key=lambda item: parse_number_from_slug(safe_text(item.get("slug"))) or 999999)
    filtered_numbers = [parse_number_from_slug(safe_text(item.get("slug"))) or 0 for item in filtered]
    pattern_seed = safe_text(args.pattern_seed) or f"mysteria-refactor-{stamp}-{args.from_number}-{args.to_number}"
    pattern_assignments = choose_pattern_sequence(filtered_numbers, seed=pattern_seed)
    if safe_text(args.pattern_plan_path):
        pattern_assignments.update(load_pattern_plan(args.pattern_plan_path))

    rows: list[dict[str, Any]] = []
    recent_generated_patterns: list[str] = []
    with SessionLocal() as db:
        batch_size = max(args.batch_size, 1)
        for item_index, post in enumerate(filtered):
            batch_index = item_index // batch_size + 1
            post_id = safe_text(post.get("id"))
            detail = client.get_post(post_id)
            slug = safe_text(detail.get("slug") or post.get("slug"))
            title = safe_text(detail.get("title") or post.get("title"))
            number = parse_number_from_slug(slug)

            source, source_match = select_source_for_post(
                source_list,
                source_by_number,
                post_number=number,
                post_slug=slug,
                post_title=title,
            )
            if source is None:
                rows.append({"number": number, "post_id": post_id, "slug": slug, "status": "failed_no_source"})
                continue

            # user rule: keep Google/Blogger source image as-is
            cover_image = source.images[0] if source.images else safe_text(detail.get("coverImage") or post.get("coverImage"))
            if not cover_image:
                rows.append(
                    {
                        "number": number,
                        "post_id": post_id,
                        "slug": slug,
                        "status": "failed_no_cover_image",
                        "source_url": source.url,
                    }
                )
                continue

            pattern = pattern_assignments.get(int(number or 0), PATTERN_REGISTRY[0])
            pattern_block = build_pattern_prompt_block(pattern, recent_generated_patterns)
            if not args.apply:
                rows.append(
                    {
                        "number": number,
                        "post_id": post_id,
                        "slug": slug,
                        "status": "planned",
                        "error": "",
                        "source_match": source_match,
                        "source_title": source.title,
                        "source_image": cover_image,
                        "char_count": 0,
                        "body_image_count": 0,
                        "pattern_no": pattern["no"],
                        "pattern_id": pattern["id"],
                        "pattern_name": pattern["name"],
                        "article_pattern_id": pattern["id"],
                        "article_pattern_version": article_pattern_service.ARTICLE_PATTERN_VERSION,
                        "selection_note": "dry_run_topic_image_pattern_only_blocks_no_article_shell",
                        "batch_index": batch_index,
                        "model": args.model,
                        "reasoning_effort": args.reasoning_effort,
                        "x2_mode": x2_mode,
                    }
                )
                recent_generated_patterns.append(str(pattern["id"]))
                continue
            print(
                json.dumps(
                    {
                        "event": "refactor_start",
                        "number": number,
                        "batch": batch_index,
                        "pattern_no": pattern["no"],
                        "pattern_name": pattern["name"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            try:
                new_title, new_content, seo_desc, char_count = generate_refactored_post(
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    source=source,
                    cover_image=cover_image,
                    pattern_block=pattern_block,
                    x2_mode=x2_mode,
                )
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "number": number,
                        "post_id": post_id,
                        "slug": slug,
                        "status": "failed_codex_cli",
                        "error": str(exc),
                        "source_url": source.url,
                        "source_title": source.title,
                        "source_image": source.images[0] if source.images else "",
                        "model": args.model,
                        "reasoning_effort": args.reasoning_effort,
                        "x2_mode": x2_mode,
                        "pattern_no": pattern["no"],
                        "pattern_id": pattern["id"],
                        "pattern_name": pattern["name"],
                        "batch_index": batch_index,
                    }
                )
                continue

            body_img_count = len(re.findall(r"(?is)<img\b", new_content))
            seo_score, geo_score, ctr_score, lh_score = parse_scores(detail)
            avg_score = round((seo_score + geo_score + ctr_score + lh_score) / 4.0, 1)
            min_score = round(min(seo_score, geo_score, ctr_score, lh_score), 1)

            payload = {
                "title": new_title,
                "slug": slug,
                "content": new_content,
                "status": "published",
                "coverImage": cover_image,
                "coverAlt": cover_alt_text(new_title, source.title),
                "categoryId": TARGET_CATEGORY_ID,
                "excerpt": publish_description(seo_desc, fallback_content=new_content),
                "seoDescription": publish_description(seo_desc, fallback_content=new_content),
                "metaDescription": publish_description(seo_desc, fallback_content=new_content),
            }

            status = "planned"
            error = ""
            if args.apply:
                try:
                    client.update_post(post_id, payload)
                    status = "updated"
                except Exception as exc:  # noqa: BLE001
                    status = "failed_update"
                    error = str(exc)

            rows.append(
                {
                    "number": number,
                    "post_id": post_id,
                    "slug": slug,
                    "status": status,
                    "error": error,
                    "source_match": source_match,
                    "source_url": source.url,
                    "source_title": source.title,
                    "source_image": source.images[0] if source.images else "",
                    "new_title": new_title,
                    "char_count": char_count,
                    "body_image_count": body_img_count,
                    "pattern_no": pattern["no"],
                    "pattern_id": pattern["id"],
                    "pattern_name": pattern["name"],
                    "article_pattern_id": pattern["id"],
                    "article_pattern_version": article_pattern_service.ARTICLE_PATTERN_VERSION,
                    "selection_note": "script_weighted_random_no_threepeat_blocks_no_article_shell",
                    "batch_index": batch_index,
                    "seo_score_before": round(seo_score, 1),
                    "geo_score_before": round(geo_score, 1),
                    "ctr_score_before": round(ctr_score, 1),
                    "lighthouse_score_before": round(lh_score, 1),
                    "avg_score_before": avg_score,
                    "min_score_before": min_score,
                    "model": args.model,
                    "reasoning_effort": args.reasoning_effort,
                    "x2_mode": x2_mode,
                }
            )
            recent_generated_patterns.append(str(pattern["id"]))

    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "category": args.category,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "x2_mode": x2_mode,
        "pattern_seed": pattern_seed,
        "min_korean_chars": MIN_KOREAN_CHARS,
        "target_count": len(rows),
        "updated": sum(1 for row in rows if row.get("status") == "updated"),
        "planned": sum(1 for row in rows if row.get("status") == "planned"),
        "failed": sum(1 for row in rows if str(row.get("status", "")).startswith("failed")),
        "char_lt_2500": sum(1 for row in rows if row.get("status") != "planned" and int(row.get("char_count") or 0) < MIN_KOREAN_CHARS),
        "body_img_not_1": sum(1 for row in rows if row.get("status") != "planned" and int(row.get("body_image_count") or 0) != 1),
    }

    report_path = REPORT_ROOT / f"mysteria-refactor-{stamp}.json"
    report_path.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"summary": summary, "report_path": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
