"""Add STOPPED status for partial pipeline runs."""

from alembic import op
import sqlalchemy as sa


revision = "0005_job_status_stopped"
down_revision = "0004_service_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'STOPPED'"))


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally omitted.
    pass
