
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TypeVar
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    AnalyticsArticleFact,
    ContentReviewItem,
    GoogleIndexUrlState,
    PublicationRecord,
    QmsAuditFinding,
    QmsCapaAction,
    QmsCapaCase,
    QmsChangeRequest,
    QmsDocument,
    QmsEvidenceItem,
    QmsInternalAudit,
    QmsKpiSnapshot,
    QmsManagementReview,
    QmsReleaseRecord,
    QmsRisk,
    QmsRuntimeScan,
    QmsSupplier,
    SearchConsolePageMetric,
    SyncedBloggerPost,
    SyncedCloudflarePost,
)

RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
QMS_REPORT_DIR = RUNTIME_ROOT / "storage" / "reports" / "qms"
RUNTIME_SCAN_TARGETS = [
    RUNTIME_ROOT / "Rool",
    RUNTIME_ROOT / "env" / "runtime.settings.env",
    RUNTIME_ROOT / "storage" / "reports",
    RUNTIME_ROOT / "storage" / "travel",
    RUNTIME_ROOT / "storage" / "mystery",
    RUNTIME_ROOT / "storage" / "cloudflare",
    RUNTIME_ROOT / "db" / "snapshots",
]
DOC_TEMPLATES = [
    ("quality-policy", "Quality Policy", "phase-1", "ISO 9001:2015 5.2", "operations", "docs/qms/quality-policy.md"),
    ("kpi-definition", "QMS KPI Definition", "phase-1", "ISO 9001:2015 6.2, 9.1", "operations", "docs/qms/kpi-definition.md"),
    ("risk-register-guide", "Risk Register Guide", "phase-2", "ISO 9001:2015 6.1", "quality", "docs/qms/risk-register-guide.md"),
    ("capa-guide", "CAPA Guide", "phase-2", "ISO 9001:2015 10.2", "quality", "docs/qms/capa-guide.md"),
    ("change-control-guide", "Change Control Guide", "phase-3", "ISO 9001:2015 6.3, 8.5.6", "release", "docs/qms/change-control-guide.md"),
    ("release-evidence-guide", "Release Evidence Guide", "phase-3", "ISO 9001:2015 8.6", "release", "docs/qms/release-evidence-guide.md"),
    ("supplier-control-guide", "Supplier Control Guide", "phase-3", "ISO 9001:2015 8.4", "operations", "docs/qms/supplier-control-guide.md"),
    ("internal-audit-guide", "Internal Audit Guide", "phase-4", "ISO 9001:2015 9.2", "quality", "docs/qms/internal-audit-guide.md"),
    ("management-review-guide", "Management Review Guide", "phase-4", "ISO 9001:2015 9.3", "management", "docs/qms/management-review-guide.md"),
    ("certification-evidence-index", "Certification Evidence Index", "phase-4", "ISO 9001:2015 7.5", "quality", "docs/qms/certification-evidence-index.md"),
]
SUPPLIER_DEFAULTS = [
    ("openai", "OpenAI", "api", "Text/Image generation and model telemetry"),
    ("google", "Google", "api", "Blogger, Search Console, Analytics, Indexing"),
    ("cloudflare", "Cloudflare", "platform", "R2, Workers, Pages and channel assets"),
    ("github", "GitHub", "platform", "Source control, releases and CI evidence"),
    ("blogger", "Blogger", "platform", "Google Blogger publication target"),
    ("telegram", "Telegram", "api", "Operations notification bot"),
]
T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    return "published" if status in {"live", "published"} else status or "unknown"


def _score_present(value: Any) -> bool:
    try:
        return value is not None and float(value) >= 0
    except (TypeError, ValueError):
        return False


def _coverage(name: str, label: str, total: int, covered: int) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "total": total,
        "covered": covered,
        "missing": max(total - covered, 0),
        "coverage_percent": round((covered / total) * 100, 2) if total else 0.0,
    }


def _row_key(provider: str, row_id: int, url: str | None, title: str | None) -> str:
    normalized_url = str(url or "").strip().lower().rstrip("/")
    return normalized_url or f"{provider}:{row_id}:{str(title or '').strip().lower()}"


def _published_content_rows(db: Session) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    facts = db.execute(
        select(AnalyticsArticleFact).where(sa.func.lower(sa.func.coalesce(AnalyticsArticleFact.status, "")).in_(["published", "live"]))
    ).scalars().all()
    for fact in facts:
        key = _row_key("analytics", fact.id, fact.actual_url, fact.title)
        current = rows.setdefault(
            key,
            {"url": fact.actual_url, "title": fact.title, "status": _normalize_status(fact.status), "blog_id": fact.blog_id},
        )
        for source, target in [(fact.seo_score, "seo_score"), (fact.geo_score, "geo_score"), (getattr(fact, "ctr_score", None), "ctr_score"), (fact.lighthouse_score, "lighthouse_score")]:
            if not _score_present(current.get(target)):
                current[target] = source
    blogger_posts = db.execute(
        select(SyncedBloggerPost).where(sa.func.lower(sa.func.coalesce(SyncedBloggerPost.status, "")).in_(["published", "live"]))
    ).scalars().all()
    for post in blogger_posts:
        rows.setdefault(
            _row_key("blogger", post.id, post.url, post.title),
            {"url": post.url, "title": post.title, "status": _normalize_status(post.status), "blog_id": post.blog_id},
        )
    cloudflare_posts = db.execute(
        select(SyncedCloudflarePost).where(sa.func.lower(sa.func.coalesce(SyncedCloudflarePost.status, "")).in_(["published", "live"]))
    ).scalars().all()
    for post in cloudflare_posts:
        key = _row_key("cloudflare", post.id, post.url, post.title)
        current = rows.setdefault(key, {"url": post.url, "title": post.title, "status": _normalize_status(post.status), "blog_id": None})
        current.update({"url": post.url, "title": post.title, "status": _normalize_status(post.status)})
        for source, target in [(post.seo_score, "seo_score"), (post.geo_score, "geo_score"), (post.ctr, "ctr_score"), (post.lighthouse_score, "lighthouse_score")]:
            if _score_present(source):
                current[target] = source
    return rows


def compute_current_kpi(db: Session) -> dict[str, Any]:
    rows = _published_content_rows(db)
    total = len(rows)
    urls = [str(item.get("url") or "").strip() for item in rows.values() if str(item.get("url") or "").strip()]
    index_rows = db.execute(select(GoogleIndexUrlState).where(GoogleIndexUrlState.url.in_(urls))).scalars().all() if urls else []
    index_by_url = {str(row.url or "").strip().lower().rstrip("/"): row for row in index_rows}
    sc_rows = db.execute(select(SearchConsolePageMetric).where(SearchConsolePageMetric.url.in_(urls))).scalars().all() if urls else []
    ctr_by_url = {str(row.url or "").strip().lower().rstrip("/"): row for row in sc_rows}
    counts = Counter()
    for item in rows.values():
        counts["seo"] += int(_score_present(item.get("seo_score")))
        counts["geo"] += int(_score_present(item.get("geo_score")))
        counts["ctr"] += int(_score_present(item.get("ctr_score")))
        counts["lighthouse"] += int(_score_present(item.get("lighthouse_score")))
        url_key = str(item.get("url") or "").strip().lower().rstrip("/")
        index_status = str(getattr(index_by_url.get(url_key), "index_status", "") or "unknown").strip().lower()
        if index_status == "indexed":
            counts["indexed"] += 1
        elif index_status in {"submitted", "pending", "blocked", "failed", "not_indexed", "excluded"}:
            counts["not_indexed"] += 1
        else:
            counts["unknown_index"] += 1
        counts["search_console_ctr"] += int(url_key in ctr_by_url and _score_present(getattr(ctr_by_url[url_key], "ctr", None)))
        pass_gate = (
            _score_present(item.get("seo_score")) and float(item.get("seo_score") or 0) >= 70
            and _score_present(item.get("geo_score")) and float(item.get("geo_score") or 0) >= 60
            and _score_present(item.get("ctr_score")) and float(item.get("ctr_score") or 0) >= 60
            and _score_present(item.get("lighthouse_score")) and float(item.get("lighthouse_score") or 0) >= 70
        )
        counts["quality_gate_pass"] += int(pass_gate)
    review_counts = db.execute(select(ContentReviewItem.approval_status, func.count(ContentReviewItem.id)).group_by(ContentReviewItem.approval_status)).all()
    review_by_status = {str(status or "unknown"): int(count or 0) for status, count in review_counts}
    publish_success_count = int(db.execute(select(func.count(PublicationRecord.id)).where(PublicationRecord.publish_status == "published")).scalar() or 0)
    return {
        "generated_at": utcnow(),
        "published_total": total,
        "seo_scored_count": counts["seo"],
        "geo_scored_count": counts["geo"],
        "ctr_scored_count": counts["ctr"],
        "lighthouse_scored_count": counts["lighthouse"],
        "indexed_count": counts["indexed"],
        "not_indexed_count": counts["not_indexed"],
        "unknown_index_count": counts["unknown_index"],
        "search_console_ctr_count": counts["search_console_ctr"],
        "quality_gate_pass_count": counts["quality_gate_pass"],
        "rewrite_required_count": review_by_status.get("rejected", 0) + review_by_status.get("needs_rewrite", 0),
        "manual_review_count": review_by_status.get("pending", 0),
        "publish_success_count": publish_success_count,
        "status_breakdown": dict(Counter(str(item.get("status") or "unknown") for item in rows.values())),
        "coverage": [
            _coverage("seo", "SEO score", total, counts["seo"]),
            _coverage("geo", "GEO score", total, counts["geo"]),
            _coverage("ctr", "CTR quality score", total, counts["ctr"]),
            _coverage("lighthouse", "Lighthouse score", total, counts["lighthouse"]),
            _coverage("index", "Index status", total, counts["indexed"] + counts["not_indexed"]),
            _coverage("search_console_ctr", "Search Console CTR", total, counts["search_console_ctr"]),
        ],
    }

def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def list_documents(db: Session) -> list[dict[str, Any] | QmsDocument]:
    stored = {item.document_key: item for item in db.execute(select(QmsDocument).where(QmsDocument.archived_at.is_(None))).scalars().all()}
    documents: list[dict[str, Any] | QmsDocument] = []
    for key, title, phase, clause, owner, source_path_text in DOC_TEMPLATES:
        if key in stored:
            documents.append(stored[key])
            continue
        source_path = Path(source_path_text)
        documents.append(
            {
                "id": None,
                "document_key": key,
                "title": title,
                "phase": phase,
                "clause": clause,
                "owner": owner,
                "status": "draft",
                "version": "1.0",
                "source_path": source_path_text,
                "runtime_path": None,
                "checksum_sha256": _sha256_file(source_path) if source_path.exists() else None,
                "last_reviewed_at": None,
                "next_review_due": None,
                "document_payload": {},
                "archived_at": None,
                "archived_reason": None,
                "created_at": None,
                "updated_at": None,
            }
        )
    template_keys = {item[0] for item in DOC_TEMPLATES}
    documents.extend(item for key, item in stored.items() if key not in template_keys)
    return documents


def list_kpi_snapshots(db: Session, limit: int = 20) -> list[QmsKpiSnapshot]:
    return db.execute(select(QmsKpiSnapshot).order_by(QmsKpiSnapshot.created_at.desc()).limit(limit)).scalars().all()


def create_kpi_snapshot(db: Session) -> QmsKpiSnapshot:
    current = compute_current_kpi(db)
    today = date.today()
    snapshot = QmsKpiSnapshot(
        snapshot_key=f"qms-kpi-{today.isoformat()}-{uuid4().hex[:8]}",
        period_start=today,
        period_end=today,
        published_total=current["published_total"],
        seo_scored_count=current["seo_scored_count"],
        geo_scored_count=current["geo_scored_count"],
        ctr_scored_count=current["ctr_scored_count"],
        lighthouse_scored_count=current["lighthouse_scored_count"],
        indexed_count=current["indexed_count"],
        not_indexed_count=current["not_indexed_count"],
        unknown_index_count=current["unknown_index_count"],
        search_console_ctr_count=current["search_console_ctr_count"],
        quality_gate_pass_count=current["quality_gate_pass_count"],
        rewrite_required_count=current["rewrite_required_count"],
        manual_review_count=current["manual_review_count"],
        publish_success_count=current["publish_success_count"],
        status_breakdown=current["status_breakdown"],
        snapshot_payload={"coverage": current["coverage"]},
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def _summary(db: Session, model: type[Any], *, closed_statuses: set[str] | None = None) -> dict[str, Any]:
    closed_statuses = closed_statuses or {"closed", "completed", "released", "approved", "accepted"}
    query = select(model).where(model.archived_at.is_(None)) if hasattr(model, "archived_at") else select(model)
    rows = db.execute(query).scalars().all()
    today = date.today()
    by_status = Counter(str(getattr(row, "status", "unknown") or "unknown") for row in rows)
    closed = sum(count for status, count in by_status.items() if status in closed_statuses)
    overdue = 0
    for row in rows:
        due = getattr(row, "due_date", None) or getattr(row, "next_review_due", None)
        status = str(getattr(row, "status", "") or "").lower()
        due_date = due.date() if isinstance(due, datetime) else due
        overdue += int(bool(due_date and due_date < today and status not in closed_statuses))
    return {"total": len(rows), "open": max(len(rows) - closed, 0), "closed": closed, "overdue": overdue, "by_status": dict(by_status)}


def runtime_summary(db: Session) -> dict[str, Any]:
    latest_scan = db.execute(select(QmsRuntimeScan).order_by(QmsRuntimeScan.created_at.desc()).limit(1)).scalar_one_or_none()
    evidence_count = int(db.execute(select(func.count(QmsEvidenceItem.id)).where(QmsEvidenceItem.archived_at.is_(None))).scalar() or 0)
    targets = [{"path": str(path), "exists": path.exists(), "kind": "file" if path.is_file() else "directory"} for path in RUNTIME_SCAN_TARGETS]
    return {
        "runtime_root": str(RUNTIME_ROOT),
        "qms_report_dir": str(QMS_REPORT_DIR),
        "runtime_root_exists": RUNTIME_ROOT.exists(),
        "target_count": len(targets),
        "available_target_count": sum(1 for item in targets if item["exists"]),
        "targets": targets,
        "latest_scan": latest_scan.scan_key if latest_scan else None,
        "latest_scan_status": latest_scan.status if latest_scan else "missing",
        "evidence_count": evidence_count,
    }


def get_dashboard(db: Session) -> dict[str, Any]:
    return {
        "generated_at": utcnow(),
        "documents": list_documents(db),
        "current_kpi": compute_current_kpi(db),
        "latest_snapshot": db.execute(select(QmsKpiSnapshot).order_by(QmsKpiSnapshot.created_at.desc()).limit(1)).scalar_one_or_none(),
        "risk_summary": _summary(db, QmsRisk),
        "capa_summary": _summary(db, QmsCapaCase),
        "change_summary": _summary(db, QmsChangeRequest),
        "release_summary": _summary(db, QmsReleaseRecord),
        "supplier_summary": _summary(db, QmsSupplier),
        "audit_summary": _summary(db, QmsInternalAudit),
        "review_summary": _summary(db, QmsManagementReview),
        "runtime_summary": runtime_summary(db),
        "recent_evidence": db.execute(select(QmsEvidenceItem).where(QmsEvidenceItem.archived_at.is_(None)).order_by(QmsEvidenceItem.created_at.desc()).limit(12)).scalars().all(),
    }


def _slug(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).strip("-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized or uuid4().hex[:12]


def _make_key(prefix: str, value: str) -> str:
    return f"{prefix}-{_slug(value)[:80]}-{uuid4().hex[:8]}"


def _apply_update(row: Any, payload: Any, fields: Iterable[str]) -> Any:
    data = payload.model_dump(exclude_unset=True)
    archive_reason = data.pop("archived_reason", None)
    for field in fields:
        if field in data:
            setattr(row, field, data[field])
    if archive_reason:
        row.archived_at = utcnow()
        row.archived_reason = archive_reason
    return row


def _create_and_refresh(db: Session, row: T) -> T:
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_active(db: Session, model: type[T], row_id: int) -> T:
    row = db.get(model, row_id)
    if row is None or getattr(row, "archived_at", None) is not None:
        raise LookupError(f"{model.__name__} not found: {row_id}")
    return row

def list_risks(db: Session) -> list[QmsRisk]:
    return db.execute(select(QmsRisk).where(QmsRisk.archived_at.is_(None)).order_by(QmsRisk.rpn.desc(), QmsRisk.created_at.desc())).scalars().all()


def create_risk(db: Session, payload: Any) -> QmsRisk:
    data = payload.model_dump()
    data["risk_key"] = data.get("risk_key") or _make_key("risk", data.get("title") or "risk")
    data["rpn"] = int(data["severity"]) * int(data["occurrence"]) * int(data["detection"])
    return _create_and_refresh(db, QmsRisk(**data))


def update_risk(db: Session, risk_id: int, payload: Any) -> QmsRisk:
    row = _get_active(db, QmsRisk, risk_id)
    _apply_update(row, payload, ["title", "category", "phase", "source", "severity", "occurrence", "detection", "status", "owner", "mitigation_plan", "due_date", "closed_at", "risk_payload"])
    row.rpn = int(row.severity) * int(row.occurrence) * int(row.detection)
    db.commit(); db.refresh(row); return row


def list_capa(db: Session) -> list[QmsCapaCase]:
    return db.execute(select(QmsCapaCase).options(selectinload(QmsCapaCase.actions)).where(QmsCapaCase.archived_at.is_(None)).order_by(QmsCapaCase.created_at.desc())).scalars().all()


def create_capa(db: Session, payload: Any) -> QmsCapaCase:
    data = payload.model_dump(); data["capa_key"] = data.get("capa_key") or _make_key("capa", data.get("title") or "capa")
    return _create_and_refresh(db, QmsCapaCase(**data))


def update_capa(db: Session, capa_id: int, payload: Any) -> QmsCapaCase:
    row = _get_active(db, QmsCapaCase, capa_id)
    _apply_update(row, payload, ["title", "source_type", "source_id", "problem_statement", "root_cause", "containment_action", "corrective_action", "preventive_action", "status", "priority", "owner", "due_date", "verified_at", "effectiveness_score", "capa_payload"])
    db.commit(); db.refresh(row); return row


def create_capa_action(db: Session, capa_id: int, payload: Any) -> QmsCapaAction:
    _get_active(db, QmsCapaCase, capa_id)
    return _create_and_refresh(db, QmsCapaAction(capa_id=capa_id, **payload.model_dump()))


def update_capa_action(db: Session, capa_id: int, action_id: int, payload: Any) -> QmsCapaAction:
    _get_active(db, QmsCapaCase, capa_id)
    row = db.get(QmsCapaAction, action_id)
    if row is None or row.capa_id != capa_id:
        raise LookupError(f"QmsCapaAction not found: {action_id}")
    _apply_update(row, payload, ["action_type", "title", "owner", "status", "due_date", "completed_at", "result_payload"])
    db.commit(); db.refresh(row); return row


def list_changes(db: Session) -> list[QmsChangeRequest]:
    return db.execute(select(QmsChangeRequest).where(QmsChangeRequest.archived_at.is_(None)).order_by(QmsChangeRequest.created_at.desc())).scalars().all()


def create_change(db: Session, payload: Any) -> QmsChangeRequest:
    data = payload.model_dump(); data["change_key"] = data.get("change_key") or _make_key("change", data.get("title") or "change")
    return _create_and_refresh(db, QmsChangeRequest(**data))


def update_change(db: Session, change_id: int, payload: Any) -> QmsChangeRequest:
    row = _get_active(db, QmsChangeRequest, change_id)
    _apply_update(row, payload, ["title", "change_type", "risk_level", "status", "requester", "approver", "description", "impact_summary", "rollback_plan", "planned_at", "approved_at", "implemented_at", "released_at", "change_payload"])
    db.commit(); db.refresh(row); return row


def list_releases(db: Session) -> list[QmsReleaseRecord]:
    return db.execute(select(QmsReleaseRecord).where(QmsReleaseRecord.archived_at.is_(None)).order_by(QmsReleaseRecord.created_at.desc())).scalars().all()


def create_release(db: Session, payload: Any) -> QmsReleaseRecord:
    data = payload.model_dump(); data["release_key"] = data.get("release_key") or _make_key("release", data.get("title") or "release")
    return _create_and_refresh(db, QmsReleaseRecord(**data))


def update_release(db: Session, release_id: int, payload: Any) -> QmsReleaseRecord:
    row = _get_active(db, QmsReleaseRecord, release_id)
    _apply_update(row, payload, ["title", "status", "branch", "commit_hash", "pushed", "alembic_revision", "test_summary", "evidence_path", "released_at", "release_payload"])
    db.commit(); db.refresh(row); return row


def ensure_default_suppliers(db: Session) -> None:
    existing = {key for key, in db.execute(select(QmsSupplier.supplier_key)).all()}
    changed = False
    for key, name, supplier_type, scope in SUPPLIER_DEFAULTS:
        if key in existing:
            continue
        db.add(QmsSupplier(supplier_key=key, name=name, supplier_type=supplier_type, status="active", risk_level="medium", service_scope=scope, data_access_level="operational", owner="operations"))
        changed = True
    if changed:
        db.commit()


def list_suppliers(db: Session) -> list[QmsSupplier]:
    ensure_default_suppliers(db)
    return db.execute(select(QmsSupplier).options(selectinload(QmsSupplier.reviews)).where(QmsSupplier.archived_at.is_(None)).order_by(QmsSupplier.name.asc())).scalars().all()


def create_supplier(db: Session, payload: Any) -> QmsSupplier:
    data = payload.model_dump(); data["supplier_key"] = data.get("supplier_key") or _slug(data.get("name") or "supplier")
    return _create_and_refresh(db, QmsSupplier(**data))


def update_supplier(db: Session, supplier_id: int, payload: Any) -> QmsSupplier:
    row = _get_active(db, QmsSupplier, supplier_id)
    _apply_update(row, payload, ["name", "supplier_type", "status", "risk_level", "service_scope", "data_access_level", "owner", "review_cycle_days", "last_reviewed_at", "next_review_due", "supplier_payload"])
    db.commit(); db.refresh(row); return row

def list_audits(db: Session) -> list[QmsInternalAudit]:
    return db.execute(select(QmsInternalAudit).options(selectinload(QmsInternalAudit.findings)).where(QmsInternalAudit.archived_at.is_(None)).order_by(QmsInternalAudit.created_at.desc())).scalars().all()


def create_audit(db: Session, payload: Any) -> QmsInternalAudit:
    data = payload.model_dump(); data["audit_key"] = data.get("audit_key") or _make_key("audit", data.get("title") or "audit")
    return _create_and_refresh(db, QmsInternalAudit(**data))


def update_audit(db: Session, audit_id: int, payload: Any) -> QmsInternalAudit:
    row = _get_active(db, QmsInternalAudit, audit_id)
    _apply_update(row, payload, ["title", "scope", "status", "auditor", "scheduled_at", "started_at", "completed_at", "summary", "audit_payload"])
    db.commit(); db.refresh(row); return row


def create_audit_finding(db: Session, audit_id: int, payload: Any) -> QmsAuditFinding:
    _get_active(db, QmsInternalAudit, audit_id)
    data = payload.model_dump(); data["finding_key"] = data.get("finding_key") or _make_key("finding", data.get("title") or "finding")
    return _create_and_refresh(db, QmsAuditFinding(audit_id=audit_id, **data))


def update_audit_finding(db: Session, audit_id: int, finding_id: int, payload: Any) -> QmsAuditFinding:
    _get_active(db, QmsInternalAudit, audit_id)
    row = db.get(QmsAuditFinding, finding_id)
    if row is None or row.audit_id != audit_id:
        raise LookupError(f"QmsAuditFinding not found: {finding_id}")
    _apply_update(row, payload, ["severity", "clause", "title", "description", "status", "owner", "due_date", "closed_at", "capa_id", "finding_payload"])
    db.commit(); db.refresh(row); return row


def list_management_reviews(db: Session) -> list[QmsManagementReview]:
    return db.execute(select(QmsManagementReview).options(selectinload(QmsManagementReview.actions)).where(QmsManagementReview.archived_at.is_(None)).order_by(QmsManagementReview.created_at.desc())).scalars().all()


def create_management_review(db: Session, payload: Any) -> QmsManagementReview:
    data = payload.model_dump(); data["review_key"] = data.get("review_key") or _make_key("review", data.get("title") or "review")
    return _create_and_refresh(db, QmsManagementReview(**data))


def update_management_review(db: Session, review_id: int, payload: Any) -> QmsManagementReview:
    row = _get_active(db, QmsManagementReview, review_id)
    _apply_update(row, payload, ["title", "period_start", "period_end", "status", "chair", "scheduled_at", "completed_at", "inputs_summary", "decisions_summary", "review_payload"])
    db.commit(); db.refresh(row); return row


def list_evidence(db: Session, limit: int = 100) -> list[QmsEvidenceItem]:
    return db.execute(select(QmsEvidenceItem).where(QmsEvidenceItem.archived_at.is_(None)).order_by(QmsEvidenceItem.created_at.desc()).limit(limit)).scalars().all()


def _safe_relative(path: Path) -> str:
    try:
        return str(path.relative_to(RUNTIME_ROOT))
    except ValueError:
        return str(path)


def _classify_evidence(path: Path) -> str:
    text = str(path).lower()
    if "rool" in text:
        return "runtime_rule"
    if "snapshots" in text:
        return "db_snapshot"
    if "reports" in text:
        return "runtime_report"
    if path.suffix.lower() in {".md", ".txt"}:
        return "document"
    if path.suffix.lower() == ".env" or path.name.endswith(".env"):
        return "masked_env"
    return "runtime_file"


def _env_key_metadata(path: Path) -> tuple[list[str], int]:
    keys: list[str] = []
    secret_count = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return [], 0
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if not key:
            continue
        keys.append(key)
        if any(token in key.upper() for token in ["KEY", "TOKEN", "SECRET", "PASSWORD", "CLIENT_SECRET"]):
            secret_count += 1
    return keys, secret_count


def _iter_scan_files(target: Path, max_files: int) -> Iterable[Path]:
    if not target.exists():
        return []
    if target.is_file():
        return [target]
    selected: list[Path] = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [name for name in dirs if name not in {"node_modules", ".git", "__pycache__", ".next"}]
        for name in files:
            path = Path(root) / name
            if path.suffix.lower() not in {".json", ".md", ".txt", ".csv", ".log", ".env"} and not path.name.endswith(".env"):
                continue
            selected.append(path)
            if len(selected) >= max_files:
                return selected
    return selected


def scan_runtime_evidence(db: Session, *, max_files_per_root: int = 500) -> QmsRuntimeScan:
    started_at = utcnow()
    scan = QmsRuntimeScan(
        scan_key=f"qms-runtime-scan-{started_at.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        status="running",
        runtime_root=str(RUNTIME_ROOT),
        scanned_paths=[str(path) for path in RUNTIME_SCAN_TARGETS],
        file_count=0,
        evidence_count=0,
        secrets_masked_count=0,
        started_at=started_at,
        scan_payload={"targets": []},
    )
    db.add(scan); db.flush()
    evidence_count = file_count = secrets_masked_count = 0
    targets: list[dict[str, Any]] = []
    try:
        for target in RUNTIME_SCAN_TARGETS:
            files = list(_iter_scan_files(target, max_files_per_root))
            targets.append({"path": str(target), "exists": target.exists(), "file_count": len(files)})
            for path in files:
                file_count += 1
                stat = path.stat()
                evidence_type = _classify_evidence(path)
                env_keys: list[str] = []
                if evidence_type == "masked_env":
                    env_keys, count = _env_key_metadata(path)
                    secrets_masked_count += count
                evidence_key = f"runtime-{hashlib.sha1(str(path).encode('utf-8', errors='ignore')).hexdigest()[:16]}"
                row = db.execute(select(QmsEvidenceItem).where(QmsEvidenceItem.evidence_key == evidence_key)).scalar_one_or_none()
                values = {
                    "evidence_type": evidence_type,
                    "title": path.name,
                    "source_path": str(path),
                    "runtime_path": str(path),
                    "checksum_sha256": _sha256_file(path),
                    "file_size": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                    "status": "captured",
                    "captured_at": utcnow(),
                    "evidence_payload": {"relative_path": _safe_relative(path), "env_keys": env_keys, "scan_key": scan.scan_key},
                }
                if row is None:
                    db.add(QmsEvidenceItem(evidence_key=evidence_key, **values))
                else:
                    for field, value in values.items():
                        setattr(row, field, value)
                evidence_count += 1
        scan.status = "completed"
    except Exception as exc:  # noqa: BLE001
        scan.status = "failed"; scan.error_message = str(exc)
    finally:
        scan.file_count = file_count
        scan.evidence_count = evidence_count
        scan.secrets_masked_count = secrets_masked_count
        scan.completed_at = utcnow()
        scan.scan_payload = {"targets": targets}
        db.commit(); db.refresh(scan)
    return scan

def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if hasattr(value, "__table__"):
        mapper = sa.inspect(value).mapper
        return {attr.key: _json_safe(getattr(value, attr.key)) for attr in mapper.column_attrs}
    return value


def _render_markdown_report(payload: dict[str, Any]) -> str:
    dashboard = payload.get("dashboard") or {}
    current = dashboard.get("current_kpi") or {}
    lines = [
        f"# {payload.get('title')}",
        "",
        f"- Generated at: {payload.get('generated_at')}",
        f"- Published total: {current.get('published_total', 0)}",
        f"- SEO scored: {current.get('seo_scored_count', 0)}",
        f"- GEO scored: {current.get('geo_scored_count', 0)}",
        f"- CTR quality scored: {current.get('ctr_scored_count', 0)}",
        f"- Lighthouse scored: {current.get('lighthouse_scored_count', 0)}",
        f"- Indexed / Not indexed / Unknown: {current.get('indexed_count', 0)} / {current.get('not_indexed_count', 0)} / {current.get('unknown_index_count', 0)}",
        "",
        "## Coverage",
        "",
    ]
    for item in current.get("coverage", []):
        lines.append(f"- {item.get('label')}: {item.get('covered')}/{item.get('total')} ({item.get('coverage_percent')}%)")
    runtime = dashboard.get("runtime_summary") or {}
    lines.extend([
        "",
        "## Runtime Evidence",
        "",
        f"- Runtime root: {runtime.get('runtime_root', '-')}",
        f"- QMS report dir: {runtime.get('qms_report_dir', '-')}",
        f"- Evidence count: {runtime.get('evidence_count', 0)}",
    ])
    return "\n".join(lines).strip() + "\n"


def export_qms_report(db: Session, *, title: str, include_runtime: bool = True) -> dict[str, Any]:
    QMS_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = utcnow()
    dashboard = get_dashboard(db)
    payload = {"title": title, "generated_at": generated_at.isoformat(), "dashboard": _json_safe(dashboard), "runtime_included": include_runtime}
    if include_runtime:
        payload["runtime_summary"] = runtime_summary(db)
    stamp = generated_at.strftime("%Y%m%d-%H%M%S")
    json_path = QMS_REPORT_DIR / f"qms-evidence-{stamp}.json"
    md_path = QMS_REPORT_DIR / f"qms-evidence-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_render_markdown_report(payload), encoding="utf-8")
    evidence = QmsEvidenceItem(
        evidence_key=f"qms-export-{stamp}-{uuid4().hex[:8]}",
        evidence_type="qms_report",
        title=title,
        source_path=str(md_path),
        runtime_path=str(md_path),
        checksum_sha256=_sha256_file(md_path),
        file_size=md_path.stat().st_size,
        modified_at=datetime.fromtimestamp(md_path.stat().st_mtime, timezone.utc),
        status="captured",
        captured_at=generated_at,
        evidence_payload={"json_path": str(json_path), "markdown_path": str(md_path)},
    )
    db.add(evidence); db.commit(); db.refresh(evidence)
    return {"status": "ok", "json_path": str(json_path), "markdown_path": str(md_path), "evidence": evidence}
