from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
import re
from typing import Any, Sequence
from urllib.parse import quote, unquote, urlsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Article, Blog, BloggerPost
from app.services.blogger_oauth_service import BloggerOAuthError, authorized_google_request
from app.services.settings_service import get_settings_map

GOOGLE_SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")

BLOGGER_SNAPSHOT_COLUMNS = [
    "date_kst",
    "profile",
    "blog",
    "title",
    "url",
    "slug",
    "summary",
    "labels",
    "status",
    "published_at",
    "updated_at",
    "content_category",
    "category_key",
]

CLOUDFLARE_SNAPSHOT_COLUMNS = [
    "published_at",
    "created_at",
    "updated_at",
    "category",
    "category_slug",
    "remote_id",
    "title",
    "url",
    "excerpt",
    "labels",
    "status",
]

PRIORITY_COLUMNS = [
    "priority_rank",
    "priority_label",
    "priority_reason",
    "due_at",
]

QUALITY_COLUMNS = [
    *PRIORITY_COLUMNS,
    "quality_status",
    "similarity_score",
    "seo_score",
    "geo_score",
    "ctr_score",
    "dbs_score",
    "dbs_grade",
    "dbs_confidence",
    "dbs_version",
    "rewrite_attempts",
    "last_audited_at",
    "topic_cluster",
    "topic_angle",
    "most_similar_url",
]

BACKUP_META_COLUMNS = [
    "backup_batch_id",
    "backup_moved_at",
    "backup_source_tab",
    "backup_reason",
    "backup_reason_detail",
    "canonical_key",
    "source_status_at_backup",
    "source_hash",
    "raw_row_json",
]

COLUMN_LABELS_KO = {
    "date_kst": "작성일 (KST)",
    "profile": "프로필",
    "blog": "블로그",
    "title": "제목",
    "url": "본문 URL",
    "slug": "슬러그",
    "summary": "요약",
    "excerpt": "요약",
    "labels": "라벨",
    "status": "상태",
    "priority_rank": "우선순위",
    "priority_label": "우선 처리",
    "priority_reason": "우선 사유",
    "due_at": "발행 일정",
    "published_at": "발행일시",
    "created_at": "생성일시",
    "updated_at": "수정일시",
    "category": "카테고리",
    "category_slug": "카테고리 슬러그",
    "remote_id": "원격 ID",
    "content_category": "콘텐츠 카테고리",
    "category_key": "카테고리 키",
    "topic_cluster": "주제 클러스터",
    "topic_angle": "주제 각도",
    "similarity_score": "유사도",
    "most_similar_url": "유사 URL",
    "seo_score": "SEO 점수",
    "geo_score": "GEO 점수",
    "ctr_score": "CTR 점수",
    "dbs_score": "DBS 점수",
    "dbs_grade": "DBS 등급",
    "dbs_confidence": "DBS 신뢰도",
    "dbs_version": "DBS 버전",
    "quality_status": "품질 상태",
    "rewrite_attempts": "재작성 횟수",
    "last_audited_at": "최종 점검일시",
    "backup_batch_id": "백업 배치 ID",
    "backup_moved_at": "백업 이동시각",
    "backup_source_tab": "백업 원본 탭",
    "backup_reason": "백업 사유",
    "backup_reason_detail": "백업 상세 사유",
    "canonical_key": "정합 키",
    "source_status_at_backup": "백업 시 상태",
    "source_hash": "원본 해시",
    "raw_row_json": "원본 행 JSON",
}

COLUMN_ALIASES = {
    **{key: key for key in [*BLOGGER_SNAPSHOT_COLUMNS, *CLOUDFLARE_SNAPSHOT_COLUMNS, *QUALITY_COLUMNS]},
    **{label: key for key, label in COLUMN_LABELS_KO.items()},
}

TRAVEL_CATEGORY_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "travel": (
        "Travel",
        ("travel", "trip", "route", "itinerary", "walk", "neighborhood", "local"),
    ),
    "culture": (
        "Culture",
        ("culture", "festival", "event", "exhibition", "museum", "heritage", "idol", "filming"),
    ),
    "food": (
        "Food",
        ("food", "restaurant", "market", "cafe", "eatery", "korean food", "dining"),
    ),
}

MYSTERY_CATEGORY_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "case-files": (
        "Case Files",
        ("case", "incident", "investigation", "evidence", "timeline", "disappearance", "murder"),
    ),
    "legends-lore": (
        "Legends & Lore",
        ("legend", "folklore", "myth", "urban legend", "scp", "lore", "haunted"),
    ),
    "mystery-archives": (
        "Mystery Archives",
        ("archive", "historical", "record", "document", "expedition", "manuscript", "chronology"),
    ),
}

DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS = 180
DEFAULT_TOPIC_NOVELTY_CLUSTER_THRESHOLD = 0.85
DEFAULT_TOPIC_NOVELTY_ANGLE_THRESHOLD = 0.75
DEFAULT_TOPIC_SOFT_PENALTY_THRESHOLD = 2


@dataclass(slots=True)
class TopicHistoryEntry:
    keyword: str
    topic_cluster: str
    topic_angle: str
    category: str
    profile: str
    blog: str
    published_at: str
    source: str


def _extract_sheet_id(values: dict[str, str]) -> str:
    raw = (values.get("google_sheet_id") or "").strip()
    if raw:
        return raw
    url = (values.get("google_sheet_url") or "").strip()
    marker = "/spreadsheets/d/"
    if marker in url:
        tail = url.split(marker, 1)[1]
        return tail.split("/", 1)[0]
    return ""


def _safe_str(value: object | None) -> str:
    return str(value or "").strip()


def _normalize_column_key(value: str) -> str:
    raw = _safe_str(value)
    return COLUMN_ALIASES.get(raw, raw)


def _display_column_label(column_key: str) -> str:
    normalized = _normalize_column_key(column_key)
    return COLUMN_LABELS_KO.get(normalized, normalized)


def _hydrate_summary_alias(record: dict[str, str]) -> dict[str, str]:
    summary = _safe_str(record.get("summary"))
    excerpt = _safe_str(record.get("excerpt"))
    if summary and not excerpt:
        record["excerpt"] = summary
    elif excerpt and not summary:
        record["summary"] = excerpt
    return record


def _resolve_category_column(base_columns: Sequence[str]) -> str:
    normalized = {_normalize_column_key(_safe_str(column)) for column in base_columns if _safe_str(column)}
    if "category" in normalized:
        return "category"
    if "content_category" in normalized:
        return "content_category"
    return ""


def _build_front_columns(base_columns: Sequence[str]) -> list[str]:
    front_columns = [
        "priority_rank",
        "priority_label",
        "priority_reason",
        "due_at",
        "status",
        "published_at",
        "updated_at",
        "title",
    ]
    category_column = _resolve_category_column(base_columns)
    if category_column:
        front_columns.append(category_column)
    front_columns.append("url")
    return front_columns


def _build_merged_header(
    *,
    existing_header: Sequence[str],
    base_columns: Sequence[str],
    quality_columns: Sequence[str],
) -> list[str]:
    prioritized_columns: list[str] = []
    for column in [*_build_front_columns(base_columns), *base_columns, *quality_columns]:
        normalized = _normalize_column_key(_safe_str(column))
        if normalized and normalized not in prioritized_columns:
            prioritized_columns.append(normalized)

    merged_header: list[str] = []
    used_display_labels: set[str] = set()

    for column in prioritized_columns:
        display_label = _display_column_label(column)
        if display_label in used_display_labels:
            continue
        merged_header.append(column)
        used_display_labels.add(display_label)

    for column in existing_header:
        normalized = _normalize_column_key(_safe_str(column))
        if not normalized or normalized in merged_header:
            continue
        display_label = _display_column_label(normalized)
        if display_label in used_display_labels:
            continue
        merged_header.append(normalized)
        used_display_labels.add(display_label)

    return merged_header


def _canonical_url_key(value: str) -> str:
    raw = unquote(_safe_str(value)).strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlsplit(raw)
        host = _safe_str(parsed.netloc).lower()
        path = _safe_str(parsed.path).rstrip("/")
        if host and path:
            return f"{host}{path}"
        return (host or path).lower()
    return raw.rstrip("/").lower()


def _is_live_status(value: str) -> bool:
    return _safe_str(value).lower() in {"published", "live"}


def _merge_record_key(record: dict[str, str], *, key_columns: Sequence[str]) -> str:
    for key in key_columns:
        normalized_key = _safe_str(key)
        candidate = _safe_str(record.get(normalized_key))
        if not candidate:
            continue
        if normalized_key == "url":
            canonical_url = _canonical_url_key(candidate)
            if canonical_url:
                return canonical_url
            continue
        if normalized_key in {"slug", "title"}:
            return candidate.casefold()
        return candidate.strip()
    return ""


def _sheet_range(tab_name: str) -> str:
    return f"'{tab_name}'!A1:ZZ"


def _sheet_url(sheet_id: str, suffix: str) -> str:
    return f"{GOOGLE_SHEETS_API_BASE}/{sheet_id}{suffix}"


def _format_datetime(value: datetime | None, *, timezone_name: str = "Asia/Seoul") -> str:
    if value is None:
        return ""
    return value.astimezone(ZoneInfo(timezone_name)).replace(microsecond=0).isoformat()


def _parse_datetime_text(value: object | None) -> datetime | None:
    text = _safe_str(value)
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _normalize_datetime_text(value: object | None, *, timezone_name: str = "Asia/Seoul") -> str:
    parsed = _parse_datetime_text(value)
    if parsed is None:
        return _safe_str(value)
    return parsed.astimezone(ZoneInfo(timezone_name)).replace(microsecond=0).isoformat()


def _safe_float(value: object | None, fallback: float = 0.0) -> float:
    try:
        return float(_safe_str(value))
    except (TypeError, ValueError):
        return fallback


def _safe_int(value: object | None, fallback: int = 0) -> int:
    try:
        return int(float(_safe_str(value)))
    except (TypeError, ValueError):
        return fallback


def _is_enabled(value: object | None, *, default: bool = False) -> bool:
    normalized = _safe_str(value).lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "y", "yes", "on"}


def _is_cloudflare_record(record: dict[str, str]) -> bool:
    keys = ("remote_id", "category", "category_slug", "created_at")
    return any(key in record for key in keys) or any(_safe_str(record.get(key)) for key in keys)


def _due_datetime_keys(record: dict[str, str]) -> tuple[str, ...]:
    if _is_cloudflare_record(record):
        return ("published_at", "updated_at", "created_at")
    return ("scheduled_for", "published_at", "updated_at", "date_kst")


def _resolve_due_at(record: dict[str, str]) -> str:
    direct_due = _parse_datetime_text(record.get("due_at"))
    if direct_due is not None:
        return direct_due.astimezone(KST).replace(microsecond=0).isoformat()

    for key in _due_datetime_keys(record):
        parsed = _parse_datetime_text(record.get(key))
        if parsed is not None:
            return parsed.astimezone(KST).replace(microsecond=0).isoformat()
    return _safe_str(record.get("due_at"))


def _normalize_operational_datetimes(record: dict[str, str]) -> dict[str, str]:
    for key in ("scheduled_for", "due_at", "published_at", "updated_at", "created_at", "date_kst", "last_audited_at"):
        if key not in record and not _safe_str(record.get(key)):
            continue
        record[key] = _normalize_datetime_text(record.get(key))
    return record


def _row_reference_datetime(record: dict[str, str]) -> datetime | None:
    for key in ("published_at", "updated_at", "created_at", "date_kst"):
        parsed = _parse_datetime_text(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _derive_priority_fields(record: dict[str, str], *, now: datetime | None = None) -> tuple[int, str, str]:
    now_kst = (now or datetime.now(KST)).astimezone(KST)
    status = _safe_str(record.get("status")).lower()
    quality_status = _safe_str(record.get("quality_status")).lower()
    due_at = _resolve_due_at(record)
    due_dt = _parse_datetime_text(due_at)
    if due_dt is not None:
        due_dt = due_dt.astimezone(KST)
    similarity_score = _safe_float(record.get("similarity_score"), 0.0)
    seo_score = _safe_int(record.get("seo_score"), 0)
    geo_score = _safe_int(record.get("geo_score"), 0)

    if _is_dislive_row(status):
        return 5, "보관", "비공개/삭제 상태"

    if status in {"scheduled", "pending"}:
        if due_dt is not None and due_dt <= now_kst + timedelta(hours=24):
            if due_dt < now_kst:
                return 1, "긴급", f"발행 일정 지남 ({due_at})"
            return 1, "긴급", f"24시간 내 발행 일정 ({due_at})"
        if due_dt is None:
            return 2, "확인", "예약 일정 미설정"
        return 2, "확인", f"24시간 이후 예약 일정 ({due_at})"

    if status in {"draft", "queued"}:
        if due_dt is None:
            return 2, "확인", "초안 일정 미설정"
        return 2, "확인", f"초안 일정 확인 필요 ({due_at})"

    if quality_status in {"rewrite_required", "manual_review_required", "quality_gate_failed", "failed"}:
        return 3, "확인", f"품질 상태 점검 ({quality_status})"
    if (seo_score and seo_score < 60) or (geo_score and geo_score < 60):
        return 3, "확인", f"품질 점수 경고 (SEO {seo_score}, GEO {geo_score})"
    if similarity_score >= 70.0:
        return 3, "확인", f"유사도 경고 ({similarity_score:.1f})"
    if status in {"published", "live"}:
        return 4, "일반", "발행 완료"
    return 4, "일반", "일반 운영"


def _apply_priority_fields(record: dict[str, str]) -> dict[str, str]:
    normalized = _normalize_operational_datetimes({key: _safe_str(value) for key, value in record.items()})
    normalized["due_at"] = _resolve_due_at(normalized)
    rank, label, reason = _derive_priority_fields(normalized)
    normalized["priority_rank"] = str(rank)
    normalized["priority_label"] = label
    normalized["priority_reason"] = reason
    return normalized


def _sort_sheet_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    def _sort_key(record: dict[str, str]) -> tuple[int, int, float, str]:
        rank = _safe_int(record.get("priority_rank"), 9)
        title = _safe_str(record.get("title")).lower()
        if rank in {1, 2}:
            due_dt = _parse_datetime_text(record.get("due_at"))
            due_timestamp = due_dt.timestamp() if due_dt is not None else float("inf")
            return rank, 0, due_timestamp, title
        parsed = _row_reference_datetime(record)
        timestamp = parsed.timestamp() if parsed is not None else float("-inf")
        return rank, 1, -timestamp, title

    return sorted(records, key=_sort_key)


def _records_from_sheet_rows(rows: list[list[str]] | None) -> tuple[list[str], list[dict[str, str]]]:
    normalized_rows = list(rows or [])
    header_raw = [column for column in (normalized_rows[0] if normalized_rows else []) if _safe_str(column)]
    header: list[str] = []
    for column in header_raw:
        normalized_column = _normalize_column_key(column)
        if normalized_column and normalized_column not in header:
            header.append(normalized_column)
    records: list[dict[str, str]] = []
    if not header:
        return header, records
    for row in normalized_rows[1:]:
        record = {
            header[index]: _safe_str(row[index] if index < len(row) else "")
            for index in range(len(header))
        }
        if any(_safe_str(value) for value in record.values()):
            records.append(_hydrate_summary_alias(record))
    return header, records


def _prefer_live_record(candidate: dict[str, str], current: dict[str, str]) -> bool:
    cand_published = _safe_str(candidate.get("published_at"))
    curr_published = _safe_str(current.get("published_at"))
    if bool(cand_published) != bool(curr_published):
        return bool(cand_published)
    cand_updated = _parse_datetime_text(candidate.get("updated_at"))
    curr_updated = _parse_datetime_text(current.get("updated_at"))
    if cand_updated is not None and curr_updated is not None and cand_updated != curr_updated:
        return cand_updated > curr_updated
    if cand_updated is not None and curr_updated is None:
        return True
    if cand_updated is None and curr_updated is not None:
        return False
    cand_has_url = bool(_safe_str(candidate.get("url")))
    curr_has_url = bool(_safe_str(current.get("url")))
    if cand_has_url != curr_has_url:
        return cand_has_url
    return _safe_str(candidate.get("title")) < _safe_str(current.get("title"))


def _build_backup_columns(base_columns: Sequence[str], quality_columns: Sequence[str]) -> list[str]:
    columns: list[str] = []
    for column in [*BACKUP_META_COLUMNS, *base_columns, *quality_columns]:
        normalized = _normalize_column_key(_safe_str(column))
        if normalized and normalized not in columns:
            columns.append(normalized)
    return columns


def _backup_report_path(*, tab_name: str, batch_id: str) -> str:
    storage_root = Path(os.environ.get("STORAGE_ROOT", "storage"))
    report_dir = storage_root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", _safe_str(tab_name)).strip("-") or "sheet"
    path = report_dir / f"sheet-live-backup-{safe_name}-{batch_id}.json"
    return str(path.resolve())


def _write_backup_report(
    *,
    tab_name: str,
    backup_tab_name: str,
    batch_id: str,
    backup_rows: list[dict[str, str]],
) -> str:
    report_path = _backup_report_path(tab_name=tab_name, batch_id=batch_id)
    payload = {
        "generated_at": _format_datetime(datetime.now(UTC), timezone_name="UTC"),
        "batch_id": batch_id,
        "tab": tab_name,
        "backup_tab": backup_tab_name,
        "rows": backup_rows,
    }
    Path(report_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _append_backup_rows(
    db: Session,
    *,
    sheet_id: str,
    backup_tab_name: str,
    backup_rows: list[dict[str, str]],
    backup_columns: Sequence[str],
) -> int:
    if not backup_rows:
        return 0
    _ensure_sheet_tab_exists(db, sheet_id=sheet_id, tab_name=backup_tab_name)
    existing_rows = _read_sheet_rows(db, sheet_id=sheet_id, tab_name=backup_tab_name)
    existing_header, existing_records = _records_from_sheet_rows(existing_rows)
    if not existing_header:
        existing_header = [_normalize_column_key(column) for column in backup_columns if _normalize_column_key(column)]
    merged_header = _build_merged_header(existing_header=existing_header, base_columns=backup_columns, quality_columns=())

    dedupe_key_set: set[str] = set()
    for record in existing_records:
        key = f"{_safe_str(record.get('canonical_key'))}|{_safe_str(record.get('source_hash'))}"
        if key:
            dedupe_key_set.add(key)

    appended = 0
    for record in backup_rows:
        dedupe_key = f"{_safe_str(record.get('canonical_key'))}|{_safe_str(record.get('source_hash'))}"
        if dedupe_key and dedupe_key in dedupe_key_set:
            continue
        if dedupe_key:
            dedupe_key_set.add(dedupe_key)
        existing_records.append(record)
        appended += 1

    rendered_rows: list[list[str]] = [[_display_column_label(column) for column in merged_header]]
    for record in existing_records:
        rendered_rows.append([_safe_str(record.get(column)) for column in merged_header])

    _clear_sheet_tab(db, sheet_id=sheet_id, tab_name=backup_tab_name)
    _write_sheet_rows(db, sheet_id=sheet_id, tab_name=backup_tab_name, rows=rendered_rows)
    return appended

def _infer_editorial_category(
    *,
    profile_key: str,
    labels: list[str],
    title: str,
    summary: str,
) -> tuple[str, str]:
    normalized_labels = {label.strip().lower() for label in labels if label and label.strip()}
    category_map = TRAVEL_CATEGORY_MAP if profile_key == "korea_travel" else MYSTERY_CATEGORY_MAP

    for key, (label, _keywords) in category_map.items():
        if label.lower() in normalized_labels:
            return key, label

    haystack = f"{title} {summary} {' '.join(labels)}".lower()
    best_key = ""
    best_label = ""
    best_score = -1
    for key, (label, keywords) in category_map.items():
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score > best_score:
            best_key = key
            best_label = label
            best_score = score

    if best_key and best_label:
        return best_key, best_label

    first_key, (first_label, _keywords) = next(iter(category_map.items()))
    return first_key, first_label


def _ensure_sheet_tab_exists(db: Session, *, sheet_id: str, tab_name: str) -> None:
    metadata_response = authorized_google_request(
        db,
        "GET",
        _sheet_url(sheet_id, ""),
        params={"fields": "sheets.properties.title"},
        timeout=30.0,
    )
    metadata_response.raise_for_status()
    payload = metadata_response.json() if metadata_response.content else {}
    sheets = payload.get("sheets") if isinstance(payload, dict) else []
    titles = {
        _safe_str(sheet.get("properties", {}).get("title"))
        for sheet in sheets
        if isinstance(sheet, dict) and isinstance(sheet.get("properties"), dict)
    }
    if tab_name in titles:
        return

    create_response = authorized_google_request(
        db,
        "POST",
        _sheet_url(sheet_id, ":batchUpdate"),
        json={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]},
        timeout=30.0,
    )
    create_response.raise_for_status()


def _clear_sheet_tab(db: Session, *, sheet_id: str, tab_name: str) -> None:
    clear_range = quote(_sheet_range(tab_name), safe="")
    clear_response = authorized_google_request(
        db,
        "POST",
        _sheet_url(sheet_id, f"/values/{clear_range}:clear"),
        json={},
        timeout=30.0,
    )
    clear_response.raise_for_status()


def _write_sheet_rows(db: Session, *, sheet_id: str, tab_name: str, rows: list[list[str]]) -> None:
    update_range = quote(_sheet_range(tab_name), safe="")
    update_response = authorized_google_request(
        db,
        "PUT",
        _sheet_url(sheet_id, f"/values/{update_range}"),
        params={"valueInputOption": "RAW"},
        json={
            "majorDimension": "ROWS",
            "values": rows,
        },
        timeout=60.0,
    )
    update_response.raise_for_status()


def _fetch_sheet_metadata(db: Session, *, sheet_id: str) -> list[dict[str, Any]]:
    response = authorized_google_request(
        db,
        "GET",
        _sheet_url(sheet_id, ""),
        params={
            "fields": (
                "sheets.properties(sheetId,title,gridProperties(rowCount,columnCount)),"
                "sheets.conditionalFormats"
            )
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json() if response.content else {}
    sheets = payload.get("sheets") if isinstance(payload, dict) else []
    return [sheet for sheet in sheets if isinstance(sheet, dict)] if isinstance(sheets, list) else []


def _find_sheet_metadata(sheets: list[dict[str, Any]], *, tab_name: str) -> dict[str, Any] | None:
    for sheet in sheets:
        properties = sheet.get("properties")
        if not isinstance(properties, dict):
            continue
        if _safe_str(properties.get("title")) == tab_name:
            return sheet
    return None


def _apply_sheet_operational_format(
    db: Session,
    *,
    sheet_id: str,
    tab_name: str,
    header_row: list[str],
    row_count: int,
) -> None:
    sheets = _fetch_sheet_metadata(db, sheet_id=sheet_id)
    sheet = _find_sheet_metadata(sheets, tab_name=tab_name)
    if sheet is None:
        return

    properties = sheet.get("properties") if isinstance(sheet.get("properties"), dict) else {}
    sheet_gid = properties.get("sheetId")
    if not isinstance(sheet_gid, int):
        return

    grid_props = properties.get("gridProperties") if isinstance(properties.get("gridProperties"), dict) else {}
    column_count = max(_safe_int(grid_props.get("columnCount"), 0), len(header_row), 1)
    normalized_row_count = max(row_count, 1)
    data_end_row_index = max(normalized_row_count, 2)
    priority_label_column = _display_column_label("priority_label")
    priority_col_index = next(
        (index for index, column in enumerate(header_row) if _safe_str(column) == priority_label_column),
        -1,
    )

    requests: list[dict[str, Any]] = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_gid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_gid,
                        "startRowIndex": 0,
                        "startColumnIndex": 0,
                        "endRowIndex": normalized_row_count,
                        "endColumnIndex": column_count,
                    }
                }
            }
        },
    ]

    conditional_rules = sheet.get("conditionalFormats")
    if isinstance(conditional_rules, list):
        for _ in conditional_rules:
            requests.append({"deleteConditionalFormatRule": {"sheetId": sheet_gid, "index": 0}})

    if priority_col_index >= 0:
        label_formats: list[tuple[str, dict[str, float]]] = [
            ("긴급", {"red": 0.93, "green": 0.73, "blue": 0.73}),
            ("확인", {"red": 0.98, "green": 0.92, "blue": 0.67}),
            ("일반", {"red": 0.78, "green": 0.90, "blue": 0.78}),
            ("보관", {"red": 0.86, "green": 0.86, "blue": 0.86}),
        ]
        for label, color in label_formats:
            requests.append(
                {
                    "addConditionalFormatRule": {
                        "index": 0,
                        "rule": {
                            "ranges": [
                                {
                                    "sheetId": sheet_gid,
                                    "startRowIndex": 1,
                                    "endRowIndex": data_end_row_index,
                                    "startColumnIndex": priority_col_index,
                                    "endColumnIndex": priority_col_index + 1,
                                }
                            ],
                            "booleanRule": {
                                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": label}]},
                                "format": {"backgroundColor": color, "textFormat": {"bold": True}},
                            },
                        },
                    }
                }
            )

    batch_response = authorized_google_request(
        db,
        "POST",
        _sheet_url(sheet_id, ":batchUpdate"),
        json={"requests": requests},
        timeout=30.0,
    )
    batch_response.raise_for_status()


def _read_sheet_rows(db: Session, *, sheet_id: str, tab_name: str) -> list[list[str]]:
    read_range = quote(_sheet_range(tab_name), safe="")
    response = authorized_google_request(
        db,
        "GET",
        _sheet_url(sheet_id, f"/values/{read_range}"),
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json() if response.content else {}
    values = payload.get("values") if isinstance(payload, dict) else []
    rows: list[list[str]] = []
    for row in values if isinstance(values, list) else []:
        if isinstance(row, list):
            rows.append([_safe_str(cell) for cell in row])
    return rows


def _resolve_blogger_tab_by_profile(*, profile_key: str, config: dict[str, str]) -> str:
    if profile_key == "world_mystery":
        return config.get("mystery_tab") or "援ш?釉붾줈洹?"
    return config.get("travel_tab") or "援ш?釉붾줈洹?"


def _build_header_index_map(header_row: list[str]) -> dict[str, int]:
    index_map: dict[str, int] = {}
    for index, column in enumerate(header_row):
        normalized = _normalize_column_key(column)
        if normalized and normalized not in index_map:
            index_map[normalized] = index
    return index_map


def _is_dislive_row(status_text: str) -> bool:
    value = _safe_str(status_text).lower()
    if not value:
        return False
    return any(token in value for token in ("dislive", "deleted", "trash", "removed"))


def _is_noise_topic_value(value: str) -> bool:
    normalized = _safe_str(value).lower()
    if not normalized:
        return True
    return normalized in {"channel_post", "channel post", "post", "n/a", "none", "-", "_"}


def _normalize_topic_text(value: str) -> str:
    lowered = _safe_str(value).lower()
    if not lowered:
        return ""
    cleaned = re.sub(r"[^a-z0-9가-힣\s]+", " ", lowered)
    return " ".join(cleaned.split()).strip()


def _text_similarity(left: str, right: str) -> float:
    left_norm = _normalize_topic_text(left)
    right_norm = _normalize_topic_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    if left_norm in right_norm or right_norm in left_norm:
        return max(ratio, 0.93)
    return ratio


def _resolve_history_base_text(*, title: str, cluster: str, angle: str) -> str:
    if cluster and angle and not _is_noise_topic_value(cluster) and not _is_noise_topic_value(angle):
        return f"{cluster} | {angle}"
    if title and not _is_noise_topic_value(title):
        return title
    if cluster and not _is_noise_topic_value(cluster):
        return cluster
    if angle and not _is_noise_topic_value(angle):
        return angle
    return ""


def _history_cutoff_utc(*, lookback_days: int) -> datetime:
    safe_days = max(int(lookback_days or DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS), 1)
    return datetime.now(UTC) - timedelta(days=safe_days)


def _extract_history_row_datetime(*, row: list[str], index_map: dict[str, int]) -> datetime | None:
    candidate_keys = ("published_at", "updated_at", "created_at", "date_kst", "due_at")
    for key in candidate_keys:
        idx = index_map.get(key, -1)
        if idx < 0 or idx >= len(row):
            continue
        parsed = _parse_datetime_text(row[idx])
        if parsed is not None:
            return parsed.astimezone(UTC)
    return None


def _collect_sheet_topic_history_entries(
    *,
    rows: list[list[str]],
    lookback_days: int,
    limit: int,
    profile_key: str = "",
    blog_name: str = "",
    source: str,
) -> list[TopicHistoryEntry]:
    if not rows:
        return []
    header_row = rows[0] if rows else []
    if not header_row:
        return []

    index_map = _build_header_index_map(header_row)
    idx_title = index_map.get("title", -1)
    idx_cluster = index_map.get("topic_cluster", -1)
    idx_angle = index_map.get("topic_angle", -1)
    idx_status = index_map.get("status", -1)
    idx_category = index_map.get("category", -1)
    idx_profile = index_map.get("profile", -1)
    idx_blog = index_map.get("blog", -1)
    cutoff_utc = _history_cutoff_utc(lookback_days=lookback_days)
    normalized_profile = _safe_str(profile_key).lower()
    normalized_blog = _safe_str(blog_name).lower()

    entries: list[TopicHistoryEntry] = []
    seen: set[str] = set()
    for row in rows[1:]:
        status_value = _safe_str(row[idx_status] if 0 <= idx_status < len(row) else "")
        if _is_dislive_row(status_value):
            continue

        profile = _safe_str(row[idx_profile] if 0 <= idx_profile < len(row) else "")
        blog = _safe_str(row[idx_blog] if 0 <= idx_blog < len(row) else "")
        if normalized_profile and profile and profile.lower() != normalized_profile:
            continue
        if normalized_blog and blog and blog.lower() != normalized_blog:
            continue
        if normalized_profile and not profile and source == "sheet_blogger":
            continue
        if normalized_blog and not blog and source == "sheet_blogger":
            continue

        row_dt = _extract_history_row_datetime(row=row, index_map=index_map)
        if row_dt is not None and row_dt < cutoff_utc:
            continue

        title = _safe_str(row[idx_title] if 0 <= idx_title < len(row) else "")
        cluster = _safe_str(row[idx_cluster] if 0 <= idx_cluster < len(row) else "")
        angle = _safe_str(row[idx_angle] if 0 <= idx_angle < len(row) else "")
        category = _safe_str(row[idx_category] if 0 <= idx_category < len(row) else "")
        base_text = _resolve_history_base_text(title=title, cluster=cluster, angle=angle)
        if not base_text:
            continue

        dedupe_key = _normalize_topic_text(base_text)
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(
            TopicHistoryEntry(
                keyword=base_text,
                topic_cluster=cluster,
                topic_angle=angle,
                category=category,
                profile=profile,
                blog=blog,
                published_at=row_dt.isoformat() if row_dt is not None else "",
                source=source,
            )
        )
        if len(entries) >= max(limit, 1):
            break
    return entries


def _history_entry_display_value(entry: TopicHistoryEntry, *, include_category: bool) -> str:
    base = entry.keyword.strip()
    if include_category and entry.category:
        return f"{entry.category} :: {base}"
    return base


def assess_topic_novelty_against_history(
    *,
    keyword: str,
    topic_cluster: str,
    topic_angle: str,
    history_entries: Sequence[TopicHistoryEntry],
    cluster_threshold: float = DEFAULT_TOPIC_NOVELTY_CLUSTER_THRESHOLD,
    angle_threshold: float = DEFAULT_TOPIC_NOVELTY_ANGLE_THRESHOLD,
) -> dict[str, object]:
    candidate_keyword = _safe_str(keyword)
    candidate_cluster = _safe_str(topic_cluster)
    candidate_angle = _safe_str(topic_angle)
    best_entry: TopicHistoryEntry | None = None
    best_overlap = 0.0
    best_cluster_similarity = 0.0
    best_angle_similarity = 0.0
    best_keyword_similarity = 0.0

    for entry in history_entries:
        keyword_similarity = _text_similarity(candidate_keyword, entry.keyword)
        if candidate_cluster and entry.topic_cluster:
            cluster_similarity = _text_similarity(candidate_cluster, entry.topic_cluster)
        else:
            cluster_similarity = _text_similarity(candidate_keyword, entry.topic_cluster or entry.keyword)
        if candidate_angle and entry.topic_angle:
            angle_similarity = _text_similarity(candidate_angle, entry.topic_angle)
        else:
            angle_similarity = _text_similarity(candidate_keyword, entry.topic_angle or entry.keyword)

        overlap = max(keyword_similarity, (cluster_similarity * 0.6) + (angle_similarity * 0.4))
        if overlap > best_overlap:
            best_overlap = overlap
            best_entry = entry
            best_cluster_similarity = cluster_similarity
            best_angle_similarity = angle_similarity
            best_keyword_similarity = keyword_similarity

    reasons: list[str] = []
    penalty_points = 0
    if best_entry is not None:
        if best_keyword_similarity >= 0.93:
            penalty_points += 2
            reasons.append("keyword_rephrase")
        elif best_keyword_similarity >= 0.86:
            penalty_points += 1
            reasons.append("keyword_near_duplicate")

        if (
            best_cluster_similarity >= float(cluster_threshold)
            and best_angle_similarity >= float(angle_threshold)
        ):
            penalty_points += 2
            reasons.append("same_cluster_similar_angle")
        elif best_cluster_similarity >= float(cluster_threshold):
            reasons.append("same_cluster_different_angle_allowed")

    novelty_score = max(0.0, round(100.0 - (best_overlap * 100.0) - (penalty_points * 8.0), 1))
    return {
        "novelty_score": novelty_score,
        "penalty_points": penalty_points,
        "penalty_reason": "|".join(reasons),
        "matched_history_item": (
            {
                "keyword": best_entry.keyword,
                "topic_cluster": best_entry.topic_cluster,
                "topic_angle": best_entry.topic_angle,
                "category": best_entry.category,
                "profile": best_entry.profile,
                "blog": best_entry.blog,
                "published_at": best_entry.published_at,
                "source": best_entry.source,
            }
            if best_entry is not None
            else {}
        ),
        "similarity": {
            "keyword": round(best_keyword_similarity, 3),
            "cluster": round(best_cluster_similarity, 3),
            "angle": round(best_angle_similarity, 3),
            "overlap": round(best_overlap, 3),
        },
    }


def _collect_sheet_exclusion_entries(
    *,
    rows: list[list[str]],
    require_cluster_angle: bool,
    include_category: bool,
    limit: int,
    lookback_days: int = DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS,
    profile_key: str = "",
    blog_name: str = "",
    source: str = "sheet",
) -> list[str]:
    entries = _collect_sheet_topic_history_entries(
        rows=rows,
        lookback_days=lookback_days,
        limit=limit,
        profile_key=profile_key,
        blog_name=blog_name,
        source=source,
    )

    exclusions: list[str] = []
    for entry in entries:
        if require_cluster_angle and (not entry.topic_cluster or not entry.topic_angle):
            continue
        if require_cluster_angle and (
            _is_noise_topic_value(entry.topic_cluster) or _is_noise_topic_value(entry.topic_angle)
        ):
            continue
        exclusions.append(_history_entry_display_value(entry, include_category=include_category))
        if len(exclusions) >= max(limit, 1):
            break
    return exclusions


def build_sheet_topic_exclusion_prompt(
    db: Session,
    *,
    profile_key: str,
    blog_name: str = "",
    lookback_days: int = DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS,
    limit: int = 28,
) -> str:
    history = list_sheet_topic_history_entries(
        db,
        profile_key=profile_key,
        blog_name=blog_name,
        lookback_days=lookback_days,
        limit=limit,
    )
    exclusions = [_history_entry_display_value(entry, include_category=False) for entry in history]
    if not exclusions:
        return ""
    bullet_list = "\n".join(f"- {value}" for value in exclusions)
    return (
        "\n\nHard exclusion list from Google Sheet review memory.\n"
        "Do not rephrase or lightly rewrite items below.\n"
        "If the main topic cluster overlaps, choose a clearly different angle and user intent.\n"
        f"{bullet_list}"
    )


def list_sheet_topic_history_entries(
    db: Session,
    *,
    profile_key: str,
    blog_name: str = "",
    lookback_days: int = DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS,
    limit: int = 120,
) -> list[TopicHistoryEntry]:
    config = get_google_sheet_sync_config(db)
    sheet_id = _safe_str(config.get("sheet_id"))
    if not sheet_id:
        return []

    tab_name = _resolve_blogger_tab_by_profile(profile_key=profile_key, config=config)
    try:
        rows = _read_sheet_rows(db, sheet_id=sheet_id, tab_name=tab_name)
    except (BloggerOAuthError, httpx.HTTPError):
        return []

    return _collect_sheet_topic_history_entries(
        rows=rows,
        lookback_days=lookback_days,
        limit=limit,
        profile_key=profile_key,
        blog_name=blog_name,
        source="sheet_blogger",
    )


def list_sheet_topic_exclusions_cloudflare(
    db: Session,
    *,
    lookback_days: int = DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS,
    limit: int = 120,
) -> list[str]:
    entries = list_sheet_topic_history_entries_cloudflare(
        db,
        lookback_days=lookback_days,
        limit=limit,
    )
    return [_history_entry_display_value(entry, include_category=True) for entry in entries]


def list_sheet_topic_history_entries_cloudflare(
    db: Session,
    *,
    lookback_days: int = DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS,
    limit: int = 120,
) -> list[TopicHistoryEntry]:
    config = get_google_sheet_sync_config(db)
    sheet_id = _safe_str(config.get("sheet_id"))
    if not sheet_id:
        return []

    tab_name = _safe_str(config.get("cloudflare_tab")) or "?대씪?곕뱶?뚮젅?대툝濡쒓렇"
    try:
        rows = _read_sheet_rows(db, sheet_id=sheet_id, tab_name=tab_name)
    except (BloggerOAuthError, httpx.HTTPError):
        return []

    entries = _collect_sheet_topic_history_entries(
        rows=rows,
        lookback_days=lookback_days,
        limit=limit,
        source="sheet_cloudflare",
    )
    filtered: list[TopicHistoryEntry] = []
    for entry in entries:
        if not entry.topic_cluster or not entry.topic_angle:
            continue
        if _is_noise_topic_value(entry.topic_cluster) or _is_noise_topic_value(entry.topic_angle):
            continue
        filtered.append(entry)
        if len(filtered) >= max(limit, 1):
            break
    return filtered


def build_sheet_topic_exclusion_prompt_cloudflare(
    db: Session,
    *,
    lookback_days: int = DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS,
    limit: int = 36,
) -> str:
    exclusions = list_sheet_topic_exclusions_cloudflare(
        db,
        lookback_days=lookback_days,
        limit=limit,
    )
    if not exclusions:
        return ""

    bullet_list = "\n".join(f"- {value}" for value in exclusions)
    return (
        "\n\nHard exclusion list from Cloudflare sheet history.\n"
        "Do not rephrase existing topics below.\n"
        "If cluster overlaps, enforce a clearly different angle and user task.\n"
        f"{bullet_list}"
    )


def get_google_sheet_sync_config(db: Session) -> dict[str, str]:
    values = get_settings_map(db)
    sheet_sync_enabled = _is_enabled(values.get("sheet_sync_enabled"), default=False)
    return {
        "sheet_id": _extract_sheet_id(values) if sheet_sync_enabled else "",
        "travel_tab": (values.get("google_sheet_travel_tab") or "援ш?釉붾줈洹?").strip() or "援ш?釉붾줈洹?",
        "mystery_tab": (values.get("google_sheet_mystery_tab") or "援ш?釉붾줈洹?").strip() or "援ш?釉붾줈洹?",
        "cloudflare_tab": (values.get("google_sheet_cloudflare_tab") or "?대씪?곕뱶?뚮젅?대툝濡쒓렇").strip() or "?대씪?곕뱶?뚮젅?대툝濡쒓렇",
        "cloudflare_category_tabs_enabled": (values.get("google_sheet_cloudflare_category_tabs_enabled") or "false").strip() or "false",
        "auto_format_enabled": (values.get("google_sheet_auto_format_enabled") or "true").strip() or "true",
        "content_overview_tab": (values.get("content_overview_tab") or "?꾩껜 湲 ?꾪솴").strip() or "?꾩껜 湲 ?꾪솴",
    }


def merge_sheet_rows_with_existing(
    *,
    existing_rows: list[list[str]] | None,
    incoming_rows: list[dict[str, Any]],
    base_columns: Sequence[str],
    quality_columns: Sequence[str] = QUALITY_COLUMNS,
    key_columns: Sequence[str] = ("url", "slug"),
) -> list[list[str]]:
    normalized_existing = list(existing_rows or [])
    existing_header_raw = [column for column in (normalized_existing[0] if normalized_existing else []) if _safe_str(column)]
    existing_header: list[str] = []
    for column in existing_header_raw:
        normalized_column = _normalize_column_key(column)
        if normalized_column and normalized_column not in existing_header:
            existing_header.append(normalized_column)
    if not existing_header:
        existing_header = [_safe_str(column) for column in base_columns if _safe_str(column)]
    merged_header = _build_merged_header(
        existing_header=existing_header,
        base_columns=base_columns,
        quality_columns=quality_columns,
    )

    existing_records_by_key: dict[str, dict[str, str]] = {}
    existing_record_order: list[str] = []
    existing_orphan_records: list[dict[str, str]] = []
    for row in normalized_existing[1:]:
        record = _hydrate_summary_alias(
            {header: _safe_str(row[index] if index < len(row) else "") for index, header in enumerate(existing_header)}
        )
        record_key = _merge_record_key(record, key_columns=key_columns)
        if record_key:
            if record_key not in existing_records_by_key:
                existing_record_order.append(record_key)
            existing_records_by_key[record_key] = record
        elif any(_safe_str(value) for value in record.values()):
            existing_orphan_records.append(record)

    merged_records: list[dict[str, str]] = []
    consumed_existing_keys: set[str] = set()
    for row_data in incoming_rows:
        normalized_row = _hydrate_summary_alias(
            {
                _normalize_column_key(_safe_str(key)): _safe_str(value)
                for key, value in row_data.items()
                if _safe_str(key)
            }
        )
        record_key = _merge_record_key(normalized_row, key_columns=key_columns)
        merged_record = dict(existing_records_by_key.get(record_key, {})) if record_key else {}
        if record_key:
            consumed_existing_keys.add(record_key)
        for column in base_columns:
            key = _normalize_column_key(_safe_str(column))
            merged_record[key] = _safe_str(normalized_row.get(key))
        for column in quality_columns:
            key = _normalize_column_key(_safe_str(column))
            if key in normalized_row:
                merged_record[key] = _safe_str(normalized_row.get(key))
        merged_records.append(_apply_priority_fields(merged_record))

    for record_key in existing_record_order:
        if record_key in consumed_existing_keys:
            continue
        record = existing_records_by_key.get(record_key, {})
        merged_records.append(_apply_priority_fields(record))

    for record in existing_orphan_records:
        merged_records.append(_apply_priority_fields(record))

    sorted_records = _sort_sheet_records(merged_records)
    merged_rows: list[list[str]] = [merged_header]
    for record in sorted_records:
        merged_rows.append([_safe_str(record.get(header)) for header in merged_header])

    rendered_rows: list[list[str]] = []
    for row_index, row in enumerate(merged_rows):
        if row_index == 0:
            rendered_rows.append([_display_column_label(cell) for cell in row])
        else:
            rendered_rows.append(row)
    return rendered_rows


def _rows_to_payload(rows: list[list[str]], *, columns: Sequence[str]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for row in rows[1:]:
        payload.append(
            {
                _safe_str(column): _safe_str(row[index] if index < len(row) else "")
                for index, column in enumerate(columns)
                if _safe_str(column)
            }
        )
    return payload


def sync_google_sheet_quality_tab(
    db: Session,
    *,
    sheet_id: str,
    tab_name: str,
    incoming_rows: list[dict[str, Any]],
    base_columns: Sequence[str],
    quality_columns: Sequence[str] = QUALITY_COLUMNS,
    key_columns: Sequence[str] = ("url", "slug"),
    auto_format_enabled: bool = True,
    strict_live_only: bool = False,
    backup_tab_name: str | None = None,
) -> dict[str, str | int]:
    _ensure_sheet_tab_exists(db, sheet_id=sheet_id, tab_name=tab_name)
    existing_rows = _read_sheet_rows(db, sheet_id=sheet_id, tab_name=tab_name)
    if strict_live_only:
        existing_header, existing_records = _records_from_sheet_rows(existing_rows)
        incoming_by_key: dict[str, dict[str, str]] = {}
        for row_data in incoming_rows:
            normalized_row = _hydrate_summary_alias(
                {
                    _normalize_column_key(_safe_str(key)): _safe_str(value)
                    for key, value in row_data.items()
                    if _safe_str(key)
                }
            )
            if not _is_live_status(_safe_str(normalized_row.get("status"))):
                continue
            record_key = _merge_record_key(normalized_row, key_columns=key_columns)
            if not record_key:
                continue
            current = incoming_by_key.get(record_key)
            if current is None or _prefer_live_record(normalized_row, current):
                incoming_by_key[record_key] = normalized_row

        merged_header = _build_merged_header(
            existing_header=existing_header or [_safe_str(column) for column in base_columns if _safe_str(column)],
            base_columns=base_columns,
            quality_columns=quality_columns,
        )

        batch_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup_tab = _safe_str(backup_tab_name) or f"{tab_name}_BACKUP"
        backup_columns = _build_backup_columns(base_columns, quality_columns)
        now_kst = datetime.now(KST).replace(microsecond=0).isoformat()

        existing_by_key: dict[str, list[dict[str, str]]] = {}
        existing_orphans: list[dict[str, str]] = []
        for record in existing_records:
            record_key = _merge_record_key(record, key_columns=key_columns)
            if record_key:
                existing_by_key.setdefault(record_key, []).append(record)
            else:
                existing_orphans.append(record)

        backup_rows: list[dict[str, str]] = []
        removed_dead_count = 0
        removed_duplicate_count = 0

        for record in existing_orphans:
            raw_row = {column: _safe_str(record.get(column)) for column in set([*base_columns, *quality_columns, *record.keys()])}
            raw_json = json.dumps(raw_row, ensure_ascii=False, sort_keys=True)
            source_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()[:16]
            payload = {column: "" for column in backup_columns}
            payload.update(
                {
                    "backup_batch_id": batch_id,
                    "backup_moved_at": now_kst,
                    "backup_source_tab": tab_name,
                    "backup_reason": "orphan_sheet_row",
                    "backup_reason_detail": "missing_identity_key",
                    "canonical_key": "",
                    "source_status_at_backup": _safe_str(record.get("status")),
                    "source_hash": source_hash,
                    "raw_row_json": raw_json,
                }
            )
            for column in [*base_columns, *quality_columns]:
                payload[_normalize_column_key(_safe_str(column))] = _safe_str(record.get(_normalize_column_key(_safe_str(column))))
            backup_rows.append(payload)
            removed_dead_count += 1

        for record_key, records in existing_by_key.items():
            if record_key in incoming_by_key:
                duplicate_rows = records[1:] if len(records) > 1 else []
                for record in duplicate_rows:
                    raw_row = {column: _safe_str(record.get(column)) for column in set([*base_columns, *quality_columns, *record.keys()])}
                    raw_json = json.dumps(raw_row, ensure_ascii=False, sort_keys=True)
                    source_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()[:16]
                    payload = {column: "" for column in backup_columns}
                    payload.update(
                        {
                            "backup_batch_id": batch_id,
                            "backup_moved_at": now_kst,
                            "backup_source_tab": tab_name,
                            "backup_reason": "duplicate_existing_row",
                            "backup_reason_detail": "same_canonical_key",
                            "canonical_key": record_key,
                            "source_status_at_backup": _safe_str(record.get("status")),
                            "source_hash": source_hash,
                            "raw_row_json": raw_json,
                        }
                    )
                    for column in [*base_columns, *quality_columns]:
                        payload[_normalize_column_key(_safe_str(column))] = _safe_str(record.get(_normalize_column_key(_safe_str(column))))
                    backup_rows.append(payload)
                    removed_duplicate_count += 1
                continue

            for record in records:
                raw_row = {column: _safe_str(record.get(column)) for column in set([*base_columns, *quality_columns, *record.keys()])}
                raw_json = json.dumps(raw_row, ensure_ascii=False, sort_keys=True)
                source_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()[:16]
                status_at_backup = _safe_str(record.get("status"))
                reason = "non_live_status" if not _is_live_status(status_at_backup) else "not_in_live_source"
                payload = {column: "" for column in backup_columns}
                payload.update(
                    {
                        "backup_batch_id": batch_id,
                        "backup_moved_at": now_kst,
                        "backup_source_tab": tab_name,
                        "backup_reason": reason,
                        "backup_reason_detail": "strict_live_only_mismatch",
                        "canonical_key": record_key,
                        "source_status_at_backup": status_at_backup,
                        "source_hash": source_hash,
                        "raw_row_json": raw_json,
                    }
                )
                for column in [*base_columns, *quality_columns]:
                    payload[_normalize_column_key(_safe_str(column))] = _safe_str(record.get(_normalize_column_key(_safe_str(column))))
                backup_rows.append(payload)
                removed_dead_count += 1

        try:
            backup_appended_count = _append_backup_rows(
                db,
                sheet_id=sheet_id,
                backup_tab_name=backup_tab,
                backup_rows=backup_rows,
                backup_columns=backup_columns,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "tab": tab_name,
                "backup_tab": backup_tab,
                "sync_mode": "strict_live_only",
                "reason": f"backup_failed:{exc}",
                "live_source_count": len(incoming_rows),
                "incoming_unique_count": len(incoming_by_key),
                "existing_main_count_before": len(existing_records),
                "removed_dead_count": removed_dead_count,
                "removed_duplicate_count": removed_duplicate_count,
                "written_main_count": 0,
                "final_main_count": max(len(existing_rows) - 1, 0),
                "count_match": False,
                "mismatch_reason": "backup_write_failed",
            }

        backup_report = _write_backup_report(
            tab_name=tab_name,
            backup_tab_name=backup_tab,
            batch_id=batch_id,
            backup_rows=backup_rows,
        )

        strict_records = [_apply_priority_fields(record) for record in incoming_by_key.values()]
        strict_records = _sort_sheet_records(strict_records)
        strict_rows: list[list[str]] = [[_display_column_label(column) for column in merged_header]]
        for record in strict_records:
            strict_rows.append([_safe_str(record.get(column)) for column in merged_header])

        _clear_sheet_tab(db, sheet_id=sheet_id, tab_name=tab_name)
        _write_sheet_rows(db, sheet_id=sheet_id, tab_name=tab_name, rows=strict_rows)
        if auto_format_enabled and strict_rows:
            _apply_sheet_operational_format(
                db,
                sheet_id=sheet_id,
                tab_name=tab_name,
                header_row=strict_rows[0],
                row_count=len(strict_rows),
            )
        final_count = max(len(strict_rows) - 1, 0)
        expected_count = len(incoming_by_key)
        count_match = final_count == expected_count
        return {
            "status": "ok" if count_match else "failed",
            "tab": tab_name,
            "backup_tab": backup_tab,
            "sync_mode": "strict_live_only",
            "live_source_count": len(incoming_rows),
            "incoming_unique_count": expected_count,
            "existing_main_count_before": len(existing_records),
            "backup_appended_count": backup_appended_count,
            "removed_dead_count": removed_dead_count,
            "removed_duplicate_count": removed_duplicate_count,
            "written_main_count": final_count,
            "final_main_count": final_count,
            "count_match": count_match,
            "mismatch_reason": "" if count_match else "final_count_mismatch",
            "backup_report": backup_report,
            "rows": final_count,
            "columns": len(merged_header),
        }

    merged_rows = merge_sheet_rows_with_existing(
        existing_rows=existing_rows,
        incoming_rows=incoming_rows,
        base_columns=base_columns,
        quality_columns=quality_columns,
        key_columns=key_columns,
    )
    _clear_sheet_tab(db, sheet_id=sheet_id, tab_name=tab_name)
    _write_sheet_rows(db, sheet_id=sheet_id, tab_name=tab_name, rows=merged_rows)
    if auto_format_enabled and merged_rows:
        _apply_sheet_operational_format(
            db,
            sheet_id=sheet_id,
            tab_name=tab_name,
            header_row=merged_rows[0],
            row_count=len(merged_rows),
        )
    return {
        "status": "ok",
        "tab": tab_name,
        "rows": max(len(merged_rows) - 1, 0),
        "columns": len(merged_rows[0]) if merged_rows else 0,
    }


def _build_blogger_rows(db: Session, *, profile_key: str) -> tuple[list[list[str]], int]:
    rows = [[_display_column_label(column) for column in BLOGGER_SNAPSHOT_COLUMNS]]
    query = (
        select(Article, Blog, BloggerPost)
        .join(Blog, Blog.id == Article.blog_id)
        .outerjoin(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Blog.profile_key == profile_key)
        .order_by(Article.created_at.desc())
    )
    data = db.execute(query).all()
    updated_articles = 0
    for article, blog, blogger_post in data:
        labels = article.labels if isinstance(article.labels, list) else []
        category_label = _safe_str(getattr(article, "editorial_category_label", None))
        category_key = _safe_str(getattr(article, "editorial_category_key", None))
        original_category_label = category_label
        original_category_key = category_key
        if not category_label and article.topic is not None:
            category_label = _safe_str(getattr(article.topic, "editorial_category_label", None))
        if not category_key and article.topic is not None:
            category_key = _safe_str(getattr(article.topic, "editorial_category_key", None))
        if not category_key or not category_label:
            inferred_key, inferred_label = _infer_editorial_category(
                profile_key=profile_key,
                labels=[_safe_str(label) for label in labels],
                title=_safe_str(article.title),
                summary=_safe_str(article.excerpt),
            )
            category_key = category_key or inferred_key
            category_label = category_label or inferred_label
        if category_key and category_label and (category_key != original_category_key or category_label != original_category_label):
            article.editorial_category_key = category_key
            article.editorial_category_label = category_label
            db.add(article)
            updated_articles += 1
        rows.append(
            [
                _format_datetime(article.created_at),
                _safe_str(blog.profile_key),
                _safe_str(blog.name),
                _safe_str(article.title),
                _safe_str(blogger_post.published_url if blogger_post else ""),
                _safe_str(article.slug),
                _safe_str(article.excerpt),
                ", ".join(_safe_str(label) for label in labels if _safe_str(label)),
                _safe_str(blogger_post.post_status.value if blogger_post else "draft"),
                _format_datetime(blogger_post.published_at if blogger_post else None),
                _format_datetime(article.updated_at),
                category_label,
                category_key,
            ]
        )
    if updated_articles:
        db.commit()
    return rows, max(len(rows) - 1, 0)


def _build_cloudflare_rows(db: Session) -> tuple[list[list[str]], int]:
    from app.services.cloudflare_channel_service import list_cloudflare_posts
    from app.services.content_ops_service import compute_dbs_score, compute_seo_geo_scores, compute_similarity_analysis

    columns = [*CLOUDFLARE_SNAPSHOT_COLUMNS, *QUALITY_COLUMNS]
    rows = [[_display_column_label(column) for column in columns]]
    posts = list_cloudflare_posts(db)
    records: list[dict[str, str]] = []
    for index, post in enumerate(posts, start=1):
        category_name = _safe_str(post.get("category_name"))
        category_slug = _safe_str(post.get("category_slug"))
        category_cell = category_name or _safe_str(post.get("channel_name"))
        status_value = _safe_str(post.get("status")).lower() or "published"
        created_at = _normalize_datetime_text(post.get("created_at"))
        updated_at = _normalize_datetime_text(post.get("updated_at"))
        published_at = _normalize_datetime_text(post.get("published_at"))
        if not published_at and status_value in {"published", "live"}:
            published_at = updated_at or created_at
        record = {
            "key": f"cf-{index}",
            "published_at": published_at,
            "created_at": created_at,
            "updated_at": updated_at,
            "due_at": published_at or updated_at or created_at,
            "category": category_cell,
            "category_slug": category_slug,
            "remote_id": _safe_str(post.get("remote_id")),
            "title": _safe_str(post.get("title")),
            "url": _safe_str(post.get("published_url")),
            "excerpt": _safe_str(post.get("excerpt")),
            "labels": ", ".join(_safe_str(label) for label in (post.get("labels") or []) if _safe_str(label)),
            "status": status_value,
            "topic_cluster": category_slug or category_cell or "cloudflare",
            "topic_angle": "channel_post",
            "similarity_score": "",
            "most_similar_url": "",
            "seo_score": "",
            "geo_score": "",
            "quality_status": "",
            "rewrite_attempts": "0",
            "last_audited_at": _format_datetime(datetime.now(ZoneInfo("Asia/Seoul"))),
        }
        records.append(record)

    if records:
        similarity_map = compute_similarity_analysis(
            [
                {
                    "key": record["key"],
                    "title": record["title"],
                    "body_html": f"<p>{record['excerpt']}</p>",
                    "url": record["url"],
                }
                for record in records
            ]
        )
        for record in records:
            similarity_payload = similarity_map.get(record["key"], {"similarity_score": 0.0, "most_similar_url": ""})
            score_payload = compute_seo_geo_scores(
                title=record["title"],
                html_body=f"<p>{record['excerpt']}</p>",
                excerpt=record["excerpt"],
                faq_section=[],
            )
            record["similarity_score"] = f"{float(similarity_payload.get('similarity_score', 0.0)):.1f}"
            record["most_similar_url"] = _safe_str(similarity_payload.get("most_similar_url"))
            record["seo_score"] = str(int(score_payload["seo_score"]))
            record["geo_score"] = str(int(score_payload["geo_score"]))
            record["ctr_score"] = str(int(score_payload.get("ctr_score") or 0))
            dbs_payload = compute_dbs_score(
                seo_score=float(score_payload["seo_score"]),
                geo_score=float(score_payload["geo_score"]),
                ctr_score=float(score_payload.get("ctr_score") or 0),
                plain_text_length=int(score_payload.get("plain_text_length") or 0),
                sentence_count=int(score_payload.get("sentence_count") or 0),
                excerpt_length=int(score_payload.get("excerpt_length") or 0),
            )
            record["dbs_score"] = f"{float(dbs_payload.get('dbs_score') or 0):.1f}"
            record["dbs_grade"] = _safe_str(dbs_payload.get("dbs_grade"))
            record["dbs_confidence"] = f"{float(dbs_payload.get('dbs_confidence') or 0):.1f}"
            record["dbs_version"] = _safe_str(dbs_payload.get("dbs_version"))
            record["quality_status"] = "ok" if record["status"] in {"published", "live"} else "DISLIVE"

    records.sort(
        key=lambda row: (
            _safe_str(row.get("published_at")) or _safe_str(row.get("updated_at")) or _safe_str(row.get("created_at")),
            _safe_str(row.get("title")),
        ),
        reverse=True,
    )

    for record in records:
        rows.append([_safe_str(record.get(column)) for column in columns])
    return rows, max(len(rows) - 1, 0)


def _sync_tab(db: Session, *, sheet_id: str, tab_name: str, rows: list[list[str]]) -> dict[str, str | int]:
    _ensure_sheet_tab_exists(db, sheet_id=sheet_id, tab_name=tab_name)
    _clear_sheet_tab(db, sheet_id=sheet_id, tab_name=tab_name)
    _write_sheet_rows(db, sheet_id=sheet_id, tab_name=tab_name, rows=rows)
    return {
        "status": "ok",
        "tab": tab_name,
        "rows": max(len(rows) - 1, 0),
    }


def sync_google_sheet_snapshot(db: Session, *, initial: bool = False) -> dict:
    sheet_config = get_google_sheet_sync_config(db)
    sheet_id = sheet_config["sheet_id"]
    travel_tab = sheet_config["travel_tab"]
    mystery_tab = sheet_config["mystery_tab"]
    cloudflare_tab = sheet_config["cloudflare_tab"]
    auto_format_enabled = _is_enabled(sheet_config.get("auto_format_enabled"), default=True)
    snapshot_date_kst = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()

    if not sheet_id:
        return {
            "status": "skipped",
            "reason": "google_sheet_not_configured",
            "sheet_id": "",
            "initial": initial,
            "snapshot_date_kst": snapshot_date_kst,
            "travel_blog_id": 0,
            "mystery_blog_id": 0,
            "travel_rows": 0,
            "mystery_rows": 0,
            "cloudflare_rows": 0,
            "travel_tab": travel_tab,
            "mystery_tab": mystery_tab,
            "cloudflare_tab": cloudflare_tab,
        }

    travel_rows, travel_count = _build_blogger_rows(db, profile_key="korea_travel")
    mystery_rows, mystery_count = _build_blogger_rows(db, profile_key="world_mystery")
    cloudflare_rows, cloudflare_count = _build_cloudflare_rows(db)

    tab_results: dict[str, dict[str, str | int]] = {}
    try:
        tab_results["travel"] = sync_google_sheet_quality_tab(
            db,
            sheet_id=sheet_id,
            tab_name=travel_tab,
            incoming_rows=_rows_to_payload(travel_rows, columns=BLOGGER_SNAPSHOT_COLUMNS),
            base_columns=BLOGGER_SNAPSHOT_COLUMNS,
            quality_columns=QUALITY_COLUMNS,
            key_columns=("url", "slug"),
            auto_format_enabled=auto_format_enabled,
        )
        tab_results["mystery"] = sync_google_sheet_quality_tab(
            db,
            sheet_id=sheet_id,
            tab_name=mystery_tab,
            incoming_rows=_rows_to_payload(mystery_rows, columns=BLOGGER_SNAPSHOT_COLUMNS),
            base_columns=BLOGGER_SNAPSHOT_COLUMNS,
            quality_columns=QUALITY_COLUMNS,
            key_columns=("url", "slug"),
            auto_format_enabled=auto_format_enabled,
        )
        tab_results["cloudflare"] = sync_google_sheet_quality_tab(
            db,
            sheet_id=sheet_id,
            tab_name=cloudflare_tab,
            incoming_rows=_rows_to_payload(cloudflare_rows, columns=[*CLOUDFLARE_SNAPSHOT_COLUMNS, *QUALITY_COLUMNS]),
            base_columns=CLOUDFLARE_SNAPSHOT_COLUMNS,
            quality_columns=QUALITY_COLUMNS,
            key_columns=("url", "remote_id", "title"),
            auto_format_enabled=auto_format_enabled,
        )
    except BloggerOAuthError as exc:
        return {
            "status": "failed",
            "reason": "google_oauth_error",
            "detail": exc.detail,
            "sheet_id": sheet_id,
            "initial": initial,
            "snapshot_date_kst": snapshot_date_kst,
            "travel_rows": travel_count,
            "mystery_rows": mystery_count,
            "cloudflare_rows": cloudflare_count,
            "travel_tab": travel_tab,
            "mystery_tab": mystery_tab,
            "cloudflare_tab": cloudflare_tab,
        }
    except httpx.HTTPError as exc:
        detail = str(exc)
        if hasattr(exc, "response") and exc.response is not None:
            detail = f"{detail}: {exc.response.text}"
        return {
            "status": "failed",
            "reason": "google_sheet_http_error",
            "detail": detail,
            "sheet_id": sheet_id,
            "initial": initial,
            "snapshot_date_kst": snapshot_date_kst,
            "travel_rows": travel_count,
            "mystery_rows": mystery_count,
            "cloudflare_rows": cloudflare_count,
            "travel_tab": travel_tab,
            "mystery_tab": mystery_tab,
            "cloudflare_tab": cloudflare_tab,
        }

    return {
        "status": "ok",
        "sheet_id": sheet_id,
        "initial": initial,
        "snapshot_date_kst": snapshot_date_kst,
        "travel_blog_id": 0,
        "mystery_blog_id": 0,
        "travel_rows": travel_count,
        "mystery_rows": mystery_count,
        "cloudflare_rows": cloudflare_count,
        "travel_tab": travel_tab,
        "mystery_tab": mystery_tab,
        "cloudflare_tab": cloudflare_tab,
        "tab_results": tab_results,
    }
