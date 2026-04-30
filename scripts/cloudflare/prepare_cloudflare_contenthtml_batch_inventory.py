from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

RUNTIME_ROOT = Path(os.getenv("BLOGGENT_RUNTIME_ROOT", r"D:\Donggri_Runtime\BloggerGent"))
AUDIT_ROOT = RUNTIME_ROOT / "Rool" / "30-cloudflare" / "12-category-layout-refactor" / "body-contract-audit"
OUT_ROOT = AUDIT_ROOT / "category-batches"
LEGACY_REPORT_ROOT = RUNTIME_ROOT / "storage" / "cloudflare" / "_reports"
CHANNEL_ID = "cloudflare:dongriarchive"
DEFAULT_BATCH_SIZE = 25

CATEGORY_ORDER = [
    "개발과-프로그래밍",
    "일상과-메모",
    "여행과-기록",
    "동그리의-생각",
    "주식의-흐름",
    "크립토의-흐름",
    "나스닥의-흐름",
    "문화와-공간",
    "축제와-현장",
    "삶을-유용하게",
    "삶의-기름칠",
    "미스테리아-스토리",
]

CATEGORY_BATCH_PREFIX = {
    "개발과-프로그래밍": "dev",
    "일상과-메모": "daily",
    "여행과-기록": "travel-record",
    "동그리의-생각": "thought",
    "주식의-흐름": "stock",
    "크립토의-흐름": "crypto",
    "나스닥의-흐름": "nasdaq",
    "문화와-공간": "culture",
    "축제와-현장": "festival",
    "삶을-유용하게": "life-useful",
    "삶의-기름칠": "life-benefit",
    "미스테리아-스토리": "mysteria",
}

PRIORITY_RANK = {"P0": 0, "P1": 1, "FETCH_ERROR": 2, "OK": 3}


def _load_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = value
    os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@localhost:15432/bloggent")
    os.environ.setdefault("STORAGE_ROOT", str(RUNTIME_ROOT / "storage"))


_load_runtime_env()

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ManagedChannel, SyncedCloudflarePost  # noqa: E402


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return _safe_text(value)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _audit_path(value: str | None) -> Path:
    if value:
        return Path(value)
    latest = AUDIT_ROOT / "cloudflare-body-contract-audit-latest.csv"
    if not latest.exists():
        raise FileNotFoundError(f"Audit CSV not found: {latest}")
    return latest


def _score_gap(value: Any, target: float = 80.0) -> float:
    score = _safe_float(value)
    if score is None:
        return target
    return max(target - score, 0.0)


def _category_key(row: dict[str, Any]) -> str:
    return _safe_text(row.get("category_slug") or row.get("remote_category_slug") or row.get("category_name") or "unknown")


def _category_rank(category: str) -> int:
    try:
        return CATEGORY_ORDER.index(category)
    except ValueError:
        return len(CATEGORY_ORDER)


def _batch_prefix(category: str) -> str:
    return CATEGORY_BATCH_PREFIX.get(category, "unknown")


def _batch_reason(row: dict[str, Any]) -> str:
    issues = _safe_text(row.get("issue_codes"))
    reasons: list[str] = []
    if row.get("refactor_priority") == "P0":
        reasons.append("body_contract_p0")
    elif row.get("refactor_priority") == "P1":
        reasons.append("body_contract_p1")
    if _score_gap(row.get("seo_score")) > 0:
        reasons.append("seo_below_80")
    if _score_gap(row.get("geo_score")) > 0:
        reasons.append("geo_below_80")
    if _score_gap(row.get("ctr_score")) > 0:
        reasons.append("ctr_below_80")
    if _score_gap(row.get("lighthouse_score")) > 0:
        reasons.append("lighthouse_below_80")
    if _safe_text(row.get("image_health_status")) and _safe_text(row.get("image_health_status")).lower() != "ok":
        reasons.append("image_health_not_ok")
    if issues:
        reasons.append(f"issues:{issues}")
    return ";".join(reasons) if reasons else "ok"


def _load_db_posts() -> dict[str, SyncedCloudflarePost]:
    with SessionLocal() as db:
        managed_channel = (
            db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == CHANNEL_ID))
            .scalars()
            .first()
        )
        query = select(SyncedCloudflarePost).where(SyncedCloudflarePost.status.in_(["published", "live"]))
        if managed_channel is not None:
            query = query.where(SyncedCloudflarePost.managed_channel_id == managed_channel.id)
        posts = db.execute(query).scalars().all()
    return {_safe_text(post.remote_post_id): post for post in posts}


def _latest_report(pattern: str) -> Path | None:
    candidates = sorted(
        LEGACY_REPORT_ROOT.glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_category_review_map() -> dict[str, dict[str, str]]:
    review_map: dict[str, dict[str, str]] = {}
    high_confidence_path = _latest_report("cloudflare-category-audit-high-confidence-*.csv")
    if high_confidence_path is None:
        return review_map
    for row in _read_csv(high_confidence_path):
        payload = {
            "category_audit_status": "high_confidence_review",
            "category_audit_reason": _safe_text(row.get("reason_code")),
            "category_audit_matched_rules": _safe_text(row.get("matched_rules")),
            "category_audit_source_path": str(high_confidence_path),
        }
        remote_post_id = _safe_text(row.get("remote_post_id"))
        slug = _safe_text(row.get("slug"))
        if remote_post_id:
            review_map[f"id:{remote_post_id}"] = payload
        if slug:
            review_map[f"slug:{slug}"] = payload
    return review_map


def build_inventory(*, audit_csv: str | None, batch_size: int) -> dict[str, Any]:
    source_path = _audit_path(audit_csv)
    audit_rows = _read_csv(source_path)
    db_posts = _load_db_posts()
    category_review_map = _load_category_review_map()
    rows: list[dict[str, Any]] = []

    for index, audit in enumerate(audit_rows, 1):
        remote_post_id = _safe_text(audit.get("remote_post_id"))
        post = db_posts.get(remote_post_id)
        category = _category_key(audit)
        slug = _safe_text(audit.get("slug"))
        category_review = category_review_map.get(f"id:{remote_post_id}") or category_review_map.get(f"slug:{slug}") or {}
        output = {
            "row_no": index,
            "remote_post_id": remote_post_id,
            "status": _safe_text(audit.get("status")),
            "category_slug": category,
            "category_name": _safe_text(audit.get("category_name")),
            "slug": slug,
            "title": _safe_text(audit.get("title")),
            "url": _safe_text(audit.get("url")),
            "published_at": _iso(post.published_at if post else ""),
            "updated_at_remote": _iso(post.updated_at_remote if post else ""),
            "article_pattern_id": _safe_text(audit.get("article_pattern_id") or (post.article_pattern_id if post else "")),
            "article_pattern_version": _safe_text(audit.get("article_pattern_version") or (post.article_pattern_version if post else "")),
            "seo_score": _safe_text(audit.get("seo_score") or (post.seo_score if post else "")),
            "geo_score": _safe_text(audit.get("geo_score") or (post.geo_score if post else "")),
            "ctr_score": _safe_text(post.ctr if post else ""),
            "lighthouse_score": _safe_text(audit.get("lighthouse_score") or (post.lighthouse_score if post else "")),
            "lighthouse_last_audited_at": _iso(post.lighthouse_last_audited_at if post else ""),
            "korean_syllable_count": _safe_text(audit.get("korean_syllable_count")),
            "plain_text_length_reference": _safe_text(audit.get("plain_text_length_reference")),
            "h2_count": _safe_text(audit.get("h2_count")),
            "live_image_count": _safe_text(post.live_image_count if post else ""),
            "live_unique_image_count": _safe_text(post.live_unique_image_count if post else ""),
            "live_webp_count": _safe_text(post.live_webp_count if post else ""),
            "live_png_count": _safe_text(post.live_png_count if post else ""),
            "live_other_image_count": _safe_text(post.live_other_image_count if post else ""),
            "image_health_status": _safe_text(post.image_health_status if post else ""),
            "live_image_issue": _safe_text(post.live_image_issue if post else ""),
            "live_image_audited_at": _iso(post.live_image_audited_at if post else ""),
            "thumbnail_url": _safe_text(post.thumbnail_url if post else ""),
            "expected_body_class": _safe_text(audit.get("expected_body_class")),
            "cf_body_classes_in_content": _safe_text(audit.get("cf_body_classes_in_content")),
            "refactor_priority": _safe_text(audit.get("refactor_priority")),
            "issue_codes": _safe_text(audit.get("issue_codes")),
            "required_fact_hit_count": _safe_text(audit.get("required_fact_hit_count")),
            "required_fact_total": _safe_text(audit.get("required_fact_total")),
            "category_audit_status": _safe_text(category_review.get("category_audit_status")),
            "category_audit_reason": _safe_text(category_review.get("category_audit_reason")),
            "category_audit_matched_rules": _safe_text(category_review.get("category_audit_matched_rules")),
            "category_audit_source_path": _safe_text(category_review.get("category_audit_source_path")),
            "batch_reason": "",
            "batch_id": "",
            "batch_order": "",
            "batch_status": "not_planned",
        }
        output["batch_reason"] = _batch_reason(output)
        rows.append(output)

    rows.sort(
        key=lambda row: (
            _category_rank(_category_key(row)),
            PRIORITY_RANK.get(_safe_text(row.get("refactor_priority")), 9),
            -_score_gap(row.get("seo_score")),
            -_score_gap(row.get("geo_score")),
            -_score_gap(row.get("lighthouse_score")),
            _safe_int(row.get("korean_syllable_count")) or 999999,
            _safe_text(row.get("slug")),
        )
    )

    planned_rows: list[dict[str, Any]] = []
    batch_files: list[dict[str, Any]] = []
    category_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _safe_text(row.get("category_audit_status")) == "high_confidence_review":
            continue
        if _safe_text(row.get("refactor_priority")) in {"P0", "P1", "FETCH_ERROR"}:
            category_groups[_category_key(row)].append(row)

    for category in sorted(category_groups.keys(), key=_category_rank):
        group = category_groups[category]
        for batch_index, start in enumerate(range(0, len(group), batch_size), 1):
            batch_id = f"cf-body-{_batch_prefix(category)}-{batch_index:03d}"
            batch_rows = group[start : start + batch_size]
            for order, row in enumerate(batch_rows, 1):
                row["batch_id"] = batch_id
                row["batch_order"] = order
                row["batch_status"] = "planned"
                planned_rows.append(row)
            batch_path = OUT_ROOT / f"{batch_id}.csv"
            _write_csv(batch_path, batch_rows)
            batch_files.append(
                {
                    "batch_id": batch_id,
                    "category_slug": category,
                    "count": len(batch_rows),
                    "path": str(batch_path),
                }
            )

    stamp = _stamp()
    inventory_path = OUT_ROOT / f"cloudflare-live-post-inventory-{stamp}.csv"
    inventory_latest_path = OUT_ROOT / "cloudflare-live-post-inventory-latest.csv"
    plan_path = OUT_ROOT / f"cloudflare-contenthtml-category-batch-plan-{stamp}.csv"
    plan_latest_path = OUT_ROOT / "cloudflare-contenthtml-category-batch-plan-latest.csv"
    summary_path = OUT_ROOT / f"cloudflare-contenthtml-category-batch-summary-{stamp}.json"
    summary_latest_path = OUT_ROOT / "cloudflare-contenthtml-category-batch-summary-latest.json"

    _write_csv(inventory_path, rows)
    _write_csv(inventory_latest_path, rows)
    _write_csv(plan_path, planned_rows)
    _write_csv(plan_latest_path, planned_rows)

    category_summary: list[dict[str, Any]] = []
    for category in sorted({_category_key(row) for row in rows}, key=_category_rank):
        group = [row for row in rows if _category_key(row) == category]
        priority_counts = Counter(_safe_text(row.get("refactor_priority")) for row in group)
        category_summary.append(
            {
                "category_slug": category,
                "total": len(group),
                "p0": priority_counts.get("P0", 0),
                "p1": priority_counts.get("P1", 0),
                "ok": priority_counts.get("OK", 0),
                "fetch_error": priority_counts.get("FETCH_ERROR", 0),
                "seo_below_80": sum(1 for row in group if _score_gap(row.get("seo_score")) > 0),
                "geo_below_80": sum(1 for row in group if _score_gap(row.get("geo_score")) > 0),
                "ctr_below_80": sum(1 for row in group if _score_gap(row.get("ctr_score")) > 0),
                "lighthouse_below_80": sum(1 for row in group if _score_gap(row.get("lighthouse_score")) > 0),
                "korean_under_2000": sum(1 for row in group if (_safe_int(row.get("korean_syllable_count")) or 0) < 2000),
                "image_issue": sum(
                    1
                    for row in group
                    if _safe_text(row.get("image_health_status"))
                    and _safe_text(row.get("image_health_status")).lower() != "ok"
                ),
                "category_review_excluded": sum(
                    1 for row in group if _safe_text(row.get("category_audit_status")) == "high_confidence_review"
                ),
            }
        )

    summary = {
        "mode": "category_batch_inventory",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_audit_csv": str(source_path),
        "total_count": len(rows),
        "planned_count": len(planned_rows),
        "batch_size": batch_size,
        "batch_count": len(batch_files),
        "inventory_csv": str(inventory_path),
        "inventory_latest_csv": str(inventory_latest_path),
        "batch_plan_csv": str(plan_path),
        "batch_plan_latest_csv": str(plan_latest_path),
        "batch_files": batch_files,
        "category_summary": category_summary,
        "mutation_policy": "read_only_no_db_live_r2_writes",
    }
    _write_json(summary_path, summary)
    _write_json(summary_latest_path, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Cloudflare live post inventory and category-first refactor batches.")
    parser.add_argument("--audit-csv", default=None)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    result = build_inventory(audit_csv=args.audit_csv, batch_size=args.batch_size)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
