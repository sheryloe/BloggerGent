from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx


def _repo_root() -> Path:
    configured = os.environ.get("BLOGGENT_REPO_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    cursor = Path(__file__).resolve().parent
    for candidate in [cursor, *cursor.parents]:
        if (candidate / "apps" / "api").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_DIR = REPO_ROOT / "refactoring" / "reports"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(LOCAL_STORAGE_ROOT)

sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session, selectinload  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, PostStatus, SyncedBloggerPost  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.content.article_service import estimate_reading_time, sanitize_blog_html  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.platform.publishing_service import (  # noqa: E402
    build_ctr_permalink_title,
    rebuild_article_html,
    sanitize_blogger_labels_for_article,
    upsert_article_blogger_post,
)
from app.services.providers.factory import get_blogger_provider  # noqa: E402


MOJIBAKE_HINTS: tuple[str, ...] = ("�", "占", "筌")
IN_WORD_QUESTION_RE = re.compile(r"[A-Za-zÀ-ÿ]\?[A-Za-zÀ-ÿ]")
MULTI_QUESTION_RE = re.compile(r"\?{2,}")
LATIN_IN_WORD_QUESTION_RE = re.compile(r"([A-Za-zÀ-ÿ])\?([A-Za-zÀ-ÿ])")
CJK_IN_WORD_QUESTION_RE = re.compile(r"([\u3040-\u30ff\u4e00-\u9fff])\?([\u3040-\u30ff\u4e00-\u9fff])")
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
ALLOWED_TAGS = "h2, h3, p, ul, li, strong, br"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair mojibake-like text in travel Blogger posts (es/ja), republish, and resync.",
    )
    parser.add_argument("--blog-id", type=int, action="append", help="Target blog id (repeatable). Default: 36,37")
    parser.add_argument("--article-id", type=int, action="append", help="Target article id (repeatable).")
    parser.add_argument("--max-items", type=int, default=0, help="Max candidate count to process. 0 means unlimited.")
    parser.add_argument("--execute", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--sync-blogger", action="store_true", help="Push repaired content to Blogger via update_post.")
    parser.add_argument(
        "--include-scheduled",
        action="store_true",
        help="Include scheduled posts in target set. Default includes published only.",
    )
    parser.add_argument("--model", default="", help="Override model for rewrite.")
    parser.add_argument("--report-prefix", default="travel-mojibake-repair", help="Report filename prefix.")
    return parser.parse_args()


def _normalize_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or ""
    if path.endswith("/") and path != "/":
        path = path[:-1]
    return f"{netloc}{path}"


def _plain_text(html: str | None) -> str:
    return WS_RE.sub(" ", TAG_RE.sub(" ", str(html or ""))).strip()


def _looks_corrupted(value: str | None, *, allow_many_questions: bool = False) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if any(token in raw for token in MOJIBAKE_HINTS):
        return True
    if (not allow_many_questions) and raw.count("?") >= 3:
        return True
    if MULTI_QUESTION_RE.search(raw):
        return True
    if IN_WORD_QUESTION_RE.search(raw):
        return True
    return False


def _first(text: str | None, *, fallback: str) -> str:
    raw = str(text or "").strip()
    return raw or fallback


def _heuristic_clean_text(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    for token in MOJIBAKE_HINTS:
        text = text.replace(token, " ")
    text = CJK_IN_WORD_QUESTION_RE.sub(r"\1・\2", text)
    text = LATIN_IN_WORD_QUESTION_RE.sub(r"\1-\2", text)
    text = MULTI_QUESTION_RE.sub(" ", text)
    text = re.sub(r"\s+\?\s+", " - ", text)
    text = re.sub(r"\?+", " ", text)
    text = WS_RE.sub(" ", text).strip()
    return text


def _heuristic_payload(article: Article) -> dict[str, Any]:
    title = _heuristic_clean_text(article.title)
    excerpt = _heuristic_clean_text(article.excerpt)
    meta_description = _heuristic_clean_text(article.meta_description)
    html_article = _heuristic_clean_text(article.html_article)
    faq_source = list(article.faq_section or [])
    cleaned_faq: list[dict[str, str]] = []
    for item in faq_source:
        question = _heuristic_clean_text(str((item or {}).get("question") or ""))
        answer = _heuristic_clean_text(str((item or {}).get("answer") or ""))
        if len(question) >= 5 and len(answer) >= 10:
            cleaned_faq.append({"question": question, "answer": answer})

    if int(article.blog_id or 0) == 37:
        title = build_ctr_permalink_title(article)
    title = _first(title, fallback=article.title)

    plain = _plain_text(html_article)
    if len(excerpt) < 40:
        excerpt = (plain[:180] if plain else _plain_text(article.html_article)[:180]).strip()
    if len(meta_description) < 50:
        base_meta = plain if plain else _plain_text(article.html_article)
        meta_description = base_meta[:160].strip()
    if len(meta_description) > 320:
        meta_description = meta_description[:320].rstrip()
    if len(cleaned_faq) < 2:
        cleaned_faq = list(article.faq_section or [])[:4]

    return {
        "title": title,
        "excerpt": excerpt,
        "meta_description": meta_description,
        "html_article": sanitize_blog_html(html_article),
        "faq_section": cleaned_faq,
    }


def _json_content_to_object(content: str) -> dict[str, Any]:
    content = str(content or "").strip()
    if not content:
        raise ValueError("empty model response")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise


def _language_prompt(blog: Blog) -> str:
    language = str(blog.primary_language or "").strip().lower()
    if language.startswith("es"):
        return (
            "Output language must be Spanish (natural travel-blog Spanish). "
            "Do not leave mojibake artifacts like ?, ??, ???, or replacement chars."
        )
    if language.startswith("ja"):
        return (
            "Output rules: title must be English CTR style; excerpt/meta/body/FAQ must be Japanese. "
            "Do not leave mojibake artifacts like ?, ??, ???, or replacement chars."
        )
    return "Output language must match the original article intent."


def _build_repair_prompt(article: Article) -> str:
    labels = ", ".join(str(x) for x in list(article.labels or []))
    faq_json = json.dumps(list(article.faq_section or []), ensure_ascii=False)
    old_body_plain = _plain_text(article.html_article)
    return f"""Repair mojibake and clarity issues in this published travel blog post. Return JSON only.

Output JSON schema:
{{
  "title": "string",
  "excerpt": "string",
  "meta_description": "string",
  "html_article": "string",
  "faq_section": [
    {{"question": "string", "answer": "string"}}
  ]
}}

Hard rules:
- Keep topic/entities/places/facts aligned with current article.
- Remove corrupted text artifacts (mojibake) and rewrite naturally.
- Keep post useful for real trip planning.
- HTML must use only: {ALLOWED_TAGS}.
- Do not include image tags, markdown fences, scripts, tables, iframes.
- Keep body depth similar to existing content (do not collapse into short summary).
- FAQ should be practical and concise.

Blog context:
- blog_id: {article.blog_id}
- blog_language: {article.blog.primary_language if article.blog else ""}
- {_language_prompt(article.blog) if article.blog else ""}

Current data:
- title: {article.title}
- excerpt: {article.excerpt}
- meta_description: {article.meta_description}
- labels: {labels}
- faq_section_json: {faq_json}
- body_plain_text:
{old_body_plain}
"""


def _load_runtime_config(db: Session, model_override: str) -> tuple[str, str]:
    settings = get_settings_map(db)
    api_key = str(settings.get("openai_api_key") or "").strip()
    model = (
        str(model_override or "").strip()
        or str(settings.get("article_generation_model") or "").strip()
        or str(settings.get("openai_text_model") or "").strip()
        or "gpt-5.4"
    )
    return api_key, model


def _rewrite_with_openai(*, api_key: str, model: str, article: Article) -> dict[str, Any]:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You repair corrupted multilingual travel blog posts. "
                        "Return valid JSON only. Preserve factual intent."
                    ),
                },
                {"role": "user", "content": _build_repair_prompt(article)},
            ],
        },
        timeout=300.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _json_content_to_object(content)


def _normalize_faq(raw_faq: Any) -> list[dict[str, str]]:
    items = list(raw_faq or [])
    normalized: list[dict[str, str]] = []
    for item in items[:6]:
        question = str((item or {}).get("question") or "").strip()
        answer = str((item or {}).get("answer") or "").strip()
        if len(question) < 5 or len(answer) < 10:
            continue
        normalized.append({"question": question, "answer": answer})
    return normalized


def _validated_payload(article: Article, raw_payload: dict[str, Any]) -> dict[str, Any]:
    title = str(raw_payload.get("title") or "").strip()
    excerpt = str(raw_payload.get("excerpt") or "").strip()
    meta_description = str(raw_payload.get("meta_description") or "").strip()
    html_article = sanitize_blog_html(str(raw_payload.get("html_article") or "").strip())
    faq_section = _normalize_faq(raw_payload.get("faq_section"))

    if int(article.blog_id or 0) == 37:
        title = build_ctr_permalink_title(article)
    title = _first(title, fallback=article.title)

    if _looks_corrupted(title):
        if int(article.blog_id or 0) == 37:
            title = build_ctr_permalink_title(article)
        else:
            raise ValueError("title remains corrupted after rewrite")
    if _looks_corrupted(excerpt):
        raise ValueError("excerpt remains corrupted after rewrite")
    if _looks_corrupted(meta_description):
        raise ValueError("meta_description remains corrupted after rewrite")
    if _looks_corrupted(_plain_text(html_article), allow_many_questions=True):
        raise ValueError("body remains corrupted after rewrite")

    if len(excerpt) < 40:
        raise ValueError("excerpt too short")
    if len(meta_description) < 50:
        raise ValueError("meta_description too short")
    if len(meta_description) > 320:
        meta_description = meta_description[:320].rstrip()
    old_len = len(_plain_text(article.html_article))
    new_len = len(_plain_text(html_article))
    minimum_len = max(450, int(old_len * 0.4))
    if new_len < minimum_len:
        raise ValueError("body too short")
    if len(faq_section) < 2:
        faq_section = list(article.faq_section or [])[:4]

    return {
        "title": title,
        "excerpt": excerpt,
        "meta_description": meta_description,
        "html_article": html_article,
        "faq_section": faq_section,
    }


def _apply_article_update(db: Session, article: Article, payload: dict[str, Any]) -> None:
    article.title = payload["title"]
    article.excerpt = payload["excerpt"]
    article.meta_description = payload["meta_description"]
    article.html_article = payload["html_article"]
    article.faq_section = payload["faq_section"]
    article.labels = sanitize_blogger_labels_for_article(article, list(article.labels or []))
    article.reading_time_minutes = estimate_reading_time(article.html_article)
    db.add(article)
    db.commit()
    db.refresh(article)


def _sync_post(db: Session, article: Article) -> str:
    if not article.blog or not article.blogger_post:
        return "skip:no-linked-post"
    provider = get_blogger_provider(db, article.blog)
    if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
        return "skip:mock-provider"
    summary, raw_payload = provider.update_post(
        post_id=article.blogger_post.blogger_post_id,
        title=article.title,
        content=article.assembled_html or article.html_article or "",
        labels=list(article.labels or []),
        meta_description=article.meta_description or "",
    )
    upsert_article_blogger_post(
        db,
        article=article,
        summary=summary,
        raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
    )
    return "updated"


def _load_candidates(
    db: Session,
    blog_ids: list[int],
    include_scheduled: bool,
    article_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    statuses = [PostStatus.PUBLISHED]
    if include_scheduled:
        statuses.append(PostStatus.SCHEDULED)

    stmt = (
        select(Article)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .join(Blog, Blog.id == Article.blog_id)
        .where(
            Blog.is_active.is_(True),
            Blog.id.in_(blog_ids),
            BloggerPost.post_status.in_(tuple(statuses)),
        )
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
        .order_by(Article.id.asc())
    )
    articles = db.execute(stmt).scalars().all()
    if article_ids:
        articles = [item for item in articles if int(item.id) in article_ids]

    sync_rows = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id.in_(blog_ids))).scalars().all()
    synced_by_key = {(int(row.blog_id), _normalize_url(row.url)): row for row in sync_rows}

    candidates: list[dict[str, Any]] = []
    for article in articles:
        article_flags: list[str] = []
        if _looks_corrupted(article.title):
            article_flags.append("article.title")
        if _looks_corrupted(article.excerpt):
            article_flags.append("article.excerpt")
        if _looks_corrupted(article.meta_description):
            article_flags.append("article.meta_description")
        if _looks_corrupted(_plain_text(article.html_article), allow_many_questions=True):
            article_flags.append("article.html_article")
        if any(_looks_corrupted(str(label)) for label in list(article.labels or [])):
            article_flags.append("article.labels")

        sync_flags: list[str] = []
        synced = None
        published_url = _normalize_url(article.blogger_post.published_url if article.blogger_post else "")
        if published_url:
            synced = synced_by_key.get((int(article.blog_id), published_url))
        if synced:
            if _looks_corrupted(synced.title):
                sync_flags.append("synced.title")
            if _looks_corrupted(synced.excerpt_text):
                sync_flags.append("synced.excerpt_text")
            if _looks_corrupted(_plain_text(synced.content_html), allow_many_questions=True):
                sync_flags.append("synced.content_html")
            if any(_looks_corrupted(str(label)) for label in list(synced.labels or [])):
                sync_flags.append("synced.labels")

        if not article_flags and not sync_flags:
            continue
        candidates.append(
            {
                "article_id": int(article.id),
                "blog_id": int(article.blog_id),
                "url": article.blogger_post.published_url if article.blogger_post else "",
                "article_flags": article_flags,
                "synced_flags": sync_flags,
            }
        )
    return candidates


def _write_report(prefix: str, payload: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_DIR / f"{prefix}-{stamp}.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _sync_live_snapshot(db: Session, blog_ids: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for blog_id in blog_ids:
        blog = db.get(Blog, blog_id)
        if not blog or not blog.is_active:
            continue
        if not str(blog.blogger_blog_id or "").strip():
            continue
        result = sync_blogger_posts_for_blog(db, blog)
        count_value = 0
        synced_at_value: str | None = None
        source_value = ""
        if isinstance(result, dict):
            count_value = int(result.get("count") or 0)
            raw_synced_at = result.get("last_synced_at")
            synced_at_value = raw_synced_at.isoformat() if hasattr(raw_synced_at, "isoformat") else str(raw_synced_at or "")
            source_value = str(result.get("source") or "")
        else:
            count_value = int(getattr(result, "count", 0) or 0)
            raw_synced_at = getattr(result, "last_synced_at", None)
            synced_at_value = raw_synced_at.isoformat() if hasattr(raw_synced_at, "isoformat") else None
            source_value = str(getattr(result, "source", "") or "")
        rows.append(
            {
                "blog_id": blog_id,
                "count": count_value,
                "last_synced_at": synced_at_value or None,
                "source": source_value,
            }
        )
    return rows


def main() -> int:
    args = parse_args()
    blog_ids = list(dict.fromkeys(args.blog_id or [36, 37]))
    article_ids = {int(x) for x in list(args.article_id or []) if int(x) > 0}
    if not blog_ids:
        raise ValueError("No blog ids specified.")

    summary: dict[str, Any] = {
        "execute": bool(args.execute),
        "sync_blogger": bool(args.sync_blogger),
        "blog_ids": blog_ids,
        "include_scheduled": bool(args.include_scheduled),
        "article_ids": sorted(article_ids),
        "max_items": int(args.max_items or 0),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "pre_sync": [],
        "post_sync": [],
        "candidate_count": 0,
        "processed_count": 0,
        "repaired_count": 0,
        "failed_count": 0,
        "items": [],
    }

    with SessionLocal() as db:
        summary["pre_sync"] = _sync_live_snapshot(db, blog_ids)
        api_key, model = _load_runtime_config(db, args.model)
        if args.execute and not api_key:
            raise RuntimeError("openai_api_key setting is missing.")
        summary["model"] = model

    with SessionLocal() as db:
        candidates = _load_candidates(
            db,
            blog_ids,
            include_scheduled=bool(args.include_scheduled),
            article_ids=article_ids or None,
        )
    if args.max_items and args.max_items > 0:
        candidates = candidates[: args.max_items]
    summary["candidate_count"] = len(candidates)

    if not args.execute:
        summary["items"] = candidates
        with SessionLocal() as db:
            summary["post_sync"] = _sync_live_snapshot(db, blog_ids)
        report_path = _write_report(args.report_prefix, summary)
        print(json.dumps({"status": "dry-run", "candidate_count": len(candidates), "report": str(report_path)}, ensure_ascii=False))
        return 0

    with SessionLocal() as db:
        api_key, model = _load_runtime_config(db, args.model)

    for idx, item in enumerate(candidates, start=1):
        row: dict[str, Any] = {
            "index": idx,
            "article_id": item["article_id"],
            "blog_id": item["blog_id"],
            "url": item.get("url", ""),
            "article_flags": item.get("article_flags", []),
            "synced_flags": item.get("synced_flags", []),
            "status": "pending",
        }
        print(
            f"[{idx}/{len(candidates)}] repairing article={item['article_id']} blog={item['blog_id']} "
            f"flags={len(row['article_flags']) + len(row['synced_flags'])}",
        )
        summary["processed_count"] += 1

        try:
            with SessionLocal() as db:
                article = db.execute(
                    select(Article)
                    .where(Article.id == int(item["article_id"]))
                    .options(
                        selectinload(Article.blog),
                        selectinload(Article.image),
                        selectinload(Article.blogger_post),
                    )
                ).scalar_one_or_none()
                if not article:
                    raise ValueError("article_not_found")

                payload = None
                last_error: Exception | None = None
                for _attempt in range(2):
                    try:
                        raw = _rewrite_with_openai(api_key=api_key, model=model, article=article)
                        payload = _validated_payload(article, raw)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        time.sleep(1.5)
                if payload is None:
                    fallback_payload = _heuristic_payload(article)
                    payload = _validated_payload(article, fallback_payload)
                    row["repair_mode"] = f"heuristic_fallback({last_error})"
                else:
                    row["repair_mode"] = "openai"

                _apply_article_update(db, article, payload)
                hero_image_url = article.image.public_url if article.image else ""
                rebuild_article_html(db, article, hero_image_url)
                db.refresh(article)

                sync_status = "skipped"
                if args.sync_blogger:
                    sync_status = _sync_post(db, article)
                row["status"] = "repaired"
                row["new_title"] = article.title
                row["reading_time_minutes"] = int(article.reading_time_minutes or 0)
                row["sync_status"] = sync_status
                summary["repaired_count"] += 1
        except Exception as exc:  # noqa: BLE001
            row["status"] = "failed"
            row["error"] = str(exc)
            summary["failed_count"] += 1
            print(f"  error: {exc}")

        summary["items"].append(row)

    with SessionLocal() as db:
        summary["post_sync"] = _sync_live_snapshot(db, blog_ids)
    summary["completed_at"] = datetime.now().isoformat(timespec="seconds")

    report_path = _write_report(args.report_prefix, summary)
    print(
        json.dumps(
            {
                "status": "done",
                "candidate_count": summary["candidate_count"],
                "processed_count": summary["processed_count"],
                "repaired_count": summary["repaired_count"],
                "failed_count": summary["failed_count"],
                "report": str(report_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
