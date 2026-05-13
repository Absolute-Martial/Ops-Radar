from __future__ import annotations

import json
import uuid

import pytest

from app.models import UserRole
from tests.conftest import auth_header


async def _create_project(client, token: str, *, name: str) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={"name": name},
        headers=auth_header(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_request(client, token: str, *, workspace_id: str, title: str) -> dict:
    response = await client.post(
        "/api/v1/op-requests",
        json={
            "workspace_id": workspace_id,
            "request_type": "production access request",
            "title": title,
            "resource_key": f"svc-{uuid.uuid4().hex[:8]}",
            "resource_name": "Payments Service",
            "access_level": "admin",
            "reason": "Investigate an incident",
            "urgency": "high",
            "duration_days": 7,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _assign_role(client, token: str, *, workspace_id: str, user_id: str, role_key: str) -> dict:
    response = await client.post(
        "/api/v1/op-role-assignments",
        json={
            "workspace_id": workspace_id,
            "user_id": user_id,
            "role_key": role_key,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_op_request_lifecycle_approve_flow(client, make_user, monkeypatch):
    requester, requester_token = await make_user(role=UserRole.analyst)
    approver, approver_token = await make_user(role=UserRole.admin)

    async def _resolve_request_approvers(_db, _request_row):
        return [approver]

    monkeypatch.setattr("app.api.ops._resolve_request_approvers", _resolve_request_approvers)

    workspace_id = await _create_project(
        client,
        requester_token,
        name=f"Ops Lifecycle Approve {uuid.uuid4().hex[:8]}",
    )
    created = await _create_request(
        client,
        requester_token,
        workspace_id=workspace_id,
        title="Production read access for incident triage",
    )

    assert created["status"] == "draft"
    assert created["request_type"] == "production_access_request"
    assert created["risk_level"] == "high"

    submit_response = await client.post(
        f"/api/v1/op-requests/{created['id']}/submit",
        headers=auth_header(requester_token),
    )

    assert submit_response.status_code == 200, submit_response.text
    submitted = submit_response.json()
    assert submitted["status"] == "pending_approval"

    requester_inbox = await client.get(
        "/api/v1/op-approvals/inbox",
        headers=auth_header(requester_token),
    )
    assert requester_inbox.status_code == 200, requester_inbox.text
    assert requester_inbox.json() == []

    approvals_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/approvals",
        headers=auth_header(requester_token),
    )
    assert approvals_response.status_code == 200, approvals_response.text
    approvals = approvals_response.json()
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval["status"] == "pending"
    assert approval["approver_user_id"] == str(approver.id)
    assert approval["approver_email"] == approver.email

    approver_inbox = await client.get(
        "/api/v1/op-approvals/inbox",
        params={"workspace_id": workspace_id},
        headers=auth_header(approver_token),
    )
    assert approver_inbox.status_code == 200, approver_inbox.text
    approver_items = approver_inbox.json()
    assert len(approver_items) == 1
    assert approver_items[0]["id"] == approval["id"]
    assert approver_items[0]["request_id"] == created["id"]
    assert approver_items[0]["request_status"] == "pending_approval"
    assert approver_items[0]["requester_email"] == requester.email

    approve_response = await client.post(
        f"/api/v1/op-approvals/{approval['id']}/approve",
        json={"comment": "Approved for incident response"},
        headers=auth_header(approver_token),
    )
    assert approve_response.status_code == 200, approve_response.text
    approved = approve_response.json()
    assert approved["status"] == "approved"
    assert approved["decision"] == "approve"
    assert approved["decision_comment"] == "Approved for incident response"

    request_response = await client.get(
        f"/api/v1/op-requests/{created['id']}",
        headers=auth_header(requester_token),
    )
    assert request_response.status_code == 200, request_response.text
    request_payload = request_response.json()
    assert request_payload["status"] == "fulfillment_pending"
    assert request_payload["temporal_workflow_id"].startswith("opsradar-access-request-")

    tasks_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/fulfillment-tasks",
        headers=auth_header(requester_token),
    )
    assert tasks_response.status_code == 200, tasks_response.text
    tasks = tasks_response.json()
    assert len(tasks) == 1
    assert tasks[0]["status"] == "pending"

    fulfill_response = await client.post(
        f"/api/v1/op-requests/{created['id']}/fulfillment/mark-complete",
        json={"comment": "Manual grant completed"},
        headers=auth_header(approver_token),
    )
    assert fulfill_response.status_code == 200, fulfill_response.text
    assert fulfill_response.json()["status"] == "completed"

    grants_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/access-grants",
        headers=auth_header(requester_token),
    )
    assert grants_response.status_code == 200, grants_response.text
    grants = grants_response.json()
    assert len(grants) == 1
    assert grants[0]["user_email"] == requester.email
    assert grants[0]["resource_name"] == "Payments Service"

    policy_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/policy-results",
        headers=auth_header(requester_token),
    )
    assert policy_response.status_code == 200, policy_response.text
    policies = policy_response.json()
    assert policies[0]["decision"] == "approval_required"
    assert policies[0]["risk_level"] == "high"
    assert policies[0]["policy_version"] == "opsradar-v1"

    notifications_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/notifications",
        headers=auth_header(requester_token),
    )
    assert notifications_response.status_code == 200, notifications_response.text
    notifications = notifications_response.json()
    assert len(notifications) >= 5
    assert {item["event_type"] for item in notifications} >= {
        "request_submitted",
        "approval_created",
        "request_approved",
        "fulfillment_task_created",
        "request_completed",
    }

    events_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/events",
        headers=auth_header(requester_token),
    )
    assert events_response.status_code == 200, events_response.text
    event_types = [event["event_type"] for event in events_response.json()]
    assert event_types == [
        "request_created",
        "request_submitted",
        "notification_queued",
        "temporal_workflow_started",
        "policy_evaluated",
        "approval_created",
        "notification_queued",
        "approval_approved",
        "temporal_signal_received",
        "request_approved",
        "notification_queued",
        "fulfillment_task_created",
        "notification_queued",
        "fulfillment_started",
        "fulfillment_completed",
        "notification_queued",
        "request_completed",
        "notification_queued",
    ]


@pytest.mark.asyncio
async def test_op_request_lifecycle_reject_flow(client, make_user, monkeypatch):
    requester, requester_token = await make_user(role=UserRole.analyst)
    approver, approver_token = await make_user(role=UserRole.admin)

    async def _resolve_request_approvers(_db, _request_row):
        return [approver]

    monkeypatch.setattr("app.api.ops._resolve_request_approvers", _resolve_request_approvers)

    workspace_id = await _create_project(
        client,
        requester_token,
        name=f"Ops Lifecycle Reject {uuid.uuid4().hex[:8]}",
    )
    created = await _create_request(
        client,
        requester_token,
        workspace_id=workspace_id,
        title="Temporary vendor access for audit support",
    )

    submit_response = await client.post(
        f"/api/v1/op-requests/{created['id']}/submit",
        headers=auth_header(requester_token),
    )
    assert submit_response.status_code == 200, submit_response.text

    approvals_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/approvals",
        headers=auth_header(requester_token),
    )
    assert approvals_response.status_code == 200, approvals_response.text
    approval = approvals_response.json()[0]

    reject_response = await client.post(
        f"/api/v1/op-approvals/{approval['id']}/reject",
        json={"comment": "Use break-glass process instead"},
        headers=auth_header(approver_token),
    )
    assert reject_response.status_code == 200, reject_response.text
    rejected = reject_response.json()
    assert rejected["status"] == "rejected"
    assert rejected["decision"] == "reject"
    assert rejected["decision_comment"] == "Use break-glass process instead"
    assert rejected["decided_at"] is not None

    request_response = await client.get(
        f"/api/v1/op-requests/{created['id']}",
        headers=auth_header(requester_token),
    )
    assert request_response.status_code == 200, request_response.text
    request_payload = request_response.json()
    assert request_payload["status"] == "rejected"
    assert request_payload["completed_at"] is not None

    inbox_response = await client.get(
        "/api/v1/op-approvals/inbox",
        params={"status": "rejected", "workspace_id": workspace_id},
        headers=auth_header(approver_token),
    )
    assert inbox_response.status_code == 200, inbox_response.text
    inbox_items = inbox_response.json()
    assert len(inbox_items) == 1
    assert inbox_items[0]["id"] == approval["id"]
    assert inbox_items[0]["request_status"] == "rejected"

    events_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/events",
        headers=auth_header(requester_token),
    )
    assert events_response.status_code == 200, events_response.text
    event_types = [event["event_type"] for event in events_response.json()]
    assert event_types == [
        "request_created",
        "request_submitted",
        "notification_queued",
        "temporal_workflow_started",
        "policy_evaluated",
        "approval_created",
        "notification_queued",
        "approval_rejected",
        "temporal_signal_received",
        "request_failed",
        "notification_queued",
    ]


@pytest.mark.asyncio
async def test_op_request_submit_uses_workspace_role_assignments(client, make_user):
    requester, requester_token = await make_user(role=UserRole.analyst)
    admin, admin_token = await make_user(role=UserRole.admin)
    manager, _manager_token = await make_user(role=UserRole.analyst)
    it_admin, _it_admin_token = await make_user(role=UserRole.analyst)
    security_reviewer, _security_token = await make_user(role=UserRole.analyst)

    workspace_id = await _create_project(
        client,
        requester_token,
        name=f"Ops Routing {uuid.uuid4().hex[:8]}",
    )

    await _assign_role(client, admin_token, workspace_id=workspace_id, user_id=str(manager.id), role_key="manager")
    await _assign_role(client, admin_token, workspace_id=workspace_id, user_id=str(it_admin.id), role_key="it_admin")
    await _assign_role(
        client,
        admin_token,
        workspace_id=workspace_id,
        user_id=str(security_reviewer.id),
        role_key="security_reviewer",
    )

    created = await _create_request(
        client,
        requester_token,
        workspace_id=workspace_id,
        title="Production admin access for incident response",
    )

    submit_response = await client.post(
        f"/api/v1/op-requests/{created['id']}/submit",
        headers=auth_header(requester_token),
    )
    assert submit_response.status_code == 200, submit_response.text

    approvals_response = await client.get(
        f"/api/v1/op-requests/{created['id']}/approvals",
        headers=auth_header(requester_token),
    )
    assert approvals_response.status_code == 200, approvals_response.text
    approvals = approvals_response.json()
    roles = {approval["approver_role_key"] for approval in approvals}
    emails = {approval["approver_email"] for approval in approvals}

    assert roles == {"manager", "it_admin", "security_reviewer"}
    assert emails == {manager.email, it_admin.email, security_reviewer.email}


@pytest.mark.asyncio
async def test_slack_modal_submission_creates_request(client, make_user):
    admin, admin_token = await make_user(role=UserRole.admin)
    _requester, _requester_token = await make_user(role=UserRole.analyst)

    workspace_id = await _create_project(
        client,
        admin_token,
        name=f"Ops Slack Modal {uuid.uuid4().hex[:8]}",
    )

    source_response = await client.post(
        "/api/v1/intake-sources",
        json={
            "workspace_id": workspace_id,
            "name": "Slack Intake",
            "source_type": "slack",
            "allowed_project_or_channel": "C12345",
        },
        headers=auth_header(admin_token),
    )
    assert source_response.status_code == 201, source_response.text

    payload = {
        "type": "view_submission",
        "user": {"id": "U12345"},
        "trigger_id": "trigger-123",
        "view": {
            "private_metadata": f'{{"workspace_id":"{workspace_id}","channel_id":"C12345"}}',
            "state": {
                "values": {
                    "email_block": {"email": {"type": "plain_text_input", "value": "requester@example.com"}},
                    "resource_block": {"resource": {"type": "plain_text_input", "value": "Figma"}},
                    "access_block": {"access": {"type": "plain_text_input", "value": "editor"}},
                    "reason_block": {"reason": {"type": "plain_text_input", "value": "Need design access"}},
                }
            },
        },
    }
    response = await client.post(
        "/api/v1/slack/interactions",
        content=f"payload={json.dumps(payload)}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text

    requests_response = await client.get(
        "/api/v1/op-requests",
        params={"workspace_id": workspace_id},
        headers=auth_header(admin_token),
    )
    assert requests_response.status_code == 200, requests_response.text
    requests_payload = requests_response.json()
    assert len(requests_payload) == 1
    assert requests_payload[0]["source_type"] == "slack"
    assert requests_payload[0]["requester_email"] == "requester@example.com"
