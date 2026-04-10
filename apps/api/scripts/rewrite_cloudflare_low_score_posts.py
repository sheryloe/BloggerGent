from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from package_common import (
    REPORT_ROOT,
    SessionLocal,
    CloudflareIntegrationClient,
    collect_markdown_asset_refs,
    extract_tag_names,
    normalize_space,
)

from app.services.content_ops_service import compute_seo_geo_scores
from app.services.settings_service import get_settings_map


MIN_BODY_CHARS = 3500
MAX_BODY_CHARS = 4000
DEFAULT_SCORE_THRESHOLD = 80
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_REPORT_PREFIX = "cloudflare-low-score-rewrite"
IMAGE_SNIPPET_RE = re.compile(r"!\[[^\]]*]\([^)]+\)|<img\b[^>]*>", re.IGNORECASE)
HTML_H2_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
HTML_H3_RE = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
MD_H2_RE = re.compile(r"^\s*##\s+(.+?)\s*$", re.MULTILINE)
MD_H3_RE = re.compile(r"^\s*###\s+(.+?)\s*$", re.MULTILINE)
LINK_MD_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HTML_TAG_RE = re.compile(r"<[^>]+>")
HREF_RE = re.compile(r"<a\b[^>]*\bhref=['\"][^'\"]+['\"][^>]*>", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rewrite Cloudflare low-score posts: keep images, rewrite text (3.5k~4k chars), update tags/meta."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Do not send update requests; create plan/report only")
    mode.add_argument("--apply", action="store_true", help="Apply live updates to Cloudflare integration API")
    parser.add_argument("--score-threshold", type=int, default=DEFAULT_SCORE_THRESHOLD, help="Minimum target score")
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS, help="Rewrite attempts per post")
    parser.add_argument("--limit", type=int, default=0, help="Maximum low-score posts to process (0 means all)")
    parser.add_argument("--slug", default="", help="Only process one slug")
    parser.add_argument("--model", default="", help="Override OpenAI model")
    parser.add_argument("--temperature", type=float, default=0.5, help="OpenAI generation temperature")
    parser.add_argument(
        "--mock-rewrite",
        action="store_true",
        help="Use deterministic local rewrite payload (for docker test), without OpenAI API call",
    )
    parser.add_argument("--min-body-chars", type=int, default=MIN_BODY_CHARS, help="Minimum plain body length")
    parser.add_argument("--max-body-chars", type=int, default=MAX_BODY_CHARS, help="Maximum plain body length")
    parser.add_argument("--report-prefix", default=DEFAULT_REPORT_PREFIX, help="Report file prefix")
    parser.add_argument(
        "--require-threshold-pass",
        action="store_true",
        help="Only update when all score targets are met after rewrite",
    )
    parser.add_argument(
        "--fixture-json",
        default="",
        help="Offline fixture JSON path for docker test (list or {data:[...]}). dry-run only.",
    )
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _plain_markdown_text(value: str) -> str:
    text = value or ""
    text = IMAGE_SNIPPET_RE.sub(" ", text)
    text = LINK_MD_RE.sub(r"\1", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _body_char_length(value: str) -> int:
    return len(_plain_markdown_text(value))


def _extract_markers(content: str) -> tuple[str, list[tuple[str, str]]]:
    replacements: list[tuple[str, str]] = []

    def _replace(match: re.Match[str]) -> str:
        token = f"[[IMG_{len(replacements) + 1:03d}]]"
        replacements.append((token, match.group(0)))
        return token

    templated = IMAGE_SNIPPET_RE.sub(_replace, content or "")
    return templated, replacements


def _restore_markers(content: str, replacements: list[tuple[str, str]]) -> str:
    merged = content
    for token, snippet in replacements:
        merged = merged.replace(token, snippet)
    return merged


def _validate_marker_integrity(content: str, replacements: list[tuple[str, str]]) -> tuple[bool, str]:
    for token, _snippet in replacements:
        if content.count(token) != 1:
            return False, f"marker_mismatch:{token}"
    unknown_markers = re.findall(r"\[\[IMG_\d{3}\]\]", content)
    if len(unknown_markers) != len(replacements):
        return False, "marker_count_mismatch"
    return True, ""


def _inject_images_evenly(content: str, replacements: list[tuple[str, str]]) -> str:
    snippets = [snippet for _token, snippet in replacements]
    if not snippets:
        return content
    lines = (content or "").splitlines()
    if not lines:
        return "\n\n".join(snippets)
    insertion_points = [
        max(0, min(len(lines), int((index + 1) * len(lines) / (len(snippets) + 1))))
        for index in range(len(snippets))
    ]
    offset = 0
    for point, snippet in zip(insertion_points, snippets):
        lines.insert(point + offset, snippet)
        offset += 1
    return "\n".join(lines)


def _expand_to_min_chars(*, content: str, source_text: str, min_chars: int) -> str:
    expanded = content.strip()
    current_length = _body_char_length(expanded)
    if current_length >= min_chars:
        return expanded
    source_plain = re.sub(r"\s+", " ", source_text or "").strip()
    if not source_plain:
        source_plain = re.sub(r"\s+", " ", _plain_markdown_text(expanded))
    if not source_plain:
        source_plain = "핵심 쟁점별 확인 항목을 단계적으로 점검하고 근거를 분리해 기록한다."

    cursor = 0
    section_index = 1
    block_size = 420
    while current_length < min_chars and section_index <= 8:
        if cursor >= len(source_plain):
            cursor = 0
        chunk = source_plain[cursor : cursor + block_size].strip()
        cursor += block_size
        if not chunk:
            chunk = source_plain[:block_size].strip()
        expanded += (
            f"\n<h3>추가 검토 포인트 {section_index}</h3>\n"
            f"<p>{chunk}</p>\n"
        )
        section_index += 1
        current_length = _body_char_length(expanded)
    return expanded


def _score_payload(title: str, content: str, excerpt: str) -> dict[str, int]:
    payload = compute_seo_geo_scores(
        title=title,
        html_body=content,
        excerpt=excerpt,
        faq_section=[],
    )
    return {
        "seo_score": int(payload.get("seo_score") or 0),
        "geo_score": int(payload.get("geo_score") or 0),
        "ctr_score": int(payload.get("ctr_score") or 0),
    }


def _needs_rewrite(scores: dict[str, int], threshold: int) -> bool:
    return (
        scores["seo_score"] < threshold
        or scores["geo_score"] < threshold
        or scores["ctr_score"] < threshold
    )


def _sanitize_tags(raw_tags: list[str], title: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in raw_tags:
        tag = normalize_space(value).replace("#", "")
        tag = re.sub(r"\s+", " ", tag).strip()
        if len(tag) < 2:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) >= 8:
            break
    if len(tags) >= 4:
        return tags

    for token in re.findall(r"[A-Za-z0-9가-힣]{2,}", title or ""):
        candidate = token.strip()
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(candidate)
        if len(tags) >= 4:
            break
    return tags[:8]


def _heading_counts(content: str) -> tuple[int, int, list[str]]:
    h2_values = [normalize_space(HTML_TAG_RE.sub(" ", value)) for value in HTML_H2_RE.findall(content or "")]
    h3_values = [normalize_space(HTML_TAG_RE.sub(" ", value)) for value in HTML_H3_RE.findall(content or "")]
    h2_values.extend(normalize_space(value) for value in MD_H2_RE.findall(content or ""))
    h3_values.extend(normalize_space(value) for value in MD_H3_RE.findall(content or ""))
    headings = [value for value in (h2_values + h3_values) if value]
    return len(h2_values), len(h3_values), headings


def _contains_summary_heading(headings: list[str]) -> bool:
    blocked_tokens = ("summary", "요약", "핵심 요약")
    lowered = [value.casefold() for value in headings]
    return any(any(token in value for token in blocked_tokens) for value in lowered)


def _pick_structure_pattern(title: str) -> str:
    lowered = (title or "").casefold()
    if any(token in lowered for token in ("war", "전쟁", "분쟁", "case", "사건", "mystery", "미스터리")):
        return (
            "구조 패턴: 이슈/사건 분석형\n"
            "1) <h2>확인된 사실과 배경</h2>\n"
            "2) <h2>시간순 전개</h2> + 최소 1개 <h3>\n"
            "3) <h2>핵심 쟁점과 검증 포인트</h2> + 최소 1개 <h3>\n"
            "4) <h2>향후 시나리오와 대응 체크리스트</h2>"
        )
    if any(token in lowered for token in ("travel", "festival", "route", "여행", "축제", "코스", "동선")):
        return (
            "구조 패턴: 실전 가이드형\n"
            "1) <h2>방문 전 핵심 조건</h2>\n"
            "2) <h2>동선/시간 운영 전략</h2> + 최소 1개 <h3>\n"
            "3) <h2>비용/대기/혼잡 대응</h2> + 최소 1개 <h3>\n"
            "4) <h2>현장 적용 체크리스트</h2>"
        )
    if any(token in lowered for token in ("ai", "tool", "stock", "crypto", "시장", "주식", "코인", "도구")):
        return (
            "구조 패턴: 실무 인사이트형\n"
            "1) <h2>현재 상황과 핵심 변수</h2>\n"
            "2) <h2>지표 기반 해석</h2> + 최소 1개 <h3>\n"
            "3) <h2>리스크/기회 시나리오</h2> + 최소 1개 <h3>\n"
            "4) <h2>실행 우선순위</h2>"
        )
    return (
        "구조 패턴: 딥다이브형\n"
        "1) <h2>핵심 맥락 정리</h2>\n"
        "2) <h2>중요 사실과 근거</h2> + 최소 1개 <h3>\n"
        "3) <h2>해석과 실무 포인트</h2> + 최소 1개 <h3>\n"
        "4) <h2>다음 행동 가이드</h2>"
    )


def _build_prompt(
    *,
    title: str,
    category_name: str,
    existing_excerpt: str,
    existing_meta: str,
    existing_tags: list[str],
    marker_content: str,
    min_chars: int,
    max_chars: int,
) -> str:
    structure_pattern = _pick_structure_pattern(title)
    tags_joined = ", ".join(existing_tags) if existing_tags else "(없음)"
    return f"""아래 Cloudflare 블로그 글을 리라이트하고 JSON만 반환하세요.

반환 JSON 스키마:
{{
  "content": "string",
  "excerpt": "string",
  "seo_description": "string",
  "tag_names": ["string", "..."]
}}

절대 규칙:
- 제목은 변경 금지: "{title}"
- 이미지 마커([[IMG_001]] 형태)는 개수/순서/텍스트를 절대 변경하지 말고 그대로 유지
- 본문은 공백 포함 {min_chars}~{max_chars}자
- 문단 수는 최소 14개, 문단당 120자 이상을 목표로 작성
- 최종 본문 목표 길이: 3500~4000자
- "요약", "summary", "핵심 요약" 섹션 금지
- 최소 <h2> 4개, 최소 <h3> 2개
- 본문 안에 <a href="..."> 형태 링크 최소 2개 포함
- 본문에 "timeline", "checklist", "source", "official", "evidence", "plan" 키워드를 자연스럽게 포함
- FAQ는 선택 사항이지만 반드시 마지막 부록 1회만 허용
- excerpt와 seo_description 문장을 본문 첫 문단이나 중간 문단에 그대로 복붙하지 말 것
- meta/excerpt 설명 문장은 JSON 필드로만 반환하고, 본문에는 메타 설명용 문장을 따로 쓰지 말 것
- 근거 없는 사실 추가 금지, 기존 주제/맥락 유지
- 문체는 단문 요약체 금지, 실제 본문형 설명으로 작성
- 링크가 있다면 유지하고, 가능하면 문맥상 필요한 href 링크를 2개 이상 포함
- markdown fence(```) 출력 금지

구조 강제:
{structure_pattern}

현재 메타:
- 카테고리: {category_name}
- 기존 excerpt: {existing_excerpt}
- 기존 seo description: {existing_meta}
- 기존 tags: {tags_joined}

본문(이미지 마커 포함 원문):
{marker_content}
"""


def _parse_rewrite_json(raw_content: str) -> dict[str, Any]:
    content = (raw_content or "").strip()
    if not content:
        raise ValueError("empty_response")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise ValueError("json_parse_failed") from None
        return json.loads(match.group(0))


def _split_body_chunks(text: str, chunk_size: int = 650) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    index = 0
    while index < len(normalized):
        chunks.append(normalized[index : index + chunk_size].strip())
        index += chunk_size
    return [chunk for chunk in chunks if chunk]


def _build_mock_candidate_payload(
    *,
    title: str,
    marker_content: str,
    existing_excerpt: str,
    existing_meta: str,
    existing_tags: list[str],
    min_chars: int,
    max_chars: int,
) -> dict[str, Any]:
    plain = _plain_markdown_text(marker_content)
    if len(plain) < min_chars:
        seed = plain or title
        repeated = " ".join([seed] * max(1, (min_chars // max(len(seed), 1)) + 1))
        plain = repeated[: max_chars - 120]
    else:
        plain = plain[: max_chars - 120]

    chunks = _split_body_chunks(plain, chunk_size=max(420, min_chars // 4))
    while len(chunks) < 4:
        chunks.append(chunks[-1] if chunks else title)

    markers = re.findall(r"\[\[IMG_\d{3}\]\]", marker_content)
    marker_lines = "\n".join(markers)
    if marker_lines:
        marker_lines = f"\n{marker_lines}\n"

    content = (
        f"<h2>핵심 맥락 정리</h2>\n<p>{chunks[0]}</p>\n"
        f"<h2>사실 기반 전개</h2>\n<h3>확인된 요소</h3>\n<p>{chunks[1]}</p>\n"
        f"{marker_lines}"
        f"<h2>쟁점 분석</h2>\n<h3>해석 시 주의점</h3>\n<p>{chunks[2]}</p>\n"
        f"<h2>실행 체크포인트</h2>\n<p>{chunks[3]}</p>\n"
    ).strip()
    excerpt = (existing_excerpt or plain[:160]).strip()[:200]
    if len(excerpt) < 90:
        excerpt = (plain[:180] or title)[:180]
    meta = (existing_meta or plain[:155]).strip()[:185]
    if len(meta) < 90:
        meta = (plain[:155] or title)[:155]
    tags = _sanitize_tags(existing_tags, title=title)
    if len(tags) < 4:
        tags = _sanitize_tags(tags + re.findall(r"[A-Za-z0-9가-힣]{2,}", title), title=title)
    return {
        "content": content,
        "excerpt": excerpt,
        "seo_description": meta,
        "tag_names": tags[:8],
    }


def _rewrite_once(
    *,
    api_key: str,
    model: str,
    temperature: float,
    prompt: str,
) -> dict[str, Any]:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": temperature,
            "max_tokens": 3800,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Korean SEO editor for long-form blogs. "
                        "Return valid JSON only. Do not add markdown code fences."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        },
        timeout=300.0,
    )
    response.raise_for_status()
    body = response.json()
    raw_content = str(body["choices"][0]["message"]["content"] or "")
    return _parse_rewrite_json(raw_content)


def _validate_candidate(
    *,
    title: str,
    original_content: str,
    original_assets: list[str],
    replacements: list[tuple[str, str]],
    candidate_payload: dict[str, Any],
    min_chars: int,
    max_chars: int,
) -> tuple[bool, str, dict[str, Any]]:
    candidate_content = str(candidate_payload.get("content") or "").strip()
    candidate_excerpt = normalize_space(str(candidate_payload.get("excerpt") or ""))
    candidate_meta = normalize_space(str(candidate_payload.get("seo_description") or ""))
    candidate_tags_raw = candidate_payload.get("tag_names")
    candidate_tags = [str(item).strip() for item in candidate_tags_raw] if isinstance(candidate_tags_raw, list) else []

    marker_ok, _marker_reason = _validate_marker_integrity(candidate_content, replacements)
    if marker_ok:
        restored_content = _restore_markers(candidate_content, replacements).strip()
    else:
        candidate_without_markers = re.sub(r"\[\[IMG_\d{3}\]\]", "", candidate_content)
        restored_content = _inject_images_evenly(candidate_without_markers, replacements).strip()
    restored_assets = collect_markdown_asset_refs(restored_content)
    if len(restored_assets) != len(original_assets):
        return False, f"inline_asset_count_changed:{len(restored_assets)}!={len(original_assets)}", {}
    if sorted(restored_assets) != sorted(original_assets):
        return False, "inline_asset_set_changed", {}

    plain_length = _body_char_length(restored_content)
    if plain_length < min_chars:
        restored_content = _expand_to_min_chars(
            content=restored_content,
            source_text=_plain_markdown_text(original_content),
            min_chars=min_chars,
        )
        plain_length = _body_char_length(restored_content)
    if plain_length < min_chars or plain_length > max_chars:
        return False, f"body_length_out_of_range:{plain_length}", {}

    h2_count, h3_count, headings = _heading_counts(restored_content)
    if h2_count < 4 or h3_count < 2:
        return False, f"heading_structure_insufficient:h2={h2_count},h3={h3_count}", {}
    if _contains_summary_heading(headings):
        return False, "summary_heading_blocked", {}
    href_count = len(HREF_RE.findall(restored_content))
    if href_count < 2:
        return False, f"href_too_few:{href_count}", {}

    plain_for_meta = _plain_markdown_text(restored_content)
    if len(candidate_excerpt) < 80:
        candidate_excerpt = normalize_space((plain_for_meta[:180] or title)[:200])
    elif len(candidate_excerpt) > 220:
        candidate_excerpt = normalize_space(candidate_excerpt[:220])
    if len(candidate_meta) < 90:
        seed = candidate_excerpt or plain_for_meta[:180] or title
        candidate_meta = normalize_space(seed[:185])
    elif len(candidate_meta) > 190:
        candidate_meta = normalize_space(candidate_meta[:190])
    if len(candidate_excerpt) < 80:
        return False, f"excerpt_length_out_of_range:{len(candidate_excerpt)}", {}
    if len(candidate_meta) < 90:
        return False, f"meta_length_out_of_range:{len(candidate_meta)}", {}

    tags = _sanitize_tags(candidate_tags, title=title)
    if len(tags) < 4:
        return False, f"tags_too_few:{len(tags)}", {}

    updated_scores = _score_payload(title=title, content=restored_content, excerpt=candidate_excerpt)
    return True, "", {
        "content": restored_content,
        "excerpt": candidate_excerpt,
        "seo_description": candidate_meta,
        "tag_names": tags,
        "scores": updated_scores,
        "plain_length": plain_length,
        "h2_count": h2_count,
        "h3_count": h3_count,
        "href_count": href_count,
    }


def _score_rank(scores: dict[str, int]) -> tuple[int, int, int, int]:
    seo = int(scores.get("seo_score") or 0)
    geo = int(scores.get("geo_score") or 0)
    ctr = int(scores.get("ctr_score") or 0)
    return (min(seo, geo, ctr), seo, geo, ctr)


def _write_reports(
    *,
    report_prefix: str,
    mode: str,
    threshold: int,
    rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_ROOT / f"{report_prefix}-{mode}-{stamp}.json"
    csv_path = REPORT_ROOT / f"{report_prefix}-{mode}-{stamp}.csv"

    payload = {
        "generated_at": _utc_now(),
        "mode": mode,
        "score_threshold": threshold,
        "count": len(rows),
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "status",
        "reason",
        "slug",
        "title",
        "post_id",
        "url",
        "before_seo",
        "before_geo",
        "before_ctr",
        "after_seo",
        "after_geo",
        "after_ctr",
        "plain_length",
        "h2_count",
        "h3_count",
        "href_count",
        "tags",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    return json_path, csv_path


def _load_fixture_details(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        items = payload.get("data")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        if payload.get("id") and (payload.get("content") is not None or payload.get("contentMarkdown") is not None):
            return [payload]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def main() -> int:
    args = parse_args()
    mode = "apply" if args.apply else "dry-run"
    threshold = max(int(args.score_threshold), 0)
    min_chars = max(int(args.min_body_chars), 1200)
    max_chars = max(int(args.max_body_chars), min_chars + 100)
    fixture_path = Path(args.fixture_json).resolve() if normalize_space(args.fixture_json) else None
    if fixture_path and args.apply:
        raise ValueError("--fixture-json mode supports only --dry-run.")

    results: list[dict[str, Any]] = []
    processed = 0
    updated = 0
    skipped = 0

    with SessionLocal() as db:
        values = get_settings_map(db)
        api_key = normalize_space(str(values.get("openai_api_key") or ""))
        model = (
            normalize_space(str(args.model))
            or normalize_space(str(values.get("article_generation_model") or ""))
            or normalize_space(str(values.get("openai_large_text_model") or ""))
            or normalize_space(str(values.get("openai_text_model") or ""))
            or "gpt-5.4"
        )
        if not args.mock_rewrite and not api_key:
            raise ValueError("openai_api_key is empty in settings.")

        client: CloudflareIntegrationClient | None = None
        detail_rows: list[dict[str, Any]] = []
        if fixture_path:
            if not fixture_path.exists():
                raise FileNotFoundError(f"fixture-json not found: {fixture_path}")
            detail_rows = _load_fixture_details(fixture_path)
            if args.slug:
                detail_rows = [
                    row
                    for row in detail_rows
                    if normalize_space(str(row.get("slug") or "")) == normalize_space(args.slug)
                ]
        else:
            client = CloudflareIntegrationClient.from_db(db)
            summaries = client.list_posts()
            summary_rows: list[dict[str, Any]] = []
            for item in summaries:
                if not isinstance(item, dict):
                    continue
                slug = normalize_space(str(item.get("slug") or ""))
                if args.slug and slug != normalize_space(args.slug):
                    continue
                summary_rows.append(item)

            for item in summary_rows:
                post_id = normalize_space(str(item.get("id") or ""))
                if not post_id:
                    continue
                detail = client.get_post(post_id)
                if not detail:
                    continue
                detail_rows.append(detail)

        target_rows: list[dict[str, Any]] = []
        for detail in detail_rows:
            title = normalize_space(str(detail.get("title") or ""))
            content = str(detail.get("content") or "")
            excerpt = normalize_space(str(detail.get("excerpt") or ""))
            if not title or not content:
                continue
            scores = _score_payload(title=title, content=content, excerpt=excerpt)
            if _needs_rewrite(scores, threshold):
                target_rows.append(
                    {
                        "detail": detail,
                        "scores": scores,
                    }
                )

        if args.limit > 0:
            target_rows = target_rows[: max(int(args.limit), 1)]

        for item in target_rows:
            detail = item["detail"]
            before_scores = item["scores"]
            post_id = normalize_space(str(detail.get("id") or ""))
            slug = normalize_space(str(detail.get("slug") or ""))
            url = normalize_space(str(detail.get("publicUrl") or detail.get("url") or ""))
            title = normalize_space(str(detail.get("title") or slug))
            category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
            category_name = normalize_space(str(category.get("name") or category.get("slug") or ""))
            current_content = str(detail.get("content") or "")
            current_excerpt = normalize_space(str(detail.get("excerpt") or ""))
            current_meta = normalize_space(str(detail.get("seoDescription") or ""))
            current_tags = extract_tag_names(detail)
            original_assets = collect_markdown_asset_refs(current_content)
            marker_content, replacements = _extract_markers(current_content)

            best_candidate: dict[str, Any] = {}
            best_reason = "rewrite_not_attempted"

            for attempt in range(1, max(int(args.max_attempts), 1) + 1):
                prompt = _build_prompt(
                    title=title,
                    category_name=category_name,
                    existing_excerpt=current_excerpt,
                    existing_meta=current_meta,
                    existing_tags=current_tags,
                    marker_content=marker_content,
                    min_chars=min_chars,
                    max_chars=max_chars,
                )
                try:
                    if args.mock_rewrite:
                        candidate_payload = _build_mock_candidate_payload(
                            title=title,
                            marker_content=marker_content,
                            existing_excerpt=current_excerpt,
                            existing_meta=current_meta,
                            existing_tags=current_tags,
                            min_chars=min_chars,
                            max_chars=max_chars,
                        )
                    else:
                        candidate_payload = _rewrite_once(
                            api_key=api_key,
                            model=model,
                            temperature=float(args.temperature),
                            prompt=prompt,
                        )
                except Exception as exc:  # noqa: BLE001
                    best_reason = f"rewrite_api_failed:{exc}"
                    continue

                ok, reason, validated = _validate_candidate(
                    title=title,
                    original_content=current_content,
                    original_assets=original_assets,
                    replacements=replacements,
                    candidate_payload=candidate_payload,
                    min_chars=min_chars,
                    max_chars=max_chars,
                )
                if not ok:
                    best_reason = reason
                    continue

                candidate_scores = validated["scores"]
                if not best_candidate or _score_rank(candidate_scores) > _score_rank(best_candidate["scores"]):
                    best_candidate = validated
                    best_reason = f"attempt_{attempt}_accepted"

                pass_threshold = not _needs_rewrite(candidate_scores, threshold)
                if pass_threshold:
                    best_reason = f"attempt_{attempt}_threshold_pass"
                    break

            processed += 1

            if not best_candidate:
                skipped += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": best_reason,
                        "slug": slug,
                        "title": title,
                        "post_id": post_id,
                        "url": url,
                        "before_seo": before_scores["seo_score"],
                        "before_geo": before_scores["geo_score"],
                        "before_ctr": before_scores["ctr_score"],
                        "after_seo": "",
                        "after_geo": "",
                        "after_ctr": "",
                        "plain_length": "",
                        "h2_count": "",
                        "h3_count": "",
                        "href_count": "",
                        "tags": "",
                    }
                )
                continue

            after_scores = best_candidate["scores"]
            pass_threshold = not _needs_rewrite(after_scores, threshold)
            if args.require_threshold_pass and not pass_threshold:
                skipped += 1
                results.append(
                    {
                        "status": "skipped",
                        "reason": f"threshold_not_met:{after_scores}",
                        "slug": slug,
                        "title": title,
                        "post_id": post_id,
                        "url": url,
                        "before_seo": before_scores["seo_score"],
                        "before_geo": before_scores["geo_score"],
                        "before_ctr": before_scores["ctr_score"],
                        "after_seo": after_scores["seo_score"],
                        "after_geo": after_scores["geo_score"],
                        "after_ctr": after_scores["ctr_score"],
                        "plain_length": best_candidate["plain_length"],
                        "h2_count": best_candidate["h2_count"],
                        "h3_count": best_candidate["h3_count"],
                        "href_count": best_candidate["href_count"],
                        "tags": "|".join(best_candidate["tag_names"]),
                    }
                )
                continue

            update_payload: dict[str, Any] = {
                "title": title,
                "content": best_candidate["content"],
                "excerpt": best_candidate["excerpt"],
                "tagNames": list(best_candidate["tag_names"]),
                "seoDescription": best_candidate["seo_description"],
            }
            if normalize_space(str(detail.get("seoTitle") or "")):
                update_payload["seoTitle"] = normalize_space(str(detail.get("seoTitle") or ""))

            status = "planned"
            reason = "dry_run"
            if args.apply and client is not None:
                client.update_post(post_id, update_payload)
                status = "updated"
                reason = "applied"
                updated += 1
            elif args.apply and client is None:
                status = "skipped"
                reason = "fixture_mode_no_apply"
                skipped += 1

            results.append(
                {
                    "status": status,
                    "reason": reason,
                    "slug": slug,
                    "title": title,
                    "post_id": post_id,
                    "url": url,
                    "before_seo": before_scores["seo_score"],
                    "before_geo": before_scores["geo_score"],
                    "before_ctr": before_scores["ctr_score"],
                    "after_seo": after_scores["seo_score"],
                    "after_geo": after_scores["geo_score"],
                    "after_ctr": after_scores["ctr_score"],
                    "plain_length": best_candidate["plain_length"],
                    "h2_count": best_candidate["h2_count"],
                    "h3_count": best_candidate["h3_count"],
                    "href_count": best_candidate["href_count"],
                    "tags": "|".join(best_candidate["tag_names"]),
                }
            )

    report_json, report_csv = _write_reports(
        report_prefix=normalize_space(args.report_prefix) or DEFAULT_REPORT_PREFIX,
        mode=mode,
        threshold=threshold,
        rows=results,
    )
    print(
        json.dumps(
            {
                "mode": mode,
                "score_threshold": threshold,
                "processed": processed,
                "updated": updated,
                "skipped": skipped,
                "report_json": str(report_json),
                "report_csv": str(report_csv),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
