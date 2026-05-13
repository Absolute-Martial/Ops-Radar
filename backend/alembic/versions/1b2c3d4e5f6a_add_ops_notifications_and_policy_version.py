"""add ops notifications and policy version

Revision ID: 1b2c3d4e5f6a
Revises: 0f1e2d3c4b5a
Create Date: 2026-05-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "1b2c3d4e5f6a"
down_revision = "0f1e2d3c4b5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "op_request_policy_results",
        sa.Column("policy_version", sa.String(), nullable=False, server_default="opsradar-v1"),
    )

    op.create_table(
        "op_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_email", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["op_request_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_notifications_workspace_id", "op_notifications", ["workspace_id"])
    op.create_index("ix_op_notifications_request_id", "op_notifications", ["request_id"])
    op.create_index("ix_op_notifications_event_id", "op_notifications", ["event_id"])
    op.create_index("ix_op_notifications_recipient_user_id", "op_notifications", ["recipient_user_id"])
    op.create_index("ix_op_notifications_recipient_email", "op_notifications", ["recipient_email"])
    op.create_index("ix_op_notifications_channel", "op_notifications", ["channel"])
    op.create_index("ix_op_notifications_event_type", "op_notifications", ["event_type"])
    op.create_index("ix_op_notifications_status", "op_notifications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_op_notifications_status", table_name="op_notifications")
    op.drop_index("ix_op_notifications_event_type", table_name="op_notifications")
    op.drop_index("ix_op_notifications_channel", table_name="op_notifications")
    op.drop_index("ix_op_notifications_recipient_email", table_name="op_notifications")
    op.drop_index("ix_op_notifications_recipient_user_id", table_name="op_notifications")
    op.drop_index("ix_op_notifications_event_id", table_name="op_notifications")
    op.drop_index("ix_op_notifications_request_id", table_name="op_notifications")
    op.drop_index("ix_op_notifications_workspace_id", table_name="op_notifications")
    op.drop_table("op_notifications")
    op.drop_column("op_request_policy_results", "policy_version")
