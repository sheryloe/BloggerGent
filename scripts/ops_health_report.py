#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
REPORT_DIR = ROOT / "storage" / "reports"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql+psycopg2://bloggent:bloggent@localhost:15432/bloggent",
    )

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Blog, Job, JobStatus  # noqa: E402
from app.services.blogger_oauth_service import authorized_google_request  # noqa: E402
from app.services.google_sheet_service import (  # noqa: E402
    _read_sheet_rows,
    _sheet_url,
    get_google_sheet_sync_config,
)
from app.services.openai_usage_service import get_openai_free_usage  # noqa: E402


def _safe_text(value: object | None) -> str:
    return str(value or "").strip()


def _now_kst_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _parse_report_snapshot(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    status_match = re.search(r'"result"\s*:\s*\{.*?"status"\s*:\s*"([^"]+)"', text, flags=re.S)
    created_match = re.search(r'"created_count"\s*:\s*(\d+)', text)
    failed_match = re.search(r'"failed_count"\s*:\s*(\d+)', text)
    generated_match = re.search(r'"generated_at_utc"\s*:\s*"([^"]+)"', text)
    return {
        "file": path.name,
        "generated_at_utc": generated_match.group(1) if generated_match else "",
        "status": status_match.group(1) if status_match else "unknown",
        "created_count": int(created_match.group(1)) if created_match else 0,
        "failed_count": int(failed_match.group(1)) if failed_match else 0,
    }


def _latest_cloudflare_reports(limit: int = 5) -> list[dict[str, Any]]:
    files = sorted(
        REPORT_DIR.glob("cloudflare-generate-*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    snapshots: list[dict[str, Any]] = []
    for path in files[:limit]:
        snapshots.append(_parse_report_snapshot(path))
    return snapshots


def _fetch_sheet_tabs(db) -> list[str]:
    config = get_google_sheet_sync_config(db)
    sheet_id = _safe_text(config.get("sheet_id"))
    if not sheet_id:
        return []
    response = authorized_google_request(
        db,
        "GET",
        _sheet_url(sheet_id, ""),
        params={"fields": "sheets.properties.title"},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json() if response.content else {}
    tabs: list[str] = []
    for sheet in payload.get("sheets", []) if isinstance(payload, dict) else []:
        if not isinstance(sheet, dict):
            continue
        properties = sheet.get("properties")
        if not isinstance(properties, dict):
            continue
        title = _safe_text(properties.get("title"))
        if title:
            tabs.append(title)
    return tabs


def _sheet_issues(db) -> dict[str, Any]:
    config = get_google_sheet_sync_config(db)
    sheet_id = _safe_text(config.get("sheet_id"))
    if not sheet_id:
        return {"configured": False, "duplicates": [], "english_columns": []}

    duplicates: list[dict[str, Any]] = []
    english_columns: list[dict[str, Any]] = []
    tabs = _fetch_sheet_tabs(db)
    for tab in tabs:
        if _safe_text(tab).startswith("__"):
            continue
        rows = _read_sheet_rows(db, sheet_id=sheet_id, tab_name=tab)
        header = rows[0] if rows else []
        if not header:
            continue
        counts = Counter(_safe_text(value) for value in header if _safe_text(value))
        duplicate_columns = [column for column, count in counts.items() if count > 1]
        if duplicate_columns:
            duplicates.append({"tab": tab, "columns": duplicate_columns})

        english_only = [column for column in header if re.fullmatch(r"[a-z0-9_]+", _safe_text(column))]
        if english_only:
            english_columns.append({"tab": tab, "columns": english_only})

    return {
        "configured": True,
        "sheet_id": sheet_id,
        "duplicates": duplicates,
        "english_columns": english_columns,
    }


def _failed_jobs_last_hours(db, hours: int = 24, limit: int = 30) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(hours=max(hours, 1))
    rows = db.execute(
        select(
            Job.id,
            Job.blog_id,
            Blog.slug,
            Job.keyword_snapshot,
            Job.end_time,
        )
        .join(Blog, Blog.id == Job.blog_id)
        .where(Job.status == JobStatus.FAILED)
        .where(Job.end_time.is_not(None))
        .where(Job.end_time >= since)
        .order_by(Job.end_time.desc())
        .limit(max(limit, 1))
    ).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        end_time = row.end_time.astimezone(timezone.utc).replace(microsecond=0).isoformat() if row.end_time else ""
        items.append(
            {
                "job_id": int(row.id),
                "blog_id": int(row.blog_id),
                "blog_slug": _safe_text(row.slug),
                "keyword": _safe_text(row.keyword_snapshot),
                "ended_at_utc": end_time,
            }
        )
    return items


def _token_usage_snapshot(db) -> dict[str, Any]:
    usage = get_openai_free_usage(db)
    return {
        "date_label": usage.date_label,
        "window_start_utc": usage.window_start_utc,
        "window_end_utc": usage.window_end_utc,
        "large": {
            "used_tokens": int(usage.large.used_tokens),
            "limit_tokens": int(usage.large.limit_tokens),
            "usage_percent": float(usage.large.usage_percent),
            "remaining_tokens": int(usage.large.remaining_tokens),
            "matched_models": list(usage.large.matched_models),
        },
        "small": {
            "used_tokens": int(usage.small.used_tokens),
            "limit_tokens": int(usage.small.limit_tokens),
            "usage_percent": float(usage.small.usage_percent),
            "remaining_tokens": int(usage.small.remaining_tokens),
            "matched_models": list(usage.small.matched_models),
        },
    }


def _status_from_payload(payload: dict[str, Any]) -> str:
    issues = 0
    token_error = _safe_text(payload.get("token_error"))
    if token_error:
        issues += 1

    failed_jobs = payload.get("failed_jobs_last_24h") or []
    if isinstance(failed_jobs, list) and failed_jobs:
        issues += 1

    sheet = payload.get("sheet_issues") or {}
    if isinstance(sheet, dict):
        if sheet.get("duplicates"):
            issues += 1
        if sheet.get("english_columns"):
            issues += 1

    recent_reports = payload.get("latest_cloudflare_reports") or []
    if isinstance(recent_reports, list):
        latest = next((item for item in recent_reports if isinstance(item, dict)), None)
        if isinstance(latest, dict) and _safe_text(latest.get("status")) in {"failed", "partial"}:
            issues += 1

    if issues == 0:
        return "ok"
    if issues == 1:
        return "warning"
    return "critical"


def _write_reports(payload: dict[str, Any]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"ops-health-{stamp}.json"
    md_path = REPORT_DIR / f"ops-health-{stamp}.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# ops-health")
    lines.append("")
    lines.append(f"- generated_at_kst: {payload['generated_at_kst']}")
    lines.append(f"- overall_status: {payload['overall_status']}")
    lines.append(f"- failed_jobs_last_24h: {len(payload['failed_jobs_last_24h'])}")
    lines.append(f"- cloudflare_recent_reports: {len(payload['latest_cloudflare_reports'])}")
    lines.append("")

    token = payload.get("token_usage")
    if isinstance(token, dict):
        large = token.get("large", {})
        small = token.get("small", {})
        lines.append("## Free Token Usage")
        lines.append("")
        lines.append(
            f"- large: {large.get('used_tokens', 0)} / {large.get('limit_tokens', 0)} ({large.get('usage_percent', 0)}%)"
        )
        lines.append(
            f"- small: {small.get('used_tokens', 0)} / {small.get('limit_tokens', 0)} ({small.get('usage_percent', 0)}%)"
        )
        lines.append("")
    else:
        lines.append("## Free Token Usage")
        lines.append("")
        lines.append(f"- error: {_safe_text(payload.get('token_error'))}")
        lines.append("")

    lines.append("## Sheet Issues")
    lines.append("")
    sheet = payload.get("sheet_issues") if isinstance(payload.get("sheet_issues"), dict) else {}
    duplicates = sheet.get("duplicates", []) if isinstance(sheet, dict) else []
    english = sheet.get("english_columns", []) if isinstance(sheet, dict) else []
    lines.append(f"- duplicate_headers: {len(duplicates)}")
    lines.append(f"- english_headers: {len(english)}")
    lines.append("")

    lines.append("## Recent Cloudflare Generate Reports")
    lines.append("")
    for item in payload.get("latest_cloudflare_reports", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('file')}: status={item.get('status')} created={item.get('created_count')} failed={item.get('failed_count')}"
        )
    if not payload.get("latest_cloudflare_reports"):
        lines.append("- none")
    lines.append("")

    lines.append("## Failed Jobs (Last 24h)")
    lines.append("")
    for item in payload.get("failed_jobs_last_24h", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- job={item.get('job_id')} blog={item.get('blog_slug')} ended={item.get('ended_at_utc')} keyword={item.get('keyword')}"
        )
    if not payload.get("failed_jobs_last_24h"):
        lines.append("- none")
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> None:
    payload: dict[str, Any] = {
        "generated_at_kst": _now_kst_iso(),
        "token_usage": None,
        "token_error": "",
        "failed_jobs_last_24h": [],
        "latest_cloudflare_reports": _latest_cloudflare_reports(limit=5),
        "sheet_issues": {},
        "overall_status": "unknown",
    }

    with SessionLocal() as db:
        try:
            payload["token_usage"] = _token_usage_snapshot(db)
        except Exception as exc:  # noqa: BLE001
            payload["token_error"] = _safe_text(exc)

        payload["failed_jobs_last_24h"] = _failed_jobs_last_hours(db, hours=24, limit=30)

        try:
            payload["sheet_issues"] = _sheet_issues(db)
        except Exception as exc:  # noqa: BLE001
            payload["sheet_issues"] = {"configured": True, "error": _safe_text(exc), "duplicates": [], "english_columns": []}

    payload["overall_status"] = _status_from_payload(payload)
    paths = _write_reports(payload)
    print(json.dumps({"status": payload["overall_status"], "report_paths": paths}, ensure_ascii=False))


if __name__ == "__main__":
    main()
