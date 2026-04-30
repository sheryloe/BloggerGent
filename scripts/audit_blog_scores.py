from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
REPORT_DIR = REPO_ROOT / "storage" / "reports"
SEO_THRESHOLD = 70
GEO_THRESHOLD = 60
CTR_PRIORITY_THRESHOLD = 60


def _load_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


_load_runtime_env()

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str((REPO_ROOT / "storage").resolve())

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, PostStatus  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
    _list_integration_posts,
)
from app.services.content.content_ops_service import compute_seo_geo_scores  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit SEO/GEO/CTR scores for all blogs.")
    parser.add_argument("--provider", choices=("all", "blogger", "cloudflare"), default="all")
    parser.add_argument("--seo-threshold", type=int, default=SEO_THRESHOLD)
    parser.add_argument("--geo-threshold", type=int, default=GEO_THRESHOLD)
    parser.add_argument("--report-prefix", default="blog-score-audit")
    return parser.parse_args()


def _priority(*, seo_score: int, geo_score: int, ctr_score: int, seo_threshold: int, geo_threshold: int) -> str:
    seo_gap = max(seo_threshold - seo_score, 0)
    geo_gap = max(geo_threshold - geo_score, 0)
    ctr_gap = max(CTR_PRIORITY_THRESHOLD - ctr_score, 0)
    worst_gap = max(seo_gap, geo_gap, ctr_gap)
    if worst_gap == 0:
        return "pass"
    if worst_gap >= 15:
        return "high"
    return "medium"


def _score_payload(*, title: str, html_body: str, excerpt: str | None, faq_section: list[dict[str, Any]] | None) -> dict[str, Any]:
    return compute_seo_geo_scores(
        title=title,
        html_body=html_body,
        excerpt=excerpt,
        faq_section=faq_section or [],
    )


def _build_blogger_rows(db, *, seo_threshold: int, geo_threshold: int) -> list[dict[str, Any]]:
    stmt = (
        select(Article)
        .join(Blog, Blog.id == Article.blog_id)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(
            Blog.is_active.is_(True),
            Blog.profile_key.in_(("korea_travel", "world_mystery")),
            BloggerPost.post_status.in_((PostStatus.PUBLISHED, PostStatus.SCHEDULED)),
        )
        .options(
            selectinload(Article.blog),
            selectinload(Article.blogger_post),
        )
        .order_by(BloggerPost.created_at.desc(), Article.id.desc())
    )
    rows: list[dict[str, Any]] = []
    for article in db.execute(stmt).scalars().all():
        score_payload = _score_payload(
            title=article.title,
            html_body=article.assembled_html or article.html_article or "",
            excerpt=article.excerpt,
            faq_section=article.faq_section if isinstance(article.faq_section, list) else [],
        )
        seo_score = int(score_payload.get("seo_score") or 0)
        geo_score = int(score_payload.get("geo_score") or 0)
        ctr_score = int(score_payload.get("ctr_score") or 0)
        threshold_pass = seo_score >= seo_threshold and geo_score >= geo_threshold
        rows.append(
            {
                "provider": "blogger",
                "channel": article.blog.profile_key if article.blog else "",
                "slug": article.slug,
                "title": article.title,
                "post_url": article.blogger_post.published_url if article.blogger_post else "",
                "seo_score": seo_score,
                "geo_score": geo_score,
                "ctr_score": ctr_score,
                "threshold_pass": threshold_pass,
                "priority": _priority(
                    seo_score=seo_score,
                    geo_score=geo_score,
                    ctr_score=ctr_score,
                    seo_threshold=seo_threshold,
                    geo_threshold=geo_threshold,
                ),
            }
        )
    return rows


def _build_cloudflare_rows(db, *, seo_threshold: int, geo_threshold: int) -> list[dict[str, Any]]:
    posts = _list_integration_posts(db)
    rows: list[dict[str, Any]] = []
    for post in posts:
        status = str(post.get("status") or "").strip().lower()
        if status not in {"published", "live"}:
            continue
        remote_id = str(post.get("id") or "").strip()
        detail = post
        if remote_id:
            try:
                response = _integration_request(db, method="GET", path=f"/api/integrations/posts/{remote_id}", timeout=45.0)
                data = _integration_data_or_raise(response)
                if isinstance(data, dict):
                    detail = data
            except Exception:
                detail = post
        slug = str(post.get("slug") or "").strip()
        title = str(detail.get("title") or post.get("title") or slug).strip()
        body_html = str(
            detail.get("contentHtml")
            or detail.get("contentMarkdown")
            or detail.get("content")
            or detail.get("excerpt")
            or post.get("excerpt")
            or ""
        ).strip()
        excerpt = str(detail.get("seoDescription") or detail.get("excerpt") or post.get("excerpt") or "").strip()
        category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
        score_payload = _score_payload(
            title=str(detail.get("seoTitle") or title),
            html_body=body_html,
            excerpt=excerpt,
            faq_section=[],
        )
        seo_score = int(score_payload.get("seo_score") or 0)
        geo_score = int(score_payload.get("geo_score") or 0)
        ctr_score = int(score_payload.get("ctr_score") or 0)
        threshold_pass = seo_score >= seo_threshold and geo_score >= geo_threshold
        rows.append(
            {
                "provider": "cloudflare",
                "remote_post_id": remote_id,
                "channel": str(category.get("slug") or "").strip(),
                "slug": slug,
                "title": title,
                "post_url": str(detail.get("publicUrl") or detail.get("url") or post.get("publicUrl") or post.get("url") or "").strip(),
                "seo_score": seo_score,
                "geo_score": geo_score,
                "ctr_score": ctr_score,
                "threshold_pass": threshold_pass,
                "priority": _priority(
                    seo_score=seo_score,
                    geo_score=geo_score,
                    ctr_score=ctr_score,
                    seo_threshold=seo_threshold,
                    geo_threshold=geo_threshold,
                ),
            }
        )
    return rows


def _provider_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("provider") or "unknown")
        bucket = buckets.setdefault(
            key,
            {
                "provider": key,
                "count": 0,
                "pass_count": 0,
                "seo_total": 0,
                "geo_total": 0,
                "ctr_total": 0,
            },
        )
        bucket["count"] += 1
        bucket["pass_count"] += 1 if row.get("threshold_pass") else 0
        bucket["seo_total"] += int(row.get("seo_score") or 0)
        bucket["geo_total"] += int(row.get("geo_score") or 0)
        bucket["ctr_total"] += int(row.get("ctr_score") or 0)
    summary: list[dict[str, Any]] = []
    for bucket in buckets.values():
        count = max(int(bucket["count"]), 1)
        summary.append(
            {
                "provider": bucket["provider"],
                "count": bucket["count"],
                "pass_count": bucket["pass_count"],
                "avg_seo_score": round(float(bucket["seo_total"]) / count, 1),
                "avg_geo_score": round(float(bucket["geo_total"]) / count, 1),
                "avg_ctr_score": round(float(bucket["ctr_total"]) / count, 1),
            }
        )
    summary.sort(key=lambda item: item["provider"])
    return summary


def _write_reports(rows: list[dict[str, Any]], *, prefix: str, seo_threshold: int, geo_threshold: int) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"{prefix}-{timestamp}.json"
    csv_path = REPORT_DIR / f"{prefix}-{timestamp}.csv"
    rows.sort(key=lambda item: (item["threshold_pass"], item["priority"] == "pass", item["ctr_score"], item["slug"]))

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "thresholds": {"seo": seo_threshold, "geo": geo_threshold},
        "total_count": len(rows),
        "pass_count": len([row for row in rows if bool(row.get("threshold_pass"))]),
        "fail_count": len([row for row in rows if not bool(row.get("threshold_pass"))]),
        "provider_summary": _provider_summary(rows),
        "items": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "provider",
        "remote_post_id",
        "channel",
        "slug",
        "title",
        "post_url",
        "seo_score",
        "geo_score",
        "ctr_score",
        "threshold_pass",
        "priority",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return {"json": str(json_path.resolve()), "csv": str(csv_path.resolve())}


def main() -> int:
    args = parse_args()
    with SessionLocal() as db:
        rows: list[dict[str, Any]] = []
        if args.provider in {"all", "blogger"}:
            rows.extend(
                _build_blogger_rows(
                    db,
                    seo_threshold=max(int(args.seo_threshold), 0),
                    geo_threshold=max(int(args.geo_threshold), 0),
                )
            )
        if args.provider in {"all", "cloudflare"}:
            rows.extend(
                _build_cloudflare_rows(
                    db,
                    seo_threshold=max(int(args.seo_threshold), 0),
                    geo_threshold=max(int(args.geo_threshold), 0),
                )
            )
    report_paths = _write_reports(
        rows,
        prefix=str(args.report_prefix).strip() or "blog-score-audit",
        seo_threshold=max(int(args.seo_threshold), 0),
        geo_threshold=max(int(args.geo_threshold), 0),
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "count": len(rows),
                "provider": args.provider,
                **report_paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
