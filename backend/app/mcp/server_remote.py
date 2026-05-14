from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp.auth import MCPBearerAuthMiddleware
from app.mcp.context import require_current_mcp_user
from app.mcp.tools_mining import (
    ask_natural_language,
    get_bottlenecks,
    get_conformance,
    get_dfg,
    get_insights,
    get_log_summary,
    get_rework,
    get_variants,
    list_event_logs,
)
from app.mcp.tools_requests import (
    add_request_comment,
    decide_approval,
    explain_request_blocker,
    export_request_audit_summary,
    get_request_context,
    list_my_approvals,
    list_open_requests,
    mark_fulfillment_complete,
    provide_request_info,
    request_more_info,
    search_duplicate_requests,
    summarize_friction,
)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


@lru_cache(maxsize=1)
def get_opsreader_remote_server() -> FastMCP:
    server = FastMCP(
        name="opsreader-mcp",
        instructions=(
            "OpsReader is the MCP interface for OpsRadar. It exposes "
            "process-intelligence tools, request coordination tools, "
            "approval actions, and audit-friendly context summaries."
        ),
        streamable_http_path="/",
        debug=False,
        stateless_http=False,
    )

    @server.tool(name="list_event_logs", description="List event logs the current user can access.")
    async def list_event_logs_tool(limit: int = 20) -> dict[str, Any]:
        return _jsonable(await list_event_logs(require_current_mcp_user(), limit=limit))

    @server.tool(name="get_log_summary", description="Get the summary statistics for one event log.")
    async def get_log_summary_tool(event_log_id: str) -> dict[str, Any]:
        return _jsonable(await get_log_summary(require_current_mcp_user(), event_log_id=event_log_id))

    @server.tool(name="get_bottlenecks", description="Get bottleneck activities for one event log.")
    async def get_bottlenecks_tool(event_log_id: str, top_n: int = 10) -> dict[str, Any]:
        return _jsonable(await get_bottlenecks(require_current_mcp_user(), event_log_id=event_log_id, top_n=top_n))

    @server.tool(name="get_variants", description="Get the most common variants for one event log.")
    async def get_variants_tool(event_log_id: str, top_n: int = 10) -> dict[str, Any]:
        return _jsonable(await get_variants(require_current_mcp_user(), event_log_id=event_log_id, top_n=top_n))

    @server.tool(name="get_rework", description="Get activity-level rework metrics for one event log.")
    async def get_rework_tool(event_log_id: str) -> dict[str, Any]:
        return _jsonable(await get_rework(require_current_mcp_user(), event_log_id=event_log_id))

    @server.tool(name="get_conformance", description="Run conformance checking for one event log.")
    async def get_conformance_tool(event_log_id: str) -> Any:
        return _jsonable(await get_conformance(require_current_mcp_user(), event_log_id=event_log_id))

    @server.tool(name="get_dfg", description="Return the directly-follows graph for one event log.")
    async def get_dfg_tool(event_log_id: str) -> Any:
        return _jsonable(await get_dfg(require_current_mcp_user(), event_log_id=event_log_id))

    @server.tool(name="get_insights", description="Return generated process insights for one event log.")
    async def get_insights_tool(event_log_id: str) -> Any:
        return _jsonable(await get_insights(require_current_mcp_user(), event_log_id=event_log_id))

    @server.tool(name="ask_natural_language", description="Ask a natural-language question about one event log.")
    async def ask_natural_language_tool(event_log_id: str, question: str) -> dict[str, Any]:
        return _jsonable(
            await ask_natural_language(require_current_mcp_user(), event_log_id=event_log_id, question=question)
        )

    @server.tool(name="list_open_requests", description="List open OpsRadar requests visible to the current user.")
    async def list_open_requests_tool(workspace_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        return _jsonable(
            await list_open_requests(require_current_mcp_user(), workspace_id=workspace_id, limit=limit)
        )

    @server.tool(name="list_my_approvals", description="List approval tasks assigned to the current user.")
    async def list_my_approvals_tool(
        status: str | None = "pending",
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return _jsonable(
            await list_my_approvals(
                require_current_mcp_user(),
                status=status,
                workspace_id=workspace_id,
                limit=limit,
            )
        )

    @server.tool(name="get_request_context", description="Return the full request context for one OpsRadar request.")
    async def get_request_context_tool(request_id: str) -> dict[str, Any]:
        return _jsonable(await get_request_context(require_current_mcp_user(), request_id=request_id))

    @server.tool(name="explain_request_blocker", description="Explain why an OpsRadar request is currently blocked.")
    async def explain_request_blocker_tool(request_id: str) -> dict[str, Any]:
        return _jsonable(await explain_request_blocker(require_current_mcp_user(), request_id=request_id))

    @server.tool(name="search_duplicate_requests", description="Search for likely duplicate requests.")
    async def search_duplicate_requests_tool(
        query: str,
        workspace_id: str | None = None,
        include_closed: bool = False,
    ) -> dict[str, Any]:
        return _jsonable(
            await search_duplicate_requests(
                require_current_mcp_user(),
                query=query,
                workspace_id=workspace_id,
                include_closed=include_closed,
            )
        )

    @server.tool(name="summarize_friction", description="Summarize request friction metrics.")
    async def summarize_friction_tool(workspace_id: str | None = None) -> dict[str, Any]:
        return _jsonable(await summarize_friction(require_current_mcp_user(), workspace_id=workspace_id))

    @server.tool(name="export_request_audit_summary", description="Export the audit and event summary for one request.")
    async def export_request_audit_summary_tool(request_id: str) -> dict[str, Any]:
        return _jsonable(await export_request_audit_summary(require_current_mcp_user(), request_id=request_id))

    @server.tool(name="add_request_comment", description="Add a comment to an OpsRadar request.")
    async def add_request_comment_tool(request_id: str, body: str) -> dict[str, Any]:
        return _jsonable(await add_request_comment(require_current_mcp_user(), request_id=request_id, body=body))

    @server.tool(name="request_more_info", description="Move a request to waiting_on_requester with a reason.")
    async def request_more_info_tool(
        request_id: str,
        reason: str,
        requested_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        return _jsonable(
            await request_more_info(
                require_current_mcp_user(),
                request_id=request_id,
                reason=reason,
                requested_fields=requested_fields or [],
            )
        )

    @server.tool(name="provide_request_info", description="Provide the requested information for a waiting request.")
    async def provide_request_info_tool(request_id: str, message: str) -> dict[str, Any]:
        return _jsonable(
            await provide_request_info(require_current_mcp_user(), request_id=request_id, message=message)
        )

    @server.tool(name="decide_approval", description="Approve or reject a pending OpsRadar approval.")
    async def decide_approval_tool(
        approval_id: str,
        decision: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        return _jsonable(
            await decide_approval(
                require_current_mcp_user(),
                approval_id=approval_id,
                decision=decision,
                comment=comment,
            )
        )

    @server.tool(name="mark_fulfillment_complete", description="Mark a pending fulfillment task as complete.")
    async def mark_fulfillment_complete_tool(
        request_id: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        return _jsonable(
            await mark_fulfillment_complete(
                require_current_mcp_user(),
                request_id=request_id,
                comment=comment,
            )
        )

    return server


def create_streamable_http_app():
    return MCPBearerAuthMiddleware(get_opsreader_remote_server().streamable_http_app())
