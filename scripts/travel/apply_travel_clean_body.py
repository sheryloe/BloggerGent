from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_STORAGE_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage")
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
TRAVEL_BLOGS = {34: "en", 36: "es", 37: "ja"}

H1_OPEN_RE = re.compile(r"<\s*h1(\s[^>]*)?>", re.IGNORECASE)
H1_CLOSE_RE = re.compile(r"<\s*/\s*h1\s*>", re.IGNORECASE)
ARTICLE_OPEN_RE = re.compile(r"<\s*article\b[^>]*>", re.IGNORECASE)
ARTICLE_CLOSE_RE = re.compile(r"<\s*/\s*article\s*>", re.IGNORECASE)
STYLE_ATTR_RE = re.compile(r"\sstyle\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
BLOCK_RE = re.compile(r"<\s*(script|style|form|iframe)\b[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
SELF_BLOCK_RE = re.compile(r"<\s*(script|style|form|iframe)\b[^>]*?/?>", re.IGNORECASE)
H2_RE = re.compile(r"<\s*h2\b", re.IGNORECASE)


def load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip("\"'")
        os.environ[key] = value


load_runtime_env(RUNTIME_ENV_PATH)
os.environ.setdefault("DATABASE_URL", os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL))
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", os.environ.get("BLOGGENT_SETTINGS_ENCRYPTION_SECRET", "bloggent-dockerdesktop-2026-03-17"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Blog  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def visible_text(html: str) -> str:
    parser = TextExtractor()
    try:
        parser.feed(html)
        return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def normalize_labels(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def clean_body(html: str) -> tuple[str, list[str]]:
    cleaned = str(html or "")
    changes: list[str] = []

    cleaned_next = BLOCK_RE.sub("", cleaned)
    cleaned_next = SELF_BLOCK_RE.sub("", cleaned_next)
    if cleaned_next != cleaned:
        changes.append("removed_blocked_tags")
        cleaned = cleaned_next

    cleaned_next = H1_OPEN_RE.sub("<h2>", cleaned)
    cleaned_next = H1_CLOSE_RE.sub("</h2>", cleaned_next)
    if cleaned_next != cleaned:
        changes.append("h1_to_h2")
        cleaned = cleaned_next

    cleaned_next = ARTICLE_OPEN_RE.sub("", cleaned)
    cleaned_next = ARTICLE_CLOSE_RE.sub("", cleaned_next)
    if cleaned_next != cleaned:
        changes.append("removed_article_wrapper")
        cleaned = cleaned_next

    cleaned_next = STYLE_ATTR_RE.sub("", cleaned)
    if cleaned_next != cleaned:
        changes.append("removed_inline_style")
        cleaned = cleaned_next

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, changes


def has_clean_body_issue(html: str) -> bool:
    return bool(
        H1_OPEN_RE.search(html)
        or ARTICLE_OPEN_RE.search(html)
        or ARTICLE_CLOSE_RE.search(html)
        or STYLE_ATTR_RE.search(html)
        or BLOCK_RE.search(html)
        or SELF_BLOCK_RE.search(html)
    )


def load_rows(db, blog_ids: list[int]) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT blog_id, remote_post_id, title, url, status, labels, content_html, published_at
            FROM synced_blogger_posts
            WHERE blog_id = ANY(:ids)
              AND lower(COALESCE(status, '')) IN ('live', 'published', 'scheduled')
            ORDER BY blog_id, COALESCE(published_at, synced_at) DESC NULLS LAST, title
            """
        ),
        {"ids": blog_ids},
    ).mappings().all()
    return [dict(row) for row in rows]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "blog_id",
        "remote_post_id",
        "title",
        "url",
        "status",
        "before_visible_chars",
        "after_visible_chars",
        "before_h2_count",
        "after_h2_count",
        "changed",
        "changes",
        "api_result",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: ";".join(row[field]) if field == "changes" else row.get(field, "") for field in fields})


def parse_blog_ids(raw: str) -> list[int]:
    values: list[int] = []
    for token in str(raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        blog_id = int(token)
        if blog_id not in TRAVEL_BLOGS:
            raise ValueError(f"Travel blog id only allows {sorted(TRAVEL_BLOGS)}; got {blog_id}")
        values.append(blog_id)
    return values or sorted(TRAVEL_BLOGS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply TRAVEL-CLEAN-BODY deterministic cleanup to travel Blogger posts.")
    parser.add_argument("--mode", choices=("dry_run", "execute"), default="dry_run")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT))
    parser.add_argument("--batch-name", default="travel-clean-body")
    args = parser.parse_args()

    blog_ids = parse_blog_ids(args.blog_ids)
    storage_root = Path(args.storage_root).resolve()
    report_dir = storage_root / "travel" / "refactor" / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{args.batch_name}"
    before_after_dir = report_dir / "before-after"
    results: list[dict[str, Any]] = []

    with SessionLocal() as db:
        rows = load_rows(db, blog_ids)
        targets = [row for row in rows if has_clean_body_issue(str(row.get("content_html") or ""))]
        if args.limit and args.limit > 0:
            targets = targets[: args.limit]

        providers: dict[int, Any] = {}
        blogs: dict[int, Blog] = {}
        for row in targets:
            html = str(row.get("content_html") or "")
            cleaned, changes = clean_body(html)
            result = {
                "blog_id": row.get("blog_id"),
                "remote_post_id": row.get("remote_post_id"),
                "title": row.get("title"),
                "url": row.get("url"),
                "status": row.get("status"),
                "before_visible_chars": len(re.sub(r"\s+", "", visible_text(html))),
                "after_visible_chars": len(re.sub(r"\s+", "", visible_text(cleaned))),
                "before_h2_count": len(H2_RE.findall(html)),
                "after_h2_count": len(H2_RE.findall(cleaned)),
                "changed": cleaned != html,
                "changes": changes,
                "api_result": "dry_run",
                "error": "",
            }
            write_json(
                before_after_dir / f"{row.get('blog_id')}-{row.get('remote_post_id')}.json",
                {
                    "row": {key: value for key, value in row.items() if key != "content_html"},
                    "before_content_html": html,
                    "after_content_html": cleaned,
                    "changes": changes,
                },
            )
            if args.mode == "execute" and cleaned != html:
                try:
                    blog_id = int(row["blog_id"])
                    if blog_id not in blogs:
                        blog = db.get(Blog, blog_id)
                        if blog is None:
                            raise RuntimeError(f"blog_not_found:{blog_id}")
                        blogs[blog_id] = blog
                        providers[blog_id] = get_blogger_provider(db, blog)
                    providers[blog_id].update_post(
                        post_id=str(row["remote_post_id"]),
                        title=str(row["title"] or ""),
                        content=cleaned,
                        labels=normalize_labels(row.get("labels")),
                        meta_description="",
                    )
                    result["api_result"] = "updated"
                except Exception as exc:
                    result["api_result"] = "failed"
                    result["error"] = str(exc)
            results.append(result)

        sync_results: dict[str, Any] = {}
        if args.mode == "execute":
            for blog_id, blog in blogs.items():
                sync_results[str(blog_id)] = sync_blogger_posts_for_blog(db, blog)

    summary = {
        "mode": args.mode,
        "rule": "TRAVEL-CLEAN-BODY",
        "blog_ids": blog_ids,
        "report_dir": str(report_dir),
        "target_count": len(targets),
        "changed_count": sum(1 for row in results if row.get("changed")),
        "updated_count": sum(1 for row in results if row.get("api_result") == "updated"),
        "failed_count": sum(1 for row in results if row.get("api_result") == "failed"),
        "sync_results": sync_results,
    }
    write_json(report_dir / "summary.json", summary)
    write_json(report_dir / "results.json", results)
    write_csv(report_dir / "results.csv", results)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
