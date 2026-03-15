"""Add multi-blog service model and blog-scoped agents."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_multi_blog_service"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


publish_mode = postgresql.ENUM("draft", "publish", name="publish_mode", create_type=False)


def upgrade() -> None:
    op.create_table(
        "blogs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content_category", sa.String(length=50), nullable=False, server_default="custom"),
        sa.Column("primary_language", sa.String(length=20), nullable=False, server_default="en"),
        sa.Column("target_audience", sa.String(length=255), nullable=True),
        sa.Column("content_brief", sa.Text(), nullable=True),
        sa.Column("blogger_blog_id", sa.String(length=255), nullable=True),
        sa.Column("publish_mode", publish_mode, nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_blogs_id", "blogs", ["id"])
    op.create_index("ix_blogs_slug", "blogs", ["slug"])

    op.create_table(
        "blog_agent_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("blog_id", sa.Integer(), sa.ForeignKey("blogs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_key", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("role_name", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("provider_hint", sa.String(length=50), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("blog_id", "agent_key", name="uq_blog_agent_configs_blog_agent"),
    )
    op.create_index("ix_blog_agent_configs_id", "blog_agent_configs", ["id"])
    op.create_index("ix_blog_agent_configs_blog_id", "blog_agent_configs", ["blog_id"])
    op.create_index("ix_blog_agent_configs_agent_key", "blog_agent_configs", ["agent_key"])

    op.add_column("topics", sa.Column("blog_id", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("blog_id", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("blog_id", sa.Integer(), nullable=True))
    op.add_column("blogger_posts", sa.Column("blog_id", sa.Integer(), nullable=True))

    op.create_index("ix_topics_blog_id", "topics", ["blog_id"])
    op.create_index("ix_jobs_blog_id", "jobs", ["blog_id"])
    op.create_index("ix_articles_blog_id", "articles", ["blog_id"])
    op.create_index("ix_blogger_posts_blog_id", "blogger_posts", ["blog_id"])

    op.create_foreign_key("fk_topics_blog_id", "topics", "blogs", ["blog_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_jobs_blog_id", "jobs", "blogs", ["blog_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_articles_blog_id", "articles", "blogs", ["blog_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_blogger_posts_blog_id", "blogger_posts", "blogs", ["blog_id"], ["id"], ondelete="CASCADE")

    conn = op.get_bind()
    travel_blog_id = conn.execute(
        sa.text(
            """
            INSERT INTO blogs (
                name, slug, description, content_category, primary_language, target_audience,
                content_brief, blogger_blog_id, publish_mode, is_active
            ) VALUES (
                :name, :slug, :description, :content_category, :primary_language, :target_audience,
                :content_brief, :blogger_blog_id, :publish_mode, :is_active
            )
            RETURNING id
            """
        ),
        {
            "name": "Korea Travel & Events",
            "slug": "korea-travel-and-events",
            "description": "외국인 방문자를 위한 한국 여행 및 행사 정보 블로그",
            "content_category": "travel",
            "primary_language": "en",
            "target_audience": "First-time international visitors planning a Korea trip",
            "content_brief": "외국인을 위한 한국 여행, 행사, 문화, 맛집 가이드",
            "blogger_blog_id": None,
            "publish_mode": "draft",
            "is_active": True,
        },
    ).scalar_one()

    conn.execute(
        sa.text(
            """
            INSERT INTO blogs (
                name, slug, description, content_category, primary_language, target_audience,
                content_brief, blogger_blog_id, publish_mode, is_active
            ) VALUES (
                :name, :slug, :description, :content_category, :primary_language, :target_audience,
                :content_brief, :blogger_blog_id, :publish_mode, :is_active
            )
            """
        ),
        {
            "name": "World Mystery Documentary",
            "slug": "world-mystery-documentary",
            "description": "세계 미스터리, 전설, 다큐멘터리형 실화 블로그",
            "content_category": "mystery",
            "primary_language": "en",
            "target_audience": "Global readers interested in mysteries, legends, and documentaries",
            "content_brief": "미스터리, 전설, 실화, 다큐멘터리형 서사",
            "blogger_blog_id": None,
            "publish_mode": "draft",
            "is_active": True,
        },
    )

    conn.execute(sa.text("UPDATE topics SET blog_id = :blog_id WHERE blog_id IS NULL"), {"blog_id": travel_blog_id})
    conn.execute(sa.text("UPDATE jobs SET blog_id = :blog_id WHERE blog_id IS NULL"), {"blog_id": travel_blog_id})
    conn.execute(sa.text("UPDATE articles SET blog_id = :blog_id WHERE blog_id IS NULL"), {"blog_id": travel_blog_id})
    conn.execute(sa.text("UPDATE blogger_posts SET blog_id = :blog_id WHERE blog_id IS NULL"), {"blog_id": travel_blog_id})

    op.alter_column("topics", "blog_id", nullable=False)
    op.alter_column("jobs", "blog_id", nullable=False)
    op.alter_column("articles", "blog_id", nullable=False)
    op.alter_column("blogger_posts", "blog_id", nullable=False)

    op.execute("ALTER TABLE topics DROP CONSTRAINT IF EXISTS topics_keyword_key")
    op.create_unique_constraint("uq_topics_blog_keyword", "topics", ["blog_id", "keyword"])

    op.execute("ALTER TABLE articles DROP CONSTRAINT IF EXISTS articles_slug_key")
    op.create_unique_constraint("uq_articles_blog_slug", "articles", ["blog_id", "slug"])


def downgrade() -> None:
    op.drop_constraint("uq_articles_blog_slug", "articles", type_="unique")
    op.create_unique_constraint("articles_slug_key", "articles", ["slug"])

    op.drop_constraint("uq_topics_blog_keyword", "topics", type_="unique")
    op.create_unique_constraint("topics_keyword_key", "topics", ["keyword"])

    op.drop_constraint("fk_blogger_posts_blog_id", "blogger_posts", type_="foreignkey")
    op.drop_constraint("fk_articles_blog_id", "articles", type_="foreignkey")
    op.drop_constraint("fk_jobs_blog_id", "jobs", type_="foreignkey")
    op.drop_constraint("fk_topics_blog_id", "topics", type_="foreignkey")

    op.drop_index("ix_blogger_posts_blog_id", table_name="blogger_posts")
    op.drop_index("ix_articles_blog_id", table_name="articles")
    op.drop_index("ix_jobs_blog_id", table_name="jobs")
    op.drop_index("ix_topics_blog_id", table_name="topics")

    op.drop_column("blogger_posts", "blog_id")
    op.drop_column("articles", "blog_id")
    op.drop_column("jobs", "blog_id")
    op.drop_column("topics", "blog_id")

    op.drop_index("ix_blog_agent_configs_agent_key", table_name="blog_agent_configs")
    op.drop_index("ix_blog_agent_configs_blog_id", table_name="blog_agent_configs")
    op.drop_index("ix_blog_agent_configs_id", table_name="blog_agent_configs")
    op.drop_table("blog_agent_configs")

    op.drop_index("ix_blogs_slug", table_name="blogs")
    op.drop_index("ix_blogs_id", table_name="blogs")
    op.drop_table("blogs")
