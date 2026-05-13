import pytest

from app.models import UserRole
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_flowfix_role_blueprints_require_admin(client, make_user):
    _, token = await make_user(role=UserRole.viewer)

    response = await client.get("/api/v1/system-settings/flowfix/roles", headers=auth_header(token))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_flowfix_role_blueprints_default_and_update_roundtrip(
    client, make_user, monkeypatch
):
    _, token = await make_user(role=UserRole.admin)
    store = {}

    def fake_get_setting(key: str):
        return store.get(key)

    def fake_set_setting(key: str, value, *, user_id=None):
        store[key] = value

    monkeypatch.setattr("app.api.system_settings.settings_service.get_setting", fake_get_setting)
    monkeypatch.setattr("app.api.system_settings.settings_service.set_setting", fake_set_setting)

    response = await client.get("/api/v1/system-settings/flowfix/roles", headers=auth_header(token))

    assert response.status_code == 200, response.text
    data = response.json()
    role_ids = {role["id"] for role in data["roles"]}
    assert "super_admin" in role_ids
    assert "requester" in role_ids

    updated_roles = [
        {
            "id": "super_admin",
            "name": "Super Admin",
            "description": "Full workspace control.",
            "role_type": "system",
            "permissions": ["manage_users", "manage_roles"],
            "scopes": {"workspace": "all"},
            "allowed_request_types": ["*"],
            "allowed_resources": ["*"],
            "approval_authority": ["all"],
            "audit_visibility": "all",
            "is_system": True,
            "disabled": False,
        },
        {
            "id": "team_ops",
            "name": "Team Ops",
            "description": "Custom queue owner for request triage.",
            "role_type": "custom",
            "permissions": ["view_team_requests", "approve_request"],
            "scopes": {"owner_team": ["Ops"]},
            "allowed_request_types": ["access_request"],
            "allowed_resources": ["GitHub"],
            "approval_authority": ["assigned_only"],
            "audit_visibility": "assigned",
            "is_system": False,
            "disabled": False,
        },
    ]

    response = await client.put(
        "/api/v1/system-settings/flowfix/roles",
        json={"roles": updated_roles},
        headers=auth_header(token),
    )

    assert response.status_code == 200, response.text
    assert store["flowfix.role_blueprints"] == {"roles": updated_roles}
    assert response.json()["roles"] == updated_roles


@pytest.mark.asyncio
async def test_seed_templates_creates_flowfix_templates_and_is_idempotent(client, make_user):
    _, token = await make_user(role=UserRole.admin)

    first = await client.post("/api/v1/templates/seed", headers=auth_header(token))

    assert first.status_code == 201, first.text
    first_payload = first.json()
    assert first_payload["created"] > 0

    listed = await client.get(
        "/api/v1/templates",
        params={"category": "flowfix"},
        headers=auth_header(token),
    )

    assert listed.status_code == 200, listed.text
    names = {template["name"] for template in listed.json()}
    assert {"Access Request", "Jira Project Creation", "Vendor Review"} <= names

    second = await client.post("/api/v1/templates/seed", headers=auth_header(token))

    assert second.status_code == 201, second.text
    second_payload = second.json()
    assert second_payload["created"] == 0
    assert second_payload["skipped"] == second_payload["total"]
