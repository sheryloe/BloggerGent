from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps.admin_auth import require_admin_auth
from app.db.session import get_db
from app.schemas.qms import (
    QmsAuditCreate,
    QmsAuditFindingCreate,
    QmsAuditFindingRead,
    QmsAuditFindingUpdate,
    QmsAuditRead,
    QmsAuditUpdate,
    QmsCapaActionCreate,
    QmsCapaActionRead,
    QmsCapaActionUpdate,
    QmsCapaCreate,
    QmsCapaRead,
    QmsCapaUpdate,
    QmsChangeCreate,
    QmsChangeRead,
    QmsChangeUpdate,
    QmsDashboardRead,
    QmsDocumentRead,
    QmsEvidenceRead,
    QmsExportReportRequest,
    QmsKpiCurrentRead,
    QmsKpiSnapshotRead,
    QmsManagementReviewCreate,
    QmsManagementReviewRead,
    QmsManagementReviewUpdate,
    QmsReleaseCreate,
    QmsReleaseRead,
    QmsReleaseUpdate,
    QmsRiskCreate,
    QmsRiskRead,
    QmsRiskUpdate,
    QmsRuntimeScanRead,
    QmsRuntimeScanRequest,
    QmsSupplierCreate,
    QmsSupplierRead,
    QmsSupplierUpdate,
)
from app.services.qms.qms_service import (
    compute_current_kpi,
    create_audit,
    create_audit_finding,
    create_capa,
    create_capa_action,
    create_change,
    create_kpi_snapshot,
    create_management_review,
    create_release,
    create_risk,
    create_supplier,
    export_qms_report,
    get_dashboard,
    list_audits,
    list_capa,
    list_changes,
    list_documents,
    list_evidence,
    list_kpi_snapshots,
    list_management_reviews,
    list_releases,
    list_risks,
    list_suppliers,
    scan_runtime_evidence,
    update_audit,
    update_audit_finding,
    update_capa,
    update_capa_action,
    update_change,
    update_management_review,
    update_release,
    update_risk,
    update_supplier,
)

router = APIRouter(prefix="/qms", tags=["qms"], dependencies=[Depends(require_admin_auth)])


def _raise_not_found(exc: LookupError) -> None:
    raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/dashboard", response_model=QmsDashboardRead)
def read_qms_dashboard(db: Session = Depends(get_db)) -> dict:
    return get_dashboard(db)


@router.get("/documents", response_model=list[QmsDocumentRead])
def read_qms_documents(db: Session = Depends(get_db)) -> list[dict]:
    return list_documents(db)


@router.get("/kpis", response_model=list[QmsKpiSnapshotRead])
def read_qms_kpis(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)) -> list:
    return list_kpi_snapshots(db, limit=limit)


@router.post("/kpis/snapshot", response_model=QmsKpiSnapshotRead)
def create_qms_kpi_snapshot(db: Session = Depends(get_db)):
    return create_kpi_snapshot(db)


@router.get("/kpis/current", response_model=QmsKpiCurrentRead)
def read_current_qms_kpi(db: Session = Depends(get_db)) -> dict:
    return compute_current_kpi(db)


@router.get("/risks", response_model=list[QmsRiskRead])
def read_qms_risks(db: Session = Depends(get_db)) -> list:
    return list_risks(db)


@router.post("/risks", response_model=QmsRiskRead)
def create_qms_risk(payload: QmsRiskCreate, db: Session = Depends(get_db)):
    return create_risk(db, payload)


@router.patch("/risks/{risk_id}", response_model=QmsRiskRead)
def update_qms_risk(risk_id: int, payload: QmsRiskUpdate, db: Session = Depends(get_db)):
    try:
        return update_risk(db, risk_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.get("/capa", response_model=list[QmsCapaRead])
def read_qms_capa(db: Session = Depends(get_db)) -> list:
    return list_capa(db)


@router.post("/capa", response_model=QmsCapaRead)
def create_qms_capa(payload: QmsCapaCreate, db: Session = Depends(get_db)):
    return create_capa(db, payload)


@router.patch("/capa/{capa_id}", response_model=QmsCapaRead)
def update_qms_capa(capa_id: int, payload: QmsCapaUpdate, db: Session = Depends(get_db)):
    try:
        return update_capa(db, capa_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.post("/capa/{capa_id}/actions", response_model=QmsCapaActionRead)
def create_qms_capa_action(capa_id: int, payload: QmsCapaActionCreate, db: Session = Depends(get_db)):
    try:
        return create_capa_action(db, capa_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.patch("/capa/{capa_id}/actions/{action_id}", response_model=QmsCapaActionRead)
def update_qms_capa_action(capa_id: int, action_id: int, payload: QmsCapaActionUpdate, db: Session = Depends(get_db)):
    try:
        return update_capa_action(db, capa_id, action_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.get("/changes", response_model=list[QmsChangeRead])
def read_qms_changes(db: Session = Depends(get_db)) -> list:
    return list_changes(db)


@router.post("/changes", response_model=QmsChangeRead)
def create_qms_change(payload: QmsChangeCreate, db: Session = Depends(get_db)):
    return create_change(db, payload)


@router.patch("/changes/{change_id}", response_model=QmsChangeRead)
def update_qms_change(change_id: int, payload: QmsChangeUpdate, db: Session = Depends(get_db)):
    try:
        return update_change(db, change_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.get("/releases", response_model=list[QmsReleaseRead])
def read_qms_releases(db: Session = Depends(get_db)) -> list:
    return list_releases(db)


@router.post("/releases", response_model=QmsReleaseRead)
def create_qms_release(payload: QmsReleaseCreate, db: Session = Depends(get_db)):
    return create_release(db, payload)


@router.patch("/releases/{release_id}", response_model=QmsReleaseRead)
def update_qms_release(release_id: int, payload: QmsReleaseUpdate, db: Session = Depends(get_db)):
    try:
        return update_release(db, release_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.get("/suppliers", response_model=list[QmsSupplierRead])
def read_qms_suppliers(db: Session = Depends(get_db)) -> list:
    return list_suppliers(db)


@router.post("/suppliers", response_model=QmsSupplierRead)
def create_qms_supplier(payload: QmsSupplierCreate, db: Session = Depends(get_db)):
    return create_supplier(db, payload)


@router.patch("/suppliers/{supplier_id}", response_model=QmsSupplierRead)
def update_qms_supplier(supplier_id: int, payload: QmsSupplierUpdate, db: Session = Depends(get_db)):
    try:
        return update_supplier(db, supplier_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.get("/audits", response_model=list[QmsAuditRead])
def read_qms_audits(db: Session = Depends(get_db)) -> list:
    return list_audits(db)


@router.post("/audits", response_model=QmsAuditRead)
def create_qms_audit(payload: QmsAuditCreate, db: Session = Depends(get_db)):
    return create_audit(db, payload)


@router.patch("/audits/{audit_id}", response_model=QmsAuditRead)
def update_qms_audit(audit_id: int, payload: QmsAuditUpdate, db: Session = Depends(get_db)):
    try:
        return update_audit(db, audit_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.post("/audits/{audit_id}/findings", response_model=QmsAuditFindingRead)
def create_qms_audit_finding(audit_id: int, payload: QmsAuditFindingCreate, db: Session = Depends(get_db)):
    try:
        return create_audit_finding(db, audit_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.patch("/audits/{audit_id}/findings/{finding_id}", response_model=QmsAuditFindingRead)
def update_qms_audit_finding(audit_id: int, finding_id: int, payload: QmsAuditFindingUpdate, db: Session = Depends(get_db)):
    try:
        return update_audit_finding(db, audit_id, finding_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.get("/management-reviews", response_model=list[QmsManagementReviewRead])
def read_qms_management_reviews(db: Session = Depends(get_db)) -> list:
    return list_management_reviews(db)


@router.post("/management-reviews", response_model=QmsManagementReviewRead)
def create_qms_management_review(payload: QmsManagementReviewCreate, db: Session = Depends(get_db)):
    return create_management_review(db, payload)


@router.patch("/management-reviews/{review_id}", response_model=QmsManagementReviewRead)
def update_qms_management_review(review_id: int, payload: QmsManagementReviewUpdate, db: Session = Depends(get_db)):
    try:
        return update_management_review(db, review_id, payload)
    except LookupError as exc:
        _raise_not_found(exc)


@router.get("/evidence", response_model=list[QmsEvidenceRead])
def read_qms_evidence(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list:
    return list_evidence(db, limit=limit)


@router.post("/evidence/scan-runtime", response_model=QmsRuntimeScanRead)
def scan_qms_runtime(payload: QmsRuntimeScanRequest | None = None, db: Session = Depends(get_db)):
    request = payload or QmsRuntimeScanRequest()
    return scan_runtime_evidence(db, max_files_per_root=request.max_files_per_root)


@router.post("/evidence/export-report")
def export_qms_evidence_report(payload: QmsExportReportRequest | None = None, db: Session = Depends(get_db)) -> dict:
    request = payload or QmsExportReportRequest()
    return export_qms_report(db, title=request.title, include_runtime=request.include_runtime)
