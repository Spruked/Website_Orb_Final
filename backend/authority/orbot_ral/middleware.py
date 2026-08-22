"""TTI Validation Middleware: Core-4 -> Hard Admission -> Permit -> Execution Fabric."""
from __future__ import annotations

from typing import Any, Dict

from .admission import AdmissionRejected, HardAdmissionGate
from .core4 import evaluate_core4
from .event_bus import AsyncExecutionFabric
from .models import ActionProposal, WorldState


class TTIValidationMiddleware:
    def __init__(self, fabric: AsyncExecutionFabric, admission: HardAdmissionGate | None = None) -> None:
        self.fabric = fabric
        self.admission = admission or HardAdmissionGate()

    async def intercept_and_dispatch(self, proposal: ActionProposal, world: WorldState) -> Dict[str, Any]:
        evaluation = evaluate_core4(proposal, world)
        if evaluation.disposition != "ADMISSIBLE":
            return {
                "status": evaluation.disposition,
                "cycle_id": proposal.cycle_id,
                "evaluation": evaluation,
            }

        try:
            permit = self.admission.admit(proposal, world, evaluation)
        except AdmissionRejected as exc:
            return {
                "status": "REJECTED",
                "cycle_id": proposal.cycle_id,
                "reason": str(exc),
            }

        envelopes = await self.fabric.dispatch(proposal, permit)
        return {
            "status": "PERMITTED",
            "cycle_id": proposal.cycle_id,
            "permit": permit,
            "envelopes": envelopes,
        }
