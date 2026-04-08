#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
BACKUP_ROOT = REPO_ROOT / "backup"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent",
    )
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from package_common import (  # noqa: E402
    CloudflareIntegrationClient,
    SessionLocal,
    extract_tag_names,
    normalize_space,
    safe_filename,
    write_json,
)

from app.services.cloudflare_channel_service import (  # noqa: E402
    _category_topic_guidance,
    _cloudflare_content_brief,
    _cloudflare_editorial_category_key,
    _cloudflare_target_audience,
)
from app.services.prompt_service import render_prompt_template  # noqa: E402
from app.services.providers.factory import get_article_provider, get_runtime_config  # noqa: E402
from app.services.settings_service import get_settings_map  # noqa: E402


IMAGE_SNIPPET_RE = re.compile(r"!\[[^\]]*]\([^)]+\)|<img\b[^>]*>", re.IGNORECASE)
HTML_H2_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
HTML_H3_RE = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")
MARKDOWN_H1_RE = re.compile(r"^\s*#\s+.+?(?:\n+|$)", re.MULTILINE)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite Cloudflare published posts by local date range using the travel master prompt "
            "while preserving existing image URLs."
        )
    )
    parser.add_argument("--date", default="", help="Single local date (YYYY-MM-DD). Shortcut for start=end.")
    parser.add_argument("--start-date", default="", help="Local start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", default="", help="Local end date (YYYY-MM-DD).")
    parser.add_argument("--timezone", default="Asia/Seoul", help="IANA timezone name. Default: Asia/Seoul.")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of posts to process.")
    parser.add_argument("--slug", default="", help="Optional single slug to rewrite.")
    parser.add_argument("--slugs-file", default="", help="Optional UTF-8 text or JSON file containing slugs to process.")
    parser.add_argument("--model", default="", help="Optional model override.")
    parser.add_argument("--max-attempts", type=int, default=2, help="Rewrite attempts per post.")
    parser.add_argument("--min-body-chars", type=int, default=2800, help="Minimum plain-text body length.")
    parser.add_argument("--max-body-chars", type=int, default=4200, help="Maximum plain-text body length.")
    parser.add_argument("--backup-dir", default=str(BACKUP_ROOT), help="Backup/report root directory.")
    parser.add_argument("--report-prefix", default="cloudflare-range-rewrite", help="Report filename prefix.")
    parser.add_argument("--apply", action="store_true", help="Apply live updates.")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Generate rewrite payloads but do not update remote posts (still uses the article provider).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only: fetch and backup the target scope without generating rewrites (default).",
    )
    args = parser.parse_args()

    if args.apply and args.preview:
        parser.error("--apply and --preview cannot be used together.")
    if args.dry_run and (args.apply or args.preview):
        parser.error("--dry-run cannot be used with --apply/--preview.")
    return args


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    raw = normalize_space(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_local_date(value: str | None, tz: ZoneInfo) -> str:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return ""
    return parsed.astimezone(tz).date().isoformat()


def _plain_text(value: str) -> str:
    text = IMAGE_SNIPPET_RE.sub(" ", value or "")
    text = HTML_TAG_RE.sub(" ", text)
    text = MARKDOWN_H1_RE.sub(" ", text)
    text = re.sub(r"^\s*#{2,6}\s+", "", text, flags=re.MULTILINE)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _extract_image_snippets(value: str) -> list[str]:
    snippets: list[str] = []
    seen: set[str] = set()
    for match in IMAGE_SNIPPET_RE.finditer(value or ""):
        snippet = match.group(0).strip()
        if not snippet or snippet in seen:
            continue
        seen.add(snippet)
        snippets.append(snippet)
    return snippets


def _strip_existing_heading(value: str) -> str:
    body = MARKDOWN_H1_RE.sub("", value or "", count=1)
    return body.strip()


def _heading_texts(value: str) -> list[str]:
    headings = [normalize_space(HTML_TAG_RE.sub(" ", item)) for item in HTML_H2_RE.findall(value or "")]
    headings.extend(normalize_space(HTML_TAG_RE.sub(" ", item)) for item in HTML_H3_RE.findall(value or ""))
    return [item for item in headings if item]


def _has_blocked_heading(value: str) -> bool:
    lowered = [heading.casefold() for heading in _heading_texts(value)]
    return any(token.casefold() in heading for token in BLOCKED_HEADINGS for heading in lowered)


def _strip_inline_images(value: str) -> str:
    return IMAGE_SNIPPET_RE.sub("", value or "")


def _inject_images_evenly(content: str, snippets: list[str]) -> str:
    if not snippets:
        return content.strip()
    lines = [line for line in (content or "").splitlines()]
    if not lines:
        return "\n\n".join(snippets).strip()
    insertion_points = [
        max(0, min(len(lines), int((index + 1) * len(lines) / (len(snippets) + 1))))
        for index in range(len(snippets))
    ]
    offset = 0
    for point, snippet in zip(insertion_points, snippets):
        lines.insert(point + offset, "")
        lines.insert(point + offset + 1, snippet)
        lines.insert(point + offset + 2, "")
        offset += 3
    return "\n".join(lines).strip()


def _inject_images_before_faq(content: str, snippets: list[str]) -> str:
    if not snippets:
        return content.strip()
    faq_markers = ("<h2>FAQ</h2>", "<h2>자주 묻는 질문</h2>")
    body_part = content
    faq_part = ""
    for marker in faq_markers:
        if marker in content:
            left, right = content.split(marker, maxsplit=1)
            body_part = left.strip()
            faq_part = f"{marker}{right}".strip()
            break
    injected_body = _inject_images_evenly(body_part, snippets)
    if faq_part:
        return f"{injected_body}\n\n{faq_part}".strip()
    return injected_body


def _expand_body_to_min_chars(content: str, *, source_text: str, min_body_chars: int) -> str:
    expanded = (content or "").strip()
    plain_source = normalize_space(source_text)
    if not plain_source:
        return expanded
    section_index = 1
    cursor = 0
    while len(_plain_text(expanded)) < min_body_chars and section_index <= 3:
        chunk = plain_source[cursor : cursor + 420].strip()
        if not chunk:
            cursor = 0
            chunk = plain_source[:420].strip()
        if not chunk:
            break
        expanded = (
            f"{expanded}\n\n"
            f"<h2>실전 체크포인트 {section_index}</h2>\n"
            f"<h3>놓치기 쉬운 포인트</h3>\n"
            f"<p>{chunk}</p>"
        ).strip()
        cursor += 420
        section_index += 1
    return expanded


def _localize_common_headings(content: str) -> str:
    replacements = {
        "<h2>Quick Answer</h2>": "<h2>빠른 결론</h2>",
        "<h2>At a Glance</h2>": "<h2>핵심 포인트</h2>",
        "<h2>Final Takeaway</h2>": "<h2>최종 정리</h2>",
        "<h2>FAQ</h2>": "<h2>자주 묻는 질문</h2>",
    }
    localized = content or ""
    for source, target in replacements.items():
        localized = localized.replace(source, target)
    return localized


def _faq_to_html(faq_section: list[Any]) -> str:
    rows: list[str] = ["<h2>자주 묻는 질문</h2>"]
    for item in faq_section[:4]:
        question = normalize_space(str(getattr(item, "question", "") or ""))
        answer = normalize_space(str(getattr(item, "answer", "") or ""))
        if not question or not answer:
            continue
        rows.append(f"<h3>{question}</h3>")
        rows.append(f"<p>{answer}</p>")
    return "\n".join(rows).strip()


def _normalize_tags(candidate_labels: list[str], *, category_name: str, existing_tags: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()

    def _append(value: str) -> None:
        tag = normalize_space(value).replace("#", "")
        if not tag:
            return
        key = tag.casefold()
        if key in seen:
            return
        seen.add(key)
        tags.append(tag)

    _append(category_name)
    for item in candidate_labels:
        _append(item)
    for item in existing_tags:
        _append(item)
    return tags[:6]


def _finalize_meta(value: str, fallback_text: str) -> str:
    meta = normalize_space(value)
    if len(meta) > 160:
        meta = meta[:160].rstrip(" .,")
    if len(meta) < 130:
        fallback = normalize_space(fallback_text)
        meta = fallback[:160].rstrip(" .,")
    return meta


def _finalize_excerpt(value: str, fallback_text: str) -> str:
    excerpt = normalize_space(value)
    if len(excerpt) >= 60:
        return excerpt[:220].rstrip(" .,")
    fallback = normalize_space(fallback_text)
    return fallback[:220].rstrip(" .,")


def _load_slug_filter(path_value: str) -> set[str]:
    path = Path(path_value).resolve()
    if not path.exists():
        raise FileNotFoundError(f"slugs-file not found: {path}")
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return set()
    if raw.startswith("["):
        payload = json.loads(raw)
        return {normalize_space(str(item)) for item in payload if normalize_space(str(item))}
    return {
        normalize_space(line)
        for line in raw.splitlines()
        if normalize_space(line)
    }


def _resolve_target_range(args: argparse.Namespace) -> tuple[date, date]:
    single_date = normalize_space(args.date)
    start_raw = normalize_space(args.start_date)
    end_raw = normalize_space(args.end_date)

    if single_date:
        if start_raw or end_raw:
            raise ValueError("--date cannot be combined with --start-date/--end-date.")
        start_raw = single_date
        end_raw = single_date

    if not start_raw or not end_raw:
        raise ValueError("Use either --date YYYY-MM-DD or both --start-date and --end-date.")

    try:
        start_date = date.fromisoformat(start_raw)
        end_date = date.fromisoformat(end_raw)
    except ValueError as exc:  # noqa: BLE001
        raise ValueError("Date format must be YYYY-MM-DD.") from exc

    if start_date > end_date:
        raise ValueError("--start-date must be less than or equal to --end-date.")
    return start_date, end_date


def _build_prompt(
    *,
    prompt_template: str,
    detail: dict[str, Any],
    local_date_label: str,
    timezone_name: str,
) -> str:
    title = normalize_space(str(detail.get("title") or ""))
    excerpt = normalize_space(str(detail.get("excerpt") or ""))
    content = str(detail.get("content") or "")
    category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    category_name = normalize_space(str(category.get("name") or category.get("slug") or "Cloudflare"))
    category_slug = normalize_space(str(category.get("slug") or ""))
    category_description = normalize_space(str(category.get("description") or ""))
    existing_tags = extract_tag_names(detail)
    source_text = _plain_text(content)[:2600]
    planner_brief = {
        "rewrite_mode": "cloudflare_live_refresh",
        "published_local_date": local_date_label,
        "timezone": timezone_name,
        "preserve_existing_images": True,
        "keep_slug_unchanged": True,
        "target_body_chars": "2800-4200",
        "existing_url": detail.get("publicUrl") or detail.get("url") or "",
        "existing_title": title,
        "existing_excerpt": excerpt,
        "existing_tags": existing_tags,
    }
    rendered = render_prompt_template(
        prompt_template,
        keyword=title or normalize_space(str(detail.get("slug") or "")),
        primary_language="ko",
        target_audience=_cloudflare_target_audience(category_slug, category_name),
        content_brief=_cloudflare_content_brief(category_slug, category_name, category_description),
        planner_brief=json.dumps(planner_brief, ensure_ascii=False, indent=2),
        current_date=f"{local_date_label} ({timezone_name})",
        editorial_category_key=_cloudflare_editorial_category_key(category_slug),
        editorial_category_label=category_name or "Cloudflare",
        editorial_category_guidance=_category_topic_guidance(category_slug, category_name, category_description),
    )
    return (
        f"{rendered.rstrip()}\n\n"
        "[Rewrite Mission]\n"
        "- Rewrite this live Cloudflare post from scratch with a CTR-first, SEO-ready Korean structure.\n"
        "- Do not write report-style sections (기준 시각, 핵심 요약, 확인된 사실, 미확인 정보/가정, 출처/확인 경로).\n"
        "- Keep the topic intent aligned to the original post, but improve title, lead, body flow, excerpt, tags, and meta description.\n"
        "- Existing image snippets are preserved separately. Do not include inline image tags in html_article.\n"
        "- Keep the main body practical and substantial, roughly 2800 to 4200 Korean characters before FAQ injection.\n"
        "- If exact schedules, prices, eligibility, or current policies are not explicit in source text, avoid inventing them.\n"
        "\n[Source Material]\n"
        f"- Existing category: {category_name}\n"
        f"- Existing title: {title}\n"
        f"- Existing excerpt: {excerpt}\n"
        f"- Existing tags: {', '.join(existing_tags) if existing_tags else 'none'}\n"
        f"- Existing public URL: {detail.get('publicUrl') or detail.get('url') or ''}\n"
        f"- Source body notes:\n{source_text}\n"
    )


def _validate_candidate(
    *,
    title: str,
    body: str,
    excerpt: str,
    meta_description: str,
    tags: list[str],
    min_body_chars: int,
    max_body_chars: int,
) -> tuple[bool, str]:
    plain_len = len(_plain_text(body))
    if plain_len < min_body_chars:
        return False, f"body_too_short:{plain_len}"
    if plain_len > max_body_chars:
        return False, f"body_too_long:{plain_len}"
    if len(HTML_H2_RE.findall(body)) < 5:
        return False, "insufficient_h2"
    if len(HTML_H3_RE.findall(body)) < 2:
        return False, "insufficient_h3"
    if _has_blocked_heading(body):
        return False, "blocked_heading"
    if len(normalize_space(title)) < 14:
        return False, "title_too_short"
    if len(normalize_space(excerpt)) < 60:
        return False, "excerpt_too_short"
    if len(normalize_space(meta_description)) < 120:
        return False, "meta_too_short"
    if len(tags) < 5:
        return False, "tags_too_few"
    return True, "ok"


def _backup_payload(*, backup_dir: Path, range_key: str, details: list[dict[str, Any]]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"cloudflare-{range_key}-{stamp}-before.json"
    payload = {
        "generated_at": _utc_now(),
        "range_key": range_key,
        "count": len(details),
        "posts": details,
    }
    write_json(path, payload)
    return path


def _read_prompt_template() -> str:
    path = REPO_ROOT / "prompts" / "travel_article_generation.md"
    return path.read_text(encoding="utf-8")


def _write_report(
    *,
    backup_dir: Path,
    report_prefix: str,
    mode: str,
    range_key: str,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = backup_dir / f"{report_prefix}-{range_key}-{mode}-{stamp}.json"
    payload = {
        "generated_at": _utc_now(),
        "mode": mode,
        "range_key": range_key,
        "summary": summary,
        "count": len(rows),
        "rows": rows,
    }
    write_json(path, payload)
    return path


def _in_range(local_date: str, start_date: date, end_date: date) -> bool:
    if not local_date:
        return False
    try:
        candidate = date.fromisoformat(local_date)
    except ValueError:
        return False
    return start_date <= candidate <= end_date


def main() -> int:
    args = parse_args()
    generation_enabled = bool(args.apply or args.preview)
    mode = "apply" if args.apply else ("preview" if args.preview else "dry-run")
    min_body_chars = max(int(args.min_body_chars), 1600)
    max_body_chars = max(int(args.max_body_chars), min_body_chars + 200)
    backup_dir = Path(args.backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    slug_filter = _load_slug_filter(args.slugs_file) if normalize_space(args.slugs_file) else set()

    try:
        start_date, end_date = _resolve_target_range(args)
    except ValueError as exc:  # noqa: BLE001
        raise RuntimeError(str(exc)) from exc

    try:
        target_tz = ZoneInfo(args.timezone)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Invalid timezone: {args.timezone}") from exc

    range_key = start_date.isoformat() if start_date == end_date else f"{start_date.isoformat()}_to_{end_date.isoformat()}"
    summary = {
        "timezone": args.timezone,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "processed": 0,
        "planned": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "cloudflare_api_rate_limit": "used/unknown",
    }
    report_rows: list[dict[str, Any]] = []

    with SessionLocal() as db:
        runtime = get_runtime_config(db)
        if generation_enabled and runtime.provider_mode != "live":
            raise RuntimeError(
                "provider_mode must be 'live' to generate rewrite candidates. "
                "Use --dry-run for backup/scope planning without content generation."
            )

        client = CloudflareIntegrationClient.from_db(db)
        summaries = client.list_posts()
        article_provider = None
        prompt_template = ""
        model = ""
        if generation_enabled:
            settings_map = get_settings_map(db)
            model = (
                normalize_space(args.model)
                or normalize_space(str(settings_map.get("article_generation_model") or ""))
                or normalize_space(str(settings_map.get("openai_large_text_model") or ""))
                or normalize_space(str(settings_map.get("openai_text_model") or ""))
                or "gpt-5.4"
            )
            prompt_template = _read_prompt_template()
            article_provider = get_article_provider(db, model_override=model, allow_large=True)

        target_summaries: list[dict[str, Any]] = []
        for item in summaries:
            if not isinstance(item, dict):
                continue
            if normalize_space(str(item.get("status") or "")).lower() != "published":
                continue
            normalized_slug = normalize_space(str(item.get("slug") or ""))
            if args.slug and normalized_slug != normalize_space(args.slug):
                continue
            if slug_filter and normalized_slug not in slug_filter:
                continue
            local_date = _to_local_date(
                str(
                    item.get("publishedAt")
                    or item.get("published_at")
                    or item.get("updatedAt")
                    or item.get("createdAt")
                    or ""
                ),
                target_tz,
            )
            if not _in_range(local_date, start_date, end_date):
                continue
            target_summaries.append(item)

        target_summaries.sort(
            key=lambda row: str(row.get("publishedAt") or row.get("published_at") or row.get("updatedAt") or "")
        )
        if args.limit > 0:
            target_summaries = target_summaries[: max(int(args.limit), 1)]

        if not target_summaries:
            raise RuntimeError(
                f"No published Cloudflare posts found in range {start_date.isoformat()}~{end_date.isoformat()} ({args.timezone})."
            )

        detailed_rows: list[dict[str, Any]] = []
        for summary_row in target_summaries:
            post_id = normalize_space(str(summary_row.get("id") or ""))
            if not post_id:
                continue
            try:
                detail = client.get_post(post_id)
            except Exception as exc:  # noqa: BLE001
                report_rows.append(
                    {
                        "status": "failed",
                        "reason": f"detail_fetch_failed:{exc}",
                        "slug": normalize_space(str(summary_row.get("slug") or "")),
                        "post_id": post_id,
                        "publish_local_date": "",
                        "title_before": normalize_space(str(summary_row.get("title") or "")),
                        "title_after": "",
                        "url": summary_row.get("publicUrl") or summary_row.get("url") or "",
                        "rate_limit": client.get_last_usage_ratio(),
                    }
                )
                continue
            if detail:
                detailed_rows.append(detail)

        backup_path = _backup_payload(backup_dir=backup_dir, range_key=range_key, details=detailed_rows)
        print(f"[backup] {backup_path}", flush=True)

        for index, detail in enumerate(detailed_rows, start=1):
            post_id = normalize_space(str(detail.get("id") or ""))
            slug = normalize_space(str(detail.get("slug") or ""))
            title_before = normalize_space(str(detail.get("title") or slug))
            current_content = str(detail.get("content") or "")
            existing_images = _extract_image_snippets(current_content)
            existing_tags = extract_tag_names(detail)
            category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
            category_name = normalize_space(str(category.get("name") or category.get("slug") or "Cloudflare"))
            publish_local_date = _to_local_date(
                str(
                    detail.get("publishedAt")
                    or detail.get("published_at")
                    or detail.get("updatedAt")
                    or detail.get("createdAt")
                    or ""
                ),
                target_tz,
            )

            if not generation_enabled:
                print(f"[{index}/{len(detailed_rows)}] plan {slug}", flush=True)
                usage_ratio = client.get_last_usage_ratio()
                if usage_ratio != "used/unknown":
                    summary["cloudflare_api_rate_limit"] = usage_ratio
                summary["processed"] += 1
                summary["planned"] += 1
                report_rows.append(
                    {
                        "status": "planned",
                        "reason": "dry_run_no_generation",
                        "slug": slug,
                        "post_id": post_id,
                        "publish_local_date": publish_local_date,
                        "title_before": title_before,
                        "title_after": "",
                        "url": detail.get("publicUrl") or detail.get("url") or "",
                        "rate_limit": usage_ratio,
                    }
                )
                print(f"[rate-limit] cloudflare-api {usage_ratio}", flush=True)
                continue

            if article_provider is None:
                raise RuntimeError("Internal error: article provider is missing in generation mode.")

            print(f"[{index}/{len(detailed_rows)}] rewrite {slug}", flush=True)
            best_payload: dict[str, Any] | None = None
            failure_reason = "no_candidate"

            for attempt in range(1, max(int(args.max_attempts), 1) + 1):
                prompt = _build_prompt(
                    prompt_template=prompt_template,
                    detail=detail,
                    local_date_label=publish_local_date or start_date.isoformat(),
                    timezone_name=args.timezone,
                )
                try:
                    output, _raw = article_provider.generate_article(title_before, prompt)
                except Exception as exc:  # noqa: BLE001
                    failure_reason = f"attempt_{attempt}_generation_failed:{exc}"
                    continue

                candidate_title = normalize_space(output.title)
                candidate_excerpt = _finalize_excerpt(output.excerpt, f"{candidate_title}. {_plain_text(current_content)}")
                candidate_tags = _normalize_tags(list(output.labels or []), category_name=category_name, existing_tags=existing_tags)

                article_body = _strip_existing_heading(str(output.html_article or ""))
                article_body = _strip_inline_images(article_body)
                article_body = _localize_common_headings(article_body)
                article_body = _expand_body_to_min_chars(
                    article_body,
                    source_text=_plain_text(current_content),
                    min_body_chars=max(min_body_chars - 450, 1800),
                )
                faq_html = _faq_to_html(list(output.faq_section or []))
                merged_body = f"{article_body}\n\n{faq_html}".strip()
                merged_body = _inject_images_before_faq(merged_body, existing_images)
                final_content = f"# {candidate_title}\n\n{merged_body}".strip()
                candidate_meta = _finalize_meta(
                    output.meta_description,
                    f"{candidate_excerpt} {_plain_text(final_content)}",
                )

                ok, reason = _validate_candidate(
                    title=candidate_title,
                    body=final_content,
                    excerpt=candidate_excerpt,
                    meta_description=candidate_meta,
                    tags=candidate_tags,
                    min_body_chars=min_body_chars,
                    max_body_chars=max_body_chars,
                )
                if ok:
                    best_payload = {
                        "title": candidate_title,
                        "content": final_content,
                        "excerpt": candidate_excerpt,
                        "seoDescription": candidate_meta,
                        "seoTitle": candidate_title,
                        "tagNames": candidate_tags,
                    }
                    failure_reason = f"attempt_{attempt}_accepted"
                    break
                failure_reason = f"attempt_{attempt}_{reason}"

            if best_payload is None:
                summary["processed"] += 1
                summary["skipped"] += 1
                report_rows.append(
                    {
                        "status": "skipped",
                        "reason": failure_reason,
                        "slug": slug,
                        "post_id": post_id,
                        "publish_local_date": publish_local_date,
                        "title_before": title_before,
                        "title_after": "",
                        "url": detail.get("publicUrl") or detail.get("url") or "",
                        "rate_limit": client.get_last_usage_ratio(),
                    }
                )
                continue

            row_status = "planned"
            row_reason = "preview" if args.preview else "dry_run"
            if args.apply:
                try:
                    client.update_post(post_id, best_payload)
                    row_status = "updated"
                    row_reason = "applied"
                except Exception as exc:  # noqa: BLE001
                    summary["processed"] += 1
                    summary["failed"] += 1
                    report_rows.append(
                        {
                            "status": "failed",
                            "reason": f"update_failed:{exc}",
                            "slug": slug,
                            "post_id": post_id,
                            "publish_local_date": publish_local_date,
                            "title_before": title_before,
                            "title_after": best_payload["title"],
                            "url": detail.get("publicUrl") or detail.get("url") or "",
                            "rate_limit": client.get_last_usage_ratio(),
                        }
                    )
                    continue

            usage_ratio = client.get_last_usage_ratio()
            if usage_ratio != "used/unknown":
                summary["cloudflare_api_rate_limit"] = usage_ratio

            write_json(
                backup_dir / f"{safe_filename(slug, 'post')}-after.json",
                {
                    "generated_at": _utc_now(),
                    "mode": mode,
                    "range_key": range_key,
                    "timezone": args.timezone,
                    "post_id": post_id,
                    "slug": slug,
                    "before": {
                        "title": title_before,
                        "excerpt": detail.get("excerpt"),
                        "seoDescription": detail.get("seoDescription"),
                        "tagNames": existing_tags,
                    },
                    "after": best_payload,
                    "rate_limit": usage_ratio,
                },
            )

            summary["processed"] += 1
            if row_status == "updated":
                summary["updated"] += 1
            else:
                summary["planned"] += 1
            report_rows.append(
                {
                    "status": row_status,
                    "reason": row_reason,
                    "slug": slug,
                    "post_id": post_id,
                    "publish_local_date": publish_local_date,
                    "title_before": title_before,
                    "title_after": best_payload["title"],
                    "url": detail.get("publicUrl") or detail.get("url") or "",
                    "tags": best_payload["tagNames"],
                    "rate_limit": usage_ratio,
                }
            )
            print(f"[rate-limit] cloudflare-api {usage_ratio}", flush=True)

    report_path = _write_report(
        backup_dir=backup_dir,
        report_prefix=normalize_space(args.report_prefix) or "cloudflare-range-rewrite",
        mode=mode,
        range_key=range_key,
        summary=summary,
        rows=report_rows,
    )
    print(
        json.dumps(
            {
                "mode": mode,
                "timezone": args.timezone,
                "range": f"{start_date.isoformat()}~{end_date.isoformat()}",
                "processed": summary["processed"],
                "updated": summary["updated"],
                "planned": summary["planned"],
                "skipped": summary["skipped"],
                "failed": summary["failed"],
                "cloudflare_api_rate_limit": summary["cloudflare_api_rate_limit"],
                "report": str(report_path),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
