"""Add content review ops tables."""

from alembic import op
import sqlalchemy as sa


revision = "0013_content_review_ops"
down_revision = "0012_training_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_review_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("source_title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("review_kind", sa.String(length=50), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("quality_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("issues", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("proposed_patch", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("approval_status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("apply_status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("learning_state", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_id", "review_kind", name="uq_content_review_items_source_kind"),
    )
    op.create_index("ix_content_review_items_id", "content_review_items", ["id"])
    op.create_index("ix_content_review_items_blog_id", "content_review_items", ["blog_id"])
    op.create_index("ix_content_review_items_source_type", "content_review_items", ["source_type"])
    op.create_index("ix_content_review_items_source_id", "content_review_items", ["source_id"])
    op.create_index("ix_content_review_items_review_kind", "content_review_items", ["review_kind"])
    op.create_index("ix_content_review_items_risk_level", "content_review_items", ["risk_level"])
    op.create_index("ix_content_review_items_approval_status", "content_review_items", ["approval_status"])
    op.create_index("ix_content_review_items_apply_status", "content_review_items", ["apply_status"])
    op.create_index("ix_content_review_items_learning_state", "content_review_items", ["learning_state"])

    op.create_table(
        "content_review_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False, server_default="system"),
        sa.Column("channel", sa.String(length=30), nullable=False, server_default="system"),
        sa.Column("result_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["content_review_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_review_actions_id", "content_review_actions", ["id"])
    op.create_index("ix_content_review_actions_item_id", "content_review_actions", ["item_id"])
    op.create_index("ix_content_review_actions_action", "content_review_actions", ["action"])


def downgrade() -> None:
    op.drop_index("ix_content_review_actions_action", table_name="content_review_actions")
    op.drop_index("ix_content_review_actions_item_id", table_name="content_review_actions")
    op.drop_index("ix_content_review_actions_id", table_name="content_review_actions")
    op.drop_table("content_review_actions")

    op.drop_index("ix_content_review_items_learning_state", table_name="content_review_items")
    op.drop_index("ix_content_review_items_apply_status", table_name="content_review_items")
    op.drop_index("ix_content_review_items_approval_status", table_name="content_review_items")
    op.drop_index("ix_content_review_items_risk_level", table_name="content_review_items")
    op.drop_index("ix_content_review_items_review_kind", table_name="content_review_items")
    op.drop_index("ix_content_review_items_source_id", table_name="content_review_items")
    op.drop_index("ix_content_review_items_source_type", table_name="content_review_items")
    op.drop_index("ix_content_review_items_blog_id", table_name="content_review_items")
    op.drop_index("ix_content_review_items_id", table_name="content_review_items")
    op.drop_table("content_review_items")
