"""Add planner brief analysis run history.

Revision ID: 0025_planner_brief_runs
Revises: 0024_runtime_usage_indexes
Create Date: 2026-04-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0025_planner_brief_runs"
down_revision = "0024_runtime_usage_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planner_brief_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_day_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.String(length=100), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("raw_response", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("slot_suggestions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'completed'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("applied_slot_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_day_id"], ["content_plan_days.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_planner_brief_runs_id"), "planner_brief_runs", ["id"], unique=False)
    op.create_index(op.f("ix_planner_brief_runs_plan_day_id"), "planner_brief_runs", ["plan_day_id"], unique=False)
    op.create_index(op.f("ix_planner_brief_runs_channel_id"), "planner_brief_runs", ["channel_id"], unique=False)
    op.create_index(op.f("ix_planner_brief_runs_blog_id"), "planner_brief_runs", ["blog_id"], unique=False)
    op.create_index(op.f("ix_planner_brief_runs_created_at"), "planner_brief_runs", ["created_at"], unique=False)

    with op.batch_alter_table("planner_brief_runs") as batch_op:
        batch_op.alter_column("raw_response", existing_type=sa.JSON(), server_default=None)
        batch_op.alter_column("slot_suggestions", existing_type=sa.JSON(), server_default=None)
        batch_op.alter_column("status", existing_type=sa.String(length=30), server_default=None)
        batch_op.alter_column("applied_slot_ids", existing_type=sa.JSON(), server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_planner_brief_runs_created_at"), table_name="planner_brief_runs")
    op.drop_index(op.f("ix_planner_brief_runs_blog_id"), table_name="planner_brief_runs")
    op.drop_index(op.f("ix_planner_brief_runs_channel_id"), table_name="planner_brief_runs")
    op.drop_index(op.f("ix_planner_brief_runs_plan_day_id"), table_name="planner_brief_runs")
    op.drop_index(op.f("ix_planner_brief_runs_id"), table_name="planner_brief_runs")
    op.drop_table("planner_brief_runs")
