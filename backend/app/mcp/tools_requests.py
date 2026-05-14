from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import Tool
from sqlalchemy import select

from app.api.ops import (
    ApprovalDecisionBody,
    CommentCreate,
    OpApprovalResponse,
    ProvideInfoBody,
    RequestMoreInfoBody,
    _decide_approval,
    create_op_request_comment,
    get_op_friction_metrics,
    get_op_request,
    list_op_audit,
    list_op_request_approvals,
    list_op_request_comments,
    list_op_request_events,
    list_op_request_fulfillment_tasks,
    list_op_request_notifications,
    list_op_request_policy_results,
    list_op_requests,
    mark_request_fulfilled,
    op_approval_inbox,
    provide_info as provide_info_endpoint,
    request_more_info as request_more_info_endpoint,
    search_op_requests,
)
from app.database import async_session
from app.models import OpRequest, User

REQUEST_TOOL_SCHEMAS: list[Tool] = [
    Tool(
        name="list_open_requests",
        description="List open OpsRadar requests visible to the current user. Use this to triage drafts, pending approvals, fulfillment work, and blocked requests.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Optional workspace UUID filter."},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
            "required": [],
        },
    ),
    Tool(
        name="list_my_approvals",
        description="List approval tasks assigned to the current user. Defaults to pending approvals only.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": "pending"},
                "workspace_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
            "required": [],
        },
    ),
    Tool(
        name="get_request_context",
        description="Return the full OpsRadar context for one request: request summary, approvals, policy results, events, comments, fulfillment tasks, notifications, and audit entries.",
        inputSchema={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
        },
    ),
    Tool(
        name="explain_request_blocker",
        description="Explain why a request is blocked or waiting, using current request state, pending approvals, fulfillment tasks, and recent lifecycle events.",
        inputSchema={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
        },
    ),
    Tool(
        name="search_duplicate_requests",
        description="Search for likely duplicate open requests by resource, title, or request type.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "workspace_id": {"type": "string"},
                "include_closed": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="summarize_friction",
        description="Return the current friction metrics for visible OpsRadar requests, including stuck work, approval delay, fulfillment delay, and top slow request types.",
        inputSchema={
            "type": "object",
            "properties": {"workspace_id": {"type": "string"}},
            "required": [],
        },
    ),
    Tool(
        name="export_request_audit_summary",
        description="Return the audit and event summary for one request, suitable for an operator handoff or compliance review.",
        inputSchema={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
        },
    ),
    Tool(
        name="add_request_comment",
        description="Add a comment to an OpsRadar request using the standard lifecycle and audit hooks.",
        inputSchema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["request_id", "body"],
        },
    ),
    Tool(
        name="request_more_info",
        description="Ask the requester for more information and move the request to waiting_on_requester.",
        inputSchema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "reason": {"type": "string"},
                "requested_fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["request_id", "reason"],
        },
    ),
    Tool(
        name="provide_request_info",
        description="Provide the missing information requested for a waiting request and restore it to the prior lifecycle state.",
        inputSchema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["request_id", "message"],
        },
    ),
    Tool(
        name="decide_approval",
        description="Approve or reject a pending approval using the existing OpsRadar authorization, event, audit, notification, and workflow hooks.",
        inputSchema={
            "type": "object",
            "properties": {
                "approval_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["approve", "reject"]},
                "comment": {"type": "string"},
            },
            "required": ["approval_id", "decision"],
        },
    ),
    Tool(
        name="mark_fulfillment_complete",
        description="Complete a pending fulfillment task for a request and trigger the simulated fulfillment lifecycle.",
        inputSchema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "comment": {"type": "string"},
            },
            "required": ["request_id"],
        },
    ),
]


def _uuid(raw: str | UUID | None) -> UUID | None:
    if raw is None:
        return None
    return raw if isinstance(raw, UUID) else UUID(str(raw))


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


async def list_open_requests(
    user: User,
    *,
    workspace_id: str | UUID | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    async with async_session() as db:
        rows = await list_op_requests(
            workspace_id=_uuid(workspace_id),
            request_status=None,
            requester_email=None,
            limit=limit,
            offset=0,
            db=db,
            current_user=user,
        )
    open_statuses = {
        "draft",
        "submitted",
        "policy_check_pending",
        "pending_approval",
        "waiting_on_requester",
        "fulfillment_pending",
        "escalated",
    }
    filtered = [row for row in rows if row.status in open_statuses]
    return {
        "requests": [_jsonable(row.model_dump(mode="json")) for row in filtered],
        "count": len(filtered),
    }


async def list_my_approvals(
    user: User,
    *,
    status: str | None = "pending",
    workspace_id: str | UUID | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    async with async_session() as db:
        items = await op_approval_inbox(
            approval_status=status,
            workspace_id=_uuid(workspace_id),
            limit=limit,
            offset=0,
            db=db,
            current_user=user,
        )
    return {"approvals": [_jsonable(item.model_dump(mode="json")) for item in items], "count": len(items)}


async def get_request_context(user: User, *, request_id: str | UUID) -> dict[str, Any]:
    request_uuid = _uuid(request_id)
    async with async_session() as db:
        request_row = await get_op_request(request_uuid, db=db, current_user=user)
        events = await list_op_request_events(request_uuid, db=db, current_user=user)
        policies = await list_op_request_policy_results(request_uuid, db=db, current_user=user)
        comments = await list_op_request_comments(request_uuid, db=db, current_user=user)
        approvals = await list_op_request_approvals(request_uuid, db=db, current_user=user)
        tasks = await list_op_request_fulfillment_tasks(request_uuid, db=db, current_user=user)
        notifications = await list_op_request_notifications(request_uuid, db=db, current_user=user)
        audit_entries = await list_op_audit(
            workspace_id=None,
            request_id=request_uuid,
            action=None,
            limit=200,
            offset=0,
            db=db,
            current_user=user,
        )
    return {
        "request": _jsonable(request_row.model_dump(mode="json")),
        "approvals": [_jsonable(item.model_dump(mode="json")) for item in approvals],
        "policy_results": [_jsonable(item.model_dump(mode="json")) for item in policies],
        "events": [_jsonable(item.model_dump(mode="json")) for item in events],
        "comments": _jsonable(comments),
        "fulfillment_tasks": [_jsonable(item.model_dump(mode="json")) for item in tasks],
        "notifications": [_jsonable(item.model_dump(mode="json")) for item in notifications],
        "audit": _jsonable(audit_entries),
    }


async def explain_request_blocker(user: User, *, request_id: str | UUID) -> dict[str, Any]:
    context = await get_request_context(user, request_id=request_id)
    request_row = context["request"]
    status = request_row["status"]

    if status == "waiting_on_requester":
        last_more_info = next(
            (event for event in reversed(context["events"]) if event["event_type"] == "more_info_requested"),
            None,
        )
        return {
            "request_id": request_row["id"],
            "status": status,
            "blocker_type": "waiting_on_requester",
            "explanation": last_more_info["message"] if last_more_info else "The requester needs to provide additional information.",
            "requested_fields": (last_more_info or {}).get("metadata_json", {}).get("requested_fields", []),
            "next_action": "Provide the requested information in OpsRadar so the request can resume.",
        }

    if status == "pending_approval":
        pending = [row for row in context["approvals"] if row["status"] == "pending"]
        return {
            "request_id": request_row["id"],
            "status": status,
            "blocker_type": "pending_approval",
            "explanation": "The request is waiting on one or more approvers.",
            "pending_approvals": pending,
            "next_action": "Review the pending approval assignees and decide the approval.",
        }

    if status == "fulfillment_pending":
        pending_tasks = [row for row in context["fulfillment_tasks"] if row["status"] == "pending"]
        return {
            "request_id": request_row["id"],
            "status": status,
            "blocker_type": "fulfillment_pending",
            "explanation": "Approval is complete, but fulfillment has not been marked done yet.",
            "pending_tasks": pending_tasks,
            "next_action": "Complete the fulfillment task or hand it to the responsible IT/admin role.",
        }

    if status in {"submitted", "policy_check_pending"}:
        latest_policy = context["policy_results"][0] if context["policy_results"] else None
        return {
            "request_id": request_row["id"],
            "status": status,
            "blocker_type": "routing_or_policy",
            "explanation": "The request is still being evaluated or routed.",
            "latest_policy_result": latest_policy,
            "next_action": "Review policy results and approval routing.",
        }

    return {
        "request_id": request_row["id"],
        "status": status,
        "blocker_type": "none",
        "explanation": "This request is not currently blocked by an actionable approval or requester dependency.",
        "next_action": "Inspect the full request context if a deeper diagnosis is needed.",
    }


async def search_duplicate_requests(
    user: User,
    *,
    query: str,
    workspace_id: str | UUID | None = None,
    include_closed: bool = False,
) -> dict[str, Any]:
    async with async_session() as db:
        matches = await search_op_requests(
            q=query,
            workspace_id=_uuid(workspace_id),
            include_closed=include_closed,
            db=db,
            current_user=user,
        )
    return {"matches": [_jsonable(item.model_dump(mode="json")) for item in matches], "count": len(matches)}


async def summarize_friction(user: User, *, workspace_id: str | UUID | None = None) -> dict[str, Any]:
    async with async_session() as db:
        metrics = await get_op_friction_metrics(
            workspace_id=_uuid(workspace_id),
            db=db,
            current_user=user,
        )
    return _jsonable(metrics.model_dump(mode="json"))


async def export_request_audit_summary(user: User, *, request_id: str | UUID) -> dict[str, Any]:
    context = await get_request_context(user, request_id=request_id)
    request_row = context["request"]
    approvals = context["approvals"]
    summary = {
        "request_id": request_row["id"],
        "request_title": request_row["title"],
        "request_status": request_row["status"],
        "approval_count": len(approvals),
        "approved_count": sum(1 for row in approvals if row["status"] == "approved"),
        "rejected_count": sum(1 for row in approvals if row["status"] == "rejected"),
        "event_count": len(context["events"]),
        "comment_count": len(context["comments"]),
        "notification_count": len(context["notifications"]),
        "audit_entry_count": len(context["audit"]),
    }
    return {
        "summary": summary,
        "events": context["events"],
        "audit": context["audit"],
    }


async def add_request_comment(user: User, *, request_id: str | UUID, body: str) -> dict[str, Any]:
    async with async_session() as db:
        result = await create_op_request_comment(
            _uuid(request_id),
            CommentCreate(body=body),
            db=db,
            current_user=user,
        )
    return _jsonable(result)


async def request_more_info(
    user: User,
    *,
    request_id: str | UUID,
    reason: str,
    requested_fields: list[str] | None = None,
) -> dict[str, Any]:
    async with async_session() as db:
        result = await request_more_info_endpoint(
            _uuid(request_id),
            RequestMoreInfoBody(reason=reason, requested_fields=requested_fields or []),
            db=db,
            current_user=user,
        )
    return _jsonable(result.model_dump(mode="json"))


async def provide_request_info(user: User, *, request_id: str | UUID, message: str) -> dict[str, Any]:
    async with async_session() as db:
        result = await provide_info_endpoint(
            _uuid(request_id),
            ProvideInfoBody(message=message),
            db=db,
            current_user=user,
        )
    return _jsonable(result.model_dump(mode="json"))


async def decide_approval(
    user: User,
    *,
    approval_id: str | UUID,
    decision: str,
    comment: str | None = None,
) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be 'approve' or 'reject'")
    async with async_session() as db:
        approval = await _decide_approval(
            _uuid(approval_id),
            decision=decision,
            body=ApprovalDecisionBody(comment=comment),
            db=db,
            current_user=user,
        )
    return _jsonable(OpApprovalResponse.model_validate(approval).model_dump(mode="json"))


async def mark_fulfillment_complete(
    user: User,
    *,
    request_id: str | UUID,
    comment: str | None = None,
) -> dict[str, Any]:
    async with async_session() as db:
        result = await mark_request_fulfilled(
            _uuid(request_id),
            ApprovalDecisionBody(comment=comment),
            db=db,
            current_user=user,
    )
    return _jsonable(result.model_dump(mode="json"))


REQUEST_TOOL_DISPATCH: dict[str, Any] = {
    "list_open_requests": lambda user, args: list_open_requests(
        user,
        workspace_id=args.get("workspace_id"),
        limit=int(args.get("limit", 50)),
    ),
    "list_my_approvals": lambda user, args: list_my_approvals(
        user,
        status=args.get("status", "pending"),
        workspace_id=args.get("workspace_id"),
        limit=int(args.get("limit", 50)),
    ),
    "get_request_context": lambda user, args: get_request_context(user, request_id=args["request_id"]),
    "explain_request_blocker": lambda user, args: explain_request_blocker(user, request_id=args["request_id"]),
    "search_duplicate_requests": lambda user, args: search_duplicate_requests(
        user,
        query=str(args["query"]),
        workspace_id=args.get("workspace_id"),
        include_closed=bool(args.get("include_closed", False)),
    ),
    "summarize_friction": lambda user, args: summarize_friction(user, workspace_id=args.get("workspace_id")),
    "export_request_audit_summary": lambda user, args: export_request_audit_summary(
        user,
        request_id=args["request_id"],
    ),
    "add_request_comment": lambda user, args: add_request_comment(
        user,
        request_id=args["request_id"],
        body=str(args["body"]),
    ),
    "request_more_info": lambda user, args: request_more_info(
        user,
        request_id=args["request_id"],
        reason=str(args["reason"]),
        requested_fields=args.get("requested_fields") or [],
    ),
    "provide_request_info": lambda user, args: provide_request_info(
        user,
        request_id=args["request_id"],
        message=str(args["message"]),
    ),
    "decide_approval": lambda user, args: decide_approval(
        user,
        approval_id=args["approval_id"],
        decision=str(args["decision"]),
        comment=args.get("comment"),
    ),
    "mark_fulfillment_complete": lambda user, args: mark_fulfillment_complete(
        user,
        request_id=args["request_id"],
        comment=args.get("comment"),
    ),
}
