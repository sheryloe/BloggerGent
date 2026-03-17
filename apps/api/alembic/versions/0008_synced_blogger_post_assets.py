"""Add thumbnail and excerpt fields to synced Blogger posts."""

from alembic import op
import sqlalchemy as sa


revision = "0008_synced_blogger_post_assets"
down_revision = "0007_synced_blogger_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("synced_blogger_posts", sa.Column("thumbnail_url", sa.String(length=1000), nullable=True))
    op.add_column(
        "synced_blogger_posts",
        sa.Column("excerpt_text", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("synced_blogger_posts", "excerpt_text")
    op.drop_column("synced_blogger_posts", "thumbnail_url")
