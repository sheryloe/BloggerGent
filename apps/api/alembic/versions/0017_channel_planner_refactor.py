"""channel planner refactor

Revision ID: 0017_channel_planner_refactor
Revises: 0016_planner_analytics_console
Create Date: 2026-04-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_channel_planner_refactor"
down_revision = "0016_planner_analytics_console"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("content_plan_days") as batch_op:
        batch_op.add_column(sa.Column("channel_id", sa.String(length=100), nullable=True))

    with op.batch_alter_table("content_plan_slots") as batch_op:
        batch_op.add_column(sa.Column("category_key", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("category_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("category_color", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("result_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    op.execute(
        """
        UPDATE content_plan_days
        SET channel_id = 'blogger:' || blog_id
        WHERE channel_id IS NULL AND blog_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE content_plan_slots
        SET category_key = (
                SELECT key
                FROM blog_themes
                WHERE blog_themes.id = content_plan_slots.theme_id
            ),
            category_name = (
                SELECT name
                FROM blog_themes
                WHERE blog_themes.id = content_plan_slots.theme_id
            ),
            category_color = (
                SELECT color
                FROM blog_themes
                WHERE blog_themes.id = content_plan_slots.theme_id
            )
        WHERE theme_id IS NOT NULL
        """
    )

    with op.batch_alter_table("content_plan_days") as batch_op:
        batch_op.alter_column("channel_id", existing_type=sa.String(length=100), nullable=False)
        batch_op.alter_column("blog_id", existing_type=sa.Integer(), nullable=True)
        batch_op.drop_constraint("uq_content_plan_days_blog_date", type_="unique")
        batch_op.create_unique_constraint("uq_content_plan_days_channel_date", ["channel_id", "plan_date"])
        batch_op.create_index(batch_op.f("ix_content_plan_days_channel_id"), ["channel_id"], unique=False)

    with op.batch_alter_table("content_plan_slots") as batch_op:
        batch_op.create_index(batch_op.f("ix_content_plan_slots_category_key"), ["category_key"], unique=False)
        batch_op.alter_column("result_payload", existing_type=sa.JSON(), server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("content_plan_slots") as batch_op:
        batch_op.drop_index(batch_op.f("ix_content_plan_slots_category_key"))
        batch_op.drop_column("result_payload")
        batch_op.drop_column("category_color")
        batch_op.drop_column("category_name")
        batch_op.drop_column("category_key")

    with op.batch_alter_table("content_plan_days") as batch_op:
        batch_op.drop_index(batch_op.f("ix_content_plan_days_channel_id"))
        batch_op.drop_constraint("uq_content_plan_days_channel_date", type_="unique")
        batch_op.create_unique_constraint("uq_content_plan_days_blog_date", ["blog_id", "plan_date"])
        batch_op.alter_column("blog_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("channel_id")
