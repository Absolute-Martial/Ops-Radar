import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.sql import func

from app.database import Base


OP_REQUEST_STATUSES = (
    "draft",
    "submitted",
    "duplicate_review",
    "policy_check_pending",
    "pending_approval",
    "waiting_on_requester",
    "approved",
    "rejected",
    "escalated",
    "fulfillment_pending",
    "fulfilled",
    "completed",
    "failed",
    "cancelled",
)

OP_APPROVAL_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "escalated",
    "expired",
)


class OpRequest(Base):
    __tablename__ = "op_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    template_id = Column(
        UUID(as_uuid=True), ForeignKey("process_templates.id"), nullable=True, index=True
    )
    request_type = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    requester_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    requester_email = Column(String, nullable=False, index=True)
    resource_key = Column(String, nullable=True, index=True)
    resource_name = Column(String, nullable=True)
    access_level = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    urgency = Column(String, nullable=False, default="medium")
    duration_days = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="draft", index=True)
    risk_level = Column(String, nullable=False, default="medium")
    source_type = Column(String, nullable=False, default="catalog")
    source_ref = Column(String, nullable=True)
    temporal_workflow_id = Column(String, nullable=True)
    temporal_run_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_op_requests_workspace_status", "workspace_id", "status"),
    )


class OpApproval(Base):
    __tablename__ = "op_approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approver_role_key = Column(String, nullable=False, index=True)
    approver_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    approver_email = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    decision = Column(String, nullable=True)
    decision_comment = Column(Text, nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_op_approvals_request_status", "request_id", "status"),
    )


class OpRequestEvent(Base):
    __tablename__ = "op_request_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = Column(String, nullable=False, index=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    actor_email = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OpResource(Base):
    __tablename__ = "op_resources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type = Column(String, nullable=False, default="software", index=True)
    resource_key = Column(String, nullable=False)
    resource_name = Column(String, nullable=False)
    default_access_level = Column(String, nullable=True)
    risk_level = Column(String, nullable=False, default="medium")
    active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_op_resources_workspace_key", "workspace_id", "resource_key", unique=True),
    )


class OpRequestComment(Base):
    __tablename__ = "op_request_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    author_email = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OpRequestPolicyResult(Base):
    __tablename__ = "op_request_policy_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    engine = Column(String, nullable=False, default="internal")
    policy_version = Column(String, nullable=False, default="opsradar-v1")
    decision = Column(String, nullable=False)
    risk_level = Column(String, nullable=False, default="medium")
    reasons = Column(JSON, nullable=True)
    raw_result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OpRoleAssignment(Base):
    __tablename__ = "op_role_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    user_email = Column(String, nullable=False, index=True)
    role_key = Column(String, nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_op_role_assignments_workspace_user_role", "workspace_id", "user_id", "role_key", unique=True),
    )


class OpAuditLog(Base):
    __tablename__ = "op_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_id = Column(
        UUID(as_uuid=True), ForeignKey("op_request_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    actor_email = Column(String, nullable=True)
    action = Column(String, nullable=False, index=True)
    resource_type = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    payload_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OpIntakeSource(Base):
    __tablename__ = "op_intake_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    allowed_project_or_channel = Column(String, nullable=True)
    request_type_mapping = Column(JSON, nullable=True)
    field_mapping = Column(JSON, nullable=True)
    confidence_threshold = Column(Float, nullable=False, default=0.75)
    requires_human_confirmation = Column(Boolean, nullable=False, default=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_op_intake_sources_workspace_type", "workspace_id", "source_type"),
    )


class OpIntakeEvent(Base):
    __tablename__ = "op_intake_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    intake_source_id = Column(
        UUID(as_uuid=True), ForeignKey("op_intake_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type = Column(String, nullable=False, index=True)
    external_ref = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="received", index=True)
    confidence = Column(Float, nullable=False, default=1.0)
    payload_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OpAccessGrant(Base):
    __tablename__ = "op_access_grants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_email = Column(String, nullable=False, index=True)
    resource_name = Column(String, nullable=False)
    access_level = Column(String, nullable=True)
    status = Column(String, nullable=False, default="fulfilled", index=True)
    grant_ref = Column(String, nullable=False, unique=True)
    message = Column(Text, nullable=False)
    revokes_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OpFulfillmentTask(Base):
    __tablename__ = "op_fulfillment_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_to_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    task_type = Column(String, nullable=False, default="manual_access_grant")
    status = Column(String, nullable=False, default="pending", index=True)
    simulated = Column(Boolean, nullable=False, default=True)
    result_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OpNotification(Base):
    __tablename__ = "op_notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id = Column(
        UUID(as_uuid=True), ForeignKey("op_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id = Column(
        UUID(as_uuid=True), ForeignKey("op_request_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipient_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    recipient_email = Column(String, nullable=False, index=True)
    channel = Column(String, nullable=False, default="in_app", index=True)
    provider = Column(String, nullable=False, default="local_log")
    event_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="queued", index=True)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    payload_json = Column(JSON, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
