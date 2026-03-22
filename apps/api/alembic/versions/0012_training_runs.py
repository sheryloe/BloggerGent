"""Add training run state table."""

from alembic import op
import sqlalchemy as sa


revision = "0012_training_runs"
down_revision = "0011_article_inline_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False, server_default="idle"),
        sa.Column("trigger_source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("session_hours", sa.Float(), nullable=False, server_default="4"),
        sa.Column("save_every_minutes", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loss", sa.Float(), nullable=True),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eta_seconds", sa.Integer(), nullable=True),
        sa.Column("dataset_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dataset_manifest_path", sa.String(length=1000), nullable=True),
        sa.Column("dataset_jsonl_path", sa.String(length=1000), nullable=True),
        sa.Column("last_checkpoint", sa.String(length=1000), nullable=True),
        sa.Column("checkpoint_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_checkpoint_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("pause_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("log_tail", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_training_runs_id", "training_runs", ["id"])
    op.create_index("ix_training_runs_state", "training_runs", ["state"])
    op.create_index("ix_training_runs_task_id", "training_runs", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_training_runs_task_id", table_name="training_runs")
    op.drop_index("ix_training_runs_state", table_name="training_runs")
    op.drop_index("ix_training_runs_id", table_name="training_runs")
    op.drop_table("training_runs")
