"""Add synced Blogger posts table."""

from alembic import op
import sqlalchemy as sa


revision = "0007_synced_blogger_posts"
down_revision = "0006_wf_models_seo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "synced_blogger_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("remote_post_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_remote", sa.DateTime(timezone=True), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("author_display_name", sa.String(length=255), nullable=True),
        sa.Column("replies_total_items", sa.Integer(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_id", "remote_post_id", name="uq_synced_blogger_posts_blog_remote_post"),
    )
    op.create_index(op.f("ix_synced_blogger_posts_id"), "synced_blogger_posts", ["id"], unique=False)
    op.create_index(op.f("ix_synced_blogger_posts_blog_id"), "synced_blogger_posts", ["blog_id"], unique=False)
    op.create_index(op.f("ix_synced_blogger_posts_remote_post_id"), "synced_blogger_posts", ["remote_post_id"], unique=False)
    op.create_index(op.f("ix_synced_blogger_posts_published_at"), "synced_blogger_posts", ["published_at"], unique=False)
    op.create_index(op.f("ix_synced_blogger_posts_updated_at_remote"), "synced_blogger_posts", ["updated_at_remote"], unique=False)
    op.create_index(op.f("ix_synced_blogger_posts_synced_at"), "synced_blogger_posts", ["synced_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_synced_blogger_posts_synced_at"), table_name="synced_blogger_posts")
    op.drop_index(op.f("ix_synced_blogger_posts_updated_at_remote"), table_name="synced_blogger_posts")
    op.drop_index(op.f("ix_synced_blogger_posts_published_at"), table_name="synced_blogger_posts")
    op.drop_index(op.f("ix_synced_blogger_posts_remote_post_id"), table_name="synced_blogger_posts")
    op.drop_index(op.f("ix_synced_blogger_posts_blog_id"), table_name="synced_blogger_posts")
    op.drop_index(op.f("ix_synced_blogger_posts_id"), table_name="synced_blogger_posts")
    op.drop_table("synced_blogger_posts")
