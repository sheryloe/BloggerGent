"""Add editorial category fields to topics and articles."""

from alembic import op
import sqlalchemy as sa


revision = "0014_editorial_categories"
down_revision = "0013_content_review_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("topics", sa.Column("editorial_category_key", sa.String(length=100), nullable=True))
    op.add_column("topics", sa.Column("editorial_category_label", sa.String(length=100), nullable=True))
    op.add_column("articles", sa.Column("editorial_category_key", sa.String(length=100), nullable=True))
    op.add_column("articles", sa.Column("editorial_category_label", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "editorial_category_label")
    op.drop_column("articles", "editorial_category_key")
    op.drop_column("topics", "editorial_category_label")
    op.drop_column("topics", "editorial_category_key")
