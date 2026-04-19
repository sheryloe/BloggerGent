from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")

PROFILE_PRIMARY_CATEGORY: dict[str, str] = {
    "tech": "개발과-프로그래밍",
    "travel": "여행과-기록",
    "finance": "주식의-흐름",
    "mystery": "미스테리아-스토리",
    "daily": "일상과-메모",
}


def _bootstrap_local_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        existing = os.environ.get(key)
        if existing is not None and existing.strip():
            continue
        os.environ[key] = value.strip()


_bootstrap_local_runtime_env()
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", "bloggent-dockerdesktop-2026-03-17")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ManagedChannel  # noqa: E402
from app.services.cloudflare.cloudflare_asset_policy import (  # noqa: E402
    CLOUDFLARE_MANAGED_CHANNEL_ID,
    get_cloudflare_asset_policy,
)
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
    _prepare_markdown_body,
)
from app.services.cloudflare.cloudflare_post_dedupe_service import dedupe_cloudflare_posts  # noqa: E402
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize Cloudflare category-audit approval rows.")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--mode", default="dry_run", choices=("dry_run", "execute"))
    parser.add_argument("--channel-id", default=CLOUDFLARE_MANAGED_CHANNEL_ID)
    parser.add_argument("--delete-scope", default="remote_and_synced", choices=("remote_and_synced", "synced_only"))
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument(
        "--input",
        default="",
        help="Override approval CSV path. Default: cloudflare-category-audit-approval-<date>.csv in report root.",
    )
    return parser.parse_args()


def _parse_int(value: Any, default: int = 0) -> int:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _compact_api_result(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    if len(text) > 2000:
        return text[:2000] + "..."
    return text


def _is_valid_category(category_slug: str, valid_categories: set[str]) -> bool:
    normalized = _safe_text(category_slug)
    return bool(normalized) and normalized in valid_categories


def _build_move_payload(detail: dict[str, Any], source_row: dict[str, str], target_category_slug: str) -> dict[str, Any]:
    title = _safe_text(detail.get("title") or source_row.get("title") or source_row.get("slug") or "Untitled") or "Untitled"
    raw_body = _safe_text(detail.get("contentMarkdown") or detail.get("content") or detail.get("markdown"))
    content = _prepare_markdown_body(title, raw_body)

    excerpt = _safe_text(detail.get("excerpt") or source_row.get("title"))
    seo_title = _safe_text(detail.get("seoTitle") or title) or title
    seo_description = _safe_text(detail.get("seoDescription") or excerpt or title) or title
    status = _safe_text(detail.get("status") or "published") or "published"

    tag_names: list[str] = []
    for raw in detail.get("tagNames") or []:
        tag = _safe_text(raw)
        if tag and tag not in tag_names:
            tag_names.append(tag)
    if not tag_names:
        for raw in detail.get("tags") or []:
            if isinstance(raw, dict):
                tag = _safe_text(raw.get("name") or raw.get("label"))
            else:
                tag = _safe_text(raw)
            if tag and tag not in tag_names:
                tag_names.append(tag)

    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "excerpt": excerpt,
        "seoTitle": seo_title,
        "seoDescription": seo_description,
        "tagNames": tag_names[:20],
        "status": status,
        "categorySlug": target_category_slug,
    }

    cover_image = _safe_text(detail.get("coverImage"))
    cover_alt = _safe_text(detail.get("coverAlt"))
    if cover_image:
        payload["coverImage"] = cover_image
    if cover_alt:
        payload["coverAlt"] = cover_alt

    metadata = detail.get("metadata")
    if isinstance(metadata, dict) and metadata:
        payload["metadata"] = metadata
    return payload


def _determine_final_decision(row: dict[str, str], valid_categories: set[str]) -> tuple[str, str, str]:
    recommended_action = _safe_text(row.get("recommended_action")).lower()
    recommended_target = _safe_text(row.get("recommended_target_category_slug"))
    reason_code = _safe_text(row.get("reason_code")).lower()

    expected_score = _parse_int(row.get("expected_score"), default=0)
    predicted_score = _parse_int(row.get("predicted_score"), default=0)
    predicted_profile = _safe_text(row.get("predicted_profile")).lower()
    predicted_target = PROFILE_PRIMARY_CATEGORY.get(predicted_profile, "")

    if recommended_action == "move" and _is_valid_category(recommended_target, valid_categories):
        return "move", recommended_target, "recommended_move_valid_target"

    if reason_code == "forbidden_token_hit" and not _is_valid_category(predicted_target, valid_categories):
        return "remove", "", "forbidden_token_hit_without_valid_target"

    if expected_score >= predicted_score:
        return "keep", "", "expected_score_ge_predicted_score"

    if predicted_score >= 2 and _is_valid_category(predicted_target, valid_categories):
        return "move", predicted_target, "predicted_profile_valid_target"

    return "remove", "", "insufficient_category_evidence"


def _fetch_integration_post_detail(db, remote_post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{remote_post_id}",
        timeout=60.0,
    )
    data = _integration_data_or_raise(response)
    if not isinstance(data, dict):
        raise ValueError("Integration detail payload is not an object.")
    return data


def _execute_move(db, row: dict[str, str], target_category_slug: str) -> dict[str, Any]:
    remote_post_id = _safe_text(row.get("remote_post_id"))
    if not remote_post_id:
        raise ValueError("remote_post_id is required for move action.")

    detail = _fetch_integration_post_detail(db, remote_post_id)
    payload = _build_move_payload(detail, row, target_category_slug)
    response = _integration_request(
        db,
        method="PUT",
        path=f"/api/integrations/posts/{remote_post_id}",
        json_payload=payload,
        timeout=120.0,
    )
    data = _integration_data_or_raise(response)
    return {
        "http_status": response.status_code,
        "response": data if isinstance(data, dict) else {"value": data},
    }


def _execute_archive(db, row: dict[str, str]) -> dict[str, Any]:
    remote_post_id = _safe_text(row.get("remote_post_id"))
    if not remote_post_id:
        raise ValueError("remote_post_id is required for archive action.")

    response = _integration_request(
        db,
        method="PUT",
        path=f"/api/integrations/posts/{remote_post_id}",
        json_payload={"status": "archived"},
        timeout=60.0,
    )
    data = _integration_data_or_raise(response)
    return {
        "http_status": response.status_code,
        "response": data if isinstance(data, dict) else {"value": data},
    }


def _verify_remote_post_archived(db, remote_post_id: str) -> tuple[bool, str]:
    detail = _fetch_integration_post_detail(db, remote_post_id)
    status = _safe_text(detail.get("status")).lower()
    return status == "archived", status


def _validate_input_rows(rows: list[dict[str, str]]) -> None:
    remote_ids = [_safe_text(row.get("remote_post_id")) for row in rows if _safe_text(row.get("remote_post_id"))]
    duplicates = sorted([remote_id for remote_id, count in Counter(remote_ids).items() if count > 1])
    if duplicates:
        raise ValueError(f"Duplicate remote_post_id found in input: {', '.join(duplicates)}")


def main() -> int:
    args = parse_args()
    mode = _safe_text(args.mode).lower() or "dry_run"
    report_root = Path(args.report_root).resolve()
    report_root.mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input).resolve() if _safe_text(args.input) else report_root / f"cloudflare-category-audit-approval-{args.date}.csv"
    if not input_path.exists():
        raise FileNotFoundError(f"Approval CSV not found: {input_path}")

    input_rows = _read_csv(input_path)
    if not input_rows:
        raise RuntimeError(f"Approval CSV is empty: {input_path}")
    _validate_input_rows(input_rows)

    finalized_rows: list[dict[str, Any]] = []
    move_success_count = 0
    move_failed_count = 0
    archive_success_count = 0
    archive_failed_count = 0
    verify_archived_count = 0
    verify_failed_count = 0
    dedupe_archive_target_count = 0
    dedupe_archive_success_count = 0
    dedupe_archive_failed_count = 0
    dedupe_verify_archived_count = 0
    dedupe_verify_failed_count = 0

    sync_result: dict[str, Any] | None = None
    dedupe_result: dict[str, Any] | None = None

    with SessionLocal() as db:
        channel = db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == args.channel_id)).scalar_one_or_none()
        if channel is None or _safe_text(channel.provider).lower() != "cloudflare":
            raise ValueError(f"Cloudflare channel not found: {args.channel_id}")
        policy = get_cloudflare_asset_policy(channel)
        valid_categories = set(policy.allowed_category_slugs)

        for row in input_rows:
            final_action, target_category, decision_reason = _determine_final_decision(row, valid_categories)
            current_category = _safe_text(row.get("category_slug"))
            item: dict[str, Any] = {
                "remote_post_id": _safe_text(row.get("remote_post_id")),
                "slug": _safe_text(row.get("slug")),
                "title": _safe_text(row.get("title")),
                "published_at": _safe_text(row.get("published_at")),
                "current_category": current_category,
                "final_action": final_action,
                "target_category": target_category,
                "reason": decision_reason,
                "expected_profile": _safe_text(row.get("expected_profile")),
                "predicted_profile": _safe_text(row.get("predicted_profile")),
                "expected_score": _parse_int(row.get("expected_score")),
                "predicted_score": _parse_int(row.get("predicted_score")),
                "recommended_action": _safe_text(row.get("recommended_action")),
                "recommended_target_category": _safe_text(row.get("recommended_target_category_slug")),
                "reason_code": _safe_text(row.get("reason_code")),
                "api_result": "",
                "error": "",
                "verified_status": "",
                "archive_verified": "",
            }

            if mode == "execute":
                try:
                    if final_action == "move":
                        result = _execute_move(db, row, target_category)
                        item["api_result"] = _compact_api_result(result)
                        move_success_count += 1
                    elif final_action == "remove":
                        result = _execute_archive(db, row)
                        item["api_result"] = _compact_api_result(result)
                        archive_success_count += 1
                except Exception as exc:  # noqa: BLE001
                    item["error"] = str(exc)
                    if final_action == "move":
                        move_failed_count += 1
                    elif final_action == "remove":
                        archive_failed_count += 1

                if final_action == "remove":
                    remote_post_id = _safe_text(row.get("remote_post_id"))
                    if remote_post_id:
                        try:
                            archived, current_status = _verify_remote_post_archived(db, remote_post_id)
                            item["verified_status"] = current_status
                            item["archive_verified"] = "true" if archived else "false"
                            if archived:
                                verify_archived_count += 1
                            else:
                                verify_failed_count += 1
                                if not item["error"]:
                                    item["error"] = f"Archive verify failed: status={current_status or 'unknown'}"
                        except Exception as exc:  # noqa: BLE001
                            verify_failed_count += 1
                            item["archive_verified"] = "false"
                            if not item["error"]:
                                item["error"] = f"Archive verify failed: {exc}"

            finalized_rows.append(item)

        if mode == "execute":
            sync_cloudflare_posts(db, include_non_published=True)
            dedupe_result = dedupe_cloudflare_posts(
                db,
                mode="dry_run",
                channel_id=args.channel_id,
                delete_scope=args.delete_scope,
                keep_rule="latest_published",
            )
            dedupe_candidates = dedupe_result.get("delete_candidates") or []
            dedupe_archive_target_count = len(dedupe_candidates)
            dedupe_archive_items: list[dict[str, Any]] = []

            for candidate in dedupe_candidates:
                remote_post_id = _safe_text(candidate.get("remote_post_id"))
                if not remote_post_id:
                    continue
                dedupe_item = {
                    "remote_post_id": remote_post_id,
                    "slug": _safe_text(candidate.get("slug")),
                    "category_slug": _safe_text(candidate.get("category_slug")),
                    "api_result": "",
                    "archive_verified": "",
                    "verified_status": "",
                    "error": "",
                }
                try:
                    result = _execute_archive(db, {"remote_post_id": remote_post_id})
                    dedupe_item["api_result"] = _compact_api_result(result)
                    dedupe_archive_success_count += 1
                except Exception as exc:  # noqa: BLE001
                    dedupe_item["error"] = str(exc)
                    dedupe_archive_failed_count += 1

                try:
                    archived, current_status = _verify_remote_post_archived(db, remote_post_id)
                    dedupe_item["verified_status"] = current_status
                    dedupe_item["archive_verified"] = "true" if archived else "false"
                    if archived:
                        dedupe_verify_archived_count += 1
                    else:
                        dedupe_verify_failed_count += 1
                        if not dedupe_item["error"]:
                            dedupe_item["error"] = f"Dedupe archive verify failed: status={current_status or 'unknown'}"
                except Exception as exc:  # noqa: BLE001
                    dedupe_verify_failed_count += 1
                    dedupe_item["archive_verified"] = "false"
                    if not dedupe_item["error"]:
                        dedupe_item["error"] = f"Dedupe archive verify failed: {exc}"

                dedupe_archive_items.append(dedupe_item)

            sync_result = sync_cloudflare_posts(db, include_non_published=True)
            dedupe_result["archive_phase"] = {
                "archive_target_count": dedupe_archive_target_count,
                "archive_success_count": dedupe_archive_success_count,
                "archive_failed_count": dedupe_archive_failed_count,
                "verify_archived_count": dedupe_verify_archived_count,
                "verify_failed_count": dedupe_verify_failed_count,
                "items": dedupe_archive_items,
            }

    action_counts = Counter(_safe_text(row.get("final_action")) for row in finalized_rows)
    execute_error_count = (
        sum(1 for row in finalized_rows if _safe_text(row.get("error")))
        + dedupe_archive_failed_count
        + dedupe_verify_failed_count
    )

    if mode == "execute":
        if execute_error_count == 0:
            status = "ok"
        elif move_success_count + archive_success_count > 0:
            status = "partial"
        else:
            status = "failed"
    else:
        status = "ok"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    json_path = report_root / f"cloudflare-category-audit-finalize-{timestamp}.json"
    csv_path = report_root / f"cloudflare-category-audit-finalize-{timestamp}.csv"

    report = {
        "status": status,
        "mode": mode,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "channel_id": args.channel_id,
        "delete_scope": args.delete_scope,
        "input_path": str(input_path),
        "report_root": str(report_root),
        "input_total": len(input_rows),
        "keep_count": int(action_counts.get("keep", 0)),
        "move_count": int(action_counts.get("move", 0)),
        "remove_count": int(action_counts.get("remove", 0)),
        "move_success_count": move_success_count,
        "move_failed_count": move_failed_count,
        "archive_success_count": archive_success_count,
        "archive_failed_count": archive_failed_count,
        "verify_archived_count": verify_archived_count,
        "verify_failed_count": verify_failed_count,
        "dedupe_archive_target_count": dedupe_archive_target_count,
        "dedupe_archive_success_count": dedupe_archive_success_count,
        "dedupe_archive_failed_count": dedupe_archive_failed_count,
        "dedupe_verify_archived_count": dedupe_verify_archived_count,
        "dedupe_verify_failed_count": dedupe_verify_failed_count,
        "archive_total_target_count": int(action_counts.get("remove", 0)) + dedupe_archive_target_count,
        "archive_total_success_count": archive_success_count + dedupe_archive_success_count,
        "archive_total_failed_count": archive_failed_count + dedupe_archive_failed_count,
        "verify_total_archived_count": verify_archived_count + dedupe_verify_archived_count,
        "verify_total_failed_count": verify_failed_count + dedupe_verify_failed_count,
        # Backward compatibility with existing report consumers.
        "remove_success_count": archive_success_count,
        "remove_failed_count": archive_failed_count,
        "execute_error_count": execute_error_count,
        "sync_result": sync_result,
        "dedupe_result": dedupe_result,
        "items": finalized_rows,
    }

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    _write_csv(
        csv_path,
        finalized_rows,
        [
            "remote_post_id",
            "slug",
            "current_category",
            "final_action",
            "target_category",
            "reason",
            "api_result",
            "archive_verified",
            "verified_status",
            "error",
            "title",
            "published_at",
            "expected_profile",
            "predicted_profile",
            "expected_score",
            "predicted_score",
            "recommended_action",
            "recommended_target_category",
            "reason_code",
        ],
    )

    print(
        json.dumps(
            {
                "status": status,
                "mode": mode,
                "channel_id": args.channel_id,
                "input_total": len(input_rows),
                "keep_count": int(action_counts.get("keep", 0)),
                "move_count": int(action_counts.get("move", 0)),
                "remove_count": int(action_counts.get("remove", 0)),
                "move_success_count": move_success_count,
                "move_failed_count": move_failed_count,
                "archive_success_count": archive_success_count,
                "archive_failed_count": archive_failed_count,
                "verify_archived_count": verify_archived_count,
                "verify_failed_count": verify_failed_count,
                "dedupe_archive_target_count": dedupe_archive_target_count,
                "dedupe_archive_success_count": dedupe_archive_success_count,
                "dedupe_archive_failed_count": dedupe_archive_failed_count,
                "dedupe_verify_archived_count": dedupe_verify_archived_count,
                "dedupe_verify_failed_count": dedupe_verify_failed_count,
                "archive_total_target_count": int(action_counts.get("remove", 0)) + dedupe_archive_target_count,
                "archive_total_success_count": archive_success_count + dedupe_archive_success_count,
                "archive_total_failed_count": archive_failed_count + dedupe_archive_failed_count,
                "verify_total_archived_count": verify_archived_count + dedupe_verify_archived_count,
                "verify_total_failed_count": verify_failed_count + dedupe_verify_failed_count,
                "remove_success_count": archive_success_count,
                "remove_failed_count": archive_failed_count,
                "execute_error_count": execute_error_count,
                "report_path": str(json_path),
                "csv_path": str(csv_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
