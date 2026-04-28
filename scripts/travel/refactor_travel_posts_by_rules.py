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
TRAVEL_CATEGORIES = {"travel", "culture", "food", "uncategorized"}
ALLOWED_PATTERNS = {
    "travel-01-hidden-path-route",
    "travel-02-cultural-insider",
    "travel-03-local-flavor-guide",
    "travel-04-seasonal-secret",
    "travel-05-smart-traveler-log",
}
RULE_SET = "TRAVEL-GEN-V2"
RULE_VERSION = 2
MIN_VISIBLE_NON_SPACE_CHARS = 3000

IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SRC_RE = re.compile(r"""\bsrc\s*=\s*[\"']([^\"']+)[\"']""", re.IGNORECASE)
H1_RE = re.compile(r"<h1\b", re.IGNORECASE)
H2_RE = re.compile(r"<h2\b", re.IGNORECASE)
BLOCKED_RE = re.compile(r"<(script|style|form)\b", re.IGNORECASE)
IFRAME_RE = re.compile(r"<iframe\b", re.IGNORECASE)
INLINE_STYLE_RE = re.compile(r"\sstyle\s*=", re.IGNORECASE)
ARTICLE_TAG_RE = re.compile(r"</?article\b", re.IGNORECASE)


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    for raw_line in lines:
        line = str(raw_line or "").strip()
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
        value = value.strip()
        if len(value) >= 2 and ((value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"'))):
            value = value[1:-1]
        os.environ[key] = value


_load_runtime_env(RUNTIME_ENV_PATH)
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
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def visible_text(html: str | None) -> str:
    parser = TextExtractor()
    try:
        parser.feed(str(html or ""))
        return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html or ""))).strip()


def visible_non_space_len(html: str | None) -> int:
    return len(re.sub(r"\s+", "", visible_text(html)))


def extract_image_srcs(html: str | None) -> list[str]:
    srcs: list[str] = []
    for tag in IMG_RE.findall(str(html or "")):
        match = SRC_RE.search(tag)
        if match:
            srcs.append(match.group(1))
    return srcs


def detect_pattern(title: str | None, html: str | None, labels: list[str] | None) -> str:
    haystack = " ".join([str(title or ""), str(html or ""), " ".join(labels or [])]).lower()
    if any(token in haystack for token in ["food", "restaurant", "caf?", "cafe", "market", "comida", "restaurante", "???", "??"]):
        return "travel-03-local-flavor-guide"
    if any(token in haystack for token in ["festival", "season", "spring", "cherry", "autumn", "winter", "summer", "seasonal", "temporada", "?", "??", "?"]):
        return "travel-04-seasonal-secret"
    if any(token in haystack for token in ["route", "walk", "itinerary", "station", "subway", "bus", "c?mo llegar", "ruta", "??????", "????"]):
        return "travel-01-hidden-path-route"
    if any(token in haystack for token in ["palace", "temple", "heritage", "hanok", "museum", "culture", "history", "cultural", "patrimonio", "cultura", "??", "??"]):
        return "travel-02-cultural-insider"
    if any(token in haystack for token in ["tip", "avoid", "queue", "booking", "reservation", "smart", "budget", "skip", "consejo", "??", "??"]):
        return "travel-05-smart-traveler-log"
    return "unclassified"


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


def category_from_row(row: dict[str, Any]) -> str:
    key = str(row.get("editorial_category_key") or "").strip().lower()
    if key in TRAVEL_CATEGORIES:
        return key
    for label in normalize_labels(row.get("labels")):
        label_key = label.strip().lower()
        if label_key in TRAVEL_CATEGORIES:
            return label_key
    return ""


def issue_list(row: dict[str, Any]) -> list[str]:
    html = str(row.get("content_html") or "")
    labels = normalize_labels(row.get("labels"))
    pattern = str(row.get("article_pattern_id") or "").strip() or detect_pattern(row.get("title"), html, labels)
    issues: list[str] = []
    if visible_non_space_len(html) < MIN_VISIBLE_NON_SPACE_CHARS:
        issues.append("under_3000_chars_no_space")
    if H1_RE.search(html):
        issues.append("contains_h1")
    if len(H2_RE.findall(html)) < 3:
        issues.append("h2_less_than_3")
    if category_from_row(row) not in TRAVEL_CATEGORIES:
        issues.append("invalid_or_missing_category")
    if pattern not in ALLOWED_PATTERNS:
        issues.append("pattern_unclassified")
    return issues


def load_candidates(db, *, blog_ids: list[int]) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT s.blog_id, s.remote_post_id, s.title, s.url, s.status, s.published_at, s.labels,
                   s.thumbnail_url, s.content_html,
                   a.id AS article_id, a.slug AS article_slug, a.editorial_category_key,
                   a.article_pattern_id
            FROM synced_blogger_posts s
            LEFT JOIN blogger_posts bp ON bp.blogger_post_id = s.remote_post_id AND bp.blog_id = s.blog_id
            LEFT JOIN articles a ON a.id = bp.article_id
            WHERE s.blog_id = ANY(:ids)
              AND lower(COALESCE(s.status, '')) IN ('live', 'published', 'scheduled')
            ORDER BY s.blog_id, COALESCE(s.published_at, s.created_at) DESC NULLS LAST, s.title
            """
        ),
        {"ids": blog_ids},
    ).mappings().all()
    candidates: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        labels = normalize_labels(row.get("labels"))
        html = str(row.get("content_html") or "")
        issues = issue_list(row)
        pattern = str(row.get("article_pattern_id") or "").strip() or detect_pattern(row.get("title"), html, labels)
        candidates.append(
            {
                **row,
                "language": TRAVEL_BLOGS.get(int(row.get("blog_id") or 0), ""),
                "labels_list": labels,
                "category": category_from_row(row),
                "detected_pattern": pattern,
                "visible_non_space_chars": visible_non_space_len(html),
                "h1_count": len(H1_RE.findall(html)),
                "h2_count": len(H2_RE.findall(html)),
                "image_srcs": extract_image_srcs(html),
                "issues": issues,
                "target": bool(issues),
            }
        )
    return candidates


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = ["blog_id", "language", "remote_post_id", "title", "url", "category", "detected_pattern", "visible_non_space_chars", "h1_count", "h2_count", "target", "issues"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ";".join(row[key]) if key == "issues" else row.get(key, "") for key in fieldnames})


def summarize(rows: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    by_blog: dict[str, dict[str, int]] = {}
    by_issue: dict[str, int] = {}
    by_pattern: dict[str, int] = {}
    for row in rows:
        blog_key = str(row.get("blog_id") or "")
        bucket = by_blog.setdefault(blog_key, {"total": 0, "target": 0})
        bucket["total"] += 1
        if row.get("target"):
            bucket["target"] += 1
        pattern = str(row.get("detected_pattern") or "unclassified")
        by_pattern[pattern] = by_pattern.get(pattern, 0) + 1
        for issue in row.get("issues") or []:
            by_issue[issue] = by_issue.get(issue, 0) + 1
    return {
        "rule_set": RULE_SET,
        "rule_version": RULE_VERSION,
        "maps_rule_removed": True,
        "total": len(rows),
        "target_count": len(targets),
        "by_blog": by_blog,
        "by_issue": dict(sorted(by_issue.items())),
        "by_pattern": dict(sorted(by_pattern.items())),
    }


def response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "meta_description", "labels", "content_html", "article_pattern_id", "article_pattern_version", "change_summary"],
        "properties": {
            "title": {"type": "string"},
            "meta_description": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
            "content_html": {"type": "string"},
            "article_pattern_id": {"type": "string", "enum": sorted(ALLOWED_PATTERNS)},
            "article_pattern_version": {"type": "integer", "enum": [RULE_VERSION]},
            "change_summary": {"type": "string"},
        },
    }


def build_codex_prompt(row: dict[str, Any]) -> str:
    payload = {
        "rule_set": RULE_SET,
        "blog_id": row["blog_id"],
        "language": row["language"],
        "remote_post_id": row["remote_post_id"],
        "url": row["url"],
        "title": row["title"],
        "labels": row["labels_list"],
        "category": row["category"] or "uncategorized",
        "detected_pattern": row["detected_pattern"],
        "issues": row["issues"],
        "visible_non_space_chars": row["visible_non_space_chars"],
        "existing_image_srcs": row["image_srcs"],
        "content_html": row["content_html"],
    }
    return f"""You are Codex CLI acting as a BloggerGent travel post refactor worker.

Follow rule set {RULE_SET} exactly.

Task:
- Rewrite only the existing Blogger post body HTML.
- Keep the same language: {row['language']}.
- Fix these issues: {', '.join(row['issues'])}.
- Make visible body text at least {MIN_VISIBLE_NON_SPACE_CHARS} non-space characters.
- Remove all body-level <h1>; use <h2> as the first heading level.
- Use at least 3 <h2> sections.
- Choose exactly one of the 5 allowed travel patterns and return it as article_pattern_id.
- Do not add Google Maps iframe. Maps are not required.
- Do not generate or change images. Preserve existing image src URLs when image tags exist.
- Do not add <script>, <style>, <form>, or <iframe>.
- Do not wrap the body in <article>. Blogger already owns the page layout.
- Do not use inline style attributes. Use clean semantic HTML only.
- Keep travel-blog tone: real movement, local atmosphere, route/place judgment, practical timing.

Allowed pattern IDs:
- travel-01-hidden-path-route
- travel-02-cultural-insider
- travel-03-local-flavor-guide
- travel-04-seasonal-secret
- travel-05-smart-traveler-log

Return JSON only with this shape:
{{
  "title": "string",
  "meta_description": "90-160 character search description in the post language",
  "labels": ["5", "to", "6", "labels"],
  "content_html": "full updated Blogger body HTML",
  "article_pattern_id": "one allowed pattern id",
  "article_pattern_version": 2,
  "change_summary": "short explanation"
}}

Source packet JSON:
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
"""


def request_id_for(row: dict[str, Any]) -> str:
    remote = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(row.get("remote_post_id") or "post"))
    return f"travel-refactor-{row['blog_id']}-{remote}"


def create_codex_requests(rows: list[dict[str, Any]], *, storage_root: Path, report_dir: Path, model: str, enqueue: bool) -> list[dict[str, Any]]:
    requests_dir = storage_root / "codex-queue" / "requests"
    if enqueue:
        requests_dir.mkdir(parents=True, exist_ok=True)
    packet_dir = report_dir / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    created: list[dict[str, Any]] = []
    schema = response_schema()
    for row in rows:
        req_id = request_id_for(row)
        request = {
            "request_id": req_id,
            "stage_name": "travel_refactor",
            "model": model,
            "workspace_dir": str(REPO_ROOT),
            "response_kind": "json_schema",
            "response_schema": schema,
            "prompt": build_codex_prompt(row),
            "metadata": {"rule_set": RULE_SET, "blog_id": row["blog_id"], "language": row["language"], "remote_post_id": row["remote_post_id"], "url": row["url"], "issues": row["issues"]},
        }
        write_json(packet_dir / f"{req_id}.json", request)
        if enqueue:
            write_json(requests_dir / f"{req_id}.json", request)
        created.append({"request_id": req_id, "remote_post_id": row["remote_post_id"], "blog_id": row["blog_id"], "url": row["url"], "issues": row["issues"], "packet_path": str(packet_dir / f"{req_id}.json")})
    return created


def parse_response_file(path: Path) -> tuple[str, dict[str, Any]]:
    wrapper = json.loads(path.read_text(encoding="utf-8-sig"))
    content = str(wrapper.get("content") or "").strip()
    payload = json.loads(content)
    return str(wrapper.get("request_id") or path.stem), payload


def validate_result(row: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    html = str(payload.get("content_html") or "")
    pattern = str(payload.get("article_pattern_id") or "")
    if visible_non_space_len(html) < MIN_VISIBLE_NON_SPACE_CHARS:
        errors.append("result_under_3000")
    if H1_RE.search(html):
        errors.append("result_contains_h1")
    if len(H2_RE.findall(html)) < 3:
        errors.append("result_h2_less_than_3")
    if BLOCKED_RE.search(html) or IFRAME_RE.search(html):
        errors.append("result_blocked_tag")
    if INLINE_STYLE_RE.search(html):
        errors.append("result_inline_style")
    if ARTICLE_TAG_RE.search(html):
        errors.append("result_article_wrapper")
    if pattern not in ALLOWED_PATTERNS:
        errors.append("result_invalid_pattern")
    if int(payload.get("article_pattern_version") or 0) != RULE_VERSION:
        errors.append("result_invalid_pattern_version")
    source_imgs = set(row.get("image_srcs") or [])
    result_imgs = set(extract_image_srcs(html))
    if source_imgs and not source_imgs.issubset(result_imgs):
        errors.append("result_dropped_existing_image_src")
    return errors


def apply_responses(*, response_dir: Path, execute: bool, limit: int | None, blog_ids: list[int]) -> dict[str, Any]:
    with SessionLocal() as db:
        candidates = {request_id_for(row): row for row in load_candidates(db, blog_ids=blog_ids)}
        providers: dict[int, Any] = {}
        blogs: dict[int, Blog] = {}
        rows = sorted(response_dir.glob("travel-refactor-*.json"))
        if limit:
            rows = rows[:limit]
        items: list[dict[str, Any]] = []
        for path in rows:
            try:
                request_id, payload = parse_response_file(path)
                row = candidates.get(request_id)
                if row is None:
                    items.append({"request_id": request_id, "action": "skipped", "error": "candidate_not_found"})
                    continue
                errors = validate_result(row, payload)
                if errors:
                    items.append({"request_id": request_id, "remote_post_id": row["remote_post_id"], "action": "failed_validation", "errors": errors})
                    continue
                if not execute:
                    items.append({"request_id": request_id, "remote_post_id": row["remote_post_id"], "action": "validated_dry_run", "errors": []})
                    continue
                blog_id = int(row["blog_id"])
                if blog_id not in blogs:
                    blog = db.get(Blog, blog_id)
                    if blog is None:
                        raise RuntimeError(f"blog_not_found:{blog_id}")
                    blogs[blog_id] = blog
                    providers[blog_id] = get_blogger_provider(db, blog)
                labels = [str(x).strip() for x in payload.get("labels") or row.get("labels_list") or [] if str(x).strip()]
                summary, _raw = providers[blog_id].update_post(
                    post_id=str(row["remote_post_id"]),
                    title=str(payload.get("title") or row["title"]),
                    content=str(payload.get("content_html") or ""),
                    labels=labels,
                    meta_description=str(payload.get("meta_description") or ""),
                )
                items.append({"request_id": request_id, "remote_post_id": row["remote_post_id"], "action": "updated", "url": summary.get("url"), "pattern": payload.get("article_pattern_id")})
            except Exception as exc:
                items.append({"request_id": path.stem, "action": "failed", "error": str(exc)})
        sync_results: dict[str, Any] = {}
        if execute:
            for blog_id, blog in blogs.items():
                sync_results[str(blog_id)] = sync_blogger_posts_for_blog(db, blog)
        return {"execute": execute, "response_dir": str(response_dir), "processed_count": len(items), "updated_count": sum(1 for item in items if item.get("action") == "updated"), "items": items, "sync_results": sync_results}


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
    parser = argparse.ArgumentParser(description="Audit and refactor travel Blogger posts using TRAVEL-GEN-V2 and Codex CLI queue.")
    parser.add_argument("--mode", choices=("audit", "packet_only", "apply_packets"), default="audit")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--issue", action="append", default=[], help="Filter target issue; can be repeated.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--batch-name", default="batch")
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT))
    parser.add_argument("--response-dir", default="")
    parser.add_argument("--enqueue-to-codex-queue", action="store_true", help="Also copy packet JSON files into storage/codex-queue/requests. Default only writes report packets.")
    parser.add_argument("--execute", action="store_true", help="Actually update Blogger in apply_packets mode.")
    args = parser.parse_args()

    storage_root = Path(args.storage_root).resolve()
    report_dir = storage_root / "travel" / "refactor" / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{args.batch_name}"
    blog_ids = parse_blog_ids(args.blog_ids)
    with SessionLocal() as db:
        candidates = load_candidates(db, blog_ids=blog_ids)
    target_issues = set(args.issue or [])
    all_targets = [row for row in candidates if row["target"] and (not target_issues or target_issues.intersection(row["issues"]))]
    targets = sorted(all_targets, key=lambda row: (row["blog_id"], row["visible_non_space_chars"], row["title"] or ""))
    if args.limit and args.mode != "audit":
        targets = targets[: max(args.limit, 1)]

    write_json(report_dir / "audit.json", {"rule_set": RULE_SET, "blog_ids": blog_ids, "total": len(candidates), "target_count": len(all_targets), "selected_count": len(targets), "targets": targets})
    write_csv(report_dir / "audit.csv", candidates)
    write_json(report_dir / "summary.json", summarize(candidates, all_targets))
    write_csv(report_dir / "manifest.csv", all_targets)

    if args.mode == "audit":
        result = {"mode": args.mode, "report_dir": str(report_dir), "total": len(candidates), "target_count": len(all_targets), "selected_count": len(targets)}
    elif args.mode == "packet_only":
        created = create_codex_requests(targets, storage_root=storage_root, report_dir=report_dir, model=args.model, enqueue=bool(args.enqueue_to_codex_queue))
        result = {
            "mode": args.mode,
            "report_dir": str(report_dir),
            "created_count": len(created),
            "enqueued_to_codex_queue": bool(args.enqueue_to_codex_queue),
            "codex_requests_dir": str(storage_root / "codex-queue" / "requests") if args.enqueue_to_codex_queue else None,
            "created": created,
        }
    else:
        response_dir = Path(args.response_dir).resolve() if args.response_dir else storage_root / "codex-queue" / "responses"
        apply_result = apply_responses(response_dir=response_dir, execute=bool(args.execute), limit=args.limit, blog_ids=blog_ids)
        write_json(report_dir / "apply-result.json", apply_result)
        result = {"mode": args.mode, "report_dir": str(report_dir), **apply_result}

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
