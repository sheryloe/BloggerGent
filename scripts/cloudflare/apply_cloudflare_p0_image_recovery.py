from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
ROOL_ROOT = RUNTIME_ROOT / "Rool" / "30-cloudflare"
RECOVERY_ROOT = ROOL_ROOT / "13-codex-imagegen-recovery"
QUEUE_PATH = RECOVERY_ROOT / "02-generation-queue" / "p0-imagegen-queue-latest.csv"
BACKUP_LOG_ROOT = RUNTIME_ROOT / "backup" / "작업log"
BACKUP_TASK_LABEL = "클라우드 이미지 복구"
REPORT_ROOT = ROOL_ROOT / "08-reports"
LIVE_AUDIT_ROOT = ROOL_ROOT / "10-live-health-audit"

TARGET_SIZE = (1600, 900)
REQUEST_TIMEOUT = 30


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
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.integrations.storage_service import upload_binary_to_cloudflare_r2  # noqa: E402


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _backup_dir() -> Path:
    path = BACKUP_LOG_ROOT / _today() / BACKUP_TASK_LABEL
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def _queue_rows() -> list[dict[str, str]]:
    rows = _read_csv(QUEUE_PATH)
    if len(rows) != 2:
        raise RuntimeError(f"P0 queue must contain exactly 2 rows; actual={len(rows)}")
    return rows


def _latest_file(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _check_image_url(url: str) -> tuple[bool, int | None, str, str]:
    session = requests.Session()
    session.headers.update({"User-Agent": "BloggerGent-P0-ImageRecovery/2026.04"})
    try:
        response = session.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
        content_type = (response.headers.get("content-type") or "").split(";")[0].lower().strip()
        if response.status_code in {403, 404, 405, 500} or not content_type.startswith("image/"):
            response = session.get(url, stream=True, allow_redirects=True, timeout=REQUEST_TIMEOUT)
            content_type = (response.headers.get("content-type") or "").split(";")[0].lower().strip()
        ok = 200 <= response.status_code < 400 and content_type.startswith("image/")
        error = "" if ok else f"http_{response.status_code}_content_type_{content_type or 'empty'}"
        response.close()
        return ok, response.status_code, content_type, error
    except Exception as exc:  # noqa: BLE001
        return False, None, "", f"{type(exc).__name__}: {str(exc)[:180]}"


def _validate_r2_key(row: dict[str, str]) -> None:
    key = str(row.get("r2_key") or "")
    leaf = str(row.get("category_leaf") or "")
    slug = str(row.get("slug") or "")
    expected_suffix = f"/{slug}/{slug}.webp"
    if not key.startswith(f"assets/media/cloudflare/dongri-archive/{leaf}/"):
        raise ValueError(f"Invalid R2 key prefix for {slug}: {key}")
    if not key.endswith(expected_suffix):
        raise ValueError(f"Invalid R2 key suffix for {slug}: {key}")


def verify_inputs() -> dict[str, Any]:
    rows = _queue_rows()
    results: list[dict[str, Any]] = []
    ok_count = 0
    for row in rows:
        result = dict(row)
        errors: list[str] = []
        try:
            _validate_r2_key(row)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        png_path = Path(row["png_path"])
        if not png_path.exists():
            errors.append(f"png_missing={png_path}")
        else:
            try:
                with Image.open(png_path) as image:
                    result["png_width"] = image.width
                    result["png_height"] = image.height
                    result["png_mode"] = image.mode
            except Exception as exc:  # noqa: BLE001
                errors.append(f"png_unreadable={type(exc).__name__}: {exc}")
        result["input_status"] = "ok" if not errors else "failed"
        result["error"] = "; ".join(errors)
        if not errors:
            ok_count += 1
        results.append(result)

    stamp = _stamp()
    out_csv = RECOVERY_ROOT / "01-input-audit" / f"p0-verify-inputs-{stamp}.csv"
    out_json = RECOVERY_ROOT / "01-input-audit" / f"p0-verify-inputs-{stamp}.json"
    _write_csv(out_csv, results)
    summary = {
        "mode": "verify_inputs",
        "created_at": datetime.now().isoformat(),
        "queue": str(QUEUE_PATH),
        "ok_count": ok_count,
        "failed_count": len(results) - ok_count,
        "csv": str(out_csv),
    }
    _write_json(out_json, {**summary, "rows": results})
    _write_json(RECOVERY_ROOT / "01-input-audit" / "p0-verify-inputs-latest.json", {**summary, "rows": results})
    return summary


def convert_webp() -> dict[str, Any]:
    rows = _queue_rows()
    results: list[dict[str, Any]] = []
    ok_count = 0
    for row in rows:
        result = dict(row)
        png_path = Path(row["png_path"])
        webp_path = Path(row["webp_path"])
        try:
            _validate_r2_key(row)
            if not png_path.exists():
                raise FileNotFoundError(f"PNG missing: {png_path}")
            webp_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(png_path) as image:
                converted = ImageOps.fit(image.convert("RGB"), TARGET_SIZE, method=Image.Resampling.LANCZOS)
                converted.save(webp_path, format="WEBP", quality=88, optimize=True, method=6)
            with Image.open(webp_path) as image:
                result["webp_width"] = image.width
                result["webp_height"] = image.height
                result["webp_format"] = image.format
            result["convert_status"] = "ok"
            result["error"] = ""
            ok_count += 1
        except Exception as exc:  # noqa: BLE001
            result["convert_status"] = "failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)

    stamp = _stamp()
    out_csv = RECOVERY_ROOT / "04-webp" / f"p0-convert-webp-{stamp}.csv"
    out_json = RECOVERY_ROOT / "04-webp" / f"p0-convert-webp-{stamp}.json"
    _write_csv(out_csv, results)
    summary = {
        "mode": "convert_webp",
        "created_at": datetime.now().isoformat(),
        "ok_count": ok_count,
        "failed_count": len(results) - ok_count,
        "csv": str(out_csv),
    }
    _write_json(out_json, {**summary, "rows": results})
    _write_json(RECOVERY_ROOT / "04-webp" / "p0-convert-webp-latest.json", {**summary, "rows": results})
    return summary


def upload_verify() -> dict[str, Any]:
    rows = _queue_rows()
    results: list[dict[str, Any]] = []
    ok_count = 0
    with SessionLocal() as db:
        for row in rows:
            result = dict(row)
            webp_path = Path(row["webp_path"])
            try:
                _validate_r2_key(row)
                if not webp_path.exists():
                    raise FileNotFoundError(f"WebP missing: {webp_path}")
                public_url, upload_payload, delivery_meta = upload_binary_to_cloudflare_r2(
                    db,
                    object_key=row["r2_key"],
                    filename=webp_path.name,
                    content=webp_path.read_bytes(),
                    force_integration_proxy=True,
                )
                expected_url = row["public_url"].strip()
                returned_key = str(upload_payload.get("object_key") or "").strip()
                if returned_key != row["r2_key"]:
                    raise RuntimeError(f"Uploaded object key mismatch: expected={row['r2_key']} actual={returned_key}")
                if public_url.rstrip("/") != expected_url.rstrip("/"):
                    raise RuntimeError(f"Public URL mismatch: expected={expected_url} actual={public_url}")
                ok, status, content_type, error = _check_image_url(expected_url)
                result.update(
                    {
                        "returned_public_url": public_url,
                        "returned_object_key": returned_key,
                        "http_status": status or "",
                        "content_type": content_type,
                        "upload_payload_json": json.dumps(upload_payload, ensure_ascii=False, default=str),
                        "delivery_meta_json": json.dumps(delivery_meta, ensure_ascii=False, default=str),
                    }
                )
                if not ok:
                    raise RuntimeError(f"public_url_verify_failed={error}")
                result["r2_upload_status"] = "ok"
                result["verify_status"] = "ok"
                result["error"] = ""
                ok_count += 1
            except Exception as exc:  # noqa: BLE001
                result["r2_upload_status"] = "failed"
                result["verify_status"] = "failed"
                result["error"] = f"{type(exc).__name__}: {exc}"
            results.append(result)

    stamp = _stamp()
    out_csv = RECOVERY_ROOT / "05-r2-upload" / f"p0-upload-verify-{stamp}.csv"
    out_json = RECOVERY_ROOT / "05-r2-upload" / f"p0-upload-verify-{stamp}.json"
    _write_csv(out_csv, results)
    _write_csv(RECOVERY_ROOT / "05-r2-upload" / "p0-upload-verify-latest.csv", results)
    summary = {
        "mode": "upload_verify",
        "created_at": datetime.now().isoformat(),
        "ok_count": ok_count,
        "failed_count": len(results) - ok_count,
        "csv": str(out_csv),
    }
    _write_json(out_json, {**summary, "rows": results})
    _write_json(RECOVERY_ROOT / "05-r2-upload" / "p0-upload-verify-latest.json", {**summary, "rows": results})
    return summary


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


def _category_slug(detail: dict[str, Any]) -> str:
    direct = _safe_text(detail.get("categorySlug"))
    if direct:
        return direct
    category = detail.get("category")
    if isinstance(category, dict):
        return _safe_text(category.get("slug") or category.get("categorySlug"))
    return ""


def _build_cover_update_payload(detail: dict[str, Any], cover_image: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": _safe_text(detail.get("title")),
        "content": _safe_text(detail.get("content")),
        "excerpt": _safe_text(detail.get("excerpt")),
        "seoTitle": _safe_text(detail.get("seoTitle")),
        "seoDescription": _safe_text(detail.get("seoDescription")),
        "tagNames": _tag_names(detail),
        "status": _safe_text(detail.get("status")) or "published",
        "coverImage": cover_image,
    }
    category_slug = _category_slug(detail)
    if category_slug:
        payload["categorySlug"] = category_slug
    cover_alt = _safe_text(detail.get("coverAlt"))
    if cover_alt:
        payload["coverAlt"] = cover_alt
    metadata = detail.get("metadata")
    if isinstance(metadata, dict) and metadata:
        payload["metadata"] = metadata
    return payload


def apply_live() -> dict[str, Any]:
    upload_path = RECOVERY_ROOT / "05-r2-upload" / "p0-upload-verify-latest.csv"
    if not upload_path.exists():
        raise FileNotFoundError(f"Upload verification report not found: {upload_path}")
    upload_rows = _read_csv(upload_path)
    results: list[dict[str, Any]] = []
    ok_count = 0
    with SessionLocal() as db:
        for row in upload_rows:
            result = dict(row)
            try:
                if row.get("verify_status") != "ok":
                    raise RuntimeError("verify_status is not ok")
                remote_post_id = _safe_text(row.get("remote_post_id"))
                public_url = _safe_text(row.get("public_url"))
                response = _integration_request(
                    db,
                    method="GET",
                    path=f"/api/integrations/posts/{remote_post_id}",
                    timeout=60.0,
                )
                detail = _integration_data_or_raise(response)
                if not isinstance(detail, dict):
                    raise RuntimeError("Remote detail payload is not an object")
                payload = _build_cover_update_payload(detail, public_url)
                response = _integration_request(
                    db,
                    method="PUT",
                    path=f"/api/integrations/posts/{remote_post_id}",
                    json_payload=payload,
                    timeout=120.0,
                )
                data = _integration_data_or_raise(response)
                post = (
                    db.query(SyncedCloudflarePost)
                    .filter(SyncedCloudflarePost.remote_post_id == remote_post_id)
                    .one_or_none()
                )
                if post is not None:
                    post.thumbnail_url = public_url
                db.commit()
                result["apply_status"] = "ok"
                result["http_status"] = response.status_code
                result["response_json"] = json.dumps(data, ensure_ascii=False, default=str)
                result["error"] = ""
                ok_count += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                result["apply_status"] = "failed"
                result["error"] = f"{type(exc).__name__}: {exc}"
            results.append(result)

    stamp = _stamp()
    out_csv = RECOVERY_ROOT / "06-live-apply" / f"p0-live-apply-{stamp}.csv"
    out_json = RECOVERY_ROOT / "06-live-apply" / f"p0-live-apply-{stamp}.json"
    _write_csv(out_csv, results)
    _write_csv(RECOVERY_ROOT / "06-live-apply" / "p0-live-apply-latest.csv", results)
    summary = {
        "mode": "apply_live",
        "created_at": datetime.now().isoformat(),
        "ok_count": ok_count,
        "failed_count": len(results) - ok_count,
        "csv": str(out_csv),
    }
    _write_json(out_json, {**summary, "rows": results})
    _write_json(RECOVERY_ROOT / "06-live-apply" / "p0-live-apply-latest.json", {**summary, "rows": results})
    return summary


def _run_command(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=900,
    )
    return {
        "args": args,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def reaudit() -> dict[str, Any]:
    command_results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        sync_result = sync_cloudflare_posts(db, include_non_published=True)
    cleanup_script = REPO_ROOT / "scripts" / "cloudflare" / "cloudflare_live_integrity_cleanup.py"
    command_results.append(_run_command([sys.executable, str(cleanup_script), "--mode", "dry_run"]))
    command_results.append(_run_command([sys.executable, str(cleanup_script), "--mode", "execute_db_health_sync"]))

    broken_path = LIVE_AUDIT_ROOT / "actual_broken_image_latest.csv"
    fallback_path = LIVE_AUDIT_ROOT / "fallback_placeholder_latest.csv"
    broken_count = len(_read_csv(broken_path)) if broken_path.exists() else 0
    fallback_count = len(_read_csv(fallback_path)) if fallback_path.exists() else 0
    summary = {
        "mode": "reaudit",
        "created_at": datetime.now().isoformat(),
        "sync_result": sync_result,
        "broken_count": broken_count,
        "fallback_placeholder_count": fallback_count,
        "commands": command_results,
        "complete": broken_count == 0 and fallback_count == 0,
    }
    stamp = _stamp()
    _write_json(RECOVERY_ROOT / "07-verify" / f"p0-reaudit-{stamp}.json", summary)
    _write_json(RECOVERY_ROOT / "07-verify" / "p0-reaudit-latest.json", summary)
    return summary


def archive_completed() -> dict[str, Any]:
    latest = RECOVERY_ROOT / "07-verify" / "p0-reaudit-latest.json"
    if not latest.exists():
        raise FileNotFoundError(f"Reaudit summary not found: {latest}")
    summary = json.loads(latest.read_text(encoding="utf-8"))
    if not summary.get("complete"):
        result = {
            "mode": "archive_completed",
            "created_at": datetime.now().isoformat(),
            "archived": False,
            "reason": "P0 is not complete; active files were not removed.",
            "reaudit_summary": str(latest),
        }
        _write_json(RECOVERY_ROOT / "08-completed" / "p0-archive-latest.json", result)
        return result

    backup_dir = _backup_dir()
    copied: list[dict[str, str]] = []
    moved: list[dict[str, str]] = []
    patterns = [
        (RECOVERY_ROOT / "02-generation-queue", "p0-imagegen-queue*.csv", True),
        (RECOVERY_ROOT / "02-generation-queue", "p0-remediation-plan*.json", True),
        (RECOVERY_ROOT / "02-generation-queue" / "p0-imagegen-prompts", "*.md", True),
        (RECOVERY_ROOT / "01-input-audit", "p0-verify-inputs*.json", True),
        (RECOVERY_ROOT / "01-input-audit", "p0-verify-inputs*.csv", True),
        (RECOVERY_ROOT / "04-webp", "p0-convert-webp*.json", True),
        (RECOVERY_ROOT / "04-webp", "p0-convert-webp*.csv", True),
        (RECOVERY_ROOT / "05-r2-upload", "p0-upload-verify*.json", True),
        (RECOVERY_ROOT / "05-r2-upload", "p0-upload-verify*.csv", True),
        (RECOVERY_ROOT / "06-live-apply", "p0-live-apply*.json", True),
        (RECOVERY_ROOT / "06-live-apply", "p0-live-apply*.csv", True),
        (RECOVERY_ROOT / "07-verify", "p0-reaudit*.json", True),
    ]
    for root, pattern, remove_after_copy in patterns:
        for src in root.glob(pattern):
            if not src.is_file():
                continue
            rel = src.relative_to(RECOVERY_ROOT)
            dst = backup_dir / "p0-artifacts" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append({"source": str(src), "backup": str(dst)})
            if remove_after_copy:
                src.unlink()
                moved.append({"removed_active": str(src), "backup": str(dst)})

    for asset_dir in [RECOVERY_ROOT / "03-generated-png", RECOVERY_ROOT / "04-webp"]:
        if asset_dir.exists():
            dst_root = backup_dir / "p0-assets-copy" / asset_dir.name
            shutil.copytree(asset_dir, dst_root, dirs_exist_ok=True)
            copied.append({"source": str(asset_dir), "backup": str(dst_root)})

    result = {
        "mode": "archive_completed",
        "created_at": datetime.now().isoformat(),
        "archived": True,
        "backup_dir": str(backup_dir),
        "copied": copied,
        "moved": moved,
    }
    _write_json(RECOVERY_ROOT / "08-completed" / "p0-archive-latest.json", result)
    _write_json(backup_dir / "p0-archive-summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Cloudflare P0 image recovery.")
    parser.add_argument(
        "--mode",
        required=True,
        choices=[
            "verify_inputs",
            "convert_webp",
            "upload_verify",
            "apply_live",
            "reaudit",
            "archive_completed",
        ],
    )
    args = parser.parse_args()
    handler = {
        "verify_inputs": verify_inputs,
        "convert_webp": convert_webp,
        "upload_verify": upload_verify,
        "apply_live": apply_live,
        "reaudit": reaudit,
        "archive_completed": archive_completed,
    }[args.mode]
    result = handler()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
