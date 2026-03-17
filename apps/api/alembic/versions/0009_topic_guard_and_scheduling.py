"""Add topic guard memory and Blogger scheduling fields."""

from alembic import op
import sqlalchemy as sa


revision = "0009_topic_guard_and_scheduling"
down_revision = "0008_synced_blogger_post_assets"
branch_labels = None
depends_on = None


post_status = sa.Enum("draft", "scheduled", "published", name="post_status")


def upgrade() -> None:
    bind = op.get_bind()
    post_status.create(bind, checkfirst=True)

    op.add_column("topics", sa.Column("topic_cluster_label", sa.String(length=255), nullable=True))
    op.add_column("topics", sa.Column("topic_angle_label", sa.String(length=255), nullable=True))
    op.add_column("topics", sa.Column("distinct_reason", sa.Text(), nullable=True))

    op.add_column(
        "blogger_posts",
        sa.Column("post_status", post_status, nullable=False, server_default="draft"),
    )
    op.add_column("blogger_posts", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE blogger_posts SET post_status = 'published' WHERE is_draft = false")
    op.execute("UPDATE blogger_posts SET post_status = 'draft' WHERE is_draft = true")

    op.create_table(
        "topic_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("blog_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("canonical_url", sa.String(length=1000), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("topic_cluster_key", sa.String(length=255), nullable=False),
        sa.Column("topic_cluster_label", sa.String(length=255), nullable=False),
        sa.Column("topic_angle_key", sa.String(length=255), nullable=False),
        sa.Column("topic_angle_label", sa.String(length=255), nullable=False),
        sa.Column("entity_names", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["blog_id"], ["blogs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("blog_id", "source_type", "source_id", name="uq_topic_memories_blog_source"),
    )
    op.create_index("ix_topic_memories_id", "topic_memories", ["id"])
    op.create_index("ix_topic_memories_blog_id", "topic_memories", ["blog_id"])
    op.create_index("ix_topic_memories_source_type", "topic_memories", ["source_type"])
    op.create_index("ix_topic_memories_source_id", "topic_memories", ["source_id"])
    op.create_index("ix_topic_memories_canonical_url", "topic_memories", ["canonical_url"])
    op.create_index("ix_topic_memories_published_at", "topic_memories", ["published_at"])
    op.create_index("ix_topic_memories_topic_cluster_key", "topic_memories", ["topic_cluster_key"])
    op.create_index("ix_topic_memories_topic_angle_key", "topic_memories", ["topic_angle_key"])


def downgrade() -> None:
    op.drop_index("ix_topic_memories_topic_angle_key", table_name="topic_memories")
    op.drop_index("ix_topic_memories_topic_cluster_key", table_name="topic_memories")
    op.drop_index("ix_topic_memories_published_at", table_name="topic_memories")
    op.drop_index("ix_topic_memories_canonical_url", table_name="topic_memories")
    op.drop_index("ix_topic_memories_source_id", table_name="topic_memories")
    op.drop_index("ix_topic_memories_source_type", table_name="topic_memories")
    op.drop_index("ix_topic_memories_blog_id", table_name="topic_memories")
    op.drop_index("ix_topic_memories_id", table_name="topic_memories")
    op.drop_table("topic_memories")

    op.drop_column("blogger_posts", "scheduled_for")
    op.drop_column("blogger_posts", "post_status")

    op.drop_column("topics", "distinct_reason")
    op.drop_column("topics", "topic_angle_label")
    op.drop_column("topics", "topic_cluster_label")

    bind = op.get_bind()
    post_status.drop(bind, checkfirst=True)
