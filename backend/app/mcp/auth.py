from __future__ import annotations

import json
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import Response

from app.api.deps import resolve_bearer_token_user
from app.database import async_session
from app.mcp.context import reset_current_mcp_user, set_current_mcp_user


def _unauthorized_response(detail: str = "Could not validate credentials") -> Response:
    return Response(
        content=json.dumps({"detail": detail}),
        status_code=401,
        headers={
            "content-type": "application/json",
            "www-authenticate": "Bearer",
        },
    )


class MCPBearerAuthMiddleware:
    """ASGI auth wrapper for remote OpsReader MCP transport.

    Reuses the same JWT / ``fmk_`` API-key logic as the REST API and
    stores the resolved user in a request-scoped context variable for
    the duration of the MCP HTTP request.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        auth_header = headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            response = _unauthorized_response()
            await response(scope, receive, send)
            return

        token = auth_header.split(None, 1)[1].strip()
        if not token:
            response = _unauthorized_response()
            await response(scope, receive, send)
            return

        try:
            async with async_session() as db:
                user = await resolve_bearer_token_user(token, db)
        except Exception:
            response = _unauthorized_response()
            await response(scope, receive, send)
            return

        ctx_token = set_current_mcp_user(user)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_mcp_user(ctx_token)
