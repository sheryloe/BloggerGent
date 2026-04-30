"""add QMS core tables

Revision ID: 0042_qms_core
Revises: 0041_article_ctr_score
Create Date: 2026-04-30 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0042_qms_core"
down_revision = "0041_article_ctr_score"
branch_labels = None
depends_on = None


def json_col(name: str) -> sa.Column:
    return sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text("'{}'::json"))


def list_col(name: str) -> sa.Column:
    return sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text("'[]'::json"))


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def archive_cols() -> list[sa.Column]:
    return [
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_reason", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "qms_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("clause", sa.String(length=120), nullable=True),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("source_path", sa.String(length=1000), nullable=True),
        sa.Column("runtime_path", sa.String(length=1000), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_review_due", sa.Date(), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_key", name="uq_qms_documents_document_key"),
    )
    op.create_table(
        "qms_kpi_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_key", sa.String(length=160), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("published_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seo_scored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("geo_scored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr_scored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lighthouse_scored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("not_indexed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown_index_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search_console_ctr_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_gate_pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rewrite_required_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual_review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publish_success_count", sa.Integer(), nullable=False, server_default="0"),
        json_col("status_breakdown"),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_key", name="uq_qms_kpi_snapshots_snapshot_key"),
    )
    op.create_table(
        "qms_risks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("risk_key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("detection", sa.Integer(), nullable=False),
        sa.Column("rpn", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("mitigation_plan", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("risk_key", name="uq_qms_risks_risk_key"),
    )
    op.create_table(
        "qms_capa_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("capa_key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("problem_statement", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("containment_action", sa.Text(), nullable=True),
        sa.Column("corrective_action", sa.Text(), nullable=True),
        sa.Column("preventive_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.String(length=30), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effectiveness_score", sa.Float(), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capa_key", name="uq_qms_capa_cases_capa_key"),
    )
    op.create_table(
        "qms_capa_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("capa_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        json_col("result_payload"),
        *timestamps(),
        sa.ForeignKeyConstraint(["capa_id"], ["qms_capa_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "qms_change_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("change_key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("change_type", sa.String(length=80), nullable=False),
        sa.Column("risk_level", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("requester", sa.String(length=120), nullable=True),
        sa.Column("approver", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("impact_summary", sa.Text(), nullable=True),
        sa.Column("rollback_plan", sa.Text(), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("implemented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("change_key", name="uq_qms_change_requests_change_key"),
    )
    op.create_table(
        "qms_release_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("branch", sa.String(length=160), nullable=True),
        sa.Column("commit_hash", sa.String(length=80), nullable=True),
        sa.Column("pushed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("alembic_revision", sa.String(length=120), nullable=True),
        sa.Column("test_summary", sa.Text(), nullable=True),
        sa.Column("evidence_path", sa.String(length=1000), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_key", name="uq_qms_release_records_release_key"),
    )
    op.create_table(
        "qms_suppliers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("supplier_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("risk_level", sa.String(length=30), nullable=False),
        sa.Column("service_scope", sa.Text(), nullable=True),
        sa.Column("data_access_level", sa.String(length=80), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("review_cycle_days", sa.Integer(), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_review_due", sa.Date(), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supplier_key", name="uq_qms_suppliers_supplier_key"),
    )
    op.create_table(
        "qms_supplier_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reviewed_by", sa.String(length=120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("findings", sa.Text(), nullable=True),
        sa.Column("action_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        json_col("payload"),
        *timestamps(),
        sa.ForeignKeyConstraint(["supplier_id"], ["qms_suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "qms_internal_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audit_key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("auditor", sa.String(length=120), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audit_key", name="uq_qms_internal_audits_audit_key"),
    )
    op.create_table(
        "qms_audit_findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("finding_key", sa.String(length=160), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("clause", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capa_id", sa.Integer(), nullable=True),
        json_col("payload"),
        *timestamps(),
        sa.ForeignKeyConstraint(["audit_id"], ["qms_internal_audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capa_id"], ["qms_capa_cases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_key", name="uq_qms_audit_findings_finding_key"),
    )
    op.create_table(
        "qms_management_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("chair", sa.String(length=120), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inputs_summary", sa.Text(), nullable=True),
        sa.Column("decisions_summary", sa.Text(), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_key", name="uq_qms_management_reviews_review_key"),
    )
    op.create_table(
        "qms_management_review_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        json_col("payload"),
        *timestamps(),
        sa.ForeignKeyConstraint(["review_id"], ["qms_management_reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "qms_evidence_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evidence_key", sa.String(length=180), nullable=False),
        sa.Column("evidence_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_path", sa.String(length=1000), nullable=True),
        sa.Column("runtime_path", sa.String(length=1000), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_record_type", sa.String(length=80), nullable=True),
        sa.Column("linked_record_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        json_col("payload"),
        *archive_cols(),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_key", name="uq_qms_evidence_items_evidence_key"),
    )
    op.create_table(
        "qms_runtime_scans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_key", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("runtime_root", sa.String(length=1000), nullable=False),
        list_col("scanned_paths"),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("secrets_masked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        json_col("payload"),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_key", name="uq_qms_runtime_scans_scan_key"),
    )

    for table in [
        "qms_documents", "qms_kpi_snapshots", "qms_risks", "qms_capa_cases", "qms_change_requests",
        "qms_release_records", "qms_suppliers", "qms_internal_audits", "qms_management_reviews",
        "qms_evidence_items", "qms_runtime_scans",
    ]:
        op.create_index(op.f(f"ix_{table}_id"), table, ["id"], unique=False)


def downgrade() -> None:
    for table in [
        "qms_runtime_scans", "qms_evidence_items", "qms_management_review_actions", "qms_management_reviews",
        "qms_audit_findings", "qms_internal_audits", "qms_supplier_reviews", "qms_suppliers",
        "qms_release_records", "qms_change_requests", "qms_capa_actions", "qms_capa_cases",
        "qms_risks", "qms_kpi_snapshots", "qms_documents",
    ]:
        op.drop_table(table)
