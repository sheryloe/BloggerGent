"""content item blocked reason and publication error codes

Revision ID: 0022_content_item_pub_errors
Revises: 0021_content_item_idempotency
Create Date: 2026-04-04 00:00:03.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_content_item_pub_errors"
down_revision = "0021_content_item_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_items", sa.Column("blocked_reason", sa.String(length=120), nullable=True))
    op.create_index(op.f("ix_content_items_blocked_reason"), "content_items", ["blocked_reason"], unique=False)

    op.add_column(
        "publication_records",
        sa.Column("target_state", sa.String(length=40), nullable=False, server_default="publish"),
    )
    op.add_column("publication_records", sa.Column("error_code", sa.String(length=50), nullable=True))
    op.create_index(op.f("ix_publication_records_target_state"), "publication_records", ["target_state"], unique=False)
    op.create_index(op.f("ix_publication_records_error_code"), "publication_records", ["error_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_publication_records_error_code"), table_name="publication_records")
    op.drop_index(op.f("ix_publication_records_target_state"), table_name="publication_records")
    op.drop_column("publication_records", "error_code")
    op.drop_column("publication_records", "target_state")

    op.drop_index(op.f("ix_content_items_blocked_reason"), table_name="content_items")
    op.drop_column("content_items", "blocked_reason")
