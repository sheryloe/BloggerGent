"""Add workflow model fields and per-blog SEO meta patch state."""

from alembic import op
import sqlalchemy as sa


revision = "0006_wf_models_seo"
down_revision = "0005_job_status_stopped"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blog_agent_configs",
        sa.Column("provider_model", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "blogs",
        sa.Column("seo_theme_patch_installed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "blogs",
        sa.Column("seo_theme_patch_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        sa.text(
            """
            UPDATE blog_agent_configs
            SET provider_model = CASE
                WHEN provider_hint = 'gemini' THEN 'gemini-2.5-flash'
                WHEN provider_hint = 'openai_text' THEN 'gpt-4.1-mini'
                WHEN provider_hint = 'openai_image' THEN 'dall-e-3'
                WHEN provider_hint = 'blogger' THEN 'blogger-v3'
                ELSE NULL
            END
            """
        )
    )

    op.alter_column("blogs", "seo_theme_patch_installed", server_default=None)


def downgrade() -> None:
    op.drop_column("blogs", "seo_theme_patch_verified_at")
    op.drop_column("blogs", "seo_theme_patch_installed")
    op.drop_column("blog_agent_configs", "provider_model")
