"""Add inline_media column to articles."""

from alembic import op
import sqlalchemy as sa


revision = "0011_article_inline_media"
down_revision = "0010_usage_queue_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("articles")}
    if "inline_media" not in columns:
        op.add_column(
            "articles",
            sa.Column("inline_media", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        )
        op.alter_column("articles", "inline_media", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("articles")}
    if "inline_media" in columns:
        op.drop_column("articles", "inline_media")
