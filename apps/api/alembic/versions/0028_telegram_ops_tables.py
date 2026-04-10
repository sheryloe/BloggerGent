"""Add Telegram operation tables for bindings, subscriptions, and telemetry.

Revision ID: 0028_telegram_ops_tables
Revises: 0027_live_audit_and_cloudflare_canonical_fields
Create Date: 2026-04-10 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_telegram_ops_tables"
down_revision = "0027_live_audit_and_cloudflare_canonical_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_chat_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=120), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("chat_title", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", name="uq_telegram_chat_bindings_chat_id"),
    )
    op.create_index(op.f("ix_telegram_chat_bindings_id"), "telegram_chat_bindings", ["id"], unique=False)
    op.create_index(op.f("ix_telegram_chat_bindings_chat_id"), "telegram_chat_bindings", ["chat_id"], unique=False)
    op.create_index(op.f("ix_telegram_chat_bindings_channel_id"), "telegram_chat_bindings", ["channel_id"], unique=False)
    with op.batch_alter_table("telegram_chat_bindings") as batch_op:
        batch_op.alter_column("is_admin", existing_type=sa.Boolean(), server_default=None)
        batch_op.alter_column("is_active", existing_type=sa.Boolean(), server_default=None)
        batch_op.alter_column("metadata", existing_type=sa.JSON(), server_default=None)

    op.create_table(
        "telegram_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_binding_id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["chat_binding_id"], ["telegram_chat_bindings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chat_binding_id",
            "event_key",
            name="uq_telegram_subscriptions_chat_binding_event_key",
        ),
    )
    op.create_index(op.f("ix_telegram_subscriptions_id"), "telegram_subscriptions", ["id"], unique=False)
    op.create_index(
        op.f("ix_telegram_subscriptions_chat_binding_id"),
        "telegram_subscriptions",
        ["chat_binding_id"],
        unique=False,
    )
    op.create_index(op.f("ix_telegram_subscriptions_event_key"), "telegram_subscriptions", ["event_key"], unique=False)
    with op.batch_alter_table("telegram_subscriptions") as batch_op:
        batch_op.alter_column("is_enabled", existing_type=sa.Boolean(), server_default=None)
        batch_op.alter_column("config_payload", existing_type=sa.JSON(), server_default=None)

    op.create_table(
        "telegram_command_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("command", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telegram_command_events_id"), "telegram_command_events", ["id"], unique=False)
    op.create_index(op.f("ix_telegram_command_events_chat_id"), "telegram_command_events", ["chat_id"], unique=False)
    op.create_index(op.f("ix_telegram_command_events_user_id"), "telegram_command_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_telegram_command_events_command"), "telegram_command_events", ["command"], unique=False)
    op.create_index(op.f("ix_telegram_command_events_status"), "telegram_command_events", ["status"], unique=False)
    op.create_index(
        op.f("ix_telegram_command_events_created_at"),
        "telegram_command_events",
        ["created_at"],
        unique=False,
    )
    with op.batch_alter_table("telegram_command_events") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=30), server_default=None)
        batch_op.alter_column("payload", existing_type=sa.JSON(), server_default=None)

    op.create_table(
        "telegram_delivery_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("message_type", sa.String(length=50), nullable=False, server_default=sa.text("'message'")),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'sent'")),
        sa.Column("error_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(op.f("ix_telegram_delivery_events_id"), "telegram_delivery_events", ["id"], unique=False)
    op.create_index(op.f("ix_telegram_delivery_events_chat_id"), "telegram_delivery_events", ["chat_id"], unique=False)
    op.create_index(
        op.f("ix_telegram_delivery_events_message_type"),
        "telegram_delivery_events",
        ["message_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_delivery_events_dedupe_key"),
        "telegram_delivery_events",
        ["dedupe_key"],
        unique=False,
    )
    op.create_index(op.f("ix_telegram_delivery_events_status"), "telegram_delivery_events", ["status"], unique=False)
    op.create_index(
        op.f("ix_telegram_delivery_events_created_at"),
        "telegram_delivery_events",
        ["created_at"],
        unique=False,
    )
    with op.batch_alter_table("telegram_delivery_events") as batch_op:
        batch_op.alter_column("message_type", existing_type=sa.String(length=50), server_default=None)
        batch_op.alter_column("status", existing_type=sa.String(length=30), server_default=None)
        batch_op.alter_column("payload", existing_type=sa.JSON(), server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_telegram_delivery_events_created_at"), table_name="telegram_delivery_events")
    op.drop_index(op.f("ix_telegram_delivery_events_status"), table_name="telegram_delivery_events")
    op.drop_index(op.f("ix_telegram_delivery_events_dedupe_key"), table_name="telegram_delivery_events")
    op.drop_index(op.f("ix_telegram_delivery_events_message_type"), table_name="telegram_delivery_events")
    op.drop_index(op.f("ix_telegram_delivery_events_chat_id"), table_name="telegram_delivery_events")
    op.drop_index(op.f("ix_telegram_delivery_events_id"), table_name="telegram_delivery_events")
    op.drop_table("telegram_delivery_events")

    op.drop_index(op.f("ix_telegram_command_events_created_at"), table_name="telegram_command_events")
    op.drop_index(op.f("ix_telegram_command_events_status"), table_name="telegram_command_events")
    op.drop_index(op.f("ix_telegram_command_events_command"), table_name="telegram_command_events")
    op.drop_index(op.f("ix_telegram_command_events_user_id"), table_name="telegram_command_events")
    op.drop_index(op.f("ix_telegram_command_events_chat_id"), table_name="telegram_command_events")
    op.drop_index(op.f("ix_telegram_command_events_id"), table_name="telegram_command_events")
    op.drop_table("telegram_command_events")

    op.drop_index(op.f("ix_telegram_subscriptions_event_key"), table_name="telegram_subscriptions")
    op.drop_index(op.f("ix_telegram_subscriptions_chat_binding_id"), table_name="telegram_subscriptions")
    op.drop_index(op.f("ix_telegram_subscriptions_id"), table_name="telegram_subscriptions")
    op.drop_table("telegram_subscriptions")

    op.drop_index(op.f("ix_telegram_chat_bindings_channel_id"), table_name="telegram_chat_bindings")
    op.drop_index(op.f("ix_telegram_chat_bindings_chat_id"), table_name="telegram_chat_bindings")
    op.drop_index(op.f("ix_telegram_chat_bindings_id"), table_name="telegram_chat_bindings")
    op.drop_table("telegram_chat_bindings")
