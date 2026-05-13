from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from statistics import median
from uuid import UUID
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_project_access, get_current_active_user
from app.config import settings
from app.database import get_db
from app.models import (
    OP_APPROVAL_STATUSES,
    OP_REQUEST_STATUSES,
    OpApproval,
    OpAccessGrant,
    OpAuditLog,
    OpFulfillmentTask,
    OpIntakeEvent,
    OpIntakeSource,
    OpNotification,
    OpRoleAssignment,
    OpRequest,
    OpRequestComment,
    OpRequestEvent,
    OpRequestPolicyResult,
    OpResource,
    ProcessTemplate,
    Project,
    User,
    UserRole,
)
from app.services.ops_notifications import create_notifications
from app.services.ops_policy import (
    authorize_request_action,
    evaluate_request_policy,
    required_role_keys_for_request,
)
from app.services.ops_temporal import signal_request_workflow, start_request_workflow

router = APIRouter()


def _validate_request_status(value: str) -> str:
    if value not in OP_REQUEST_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request status '{value}'. Must be one of: {', '.join(OP_REQUEST_STATUSES)}",
        )
    return value


def _validate_approval_status(value: str) -> str:
    if value not in OP_APPROVAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid approval status '{value}'. Must be one of: {', '.join(OP_APPROVAL_STATUSES)}",
        )
    return value


def _slugify_request_type(template_name: str | None, fallback: str | None = None) -> str:
    source = (fallback or template_name or "request").strip().lower()
    return "_".join(part for part in source.replace("-", " ").split() if part)


def _risk_for(access_level: str | None, request_type: str) -> str:
    normalized = (access_level or "").strip().lower()
    if normalized in {"admin", "owner", "super_admin"}:
        return "high"
    if "vendor" in request_type:
        return "high"
    if "jira" in request_type:
        return "medium"
    return "medium"


def _temporal_workflow_id_for(request_row: OpRequest) -> str:
    return f"opsradar-access-request-{request_row.id}"


def _seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    if start.tzinfo is None and end.tzinfo is not None:
        start = start.replace(tzinfo=end.tzinfo)
    if end.tzinfo is None and start.tzinfo is not None:
        end = end.replace(tzinfo=start.tzinfo)
    return max((end - start).total_seconds(), 0.0)


async def _visible_workspace_ids(db: AsyncSession, user: User) -> list[UUID]:
    q = select(Project.id)
    if user.role != UserRole.admin:
        conditions = [Project.created_by == user.id]
        if user.team_id is not None:
            conditions.append(Project.team_id == user.team_id)
        q = q.where(or_(*conditions))
    result = await db.execute(q)
    return [row[0] for row in result.all()]


async def _get_request_or_404(request_id: UUID, db: AsyncSession, user: User) -> OpRequest:
    request_row = await db.get(OpRequest, request_id)
    if request_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    await assert_project_access(request_row.workspace_id, db, user)
    return request_row


async def _append_event(
    db: AsyncSession,
    request_row: OpRequest,
    *,
    event_type: str,
    actor: User | None,
    message: str,
    metadata: dict | None = None,
) -> OpRequestEvent:
    event = OpRequestEvent(
        request_id=request_row.id,
        event_type=event_type,
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        message=message,
        metadata_json=metadata,
    )
    db.add(event)
    await db.flush()
    return event


async def _append_audit(
    db: AsyncSession,
    request_row: OpRequest,
    *,
    action: str,
    actor: User | None,
    message: str,
    payload: dict | None = None,
    event: OpRequestEvent | None = None,
    resource_type: str = "op_request",
    resource_id: str | None = None,
) -> None:
    db.add(
        OpAuditLog(
            workspace_id=request_row.workspace_id,
            request_id=request_row.id,
            event_id=event.id if event else None,
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id or str(request_row.id),
            message=message,
            payload_snapshot=payload,
        )
    )


async def _actor_workspace_role_keys(db: AsyncSession, workspace_id: UUID, actor: User) -> list[str]:
    rows = (
        await db.execute(
            select(OpRoleAssignment.role_key).where(
                OpRoleAssignment.workspace_id == workspace_id,
                OpRoleAssignment.user_id == actor.id,
                OpRoleAssignment.active == True,  # noqa: E712
            )
        )
    ).all()
    return [row[0] for row in rows]


async def _request_notification_recipients(
    db: AsyncSession,
    request_row: OpRequest,
    *,
    event_type: str,
    actor: User | None,
    approval: OpApproval | None = None,
) -> list[tuple[User | None, str]]:
    recipients: list[tuple[User | None, str]] = []
    requester_user = await db.get(User, request_row.requester_user_id) if request_row.requester_user_id else None

    if event_type in {"request_submitted", "request_approved", "request_rejected", "more_info_requested", "fulfillment_completed", "request_completed", "request_failed"}:
        recipients.append((requester_user, request_row.requester_email))
    if event_type == "approval_created" and approval is not None and approval.approver_email:
        approver_user = await db.get(User, approval.approver_user_id) if approval.approver_user_id else None
        recipients.append((approver_user, approval.approver_email))
    if event_type == "fulfillment_task_created":
        rows = (
            await db.execute(
                select(OpRoleAssignment, User)
                .join(User, User.id == OpRoleAssignment.user_id)
                .where(
                    OpRoleAssignment.workspace_id == request_row.workspace_id,
                    OpRoleAssignment.active == True,  # noqa: E712
                    OpRoleAssignment.role_key.in_(["it_admin", "super_admin"]),
                    User.is_active == True,  # noqa: E712
                )
            )
        ).all()
        recipients.extend((user, user.email) for _assignment, user in rows)
        if not recipients and actor and actor.role == UserRole.admin:
            recipients.append((actor, actor.email))
    if event_type == "info_provided":
        pending_rows = (
            await db.execute(
                select(OpApproval, User)
                .join(User, User.id == OpApproval.approver_user_id, isouter=True)
                .where(OpApproval.request_id == request_row.id, OpApproval.status == "pending")
            )
        ).all()
        for pending_approval, approver_user in pending_rows:
            if pending_approval.approver_email:
                recipients.append((approver_user, pending_approval.approver_email))

    unique: dict[str, tuple[User | None, str]] = {}
    for user, email in recipients:
        if email:
            unique[email.strip().lower()] = (user, email)
    return list(unique.values())


async def _emit_request_notifications(
    db: AsyncSession,
    request_row: OpRequest,
    *,
    event: OpRequestEvent,
    event_type: str,
    actor: User | None,
    approval: OpApproval | None = None,
    payload: dict | None = None,
) -> None:
    recipients = await _request_notification_recipients(
        db,
        request_row,
        event_type=event_type,
        actor=actor,
        approval=approval,
    )
    if not recipients:
        return
    notifications = await create_notifications(
        db,
        request_row,
        event=event,
        event_type=event_type,
        recipients=recipients,
        payload=payload,
    )
    summary_event = await _append_event(
        db,
        request_row,
        event_type="notification_queued",
        actor=actor,
        message=f"{len(notifications)} notification(s) prepared for {event_type}",
        metadata={
            "source_event_id": str(event.id),
            "source_event_type": event_type,
            "notification_ids": [str(notification.id) for notification in notifications],
            "statuses": [notification.status for notification in notifications],
        },
    )
    await _append_audit(
        db,
        request_row,
        action="notification_queued",
        actor=actor,
        message=f"{len(notifications)} notification(s) prepared for {event_type}",
        payload={
            "source_event_id": str(event.id),
            "source_event_type": event_type,
            "notification_ids": [str(notification.id) for notification in notifications],
        },
        event=summary_event,
        resource_type="op_notification",
    )


async def _resolve_request_approvers(
    db: AsyncSession, request_row: OpRequest
) -> list[tuple[str, User]]:
    required_roles = required_role_keys_for_request(request_row)
    if not required_roles:
        return []

    assignment_rows = (
        await db.execute(
            select(OpRoleAssignment, User)
            .join(User, User.id == OpRoleAssignment.user_id)
            .where(
                and_(
                    OpRoleAssignment.workspace_id == request_row.workspace_id,
                    OpRoleAssignment.active == True,  # noqa: E712
                    OpRoleAssignment.role_key.in_(required_roles),
                    User.is_active == True,  # noqa: E712
                )
            )
            .order_by(OpRoleAssignment.created_at.asc())
        )
    ).all()

    assignments_by_role: dict[str, list[User]] = {}
    for assignment, user in assignment_rows:
        assignments_by_role.setdefault(assignment.role_key, []).append(user)

    resolved: list[tuple[str, User]] = []
    for role_key in required_roles:
        candidates = [
            user
            for user in assignments_by_role.get(role_key, [])
            if user.id != request_row.requester_user_id
        ]
        if candidates:
            resolved.append((role_key, candidates[0]))
            continue

        if role_key == "super_admin":
            admin_rows = (
                await db.execute(
                    select(User)
                    .where(User.role == UserRole.admin, User.is_active == True)  # noqa: E712
                    .order_by(User.created_at.asc())
                )
            ).scalars().all()
            non_requester = [user for user in admin_rows if user.id != request_row.requester_user_id]
            if non_requester:
                resolved.append((role_key, non_requester[0]))

    if not resolved:
        admin_rows = (
            await db.execute(
                select(User)
                .where(User.role == UserRole.admin, User.is_active == True)  # noqa: E712
                .order_by(User.created_at.asc())
            )
        ).scalars().all()
        non_requester = [user for user in admin_rows if user.id != request_row.requester_user_id]
        if non_requester:
            resolved.append(("super_admin", non_requester[0]))

    return resolved


async def _create_initial_approvals(
    db: AsyncSession, request_row: OpRequest, actor: User | None
) -> list[OpApproval]:
    approvers = await _resolve_request_approvers(db, request_row)
    created: list[OpApproval] = []
    for item in approvers:
        if isinstance(item, tuple):
            approver_role_key, approver = item
        else:
            approver_role_key, approver = "approver", item
        approval = OpApproval(
            request_id=request_row.id,
            approver_role_key=approver_role_key,
            approver_user_id=approver.id,
            approver_email=approver.email,
            status="pending",
            due_at=datetime.now(timezone.utc) + timedelta(days=2),
        )
        db.add(approval)
        created.append(approval)
        await db.flush()
        event = await _append_event(
            db,
            request_row,
            event_type="approval_created",
            actor=actor,
            message=f"Approval assigned to {approver.email} as {approver_role_key}",
            metadata={
                "approval_id": str(approval.id),
                "approver_email": approver.email,
                "approver_role_key": approver_role_key,
            },
        )
        await _append_audit(
            db,
            request_row,
            action="approval_created",
            actor=actor,
            message=f"Approval assigned to {approver.email} as {approver_role_key}",
            payload={
                "approval_id": str(approval.id),
                "approver_email": approver.email,
                "approver_role_key": approver_role_key,
            },
            event=event,
            resource_type="op_approval",
            resource_id=str(approval.id),
        )
        await _emit_request_notifications(
            db,
            request_row,
            event=event,
            event_type="approval_created",
            actor=actor,
            approval=approval,
            payload={
                "approval_id": str(approval.id),
                "approver_email": approver.email,
                "approver_role_key": approver_role_key,
            },
        )
    return created


async def _run_submission_lifecycle(
    db: AsyncSession, request_row: OpRequest, actor: User | None
) -> list[OpApproval]:
    request_row.status = "submitted"
    if not request_row.temporal_workflow_id:
        request_row.temporal_workflow_id = _temporal_workflow_id_for(request_row)
    submitted_event = await _append_event(
        db,
        request_row,
        event_type="request_submitted",
        actor=actor,
        message="Request submitted",
        metadata={"risk_level": request_row.risk_level},
    )
    await _append_audit(
        db,
        request_row,
        action="request_submitted",
        actor=actor,
        message="Request submitted",
        payload={"risk_level": request_row.risk_level},
        event=submitted_event,
    )
    await _emit_request_notifications(
        db,
        request_row,
        event=submitted_event,
        event_type="request_submitted",
        actor=actor,
        payload={"risk_level": request_row.risk_level},
    )

    workflow_result = await start_request_workflow(
        request_row,
        workflow_id=request_row.temporal_workflow_id,
        payload={
            "request_id": str(request_row.id),
            "requester_email": request_row.requester_email,
            "resource_name": request_row.resource_name,
            "access_level": request_row.access_level,
            "reason": request_row.reason,
            "approval_timeout_seconds": 172800,
            "requester_info_timeout_seconds": 86400,
        },
    )
    request_row.temporal_workflow_id = workflow_result.workflow_id
    request_row.temporal_run_id = workflow_result.run_id
    workflow_event = await _append_event(
        db,
        request_row,
        event_type="temporal_workflow_started",
        actor=actor,
        message="Durable request workflow tracking started",
        metadata={
            "workflow_id": request_row.temporal_workflow_id,
            "run_id": request_row.temporal_run_id,
            "mode": workflow_result.mode,
        },
    )
    await _append_audit(
        db,
        request_row,
        action="temporal_workflow_started",
        actor=actor,
        message="Durable request workflow tracking started",
        payload={"workflow_id": request_row.temporal_workflow_id, "run_id": request_row.temporal_run_id, "mode": workflow_result.mode},
        event=workflow_event,
    )

    request_row.status = "policy_check_pending"
    actor_roles = await _actor_workspace_role_keys(db, request_row.workspace_id, actor) if actor else []
    policy_result = evaluate_request_policy(request_row, actor=actor, actor_role_keys=actor_roles)
    db.add(
        OpRequestPolicyResult(
            request_id=request_row.id,
            engine=policy_result["engine"],
            policy_version=policy_result["policy_version"],
            decision=policy_result["decision"],
            risk_level=policy_result["risk_level"],
            reasons=policy_result["reasons"],
            raw_result=policy_result,
        )
    )
    request_row.status = "pending_approval"
    policy_event = await _append_event(
        db,
        request_row,
        event_type="policy_evaluated",
        actor=actor,
        message="Internal policy evaluation completed",
        metadata=policy_result,
    )
    await _append_audit(
        db,
        request_row,
        action="policy_evaluated",
        actor=actor,
        message="Internal policy evaluation completed",
        payload=policy_result,
        event=policy_event,
    )

    created = await _create_initial_approvals(db, request_row, actor)
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No approver is available for this request",
        )
    return created


async def _simulate_fulfillment(
    db: AsyncSession, request_row: OpRequest, actor: User | None
) -> OpAccessGrant:
    request_row.status = "fulfillment_pending"
    start_event = await _append_event(
        db,
        request_row,
        event_type="fulfillment_started",
        actor=actor,
        message="Simulated access fulfillment started",
        metadata={"provider": "simulated"},
    )
    await _append_audit(
        db,
        request_row,
        action="fulfillment_started",
        actor=actor,
        message="Simulated access fulfillment started",
        payload={"provider": "simulated"},
        event=start_event,
    )

    resource_name = request_row.resource_name or request_row.resource_key or "requested resource"
    grant_ref = f"sim-grant-{request_row.id}"
    revokes_at = None
    if request_row.duration_days:
        revokes_at = datetime.now(timezone.utc) + timedelta(days=request_row.duration_days)
    grant = OpAccessGrant(
        workspace_id=request_row.workspace_id,
        request_id=request_row.id,
        user_email=request_row.requester_email,
        resource_name=resource_name,
        access_level=request_row.access_level,
        status="fulfilled",
        grant_ref=grant_ref,
        message=(
            f"Simulated {request_row.access_level or 'standard'} access granted to "
            f"{request_row.requester_email} for {resource_name}"
        ),
        revokes_at=revokes_at,
    )
    db.add(grant)
    await db.flush()

    request_row.status = "fulfilled"
    request_row.completed_at = datetime.now(timezone.utc)
    complete_event = await _append_event(
        db,
        request_row,
        event_type="fulfillment_completed",
        actor=actor,
        message=grant.message,
        metadata={"grant_id": str(grant.id), "grant_ref": grant_ref, "provider": "simulated"},
    )
    await _append_audit(
        db,
        request_row,
        action="fulfillment_completed",
        actor=actor,
        message=grant.message,
        payload={"grant_id": str(grant.id), "grant_ref": grant_ref, "provider": "simulated"},
        event=complete_event,
        resource_type="op_access_grant",
        resource_id=str(grant.id),
    )
    await _emit_request_notifications(
        db,
        request_row,
        event=complete_event,
        event_type="fulfillment_completed",
        actor=actor,
        payload={"grant_id": str(grant.id), "grant_ref": grant_ref},
    )
    final_event = await _append_event(
        db,
        request_row,
        event_type="request_completed",
        actor=actor,
        message="Requester notified and request completed",
        metadata={"decision": "completed", "grant_id": str(grant.id)},
    )
    request_row.status = "completed"
    await _append_audit(
        db,
        request_row,
        action="request_completed",
        actor=actor,
        message="Requester notified and request completed",
        payload={"decision": "completed", "grant_id": str(grant.id)},
        event=final_event,
    )
    await _emit_request_notifications(
        db,
        request_row,
        event=final_event,
        event_type="request_completed",
        actor=actor,
        payload={"decision": "completed", "grant_id": str(grant.id)},
    )
    return grant


async def _create_fulfillment_task(
    db: AsyncSession, request_row: OpRequest, actor: User | None
) -> OpFulfillmentTask:
    request_row.status = "approved"
    approved_event = await _append_event(
        db,
        request_row,
        event_type="request_approved",
        actor=actor,
        message="All required approvals completed",
        metadata={"decision": "approved"},
    )
    await _append_audit(
        db,
        request_row,
        action="request_approved",
        actor=actor,
        message="All required approvals completed",
        payload={"decision": "approved"},
        event=approved_event,
    )
    await _emit_request_notifications(
        db,
        request_row,
        event=approved_event,
        event_type="request_approved",
        actor=actor,
        payload={"decision": "approved"},
    )
    request_row.status = "fulfillment_pending"
    task = OpFulfillmentTask(
        request_id=request_row.id,
        assigned_to_id=actor.id if actor and actor.role == UserRole.admin else None,
        task_type="manual_access_grant",
        status="pending",
        simulated=True,
    )
    db.add(task)
    await db.flush()
    task_event = await _append_event(
        db,
        request_row,
        event_type="fulfillment_task_created",
        actor=actor,
        message="Simulated fulfillment task created",
        metadata={"task_id": str(task.id), "task_type": task.task_type},
    )
    await _append_audit(
        db,
        request_row,
        action="fulfillment_task_created",
        actor=actor,
        message="Simulated fulfillment task created",
        payload={"task_id": str(task.id), "task_type": task.task_type},
        event=task_event,
        resource_type="op_fulfillment_task",
        resource_id=str(task.id),
    )
    await _emit_request_notifications(
        db,
        request_row,
        event=task_event,
        event_type="fulfillment_task_created",
        actor=actor,
        payload={"task_id": str(task.id), "task_type": task.task_type},
    )
    return task


class OpRequestCreate(BaseModel):
    workspace_id: UUID
    template_id: UUID | None = None
    request_type: str | None = None
    title: str = Field(..., min_length=1, max_length=200)
    resource_key: str | None = None
    resource_name: str | None = None
    access_level: str | None = None
    reason: str | None = None
    urgency: str = "medium"
    duration_days: int | None = None
    source_type: str = "catalog"
    source_ref: str | None = None


class OpRequestUpdate(BaseModel):
    title: str | None = None
    resource_key: str | None = None
    resource_name: str | None = None
    access_level: str | None = None
    reason: str | None = None
    urgency: str | None = None
    duration_days: int | None = None
    status: str | None = None


class ApprovalDecisionBody(BaseModel):
    comment: str | None = None


class RequestMoreInfoBody(BaseModel):
    reason: str = Field(..., min_length=1)
    requested_fields: list[str] = Field(default_factory=list)


class ProvideInfoBody(BaseModel):
    message: str = Field(..., min_length=1)


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1)


class OpResourceCreate(BaseModel):
    workspace_id: UUID
    resource_type: str = "software"
    resource_key: str = Field(..., min_length=1)
    resource_name: str = Field(..., min_length=1)
    default_access_level: str | None = None
    risk_level: str = "medium"
    metadata_json: dict | None = None


class OpRoleAssignmentCreate(BaseModel):
    workspace_id: UUID
    user_id: UUID
    role_key: str = Field(..., min_length=1, max_length=128)


class IntakeSourceCreate(BaseModel):
    workspace_id: UUID
    name: str = Field(..., min_length=1, max_length=160)
    source_type: str = Field(..., min_length=1, max_length=80)
    enabled: bool = True
    allowed_project_or_channel: str | None = None
    request_type_mapping: dict | None = None
    field_mapping: dict | None = None
    confidence_threshold: float = Field(default=0.75, ge=0, le=1)
    requires_human_confirmation: bool = False
    metadata_json: dict | None = None


class IntakeSourceUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    allowed_project_or_channel: str | None = None
    request_type_mapping: dict | None = None
    field_mapping: dict | None = None
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    requires_human_confirmation: bool | None = None
    metadata_json: dict | None = None


class IntakeEventCreate(BaseModel):
    workspace_id: UUID
    source_type: str = Field(..., min_length=1, max_length=80)
    source_scope: str | None = None
    request_type: str = "access_request"
    requester_email: str
    title: str | None = None
    resource_key: str | None = None
    resource_name: str | None = None
    access_level: str | None = None
    reason: str | None = None
    urgency: str = "medium"
    duration_days: int | None = None
    external_ref: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    payload: dict | None = None


class OpRoleAssignmentResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    user_id: UUID
    user_email: str
    role_key: str
    active: bool
    created_at: datetime
    user_full_name: str | None = None


class IntakeSourceResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    source_type: str
    enabled: bool
    allowed_project_or_channel: str | None = None
    request_type_mapping: dict | None = None
    field_mapping: dict | None = None
    confidence_threshold: float
    requires_human_confirmation: bool
    metadata_json: dict | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class IntakeEventResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    intake_source_id: UUID | None = None
    request_id: UUID | None = None
    source_type: str
    external_ref: str | None = None
    status: str
    confidence: float
    error_message: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class OpRequestResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    template_id: UUID | None = None
    request_type: str
    title: str
    requester_user_id: UUID | None = None
    requester_email: str
    resource_key: str | None = None
    resource_name: str | None = None
    access_level: str | None = None
    reason: str | None = None
    urgency: str
    duration_days: int | None = None
    status: str
    risk_level: str
    source_type: str
    source_ref: str | None = None
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class OpApprovalResponse(BaseModel):
    id: UUID
    request_id: UUID
    approver_role_key: str
    approver_user_id: UUID | None = None
    approver_email: str | None = None
    status: str
    decision: str | None = None
    decision_comment: str | None = None
    due_at: datetime | None = None
    decided_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class OpRequestEventResponse(BaseModel):
    id: UUID
    request_id: UUID
    event_type: str
    actor_user_id: UUID | None = None
    actor_email: str | None = None
    message: str
    metadata_json: dict | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class OpRequestPolicyResultResponse(BaseModel):
    id: UUID
    request_id: UUID
    engine: str
    policy_version: str
    decision: str
    risk_level: str
    reasons: list[str] | dict | None = None
    raw_result: dict | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class OpApprovalInboxItem(BaseModel):
    id: UUID
    request_id: UUID
    approver_role_key: str
    approver_user_id: UUID | None = None
    approver_email: str | None = None
    status: str
    decision: str | None = None
    decision_comment: str | None = None
    due_at: datetime | None = None
    decided_at: datetime | None = None
    created_at: datetime
    request_title: str
    request_type: str
    request_status: str
    requester_email: str
    resource_name: str | None = None
    access_level: str | None = None
    urgency: str
    risk_level: str
    workspace_id: UUID


class OpAccessGrantResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    request_id: UUID
    user_email: str
    resource_name: str
    access_level: str | None = None
    status: str
    grant_ref: str
    message: str
    revokes_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class OpFulfillmentTaskResponse(BaseModel):
    id: UUID
    request_id: UUID
    assigned_to_id: UUID | None = None
    task_type: str
    status: str
    simulated: bool
    result_message: str | None = None
    completed_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class OpNotificationResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    request_id: UUID
    event_id: UUID | None = None
    recipient_user_id: UUID | None = None
    recipient_email: str
    channel: str
    provider: str
    event_type: str
    status: str
    subject: str
    body: str
    payload_json: dict | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class FrictionTemplateMetric(BaseModel):
    request_type: str
    volume: int
    median_approval_wait_hours: float | None = None
    stuck_count: int
    rejection_rate: float
    approver_role_causing_delay: str | None = None
    recommended_fix: str


class FrictionMetricsResponse(BaseModel):
    total_requests: int
    median_time_to_approval_hours: float | None
    median_time_to_fulfillment_hours: float | None
    stuck_requests: int
    overdue_approvals: int
    handoff_count: int
    rejection_rate: float
    estimated_hours_wasted: float
    top_slowest_templates: list[FrictionTemplateMetric]


def _slack_channel_allowed(source: OpIntakeSource, channel_id: str | None) -> bool:
    if not source.allowed_project_or_channel:
        return True
    return bool(channel_id) and source.allowed_project_or_channel == channel_id


async def _slack_open_modal(trigger_id: str, workspace_id: UUID, channel_id: str | None) -> bool:
    if not settings.OPSRADAR_SLACK_BOT_TOKEN:
        return False
    modal = {
        "trigger_id": trigger_id,
        "view": {
            "type": "modal",
            "callback_id": "opsradar_request_modal",
            "title": {"type": "plain_text", "text": "OpsRadar Request"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "private_metadata": json.dumps(
                {
                    "workspace_id": str(workspace_id),
                    "channel_id": channel_id,
                }
            ),
            "blocks": [
                {
                    "type": "input",
                    "block_id": "email_block",
                    "label": {"type": "plain_text", "text": "Requester email"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "email",
                    },
                },
                {
                    "type": "input",
                    "block_id": "resource_block",
                    "label": {"type": "plain_text", "text": "Resource"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "resource",
                    },
                },
                {
                    "type": "input",
                    "optional": True,
                    "block_id": "access_block",
                    "label": {"type": "plain_text", "text": "Access level"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "access",
                        "initial_value": "member",
                    },
                },
                {
                    "type": "input",
                    "optional": True,
                    "block_id": "reason_block",
                    "label": {"type": "plain_text", "text": "Reason"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "reason",
                        "multiline": True,
                    },
                },
            ],
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.OPSRADAR_SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post("https://slack.com/api/views.open", json=modal, headers=headers)
            response.raise_for_status()
            data = response.json()
        return bool(data.get("ok"))
    except Exception:
        return False


def _slack_modal_value(values: dict, block_id: str, action_id: str) -> str | None:
    block = values.get(block_id) or {}
    action = block.get(action_id) or {}
    return action.get("value")


async def _create_request_from_slack_source(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    requester_email: str,
    resource_name: str,
    access_level: str,
    reason: str,
    source: OpIntakeSource,
    source_ref: str | None,
    slack_user_id: str | None,
) -> OpRequest:
    request_row = OpRequest(
        workspace_id=workspace_id,
        request_type="access_request",
        title=f"Slack access request for {resource_name}",
        requester_email=requester_email,
        resource_name=resource_name,
        access_level=access_level,
        reason=reason,
        status="draft",
        risk_level=_risk_for(access_level, "access_request"),
        source_type="slack",
        source_ref=source_ref,
    )
    db.add(request_row)
    await db.flush()
    event = await _append_event(
        db,
        request_row,
        event_type="request_created",
        actor=None,
        message="Request created from Slack structured intake",
        metadata={"source": "slack", "slack_user_id": slack_user_id},
    )
    await _append_audit(
        db,
        request_row,
        action="request_created",
        actor=None,
        message="Request created from Slack structured intake",
        payload={"source": "slack"},
        event=event,
    )
    await _run_submission_lifecycle(db, request_row, None)
    db.add(
        OpIntakeEvent(
            workspace_id=workspace_id,
            intake_source_id=source.id,
            request_id=request_row.id,
            source_type="slack",
            external_ref=source_ref,
            status="processed",
            confidence=1.0,
            payload_json={"resource_name": resource_name, "access_level": access_level, "requester_email": requester_email},
        )
    )
    return request_row


@router.get("/intake-sources", response_model=list[IntakeSourceResponse])
async def list_intake_sources(
    workspace_id: UUID | None = Query(default=None),
    source_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    visible = await _visible_workspace_ids(db, current_user)
    if not visible:
        return []
    stmt = select(OpIntakeSource).where(OpIntakeSource.workspace_id.in_(visible))
    if workspace_id is not None:
        if workspace_id not in visible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        stmt = stmt.where(OpIntakeSource.workspace_id == workspace_id)
    if source_type is not None:
        stmt = stmt.where(OpIntakeSource.source_type == source_type)
    stmt = stmt.order_by(OpIntakeSource.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [IntakeSourceResponse.model_validate(row) for row in rows]


@router.post("/intake-sources", response_model=IntakeSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_intake_source(
    body: IntakeSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can manage intake sources")
    await assert_project_access(body.workspace_id, db, current_user)
    source = OpIntakeSource(
        workspace_id=body.workspace_id,
        name=body.name,
        source_type=body.source_type,
        enabled=body.enabled,
        allowed_project_or_channel=body.allowed_project_or_channel,
        request_type_mapping=body.request_type_mapping,
        field_mapping=body.field_mapping,
        confidence_threshold=body.confidence_threshold,
        requires_human_confirmation=body.requires_human_confirmation,
        created_by=current_user.id,
        metadata_json=body.metadata_json,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return IntakeSourceResponse.model_validate(source)


@router.patch("/intake-sources/{source_id}", response_model=IntakeSourceResponse)
async def update_intake_source(
    source_id: UUID,
    body: IntakeSourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can manage intake sources")
    source = await db.get(OpIntakeSource, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake source not found")
    await assert_project_access(source.workspace_id, db, current_user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return IntakeSourceResponse.model_validate(source)


@router.post("/intake/events", response_model=IntakeEventResponse, status_code=status.HTTP_202_ACCEPTED)
async def receive_intake_event(
    body: IntakeEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await assert_project_access(body.workspace_id, db, current_user)
    source = (
        await db.execute(
            select(OpIntakeSource)
            .where(
                OpIntakeSource.workspace_id == body.workspace_id,
                OpIntakeSource.source_type == body.source_type,
                OpIntakeSource.enabled == True,  # noqa: E712
            )
            .order_by(OpIntakeSource.created_at.asc())
        )
    ).scalars().first()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No enabled intake source is configured for this workspace and source type",
        )
    if source.allowed_project_or_channel and source.allowed_project_or_channel != body.source_scope:
        db.add(
            OpIntakeEvent(
                workspace_id=body.workspace_id,
                intake_source_id=source.id,
                source_type=body.source_type,
                external_ref=body.external_ref,
                status="rejected",
                confidence=body.confidence,
                payload_json=body.model_dump(mode="json"),
                error_message="Source scope is not allowlisted",
            )
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Source scope is not allowlisted")

    if body.confidence < source.confidence_threshold or source.requires_human_confirmation:
        event = OpIntakeEvent(
            workspace_id=body.workspace_id,
            intake_source_id=source.id,
            source_type=body.source_type,
            external_ref=body.external_ref,
            status="review_required",
            confidence=body.confidence,
            payload_json=body.model_dump(mode="json"),
            error_message="Human confirmation required before creating a request",
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return IntakeEventResponse.model_validate(event)

    request_type = _slugify_request_type(None, body.request_type)
    request_row = OpRequest(
        workspace_id=body.workspace_id,
        request_type=request_type,
        title=body.title or f"{request_type.replace('_', ' ').title()} for {body.resource_name or 'resource'}",
        requester_user_id=current_user.id if current_user.email == body.requester_email else None,
        requester_email=body.requester_email,
        resource_key=body.resource_key,
        resource_name=body.resource_name,
        access_level=body.access_level,
        reason=body.reason,
        urgency=body.urgency,
        duration_days=body.duration_days,
        status="draft",
        risk_level=_risk_for(body.access_level, request_type),
        source_type=body.source_type,
        source_ref=body.external_ref,
    )
    db.add(request_row)
    await db.flush()
    created_event = await _append_event(
        db,
        request_row,
        event_type="request_created",
        actor=current_user,
        message=f"Request created from {source.name}",
        metadata={"intake_source_id": str(source.id), "external_ref": body.external_ref},
    )
    await _append_audit(
        db,
        request_row,
        action="request_created",
        actor=current_user,
        message=f"Request created from {source.name}",
        payload={"source_type": body.source_type, "external_ref": body.external_ref},
        event=created_event,
    )
    await _run_submission_lifecycle(db, request_row, current_user)

    intake_event = OpIntakeEvent(
        workspace_id=body.workspace_id,
        intake_source_id=source.id,
        request_id=request_row.id,
        source_type=body.source_type,
        external_ref=body.external_ref,
        status="processed",
        confidence=body.confidence,
        payload_json=body.model_dump(mode="json"),
    )
    db.add(intake_event)
    await db.commit()
    await db.refresh(intake_event)
    return IntakeEventResponse.model_validate(intake_event)


@router.post("/slack/commands")
async def receive_slack_command(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    signing_secret = settings.OPSRADAR_SLACK_SIGNING_SECRET or os.getenv("OPSRADAR_SLACK_SIGNING_SECRET")
    if signing_secret:
        timestamp = request.headers.get("x-slack-request-timestamp", "")
        signature = request.headers.get("x-slack-signature", "")
        base = f"v0:{timestamp}:{body.decode('utf-8', errors='ignore')}".encode()
        expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack signature")

    form = parse_qs(body.decode("utf-8", errors="ignore"))
    text = (form.get("text", [""])[0] or "").strip()
    channel_id = form.get("channel_id", [None])[0]
    trigger_id = form.get("trigger_id", [None])[0]
    values: dict[str, str] = {}
    for token in text.split():
        if "=" in token:
            key, value = token.split("=", 1)
            values[key.strip().lower()] = value.strip()

    workspace_id_raw = values.get("workspace") or settings.OPSRADAR_SLACK_WORKSPACE_ID or os.getenv("OPSRADAR_SLACK_WORKSPACE_ID")
    requester_email = values.get("email")
    resource_name = values.get("resource")
    access_level = values.get("access", "member")
    reason = values.get("reason", "Slack access request")
    if not workspace_id_raw:
        return {"response_type": "ephemeral", "text": "OpsRadar workspace id is required for Slack intake."}

    try:
        workspace_id = UUID(workspace_id_raw)
    except ValueError:
        return {"response_type": "ephemeral", "text": "Invalid OpsRadar workspace id."}

    source = (
        await db.execute(
            select(OpIntakeSource).where(
                OpIntakeSource.workspace_id == workspace_id,
                OpIntakeSource.source_type == "slack",
                OpIntakeSource.enabled == True,  # noqa: E712
            )
        )
    ).scalars().first()
    if source is None:
        return {
            "response_type": "ephemeral",
            "text": "Slack intake is not enabled for that OpsRadar workspace.",
        }
    if not _slack_channel_allowed(source, channel_id):
        return {
            "response_type": "ephemeral",
            "text": "This Slack channel is not allowlisted for the configured OpsRadar intake source.",
        }

    if not requester_email or not resource_name:
        opened = False
        if trigger_id:
            opened = await _slack_open_modal(trigger_id, workspace_id, channel_id)
        if opened:
            return Response(status_code=status.HTTP_200_OK, content="")
        return {
            "response_type": "ephemeral",
            "text": (
                "Use /opsradar request email=user@example.com resource=Figma access=editor "
                "workspace=<workspace_id>, or configure `OPSRADAR_SLACK_BOT_TOKEN` so OpsRadar can open a modal."
            ),
        }
    request_row = await _create_request_from_slack_source(
        db,
        workspace_id=workspace_id,
        requester_email=requester_email,
        resource_name=resource_name,
        access_level=access_level,
        reason=reason,
        source=source,
        source_ref=trigger_id,
        slack_user_id=form.get("user_id", [None])[0],
    )
    await db.commit()
    return {
        "response_type": "ephemeral",
        "text": f"OpsRadar request created and routed: {request_row.title}",
    }


@router.post("/slack/interactions")
async def receive_slack_interactions(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    signing_secret = settings.OPSRADAR_SLACK_SIGNING_SECRET or os.getenv("OPSRADAR_SLACK_SIGNING_SECRET")
    if signing_secret:
        timestamp = request.headers.get("x-slack-request-timestamp", "")
        signature = request.headers.get("x-slack-signature", "")
        base = f"v0:{timestamp}:{body.decode('utf-8', errors='ignore')}".encode()
        expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack signature")

    form = parse_qs(body.decode("utf-8", errors="ignore"))
    payload_raw = (form.get("payload", ["{}"])[0] or "{}").strip()
    payload = json.loads(payload_raw)
    interaction_type = payload.get("type")

    if interaction_type == "view_submission":
        view = payload.get("view") or {}
        private_metadata = json.loads(view.get("private_metadata") or "{}")
        workspace_id_raw = private_metadata.get("workspace_id")
        channel_id = private_metadata.get("channel_id")
        if not workspace_id_raw:
            return {"response_action": "errors", "errors": {"email_block": "Missing workspace binding"}}
        workspace_id = UUID(workspace_id_raw)
        source = (
            await db.execute(
                select(OpIntakeSource).where(
                    OpIntakeSource.workspace_id == workspace_id,
                    OpIntakeSource.source_type == "slack",
                    OpIntakeSource.enabled == True,  # noqa: E712
                )
            )
        ).scalars().first()
        if source is None:
            return {"response_action": "errors", "errors": {"email_block": "Slack intake is not enabled for this workspace"}}
        if not _slack_channel_allowed(source, channel_id):
            return {"response_action": "errors", "errors": {"email_block": "This Slack channel is not allowlisted"}}

        values = ((view.get("state") or {}).get("values") or {})
        requester_email = _slack_modal_value(values, "email_block", "email")
        resource_name = _slack_modal_value(values, "resource_block", "resource")
        access_level = _slack_modal_value(values, "access_block", "access") or "member"
        reason = _slack_modal_value(values, "reason_block", "reason") or "Slack modal access request"
        if not requester_email or not resource_name:
            return {"response_action": "errors", "errors": {"email_block": "Requester email and resource are required"}}

        await _create_request_from_slack_source(
            db,
            workspace_id=workspace_id,
            requester_email=requester_email,
            resource_name=resource_name,
            access_level=access_level,
            reason=reason,
            source=source,
            source_ref=payload.get("trigger_id"),
            slack_user_id=((payload.get("user") or {}).get("id")),
        )
        await db.commit()
        return Response(status_code=status.HTTP_200_OK, content="")

    if interaction_type == "block_actions":
        return {
            "response_type": "ephemeral",
            "text": "Slack buttons are reserved for structured OpsRadar actions. Approval buttons can be added on top of this interaction endpoint later.",
        }

    return {"response_type": "ephemeral", "text": "Unsupported Slack interaction type for OpsRadar."}


@router.get("/op-role-assignments", response_model=list[OpRoleAssignmentResponse])
async def list_op_role_assignments(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await assert_project_access(workspace_id, db, current_user)
    rows = (
        await db.execute(
            select(OpRoleAssignment, User)
            .join(User, User.id == OpRoleAssignment.user_id)
            .where(OpRoleAssignment.workspace_id == workspace_id)
            .order_by(OpRoleAssignment.created_at.asc())
        )
    ).all()
    return [
        OpRoleAssignmentResponse(
            id=assignment.id,
            workspace_id=assignment.workspace_id,
            user_id=assignment.user_id,
            user_email=assignment.user_email,
            role_key=assignment.role_key,
            active=assignment.active,
            created_at=assignment.created_at,
            user_full_name=user.full_name,
        )
        for assignment, user in rows
    ]


@router.post("/op-role-assignments", response_model=OpRoleAssignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_op_role_assignment(
    body: OpRoleAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can manage role assignments")
    await assert_project_access(body.workspace_id, db, current_user)
    user = await db.get(User, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = (
        await db.execute(
            select(OpRoleAssignment).where(
                OpRoleAssignment.workspace_id == body.workspace_id,
                OpRoleAssignment.user_id == body.user_id,
                OpRoleAssignment.role_key == body.role_key,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.active = True
        await db.commit()
        await db.refresh(existing)
        return OpRoleAssignmentResponse(
            id=existing.id,
            workspace_id=existing.workspace_id,
            user_id=existing.user_id,
            user_email=existing.user_email,
            role_key=existing.role_key,
            active=existing.active,
            created_at=existing.created_at,
            user_full_name=user.full_name,
        )

    assignment = OpRoleAssignment(
        workspace_id=body.workspace_id,
        user_id=body.user_id,
        user_email=user.email,
        role_key=body.role_key,
        active=True,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return OpRoleAssignmentResponse(
        id=assignment.id,
        workspace_id=assignment.workspace_id,
        user_id=assignment.user_id,
        user_email=assignment.user_email,
        role_key=assignment.role_key,
        active=assignment.active,
        created_at=assignment.created_at,
        user_full_name=user.full_name,
    )


@router.delete("/op-role-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_op_role_assignment(
    assignment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can manage role assignments")
    assignment = await db.get(OpRoleAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role assignment not found")
    await assert_project_access(assignment.workspace_id, db, current_user)
    await db.delete(assignment)
    await db.commit()


@router.get("/op-requests", response_model=list[OpRequestResponse])
async def list_op_requests(
    workspace_id: UUID | None = Query(default=None),
    request_status: str | None = Query(default=None, alias="status"),
    requester_email: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    visible = await _visible_workspace_ids(db, current_user)
    if not visible:
        return []
    q = select(OpRequest).where(OpRequest.workspace_id.in_(visible))
    if workspace_id is not None:
        if workspace_id not in visible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        q = q.where(OpRequest.workspace_id == workspace_id)
    if request_status is not None:
        _validate_request_status(request_status)
        q = q.where(OpRequest.status == request_status)
    if requester_email:
        q = q.where(OpRequest.requester_email == requester_email)
    q = q.order_by(OpRequest.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return [OpRequestResponse.model_validate(row) for row in rows]


@router.get("/op-requests/search", response_model=list[OpRequestResponse])
async def search_op_requests(
    q: str = Query(..., min_length=1),
    workspace_id: UUID | None = Query(default=None),
    include_closed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    visible = await _visible_workspace_ids(db, current_user)
    if not visible:
        return []
    stmt = select(OpRequest).where(OpRequest.workspace_id.in_(visible))
    if workspace_id is not None:
        if workspace_id not in visible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        stmt = stmt.where(OpRequest.workspace_id == workspace_id)
    needle = f"%{q.strip()}%"
    stmt = stmt.where(
        or_(
            OpRequest.title.ilike(needle),
            OpRequest.resource_name.ilike(needle),
            OpRequest.resource_key.ilike(needle),
            OpRequest.request_type.ilike(needle),
        )
    )
    if not include_closed:
        stmt = stmt.where(
            OpRequest.status.not_in(["rejected", "completed", "cancelled", "failed"])
        )
    rows = (await db.execute(stmt.order_by(OpRequest.created_at.desc()).limit(10))).scalars().all()
    return [OpRequestResponse.model_validate(row) for row in rows]


@router.post("/op-requests", response_model=OpRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_op_request(
    body: OpRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await assert_project_access(body.workspace_id, db, current_user)

    template = None
    if body.template_id is not None:
        template = await db.get(ProcessTemplate, body.template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    request_type = _slugify_request_type(template.name if template else None, body.request_type)
    request_row = OpRequest(
        workspace_id=body.workspace_id,
        template_id=body.template_id,
        request_type=request_type,
        title=body.title,
        requester_user_id=current_user.id,
        requester_email=current_user.email,
        resource_key=body.resource_key,
        resource_name=body.resource_name,
        access_level=body.access_level,
        reason=body.reason,
        urgency=body.urgency,
        duration_days=body.duration_days,
        status="draft",
        risk_level=_risk_for(body.access_level, request_type),
        source_type=body.source_type,
        source_ref=body.source_ref,
    )
    db.add(request_row)
    await db.flush()
    event = await _append_event(
        db,
        request_row,
        event_type="request_created",
        actor=current_user,
        message="Request draft created",
        metadata={"template_id": str(body.template_id) if body.template_id else None},
    )
    await _append_audit(
        db,
        request_row,
        action="request_created",
        actor=current_user,
        message="Request draft created",
        payload={"request_type": request_type},
        event=event,
    )
    await db.commit()
    await db.refresh(request_row)
    return OpRequestResponse.model_validate(request_row)


@router.get("/op-requests/{request_id}", response_model=OpRequestResponse)
async def get_op_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    return OpRequestResponse.model_validate(request_row)


@router.patch("/op-requests/{request_id}", response_model=OpRequestResponse)
async def update_op_request(
    request_id: UUID,
    body: OpRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    if request_row.status != "draft" and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only draft requests can be edited")

    if body.title is not None:
        request_row.title = body.title
    if body.resource_key is not None:
        request_row.resource_key = body.resource_key
    if body.resource_name is not None:
        request_row.resource_name = body.resource_name
    if body.access_level is not None:
        request_row.access_level = body.access_level
        request_row.risk_level = _risk_for(body.access_level, request_row.request_type)
    if body.reason is not None:
        request_row.reason = body.reason
    if body.urgency is not None:
        request_row.urgency = body.urgency
    if body.duration_days is not None:
        request_row.duration_days = body.duration_days
    if body.status is not None:
        request_row.status = _validate_request_status(body.status)
    event = await _append_event(
        db,
        request_row,
        event_type="request_updated",
        actor=current_user,
        message="Request updated",
        metadata=body.model_dump(exclude_none=True),
    )
    await _append_audit(
        db,
        request_row,
        action="request_updated",
        actor=current_user,
        message="Request updated",
        payload=body.model_dump(exclude_none=True),
        event=event,
    )
    await db.commit()
    await db.refresh(request_row)
    return OpRequestResponse.model_validate(request_row)


@router.post("/op-requests/{request_id}/submit", response_model=OpRequestResponse)
async def submit_op_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    if request_row.status != "draft":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only draft requests can be submitted")

    await _run_submission_lifecycle(db, request_row, current_user)
    await db.commit()
    await db.refresh(request_row)
    return OpRequestResponse.model_validate(request_row)


@router.get("/op-requests/{request_id}/events", response_model=list[OpRequestEventResponse])
async def list_op_request_events(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    result = await db.execute(
        select(OpRequestEvent)
        .where(OpRequestEvent.request_id == request_row.id)
        .order_by(OpRequestEvent.created_at.asc())
    )
    rows = result.scalars().all()
    return [OpRequestEventResponse.model_validate(row) for row in rows]


@router.get("/op-requests/{request_id}/policy-results", response_model=list[OpRequestPolicyResultResponse])
async def list_op_request_policy_results(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    result = await db.execute(
        select(OpRequestPolicyResult)
        .where(OpRequestPolicyResult.request_id == request_row.id)
        .order_by(OpRequestPolicyResult.created_at.desc())
    )
    rows = result.scalars().all()
    return [OpRequestPolicyResultResponse.model_validate(row) for row in rows]


@router.get("/op-requests/{request_id}/comments")
async def list_op_request_comments(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    result = await db.execute(
        select(OpRequestComment)
        .where(OpRequestComment.request_id == request_row.id)
        .order_by(OpRequestComment.created_at.asc())
    )
    rows = result.scalars().all()
    return [
        {
            "id": str(row.id),
            "request_id": str(row.request_id),
            "author_user_id": str(row.author_user_id) if row.author_user_id else None,
            "author_email": row.author_email,
            "body": row.body,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.post("/op-requests/{request_id}/comments", status_code=status.HTTP_201_CREATED)
async def create_op_request_comment(
    request_id: UUID,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    comment = OpRequestComment(
        request_id=request_row.id,
        author_user_id=current_user.id,
        author_email=current_user.email,
        body=body.body,
    )
    db.add(comment)
    await db.flush()
    event = await _append_event(
        db,
        request_row,
        event_type="comment_added",
        actor=current_user,
        message="Comment added",
        metadata={"comment_id": str(comment.id)},
    )
    await _append_audit(
        db,
        request_row,
        action="comment_added",
        actor=current_user,
        message="Comment added",
        payload={"comment_id": str(comment.id)},
        event=event,
        resource_type="op_request_comment",
        resource_id=str(comment.id),
    )
    await db.commit()
    return {
        "id": str(comment.id),
        "request_id": str(comment.request_id),
        "author_user_id": str(comment.author_user_id) if comment.author_user_id else None,
        "author_email": comment.author_email,
        "body": comment.body,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


@router.get("/op-requests/{request_id}/access-grants", response_model=list[OpAccessGrantResponse])
async def list_op_request_access_grants(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    result = await db.execute(
        select(OpAccessGrant)
        .where(OpAccessGrant.request_id == request_row.id)
        .order_by(OpAccessGrant.created_at.desc())
    )
    rows = result.scalars().all()
    return [OpAccessGrantResponse.model_validate(row) for row in rows]


@router.get("/op-requests/{request_id}/fulfillment-tasks", response_model=list[OpFulfillmentTaskResponse])
async def list_op_request_fulfillment_tasks(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    result = await db.execute(
        select(OpFulfillmentTask)
        .where(OpFulfillmentTask.request_id == request_row.id)
        .order_by(OpFulfillmentTask.created_at.asc())
    )
    rows = result.scalars().all()
    return [OpFulfillmentTaskResponse.model_validate(row) for row in rows]


@router.get("/op-requests/{request_id}/notifications", response_model=list[OpNotificationResponse])
async def list_op_request_notifications(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    result = await db.execute(
        select(OpNotification)
        .where(OpNotification.request_id == request_row.id)
        .order_by(OpNotification.created_at.asc())
    )
    rows = result.scalars().all()
    return [OpNotificationResponse.model_validate(row) for row in rows]


@router.get("/op-requests/{request_id}/approvals", response_model=list[OpApprovalResponse])
async def list_op_request_approvals(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    result = await db.execute(
        select(OpApproval)
        .where(OpApproval.request_id == request_row.id)
        .order_by(OpApproval.created_at.asc())
    )
    rows = result.scalars().all()
    return [OpApprovalResponse.model_validate(row) for row in rows]


@router.get("/op-approvals/inbox", response_model=list[OpApprovalInboxItem])
async def op_approval_inbox(
    approval_status: str | None = Query(default="pending", alias="status"),
    workspace_id: UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    visible = await _visible_workspace_ids(db, current_user)
    if not visible:
        return []
    if workspace_id is not None and workspace_id not in visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if approval_status is not None:
        _validate_approval_status(approval_status)

    stmt = (
        select(OpApproval, OpRequest)
        .join(OpRequest, OpApproval.request_id == OpRequest.id)
        .where(OpRequest.workspace_id.in_(visible))
    )
    if current_user.role != UserRole.admin:
        stmt = stmt.where(
            or_(
                OpApproval.approver_user_id == current_user.id,
                OpApproval.approver_email == current_user.email,
            )
        )
    if approval_status is not None:
        stmt = stmt.where(OpApproval.status == approval_status)
    if workspace_id is not None:
        stmt = stmt.where(OpRequest.workspace_id == workspace_id)
    stmt = stmt.order_by(OpApproval.created_at.desc()).limit(limit).offset(offset)

    rows = (await db.execute(stmt)).all()
    return [
        OpApprovalInboxItem(
            id=approval.id,
            request_id=approval.request_id,
            approver_role_key=approval.approver_role_key,
            approver_user_id=approval.approver_user_id,
            approver_email=approval.approver_email,
            status=approval.status,
            decision=approval.decision,
            decision_comment=approval.decision_comment,
            due_at=approval.due_at,
            decided_at=approval.decided_at,
            created_at=approval.created_at,
            request_title=request_row.title,
            request_type=request_row.request_type,
            request_status=request_row.status,
            requester_email=request_row.requester_email,
            resource_name=request_row.resource_name,
            access_level=request_row.access_level,
            urgency=request_row.urgency,
            risk_level=request_row.risk_level,
            workspace_id=request_row.workspace_id,
        )
        for approval, request_row in rows
    ]


async def _decide_approval(
    approval_id: UUID,
    *,
    decision: str,
    body: ApprovalDecisionBody,
    db: AsyncSession,
    current_user: User,
) -> OpApproval:
    approval = await db.get(OpApproval, approval_id)
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    request_row = await _get_request_or_404(approval.request_id, db, current_user)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Approval is no longer pending")
    actor_roles = await _actor_workspace_role_keys(db, request_row.workspace_id, current_user)
    authorization = authorize_request_action(
        request_row,
        actor=current_user,
        actor_role_keys=actor_roles,
        action="approve",
    )
    if not authorization["allowed"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=authorization["reason"])
    if current_user.role != UserRole.admin and approval.approver_user_id not in (None, current_user.id) and approval.approver_email != current_user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not assigned to this approval")

    approval.status = "approved" if decision == "approve" else "rejected"
    approval.decision = decision
    approval.decision_comment = body.comment
    approval.decided_at = datetime.now(timezone.utc)

    event_type = "approval_approved" if decision == "approve" else "approval_rejected"
    msg = "Approval approved" if decision == "approve" else "Approval rejected"
    event = await _append_event(
        db,
        request_row,
        event_type=event_type,
        actor=current_user,
        message=msg,
        metadata={"approval_id": str(approval.id), "comment": body.comment},
    )
    await _append_audit(
        db,
        request_row,
        action=event_type,
        actor=current_user,
        message=msg,
        payload={"approval_id": str(approval.id), "comment": body.comment},
        event=event,
        resource_type="op_approval",
        resource_id=str(approval.id),
    )
    await _emit_request_notifications(
        db,
        request_row,
        event=event,
        event_type=event_type,
        actor=current_user,
        approval=approval,
        payload={"approval_id": str(approval.id), "comment": body.comment},
    )
    temporal_mode = await signal_request_workflow(
        request_row,
        signal_name=f"{decision}_request",
        payload={
            "approval_id": str(approval.id),
            "actor_email": current_user.email,
            "comment": body.comment,
        },
    )
    signal_event = await _append_event(
        db,
        request_row,
        event_type="temporal_signal_received",
        actor=current_user,
        message=f"Workflow signal received: {decision}_request",
        metadata={
            "workflow_id": request_row.temporal_workflow_id,
            "run_id": request_row.temporal_run_id,
            "mode": temporal_mode,
            "signal": f"{decision}_request",
            "approval_id": str(approval.id),
        },
    )
    await _append_audit(
        db,
        request_row,
        action="temporal_signal_received",
        actor=current_user,
        message=f"Workflow signal received: {decision}_request",
        payload={
            "workflow_id": request_row.temporal_workflow_id,
            "run_id": request_row.temporal_run_id,
            "mode": temporal_mode,
            "signal": f"{decision}_request",
            "approval_id": str(approval.id),
        },
        event=signal_event,
    )

    sibling_rows = (
        await db.execute(select(OpApproval).where(OpApproval.request_id == request_row.id))
    ).scalars().all()
    if any(row.status == "rejected" for row in sibling_rows):
        request_row.status = "rejected"
        request_row.completed_at = datetime.now(timezone.utc)
        final_event = await _append_event(
            db,
            request_row,
            event_type="request_failed",
            actor=current_user,
            message="Request rejected",
            metadata={"decision": "rejected"},
        )
        await _append_audit(
            db,
            request_row,
            action="request_rejected",
            actor=current_user,
            message="Request rejected",
            payload={"decision": "rejected"},
            event=final_event,
        )
        await _emit_request_notifications(
            db,
            request_row,
            event=final_event,
            event_type="request_rejected",
            actor=current_user,
            payload={"decision": "rejected"},
        )
    elif all(row.status == "approved" for row in sibling_rows):
        await _create_fulfillment_task(db, request_row, current_user)

    await db.commit()
    await db.refresh(approval)
    return approval


@router.post("/op-approvals/{approval_id}/approve", response_model=OpApprovalResponse)
async def approve_op_approval(
    approval_id: UUID,
    body: ApprovalDecisionBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    approval = await _decide_approval(
        approval_id, decision="approve", body=body, db=db, current_user=current_user
    )
    return OpApprovalResponse.model_validate(approval)


@router.post("/op-approvals/{approval_id}/reject", response_model=OpApprovalResponse)
async def reject_op_approval(
    approval_id: UUID,
    body: ApprovalDecisionBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    approval = await _decide_approval(
        approval_id, decision="reject", body=body, db=db, current_user=current_user
    )
    return OpApprovalResponse.model_validate(approval)


@router.post("/op-requests/{request_id}/request-more-info", response_model=OpRequestResponse)
async def request_more_info(
    request_id: UUID,
    body: RequestMoreInfoBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    if request_row.status not in {"pending_approval", "fulfillment_pending"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not waiting on approver or fulfillment")
    actor_roles = await _actor_workspace_role_keys(db, request_row.workspace_id, current_user)
    authorization = authorize_request_action(
        request_row,
        actor=current_user,
        actor_role_keys=actor_roles,
        action="request_more_info",
    )
    if not authorization["allowed"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=authorization["reason"])
    previous_status = request_row.status
    request_row.status = "waiting_on_requester"
    event = await _append_event(
        db,
        request_row,
        event_type="more_info_requested",
        actor=current_user,
        message=body.reason,
        metadata={
            "requested_fields": body.requested_fields,
            "previous_status": previous_status,
        },
    )
    await _append_audit(
        db,
        request_row,
        action="more_info_requested",
        actor=current_user,
        message=body.reason,
        payload={"requested_fields": body.requested_fields, "previous_status": previous_status},
        event=event,
    )
    await signal_request_workflow(
        request_row,
        signal_name="request_more_info",
        payload={
            "actor_email": current_user.email,
            "reason": body.reason,
            "requested_fields": body.requested_fields,
            "previous_status": previous_status,
        },
    )
    await _emit_request_notifications(
        db,
        request_row,
        event=event,
        event_type="more_info_requested",
        actor=current_user,
        payload={"requested_fields": body.requested_fields, "previous_status": previous_status},
    )
    await db.commit()
    await db.refresh(request_row)
    return OpRequestResponse.model_validate(request_row)


@router.post("/op-requests/{request_id}/provide-info", response_model=OpRequestResponse)
async def provide_info(
    request_id: UUID,
    body: ProvideInfoBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    if request_row.status != "waiting_on_requester":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not waiting on requester")
    actor_roles = await _actor_workspace_role_keys(db, request_row.workspace_id, current_user)
    authorization = authorize_request_action(
        request_row,
        actor=current_user,
        actor_role_keys=actor_roles,
        action="provide_info",
    )
    if not authorization["allowed"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=authorization["reason"])
    result = await db.execute(
        select(OpRequestEvent)
        .where(
            OpRequestEvent.request_id == request_row.id,
            OpRequestEvent.event_type == "more_info_requested",
        )
        .order_by(OpRequestEvent.created_at.desc())
    )
    latest = result.scalars().first()
    next_status = "pending_approval"
    if latest and latest.metadata_json and latest.metadata_json.get("previous_status") in OP_REQUEST_STATUSES:
        next_status = latest.metadata_json["previous_status"]
    request_row.status = next_status
    event = await _append_event(
        db,
        request_row,
        event_type="info_provided",
        actor=current_user,
        message=body.message,
        metadata={"restored_status": next_status},
    )
    await _append_audit(
        db,
        request_row,
        action="info_provided",
        actor=current_user,
        message=body.message,
        payload={"restored_status": next_status},
        event=event,
    )
    await signal_request_workflow(
        request_row,
        signal_name="provide_info",
        payload={
            "actor_email": current_user.email,
            "message": body.message,
            "restored_status": next_status,
        },
    )
    await _emit_request_notifications(
        db,
        request_row,
        event=event,
        event_type="info_provided",
        actor=current_user,
        payload={"restored_status": next_status},
    )
    await db.commit()
    await db.refresh(request_row)
    return OpRequestResponse.model_validate(request_row)


@router.post("/op-requests/{request_id}/fulfillment/mark-complete", response_model=OpRequestResponse)
async def mark_request_fulfilled(
    request_id: UUID,
    body: ApprovalDecisionBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request_row = await _get_request_or_404(request_id, db, current_user)
    if request_row.status != "fulfillment_pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request is not ready for fulfillment")
    actor_roles = await _actor_workspace_role_keys(db, request_row.workspace_id, current_user)
    authorization = authorize_request_action(
        request_row,
        actor=current_user,
        actor_role_keys=actor_roles,
        action="fulfill",
    )
    if not authorization["allowed"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=authorization["reason"])
    task = (
        await db.execute(
            select(OpFulfillmentTask)
            .where(
                OpFulfillmentTask.request_id == request_row.id,
                OpFulfillmentTask.status == "pending",
            )
            .order_by(OpFulfillmentTask.created_at.asc())
        )
    ).scalars().first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No pending fulfillment task found")
    task.status = "completed"
    task.result_message = body.comment or "Marked fulfilled manually"
    task.completed_at = datetime.now(timezone.utc)
    await signal_request_workflow(
        request_row,
        signal_name="mark_fulfilled",
        payload={"actor_email": current_user.email, "comment": body.comment},
    )
    await _simulate_fulfillment(db, request_row, current_user)
    await db.commit()
    await db.refresh(request_row)
    return OpRequestResponse.model_validate(request_row)


@router.get("/op-metrics/friction", response_model=FrictionMetricsResponse)
async def get_op_friction_metrics(
    workspace_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    visible = await _visible_workspace_ids(db, current_user)
    if not visible:
        return FrictionMetricsResponse(
            total_requests=0,
            median_time_to_approval_hours=None,
            median_time_to_fulfillment_hours=None,
            stuck_requests=0,
            overdue_approvals=0,
            handoff_count=0,
            rejection_rate=0,
            estimated_hours_wasted=0,
            top_slowest_templates=[],
        )
    if workspace_id is not None:
        if workspace_id not in visible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        visible = [workspace_id]

    requests = (
        await db.execute(select(OpRequest).where(OpRequest.workspace_id.in_(visible)))
    ).scalars().all()
    request_ids = [row.id for row in requests]
    if not request_ids:
        return FrictionMetricsResponse(
            total_requests=0,
            median_time_to_approval_hours=None,
            median_time_to_fulfillment_hours=None,
            stuck_requests=0,
            overdue_approvals=0,
            handoff_count=0,
            rejection_rate=0,
            estimated_hours_wasted=0,
            top_slowest_templates=[],
        )

    approvals = (
        await db.execute(select(OpApproval).where(OpApproval.request_id.in_(request_ids)))
    ).scalars().all()
    now = datetime.now(timezone.utc)
    approval_wait_hours = [
        seconds / 3600
        for approval in approvals
        if approval.decided_at is not None
        for seconds in [_seconds_between(approval.created_at, approval.decided_at)]
        if seconds is not None
    ]
    fulfillment_hours = [
        seconds / 3600
        for request_row in requests
        if request_row.status == "fulfilled"
        for seconds in [_seconds_between(request_row.created_at, request_row.completed_at)]
        if seconds is not None
    ]
    stuck_statuses = {"submitted", "policy_check_pending", "pending_approval", "fulfillment_pending"}
    stuck_requests = sum(1 for request_row in requests if request_row.status in stuck_statuses)
    overdue_approvals = sum(
        1
        for approval in approvals
        if approval.status == "pending"
        and approval.due_at is not None
        and _seconds_between(approval.due_at, now) is not None
        and _seconds_between(approval.due_at, now) > 0
    )
    rejected_count = sum(1 for request_row in requests if request_row.status == "rejected")
    estimated_hours_wasted = 0.0
    for request_row in requests:
        if request_row.status in stuck_statuses:
            seconds = _seconds_between(request_row.updated_at or request_row.created_at, now)
            estimated_hours_wasted += (seconds or 0) / 3600

    by_type: dict[str, list[OpRequest]] = {}
    for request_row in requests:
        by_type.setdefault(request_row.request_type, []).append(request_row)

    template_metrics: list[FrictionTemplateMetric] = []
    for request_type, type_requests in by_type.items():
        type_ids = {row.id for row in type_requests}
        type_approvals = [approval for approval in approvals if approval.request_id in type_ids]
        waits = [
            seconds / 3600
            for approval in type_approvals
            if approval.decided_at is not None
            for seconds in [_seconds_between(approval.created_at, approval.decided_at)]
            if seconds is not None
        ]
        pending_by_role: dict[str, int] = {}
        for approval in type_approvals:
            if approval.status == "pending":
                pending_by_role[approval.approver_role_key] = pending_by_role.get(approval.approver_role_key, 0) + 1
        slow_role = max(pending_by_role, key=pending_by_role.get) if pending_by_role else None
        type_rejected = sum(1 for request_row in type_requests if request_row.status == "rejected")
        type_stuck = sum(1 for request_row in type_requests if request_row.status in stuck_statuses)
        template_metrics.append(
            FrictionTemplateMetric(
                request_type=request_type,
                volume=len(type_requests),
                median_approval_wait_hours=round(median(waits), 2) if waits else None,
                stuck_count=type_stuck,
                rejection_rate=round(type_rejected / len(type_requests), 4) if type_requests else 0,
                approver_role_causing_delay=slow_role,
                recommended_fix=(
                    f"Review {slow_role} capacity and routing rules."
                    if slow_role
                    else "Keep routing monitored and compare against future request volume."
                ),
            )
        )
    template_metrics.sort(
        key=lambda item: (
            item.median_approval_wait_hours if item.median_approval_wait_hours is not None else -1,
            item.stuck_count,
        ),
        reverse=True,
    )

    return FrictionMetricsResponse(
        total_requests=len(requests),
        median_time_to_approval_hours=round(median(approval_wait_hours), 2) if approval_wait_hours else None,
        median_time_to_fulfillment_hours=round(median(fulfillment_hours), 2) if fulfillment_hours else None,
        stuck_requests=stuck_requests,
        overdue_approvals=overdue_approvals,
        handoff_count=len(approvals),
        rejection_rate=round(rejected_count / len(requests), 4) if requests else 0,
        estimated_hours_wasted=round(estimated_hours_wasted, 2),
        top_slowest_templates=template_metrics[:5],
    )


@router.get("/op-audit")
async def list_op_audit(
    workspace_id: UUID | None = Query(default=None),
    request_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    visible = await _visible_workspace_ids(db, current_user)
    if not visible:
        return []
    stmt = select(OpAuditLog).where(OpAuditLog.workspace_id.in_(visible))
    if workspace_id is not None:
        if workspace_id not in visible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        stmt = stmt.where(OpAuditLog.workspace_id == workspace_id)
    if request_id is not None:
        stmt = stmt.where(OpAuditLog.request_id == request_id)
    if action is not None:
        stmt = stmt.where(OpAuditLog.action == action)
    stmt = stmt.order_by(OpAuditLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(row.id),
            "workspace_id": str(row.workspace_id),
            "request_id": str(row.request_id) if row.request_id else None,
            "event_id": str(row.event_id) if row.event_id else None,
            "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
            "actor_email": row.actor_email,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "message": row.message,
            "payload_snapshot": row.payload_snapshot,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.get("/op-resources")
async def list_op_resources(
    workspace_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    visible = await _visible_workspace_ids(db, current_user)
    if not visible:
        return []
    stmt = select(OpResource).where(OpResource.workspace_id.in_(visible)).order_by(OpResource.resource_name.asc())
    if workspace_id is not None:
        if workspace_id not in visible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        stmt = stmt.where(OpResource.workspace_id == workspace_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(row.id),
            "workspace_id": str(row.workspace_id),
            "resource_type": row.resource_type,
            "resource_key": row.resource_key,
            "resource_name": row.resource_name,
            "default_access_level": row.default_access_level,
            "risk_level": row.risk_level,
            "active": row.active,
            "metadata_json": row.metadata_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@router.get("/op-access-grants", response_model=list[OpAccessGrantResponse])
async def list_op_access_grants(
    workspace_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    visible = await _visible_workspace_ids(db, current_user)
    if not visible:
        return []
    stmt = select(OpAccessGrant).where(OpAccessGrant.workspace_id.in_(visible))
    if workspace_id is not None:
        if workspace_id not in visible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        stmt = stmt.where(OpAccessGrant.workspace_id == workspace_id)
    rows = (await db.execute(stmt.order_by(OpAccessGrant.created_at.desc()))).scalars().all()
    return [OpAccessGrantResponse.model_validate(row) for row in rows]


@router.post("/op-resources", status_code=status.HTTP_201_CREATED)
async def create_op_resource(
    body: OpResourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await assert_project_access(body.workspace_id, db, current_user)
    existing = (
        await db.execute(
            select(OpResource).where(
                OpResource.workspace_id == body.workspace_id,
                OpResource.resource_key == body.resource_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resource key already exists in this workspace")

    resource = OpResource(
        workspace_id=body.workspace_id,
        resource_type=body.resource_type,
        resource_key=body.resource_key,
        resource_name=body.resource_name,
        default_access_level=body.default_access_level,
        risk_level=body.risk_level,
        metadata_json=body.metadata_json,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return {
        "id": str(resource.id),
        "workspace_id": str(resource.workspace_id),
        "resource_type": resource.resource_type,
        "resource_key": resource.resource_key,
        "resource_name": resource.resource_name,
        "default_access_level": resource.default_access_level,
        "risk_level": resource.risk_level,
        "active": resource.active,
        "metadata_json": resource.metadata_json,
        "created_at": resource.created_at.isoformat() if resource.created_at else None,
        "updated_at": resource.updated_at.isoformat() if resource.updated_at else None,
    }
