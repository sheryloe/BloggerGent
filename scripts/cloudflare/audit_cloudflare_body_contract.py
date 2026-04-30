from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from sqlalchemy import select


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

RUNTIME_ROOT = Path(os.getenv("BLOGGENT_RUNTIME_ROOT", r"D:\Donggri_Runtime\BloggerGent"))
OUT_ROOT = RUNTIME_ROOT / "Rool" / "30-cloudflare" / "12-category-layout-refactor" / "body-contract-audit"
CHANNEL_ID = "cloudflare:dongriarchive"
MIN_KOREAN_SYLLABLES = 2000
MAX_CANDIDATE_COUNT = 25
DEVELOPMENT_REQUIRED_FACT_TERMS = ("공식", "버전", "도구", "워크플로우")

CODE_BLOCK_RE = re.compile(r"```.*?```", re.S)
URL_RE = re.compile(r"https?://\S+", re.I)
TAG_RE = re.compile(r"<[^>]+>")
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
H2_RE = re.compile(r"<\s*h2\b|^\s*##\s+", re.I | re.M)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)", re.I | re.S)
CF_IMAGE_SLOT_RE = re.compile(r"data-cf-image-slot\s*=\s*['\"]([^'\"]+)['\"]", re.I)
HTML_COMMENT_SLOT_RE = re.compile(r"<!--\s*CF_IMAGE_SLOT\s*:\s*([^>]+?)\s*-->", re.I)
MOJIBAKE_MARKER_RE = re.compile(
    r"[\ufffdÃÂ]|ì[^\s]{0,2}|í[^\s]{0,2}|ê[^\s]{0,2}|ë[^\s]{0,2}|"
    r"[媛怨湲쒕꾨猷諛蹂臾誘二쇱섏띠먮꾩꽑吏]",
    re.I,
)

FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("h1", re.compile(r"<\s*h1\b|^\s*#\s+", re.I | re.M), "P0"),
    ("script", re.compile(r"<\s*script\b", re.I), "P0"),
    ("iframe", re.compile(r"<\s*iframe\b", re.I), "P0"),
    ("img", re.compile(r"<\s*img\b", re.I), "P0"),
    ("figure", re.compile(r"<\s*figure\b", re.I), "P0"),
    ("markdown_image", MARKDOWN_IMAGE_RE, "P0"),
    ("inline_style", re.compile(r"\sstyle\s*=", re.I), "P0"),
    (
        "adsense_token",
        re.compile(
            r"adsbygoogle|data-ad-client|ca-pub-|googlesyndication|doubleclick|<!--\s*adsense|\[ad_slot",
            re.I,
        ),
        "P0",
    ),
    ("outer_layout_wrapper", re.compile(r"editorial-shell|post-detail|page-hero|adsense-slot", re.I), "P1"),
)

CATEGORY_ALIASES: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    "개발과-프로그래밍": ("cf-body--technical", "development", False, ("공식", "버전", "도구", "워크플로우")),
    "gaebalgwa-peurogeuraeming": ("cf-body--technical", "development", False, ("공식", "버전", "도구", "워크플로우")),
    "일상과-메모": ("cf-body--record-note", "daily-memo", False, ("장면", "생각", "루틴")),
    "ilsanggwa-memo": ("cf-body--record-note", "daily-memo", False, ("장면", "생각", "루틴")),
    "여행과-기록": ("cf-body--record-note", "travel-record", False, ("장소", "동선", "시간")),
    "yeohaenggwa-girog": ("cf-body--record-note", "travel-record", False, ("장소", "동선", "시간")),
    "동그리의-생각": ("cf-body--record-note", "thought", False, ("질문", "사회", "생각")),
    "donggeuriyi-saenggag": ("cf-body--record-note", "thought", False, ("질문", "사회", "생각")),
    "미스테리아-스토리": ("cf-body--mysteria-dossier", "mysteria", False, ("사건", "증거", "기록")),
    "miseuteria-seutori": ("cf-body--mysteria-dossier", "mysteria", False, ("사건", "증거", "기록")),
    "시장의-기록": ("cf-body--market", "market", False, ("기준일", "리스크", "지표")),
    "market-record": ("cf-body--market", "market", False, ("기준일", "리스크", "지표")),
    "주식의-흐름": ("cf-body--market", "market", False, ("기준일", "종목", "리스크")),
    "jusigyi-heureum": ("cf-body--market", "market", False, ("기준일", "종목", "리스크")),
    "크립토의-흐름": ("cf-body--market", "market", False, ("기준일", "프로토콜", "리스크")),
    "keuribtoyi-heureum": ("cf-body--market", "market", False, ("기준일", "프로토콜", "리스크")),
    "나스닥의-흐름": ("cf-body--market", "market", False, ("기준일", "기업", "리스크")),
    "naseudagyi-heureum": ("cf-body--market", "market", False, ("기준일", "기업", "리스크")),
    "정보의-기록": ("cf-body--field-guide", "info", False, ("공식", "장소", "기간")),
    "info-record": ("cf-body--field-guide", "info", False, ("공식", "장소", "기간")),
    "축제와-현장": ("cf-body--field-guide", "festival-field", True, ("기간", "장소", "운영", "동선")),
    "cugjewa-hyeonjang": ("cf-body--field-guide", "festival-field", True, ("기간", "장소", "운영", "동선")),
    "문화와-공간": ("cf-body--field-guide", "culture-space", True, ("기간", "장소", "운영", "관람")),
    "munhwawa-gonggan": ("cf-body--field-guide", "culture-space", True, ("기간", "장소", "운영", "관람")),
    "생활의-기록": ("cf-body--utility", "life", False, ("대상", "방법", "주의")),
    "life-record": ("cf-body--utility", "life", False, ("대상", "방법", "주의")),
    "삶의-기름칠": ("cf-body--utility", "life-benefit", False, ("기관", "자격", "신청", "기간")),
    "salmyi-gireumcil": ("cf-body--utility", "life-benefit", False, ("기관", "자격", "신청", "기간")),
    "salmeui-gireumchil": ("cf-body--utility", "life-benefit", False, ("기관", "자격", "신청", "기간")),
    "삶을-유용하게": ("cf-body--utility", "life-useful", False, ("대상", "방법", "도구", "주의")),
    "salmeul-yuyonghage": ("cf-body--utility", "life-useful", False, ("대상", "방법", "도구", "주의")),
}


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
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_slug(value: Any) -> str:
    text = _safe_text(value).lower()
    if not text:
        return ""
    try:
        return unquote(text).strip().lower()
    except Exception:  # noqa: BLE001
        return text


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


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _infer_batch_id(candidate_csv: str | None, explicit_batch_id: str | None = None) -> str:
    if explicit_batch_id:
        return re.sub(r"[^a-zA-Z0-9_-]+", "-", explicit_batch_id).strip("-") or "batch-001"
    if candidate_csv:
        stem = Path(candidate_csv).stem
        if stem.startswith("cf-body-"):
            return stem
    return "batch-001"


def _packet_root_for_batch(batch_id: str) -> Path:
    return OUT_ROOT / "body-contract-refactor-packets" / batch_id


def _assert_child_path(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    resolved_parent = parent.resolve()
    if resolved != resolved_parent and resolved_parent not in resolved.parents:
        raise RuntimeError(f"Refusing to operate outside expected root: {resolved}")


def _reset_generated_json_dir(path: Path) -> None:
    _assert_child_path(path, OUT_ROOT)
    if path.exists():
        for child in path.glob("*.json"):
            if child.is_file():
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def _source_safety_status(*, title: str, content: str) -> tuple[str, list[str]]:
    sample = f"{title}\n{content}"
    reasons: list[str] = []
    if not content.strip():
        return "source_recovery_required", ["content_missing"]
    marker_count = len(MOJIBAKE_MARKER_RE.findall(sample))
    hangul_count = len(HANGUL_RE.findall(sample))
    marker_ratio = marker_count / max(len(sample), 1)
    if marker_count >= 20 or marker_ratio >= 0.015:
        reasons.append(f"mojibake_marker_count={marker_count}")
    if hangul_count < 300:
        reasons.append(f"low_hangul_count={hangul_count}")
    return ("source_recovery_required", reasons) if reasons else ("ready_for_refactor", [])


def _plain_text(value: str) -> str:
    text = CODE_BLOCK_RE.sub(" ", value or "")
    text = MARKDOWN_IMAGE_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def count_korean_syllables_for_body(value: str) -> int:
    text = _plain_text(value)
    text = re.sub(r"[A-Za-z0-9\s\W_]+", "", text)
    return len(HANGUL_RE.findall(text))


def _category_from_detail(detail: dict[str, Any], row: SyncedCloudflarePost) -> str:
    direct = _safe_text(detail.get("categorySlug"))
    if direct:
        return direct
    category = detail.get("category")
    if isinstance(category, dict):
        slug = _safe_text(category.get("slug") or category.get("categorySlug"))
        if slug:
            return slug
    return _safe_text(row.canonical_category_slug or row.category_slug or row.category_name or row.canonical_category_name)


def _category_policy(category_slug: str, row: SyncedCloudflarePost) -> tuple[str, str, bool, tuple[str, ...]]:
    candidates = [
        _normalize_slug(category_slug),
        _normalize_slug(row.canonical_category_slug),
        _normalize_slug(row.category_slug),
        _normalize_slug(row.canonical_category_name),
        _normalize_slug(row.category_name),
    ]
    normalized_map = {_normalize_slug(key): value for key, value in CATEGORY_ALIASES.items()}
    for candidate in candidates:
        if candidate in normalized_map:
            policy = normalized_map[candidate]
            if policy[1] == "development":
                return (policy[0], policy[1], policy[2], DEVELOPMENT_REQUIRED_FACT_TERMS)
            return policy
    return ("cf-body--default", "fallback", False, ())


def required_terms_for_body_class(expected_body_class: str) -> tuple[str, ...]:
    if _safe_text(expected_body_class) == "cf-body--technical":
        return DEVELOPMENT_REQUIRED_FACT_TERMS
    return ()


def _extract_content(detail: dict[str, Any]) -> str:
    for key in ("content", "contentHtml", "content_html", "html_article", "bodyHtml", "body_html", "html"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _fetch_detail(db, remote_post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{remote_post_id}",
        timeout=60.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _slot_issues(content: str, *, allow_inline: bool) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    slots = CF_IMAGE_SLOT_RE.findall(content or "")
    comment_slots = HTML_COMMENT_SLOT_RE.findall(content or "")
    if comment_slots:
        issues.append("comment_image_slot")
    invalid_slots = [slot for slot in slots if slot not in {"inline_1", "inline_2"}]
    if invalid_slots:
        issues.append("invalid_image_slot")
    if slots and not allow_inline:
        issues.append("inline_slot_not_allowed")
    return issues, slots


def _required_fact_hits(content: str, required_terms: tuple[str, ...]) -> list[str]:
    plain = _plain_text(content)
    return [term for term in required_terms if term and term in plain]


def _classify_row(*, content: str, expected_body_class: str, allow_inline: bool, required_terms: tuple[str, ...]) -> dict[str, Any]:
    issue_codes: list[str] = []
    p0 = False
    p1 = False
    for code, pattern, priority in FORBIDDEN_PATTERNS:
        if pattern.search(content or ""):
            issue_codes.append(code)
            if priority == "P0":
                p0 = True
            else:
                p1 = True

    slot_issue_codes, slots = _slot_issues(content, allow_inline=allow_inline)
    issue_codes.extend(slot_issue_codes)
    if any(code in {"comment_image_slot", "invalid_image_slot", "inline_slot_not_allowed"} for code in slot_issue_codes):
        p0 = True

    korean_count = count_korean_syllables_for_body(content)
    h2_count = len(H2_RE.findall(content or ""))
    required_hits = _required_fact_hits(content, required_terms)
    cf_body_classes = sorted(set(re.findall(r"cf-body--[a-z0-9-]+", content or "", flags=re.I)))
    conflicting_body_class = bool(cf_body_classes and expected_body_class not in cf_body_classes)
    if conflicting_body_class:
        issue_codes.append("conflicting_cf_body_class")
        p1 = True
    if korean_count < MIN_KOREAN_SYLLABLES:
        issue_codes.append("korean_syllable_count_below_2000")
        p1 = True
    if h2_count < 3:
        issue_codes.append("h2_count_below_3")
        p1 = True
    if required_terms and len(required_hits) < max(1, min(3, len(required_terms) // 2)):
        issue_codes.append("required_fact_schema_weak")
        p1 = True

    if p0:
        priority = "P0"
    elif p1:
        priority = "P1"
    else:
        priority = "OK"

    return {
        "refactor_priority": priority,
        "issue_codes": sorted(set(issue_codes)),
        "korean_syllable_count": korean_count,
        "h2_count": h2_count,
        "required_fact_hits": required_hits,
        "required_fact_hit_count": len(required_hits),
        "required_fact_total": len(required_terms),
        "content_html_length": len(content or ""),
        "plain_text_length_reference": len(_plain_text(content)),
        "cf_body_classes_in_content": cf_body_classes,
        "image_slots": slots,
        "has_expected_body_class_in_content": expected_body_class in (content or ""),
    }


def _load_posts(db, *, limit: int | None) -> list[SyncedCloudflarePost]:
    managed_channel = (
        db.execute(select(ManagedChannel).where(ManagedChannel.channel_id == CHANNEL_ID))
        .scalars()
        .first()
    )
    query = select(SyncedCloudflarePost).where(SyncedCloudflarePost.status.in_(["published", "live"]))
    if managed_channel is not None:
        query = query.where(SyncedCloudflarePost.managed_channel_id == managed_channel.id)
    query = query.order_by(
        SyncedCloudflarePost.canonical_category_slug.asc().nullslast(),
        SyncedCloudflarePost.published_at.desc().nullslast(),
        SyncedCloudflarePost.id.desc(),
    )
    if limit:
        query = query.limit(limit)
    return db.execute(query).scalars().all()


def run_dry_run(*, limit: int | None = None) -> dict[str, Any]:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with SessionLocal() as db:
        posts = _load_posts(db, limit=limit)
        for index, post in enumerate(posts, 1):
            remote_post_id = _safe_text(post.remote_post_id)
            base_row: dict[str, Any] = {
                "row_no": index,
                "remote_post_id": remote_post_id,
                "slug": _safe_text(post.slug),
                "title": _safe_text(post.title),
                "url": _safe_text(post.url),
                "status": _safe_text(post.status),
                "category_slug": _safe_text(post.canonical_category_slug or post.category_slug),
                "category_name": _safe_text(post.canonical_category_name or post.category_name),
                "article_pattern_id": _safe_text(post.article_pattern_id),
                "article_pattern_version": post.article_pattern_version,
                "seo_score": post.seo_score,
                "geo_score": post.geo_score,
                "lighthouse_score": post.lighthouse_score,
            }
            if not remote_post_id:
                rows.append({**base_row, "refactor_priority": "FETCH_ERROR", "issue_codes": "remote_post_id_missing"})
                continue
            try:
                detail = _fetch_detail(db, remote_post_id)
                content = _extract_content(detail)
                category_slug = _category_from_detail(detail, post)
                expected_body_class, category_family, allow_inline, required_terms = _category_policy(category_slug, post)
                if not content:
                    rows.append(
                        {
                            **base_row,
                            "remote_category_slug": category_slug,
                            "category_family": category_family,
                            "expected_body_class": expected_body_class,
                            "inline_allowed": allow_inline,
                            "refactor_priority": "FETCH_ERROR",
                            "issue_codes": "content_missing",
                        }
                    )
                    continue
                metrics = _classify_row(
                    content=content,
                    expected_body_class=expected_body_class,
                    allow_inline=allow_inline,
                    required_terms=required_terms,
                )
                rows.append(
                    {
                        **base_row,
                        "remote_category_slug": category_slug,
                        "category_family": category_family,
                        "expected_body_class": expected_body_class,
                        "inline_allowed": allow_inline,
                        "refactor_priority": metrics["refactor_priority"],
                        "issue_codes": ";".join(metrics["issue_codes"]),
                        "korean_syllable_count": metrics["korean_syllable_count"],
                        "min_korean_syllable_required": MIN_KOREAN_SYLLABLES,
                        "korean_length_pass": metrics["korean_syllable_count"] >= MIN_KOREAN_SYLLABLES,
                        "h2_count": metrics["h2_count"],
                        "required_fact_hit_count": metrics["required_fact_hit_count"],
                        "required_fact_total": metrics["required_fact_total"],
                        "required_fact_hits": ";".join(metrics["required_fact_hits"]),
                        "content_html_length": metrics["content_html_length"],
                        "plain_text_length_reference": metrics["plain_text_length_reference"],
                        "cf_body_classes_in_content": ";".join(metrics["cf_body_classes_in_content"]),
                        "has_expected_body_class_in_content": metrics["has_expected_body_class_in_content"],
                        "image_slots": ";".join(metrics["image_slots"]),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        **base_row,
                        "refactor_priority": "FETCH_ERROR",
                        "issue_codes": "remote_detail_fetch_failed",
                        "error": f"{type(exc).__name__}: {str(exc)[:220]}",
                    }
                )

    priority_counter = Counter(row.get("refactor_priority") or "UNKNOWN" for row in rows)
    category_counter = Counter(row.get("category_slug") or row.get("remote_category_slug") or "unknown" for row in rows)
    issue_counter: Counter[str] = Counter()
    for row in rows:
        for code in _safe_text(row.get("issue_codes")).split(";"):
            if code:
                issue_counter[code] += 1

    candidates = [
        row
        for row in rows
        if row.get("refactor_priority") in {"P0", "P1"}
    ]
    candidates.sort(
        key=lambda row: (
            0 if row.get("refactor_priority") == "P0" else 1,
            int(row.get("korean_syllable_count") or 999999),
            _safe_text(row.get("category_slug")),
            _safe_text(row.get("slug")),
        )
    )
    candidate_batch = candidates[:MAX_CANDIDATE_COUNT]

    stamp = _stamp()
    audit_csv = OUT_ROOT / f"cloudflare-body-contract-audit-{stamp}.csv"
    audit_json = OUT_ROOT / f"cloudflare-body-contract-audit-{stamp}.json"
    candidate_csv = OUT_ROOT / f"cloudflare-contenthtml-refactor-candidates-batch-001-{stamp}.csv"
    _write_csv(audit_csv, rows)
    _write_csv(OUT_ROOT / "cloudflare-body-contract-audit-latest.csv", rows)
    _write_csv(candidate_csv, candidate_batch)
    _write_csv(OUT_ROOT / "cloudflare-contenthtml-refactor-candidates-batch-001.csv", candidate_batch)

    summary = {
        "mode": "dry_run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_count": len(rows),
        "priority_counts": dict(priority_counter),
        "category_counts": dict(category_counter),
        "issue_counts": dict(issue_counter),
        "candidate_count": len(candidates),
        "candidate_batch_count": len(candidate_batch),
        "audit_csv": str(audit_csv),
        "audit_latest_csv": str(OUT_ROOT / "cloudflare-body-contract-audit-latest.csv"),
        "candidate_csv": str(candidate_csv),
        "candidate_latest_csv": str(OUT_ROOT / "cloudflare-contenthtml-refactor-candidates-batch-001.csv"),
        "mutation_policy": "read_only_no_db_live_r2_writes",
    }
    _write_json(audit_json, {"summary": summary, "rows": rows})
    _write_json(OUT_ROOT / "cloudflare-body-contract-audit-latest.json", {"summary": summary, "rows": rows})
    return summary


def _candidate_csv_path(value: str | None) -> Path:
    if value:
        return Path(value)
    return OUT_ROOT / "cloudflare-contenthtml-refactor-candidates-batch-001.csv"


def _packet_file_name(index: int, row: dict[str, str]) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", _safe_text(row.get("slug"))).strip("-") or f"post-{index:02d}"
    return f"{index:02d}-{slug}.json"


def _detail_category_slug(detail: dict[str, Any], fallback: str) -> str:
    direct = _safe_text(detail.get("categorySlug"))
    if direct:
        return direct
    category = detail.get("category")
    if isinstance(category, dict):
        return _safe_text(category.get("slug") or category.get("categorySlug")) or fallback
    return fallback


def _packet_contract(row: dict[str, str], detail: dict[str, Any], content: str) -> dict[str, Any]:
    category_slug = _safe_text(row.get("remote_category_slug") or row.get("category_slug"))
    normalized_map = {_normalize_slug(key): value for key, value in CATEGORY_ALIASES.items()}
    expected_body_class = _safe_text(row.get("expected_body_class")) or normalized_map.get(_normalize_slug(category_slug), ("cf-body--default", "", False, ()))[0]
    inline_allowed = _safe_text(row.get("inline_allowed")).lower() in {"true", "1", "yes"}
    allowed_slots = ["inline_1", "inline_2"] if inline_allowed else []
    return {
        "goal": "Convert existing Cloudflare live content into the new body-only HTML contract without applying it live.",
        "mutation_policy": "packet_only_do_not_put_do_not_update_db_do_not_upload_r2",
        "preserve": {
            "remote_post_id": _safe_text(row.get("remote_post_id")),
            "slug": _safe_text(row.get("slug") or detail.get("slug")),
            "url": _safe_text(row.get("url")),
            "status": _safe_text(row.get("status") or detail.get("status")),
            "categorySlug": _detail_category_slug(detail, category_slug),
            "coverImage": detail.get("coverImage"),
            "coverAlt": detail.get("coverAlt"),
            "metadata": detail.get("metadata"),
        },
        "body_contract": {
            "root_scope": "body_only_inner_article_content",
            "expected_body_class": expected_body_class,
            "renderer_applies_wrapper_class": True,
            "minimum_korean_syllables": MIN_KOREAN_SYLLABLES,
            "allowed_tags": [
                "section",
                "article",
                "div",
                "aside",
                "blockquote",
                "table",
                "thead",
                "tbody",
                "tr",
                "th",
                "td",
                "details",
                "summary",
                "h2",
                "h3",
                "p",
                "ul",
                "ol",
                "li",
                "strong",
                "em",
                "span",
                "br",
                "hr",
            ],
            "forbidden": [
                "h1",
                "script",
                "iframe",
                "img",
                "figure",
                "markdown_image",
                "inline_style",
                "adsense_tokens",
                "outer_layout_wrappers",
            ],
            "inline_slots_allowed": inline_allowed,
            "allowed_inline_slots": allowed_slots,
            "inline_slot_markup": '<div class="cf-image-slot" data-cf-image-slot="inline_1"></div>',
            "required_fact_terms": list(required_terms_for_body_class(expected_body_class)),
        },
        "rewrite_tasks": [
            "Remove direct image markup and figure wrappers from the body.",
            "Demote or replace any h1 with h2. The public shell owns the only page h1.",
            "Remove inline style attributes and ad/widget tokens.",
            "Keep facts, topic, category, URL, and image URL unchanged.",
            "Preserve useful tables/lists/timelines when they fit the allowed tag list.",
            "If inline slots are not allowed, remove all image slots from body content.",
            "If inline slots are allowed, use only inert data-cf-image-slot placeholders.",
        ],
        "expected_output_shape": {
            "title": "string, unchanged unless the packet explicitly asks for title cleanup",
            "content": "string, rewritten body-only HTML",
            "contentFormat": "blocknote",
            "contentMarkdown": "string, plain Markdown/text fallback derived from the rewritten HTML",
            "excerpt": "string, can be preserved or tightened",
            "seoTitle": "string, preserve if already suitable",
            "seoDescription": "string, preserve if already suitable",
            "tagNames": ["string"],
            "articlePatternId": "string",
            "articlePatternVersion": 4,
            "refactorNotes": "string",
        },
        "current_metrics": {
            "issue_codes": _safe_text(row.get("issue_codes")).split(";") if _safe_text(row.get("issue_codes")) else [],
            "korean_syllable_count": row.get("korean_syllable_count"),
            "h2_count": row.get("h2_count"),
            "content_html_length": row.get("content_html_length") or len(content),
        },
    }


def prepare_refactor_packets(
    *,
    candidate_csv: str | None = None,
    max_count: int = MAX_CANDIDATE_COUNT,
    batch_id: str | None = None,
    clean_packet_root: bool = False,
) -> dict[str, Any]:
    source_path = _candidate_csv_path(candidate_csv)
    resolved_batch_id = _infer_batch_id(candidate_csv, batch_id)
    packet_root = _packet_root_for_batch(resolved_batch_id)
    candidates = _read_csv(source_path)[:max_count]
    if clean_packet_root:
        _reset_generated_json_dir(packet_root)
    else:
        packet_root.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    with SessionLocal() as db:
        for index, row in enumerate(candidates, 1):
            remote_post_id = _safe_text(row.get("remote_post_id"))
            slug = _safe_text(row.get("slug"))
            packet_path = packet_root / _packet_file_name(index, row)
            try:
                if not remote_post_id:
                    raise RuntimeError("remote_post_id_missing")
                detail = _fetch_detail(db, remote_post_id)
                content = _extract_content(detail)
                if not content:
                    raise RuntimeError("content_missing")
                source_status, source_reasons = _source_safety_status(
                    title=_safe_text(detail.get("title") or row.get("title")),
                    content=content,
                )
                if source_status != "ready_for_refactor":
                    manifest_rows.append(
                        {
                            "batch_id": resolved_batch_id,
                            "batch_order": index,
                            "remote_post_id": remote_post_id,
                            "slug": slug,
                            "category_slug": row.get("category_slug"),
                            "refactor_priority": row.get("refactor_priority"),
                            "issue_codes": row.get("issue_codes"),
                            "packet_path": "",
                            "status": source_status,
                            "source_safety_status": source_status,
                            "source_safety_reasons": "|".join(source_reasons),
                        }
                    )
                    failures.append(
                        {
                            "batch_id": resolved_batch_id,
                            "batch_order": index,
                            "remote_post_id": remote_post_id,
                            "slug": slug,
                            "category_slug": row.get("category_slug"),
                            "status": source_status,
                            "error": "|".join(source_reasons),
                        }
                    )
                    continue
                packet = {
                    "packet_id": f"body-contract-{resolved_batch_id}-{index:02d}-{slug}",
                    "batch_id": resolved_batch_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_candidate": row,
                    "remote_detail": {
                        "id": detail.get("id") or remote_post_id,
                        "slug": detail.get("slug") or slug,
                        "title": detail.get("title"),
                        "content": content,
                        "excerpt": detail.get("excerpt"),
                        "seoTitle": detail.get("seoTitle"),
                        "seoDescription": detail.get("seoDescription"),
                        "status": detail.get("status"),
                        "categorySlug": _detail_category_slug(detail, _safe_text(row.get("remote_category_slug") or row.get("category_slug"))),
                        "coverImage": detail.get("coverImage"),
                        "coverAlt": detail.get("coverAlt"),
                        "tagNames": detail.get("tagNames") or [],
                        "metadata": detail.get("metadata"),
                    },
                    "source_safety": {
                        "status": source_status,
                        "reasons": source_reasons,
                    },
                    "contract": _packet_contract(row, detail, content),
                    "packet_path": str(packet_path),
                }
                _write_json(packet_path, packet)
                manifest_rows.append(
                    {
                        "batch_id": resolved_batch_id,
                        "batch_order": index,
                        "remote_post_id": remote_post_id,
                        "slug": slug,
                        "category_slug": row.get("category_slug"),
                        "refactor_priority": row.get("refactor_priority"),
                        "issue_codes": row.get("issue_codes"),
                        "packet_path": str(packet_path),
                        "status": "packet_ready",
                        "source_safety_status": source_status,
                        "source_safety_reasons": "|".join(source_reasons),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "batch_id": resolved_batch_id,
                        "batch_order": index,
                        "remote_post_id": remote_post_id,
                        "slug": slug,
                        "category_slug": row.get("category_slug"),
                        "refactor_priority": row.get("refactor_priority"),
                        "issue_codes": row.get("issue_codes"),
                        "packet_path": "",
                        "status": "failed",
                        "source_safety_status": "unknown",
                        "source_safety_reasons": "",
                        "error": f"{type(exc).__name__}: {str(exc)[:220]}",
                    }
                )

    stamp = _stamp()
    manifest_path = OUT_ROOT / f"cloudflare-contenthtml-refactor-packet-manifest-{stamp}.csv"
    latest_manifest_path = OUT_ROOT / "cloudflare-contenthtml-refactor-packet-manifest-latest.csv"
    _write_csv(manifest_path, manifest_rows)
    _write_csv(latest_manifest_path, manifest_rows)
    if failures:
        _write_csv(OUT_ROOT / f"cloudflare-contenthtml-refactor-packet-failures-{stamp}.csv", failures)
        _write_csv(OUT_ROOT / "cloudflare-contenthtml-refactor-packet-failures-latest.csv", failures)

    summary = {
        "mode": "prepare_refactor_packets",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": resolved_batch_id,
        "source_candidate_csv": str(source_path),
        "packet_root": str(packet_root),
        "clean_packet_root": clean_packet_root,
        "packet_count": sum(1 for row in manifest_rows if row.get("status") == "packet_ready"),
        "failure_count": len(failures),
        "source_recovery_required_count": sum(
            1 for row in manifest_rows if row.get("status") == "source_recovery_required"
        ),
        "manifest": str(manifest_path),
        "manifest_latest": str(latest_manifest_path),
        "mutation_policy": "packet_only_no_db_live_r2_writes",
    }
    _write_json(OUT_ROOT / f"cloudflare-contenthtml-refactor-packet-summary-{stamp}.json", summary)
    _write_json(OUT_ROOT / "cloudflare-contenthtml-refactor-packet-summary-latest.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run audit for Cloudflare live contentHtml body contract.")
    parser.add_argument("--mode", choices=["dry_run", "prepare_refactor_packets"], required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--candidate-csv", default=None)
    parser.add_argument("--max-count", type=int, default=MAX_CANDIDATE_COUNT)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--clean-packet-root", action="store_true")
    args = parser.parse_args()
    if args.mode == "dry_run":
        result = run_dry_run(limit=args.limit)
    else:
        result = prepare_refactor_packets(
            candidate_csv=args.candidate_csv,
            max_count=args.max_count,
            batch_id=args.batch_id,
            clean_packet_root=args.clean_packet_root,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
