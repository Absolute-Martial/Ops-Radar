"""add ops request lifecycle tables

Revision ID: 0f1e2d3c4b5a
Revises: f6a7b8c9d0e1
Create Date: 2026-05-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0f1e2d3c4b5a"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "op_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("request_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("requester_user_id", sa.UUID(), nullable=True),
        sa.Column("requester_email", sa.String(), nullable=False),
        sa.Column("resource_key", sa.String(), nullable=True),
        sa.Column("resource_name", sa.String(), nullable=True),
        sa.Column("access_level", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("urgency", sa.String(), nullable=False, server_default="medium"),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
        sa.Column("source_type", sa.String(), nullable=False, server_default="catalog"),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("temporal_workflow_id", sa.String(), nullable=True),
        sa.Column("temporal_run_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["process_templates.id"]),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_requests_workspace_id", "op_requests", ["workspace_id"])
    op.create_index("ix_op_requests_template_id", "op_requests", ["template_id"])
    op.create_index("ix_op_requests_request_type", "op_requests", ["request_type"])
    op.create_index("ix_op_requests_requester_user_id", "op_requests", ["requester_user_id"])
    op.create_index("ix_op_requests_requester_email", "op_requests", ["requester_email"])
    op.create_index("ix_op_requests_resource_key", "op_requests", ["resource_key"])
    op.create_index("ix_op_requests_status", "op_requests", ["status"])
    op.create_index("ix_op_requests_workspace_status", "op_requests", ["workspace_id", "status"])

    op.create_table(
        "op_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("approver_role_key", sa.String(), nullable=False),
        sa.Column("approver_user_id", sa.UUID(), nullable=True),
        sa.Column("approver_email", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_approvals_request_id", "op_approvals", ["request_id"])
    op.create_index("ix_op_approvals_approver_role_key", "op_approvals", ["approver_role_key"])
    op.create_index("ix_op_approvals_approver_user_id", "op_approvals", ["approver_user_id"])
    op.create_index("ix_op_approvals_approver_email", "op_approvals", ["approver_email"])
    op.create_index("ix_op_approvals_status", "op_approvals", ["status"])
    op.create_index("ix_op_approvals_request_status", "op_approvals", ["request_id", "status"])

    op.create_table(
        "op_request_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_email", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_request_events_request_id", "op_request_events", ["request_id"])
    op.create_index("ix_op_request_events_event_type", "op_request_events", ["event_type"])

    op.create_table(
        "op_resources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False, server_default="software"),
        sa.Column("resource_key", sa.String(), nullable=False),
        sa.Column("resource_name", sa.String(), nullable=False),
        sa.Column("default_access_level", sa.String(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_resources_workspace_id", "op_resources", ["workspace_id"])
    op.create_index("ix_op_resources_resource_type", "op_resources", ["resource_type"])
    op.create_index("ix_op_resources_workspace_key", "op_resources", ["workspace_id", "resource_key"], unique=True)

    op.create_table(
        "op_request_comments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        sa.Column("author_email", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_request_comments_request_id", "op_request_comments", ["request_id"])

    op.create_table(
        "op_request_policy_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("engine", sa.String(), nullable=False, server_default="internal"),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
        sa.Column("reasons", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_result", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_request_policy_results_request_id", "op_request_policy_results", ["request_id"])

    op.create_table(
        "op_role_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("role_key", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_role_assignments_workspace_id", "op_role_assignments", ["workspace_id"])
    op.create_index("ix_op_role_assignments_user_id", "op_role_assignments", ["user_id"])
    op.create_index("ix_op_role_assignments_user_email", "op_role_assignments", ["user_email"])
    op.create_index("ix_op_role_assignments_role_key", "op_role_assignments", ["role_key"])
    op.create_index(
        "ix_op_role_assignments_workspace_user_role",
        "op_role_assignments",
        ["workspace_id", "user_id", "role_key"],
        unique=True,
    )

    op.create_table(
        "op_audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_email", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_snapshot", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["op_request_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_audit_log_workspace_id", "op_audit_log", ["workspace_id"])
    op.create_index("ix_op_audit_log_request_id", "op_audit_log", ["request_id"])
    op.create_index("ix_op_audit_log_event_id", "op_audit_log", ["event_id"])
    op.create_index("ix_op_audit_log_action", "op_audit_log", ["action"])

    op.create_table(
        "op_intake_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_project_or_channel", sa.String(), nullable=True),
        sa.Column("request_type_mapping", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("field_mapping", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence_threshold", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column("requires_human_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("metadata_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_intake_sources_workspace_id", "op_intake_sources", ["workspace_id"])
    op.create_index("ix_op_intake_sources_source_type", "op_intake_sources", ["source_type"])
    op.create_index("ix_op_intake_sources_workspace_type", "op_intake_sources", ["workspace_id", "source_type"])

    op.create_table(
        "op_intake_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("intake_source_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("external_ref", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="received"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("payload_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["intake_source_id"], ["op_intake_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_intake_events_workspace_id", "op_intake_events", ["workspace_id"])
    op.create_index("ix_op_intake_events_intake_source_id", "op_intake_events", ["intake_source_id"])
    op.create_index("ix_op_intake_events_request_id", "op_intake_events", ["request_id"])
    op.create_index("ix_op_intake_events_source_type", "op_intake_events", ["source_type"])
    op.create_index("ix_op_intake_events_external_ref", "op_intake_events", ["external_ref"])
    op.create_index("ix_op_intake_events_status", "op_intake_events", ["status"])

    op.create_table(
        "op_access_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("resource_name", sa.String(), nullable=False),
        sa.Column("access_level", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="fulfilled"),
        sa.Column("grant_ref", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("revokes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_ref"),
    )
    op.create_index("ix_op_access_grants_workspace_id", "op_access_grants", ["workspace_id"])
    op.create_index("ix_op_access_grants_request_id", "op_access_grants", ["request_id"])
    op.create_index("ix_op_access_grants_user_email", "op_access_grants", ["user_email"])
    op.create_index("ix_op_access_grants_status", "op_access_grants", ["status"])

    op.create_table(
        "op_fulfillment_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("assigned_to_id", sa.UUID(), nullable=True),
        sa.Column("task_type", sa.String(), nullable=False, server_default="manual_access_grant"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("result_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["op_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_op_fulfillment_tasks_request_id", "op_fulfillment_tasks", ["request_id"])
    op.create_index("ix_op_fulfillment_tasks_assigned_to_id", "op_fulfillment_tasks", ["assigned_to_id"])
    op.create_index("ix_op_fulfillment_tasks_status", "op_fulfillment_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_op_fulfillment_tasks_status", table_name="op_fulfillment_tasks")
    op.drop_index("ix_op_fulfillment_tasks_assigned_to_id", table_name="op_fulfillment_tasks")
    op.drop_index("ix_op_fulfillment_tasks_request_id", table_name="op_fulfillment_tasks")
    op.drop_table("op_fulfillment_tasks")

    op.drop_index("ix_op_access_grants_status", table_name="op_access_grants")
    op.drop_index("ix_op_access_grants_user_email", table_name="op_access_grants")
    op.drop_index("ix_op_access_grants_request_id", table_name="op_access_grants")
    op.drop_index("ix_op_access_grants_workspace_id", table_name="op_access_grants")
    op.drop_table("op_access_grants")

    op.drop_index("ix_op_intake_events_status", table_name="op_intake_events")
    op.drop_index("ix_op_intake_events_external_ref", table_name="op_intake_events")
    op.drop_index("ix_op_intake_events_source_type", table_name="op_intake_events")
    op.drop_index("ix_op_intake_events_request_id", table_name="op_intake_events")
    op.drop_index("ix_op_intake_events_intake_source_id", table_name="op_intake_events")
    op.drop_index("ix_op_intake_events_workspace_id", table_name="op_intake_events")
    op.drop_table("op_intake_events")

    op.drop_index("ix_op_intake_sources_workspace_type", table_name="op_intake_sources")
    op.drop_index("ix_op_intake_sources_source_type", table_name="op_intake_sources")
    op.drop_index("ix_op_intake_sources_workspace_id", table_name="op_intake_sources")
    op.drop_table("op_intake_sources")

    op.drop_index("ix_op_audit_log_action", table_name="op_audit_log")
    op.drop_index("ix_op_audit_log_event_id", table_name="op_audit_log")
    op.drop_index("ix_op_audit_log_request_id", table_name="op_audit_log")
    op.drop_index("ix_op_audit_log_workspace_id", table_name="op_audit_log")
    op.drop_table("op_audit_log")

    op.drop_index("ix_op_role_assignments_workspace_user_role", table_name="op_role_assignments")
    op.drop_index("ix_op_role_assignments_role_key", table_name="op_role_assignments")
    op.drop_index("ix_op_role_assignments_user_email", table_name="op_role_assignments")
    op.drop_index("ix_op_role_assignments_user_id", table_name="op_role_assignments")
    op.drop_index("ix_op_role_assignments_workspace_id", table_name="op_role_assignments")
    op.drop_table("op_role_assignments")

    op.drop_index("ix_op_request_policy_results_request_id", table_name="op_request_policy_results")
    op.drop_table("op_request_policy_results")

    op.drop_index("ix_op_request_comments_request_id", table_name="op_request_comments")
    op.drop_table("op_request_comments")

    op.drop_index("ix_op_resources_workspace_key", table_name="op_resources")
    op.drop_index("ix_op_resources_resource_type", table_name="op_resources")
    op.drop_index("ix_op_resources_workspace_id", table_name="op_resources")
    op.drop_table("op_resources")

    op.drop_index("ix_op_request_events_event_type", table_name="op_request_events")
    op.drop_index("ix_op_request_events_request_id", table_name="op_request_events")
    op.drop_table("op_request_events")

    op.drop_index("ix_op_approvals_request_status", table_name="op_approvals")
    op.drop_index("ix_op_approvals_status", table_name="op_approvals")
    op.drop_index("ix_op_approvals_approver_email", table_name="op_approvals")
    op.drop_index("ix_op_approvals_approver_user_id", table_name="op_approvals")
    op.drop_index("ix_op_approvals_approver_role_key", table_name="op_approvals")
    op.drop_index("ix_op_approvals_request_id", table_name="op_approvals")
    op.drop_table("op_approvals")

    op.drop_index("ix_op_requests_workspace_status", table_name="op_requests")
    op.drop_index("ix_op_requests_status", table_name="op_requests")
    op.drop_index("ix_op_requests_resource_key", table_name="op_requests")
    op.drop_index("ix_op_requests_requester_email", table_name="op_requests")
    op.drop_index("ix_op_requests_requester_user_id", table_name="op_requests")
    op.drop_index("ix_op_requests_request_type", table_name="op_requests")
    op.drop_index("ix_op_requests_template_id", table_name="op_requests")
    op.drop_index("ix_op_requests_workspace_id", table_name="op_requests")
    op.drop_table("op_requests")
