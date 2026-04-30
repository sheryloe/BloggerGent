from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
ROOL_ROOT = RUNTIME_ROOT / "Rool" / "30-cloudflare"
REPORT_ROOT = ROOL_ROOT / "08-reports"
P1_ROOT = ROOL_ROOT / "12-category-layout-refactor" / "p1-quality-80"
PACKET_ROOT = P1_ROOT / "packets"
RESULT_ROOT = P1_ROOT / "results"
APPLY_ROOT = P1_ROOT / "apply"

FORBIDDEN_BODY_TOKENS = (
    "<h1",
    "<script",
    "<iframe",
    "<img",
    "<figure",
    "adsbygoogle",
    "data-ad-client",
    "ca-pub-",
    "<!--ADSENSE",
    "[AD_SLOT",
)
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+")
CODE_BLOCK_RE = re.compile(r"```.*?```", re.S)


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
            if key and key not in os.environ:
                os.environ[key] = value
    os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@localhost:15432/bloggent")


_load_runtime_env()

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
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


def _latest_batch() -> Path:
    path = REPORT_ROOT / "cloudflare-p1-quality-refactor-batch-001-latest.csv"
    if path.exists():
        return path
    matches = sorted(REPORT_ROOT.glob("cloudflare-p1-quality-refactor-batch-001-*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError("P1 batch CSV not found.")
    return matches[0]


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _tag_names(detail: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for raw in detail.get("tagNames") or []:
        text = _safe_text(raw)
        if text and text not in values:
            values.append(text)
    for raw in detail.get("tags") or []:
        if isinstance(raw, dict):
            text = _safe_text(raw.get("name") or raw.get("label"))
        else:
            text = _safe_text(raw)
        if text and text not in values:
            values.append(text)
    return values[:20]


def _category_slug(detail: dict[str, Any], fallback: str) -> str:
    direct = _safe_text(detail.get("categorySlug"))
    if direct:
        return direct
    category = detail.get("category")
    if isinstance(category, dict):
        return _safe_text(category.get("slug") or category.get("categorySlug")) or fallback
    return fallback


def count_korean_syllables_for_body(text: str) -> int:
    stripped = CODE_BLOCK_RE.sub(" ", text or "")
    stripped = URL_RE.sub(" ", stripped)
    stripped = TAG_RE.sub(" ", stripped)
    return len(HANGUL_RE.findall(stripped))


def validate_result_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    body = _safe_text(payload.get("content") or payload.get("html_article") or payload.get("body_html"))
    title = _safe_text(payload.get("title"))
    excerpt = _safe_text(payload.get("excerpt"))
    seo_title = _safe_text(payload.get("seoTitle") or payload.get("seo_title"))
    seo_description = _safe_text(payload.get("seoDescription") or payload.get("seo_description"))
    if not title:
        errors.append("title_missing")
    if not body:
        errors.append("content_missing")
    if not excerpt:
        errors.append("excerpt_missing")
    if not seo_title:
        errors.append("seo_title_missing")
    if not seo_description:
        errors.append("seo_description_missing")
    lowered = body.lower()
    for token in FORBIDDEN_BODY_TOKENS:
        if token.lower() in lowered:
            errors.append(f"forbidden_token:{token}")
    korean_count = count_korean_syllables_for_body(body)
    if korean_count < 2000:
        errors.append(f"korean_syllable_count_below_2000:{korean_count}")
    return errors


def _packet_contract(row: dict[str, str], detail: dict[str, Any]) -> dict[str, Any]:
    category = _safe_text(row.get("category_slug"))
    return {
        "goal": "Raise SEO, GEO, and Lighthouse readiness to 80+ without changing topic, URL, category, or image.",
        "hard_constraints": [
            "Keep remote_post_id, slug, categorySlug, status, coverImage, coverAlt, and metadata unchanged.",
            "Rewrite only title, content, excerpt, seoTitle, seoDescription, and tagNames if needed.",
            "Pure Korean body syllable count must be at least 2000 after removing HTML, URLs, code, numbers, English, and spaces.",
            "Do not include h1, script, iframe, img, figure, markdown image, inline style, or AdSense tokens.",
            "Do not fabricate official facts, dates, places, prices, or sources.",
            "Preserve the original subject and factual direction.",
        ],
        "score_targets": {"seo": 80, "geo": 80, "lighthouse": 80},
        "category_slug": category,
        "current_scores": {
            "seo": row.get("seo_score"),
            "geo": row.get("geo_score"),
            "lighthouse": row.get("lighthouse_score"),
        },
        "expected_output_shape": {
            "title": "string",
            "content": "string",
            "excerpt": "string",
            "seoTitle": "string",
            "seoDescription": "string",
            "tagNames": ["string"],
        },
        "preserve": {
            "remote_post_id": row.get("remote_post_id"),
            "slug": row.get("slug"),
            "url": row.get("url"),
            "status": detail.get("status"),
            "categorySlug": _category_slug(detail, category),
            "coverImage": detail.get("coverImage"),
            "coverAlt": detail.get("coverAlt"),
            "metadata": detail.get("metadata"),
        },
    }


def prepare_packets() -> dict[str, Any]:
    batch_path = _latest_batch()
    rows = _read_csv(batch_path)
    PACKET_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for row in rows:
            remote_post_id = _safe_text(row.get("remote_post_id"))
            slug = _safe_text(row.get("slug"))
            try:
                if not remote_post_id and slug:
                    synced_post = (
                        db.query(SyncedCloudflarePost)
                        .filter(SyncedCloudflarePost.slug == slug)
                        .order_by(SyncedCloudflarePost.id.desc())
                        .first()
                    )
                    if synced_post is not None:
                        remote_post_id = _safe_text(synced_post.remote_post_id)
                        row["remote_post_id"] = remote_post_id
                if not remote_post_id:
                    raise RuntimeError("remote_post_id_missing")
                response = _integration_request(
                    db,
                    method="GET",
                    path=f"/api/integrations/posts/{remote_post_id}",
                    timeout=60.0,
                )
                detail = _integration_data_or_raise(response)
                if not isinstance(detail, dict):
                    raise RuntimeError("remote_detail_not_object")
                packet = {
                    "packet_id": f"p1-b001-{row.get('batch_order')}-{slug}",
                    "batch_id": row.get("batch_id") or "P1-B001",
                    "batch_order": row.get("batch_order"),
                    "source_row": row,
                    "remote_detail": {
                        "id": detail.get("id"),
                        "slug": detail.get("slug"),
                        "title": detail.get("title"),
                        "content": detail.get("content"),
                        "excerpt": detail.get("excerpt"),
                        "seoTitle": detail.get("seoTitle"),
                        "seoDescription": detail.get("seoDescription"),
                        "status": detail.get("status"),
                        "categorySlug": _category_slug(detail, _safe_text(row.get("category_slug"))),
                        "coverImage": detail.get("coverImage"),
                        "coverAlt": detail.get("coverAlt"),
                        "tagNames": _tag_names(detail),
                        "metadata": detail.get("metadata"),
                    },
                    "contract": _packet_contract(row, detail),
                }
                packet_path = PACKET_ROOT / f"{int(row.get('batch_order') or 0):02d}-{slug}.json"
                _write_json(packet_path, packet)
                manifest_rows.append(
                    {
                        "batch_order": row.get("batch_order"),
                        "remote_post_id": remote_post_id,
                        "category_slug": row.get("category_slug"),
                        "slug": slug,
                        "title": row.get("title"),
                        "url": row.get("url"),
                        "seo_score": row.get("seo_score"),
                        "geo_score": row.get("geo_score"),
                        "lighthouse_score": row.get("lighthouse_score"),
                        "packet_path": str(packet_path),
                        "status": "packet_ready",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "batch_order": row.get("batch_order"),
                        "remote_post_id": remote_post_id,
                        "slug": slug,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    stamp = _stamp()
    manifest_path = P1_ROOT / f"p1-packet-manifest-{stamp}.csv"
    _write_csv(manifest_path, manifest_rows)
    _write_csv(P1_ROOT / "p1-packet-manifest-latest.csv", manifest_rows)
    if failures:
        _write_csv(P1_ROOT / f"p1-packet-failures-{stamp}.csv", failures)
        _write_csv(P1_ROOT / "p1-packet-failures-latest.csv", failures)
    summary = {
        "mode": "prepare_packets",
        "created_at": datetime.now().isoformat(),
        "source_batch": str(batch_path),
        "packet_count": len(manifest_rows),
        "failure_count": len(failures),
        "packet_root": str(PACKET_ROOT),
        "manifest": str(manifest_path),
    }
    _write_json(P1_ROOT / f"p1-packet-summary-{stamp}.json", summary)
    _write_json(P1_ROOT / "p1-packet-summary-latest.json", summary)
    return summary


def validate_results() -> dict[str, Any]:
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    result_files = sorted(RESULT_ROOT.glob("*.json"))
    rows: list[dict[str, Any]] = []
    ok_count = 0
    for path in result_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            errors = validate_result_payload(payload)
            status = "ok" if not errors else "failed"
            if status == "ok":
                ok_count += 1
            rows.append({"result_path": str(path), "status": status, "errors": ";".join(errors)})
        except Exception as exc:  # noqa: BLE001
            rows.append({"result_path": str(path), "status": "failed", "errors": f"{type(exc).__name__}: {exc}"})
    stamp = _stamp()
    report_path = P1_ROOT / f"p1-result-validation-{stamp}.csv"
    _write_csv(report_path, rows)
    _write_csv(P1_ROOT / "p1-result-validation-latest.csv", rows)
    summary = {
        "mode": "validate_results",
        "created_at": datetime.now().isoformat(),
        "result_count": len(result_files),
        "ok_count": ok_count,
        "failed_count": len(rows) - ok_count,
        "report": str(report_path),
    }
    _write_json(P1_ROOT / f"p1-result-validation-{stamp}.json", summary)
    _write_json(P1_ROOT / "p1-result-validation-latest.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Cloudflare P1 quality refactor packets.")
    parser.add_argument("--mode", choices=["prepare_packets", "validate_results"], required=True)
    args = parser.parse_args()
    if args.mode == "prepare_packets":
        result = prepare_packets()
    else:
        result = validate_results()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
