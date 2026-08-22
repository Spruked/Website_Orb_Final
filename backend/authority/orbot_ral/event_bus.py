"""Asynchronous Execution Fabric: real lane queues, workers, lifecycle telemetry."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .models import ActionProposal, ExecutionPermit, ExecutionPrimitive

Handler = Callable[[ExecutionPrimitive], Awaitable[Dict[str, Any] | None]]
PRIORITY = {
    "emergency_stop": 0,
    "safety": 1,
    "user_interrupt": 2,
    "task_critical": 3,
    "normal": 4,
    "ambient": 5,
}


@dataclass(frozen=True)
class ExecutionEnvelope:
    execution_id: str
    permit_id: str
    proposal_id: str
    cycle_id: str
    world_state_version: int
    world_etag: str
    primitive: ExecutionPrimitive
    permit_expires_at: str


@dataclass(frozen=True)
class TelemetryEvent:
    execution_id: str
    primitive_id: str
    cycle_id: str
    lane: str
    status: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AsyncExecutionFabric:
    def __init__(self) -> None:
        self.queues: Dict[str, asyncio.PriorityQueue] = {
            "tool": asyncio.PriorityQueue(maxsize=32),
            "speech": asyncio.PriorityQueue(maxsize=16),
            "motion": asyncio.PriorityQueue(maxsize=32),
            "pointer": asyncio.PriorityQueue(maxsize=16),
        }
        self.handlers: Dict[str, Handler] = {}
        self.telemetry: List[TelemetryEvent] = []
        self._sequence = 0
        self._cancelled_groups: set[str] = set()

    def register_handler(self, lane: str, handler: Handler) -> None:
        self.handlers[lane] = handler

    async def dispatch(self, proposal: ActionProposal, permit: ExecutionPermit) -> List[ExecutionEnvelope]:
        approved = set(permit.approved_primitive_ids)
        envelopes: List[ExecutionEnvelope] = []
        for primitive in proposal.primitives:
            if primitive.primitive_id not in approved:
                continue
            self._sequence += 1
            envelope = ExecutionEnvelope(
                execution_id=f"exec-{proposal.cycle_id}-{primitive.primitive_id}",
                permit_id=permit.permit_id,
                proposal_id=proposal.proposal_id,
                cycle_id=proposal.cycle_id,
                world_state_version=permit.world_state_version,
                world_etag=permit.world_etag,
                primitive=primitive,
                permit_expires_at=permit.expires_at,
            )
            await self.queues[primitive.lane].put((PRIORITY[primitive.priority], self._sequence, envelope))
            self._emit(envelope, "QUEUED")
            envelopes.append(envelope)
        return envelopes

    def cancel_group(self, cancel_group: str) -> None:
        self._cancelled_groups.add(cancel_group)

    async def run_one(self, lane: str) -> Optional[TelemetryEvent]:
        queue = self.queues[lane]
        if queue.empty():
            return None
        _, _, envelope = await queue.get()
        try:
            if envelope.primitive.cancel_group in self._cancelled_groups:
                return self._emit(envelope, "CANCELLED")
            handler = self.handlers.get(lane)
            if handler is None:
                return self._emit(envelope, "FAILED", {"reason": "NO_HANDLER"})
            self._emit(envelope, "STARTED")
            result = await asyncio.wait_for(
                handler(envelope.primitive),
                timeout=envelope.primitive.timeout_ms / 1000.0,
            )
            return self._emit(envelope, "COMPLETED", result or {})
        except asyncio.TimeoutError:
            return self._emit(envelope, "INTERRUPTED", {"reason": "TIMEOUT"})
        except Exception as exc:  # transport errors become telemetry, not fabricated success
            return self._emit(envelope, "FAILED", {"reason": str(exc)})
        finally:
            queue.task_done()

    def _emit(self, envelope: ExecutionEnvelope, status: str, payload: Optional[Dict[str, Any]] = None) -> TelemetryEvent:
        event = TelemetryEvent(
            execution_id=envelope.execution_id,
            primitive_id=envelope.primitive.primitive_id,
            cycle_id=envelope.cycle_id,
            lane=envelope.primitive.lane,
            status=status,
            payload=payload or {},
        )
        self.telemetry.append(event)
        return event
