"""Deterministic telemetry reducer; executors cannot mutate arbitrary WorldState fields."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class RuntimeState:
    execution: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    speech_active: bool = False
    target_state: str = "unknown"


def reduce_telemetry(state: RuntimeState, *, event_type: str, execution_id: str, payload: Dict[str, Any]) -> RuntimeState:
    if event_type in {"QUEUED", "STARTED", "COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED", "EXPIRED"}:
        state.execution[execution_id] = {"status": event_type, **payload}
    elif event_type == "SPEECH_STARTED":
        state.speech_active = True
    elif event_type == "SPEECH_COMPLETED":
        state.speech_active = False
    elif event_type in {"TARGET_VERIFIED", "TARGET_LOST", "TARGET_REACQUIRED"}:
        state.target_state = event_type
    return state
