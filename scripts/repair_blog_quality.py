from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
CONTAINER_STORAGE_ROOT = PurePosixPath("/app/storage")
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
from app.models.entities import Article, Blog, BloggerPost, Image, PostStatus, WorkflowStageType  # noqa: E402
from app.services.blog_service import sync_stage_prompts_from_profile_files  # noqa: E402
from app.services.providers.factory import get_article_provider, get_blogger_provider, get_image_provider  # noqa: E402
from app.services.publishing_service import rebuild_article_html, upsert_article_blogger_post  # noqa: E402
from app.services.settings_service import get_settings_map  # noqa: E402
from app.services.storage_service import save_public_binary  # noqa: E402

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
VISION_MODEL = "gpt-4.1-mini"
TRAVEL_IMAGE_MODEL = "gpt-image-1"
MYSTERY_IMAGE_MODEL = "gpt-image-1"
TEXT_MODEL_FALLBACK = "gpt-4.1-2025-04-14"
MYSTERY_INLINE_MARKERS = (
    "4-panel investigation collage",
    "AI-generated editorial collage",
)


def plain_text(value: str | None) -> str:
    text = TAG_RE.sub(" ", value or "")
    return WHITESPACE_RE.sub(" ", text).strip()


def to_local_storage_path(file_path: str | None) -> str:
    normalized = (file_path or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("/app/storage/"):
        relative = PurePosixPath(normalized).relative_to(CONTAINER_STORAGE_ROOT)
        return str(LOCAL_STORAGE_ROOT / Path(relative.as_posix()))
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair related links and hero images for published Blogger articles.")
    parser.add_argument("--profile-key", choices=("korea_travel", "world_mystery"), help="Target blog profile key")
    parser.add_argument("--limit", type=int, default=200, help="Maximum number of published articles to inspect")
    parser.add_argument("--offset", type=int, default=0, help="Number of rows to skip before processing")
    parser.add_argument(
        "--article-ids",
        default="",
        help="Comma-separated article ids to process (for example: 139,138,137).",
    )
    parser.add_argument("--sync-blogger", action="store_true", help="Update the live Blogger post after rebuild")
    parser.add_argument("--rebuild-related", action="store_true", help="Rebuild HTML so related links are refreshed")
    parser.add_argument(
        "--force-travel-hero-refresh",
        action="store_true",
        help="Regenerate travel hero images even if the current image is not explicitly flagged",
    )
    parser.add_argument(
        "--force-travel-3x3panel",
        action="store_true",
        help="Regenerate travel hero images as strict 3x3 panel collage with center-panel emphasis.",
    )
    parser.add_argument(
        "--sync-travel-workflow-prompts",
        action="store_true",
        help="Sync active travel blog workflow prompts (article_generation/image_prompt_generation) from prompt files before repair.",
    )
    parser.add_argument(
        "--regen-vision-bad",
        action="store_true",
        help="Use OpenAI vision to audit current hero images and regenerate only the bad ones",
    )
    parser.add_argument(
        "--report-prefix",
        default="blog-quality-repair",
        help="Prefix for generated report files",
    )
    return parser.parse_args()


def parse_article_ids(raw: str) -> list[int]:
    values: list[int] = []
    for token in (raw or "").split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            parsed = int(candidate)
        except ValueError:
            continue
        if parsed > 0:
            values.append(parsed)
    return sorted(set(values), reverse=True)


def sync_active_travel_workflow_prompts(db) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    blogs = (
        db.execute(select(Blog).where(Blog.profile_key == "korea_travel", Blog.is_active.is_(True)))
        .scalars()
        .all()
    )
    for blog in blogs:
        updates = sync_stage_prompts_from_profile_files(
            db,
            blog=blog,
            stage_types=(
                WorkflowStageType.ARTICLE_GENERATION,
                WorkflowStageType.IMAGE_PROMPT_GENERATION,
            ),
        )
        rows.append({"blog_id": blog.id, "blog_name": blog.name, "updated_count": len(updates), "updates": updates})
    return rows


def load_article_summaries(args: argparse.Namespace) -> list[dict[str, Any]]:
    selected_ids = parse_article_ids(args.article_ids)
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
            .where(Blog.is_active.is_(True), BloggerPost.post_status.in_([PostStatus.PUBLISHED, PostStatus.SCHEDULED]))
            .order_by(Article.created_at.desc())
            .offset(max(0, int(args.offset)))
            .limit(max(1, int(args.limit)))
        )
        if args.profile_key:
            stmt = stmt.where(Blog.profile_key == args.profile_key)
        if selected_ids:
            stmt = stmt.where(Article.id.in_(selected_ids))
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


def get_openai_api_key(db) -> str:
    settings = get_settings_map(db)
    return str(settings.get("openai_api_key") or "").strip()


def get_text_model(db) -> str:
    settings = get_settings_map(db)
    return (
        str(settings.get("article_generation_model") or "").strip()
        or str(settings.get("openai_text_model") or "").strip()
        or TEXT_MODEL_FALLBACK
    )


def image_data_url(article: Article) -> str:
    if not article.image:
        return ""
    file_path = Path(to_local_storage_path(article.image.file_path))
    if not file_path.exists():
        return ""
    mime = "image/png"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def audit_image_match(api_key: str, article: Article) -> dict[str, Any]:
    if not api_key:
        return {"status": "skipped", "reason": "OpenAI API key is missing.", "replacement_prompt": ""}
    data_url = image_data_url(article)
    if not data_url:
        return {"status": "missing", "reason": "Local image file is missing.", "replacement_prompt": ""}

    body = plain_text(article.html_article)[:1400]
    cluster = article.topic.topic_cluster_label if article.topic else ""
    angle = article.topic.topic_angle_label if article.topic else ""
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": VISION_MODEL,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You evaluate whether a hero image matches a blog article. "
                        "Return JSON with keys status, reason, replacement_prompt. "
                        "status must be one of good, borderline, bad, missing."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Profile: {article.blog.profile_key if article.blog else ''}\n"
                                f"Title: {article.title}\n"
                                f"Excerpt: {article.excerpt}\n"
                                f"Cluster: {cluster}\n"
                                f"Angle: {angle}\n"
                                f"Current prompt: {article.image_collage_prompt}\n"
                                f"Body: {body}\n\n"
                                "Judge whether the image strongly fits the article's main promise. "
                                "If bad, write a replacement_prompt for one single realistic hero image with no collage, no grid, no text overlay."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                },
            ],
        },
        timeout=120.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    payload = json.loads(content)
    return {
        "status": str(payload.get("status") or "borderline").strip().lower(),
        "reason": str(payload.get("reason") or "").strip(),
        "replacement_prompt": str(payload.get("replacement_prompt") or "").strip(),
    }


def build_replacement_prompt(db, article: Article) -> str:
    provider = get_article_provider(db, model_override=get_text_model(db))
    body = plain_text(article.html_article)[:2200]
    cluster = article.topic.topic_cluster_label if article.topic else ""
    angle = article.topic.topic_angle_label if article.topic else ""
    if article.blog and article.blog.profile_key == "korea_travel":
        prompt = f"""Create one final English prompt for one composite 3x3 Korea travel collage hero image.

Title: {article.title}
Excerpt: {article.excerpt}
Cluster: {cluster}
Angle: {angle}
Labels: {', '.join(article.labels or [])}
Body context: {body}
Current image prompt: {article.image_collage_prompt}

Rules:
- Return plain text only.
- The result must be exactly 9 distinct rectangular panels in a 3x3 grid collage.
- The center panel must be visually dominant and noticeably larger than each surrounding panel.
- Use visible clean white gutters between panels.
- Never output one single blended panorama, one continuous frame, or poster text.
- The collage must match the article's exact place, route, district, or local event promise immediately.
- If the article is about cherry blossoms, include specific neighborhood/event logic from the article, not generic blossom scenery.
- Use realistic editorial travel photography across all panels with clear location identity.
- No text overlays, no logos, no memo desk imagery.
"""
    else:
        prompt = f"""Create one final English prompt for a single documentary-style mystery hero image.

Title: {article.title}
Excerpt: {article.excerpt}
Cluster: {cluster}
Angle: {angle}
Labels: {', '.join(article.labels or [])}
Body context: {body}
Current image prompt: {article.image_collage_prompt}

Rules:
- Return plain text only.
- The result must be one single realistic documentary hero image.
- Never use collage, panel, grid, split screen, poster text, or logo.
- The image must match the article's main evidence path, location, document trail, or investigative mood.
- Keep it historically grounded and non-sensational.
- No gore, no fantasy styling, no horror poster look.
- Prefer one strong scene with place, artifact, or investigative atmosphere that fits the article immediately.
"""
    rendered_prompt, _ = provider.generate_visual_prompt(prompt)
    return rendered_prompt.strip()


def cleanup_mystery_inline_markers(article: Article) -> bool:
    if not article.blog or article.blog.profile_key != "world_mystery":
        return False
    original = article.html_article or ""
    cleaned = original
    for marker in MYSTERY_INLINE_MARKERS:
        cleaned = re.sub(rf"<p>\s*{re.escape(marker)}\s*</p>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(re.escape(marker), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<figure\b[^>]*>.*?</figure>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    if cleaned == original:
        return False
    article.html_article = cleaned
    return True


def attach_generated_image(db, article: Article, prompt: str, model_name: str) -> dict[str, Any]:
    image_provider = get_image_provider(db, model_override=model_name)
    image_bytes, image_raw = image_provider.generate_image(prompt, article.slug)
    file_path, public_url, delivery_meta = save_public_binary(
        db,
        subdir="images",
        filename=f"{article.slug}.webp",
        content=image_bytes,
        provider_override="cloudflare_r2",
    )

    image = article.image
    if image is None:
        image = Image(job_id=article.job_id, article_id=article.id, prompt=prompt, file_path=file_path, public_url=public_url)
        db.add(image)
        db.flush()

    image.article_id = article.id
    image.prompt = prompt
    image.file_path = file_path
    image.public_url = public_url
    image.width = int(image_raw.get("width", 1536))
    image.height = int(image_raw.get("height", 1024))
    image.provider = str(image_raw.get("actual_model") or image_raw.get("requested_model") or model_name)
    image.image_metadata = {**image_raw, "delivery": delivery_meta}
    article.image_collage_prompt = prompt
    db.add(image)
    db.add(article)
    db.commit()
    db.refresh(article)
    return {
        "public_url": public_url,
        "provider": image.provider,
        "prompt": prompt,
        "width": image.width,
        "height": image.height,
    }


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


def write_report(prefix: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"{prefix}-{timestamp}.json"
    md_path = REPORT_DIR / f"{prefix}-{timestamp}.md"
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
                f"- actions: {', '.join(row['actions']) if row['actions'] else 'none'}",
                f"- old_image_url: {row.get('old_image_url') or ''}",
                f"- new_image_url: {row.get('new_image_url') or ''}",
                f"- old_size: {row.get('old_width', 0)}x{row.get('old_height', 0)}",
                f"- new_size: {row.get('new_width', '')}x{row.get('new_height', '')}" if row.get("new_width") else "- new_size: ",
                f"- audit_status: {row.get('audit_status') or 'n/a'}",
                f"- audit_reason: {row.get('audit_reason') or ''}",
                f"- prompt_changed: {'yes' if row.get('new_prompt') else 'no'}",
                "",
            ]
        )
    md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main() -> int:
    args = parse_args()
    sync_result: list[dict[str, Any]] = []
    if args.sync_travel_workflow_prompts:
        with SessionLocal() as db:
            sync_result = sync_active_travel_workflow_prompts(db)
        print(json.dumps({"workflow_prompt_sync": sync_result}, ensure_ascii=True))

    summaries = load_article_summaries(args)
    if not summaries:
        print("No published articles matched the request.")
        return 0

    results: list[dict[str, Any]] = []
    for summary in summaries:
        try:
            with SessionLocal() as db:
                article = load_article(db, int(summary["article_id"]))
                if article is None or article.blog is None:
                    continue

                result = {
                    "article_id": article.id,
                    "title": article.title,
                    "slug": article.slug,
                    "profile_key": article.blog.profile_key,
                    "published_url": article.blogger_post.published_url if article.blogger_post else None,
                    "actions": [],
                    "old_prompt": article.image_collage_prompt,
                    "old_image_url": article.image.public_url if article.image else "",
                    "old_width": int(article.image.width or 0) if article.image else 0,
                    "old_height": int(article.image.height or 0) if article.image else 0,
                }

                audit_payload: dict[str, Any] | None = None
                should_regenerate = False
                replacement_prompt = ""

                if args.regen_vision_bad:
                    audit_payload = audit_image_match(get_openai_api_key(db), article)
                    result["audit_status"] = audit_payload.get("status")
                    result["audit_reason"] = audit_payload.get("reason")
                    if audit_payload.get("status") == "bad":
                        should_regenerate = True
                        replacement_prompt = str(audit_payload.get("replacement_prompt") or "").strip()
                    elif audit_payload.get("status") == "missing":
                        should_regenerate = True

                if args.force_travel_hero_refresh and article.blog.profile_key == "korea_travel":
                    should_regenerate = True

                if args.force_travel_3x3panel and article.blog.profile_key == "korea_travel":
                    should_regenerate = True

                mystery_cleaned = cleanup_mystery_inline_markers(article)
                if mystery_cleaned:
                    db.add(article)
                    db.commit()
                    db.refresh(article)
                    result["actions"].append("cleaned_mystery_inline_markers")

                if should_regenerate:
                    if args.force_travel_3x3panel and article.blog.profile_key == "korea_travel":
                        prompt = build_replacement_prompt(db, article)
                    else:
                        prompt = replacement_prompt or build_replacement_prompt(db, article)
                    model_name = TRAVEL_IMAGE_MODEL if article.blog.profile_key == "korea_travel" else MYSTERY_IMAGE_MODEL
                    image_result = attach_generated_image(db, article, prompt, model_name)
                    result["actions"].append("regenerated_image")
                    result["new_prompt"] = prompt
                    result["new_image_url"] = image_result["public_url"]
                    result["new_width"] = int(image_result["width"])
                    result["new_height"] = int(image_result["height"])

                if args.rebuild_related or should_regenerate or mystery_cleaned:
                    rebuild_status = rebuild_article(db, article, sync_blog=args.sync_blogger)
                    result["actions"].append(rebuild_status)

                results.append(result)
                print(json.dumps({"article_id": article.id, "title": article.title, "actions": result["actions"]}, ensure_ascii=True))
        except Exception as exc:  # noqa: BLE001
            failed_result = {
                "article_id": summary["article_id"],
                "title": summary["title"],
                "slug": summary["slug"],
                "profile_key": summary["profile_key"],
                "published_url": summary["published_url"],
                "actions": ["failed"],
                "error": str(exc),
            }
            results.append(failed_result)
            print(json.dumps(failed_result, ensure_ascii=True))

    report_paths = write_report(args.report_prefix, results)
    print(json.dumps({"processed": len(results), "workflow_prompt_sync": sync_result, **report_paths}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
