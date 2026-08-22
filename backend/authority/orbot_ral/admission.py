"""Deterministic Hard Admission Gate and short-lived Execution Permit issuance."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .models import AUTHORITY_RANK, ActionProposal, Core4Evaluation, ExecutionPermit, WorldState


class AdmissionRejected(RuntimeError):
    pass


class HardAdmissionGate:
    def __init__(self, *, permit_ttl_ms: int = 1500) -> None:
        self.permit_ttl_ms = permit_ttl_ms

    def admit(
        self,
        proposal: ActionProposal,
        world: WorldState,
        evaluation: Core4Evaluation,
    ) -> ExecutionPermit:
        if evaluation.disposition != "ADMISSIBLE":
            raise AdmissionRejected(f"Core-4 disposition is {evaluation.disposition}")
        if proposal.world_state_snapshot_id != world.snapshot_id:
            raise AdmissionRejected("WORLD_STATE_SNAPSHOT_MISMATCH")
        if proposal.world_state_version != world.version:
            raise AdmissionRejected("WORLD_STATE_VERSION_STALE")
        if AUTHORITY_RANK[world.authority] < AUTHORITY_RANK[proposal.required_authority]:
            raise AdmissionRejected("AUTHORITY_INSUFFICIENT")
        if not proposal.primitives:
            raise AdmissionRejected("NO_PRIMITIVES")

        seen: set[str] = set()
        for primitive in proposal.primitives:
            if primitive.primitive_id in seen:
                raise AdmissionRejected("DUPLICATE_PRIMITIVE_ID")
            seen.add(primitive.primitive_id)
            if primitive.timeout_ms <= 0:
                raise AdmissionRejected(f"INVALID_TIMEOUT:{primitive.primitive_id}")
            if AUTHORITY_RANK[world.authority] < AUTHORITY_RANK[primitive.required_authority]:
                raise AdmissionRejected(f"PRIMITIVE_AUTHORITY_INSUFFICIENT:{primitive.primitive_id}")
            target = primitive.arguments.get("target_pointer")
            if target and target in world.forbidden_regions:
                raise AdmissionRejected(f"FORBIDDEN_TARGET:{primitive.primitive_id}")

        issued = datetime.now(timezone.utc)
        expires = issued + timedelta(milliseconds=self.permit_ttl_ms)
        return ExecutionPermit(
            permit_id=f"permit-{uuid4()}",
            proposal_id=proposal.proposal_id,
            cycle_id=proposal.cycle_id,
            world_state_snapshot_id=world.snapshot_id,
            world_state_version=world.version,
            world_etag=world.etag,
            issued_at=issued.isoformat(),
            expires_at=expires.isoformat(),
            approved_primitive_ids=[p.primitive_id for p in proposal.primitives],
            required_authority=proposal.required_authority,
            constraints={
                "cancel_on_world_state_change": True,
                "target_must_remain_verified": True,
            },
            tribunal_receipt={
                "kant": evaluation.kant.outcome,
                "locke": evaluation.locke.outcome,
                "hume": evaluation.hume.outcome,
                "spinoza": asdict(evaluation.spinoza),
            },
        )
