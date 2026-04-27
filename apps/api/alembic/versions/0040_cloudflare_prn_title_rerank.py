"""add Cloudflare PRN title reranking

Revision ID: 0040_cloudflare_prn_title_rerank
Revises: 0039_cloudflare_persona_packs
Create Date: 2026-04-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0040_cloudflare_prn_title_rerank"
down_revision = "0039_cloudflare_persona_packs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloudflare_prn_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("managed_channel_id", sa.Integer(), nullable=False),
        sa.Column("category_slug", sa.String(length=120), nullable=False),
        sa.Column("keyword", sa.String(length=500), nullable=False),
        sa.Column("article_pattern_id", sa.String(length=100), nullable=True),
        sa.Column("article_pattern_version", sa.Integer(), nullable=True),
        sa.Column("persona_pack_key", sa.String(length=120), nullable=True),
        sa.Column("persona_pack_version", sa.Integer(), nullable=True),
        sa.Column("prn_version", sa.Integer(), nullable=False),
        sa.Column("selected_title", sa.String(length=500), nullable=False),
        sa.Column("selected_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["managed_channel_id"], ["managed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cloudflare_prn_runs_id"), "cloudflare_prn_runs", ["id"], unique=False)
    op.create_index(op.f("ix_cloudflare_prn_runs_managed_channel_id"), "cloudflare_prn_runs", ["managed_channel_id"], unique=False)
    op.create_index(op.f("ix_cloudflare_prn_runs_category_slug"), "cloudflare_prn_runs", ["category_slug"], unique=False)
    op.create_index(op.f("ix_cloudflare_prn_runs_article_pattern_id"), "cloudflare_prn_runs", ["article_pattern_id"], unique=False)
    op.create_index(op.f("ix_cloudflare_prn_runs_persona_pack_key"), "cloudflare_prn_runs", ["persona_pack_key"], unique=False)
    op.create_index(op.f("ix_cloudflare_prn_runs_status"), "cloudflare_prn_runs", ["status"], unique=False)
    op.create_index(
        "ix_cloudflare_prn_runs_channel_category_created",
        "cloudflare_prn_runs",
        ["managed_channel_id", "category_slug", "created_at"],
        unique=False,
    )
    op.alter_column("cloudflare_prn_runs", "payload", server_default=None)

    op.create_table(
        "cloudflare_prn_title_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("prn_score", sa.Float(), nullable=True),
        sa.Column("ctr_quality_score", sa.Float(), nullable=True),
        sa.Column("practicality_score", sa.Float(), nullable=True),
        sa.Column("pattern_fit_score", sa.Float(), nullable=True),
        sa.Column("forbidden_hygiene_score", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("rejection_reason", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["cloudflare_prn_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cloudflare_prn_title_candidates_id"), "cloudflare_prn_title_candidates", ["id"], unique=False)
    op.create_index(op.f("ix_cloudflare_prn_title_candidates_run_id"), "cloudflare_prn_title_candidates", ["run_id"], unique=False)
    op.create_index(op.f("ix_cloudflare_prn_title_candidates_decision"), "cloudflare_prn_title_candidates", ["decision"], unique=False)
    op.create_index(
        "ix_cloudflare_prn_title_candidates_run_rank",
        "cloudflare_prn_title_candidates",
        ["run_id", "rank"],
        unique=False,
    )
    op.alter_column("cloudflare_prn_title_candidates", "payload", server_default=None)

    op.add_column("synced_cloudflare_posts", sa.Column("prn_run_id", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("prn_version", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("title_candidate_count", sa.Integer(), nullable=True))
    op.add_column("synced_cloudflare_posts", sa.Column("title_final_score", sa.Float(), nullable=True))
    op.add_column(
        "synced_cloudflare_posts",
        sa.Column("title_rerank_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.create_foreign_key(
        "fk_synced_cloudflare_posts_prn_run_id",
        "synced_cloudflare_posts",
        "cloudflare_prn_runs",
        ["prn_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_synced_cloudflare_posts_prn_run_id"), "synced_cloudflare_posts", ["prn_run_id"], unique=False)
    op.alter_column("synced_cloudflare_posts", "title_rerank_payload", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_synced_cloudflare_posts_prn_run_id"), table_name="synced_cloudflare_posts")
    op.drop_constraint("fk_synced_cloudflare_posts_prn_run_id", "synced_cloudflare_posts", type_="foreignkey")
    op.drop_column("synced_cloudflare_posts", "title_rerank_payload")
    op.drop_column("synced_cloudflare_posts", "title_final_score")
    op.drop_column("synced_cloudflare_posts", "title_candidate_count")
    op.drop_column("synced_cloudflare_posts", "prn_version")
    op.drop_column("synced_cloudflare_posts", "prn_run_id")

    op.drop_index("ix_cloudflare_prn_title_candidates_run_rank", table_name="cloudflare_prn_title_candidates")
    op.drop_index(op.f("ix_cloudflare_prn_title_candidates_decision"), table_name="cloudflare_prn_title_candidates")
    op.drop_index(op.f("ix_cloudflare_prn_title_candidates_run_id"), table_name="cloudflare_prn_title_candidates")
    op.drop_index(op.f("ix_cloudflare_prn_title_candidates_id"), table_name="cloudflare_prn_title_candidates")
    op.drop_table("cloudflare_prn_title_candidates")

    op.drop_index("ix_cloudflare_prn_runs_channel_category_created", table_name="cloudflare_prn_runs")
    op.drop_index(op.f("ix_cloudflare_prn_runs_status"), table_name="cloudflare_prn_runs")
    op.drop_index(op.f("ix_cloudflare_prn_runs_persona_pack_key"), table_name="cloudflare_prn_runs")
    op.drop_index(op.f("ix_cloudflare_prn_runs_article_pattern_id"), table_name="cloudflare_prn_runs")
    op.drop_index(op.f("ix_cloudflare_prn_runs_category_slug"), table_name="cloudflare_prn_runs")
    op.drop_index(op.f("ix_cloudflare_prn_runs_managed_channel_id"), table_name="cloudflare_prn_runs")
    op.drop_index(op.f("ix_cloudflare_prn_runs_id"), table_name="cloudflare_prn_runs")
    op.drop_table("cloudflare_prn_runs")
