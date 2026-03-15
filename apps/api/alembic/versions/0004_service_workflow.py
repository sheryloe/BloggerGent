"""Add workflow stage model and import profile fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_service_workflow"
down_revision = "0003_google_reporting_fields"
branch_labels = None
depends_on = None


workflow_stage_type = postgresql.ENUM(
    "topic_discovery",
    "article_generation",
    "image_prompt_generation",
    "related_posts",
    "image_generation",
    "html_assembly",
    "publishing",
    name="workflow_stage_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    workflow_stage_type.create(bind, checkfirst=True)

    op.add_column("blogs", sa.Column("profile_key", sa.String(length=50), nullable=True))
    op.add_column("blogs", sa.Column("blogger_url", sa.String(length=500), nullable=True))

    op.add_column("blog_agent_configs", sa.Column("stage_type", workflow_stage_type, nullable=True))
    op.add_column("blog_agent_configs", sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()))

    conn = bind
    conn.execute(
        sa.text(
            """
            UPDATE blogs
            SET profile_key = CASE
                WHEN content_category = 'travel' THEN 'korea_travel'
                WHEN content_category = 'mystery' THEN 'world_mystery'
                ELSE 'custom'
            END
            WHERE profile_key IS NULL
            """
        )
    )
    op.alter_column("blogs", "profile_key", nullable=False)

    conn.execute(
        sa.text(
            """
            UPDATE blog_agent_configs
            SET stage_type = (
                CASE agent_key
                    WHEN 'topic_discovery' THEN 'topic_discovery'
                    WHEN 'article_generation' THEN 'article_generation'
                    WHEN 'collage_prompt' THEN 'image_prompt_generation'
                    ELSE agent_key
                END
            )::workflow_stage_type
            """
        )
    )
    conn.execute(sa.text("UPDATE blog_agent_configs SET agent_key = 'image_prompt_generation' WHERE agent_key = 'collage_prompt'"))
    conn.execute(
        sa.text(
            """
            UPDATE blog_agent_configs
            SET is_required = CASE
                WHEN stage_type IN (
                    'article_generation'::workflow_stage_type,
                    'image_generation'::workflow_stage_type,
                    'html_assembly'::workflow_stage_type,
                    'publishing'::workflow_stage_type
                ) THEN TRUE
                ELSE FALSE
            END
            """
        )
    )

    blog_rows = conn.execute(sa.text("SELECT id FROM blogs ORDER BY id ASC")).mappings().all()
    inserts = (
        ("related_posts", "관련 글 구성 단계", "System Related Posts Step", "관련 글 후보를 연결합니다.", None, True, False, 40),
        ("image_generation", "이미지 생성 단계", "System Image Generation Step", "대표 이미지를 생성합니다.", "openai_image", True, True, 50),
        ("html_assembly", "HTML 조립 단계", "System HTML Assembly Step", "최종 HTML을 조립합니다.", None, True, True, 60),
        ("publishing", "Blogger 발행 단계", "System Publishing Step", "최종 HTML을 Blogger에 게시합니다.", "blogger", True, True, 70),
    )
    for blog in blog_rows:
        for stage_type, name, role_name, objective, provider_hint, is_enabled, is_required, sort_order in inserts:
            exists = conn.execute(
                sa.text(
                    """
                    SELECT 1
                    FROM blog_agent_configs
                    WHERE blog_id = :blog_id AND stage_type = CAST(:stage_type AS workflow_stage_type)
                    LIMIT 1
                    """
                ),
                {"blog_id": blog["id"], "stage_type": stage_type},
            ).scalar_one_or_none()
            if exists:
                continue
            conn.execute(
                sa.text(
                    """
                    INSERT INTO blog_agent_configs (
                        blog_id, agent_key, stage_type, name, role_name, objective, prompt_template,
                        provider_hint, is_enabled, is_required, sort_order, created_at, updated_at
                    ) VALUES (
                        :blog_id, :agent_key, CAST(:stage_type AS workflow_stage_type), :name, :role_name, :objective, :prompt_template,
                        :provider_hint, :is_enabled, :is_required, :sort_order, NOW(), NOW()
                    )
                    """
                ),
                {
                    "blog_id": blog["id"],
                    "agent_key": stage_type,
                    "stage_type": stage_type,
                    "name": name,
                    "role_name": role_name,
                    "objective": objective,
                    "prompt_template": "",
                    "provider_hint": provider_hint,
                    "is_enabled": is_enabled,
                    "is_required": is_required,
                    "sort_order": sort_order,
                },
            )

    op.alter_column("blog_agent_configs", "stage_type", nullable=False)
    op.create_index("ix_blog_agent_configs_stage_type", "blog_agent_configs", ["stage_type"])
    op.create_unique_constraint("uq_blog_agent_configs_blog_stage", "blog_agent_configs", ["blog_id", "stage_type"])


def downgrade() -> None:
    op.drop_constraint("uq_blog_agent_configs_blog_stage", "blog_agent_configs", type_="unique")
    op.drop_index("ix_blog_agent_configs_stage_type", table_name="blog_agent_configs")
    op.drop_column("blog_agent_configs", "is_required")
    op.drop_column("blog_agent_configs", "stage_type")
    op.drop_column("blogs", "blogger_url")
    op.drop_column("blogs", "profile_key")
    workflow_stage_type.drop(op.get_bind(), checkfirst=True)
