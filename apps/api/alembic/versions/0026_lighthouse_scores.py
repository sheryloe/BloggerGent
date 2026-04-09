"""Add Lighthouse score cache fields.

Revision ID: 0026_lighthouse_scores
Revises: 0025_planner_brief_runs
Create Date: 2026-04-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_lighthouse_scores"
down_revision = "0025_planner_brief_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("quality_lighthouse_score", sa.Float(), nullable=True))
    op.add_column(
        "articles",
        sa.Column("quality_lighthouse_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("articles", sa.Column("quality_lighthouse_last_audited_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("analytics_article_facts", sa.Column("lighthouse_score", sa.Float(), nullable=True))

    with op.batch_alter_table("articles") as batch_op:
        batch_op.alter_column("quality_lighthouse_payload", existing_type=sa.JSON(), server_default=None)


def downgrade() -> None:
    op.drop_column("analytics_article_facts", "lighthouse_score")

    op.drop_column("articles", "quality_lighthouse_last_audited_at")
    op.drop_column("articles", "quality_lighthouse_payload")
    op.drop_column("articles", "quality_lighthouse_score")
