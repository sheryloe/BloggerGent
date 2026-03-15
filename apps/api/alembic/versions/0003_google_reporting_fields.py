"""Add Google reporting fields to blogs."""

from alembic import op
import sqlalchemy as sa


revision = "0003_google_reporting_fields"
down_revision = "0002_multi_blog_service"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blogs", sa.Column("search_console_site_url", sa.String(length=500), nullable=True))
    op.add_column("blogs", sa.Column("ga4_property_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("blogs", "ga4_property_id")
    op.drop_column("blogs", "search_console_site_url")
