from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from audit_cloudflare_body_contract import (  # noqa: E402
    MIN_KOREAN_SYLLABLES,
    OUT_ROOT,
    _classify_row,
    _integration_data_or_raise,
    _integration_request,
    _safe_text,
    _write_csv,
    _write_json,
    required_terms_for_body_class,
)


RUNTIME_ROOT = Path(os.getenv("BLOGGENT_RUNTIME_ROOT", r"D:\Donggri_Runtime\BloggerGent"))
RESULT_ROOT = OUT_ROOT / "body-contract-refactor-results" / "batch-001"
VALIDATED_ROOT = OUT_ROOT / "body-contract-refactor-validated" / "batch-001"
APPLY_ROOT = OUT_ROOT / "body-contract-refactor-apply" / "batch-001"
BACKUP_ROOT = OUT_ROOT / "body-contract-refactor-backups" / "batch-001"
MANIFEST_PATH = OUT_ROOT / "cloudflare-contenthtml-refactor-packet-manifest-latest.csv"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


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
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _infer_batch_id_from_manifest(path: Path) -> str:
    rows = _read_csv(path)
    for row in rows:
        batch_id = _safe_text(row.get("batch_id"))
        if batch_id:
            return re.sub(r"[^a-zA-Z0-9_-]+", "-", batch_id).strip("-") or "batch-001"
    return "batch-001"


def _root_for_batch(kind: str, batch_id: str) -> Path:
    return OUT_ROOT / kind / batch_id


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalize_result_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        for key in ("payload", "result", "post", "data"):
            nested = value.get(key)
            if isinstance(nested, dict) and any(k in nested for k in ("content", "contentHtml", "html_article")):
                return nested
        return value
    raise ValueError("result_json_must_be_object")


def _extract_content(payload: dict[str, Any]) -> str:
    for key in ("content", "contentHtml", "html_article", "bodyHtml", "body_html", "html"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _html_to_markdown_reference(content: str) -> str:
    soup = BeautifulSoup(content or "", "html.parser")

    def node_text(node: Tag | NavigableString) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        if node.name in {"script", "style", "img", "figure"}:
            return ""
        return node.get_text(" ", strip=True)

    lines: list[str] = []
    for node in soup.find_all(["h2", "h3", "p", "li", "blockquote", "th", "td"]):
        text = html.unescape(re.sub(r"\s+", " ", node_text(node))).strip()
        if not text:
            continue
        tag = (node.name or "").lower()
        if tag == "h2":
            lines.append(f"## {text}")
        elif tag == "h3":
            lines.append(f"### {text}")
        elif tag == "li":
            lines.append(f"- {text}")
        elif tag == "blockquote":
            lines.append(f"> {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines).strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest_rows() -> list[dict[str, str]]:
    rows = _read_csv(MANIFEST_PATH)
    if rows:
        return rows
    return []


def _packet_by_remote_id() -> dict[str, dict[str, Any]]:
    packets: dict[str, dict[str, Any]] = {}
    for row in _manifest_rows():
        path = Path(_safe_text(row.get("packet_path")))
        if not path.exists():
            continue
        try:
            packet = _read_json(path)
        except Exception:
            continue
        remote_post_id = _safe_text(packet.get("remote_detail", {}).get("remote_post_id") or row.get("remote_post_id"))
        if remote_post_id:
            packets[remote_post_id] = packet
    return packets


def _iter_result_files(result_root: Path) -> list[Path]:
    if not result_root.exists():
        return []
    return sorted(path for path in result_root.glob("*.json") if path.is_file())


def _packet_for_result(payload: dict[str, Any], packets: dict[str, dict[str, Any]], result_path: Path) -> tuple[str, dict[str, Any] | None]:
    remote_post_id = _safe_text(payload.get("remote_post_id") or payload.get("id") or payload.get("postId"))
    if remote_post_id and remote_post_id in packets:
        return remote_post_id, packets[remote_post_id]

    stem = result_path.stem
    for candidate_id, packet in packets.items():
        packet_slug = _safe_text(packet.get("remote_detail", {}).get("slug"))
        if packet_slug and packet_slug in stem:
            return candidate_id, packet
    return remote_post_id, packets.get(remote_post_id)


def _packet_contract(packet: dict[str, Any] | None) -> tuple[str, bool, tuple[str, ...]]:
    body_contract = (packet or {}).get("contract", {}).get("body_contract", {})
    expected_body_class = _safe_text(body_contract.get("expected_body_class")) or "cf-body--default"
    allowed_slots = body_contract.get("allowed_inline_slots")
    if not isinstance(allowed_slots, list):
        allowed_slots = body_contract.get("allowed_slots")
    allow_inline = bool(allowed_slots)
    required_terms = body_contract.get("required_fact_terms")
    if not isinstance(required_terms, list):
        required_terms = list(required_terms_for_body_class(expected_body_class))
    return expected_body_class, allow_inline, tuple(_safe_text(term) for term in required_terms if _safe_text(term))


def validate_results(*, result_root: Path = RESULT_ROOT) -> dict[str, Any]:
    VALIDATED_ROOT.mkdir(parents=True, exist_ok=True)
    packets = _packet_by_remote_id()
    rows: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0
    for result_path in _iter_result_files(result_root):
        row: dict[str, Any] = {
            "result_path": str(result_path),
            "status": "invalid",
            "remote_post_id": "",
            "slug": "",
            "error": "",
        }
        try:
            payload = _normalize_result_payload(_read_json(result_path))
            remote_post_id, packet = _packet_for_result(payload, packets, result_path)
            content = _extract_content(payload)
            expected_body_class, allow_inline, required_terms = _packet_contract(packet)
            classification = _classify_row(
                content=content,
                expected_body_class=expected_body_class,
                allow_inline=allow_inline,
                required_terms=required_terms,
            )
            issue_codes = list(classification.get("issue_codes") or [])
            remote_detail = (packet or {}).get("remote_detail", {})
            slug = _safe_text(payload.get("slug") or remote_detail.get("slug"))
            row.update(
                {
                    "remote_post_id": remote_post_id,
                    "slug": slug,
                    "title": _safe_text(payload.get("title") or remote_detail.get("title")),
                    "expected_body_class": expected_body_class,
                    "inline_allowed": str(allow_inline).lower(),
                    "korean_syllable_count": classification.get("korean_syllable_count"),
                    "h2_count": classification.get("h2_count"),
                    "issue_codes": "|".join(issue_codes),
                    "content_sha256": _sha256(content),
                }
            )
            if not remote_post_id:
                raise ValueError("remote_post_id_missing")
            if packet is None:
                raise ValueError("packet_not_found_for_result")
            if not content:
                raise ValueError("content_missing")
            if classification.get("refactor_priority") != "OK":
                raise ValueError(f"body_contract_failed:{'|'.join(issue_codes)}")
            validated_payload = {
                "remote_post_id": remote_post_id,
                "slug": slug,
                "title": payload.get("title") or remote_detail.get("title"),
                "excerpt": payload.get("excerpt"),
                "seoTitle": payload.get("seoTitle"),
                "seoDescription": payload.get("seoDescription"),
                "tagNames": payload.get("tagNames"),
                "content": content,
                "contentFormat": "blocknote",
                "contentMarkdown": payload.get("contentMarkdown") or _html_to_markdown_reference(content),
                "source_result_path": str(result_path),
                "source_packet_path": str(Path(_safe_text((packet or {}).get("packet_path", ""))) if packet else ""),
                "validated_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": _sha256(content),
            }
            out_path = VALIDATED_ROOT / result_path.name
            _write_json(out_path, validated_payload)
            row["validated_path"] = str(out_path)
            row["status"] = "valid"
            valid_count += 1
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {str(exc)[:260]}"
            invalid_count += 1
        rows.append(row)

    stamp = _stamp()
    report_csv = OUT_ROOT / f"cloudflare-body-contract-validated-{stamp}.csv"
    latest_csv = OUT_ROOT / "cloudflare-body-contract-validated-latest.csv"
    _write_csv(report_csv, rows)
    _write_csv(latest_csv, rows)
    summary = {
        "mode": "validate_results",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result_root": str(result_root),
        "validated_root": str(VALIDATED_ROOT),
        "result_count": len(rows),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "report_csv": str(report_csv),
        "report_latest_csv": str(latest_csv),
        "mutation_policy": "validation_only_no_db_live_r2_writes",
    }
    _write_json(OUT_ROOT / f"cloudflare-body-contract-validated-summary-{stamp}.json", summary)
    _write_json(OUT_ROOT / "cloudflare-body-contract-validated-summary-latest.json", summary)
    return summary


def _validated_payloads(limit: int | None) -> list[tuple[Path, dict[str, Any]]]:
    files = _iter_result_files(VALIDATED_ROOT)
    if limit is not None:
        files = files[:limit]
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for path in files:
        payload = _read_json(path)
        if isinstance(payload, dict) and _safe_text(payload.get("remote_post_id")):
            payloads.append((path, payload))
    return payloads


def _fetch_remote_detail(db, remote_post_id: str) -> dict[str, Any]:
    response = _integration_request(db, method="GET", path=f"/api/integrations/posts/{remote_post_id}", timeout=60.0)
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _put_remote_post(db, remote_post_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="PUT",
        path=f"/api/integrations/posts/{remote_post_id}",
        json_payload=payload,
        timeout=90.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _build_put_payload(validated: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": validated["content"],
        "contentFormat": "blocknote",
        "contentMarkdown": validated.get("contentMarkdown") or _html_to_markdown_reference(validated["content"]),
    }
    for key in ("title", "excerpt", "seoTitle", "seoDescription", "tagNames"):
        value = validated.get(key)
        if value not in (None, "", []):
            payload[key] = value
    return payload


def apply_validated(*, execute: bool, limit: int | None, sync: bool) -> dict[str, Any]:
    APPLY_ROOT.mkdir(parents=True, exist_ok=True)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    stamp = _stamp()
    with SessionLocal() as db:
        for path, validated in _validated_payloads(limit):
            remote_post_id = _safe_text(validated.get("remote_post_id"))
            put_payload = _build_put_payload(validated)
            row: dict[str, Any] = {
                "remote_post_id": remote_post_id,
                "slug": _safe_text(validated.get("slug")),
                "validated_path": str(path),
                "status": "planned",
                "execute": str(execute).lower(),
                "backup_path": "",
                "error": "",
            }
            try:
                before = _fetch_remote_detail(db, remote_post_id)
                backup_path = BACKUP_ROOT / f"{stamp}-{remote_post_id}.rollback.json"
                backup_payload = {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "remote_post_id": remote_post_id,
                    "before_remote_detail": before,
                    "put_payload": put_payload,
                    "validated_path": str(path),
                    "rollback_note": "Use before_remote_detail fields to restore this post through PUT if needed.",
                }
                _write_json(backup_path, backup_payload)
                row["backup_path"] = str(backup_path)

                if not execute:
                    row["status"] = "planned_backup_ready"
                    rows.append(row)
                    continue

                _put_remote_post(db, remote_post_id, put_payload)
                after = _fetch_remote_detail(db, remote_post_id)
                after_content = _extract_content(after)
                if _sha256(after_content) != _sha256(validated["content"]):
                    raise RuntimeError("remote_get_verify_content_hash_mismatch")
                row["status"] = "put_verified"
            except Exception as exc:  # noqa: BLE001
                row["status"] = "failed"
                row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            rows.append(row)

        sync_result: Any = None
        if execute and sync:
            sync_result = sync_cloudflare_posts(db, include_non_published=True)

    result_csv = APPLY_ROOT / f"cloudflare-body-contract-apply-{stamp}.csv"
    latest_csv = APPLY_ROOT / "cloudflare-body-contract-apply-latest.csv"
    _write_csv(result_csv, rows)
    _write_csv(latest_csv, rows)
    summary = {
        "mode": "apply_validated",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execute": execute,
        "sync": sync,
        "limit": limit,
        "total_count": len(rows),
        "success_count": sum(1 for row in rows if row.get("status") == "put_verified"),
        "planned_count": sum(1 for row in rows if row.get("status") == "planned_backup_ready"),
        "failed_count": sum(1 for row in rows if row.get("status") == "failed"),
        "result_csv": str(result_csv),
        "result_latest_csv": str(latest_csv),
        "sync_result": sync_result,
        "mutation_policy": "remote_put_and_db_sync_only_when_execute_true",
    }
    _write_json(APPLY_ROOT / f"cloudflare-body-contract-apply-summary-{stamp}.json", summary)
    _write_json(APPLY_ROOT / "cloudflare-body-contract-apply-summary-latest.json", summary)
    return summary


def main() -> None:
    global APPLY_ROOT, BACKUP_ROOT, MANIFEST_PATH, RESULT_ROOT, VALIDATED_ROOT

    parser = argparse.ArgumentParser(description="Validate and safely apply Cloudflare body-contract refactor results.")
    parser.add_argument("--mode", choices=["validate_results", "apply_validated"], required=True)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--result-root", default=None)
    parser.add_argument("--validated-root", default=None)
    parser.add_argument("--apply-root", default=None)
    parser.add_argument("--backup-root", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()

    MANIFEST_PATH = Path(args.manifest)
    batch_id = args.batch_id or _infer_batch_id_from_manifest(MANIFEST_PATH)
    RESULT_ROOT = Path(args.result_root) if args.result_root else _root_for_batch("body-contract-refactor-results", batch_id)
    VALIDATED_ROOT = (
        Path(args.validated_root) if args.validated_root else _root_for_batch("body-contract-refactor-validated", batch_id)
    )
    APPLY_ROOT = Path(args.apply_root) if args.apply_root else _root_for_batch("body-contract-refactor-apply", batch_id)
    BACKUP_ROOT = Path(args.backup_root) if args.backup_root else _root_for_batch("body-contract-refactor-backups", batch_id)

    if args.mode == "validate_results":
        result = validate_results(result_root=RESULT_ROOT)
    else:
        result = apply_validated(execute=args.execute, limit=args.limit, sync=args.sync)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
