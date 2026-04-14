from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


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

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, PostStatus  # noqa: E402
from app.services.content.article_service import estimate_reading_time, sanitize_blog_html  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402
from app.services.platform.publishing_service import rebuild_article_html, upsert_article_blogger_post  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402


TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
ALLOWED_TAGS = "h2, h3, p, ul, li, strong, br"


def plain_text(value: str | None) -> str:
    text = TAG_RE.sub(" ", value or "")
    return WHITESPACE_RE.sub(" ", text).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rewrite published Blogger articles for clearer copy and stronger structure.")
    parser.add_argument("--profile-key", choices=("korea_travel", "world_mystery"), help="Target blog profile key")
    parser.add_argument("--limit", type=int, default=200, help="Maximum number of published articles to inspect")
    parser.add_argument("--offset", type=int, default=0, help="Number of rows to skip before processing")
    parser.add_argument("--sync-blogger", action="store_true", help="Update the live Blogger post after rebuilding HTML")
    parser.add_argument("--report-prefix", default="blog-copy-refresh", help="Prefix for generated report files")
    return parser.parse_args()


def load_article_summaries(args: argparse.Namespace) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        stmt = (
            select(
                Article.id,
                Article.slug,
                Article.title,
                Blog.profile_key,
                BloggerPost.published_url,
            )
            .join(Blog, Blog.id == Article.blog_id)
            .join(BloggerPost, BloggerPost.article_id == Article.id)
            .where(Blog.is_active.is_(True), BloggerPost.post_status == PostStatus.PUBLISHED)
            .order_by(Article.created_at.desc())
            .offset(max(0, int(args.offset)))
            .limit(max(1, int(args.limit)))
        )
        if args.profile_key:
            stmt = stmt.where(Blog.profile_key == args.profile_key)
        rows = db.execute(stmt).all()
        return [
            {
                "article_id": row[0],
                "slug": row[1],
                "title": row[2],
                "profile_key": row[3],
                "published_url": row[4],
            }
            for row in rows
        ]


def load_article(db, article_id: int) -> Article | None:
    stmt = (
        select(Article)
        .where(Article.id == article_id)
        .options(
            selectinload(Article.blog),
            selectinload(Article.topic),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
    )
    return db.execute(stmt).scalar_one_or_none()


def get_runtime_config(db) -> tuple[str, str]:
    settings = get_settings_map(db)
    api_key = str(settings.get("openai_api_key") or "").strip()
    model = (
        str(settings.get("article_generation_model") or "").strip()
        or str(settings.get("openai_large_text_model") or "").strip()
        or str(settings.get("openai_text_model") or "").strip()
        or "gpt-5.4"
    )
    return api_key, model


def profile_guidance(article: Article) -> str:
    if article.blog and article.blog.profile_key == "world_mystery":
        return (
            "This is a documentary-style mystery post. Keep the factual spine, separate confirmed facts from interpretation, "
            "and keep a sober narrative voice. Do not turn it into fiction, hype, or a listicle."
        )
    return (
        "This is a Korea travel post for international readers. Keep the real-place planning value high, improve flow and readability, "
        "and avoid generic tourism filler. If the post is already blossom-season themed, keep the local, neighborhood-scale angle sharp."
    )


def build_revision_prompt(article: Article) -> str:
    old_body = plain_text(article.html_article)
    old_faq = json.dumps(article.faq_section or [], ensure_ascii=False)
    labels = ", ".join(article.labels or [])
    cluster = article.topic.topic_cluster_label if article.topic else ""
    angle = article.topic.topic_angle_label if article.topic else ""
    return f"""Revise this published article copy and return JSON only.

Output JSON schema:
{{
  "excerpt": "string",
  "meta_description": "string",
  "html_article": "string",
  "faq_section": [
    {{"question": "string", "answer": "string"}}
  ]
}}

Rules:
- Keep the article title exactly unchanged.
- Keep the same topic, same named entities, same case/place, and same overall promise.
- Improve clarity, sentence flow, specificity, and readability.
- Remove repetitive SEO filler and duplicated phrasing.
- Do not mention AI generation, collages, captions, or image instructions in the body.
- Do not add unsupported facts, dates, ticket prices, addresses, statistics, or claims not grounded in the provided source copy.
- Keep the structure scannable but not robotic.
- Use only these HTML tags in html_article: {ALLOWED_TAGS}.
- Do not include img, figure, table, iframe, or markdown fences.
- Keep or improve the current body depth. Do not collapse the article into a short summary.
- FAQ answers should be concise and directly helpful.

Profile guidance:
- {profile_guidance(article)}

Article data:
- Title: {article.title}
- Profile: {article.blog.profile_key if article.blog else ""}
- Labels: {labels}
- Cluster: {cluster}
- Angle: {angle}
- Current meta description: {article.meta_description}
- Current excerpt: {article.excerpt}
- Current FAQ JSON: {old_faq}
- Current body text:
{old_body}
"""


def validate_revision_payload(article: Article, payload: dict[str, Any]) -> dict[str, Any]:
    excerpt = str(payload.get("excerpt") or "").strip()
    meta_description = str(payload.get("meta_description") or "").strip()
    html_article = sanitize_blog_html(str(payload.get("html_article") or "").strip())
    faq_section = payload.get("faq_section") or []

    if len(excerpt) < 40:
        raise ValueError("Excerpt too short")
    if len(meta_description) < 50 or len(meta_description) > 320:
        raise ValueError("Meta description length is invalid")
    if not isinstance(faq_section, list) or len(faq_section) < 2:
        raise ValueError("FAQ section is missing")

    normalized_faq: list[dict[str, str]] = []
    for item in faq_section[:6]:
        question = str((item or {}).get("question") or "").strip()
        answer = str((item or {}).get("answer") or "").strip()
        if len(question) < 5 or len(answer) < 10:
            continue
        normalized_faq.append({"question": question, "answer": answer})
    if len(normalized_faq) < 2:
        raise ValueError("FAQ section did not contain enough valid items")

    old_plain = plain_text(article.html_article)
    new_plain = plain_text(html_article)
    minimum_length = max(2500, int(len(old_plain) * 0.8))
    if len(new_plain) < minimum_length:
        raise ValueError(f"Rewritten body too short ({len(new_plain)} < {minimum_length})")

    return {
        "excerpt": excerpt,
        "meta_description": meta_description,
        "html_article": html_article,
        "faq_section": normalized_faq,
        "plain_text_length": len(new_plain),
    }


def rewrite_article_copy(api_key: str, model: str, article: Article) -> dict[str, Any]:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.6,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You revise published blog posts. Return valid JSON only. "
                        "Keep facts stable and improve readability without changing the title."
                    ),
                },
                {"role": "user", "content": build_revision_prompt(article)},
            ],
        },
        timeout=300.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def sync_blogger_post(db, article: Article) -> str:
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


def rebuild_article(db, article: Article, *, sync_blog: bool) -> str:
    hero_image_url = article.image.public_url if article.image else ""
    rebuild_article_html(db, article, hero_image_url)
    db.refresh(article)
    if not sync_blog:
        return "rebuilt"
    return f"rebuilt+{sync_blogger_post(db, article)}"


def apply_revision(db, article: Article, payload: dict[str, Any], *, sync_blog: bool) -> dict[str, Any]:
    validated = validate_revision_payload(article, payload)
    article.excerpt = validated["excerpt"]
    article.meta_description = validated["meta_description"]
    article.html_article = validated["html_article"]
    article.faq_section = validated["faq_section"]
    article.reading_time_minutes = estimate_reading_time(validated["html_article"])
    db.add(article)
    db.commit()
    db.refresh(article)
    rebuild_status = rebuild_article(db, article, sync_blog=sync_blog)
    return {
        "plain_text_length": validated["plain_text_length"],
        "reading_time_minutes": article.reading_time_minutes,
        "rebuild_status": rebuild_status,
    }


def write_report(prefix: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"{prefix}-{stamp}.json"
    md_path = REPORT_DIR / f"{prefix}-{stamp}.md"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# {prefix}",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- total_rows: {len(rows)}",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"## {index}. {row['title']}",
                f"- profile: {row['profile_key']}",
                f"- url: {row['published_url']}",
                f"- status: {row['status']}",
                f"- plain_text_length: {row.get('plain_text_length', '')}",
                f"- reading_time_minutes: {row.get('reading_time_minutes', '')}",
                f"- actions: {', '.join(row.get('actions', []))}",
            ]
        )
        if row.get("error"):
            lines.append(f"- error: {row['error']}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    args = parse_args()
    summaries = load_article_summaries(args)
    rows: list[dict[str, Any]] = []

    if not summaries:
        print("No published articles matched the requested filters.")
        return 0

    with SessionLocal() as db:
        api_key, model = get_runtime_config(db)
        if not api_key:
            raise RuntimeError("OpenAI API key is missing in settings.")

    for index, summary in enumerate(summaries, start=1):
        row: dict[str, Any] = {
            "article_id": summary["article_id"],
            "title": summary["title"],
            "profile_key": summary["profile_key"],
            "published_url": summary["published_url"],
            "status": "pending",
            "actions": [],
        }
        print(f"[{index}/{len(summaries)}] rewriting article {summary['article_id']} :: {summary['title']}")
        try:
            with SessionLocal() as db:
                article = load_article(db, summary["article_id"])
                if not article:
                    raise ValueError("Article not found")
                payload = rewrite_article_copy(api_key, model, article)
                result = apply_revision(db, article, payload, sync_blog=bool(args.sync_blogger))
                row["status"] = "ok"
                row["plain_text_length"] = result["plain_text_length"]
                row["reading_time_minutes"] = result["reading_time_minutes"]
                row["actions"] = ["rewritten", result["rebuild_status"]]
        except Exception as exc:  # noqa: BLE001
            row["status"] = "error"
            row["error"] = str(exc)
            print(f"  error: {exc}")
        rows.append(row)

    report_paths = write_report(args.report_prefix, rows)
    print(json.dumps({"report_paths": report_paths, "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
