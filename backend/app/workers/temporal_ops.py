from __future__ import annotations

import asyncio
from asyncio import TimeoutError
from datetime import timedelta

from app.config import settings


try:  # pragma: no cover - import is optional during local non-Temporal tests
    from temporalio import workflow
    from temporalio.client import Client
    from temporalio.worker import Worker
except ImportError:  # pragma: no cover
    workflow = None
    Client = None
    Worker = None


if workflow is not None:

    @workflow.defn(name="AccessRequestWorkflow")
    class AccessRequestWorkflow:
        def __init__(self) -> None:
            self.current_status = "submitted"
            self.timeline: list[dict] = []
            self.decision: str | None = None

        @workflow.run
        async def run(self, payload: dict) -> dict:
            self.timeline.append({"event": "workflow_started", "payload": payload})
            self.current_status = "pending_approval"
            try:
                await workflow.wait_condition(
                    lambda: self.decision in {"approved", "rejected", "cancelled"},
                    timeout=timedelta(seconds=payload.get("approval_timeout_seconds") or settings.TEMPORAL_APPROVAL_TIMEOUT_SECONDS),
                )
            except TimeoutError:
                self.current_status = "escalated"
                self.timeline.append({"event": "approval_timeout"})
                return {"status": self.current_status, "timeline": self.timeline}

            if self.decision == "approved":
                self.current_status = "fulfillment_pending"
                try:
                    await workflow.wait_condition(
                        lambda: self.decision in {"fulfilled", "cancelled"},
                        timeout=timedelta(seconds=payload.get("requester_info_timeout_seconds") or settings.TEMPORAL_REQUESTER_INFO_TIMEOUT_SECONDS),
                    )
                except TimeoutError:
                    self.current_status = "escalated"
                    self.timeline.append({"event": "fulfillment_timeout"})
                    return {"status": self.current_status, "timeline": self.timeline}

            self.current_status = self.decision or self.current_status
            self.timeline.append({"event": "workflow_finished", "status": self.current_status})
            return {"status": self.current_status, "timeline": self.timeline}

        @workflow.signal
        def approve_request(self, payload: dict) -> None:
            self.timeline.append({"event": "approve_request", "payload": payload})
            self.decision = "approved"

        @workflow.signal
        def reject_request(self, payload: dict) -> None:
            self.timeline.append({"event": "reject_request", "payload": payload})
            self.decision = "rejected"

        @workflow.signal
        def request_more_info(self, payload: dict) -> None:
            self.timeline.append({"event": "request_more_info", "payload": payload})
            self.current_status = "waiting_on_requester"

        @workflow.signal
        def provide_info(self, payload: dict) -> None:
            self.timeline.append({"event": "provide_info", "payload": payload})
            self.current_status = "pending_approval"

        @workflow.signal
        def mark_fulfilled(self, payload: dict) -> None:
            self.timeline.append({"event": "mark_fulfilled", "payload": payload})
            self.decision = "fulfilled"

        @workflow.query
        def get_current_status(self) -> str:
            return self.current_status

        @workflow.query
        def get_timeline(self) -> list[dict]:
            return self.timeline


async def run_temporal_worker() -> None:  # pragma: no cover - requires external Temporal runtime
    if Client is None or Worker is None or workflow is None:
        raise RuntimeError("temporalio is not installed")

    address = settings.TEMPORAL_ADDRESS.strip()
    if not address:
        raise RuntimeError("TEMPORAL_ADDRESS is not configured")

    while True:
        try:
            client = await Client.connect(
                address,
                namespace=settings.TEMPORAL_NAMESPACE,
            )
            worker = Worker(
                client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[AccessRequestWorkflow],
            )
            logger.info("Temporal worker connected to %s", address)
            await worker.run()
            return
        except Exception as exc:
            logger.warning("Temporal worker connection failed for %s: %s", address, exc)
            await asyncio.sleep(5)


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(run_temporal_worker())
