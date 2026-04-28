from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal
from app.services.providers.factory import get_article_provider
from app.services.integrations.settings_service import get_settings_map


DEFAULT_SCORE_THRESHOLD = 80
DEFAULT_BATCH_SIZE = 10
DEFAULT_MODEL = "gpt-5.2"

DEFAULT_CATEGORY_ORDER = [
    "개발과-프로그래밍",
    "여행과-기록",
    "축제와-현장",
    "문화와-공간",
    "미스테리아-스토리",
    "일상과-메모",
    "동그리의-생각",
    "삶을-유용하게",
    "주식의-흐름",
    "나스닥의-흐름",
    "크립토의-흐름",
    "삶의-기름칠",
]

IMAGE_HTML_RE = re.compile(r"(?is)<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"][^>]*>")
IMAGE_MD_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_TABLE_RE = re.compile(r"(?is)<table\b")
TAG_RE = re.compile(r"(?is)<[^>]+>")
IMG_TAG_RE = re.compile(r"(?is)<img\b[^>]*>")
FIGURE_BLOCK_RE = re.compile(r"(?is)<figure\b[^>]*>.*?</figure>")


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").replace("\\xa0", " ").split())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _load_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key:
                continue
            os.environ.setdefault(key, value.strip())
    os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent")
    os.environ.setdefault("STORAGE_ROOT", str(REPO_ROOT / "storage"))


def _storage_root() -> Path:
    return Path(os.environ.get("STORAGE_ROOT") or "").resolve()


def _ops_root() -> Path:
    return _storage_root() / "ops" / "cloudflare_auto_refactor"


def _state_path() -> Path:
    return _ops_root() / "state.json"


def _work_dir(stamp: str) -> Path:
    return _ops_root() / "work" / stamp


def _report_dir(day: str) -> Path:
    return _ops_root() / "reports" / day


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _http_200(url: str) -> bool:
    target = _normalize_space(url)
    if not target:
        return False
    try:
        response = httpx.get(target, follow_redirects=True, timeout=20.0)
        return int(response.status_code) == 200
    except Exception:
        return False


def _integration_client_from_db(db) -> tuple[str, str]:
    values = get_settings_map(db)
    base_url = _normalize_space(values.get("cloudflare_blog_api_base_url")).rstrip("/")
    token = _normalize_space(values.get("cloudflare_blog_m2m_token"))
    if not base_url or not token:
        raise RuntimeError("Cloudflare integration settings are missing (base_url/token).")
    return base_url, token


def _integration_request(base_url: str, token: str, *, method: str, path: str, json_payload: dict | None = None) -> Any:
    response = httpx.request(
        method=method,
        url=f"{base_url}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json=json_payload,
        timeout=120.0,
    )
    try:
        payload: Any = response.json()
    except ValueError:
        payload = {}
    if not response.is_success:
        detail = response.text
        if isinstance(payload, dict):
            detail = str(payload.get("message") or payload.get("detail") or payload.get("error") or detail)
        raise RuntimeError(f"Cloudflare integration request failed ({response.status_code}): {detail}")
    if isinstance(payload, dict):
        if payload.get("success") is False:
            raise RuntimeError(f"Cloudflare integration error: {payload.get('error') or payload}")
        if "data" in payload:
            return payload["data"]
    return payload


def _extract_inline_images(content: str) -> list[str]:
    body = str(content or "")
    urls: list[str] = []
    seen: set[str] = set()
    for match in IMAGE_HTML_RE.finditer(body):
        url = _normalize_space(match.group(1))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    for match in IMAGE_MD_RE.finditer(body):
        url = _normalize_space(match.group(1))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _strip_all_but_first_inline_image(content: str) -> tuple[str, dict[str, Any]]:
    body = str(content or "")
    urls = _extract_inline_images(body)
    if len(urls) <= 1:
        return body, {"inline_image_count_before": len(urls), "inline_image_count_after": len(urls), "kept_inline_url": urls[0] if urls else ""}
    keep = urls[0]

    def _replace_html(match: re.Match[str]) -> str:
        url = _normalize_space(match.group(1))
        return match.group(0) if url == keep else ""

    def _replace_md(match: re.Match[str]) -> str:
        url = _normalize_space(match.group(1))
        return match.group(0) if url == keep else ""

    stripped = IMAGE_HTML_RE.sub(_replace_html, body)
    stripped = IMAGE_MD_RE.sub(_replace_md, stripped)
    stripped = re.sub(r"\\n{3,}", "\\n\\n", stripped).strip()
    return stripped, {"inline_image_count_before": len(urls), "inline_image_count_after": 1, "kept_inline_url": keep}


def _strip_all_html_images(content: str) -> str:
    body = str(content or "")
    body = FIGURE_BLOCK_RE.sub("", body)
    body = IMG_TAG_RE.sub("", body)
    body = re.sub(r"\\n{3,}", "\\n\\n", body).strip()
    return body


def _inject_inline_image_once(html_article: str, inline_url: str) -> str:
    url = _normalize_space(inline_url)
    if not url:
        return html_article
    body = _strip_all_html_images(html_article)
    figure = f'\\n<figure>\\n  <img src="{url}" alt="본문 이미지" />\\n</figure>\\n'
    # Insert after first </h2> if present, else after first </p>, else append.
    h2_end = body.lower().find("</h2>")
    if h2_end != -1:
        return body[: h2_end + 5] + figure + body[h2_end + 5 :]
    p_end = body.lower().find("</p>")
    if p_end != -1:
        return body[: p_end + 4] + figure + body[p_end + 4 :]
    return body + figure


def _strip_tags(text_value: str) -> str:
    return _normalize_space(TAG_RE.sub(" ", str(text_value or "")))


def _count_sentences_korean(text_value: str) -> int:
    text = _normalize_space(_strip_tags(text_value))
    if not text:
        return 0
    # Primary: count explicit sentence terminators.
    explicit = re.findall(r"[.!?]", text)
    if explicit:
        return len(explicit)
    # Fallback: Korean endings when punctuation is omitted.
    fallback = re.findall(r"(습니다|입니다|해요|했어요|했다|한다|된다|하다)(?=\\s|$)", text)
    return max(1, len(fallback)) if text else 0


def _extract_closing_paragraph(content: str) -> str:
    body = str(content or "")
    matches = list(re.finditer(r"(?is)<h2\b[^>]*>\s*마무리\s*기록\s*</h2>", body))
    if not matches:
        return ""
    tail = body[matches[-1].end() :]
    paragraph_match = re.search(r"(?is)<p\b[^>]*>(.*?)</p>", tail)
    return paragraph_match.group(1) if paragraph_match else ""


def _has_table(content: str) -> bool:
    return bool(HTML_TABLE_RE.search(str(content or "")))


def _daily_memo_topic_fit_ok(content: str) -> bool:
    plain = _strip_tags(content).casefold()
    required = ["오늘", "하루", "힘들", "재미", "기분", "장면", "기억", "저녁", "아침"]
    score = sum(1 for token in required if token in plain)
    banned = ["단서", "추적", "사건", "미제", "증거", "타임라인"]
    banned_hit = any(token in plain for token in banned)
    return score >= 2 and not banned_hit


def _read_category_prompt(category_slug: str) -> str:
    base = REPO_ROOT / "prompts" / "channels" / "cloudflare" / "dongri-archive"
    mapping = {
        "개발과-프로그래밍": "gaebalgwa-peurogeuraeming",
        "일상과-메모": "ilsanggwa-memo",
        "여행과-기록": "yeohaenggwa-girog",
        "축제와-현장": "cugjewa-hyeonjang",
        "문화와-공간": "munhwawa-gonggan",
        "미스테리아-스토리": "miseuteria-seutori",
        "동그리의-생각": "donggeuriyi-saenggag",
        "삶을-유용하게": "salmeul-yuyonghage",
        "삶의-기름칠": "salmyi-gireumcil",
        "주식의-흐름": "jusigyi-heureum",
        "나스닥의-흐름": "naseudagyi-heureum",
        "크립토의-흐름": "keuribtoyi-heureum",
    }
    leaf = mapping.get(category_slug, "")
    if not leaf:
        return ""
    candidates = [
        base / "동그리의 기록" / leaf / "article_generation.md",
        base / "정보의 기록" / leaf / "article_generation.md",
        base / "세상의 기록" / leaf / "article_generation.md",
        base / "생활의 기록" / leaf / "article_generation.md",
        base / "시장의 기록" / leaf / "article_generation.md",
        base / leaf / "article_generation.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def _ensure_minimum_table(html_article: str, *, category_slug: str) -> str:
    if _has_table(html_article):
        return html_article
    # Insert a small, meaningful table to satisfy the HTML/table requirement.
    checklist_rows: list[tuple[str, str, str]] = []
    if category_slug == "개발과-프로그래밍":
        checklist_rows = [
            ("입력/출력 경계", "자동화 범위를 정하지 않으면 품질이 흔들립니다.", "필수 검증 단계와 금지 항목을 먼저 고정합니다."),
            ("비용/쿼터", "호출량이 늘면 운영비가 바로 튑니다.", "측정 지표와 알림 기준을 정리합니다."),
            ("리뷰 루프", "초안이 빨라도 검증이 느리면 의미가 없습니다.", "PR/테스트/로그 기준을 한 장으로 묶습니다."),
        ]
    elif category_slug == "일상과-메모":
        checklist_rows = [
            ("오늘의 장면", "기억은 디테일에서 살아남습니다.", "한 장면을 1문장으로 적습니다."),
            ("감정의 마찰", "힘들었던 포인트가 재료가 됩니다.", "왜 거슬렸는지 1문장으로 붙입니다."),
            ("작은 결론", "내일의 행동이 남아야 합니다.", "내일 한 번만 해볼 행동을 적습니다."),
        ]
    else:
        checklist_rows = [
            ("핵심 포인트", "글의 중심이 흐려지면 CTR이 떨어집니다.", "첫 단락에서 결론을 1문장으로 고정합니다."),
            ("비교/판단", "독자는 선택 기준을 원합니다.", "표로 기준을 3개만 정리합니다."),
            ("다음 행동", "읽고 끝나면 남는 게 없습니다.", "오늘 할 1가지/이번 주 할 1가지를 적습니다."),
        ]

    table_lines = [
        '<table border="1" cellpadding="8" cellspacing="0">',
        "  <thead>",
        "    <tr>",
        "      <th>체크포인트</th>",
        "      <th>왜 중요한가</th>",
        "      <th>다음 행동</th>",
        "    </tr>",
        "  </thead>",
        "  <tbody>",
    ]
    for a, b, c in checklist_rows:
        table_lines.append("    <tr>")
        table_lines.append(f"      <td>{a}</td>")
        table_lines.append(f"      <td>{b}</td>")
        table_lines.append(f"      <td>{c}</td>")
        table_lines.append("    </tr>")
    table_lines.extend(["  </tbody>", "</table>"])
    table_html = "\n".join(table_lines) + "\n"

    body = html_article.strip()
    h2_end = body.lower().find("</h2>")
    if h2_end != -1:
        return body[: h2_end + 5] + "\n" + table_html + body[h2_end + 5 :]
    p_end = body.lower().find("</p>")
    if p_end != -1:
        return body[: p_end + 4] + "\n" + table_html + body[p_end + 4 :]
    return table_html + body


def _ensure_closing_record(html_article: str, *, title: str) -> str:
    body = str(html_article or "").strip()
    # Remove trailing garbage after last closing record if present, and re-append a clean closing.
    body = re.sub(r"(?is)<h2\b[^>]*>\s*마무리\s*기록\s*</h2>.*$", "", body).strip()
    closing = (
        f"<h2>마무리 기록</h2>\n"
        f"<p>{title}를 읽고 나면 결국 남는 건 ‘무엇을 선택하고 무엇을 버릴지’에 대한 기준입니다. "
        f"오늘은 하나만 고르고, 내일 다시 한 번 점검해 보세요.</p>\n"
    )
    return (body + "\n\n" + closing).strip()


def _build_generation_prompt(
    *,
    base_prompt: str,
    category_slug: str,
    fixed_slug: str,
    title: str,
    excerpt: str,
    seo_score: float | None,
    geo_score: float | None,
    ctr: float | None,
    lighthouse_score: float | None,
    avg_score: int,
    current_content: str,
    kept_inline_url: str,
    has_inline: bool,
    mode: str,
) -> str:
    daily_memo_fit = ""
    if category_slug == "일상과-메모":
        daily_memo_fit = (
            "\n[Daily Memo Fit]\n"
            "- '일상과-메모'는 정보글/가이드가 아니라, 오늘의 장면과 감정의 마찰을 기록하는 글이어야 합니다.\n"
            "- 반드시 '오늘/하루/힘들/재미/기분/장면/기억' 같은 일상 서사 토큰이 드러나야 합니다.\n"
            "- '단서/추적/사건/미제/증거/타임라인'은 금지합니다.\n"
        )
    # NOTE: category prompt may require "html_article free of raw image tags".
    # We enforce that: model must output html_article WITHOUT <img>. We inject 0/1 inline image after generation.
    inline_rule = "html_article에는 <img> 태그를 절대 넣지 마세요(0개)."
    inline_block = "인라인 이미지는 시스템이 기존 본문에서 1개만 보존해 주입합니다." if has_inline else "인라인 이미지가 없으면 시스템이 주입하지 않습니다."
    return (
        f"{base_prompt.strip()}\n\n"
        f"[Input]\n"
        f"- category_slug: {category_slug}\n"
        f"- fixed_slug: {fixed_slug}\n"
        f"- current_title: {title}\n"
        f"- current_excerpt: {excerpt}\n"
        f"- current_scores: seo={seo_score} geo={geo_score} ctr={ctr} lh={lighthouse_score} avg={avg_score}\n"
        f"- rewrite_mode: {mode}  (light if avg>=80, heavy if avg<80)\n"
        f"{daily_memo_fit}\n"
        f"[Image Rules]\n"
        f"- cover 이미지는 변경하지 않습니다.\n"
        f"- {inline_rule}\n"
        f"- {inline_block}\n\n"
        f"[Body Rules]\n"
        f"- 결과 본문은 HTML로 작성합니다.\n"
        f"- <table>을 최소 1개 포함합니다.\n"
        f"- 이모티콘은 과하지 않게(섹션당 0~1개 수준) 사용 가능합니다.\n"
        f"- 마지막 섹션은 반드시 <h2>마무리 기록</h2>이고, 그 아래 <p>는 2~3문장입니다.\n"
        f"- URL을 유지해야 하므로 slug는 반드시 fixed_slug 그대로 유지합니다.\n"
        f"- 'Quick brief', 'Core focus', 'Key entities', 'internal archive' 등 메타 문구는 금지합니다.\n\n"
        f"[Current Content (reference only)]\n"
        f"{current_content[:2500]}\n\n"
        f"[Output Contract]\n"
        f"- JSON만 반환합니다.\n"
        f"- ArticleGenerationOutput 스키마를 따릅니다.\n"
        f"- slug 필드는 fixed_slug 값을 그대로 넣습니다.\n"
        f"- labels는 2~6개 한국어 키워드로 작성합니다.\n"
        f"- html_article는 반드시 HTML 문자열이고, <table> 1개 이상 포함, <img>는 0개입니다.\n"
        f"- 아래 JSON 스켈레톤의 키를 정확히 사용합니다(누락 금지).\n\n"
        "{\n"
        '  "title": "string",\n'
        '  "meta_description": "string",\n'
        '  "labels": ["string","string"],\n'
        f'  "slug": "{fixed_slug}",\n'
        '  "excerpt": "string",\n'
        '  "html_article": "string",\n'
        '  "faq_section": [\n'
        '    {"question":"string","answer":"string"},\n'
        '    {"question":"string","answer":"string"}\n'
        "  ],\n"
        '  "image_collage_prompt": "English realistic photo collage prompt"\n'
        "}\n"
    )


def _validate_generated(
    *,
    category_slug: str,
    fixed_slug: str,
    html_article: str,
    output_slug: str,
    has_inline: bool,
    kept_inline_url: str,
) -> list[str]:
    errors: list[str] = []
    if _normalize_space(output_slug) != _normalize_space(fixed_slug):
        errors.append("slug_changed")
    if not html_article.strip():
        errors.append("html_article_missing")
        return errors
    if not _has_table(html_article):
        errors.append("table_missing")
    # Model output must not contain <img>.
    if IMG_TAG_RE.search(html_article) or FIGURE_BLOCK_RE.search(html_article):
        errors.append("img_tag_present_in_model_output")
    closing = _extract_closing_paragraph(html_article)
    sentences = _count_sentences_korean(closing)
    if sentences < 2 or sentences > 3:
        errors.append(f"closing_record_sentence_count_invalid:{sentences}")
    if category_slug == "일상과-메모" and not _daily_memo_topic_fit_ok(html_article):
        errors.append("daily_memo_topic_fit_failed")
    return errors


@dataclass
class CandidatePost:
    remote_post_id: str
    slug: str
    title: str
    url: str
    category_slug: str
    seo_score: float | None
    geo_score: float | None
    ctr: float | None
    lighthouse_score: float | None
    avg_score: int


def _load_state(category_order: list[str]) -> dict[str, Any]:
    state = _read_json(
        _state_path(),
        {
            "category_index": 0,
            "processed": {slug: [] for slug in category_order},
            "consecutive_failures": 0,
            "recent_reports": [],
        },
    )
    if not isinstance(state, dict):
        state = {}
    state.setdefault("category_index", 0)
    processed = state.get("processed")
    if not isinstance(processed, dict):
        processed = {}
    for slug in category_order:
        if slug not in processed or not isinstance(processed.get(slug), list):
            processed[slug] = []
    state["processed"] = processed
    state.setdefault("consecutive_failures", 0)
    state.setdefault("recent_reports", [])
    return state


def _save_state(state: dict[str, Any]) -> None:
    _write_json(_state_path(), state)


def _select_candidates(db, *, category_slug: str, processed_ids: set[str], batch_size: int) -> list[CandidatePost]:
    rows = db.execute(
        text(
            """
            SELECT remote_post_id, slug, title, url, category_slug, seo_score, geo_score, ctr, lighthouse_score,
                   ROUND((COALESCE(seo_score, 0) + COALESCE(geo_score, 0) + COALESCE(ctr, 0) + COALESCE(lighthouse_score, 0)) / 4.0) AS avg_score
            FROM synced_cloudflare_posts
            WHERE status IN ('published','live')
              AND category_slug = :category_slug
              AND (
                    ((COALESCE(seo_score, 0) + COALESCE(geo_score, 0) + COALESCE(ctr, 0) + COALESCE(lighthouse_score, 0)) / 4.0) < 80
                    OR LEAST(COALESCE(seo_score, 0), COALESCE(geo_score, 0), COALESCE(ctr, 0), COALESCE(lighthouse_score, 0)) < 70
                  )
            ORDER BY avg_score ASC, updated_at_remote ASC NULLS FIRST, published_at ASC NULLS FIRST
            """,
        ),
        {"category_slug": category_slug},
    ).mappings().all()
    items: list[CandidatePost] = []
    for row in rows:
        rid = _normalize_space(row.get("remote_post_id"))
        if not rid or rid in processed_ids:
            continue
        items.append(
            CandidatePost(
                remote_post_id=rid,
                slug=_normalize_space(row.get("slug")),
                title=_normalize_space(row.get("title")),
                url=_normalize_space(row.get("url")),
                category_slug=_normalize_space(row.get("category_slug")),
                seo_score=row.get("seo_score"),
                geo_score=row.get("geo_score"),
                ctr=row.get("ctr"),
                lighthouse_score=row.get("lighthouse_score"),
                avg_score=int(row.get("avg_score") or 0),
            )
        )
        if len(items) >= batch_size:
            break
    return items


def _build_update_payload(*, detail: dict[str, Any], title: str, excerpt: str, seo_description: str, html_article: str) -> dict[str, Any]:
    category_payload = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    category_id = _normalize_space(category_payload.get("id"))
    cover_image = _normalize_space(detail.get("coverImage"))
    cover_alt = _normalize_space(detail.get("coverAlt")) or seo_description or title
    tags = detail.get("tags")
    tag_names: list[str] = []
    if isinstance(tags, list):
        seen: set[str] = set()
        for item in tags:
            name = _normalize_space(item.get("name") or item.get("label") or item.get("slug")) if isinstance(item, dict) else _normalize_space(item)
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            tag_names.append(name)
            if len(tag_names) >= 12:
                break
    payload: dict[str, Any] = {
        "title": title,
        "content": html_article,
        "excerpt": excerpt,
        "seoTitle": title,
        "seoDescription": seo_description,
        "tagNames": tag_names,
        "status": "published",
    }
    if category_id:
        payload["categoryId"] = category_id
    if cover_image:
        payload["coverImage"] = cover_image
        payload["coverAlt"] = cover_alt
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-refactor Cloudflare posts (10-min batches, no URL changes).")
    parser.add_argument("--mode", choices=["dry-run", "apply"], required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--score-threshold", type=int, default=DEFAULT_SCORE_THRESHOLD)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--category-order", default="", help="Comma-separated category list. Default is built-in order.")
    parser.add_argument("--category", default="", help="Force a single category for this run (no rotation).")
    return parser.parse_args()


def main() -> int:
    _load_runtime_env()
    args = parse_args()

    category_order = [token.strip() for token in args.category_order.split(",") if token.strip()] if args.category_order.strip() else list(DEFAULT_CATEGORY_ORDER)
    state = _load_state(category_order)

    forced = _normalize_space(args.category)
    if forced:
        current_category = forced
        rotate_after = False
    else:
        idx = int(state.get("category_index") or 0) % max(1, len(category_order))
        current_category = category_order[idx]
        rotate_after = True

    processed_ids = set(str(item) for item in (state.get("processed", {}).get(current_category) or []))

    now_local = _utc_now().astimezone()
    stamp = now_local.strftime("%Y%m%d-%H%M")
    day = now_local.strftime("%Y%m%d")
    work_dir = _work_dir(stamp)
    report_dir = _report_dir(day)
    report_path = report_dir / f"run-{now_local.strftime('%H%M')}.json"

    run_payload: dict[str, Any] = {
        "mode": args.mode,
        "category": current_category,
        "batch_size": int(args.batch_size),
        "score_threshold": int(args.score_threshold),
        "model": str(args.model),
        "started_at": now_local.isoformat(timespec="seconds"),
        "items": [],
        "summary": {},
    }

    with SessionLocal() as db:
        base_url, token = _integration_client_from_db(db)
        candidates = _select_candidates(db, category_slug=current_category, processed_ids=processed_ids, batch_size=int(args.batch_size))

        success = 0
        failed = 0
        skipped = 0

        for post in candidates:
            item: dict[str, Any] = {
                "remote_post_id": post.remote_post_id,
                "slug": post.slug,
                "url": post.url,
                "avg_score": post.avg_score,
                "seo_score": post.seo_score,
                "geo_score": post.geo_score,
                "ctr": post.ctr,
                "lighthouse_score": post.lighthouse_score,
            }
            try:
                detail = _integration_request(base_url, token, method="GET", path=f"/api/integrations/posts/{post.remote_post_id}")
                if not isinstance(detail, dict):
                    raise RuntimeError("invalid_detail_payload")
                content = str(detail.get("content") or detail.get("contentMarkdown") or "")
                content_stripped, strip_meta = _strip_all_but_first_inline_image(content)
                kept_inline = _normalize_space(strip_meta.get("kept_inline_url"))
                has_inline = bool(kept_inline)

                mode = "light" if post.avg_score >= int(args.score_threshold) else "heavy"

                already_ok = (
                    _has_table(content_stripped)
                    and (2 <= _count_sentences_korean(_extract_closing_paragraph(content_stripped)) <= 3)
                    and (current_category != "일상과-메모" or _daily_memo_topic_fit_ok(content_stripped))
                )
                if mode == "light" and already_ok:
                    item["action"] = "skip_already_ok"
                    skipped += 1
                    run_payload["items"].append(item)
                    if args.mode == "apply":
                        processed_ids.add(post.remote_post_id)
                        state["processed"][current_category].append(post.remote_post_id)
                    continue

                base_prompt = _read_category_prompt(current_category)
                if not base_prompt.strip():
                    raise RuntimeError(f"missing_category_prompt:{current_category}")

                gen_prompt = _build_generation_prompt(
                    base_prompt=base_prompt,
                    category_slug=current_category,
                    fixed_slug=post.slug,
                    title=_normalize_space(detail.get("title") or post.title),
                    excerpt=_normalize_space(detail.get("excerpt") or ""),
                    seo_score=post.seo_score,
                    geo_score=post.geo_score,
                    ctr=post.ctr,
                    lighthouse_score=post.lighthouse_score,
                    avg_score=post.avg_score,
                    current_content=content_stripped,
                    kept_inline_url=kept_inline,
                    has_inline=has_inline,
                    mode=mode,
                )

                provider = get_article_provider(db, model_override=str(args.model), provider_hint="openai_text", allow_large=True)
                output: dict[str, Any] = {}
                html_article = ""
                last_validation = ""
                for attempt in range(1, 4):
                    article_output, _raw = provider.generate_article(keyword=post.slug or post.title, prompt=gen_prompt)
                    output = article_output.model_dump() if hasattr(article_output, "model_dump") else dict(article_output)
                    html_article = str(output.get("html_article") or "")
                    html_article = _strip_all_html_images(html_article)
                    html_article = _ensure_minimum_table(html_article, category_slug=current_category)
                    html_article = _ensure_closing_record(html_article, title=_normalize_space(output.get("title") or detail.get("title") or post.title))
                    errors = _validate_generated(
                        category_slug=current_category,
                        fixed_slug=post.slug,
                        html_article=html_article,
                        output_slug=str(output.get("slug") or ""),
                        has_inline=has_inline,
                        kept_inline_url=kept_inline,
                    )
                    if not errors:
                        last_validation = "ok"
                        break
                    last_validation = ",".join(errors)
                if last_validation != "ok":
                    item["debug_validation"] = {
                        "attempts": 3,
                        "has_table": bool(HTML_TABLE_RE.search(html_article)),
                        "has_closing_h2": bool(re.search(r"(?is)<h2\b[^>]*>\s*마무리\s*기록\s*</h2>", html_article)),
                        "closing_sentence_count": _count_sentences_korean(_extract_closing_paragraph(html_article)),
                        "tail_300": html_article[-300:],
                        "head_300": html_article[:300],
                    }
                    raise RuntimeError("validation_failed:" + last_validation)

                html_article = _inject_inline_image_once(html_article, kept_inline if has_inline else "")
                html_article, _ = _strip_all_but_first_inline_image(html_article)

                title_after = _normalize_space(output.get("title") or detail.get("title") or post.title)
                excerpt_after = _normalize_space(output.get("excerpt") or detail.get("excerpt") or "")
                meta_after = _normalize_space(output.get("meta_description") or detail.get("seoDescription") or excerpt_after or title_after)

                update_payload = _build_update_payload(
                    detail=detail,
                    title=title_after,
                    excerpt=excerpt_after,
                    seo_description=meta_after,
                    html_article=html_article,
                )

                item["action"] = f"rewrite_{mode}"
                item["title_after"] = title_after
                item["public_url_before"] = _normalize_space(detail.get("publicUrl") or detail.get("url") or post.url)

                snapshot = {
                    "remote_post_id": post.remote_post_id,
                    "category": current_category,
                    "mode": mode,
                    "before": {
                        "title": _normalize_space(detail.get("title") or ""),
                        "excerpt": _normalize_space(detail.get("excerpt") or ""),
                        "seoDescription": _normalize_space(detail.get("seoDescription") or ""),
                        "coverImage": _normalize_space(detail.get("coverImage") or ""),
                        "content": content,
                    },
                    "after": {
                        "title": title_after,
                        "excerpt": excerpt_after,
                        "seoDescription": meta_after,
                        "coverImage": _normalize_space(detail.get("coverImage") or ""),
                        "content": html_article,
                    },
                    "update_payload": update_payload,
                }

                if args.mode == "apply":
                    updated = _integration_request(base_url, token, method="PUT", path=f"/api/integrations/posts/{post.remote_post_id}", json_payload=update_payload)
                    public_url = _normalize_space((updated or {}).get("publicUrl") or detail.get("publicUrl") or detail.get("url") or post.url)
                    item["public_url_after"] = public_url
                    item["public_url_http_200"] = _http_200(public_url)
                    processed_ids.add(post.remote_post_id)
                    state["processed"][current_category].append(post.remote_post_id)
                else:
                    item["publish_status"] = "dry_run"

                _write_json(work_dir / f"{post.remote_post_id}.json", snapshot)
                run_payload["items"].append(item)
                success += 1
            except Exception as exc:
                item["action"] = "failed"
                detail = getattr(exc, "detail", None)
                item["error"] = str(exc)
                if detail and str(detail) != str(exc):
                    item["error_detail"] = str(detail)
                run_payload["items"].append(item)
                failed += 1

        run_payload["summary"] = {"selected": len(candidates), "success": success, "skipped": skipped, "failed": failed}

        if args.mode == "apply":
            state["consecutive_failures"] = int(state.get("consecutive_failures") or 0) + 1 if failed > 0 else 0

            if rotate_after:
                total = db.execute(
                    text("SELECT COUNT(*) FROM synced_cloudflare_posts WHERE status IN ('published','live') AND category_slug = :category_slug"),
                    {"category_slug": current_category},
                ).scalar_one()
                if len(state["processed"].get(current_category, [])) >= int(total or 0):
                    state["category_index"] = (int(state.get("category_index") or 0) + 1) % max(1, len(category_order))

            all_done = True
            for cat in category_order:
                total = db.execute(
                    text("SELECT COUNT(*) FROM synced_cloudflare_posts WHERE status IN ('published','live') AND category_slug = :category_slug"),
                    {"category_slug": cat},
                ).scalar_one()
                if len(state["processed"].get(cat, [])) < int(total or 0):
                    all_done = False
                    break
            if all_done:
                # remove work snapshots, keep reports
                work_root = _ops_root() / "work"
                if work_root.exists():
                    for p in sorted(work_root.glob("*"), key=lambda x: str(x)):
                        if p.is_dir():
                            for f in p.rglob("*"):
                                if f.is_file():
                                    f.unlink(missing_ok=True)
                            for d in sorted([d for d in p.rglob("*") if d.is_dir()], reverse=True):
                                try:
                                    d.rmdir()
                                except Exception:
                                    pass
                            try:
                                p.rmdir()
                            except Exception:
                                pass
                run_payload["summary"]["all_categories_completed"] = True

            recent = list(state.get("recent_reports") or [])
            recent.insert(0, str(report_path))
            state["recent_reports"] = recent[:20]
            if int(state.get("consecutive_failures") or 0) >= 3:
                run_payload["summary"]["pause_recommended"] = True

            _save_state(state)

    _write_json(report_path, run_payload)
    print(json.dumps({"report": str(report_path), "summary": run_payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
