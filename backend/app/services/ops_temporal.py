from __future__ import annotations

from dataclasses import dataclass
import logging
from urllib.parse import urlparse

from app.config import settings
from app.models import OpRequest

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStartResult:
    workflow_id: str
    run_id: str | None
    mode: str


def temporal_enabled() -> bool:
    return bool(_temporal_address().strip())


def _temporal_address() -> str:
    return (
        settings.TEMPORAL_ADDRESS.strip()
        or getattr(settings, "TEMPORAL_SERVER_URL", "").strip()
        or ""
    )


def _temporal_connect_address() -> str:
    address = _temporal_address()
    if not address:
        return ""
    if "://" in address:
        parsed = urlparse(address)
        if parsed.hostname:
            return f"{parsed.hostname}:{parsed.port or 7233}"
    return address


async def start_request_workflow(
    request_row: OpRequest,
    *,
    workflow_id: str,
    payload: dict,
) -> WorkflowStartResult:
    if not temporal_enabled():
        return WorkflowStartResult(workflow_id=workflow_id, run_id=None, mode="opsradar_internal_adapter")

    try:
        from temporalio.client import Client
    except ImportError:
        logger.warning("temporalio is not installed; falling back to internal adapter")
        return WorkflowStartResult(workflow_id=workflow_id, run_id=None, mode="opsradar_internal_adapter")

    try:
        client = await Client.connect(
            _temporal_connect_address(),
            namespace=settings.TEMPORAL_NAMESPACE,
        )
        handle = await client.start_workflow(
            "AccessRequestWorkflow",
            payload,
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
        run_id = (
            getattr(handle, "first_execution_run_id", None)
            or getattr(handle, "run_id", None)
            or getattr(request_row, "temporal_run_id", None)
        )
        return WorkflowStartResult(workflow_id=workflow_id, run_id=run_id, mode="temporal")
    except Exception as exc:  # pragma: no cover - requires external Temporal runtime
        logger.warning("Temporal workflow start failed for %s: %s", workflow_id, exc)
        return WorkflowStartResult(workflow_id=workflow_id, run_id=None, mode="opsradar_internal_adapter")


async def signal_request_workflow(request_row: OpRequest, *, signal_name: str, payload: dict) -> str:
    if not temporal_enabled() or not request_row.temporal_workflow_id:
        return "opsradar_internal_adapter"

    try:
        from temporalio.client import Client
    except ImportError:
        logger.warning("temporalio is not installed; skipping signal %s", signal_name)
        return "opsradar_internal_adapter"

    try:
        client = await Client.connect(
            _temporal_connect_address(),
            namespace=settings.TEMPORAL_NAMESPACE,
        )
        handle = client.get_workflow_handle(request_row.temporal_workflow_id)
        await handle.signal(signal_name, payload)
        return "temporal"
    except Exception as exc:  # pragma: no cover - requires external Temporal runtime
        logger.warning("Temporal workflow signal failed for %s: %s", request_row.temporal_workflow_id, exc)
        return "opsradar_internal_adapter"
