from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.mcp import auth as mcp_auth
from app.mcp.auth import MCPBearerAuthMiddleware
from app.mcp.context import require_current_mcp_user
from app.mcp.server_remote import get_opsreader_remote_server
from tests.conftest import auth_header


@pytest_asyncio.fixture
async def remote_mcp_client():
    async def _echo_authenticated_user(scope, receive, send):
        user = require_current_mcp_user()
        response = JSONResponse({"email": user.email, "id": str(user.id)})
        await response(scope, receive, send)

    wrapped = MCPBearerAuthMiddleware(_echo_authenticated_user)
    async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_remote_mcp_requires_bearer_auth(client):
    response = await client.post("/mcp", json={})

    assert response.status_code == 307
    assert response.headers["location"] == "/mcp/"


@pytest.mark.asyncio
async def test_remote_mcp_accepts_valid_bearer_before_transport_validation(
    remote_mcp_client,
    make_user,
    monkeypatch,
    test_engine,
):
    _user, token = await make_user()

    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(mcp_auth, "async_session", Session)

    response = await remote_mcp_client.post("/", json={}, headers=auth_header(token))

    assert response.status_code == 200
    assert response.json()["email"] == _user.email


@pytest.mark.asyncio
async def test_remote_mcp_subapp_requires_bearer_auth(remote_mcp_client):
    response = await remote_mcp_client.post("/", json={})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_remote_mcp_registers_request_and_mining_tools():
    server = get_opsreader_remote_server()
    tool_names = {tool.name for tool in await server.list_tools()}

    assert {
        "list_event_logs",
        "get_log_summary",
        "list_open_requests",
        "list_my_approvals",
        "get_request_context",
        "decide_approval",
        "mark_fulfillment_complete",
    } <= tool_names
