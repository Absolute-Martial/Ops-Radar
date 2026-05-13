from __future__ import annotations

from datetime import datetime, timezone
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import OpNotification, OpRequest, OpRequestEvent, User

logger = logging.getLogger(__name__)


def _notification_copy(event_type: str, request_row: OpRequest) -> tuple[str, str]:
    subject_map = {
        "request_submitted": f"OpsRadar request submitted: {request_row.title}",
        "approval_created": f"Approval needed: {request_row.title}",
        "more_info_requested": f"More information requested: {request_row.title}",
        "info_provided": f"Requester updated: {request_row.title}",
        "request_approved": f"Request approved: {request_row.title}",
        "request_rejected": f"Request rejected: {request_row.title}",
        "fulfillment_task_created": f"Fulfillment needed: {request_row.title}",
        "fulfillment_completed": f"Fulfillment completed: {request_row.title}",
        "request_completed": f"Request completed: {request_row.title}",
        "request_failed": f"Request closed as failed: {request_row.title}",
        "request_escalated": f"Request escalated: {request_row.title}",
    }
    subject = subject_map.get(event_type, f"OpsRadar update: {request_row.title}")
    body = (
        f"Request: {request_row.title}\n"
        f"Type: {request_row.request_type}\n"
        f"Status: {request_row.status}\n"
        f"Resource: {request_row.resource_name or request_row.resource_key or 'n/a'}\n"
    )
    return subject, body


async def _send_via_novu(notification: OpNotification) -> tuple[str, str | None]:
    if not settings.NOVU_API_KEY:
        return "queued_local", None

    payload = {
        "name": f"{settings.NOVU_WORKFLOW_PREFIX}.{notification.event_type}",
        "to": {"subscriberId": notification.recipient_email, "email": notification.recipient_email},
        "payload": {
            "subject": notification.subject,
            "body": notification.body,
            "request_id": str(notification.request_id),
            "workspace_id": str(notification.workspace_id),
            "channel": notification.channel,
        },
    }
    headers = {
        "Authorization": f"ApiKey {settings.NOVU_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{settings.NOVU_API_URL.rstrip('/')}/v1/events/trigger",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        return "sent", None
    except Exception as exc:  # pragma: no cover - network path is optional in tests
        logger.warning("Novu delivery failed for %s: %s", notification.id, exc)
        return "delivery_failed", str(exc)


async def create_notifications(
    db: AsyncSession,
    request_row: OpRequest,
    *,
    event: OpRequestEvent,
    event_type: str,
    recipients: list[tuple[User | None, str]],
    channel: str = "in_app",
    payload: dict | None = None,
) -> list[OpNotification]:
    created: list[OpNotification] = []
    subject, body = _notification_copy(event_type, request_row)
    unique_recipients: dict[str, User | None] = {}
    for user, email in recipients:
        if not email:
            continue
        unique_recipients[email.strip().lower()] = user

    for email, user in unique_recipients.items():
        notification = OpNotification(
            workspace_id=request_row.workspace_id,
            request_id=request_row.id,
            event_id=event.id,
            recipient_user_id=user.id if user else None,
            recipient_email=email,
            channel=channel,
            provider="novu" if settings.NOVU_API_KEY else "local_log",
            event_type=event_type,
            status="queued",
            subject=subject,
            body=body,
            payload_json=payload,
        )
        db.add(notification)
        await db.flush()
        status_value, error_message = await _send_via_novu(notification)
        notification.status = status_value
        if status_value == "sent":
            notification.sent_at = datetime.now(timezone.utc)
            notification.delivered_at = notification.sent_at
        if error_message:
            notification.error_message = error_message
        created.append(notification)
    return created
