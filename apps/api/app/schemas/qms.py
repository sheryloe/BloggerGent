from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class QmsArchivedMixin(BaseModel):
    archived_at: datetime | None = None
    archived_reason: str | None = None


class QmsDocumentRead(QmsArchivedMixin):
    id: int | None = None
    document_key: str
    title: str
    phase: str
    clause: str | None = None
    owner: str | None = None
    status: str
    version: str
    source_path: str | None = None
    runtime_path: str | None = None
    checksum_sha256: str | None = None
    last_reviewed_at: datetime | None = None
    next_review_due: date | None = None
    document_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class QmsKpiCoverageRead(BaseModel):
    name: str
    label: str
    total: int
    covered: int
    missing: int
    coverage_percent: float


class QmsKpiCurrentRead(BaseModel):
    generated_at: datetime
    published_total: int
    seo_scored_count: int
    geo_scored_count: int
    ctr_scored_count: int
    lighthouse_scored_count: int
    indexed_count: int
    not_indexed_count: int
    unknown_index_count: int
    search_console_ctr_count: int
    quality_gate_pass_count: int
    rewrite_required_count: int
    manual_review_count: int
    publish_success_count: int
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    coverage: list[QmsKpiCoverageRead] = Field(default_factory=list)


class QmsKpiSnapshotRead(QmsArchivedMixin):
    id: int
    snapshot_key: str
    period_start: date | None = None
    period_end: date | None = None
    published_total: int
    seo_scored_count: int
    geo_scored_count: int
    ctr_scored_count: int
    lighthouse_scored_count: int
    indexed_count: int
    not_indexed_count: int
    unknown_index_count: int
    search_console_ctr_count: int
    quality_gate_pass_count: int
    rewrite_required_count: int
    manual_review_count: int
    publish_success_count: int
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    snapshot_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsRiskBase(BaseModel):
    title: str
    category: str = "operation"
    phase: str = "phase-2"
    source: str = "manual"
    severity: int = Field(default=3, ge=1, le=5)
    occurrence: int = Field(default=3, ge=1, le=5)
    detection: int = Field(default=3, ge=1, le=5)
    status: str = "open"
    owner: str | None = None
    mitigation_plan: str | None = None
    due_date: date | None = None
    risk_payload: dict[str, Any] = Field(default_factory=dict)


class QmsRiskCreate(QmsRiskBase):
    risk_key: str | None = None


class QmsRiskUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    phase: str | None = None
    source: str | None = None
    severity: int | None = Field(default=None, ge=1, le=5)
    occurrence: int | None = Field(default=None, ge=1, le=5)
    detection: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None
    owner: str | None = None
    mitigation_plan: str | None = None
    due_date: date | None = None
    closed_at: datetime | None = None
    risk_payload: dict[str, Any] | None = None
    archived_reason: str | None = None


class QmsRiskRead(QmsArchivedMixin, QmsRiskBase):
    id: int
    risk_key: str
    rpn: int
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsCapaActionBase(BaseModel):
    action_type: str = "corrective"
    title: str
    owner: str | None = None
    status: str = "open"
    due_date: date | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)


class QmsCapaActionCreate(QmsCapaActionBase):
    pass


class QmsCapaActionUpdate(BaseModel):
    action_type: str | None = None
    title: str | None = None
    owner: str | None = None
    status: str | None = None
    due_date: date | None = None
    completed_at: datetime | None = None
    result_payload: dict[str, Any] | None = None


class QmsCapaActionRead(QmsCapaActionBase):
    id: int
    capa_id: int
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsCapaBase(BaseModel):
    title: str
    source_type: str = "manual"
    source_id: str | None = None
    problem_statement: str
    root_cause: str | None = None
    containment_action: str | None = None
    corrective_action: str | None = None
    preventive_action: str | None = None
    status: str = "open"
    priority: str = "medium"
    owner: str | None = None
    due_date: date | None = None
    effectiveness_score: float | None = None
    capa_payload: dict[str, Any] = Field(default_factory=dict)


class QmsCapaCreate(QmsCapaBase):
    capa_key: str | None = None


class QmsCapaUpdate(BaseModel):
    title: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    problem_statement: str | None = None
    root_cause: str | None = None
    containment_action: str | None = None
    corrective_action: str | None = None
    preventive_action: str | None = None
    status: str | None = None
    priority: str | None = None
    owner: str | None = None
    due_date: date | None = None
    verified_at: datetime | None = None
    effectiveness_score: float | None = None
    capa_payload: dict[str, Any] | None = None
    archived_reason: str | None = None


class QmsCapaRead(QmsArchivedMixin, QmsCapaBase):
    id: int
    capa_key: str
    verified_at: datetime | None = None
    actions: list[QmsCapaActionRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsChangeBase(BaseModel):
    title: str
    change_type: str = "process"
    risk_level: str = "medium"
    status: str = "draft"
    requester: str | None = None
    approver: str | None = None
    description: str | None = None
    impact_summary: str | None = None
    rollback_plan: str | None = None
    planned_at: datetime | None = None
    change_payload: dict[str, Any] = Field(default_factory=dict)


class QmsChangeCreate(QmsChangeBase):
    change_key: str | None = None


class QmsChangeUpdate(BaseModel):
    title: str | None = None
    change_type: str | None = None
    risk_level: str | None = None
    status: str | None = None
    requester: str | None = None
    approver: str | None = None
    description: str | None = None
    impact_summary: str | None = None
    rollback_plan: str | None = None
    planned_at: datetime | None = None
    approved_at: datetime | None = None
    implemented_at: datetime | None = None
    released_at: datetime | None = None
    change_payload: dict[str, Any] | None = None
    archived_reason: str | None = None


class QmsChangeRead(QmsArchivedMixin, QmsChangeBase):
    id: int
    change_key: str
    approved_at: datetime | None = None
    implemented_at: datetime | None = None
    released_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsReleaseBase(BaseModel):
    title: str
    status: str = "planned"
    branch: str | None = None
    commit_hash: str | None = None
    pushed: bool = False
    alembic_revision: str | None = None
    test_summary: str | None = None
    evidence_path: str | None = None
    released_at: datetime | None = None
    release_payload: dict[str, Any] = Field(default_factory=dict)


class QmsReleaseCreate(QmsReleaseBase):
    release_key: str | None = None


class QmsReleaseUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    branch: str | None = None
    commit_hash: str | None = None
    pushed: bool | None = None
    alembic_revision: str | None = None
    test_summary: str | None = None
    evidence_path: str | None = None
    released_at: datetime | None = None
    release_payload: dict[str, Any] | None = None
    archived_reason: str | None = None


class QmsReleaseRead(QmsArchivedMixin, QmsReleaseBase):
    id: int
    release_key: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsSupplierReviewRead(BaseModel):
    id: int
    supplier_id: int
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    score: float | None = None
    findings: str | None = None
    action_required: bool
    review_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsSupplierBase(BaseModel):
    supplier_key: str | None = None
    name: str
    supplier_type: str = "api"
    status: str = "active"
    risk_level: str = "medium"
    service_scope: str | None = None
    data_access_level: str = "operational"
    owner: str | None = None
    review_cycle_days: int = 90
    last_reviewed_at: datetime | None = None
    next_review_due: date | None = None
    supplier_payload: dict[str, Any] = Field(default_factory=dict)


class QmsSupplierCreate(QmsSupplierBase):
    pass


class QmsSupplierUpdate(BaseModel):
    name: str | None = None
    supplier_type: str | None = None
    status: str | None = None
    risk_level: str | None = None
    service_scope: str | None = None
    data_access_level: str | None = None
    owner: str | None = None
    review_cycle_days: int | None = None
    last_reviewed_at: datetime | None = None
    next_review_due: date | None = None
    supplier_payload: dict[str, Any] | None = None
    archived_reason: str | None = None


class QmsSupplierRead(QmsArchivedMixin, QmsSupplierBase):
    id: int
    supplier_key: str
    reviews: list[QmsSupplierReviewRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsAuditFindingBase(BaseModel):
    finding_key: str | None = None
    severity: str = "minor"
    clause: str | None = None
    title: str
    description: str | None = None
    status: str = "open"
    owner: str | None = None
    due_date: date | None = None
    capa_id: int | None = None
    finding_payload: dict[str, Any] = Field(default_factory=dict)


class QmsAuditFindingCreate(QmsAuditFindingBase):
    pass


class QmsAuditFindingUpdate(BaseModel):
    severity: str | None = None
    clause: str | None = None
    title: str | None = None
    description: str | None = None
    status: str | None = None
    owner: str | None = None
    due_date: date | None = None
    closed_at: datetime | None = None
    capa_id: int | None = None
    finding_payload: dict[str, Any] | None = None


class QmsAuditFindingRead(QmsAuditFindingBase):
    id: int
    audit_id: int
    finding_key: str
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsAuditBase(BaseModel):
    audit_key: str | None = None
    title: str
    scope: str | None = None
    status: str = "planned"
    auditor: str | None = None
    scheduled_at: datetime | None = None
    summary: str | None = None
    audit_payload: dict[str, Any] = Field(default_factory=dict)


class QmsAuditCreate(QmsAuditBase):
    pass


class QmsAuditUpdate(BaseModel):
    title: str | None = None
    scope: str | None = None
    status: str | None = None
    auditor: str | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: str | None = None
    audit_payload: dict[str, Any] | None = None
    archived_reason: str | None = None


class QmsAuditRead(QmsArchivedMixin, QmsAuditBase):
    id: int
    audit_key: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    findings: list[QmsAuditFindingRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsManagementReviewActionRead(BaseModel):
    id: int
    review_id: int
    title: str
    owner: str | None = None
    status: str
    due_date: date | None = None
    completed_at: datetime | None = None
    action_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsManagementReviewBase(BaseModel):
    review_key: str | None = None
    title: str
    period_start: date | None = None
    period_end: date | None = None
    status: str = "planned"
    chair: str | None = None
    scheduled_at: datetime | None = None
    inputs_summary: str | None = None
    decisions_summary: str | None = None
    review_payload: dict[str, Any] = Field(default_factory=dict)


class QmsManagementReviewCreate(QmsManagementReviewBase):
    pass


class QmsManagementReviewUpdate(BaseModel):
    title: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    status: str | None = None
    chair: str | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None
    inputs_summary: str | None = None
    decisions_summary: str | None = None
    review_payload: dict[str, Any] | None = None
    archived_reason: str | None = None


class QmsManagementReviewRead(QmsArchivedMixin, QmsManagementReviewBase):
    id: int
    review_key: str
    completed_at: datetime | None = None
    actions: list[QmsManagementReviewActionRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsEvidenceRead(QmsArchivedMixin):
    id: int
    evidence_key: str
    evidence_type: str
    title: str
    source_path: str | None = None
    runtime_path: str | None = None
    checksum_sha256: str | None = None
    file_size: int | None = None
    modified_at: datetime | None = None
    linked_record_type: str | None = None
    linked_record_id: int | None = None
    status: str
    captured_at: datetime | None = None
    evidence_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsRuntimeScanRead(BaseModel):
    id: int
    scan_key: str
    status: str
    runtime_root: str
    scanned_paths: list[str] = Field(default_factory=list)
    file_count: int
    evidence_count: int
    secrets_masked_count: int
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    scan_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QmsSummaryRead(BaseModel):
    total: int = 0
    open: int = 0
    overdue: int = 0
    closed: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)


class QmsDashboardRead(BaseModel):
    generated_at: datetime
    documents: list[QmsDocumentRead] = Field(default_factory=list)
    current_kpi: QmsKpiCurrentRead
    latest_snapshot: QmsKpiSnapshotRead | None = None
    risk_summary: QmsSummaryRead
    capa_summary: QmsSummaryRead
    change_summary: QmsSummaryRead
    release_summary: QmsSummaryRead
    supplier_summary: QmsSummaryRead
    audit_summary: QmsSummaryRead
    review_summary: QmsSummaryRead
    runtime_summary: dict[str, Any] = Field(default_factory=dict)
    recent_evidence: list[QmsEvidenceRead] = Field(default_factory=list)


class QmsRuntimeScanRequest(BaseModel):
    max_files_per_root: int = Field(default=500, ge=1, le=5000)


class QmsExportReportRequest(BaseModel):
    title: str = "BloggerGent QMS Evidence Report"
    include_runtime: bool = True
