from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import UUID

from mcp.types import Tool

MINING_TOOL_SCHEMAS: list[Tool] = [
    Tool(
        name="list_event_logs",
        description=(
            "List event logs the current user can access. Returns an "
            "array of {id, name, project, total_cases, total_events, "
            "created_at} objects. Always call this first to discover "
            "what logs exist before asking about a specific one."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max logs to return (default 20).",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100,
                }
            },
            "required": [],
        },
    ),
    Tool(
        name="get_log_summary",
        description=(
            "Get the headline stats for one event log: total cases, "
            "total events, unique activities, date range, and average case "
            "duration."
        ),
        inputSchema={
            "type": "object",
            "properties": {"event_log_id": {"type": "string"}},
            "required": ["event_log_id"],
        },
    ),
    Tool(
        name="get_bottlenecks",
        description="Return the activities with the longest average duration in the given event log.",
        inputSchema={
            "type": "object",
            "properties": {
                "event_log_id": {"type": "string"},
                "top_n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
            "required": ["event_log_id"],
        },
    ),
    Tool(
        name="get_variants",
        description="Return the most common execution paths through the process, ranked by case count.",
        inputSchema={
            "type": "object",
            "properties": {
                "event_log_id": {"type": "string"},
                "top_n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
            "required": ["event_log_id"],
        },
    ),
    Tool(
        name="get_rework",
        description="Return activity-level rework rates and cases-with-rework counts for one event log.",
        inputSchema={
            "type": "object",
            "properties": {"event_log_id": {"type": "string"}},
            "required": ["event_log_id"],
        },
    ),
    Tool(
        name="get_conformance",
        description="Run token-based conformance checking against an inductive miner model and return fitness, precision, and deviations.",
        inputSchema={
            "type": "object",
            "properties": {"event_log_id": {"type": "string"}},
            "required": ["event_log_id"],
        },
    ),
    Tool(
        name="get_dfg",
        description="Return the directly-follows graph as a list of {source, target, count} edges.",
        inputSchema={
            "type": "object",
            "properties": {"event_log_id": {"type": "string"}},
            "required": ["event_log_id"],
        },
    ),
    Tool(
        name="get_insights",
        description="Return the automated plain-language process insights shown in the OpsRadar UI.",
        inputSchema={
            "type": "object",
            "properties": {"event_log_id": {"type": "string"}},
            "required": ["event_log_id"],
        },
    ),
    Tool(
        name="ask_natural_language",
        description="Delegate an open-ended process question to the OpsRadar chat pipeline for a grounded answer.",
        inputSchema={
            "type": "object",
            "properties": {
                "event_log_id": {"type": "string"},
                "question": {"type": "string"},
            },
            "required": ["event_log_id", "question"],
        },
    ),
]


def _parse_uuid(raw: Any) -> UUID:
    try:
        return UUID(str(raw))
    except Exception as exc:
        raise ValueError(f"event_log_id must be a UUID, got {raw!r}") from exc


async def _load_df(user: Any, event_log_id: UUID):
    from app.api.mining import _load_event_log_and_df
    from app.database import async_session

    async with async_session() as db:
        return await _load_event_log_and_df(event_log_id, db, user)


async def list_event_logs(user: Any, *, limit: int = 20) -> dict[str, Any]:
    from sqlalchemy import select

    from app.api.deps import _user_can_access_project
    from app.database import async_session
    from app.models import EventLog, Project

    async with async_session() as db:
        result = await db.execute(
            select(EventLog).order_by(EventLog.created_at.desc()).limit(500)
        )
        rows = result.scalars().all()
        out: list[dict[str, Any]] = []
        for log in rows:
            proj_result = await db.execute(select(Project).where(Project.id == log.project_id))
            project = proj_result.scalar_one_or_none()
            if project is None or not _user_can_access_project(user, project):
                continue
            out.append(
                {
                    "id": str(log.id),
                    "name": log.name,
                    "project": project.name,
                    "log_type": log.log_type.value if hasattr(log.log_type, "value") else str(log.log_type),
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
            )
            if len(out) >= limit:
                break
    return {"event_logs": out, "count": len(out)}


async def get_log_summary(user: Any, *, event_log_id: str) -> dict[str, Any]:
    from app.services.mining_engine import mining_engine

    event_log, df = await _load_df(user, _parse_uuid(event_log_id))
    stats = mining_engine.compute_statistics(df)
    return {
        "event_log_id": str(event_log.id),
        "name": event_log.name,
        "total_cases": stats.get("total_cases"),
        "total_events": stats.get("total_events"),
        "total_activities": stats.get("total_activities"),
        "avg_case_duration_seconds": stats.get("avg_case_duration_seconds"),
        "date_range": stats.get("date_range"),
    }


async def get_bottlenecks(user: Any, *, event_log_id: str, top_n: int = 10) -> dict[str, Any]:
    from app.services.mining_engine import mining_engine

    _event_log, df = await _load_df(user, _parse_uuid(event_log_id))
    result = mining_engine.run_bottleneck_analysis(df)
    bottlenecks = result.get("bottlenecks", [])[: max(1, min(int(top_n), 50))]
    return {"bottlenecks": bottlenecks, "total": len(bottlenecks)}


async def get_variants(user: Any, *, event_log_id: str, top_n: int = 10) -> dict[str, Any]:
    from app.services.mining_engine import mining_engine

    _event_log, df = await _load_df(user, _parse_uuid(event_log_id))
    result = mining_engine.run_variant_analysis(df)
    limit = max(1, min(int(top_n), 50))
    return {
        "variants": result.get("variants", [])[:limit],
        "total_variants": result.get("total_variants"),
    }


async def get_rework(user: Any, *, event_log_id: str) -> dict[str, Any]:
    from app.services.mining_engine import mining_engine

    _event_log, df = await _load_df(user, _parse_uuid(event_log_id))
    return mining_engine.get_rework(df)


async def get_conformance(user: Any, *, event_log_id: str) -> Any:
    from app.services.mining_engine import mining_engine

    _event_log, df = await _load_df(user, _parse_uuid(event_log_id))
    return mining_engine.run_conformance(df, method="token_replay")


async def get_dfg(user: Any, *, event_log_id: str) -> Any:
    from app.services.mining_engine import mining_engine

    _event_log, df = await _load_df(user, _parse_uuid(event_log_id))
    return mining_engine.discover_process(df, algorithm="dfg")


async def get_insights(user: Any, *, event_log_id: str) -> Any:
    from app.services.mining_engine import mining_engine

    _event_log, df = await _load_df(user, _parse_uuid(event_log_id))
    return mining_engine.generate_insights(df)


async def ask_natural_language(user: Any, *, event_log_id: str, question: str) -> dict[str, Any]:
    from app.api.ai import _SYSTEM_PROMPT, _build_log_context
    from app.database import async_session
    from app.services import llm

    event_log_uuid = _parse_uuid(event_log_id)
    prompt = str(question or "").strip()
    if not prompt:
        raise ValueError("question must be a non-empty string")

    async with async_session() as db:
        context = await _build_log_context(event_log_uuid, db, user)

    user_prompt = (
        f"Context for the event log the user is asking about:\n\n{context}\n\n"
        f"User question: {prompt}"
    )
    text = llm.complete(_SYSTEM_PROMPT, user_prompt)
    return {"answer": text, "llm_configured": llm.is_llm_configured()}


MINING_TOOL_DISPATCH: dict[str, Callable[[Any, dict[str, Any]], Awaitable[Any]]] = {
    "list_event_logs": lambda user, args: list_event_logs(user, limit=int(args.get("limit", 20))),
    "get_log_summary": lambda user, args: get_log_summary(user, event_log_id=str(args["event_log_id"])),
    "get_bottlenecks": lambda user, args: get_bottlenecks(
        user,
        event_log_id=str(args["event_log_id"]),
        top_n=int(args.get("top_n", 10)),
    ),
    "get_variants": lambda user, args: get_variants(
        user,
        event_log_id=str(args["event_log_id"]),
        top_n=int(args.get("top_n", 10)),
    ),
    "get_rework": lambda user, args: get_rework(user, event_log_id=str(args["event_log_id"])),
    "get_conformance": lambda user, args: get_conformance(user, event_log_id=str(args["event_log_id"])),
    "get_dfg": lambda user, args: get_dfg(user, event_log_id=str(args["event_log_id"])),
    "get_insights": lambda user, args: get_insights(user, event_log_id=str(args["event_log_id"])),
    "ask_natural_language": lambda user, args: ask_natural_language(
        user,
        event_log_id=str(args["event_log_id"]),
        question=str(args.get("question") or ""),
    ),
}
