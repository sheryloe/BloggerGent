from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_DIR = LOCAL_STORAGE_ROOT / "reports"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(LOCAL_STORAGE_ROOT)

sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, PostStatus  # noqa: E402
from app.services.article_service import estimate_reading_time, sanitize_blog_html  # noqa: E402
from app.services.cloudflare_channel_service import _sync_cloudflare_quality_rows, list_cloudflare_posts  # noqa: E402
from app.services.content_ops_service import compute_seo_geo_scores, compute_similarity_analysis, normalize_similarity_text  # noqa: E402
from app.services.google_sheet_service import (  # noqa: E402
    BLOGGER_SNAPSHOT_COLUMNS,
    QUALITY_COLUMNS,
    get_google_sheet_sync_config,
    sync_google_sheet_quality_tab,
)
from app.services.providers.factory import get_blogger_provider  # noqa: E402
from app.services.publishing_service import rebuild_article_html, refresh_article_public_image, upsert_article_blogger_post  # noqa: E402
from app.services.settings_service import get_settings_map  # noqa: E402


TAG_RE = re.compile(r"<[^>]+>")
QUALITY_TIMEZONE = ZoneInfo("Asia/Seoul")
SUPPORTED_PROFILES = ("korea_travel", "world_mystery")

TRAVEL_CATEGORY_HINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "travel": ("Travel", ("travel", "trip", "route", "itinerary", "walk", "neighborhood", "local")),
    "culture": ("Culture", ("culture", "festival", "event", "exhibition", "museum", "heritage", "idol", "filming")),
    "food": ("Food", ("food", "restaurant", "market", "cafe", "eatery", "korean food", "dining")),
}

MYSTERY_CATEGORY_HINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "case-files": ("Case Files", ("case", "incident", "investigation", "evidence", "timeline", "disappearance", "murder")),
    "legends-lore": ("Legends & Lore", ("legend", "folklore", "myth", "urban legend", "scp", "lore", "haunted")),
    "mystery-archives": ("Mystery Archives", ("archive", "historical", "record", "document", "expedition", "manuscript", "chronology")),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync quality metrics to Google Sheet and auto-rewrite high-similarity posts.")
    parser.add_argument("--profile", choices=SUPPORTED_PROFILES, default="world_mystery", help="Rewrite target profile key")
    parser.add_argument("--published-only", action="store_true", help="Limit analysis/rewrite candidates to published posts only")
    parser.add_argument("--rewrite-threshold", type=float, default=70.0, help="Similarity threshold for rewrite target")
    parser.add_argument("--max-rewrite-attempts", type=int, default=3, help="Maximum rewrite attempts per article")
    parser.add_argument("--rewrite-model", default="gpt-5.4", help="OpenAI model for rewrite attempts")
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit per profile for analysis")
    parser.add_argument("--sync-sheet", action="store_true", help="Write quality rows to configured Google Sheet tabs")
    parser.add_argument("--sync-blogger", action="store_true", help="Update live Blogger post after successful rewrite")
    parser.add_argument("--execute", action="store_true", help="Apply rewrite actions. Without this flag, run in dry mode")
    parser.add_argument("--report-prefix", default="sheet-quality-sync", help="Prefix for report file names")
    return parser.parse_args()


def _safe_str(value: object | None) -> str:
    return str(value or "").strip()


def _is_enabled(value: object | None, *, default: bool = False) -> bool:
    normalized = _safe_str(value).lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "y", "yes", "on"}


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(QUALITY_TIMEZONE).replace(microsecond=0).isoformat()


def _normalize_datetime_text(value: object | None) -> str:
    text = _safe_str(value)
    if not text:
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(QUALITY_TIMEZONE).replace(microsecond=0).isoformat()


def _plain_text(value: str | None) -> str:
    raw = TAG_RE.sub(" ", value or "")
    return re.sub(r"\s+", " ", raw).strip()


def _infer_editorial_category(*, profile: str, labels: list[str], title: str, summary: str) -> tuple[str, str]:
    hint_map = TRAVEL_CATEGORY_HINTS if profile == "korea_travel" else MYSTERY_CATEGORY_HINTS
    normalized_labels = {label.strip().lower() for label in labels if label and label.strip()}

    for key, (label, _hints) in hint_map.items():
        if label.lower() in normalized_labels:
            return key, label

    haystack = f"{title} {summary} {' '.join(labels)}".lower()
    best_key = ""
    best_label = ""
    best_score = -1
    for key, (label, hints) in hint_map.items():
        score = sum(1 for hint in hints if hint in haystack)
        if score > best_score:
            best_key = key
            best_label = label
            best_score = score

    if best_key and best_label:
        return best_key, best_label
    fallback_key, (fallback_label, _hints) = next(iter(hint_map.items()))
    return fallback_key, fallback_label


def _infer_topic_cluster(slug: str, title: str, cluster_value: str | None) -> str:
    normalized = _safe_str(cluster_value)
    if normalized:
        return normalized
    tokens = [token for token in _safe_str(slug).split("-") if token]
    stop_words = {
        "the",
        "and",
        "guide",
        "tips",
        "travel",
        "mystery",
        "historical",
        "history",
        "review",
        "analysis",
        "for",
        "with",
        "from",
        "2026",
    }
    selected: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in stop_words:
            continue
        selected.append(token)
        if len(selected) >= 4:
            break
    if selected:
        return "-".join(selected)
    words = [word for word in normalize_similarity_text(title).split(" ") if word]
    return "-".join(words[:4])


def _infer_topic_angle(title: str, excerpt: str, angle_value: str | None) -> str:
    normalized = _safe_str(angle_value)
    if normalized:
        return normalized
    haystack = f"{title} {excerpt}".lower()
    rules = [
        ("schedule", ("schedule", "timing", "date", "calendar")),
        ("transport", ("transport", "subway", "bus", "route", "transfer")),
        ("food", ("food", "eat", "restaurant", "snack", "menu")),
        ("crowd", ("crowd", "queue", "line", "peak", "busy")),
        ("timeline", ("timeline", "chronology", "sequence")),
        ("theory", ("theory", "hypothesis", "interpretation")),
        ("cultural_impact", ("culture", "impact", "legacy", "influence")),
    ]
    for label, keywords in rules:
        if any(keyword in haystack for keyword in keywords):
            return label
    return "overview"


def _load_article_rows(
    *,
    profile: str | None = None,
    published_only: bool = False,
    limit: int = 0,
) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        stmt = (
            select(Article)
            .join(Blog, Blog.id == Article.blog_id)
            .options(
                selectinload(Article.blog),
                selectinload(Article.topic),
                selectinload(Article.blogger_post),
                selectinload(Article.image),
            )
            .where(Blog.is_active.is_(True))
            .order_by(Article.created_at.desc(), Article.id.desc())
        )
        if profile:
            stmt = stmt.where(Blog.profile_key == profile)
        if published_only:
            stmt = stmt.where(Article.blogger_post.has(post_status=PostStatus.PUBLISHED))
        if limit > 0:
            stmt = stmt.limit(limit)
        articles = db.execute(stmt).scalars().all()

    rows: list[dict[str, Any]] = []
    for article in articles:
        blog = article.blog
        blogger_post = article.blogger_post
        labels = article.labels if isinstance(article.labels, list) else []
        topic = article.topic
        status = blogger_post.post_status.value if blogger_post else "draft"
        category_label = _safe_str(getattr(article, "editorial_category_label", None) or (topic.editorial_category_label if topic else ""))
        category_key = _safe_str(getattr(article, "editorial_category_key", None) or (topic.editorial_category_key if topic else ""))
        if not category_label or not category_key:
            inferred_key, inferred_label = _infer_editorial_category(
                profile=_safe_str(blog.profile_key if blog else ""),
                labels=[_safe_str(label) for label in labels],
                title=_safe_str(article.title),
                summary=_safe_str(article.excerpt),
            )
            category_key = category_key or inferred_key
            category_label = category_label or inferred_label
        rows.append(
            {
                "article_id": article.id,
                "blog_id": blog.id if blog else 0,
                "profile": _safe_str(blog.profile_key if blog else ""),
                "blog": _safe_str(blog.name if blog else ""),
                "title": _safe_str(article.title),
                "url": _safe_str(blogger_post.published_url if blogger_post else ""),
                "slug": _safe_str(article.slug),
                "summary": _safe_str(article.excerpt),
                "labels": ", ".join(_safe_str(label) for label in labels if _safe_str(label)),
                "status": status,
                "published_at": _format_datetime(blogger_post.published_at if blogger_post else None),
                "updated_at": _format_datetime(article.updated_at),
                "date_kst": _format_datetime(article.created_at),
                "content_category": category_label,
                "category_key": category_key,
                "topic_cluster": _infer_topic_cluster(article.slug, article.title, topic.topic_cluster_label if topic else None),
                "topic_angle": _infer_topic_angle(article.title, article.excerpt, topic.topic_angle_label if topic else None),
                "body_html": article.html_article or "",
                "assembled_html": article.assembled_html or "",
                "faq_section": list(article.faq_section or []),
                "rewrite_attempts": 0,
                "quality_status": "ok",
                "last_audited_at": "",
            }
        )
    return rows


def _apply_similarity_and_scores(rows: list[dict[str, Any]], *, rewrite_threshold: float) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["profile"], []).append(row)

    for profile_rows in grouped.values():
        similarity_input = [
            {
                "key": str(row["article_id"]),
                "title": row["title"],
                "body_html": row["body_html"],
                "url": row["url"],
            }
            for row in profile_rows
        ]
        similarity_map = compute_similarity_analysis(similarity_input)
        for row in profile_rows:
            key = str(row["article_id"])
            similarity_payload = similarity_map.get(
                key,
                {
                    "similarity_score": 0.0,
                    "most_similar_url": "",
                },
            )
            row["similarity_score"] = f"{float(similarity_payload.get('similarity_score', 0.0)):.1f}"
            row["most_similar_url"] = _safe_str(similarity_payload.get("most_similar_url"))
            score_payload = compute_seo_geo_scores(
                title=row["title"],
                html_body=row["body_html"],
                excerpt=row["summary"],
                faq_section=row["faq_section"],
            )
            row["seo_score"] = str(int(score_payload["seo_score"]))
            row["geo_score"] = str(int(score_payload["geo_score"]))
            if row["status"] != "published":
                row["quality_status"] = "DISLIVE"
            elif row["profile"] == "world_mystery" and float(row["similarity_score"]) >= rewrite_threshold:
                row["quality_status"] = "rewrite_required"
            else:
                row["quality_status"] = "ok"
            row["last_audited_at"] = datetime.now(QUALITY_TIMEZONE).replace(microsecond=0).isoformat()


def _build_rewrite_prompt(row: dict[str, Any], *, attempt: int) -> str:
    plain_body = _plain_text(row["body_html"])
    return f"""Revise this mystery article while preserving topic and factual spine. Return JSON only.

JSON schema:
{{
  "excerpt": "string",
  "meta_description": "string",
  "html_article": "string",
  "faq_section": [{{"question":"string","answer":"string"}}]
}}

Hard rules:
- Keep the title exactly unchanged.
- Keep the same case, same timeline scope, and same named entities.
- Improve clarity and structure by changing sentence flow and section ordering.
- Avoid duplicated sentence patterns from the source.
- Do not mention AI generation, collage, prompt, or internal tooling.
- Use only these tags in html_article: h2, h3, p, ul, li, strong, br.
- Do not output img, figure, table, iframe, code fence, markdown.
- Keep quality high while reducing overlap with near-duplicate posts.
- Attempt #{attempt}: prioritize semantic diversity without changing core facts.

Article context:
- Profile: {row["profile"]}
- Topic cluster: {row["topic_cluster"]}
- Topic angle: {row["topic_angle"]}
- Title: {row["title"]}
- Excerpt: {row["summary"]}
- Current body:
{plain_body}
"""


def _request_rewrite_payload(api_key: str, model: str, row: dict[str, Any], *, attempt: int) -> dict[str, Any]:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "You rewrite published mystery articles. Return strict JSON only.",
                },
                {"role": "user", "content": _build_rewrite_prompt(row, attempt=attempt)},
            ],
        },
        timeout=300.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _validate_rewrite_payload(original_row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    excerpt = _safe_str(payload.get("excerpt"))
    meta_description = _safe_str(payload.get("meta_description"))
    html_article = sanitize_blog_html(_safe_str(payload.get("html_article")))
    faq_section = payload.get("faq_section") if isinstance(payload.get("faq_section"), list) else []

    if len(excerpt) < 50:
        raise ValueError("excerpt_too_short")
    if len(meta_description) < 50 or len(meta_description) > 320:
        raise ValueError("meta_description_length_invalid")
    if any(tag in html_article.lower() for tag in ["<img", "<figure", "<table", "<iframe"]):
        raise ValueError("disallowed_html_tag_detected")

    valid_faq: list[dict[str, str]] = []
    for item in faq_section[:8]:
        if not isinstance(item, dict):
            continue
        question = _safe_str(item.get("question"))
        answer = _safe_str(item.get("answer"))
        if len(question) < 5 or len(answer) < 10:
            continue
        valid_faq.append({"question": question, "answer": answer})
    if len(valid_faq) < 2:
        raise ValueError("faq_section_too_short")

    original_plain_length = len(_plain_text(original_row["body_html"]))
    revised_plain_length = len(_plain_text(html_article))
    minimum_length = max(2500, int(original_plain_length * 0.8))
    if revised_plain_length < minimum_length:
        raise ValueError(f"rewritten_body_too_short:{revised_plain_length}<{minimum_length}")

    return {
        "excerpt": excerpt,
        "meta_description": meta_description,
        "html_article": html_article,
        "faq_section": valid_faq,
    }


def _candidate_similarity(
    *,
    candidate_row: dict[str, Any],
    profile_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    items = [
        {
            "key": "__candidate__",
            "title": candidate_row["title"],
            "body_html": candidate_row["body_html"],
            "url": candidate_row.get("url", ""),
        }
    ]
    for row in profile_rows:
        if row["article_id"] == candidate_row["article_id"]:
            continue
        items.append(
            {
                "key": str(row["article_id"]),
                "title": row["title"],
                "body_html": row["body_html"],
                "url": row.get("url", ""),
            }
        )
    result = compute_similarity_analysis(items).get("__candidate__", {})
    return {
        "similarity_score": float(result.get("similarity_score", 0.0)),
        "most_similar_url": _safe_str(result.get("most_similar_url")),
    }


def _load_runtime_keys() -> tuple[str, str]:
    with SessionLocal() as db:
        values = get_settings_map(db)
        api_key = _safe_str(values.get("openai_api_key"))
        model = (
            _safe_str(values.get("article_generation_model"))
            or _safe_str(values.get("openai_text_model"))
            or "gpt-5.4"
        )
    return api_key, model


def _apply_rewrite_to_article(
    *,
    article_id: int,
    validated_payload: dict[str, Any],
    sync_blogger: bool,
) -> str:
    with SessionLocal() as db:
        article = db.execute(
            select(Article)
            .where(Article.id == article_id)
            .options(
                selectinload(Article.blog),
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
        ).scalar_one_or_none()
        if article is None:
            raise ValueError(f"article_not_found:{article_id}")

        article.excerpt = validated_payload["excerpt"]
        article.meta_description = validated_payload["meta_description"]
        article.html_article = validated_payload["html_article"]
        article.faq_section = validated_payload["faq_section"]
        article.reading_time_minutes = estimate_reading_time(validated_payload["html_article"])
        db.add(article)
        db.commit()
        db.refresh(article)

        hero_url = refresh_article_public_image(db, article) or (article.image.public_url if article.image else "")
        rebuild_article_html(db, article, hero_url)
        db.refresh(article)

        if not sync_blogger:
            return "rebuilt"
        if not article.blog or not article.blogger_post:
            return "skip:no-linked-post"
        if article.blogger_post.post_status not in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
            return "skip:not-live"

        provider = get_blogger_provider(db, article.blog)
        if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
            return "skip:mock-provider"

        summary, raw_payload = provider.update_post(
            post_id=article.blogger_post.blogger_post_id,
            title=article.title,
            content=article.assembled_html or article.html_article,
            labels=list(article.labels or []),
            meta_description=article.meta_description or "",
        )
        upsert_article_blogger_post(
            db,
            article=article,
            summary=summary,
            raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
        )
        return "rebuilt+blogger_updated"


def _run_rewrite_loop(
    *,
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[int, dict[str, Any]]:
    outcomes: dict[int, dict[str, Any]] = {}
    target_rows = [
        row
        for row in rows
        if row["profile"] == args.profile
        and row["status"] == "published"
        and float(row.get("similarity_score") or 0.0) >= float(args.rewrite_threshold)
    ]
    if not target_rows:
        return outcomes

    api_key, configured_model = _load_runtime_keys()
    model = _safe_str(args.rewrite_model) or configured_model
    if not api_key:
        for row in target_rows:
            outcomes[row["article_id"]] = {
                "status": "failed",
                "reason": "openai_api_key_missing",
                "rewrite_attempts": 0,
            }
        return outcomes

    for row in sorted(target_rows, key=lambda item: float(item.get("similarity_score") or 0.0), reverse=True):
        article_id = int(row["article_id"])
        baseline_seo = int(row.get("seo_score") or 0)
        baseline_geo = int(row.get("geo_score") or 0)
        last_error = ""
        success = False
        attempts_used = 0
        for attempt in range(1, max(1, int(args.max_rewrite_attempts)) + 1):
            attempts_used = attempt
            try:
                payload = _request_rewrite_payload(api_key, model, row, attempt=attempt)
                validated = _validate_rewrite_payload(row, payload)
                candidate_row = dict(row)
                candidate_row["summary"] = validated["excerpt"]
                candidate_row["body_html"] = validated["html_article"]
                candidate_row["faq_section"] = validated["faq_section"]
                score_payload = compute_seo_geo_scores(
                    title=candidate_row["title"],
                    html_body=candidate_row["body_html"],
                    excerpt=candidate_row["summary"],
                    faq_section=candidate_row["faq_section"],
                )
                candidate_seo = int(score_payload["seo_score"])
                candidate_geo = int(score_payload["geo_score"])
                if candidate_seo < baseline_seo - 5 or candidate_geo < baseline_geo - 5:
                    last_error = (
                        f"quality_gate_failed:seo={candidate_seo}/{baseline_seo},geo={candidate_geo}/{baseline_geo}"
                    )
                    continue
                candidate_similarity = _candidate_similarity(
                    candidate_row=candidate_row,
                    profile_rows=[item for item in rows if item["profile"] == row["profile"]],
                )
                similarity_score = float(candidate_similarity["similarity_score"])
                if similarity_score >= float(args.rewrite_threshold):
                    last_error = f"similarity_not_improved:{similarity_score:.1f}"
                    continue

                if args.execute:
                    rebuild_status = _apply_rewrite_to_article(
                        article_id=article_id,
                        validated_payload=validated,
                        sync_blogger=bool(args.sync_blogger),
                    )
                else:
                    rebuild_status = "dry-run"

                row["summary"] = validated["excerpt"]
                row["body_html"] = validated["html_article"]
                row["faq_section"] = validated["faq_section"]
                row["seo_score"] = str(candidate_seo)
                row["geo_score"] = str(candidate_geo)
                row["similarity_score"] = f"{similarity_score:.1f}"
                row["most_similar_url"] = candidate_similarity["most_similar_url"]
                row["quality_status"] = "ok"
                row["rewrite_attempts"] = attempt
                row["last_audited_at"] = datetime.now(QUALITY_TIMEZONE).replace(microsecond=0).isoformat()
                outcomes[article_id] = {
                    "status": "updated",
                    "rewrite_attempts": attempt,
                    "similarity_score": row["similarity_score"],
                    "seo_score": row["seo_score"],
                    "geo_score": row["geo_score"],
                    "rebuild_status": rebuild_status,
                }
                success = True
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                continue

        if success:
            continue
        row["quality_status"] = "manual_review_required"
        row["rewrite_attempts"] = attempts_used
        row["last_audited_at"] = datetime.now(QUALITY_TIMEZONE).replace(microsecond=0).isoformat()
        outcomes[article_id] = {
            "status": "manual_review_required",
            "rewrite_attempts": attempts_used,
            "reason": last_error or "rewrite_threshold_not_met",
        }

    return outcomes


def _prepare_cloudflare_rows() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        posts = list_cloudflare_posts(db)
    rows: list[dict[str, Any]] = []
    for index, post in enumerate(posts, start=1):
        excerpt = _safe_str(post.get("excerpt"))
        title = _safe_str(post.get("title"))
        body_html = f"<p>{excerpt}</p>" if excerpt else "<p></p>"
        category_name = _safe_str(post.get("category_name"))
        category_slug = _safe_str(post.get("category_slug"))
        category_cell = category_name or _safe_str(post.get("channel_name"))
        status_value = _safe_str(post.get("status")).lower() or "published"
        created_at = _normalize_datetime_text(post.get("created_at"))
        updated_at = _normalize_datetime_text(post.get("updated_at"))
        published_at = _normalize_datetime_text(post.get("published_at"))
        if not published_at and status_value in {"published", "live"}:
            published_at = updated_at or created_at
        rows.append(
            {
                "key": f"cf-{index}",
                "remote_id": _safe_str(post.get("remote_id")),
                "published_at": published_at,
                "created_at": created_at,
                "updated_at": updated_at,
                "category": category_cell,
                "category_slug": category_slug,
                "title": title,
                "url": _safe_str(post.get("published_url")),
                "excerpt": excerpt,
                "labels": ", ".join(_safe_str(label) for label in (post.get("labels") or []) if _safe_str(label)),
                "status": status_value,
                "topic_cluster": category_slug or category_cell or "cloudflare",
                "topic_angle": "channel_post",
                "body_html": body_html,
            }
        )

    similarity_map = compute_similarity_analysis(
        [
            {
                "key": row["key"],
                "title": row["title"],
                "body_html": row["body_html"],
                "url": row["url"],
            }
            for row in rows
        ]
    )
    for row in rows:
        similarity_payload = similarity_map.get(row["key"], {"similarity_score": 0.0, "most_similar_url": ""})
        score_payload = compute_seo_geo_scores(
            title=row["title"],
            html_body=row["body_html"],
            excerpt=row["excerpt"],
            faq_section=[],
        )
        row["similarity_score"] = f"{float(similarity_payload.get('similarity_score', 0.0)):.1f}"
        row["most_similar_url"] = _safe_str(similarity_payload.get("most_similar_url"))
        row["seo_score"] = str(int(score_payload["seo_score"]))
        row["geo_score"] = str(int(score_payload["geo_score"]))
        row["quality_status"] = "ok" if row["status"] in {"published", "live"} else "DISLIVE"
        row["rewrite_attempts"] = "0"
        row["last_audited_at"] = datetime.now(QUALITY_TIMEZONE).replace(microsecond=0).isoformat()
    return rows


def _sheet_payload_for_blogger(rows: list[dict[str, Any]], *, profile: str) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for row in rows:
        if row["profile"] != profile:
            continue
        payload.append(
            {
                "date_kst": _safe_str(row["date_kst"]),
                "profile": _safe_str(row["profile"]),
                "blog": _safe_str(row["blog"]),
                "title": _safe_str(row["title"]),
                "url": _safe_str(row["url"]),
                "slug": _safe_str(row["slug"]),
                "summary": _safe_str(row["summary"]),
                "labels": _safe_str(row["labels"]),
                "status": _safe_str(row["status"]),
                "published_at": _safe_str(row["published_at"]),
                "updated_at": _safe_str(row["updated_at"]),
                "due_at": _safe_str(
                    row.get("scheduled_for")
                    or row.get("published_at")
                    or row.get("updated_at")
                    or row.get("date_kst")
                ),
                "content_category": _safe_str(row.get("content_category")),
                "category_key": _safe_str(row.get("category_key")),
                "topic_cluster": _safe_str(row["topic_cluster"]),
                "topic_angle": _safe_str(row["topic_angle"]),
                "similarity_score": _safe_str(row["similarity_score"]),
                "most_similar_url": _safe_str(row["most_similar_url"]),
                "seo_score": _safe_str(row["seo_score"]),
                "geo_score": _safe_str(row["geo_score"]),
                "quality_status": _safe_str(row["quality_status"]),
                "rewrite_attempts": _safe_str(row["rewrite_attempts"]),
                "last_audited_at": _safe_str(row["last_audited_at"]),
            }
        )
    return payload


def _sheet_payload_for_cloudflare(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for row in rows:
        payload.append(
            {
                "remote_id": _safe_str(row.get("remote_id")),
                "published_at": _safe_str(row["published_at"]),
                "created_at": _safe_str(row.get("created_at")),
                "updated_at": _safe_str(row["updated_at"]),
                "due_at": _safe_str(row.get("published_at") or row.get("updated_at") or row.get("created_at")),
                "category": _safe_str(row["category"]),
                "category_slug": _safe_str(row.get("category_slug")),
                "title": _safe_str(row["title"]),
                "url": _safe_str(row["url"]),
                "excerpt": _safe_str(row["excerpt"]),
                "labels": _safe_str(row["labels"]),
                "status": _safe_str(row["status"]),
                "topic_cluster": _safe_str(row["topic_cluster"]),
                "topic_angle": _safe_str(row["topic_angle"]),
                "similarity_score": _safe_str(row["similarity_score"]),
                "most_similar_url": _safe_str(row["most_similar_url"]),
                "seo_score": _safe_str(row["seo_score"]),
                "geo_score": _safe_str(row["geo_score"]),
                "quality_status": _safe_str(row["quality_status"]),
                "rewrite_attempts": _safe_str(row["rewrite_attempts"]),
                "last_audited_at": _safe_str(row["last_audited_at"]),
            }
        )
    return payload


def _sync_sheet_rows(
    *,
    blogger_rows: list[dict[str, Any]],
    cloudflare_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    with SessionLocal() as db:
        config = get_google_sheet_sync_config(db)
        sheet_id = _safe_str(config["sheet_id"])
        auto_format_enabled = _is_enabled(config.get("auto_format_enabled"), default=True)
        if not sheet_id:
            return {"status": "skipped", "reason": "google_sheet_not_configured"}

        travel_result = sync_google_sheet_quality_tab(
            db,
            sheet_id=sheet_id,
            tab_name=config["travel_tab"],
            incoming_rows=_sheet_payload_for_blogger(blogger_rows, profile="korea_travel"),
            base_columns=BLOGGER_SNAPSHOT_COLUMNS,
            quality_columns=QUALITY_COLUMNS,
            key_columns=("url", "slug"),
            auto_format_enabled=auto_format_enabled,
        )
        mystery_result = sync_google_sheet_quality_tab(
            db,
            sheet_id=sheet_id,
            tab_name=config["mystery_tab"],
            incoming_rows=_sheet_payload_for_blogger(blogger_rows, profile="world_mystery"),
            base_columns=BLOGGER_SNAPSHOT_COLUMNS,
            quality_columns=QUALITY_COLUMNS,
            key_columns=("url", "slug"),
            auto_format_enabled=auto_format_enabled,
        )
        cloudflare_result = _sync_cloudflare_quality_rows(
            db,
            rows=_sheet_payload_for_cloudflare(cloudflare_rows),
        )
        return {
            "status": "ok",
            "sheet_id": sheet_id,
            "travel": travel_result,
            "mystery": mystery_result,
            "cloudflare": cloudflare_result,
        }


def _write_report(*, args: argparse.Namespace, rows: list[dict[str, Any]], outcomes: dict[int, dict[str, Any]], sheet_result: dict[str, Any]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"{args.report_prefix}-{stamp}.json"
    md_path = REPORT_DIR / f"{args.report_prefix}-{stamp}.md"

    payload = {
        "generated_at": datetime.now(QUALITY_TIMEZONE).replace(microsecond=0).isoformat(),
        "args": vars(args),
        "summary": {
            "total_rows": len(rows),
            "published_rows": len([row for row in rows if row["status"] == "published"]),
            "rewrite_required_rows": len([row for row in rows if row["quality_status"] == "rewrite_required"]),
            "updated_rows": len([item for item in outcomes.values() if item.get("status") == "updated"]),
            "manual_review_required_rows": len([item for item in outcomes.values() if item.get("status") == "manual_review_required"]),
        },
        "rewrite_outcomes": outcomes,
        "sheet_sync": sheet_result,
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# {args.report_prefix}",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- total_rows: {payload['summary']['total_rows']}",
        f"- published_rows: {payload['summary']['published_rows']}",
        f"- rewrite_required_rows: {payload['summary']['rewrite_required_rows']}",
        f"- updated_rows: {payload['summary']['updated_rows']}",
        f"- manual_review_required_rows: {payload['summary']['manual_review_required_rows']}",
        "",
        "## Rewrite Outcomes",
        "",
    ]
    if not outcomes:
        lines.append("- none")
    else:
        for article_id, outcome in sorted(outcomes.items()):
            lines.append(
                f"- article_id={article_id} status={outcome.get('status')} attempts={outcome.get('rewrite_attempts')} "
                f"similarity={outcome.get('similarity_score', '')} reason={outcome.get('reason', '')}"
            )
    lines.extend(["", "## Sheet Sync", "", f"- {json.dumps(sheet_result, ensure_ascii=False)}", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    args = parse_args()

    rows = _load_article_rows(profile=None, published_only=args.published_only, limit=args.limit)
    _apply_similarity_and_scores(rows, rewrite_threshold=float(args.rewrite_threshold))

    rewrite_outcomes: dict[int, dict[str, Any]] = {}
    if args.execute:
        rewrite_outcomes = _run_rewrite_loop(rows=rows, args=args)
        rows = _load_article_rows(profile=None, published_only=args.published_only, limit=args.limit)
        _apply_similarity_and_scores(rows, rewrite_threshold=float(args.rewrite_threshold))
        for row in rows:
            outcome = rewrite_outcomes.get(int(row["article_id"]))
            if outcome:
                row["rewrite_attempts"] = int(outcome.get("rewrite_attempts") or 0)
                if outcome.get("status") == "manual_review_required":
                    row["quality_status"] = "manual_review_required"

    cloudflare_rows = _prepare_cloudflare_rows()
    sheet_result: dict[str, Any] = {"status": "skipped", "reason": "sync_sheet_flag_disabled"}
    if args.sync_sheet:
        sheet_result = _sync_sheet_rows(blogger_rows=rows, cloudflare_rows=cloudflare_rows)

    report_paths = _write_report(args=args, rows=rows, outcomes=rewrite_outcomes, sheet_result=sheet_result)
    print(
        json.dumps(
            {
                "status": "ok",
                "report_paths": report_paths,
                "row_count": len(rows),
                "rewrite_outcomes": len(rewrite_outcomes),
                "sheet_status": sheet_result.get("status"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
