"""Core-4: deterministic, side-effect-free evaluation over proposal + WorldState."""
from __future__ import annotations

from .models import (
    AUTHORITY_RANK,
    ActionProposal,
    Core4Evaluation,
    HumeResult,
    KantResult,
    LockeResult,
    SpinozaResult,
    WorldState,
)


def kant_check(proposal: ActionProposal, world: WorldState) -> KantResult:
    reasons: list[str] = []
    if AUTHORITY_RANK[world.authority] < AUTHORITY_RANK[proposal.required_authority]:
        reasons.append(
            f"world authority {world.authority!r} is below required {proposal.required_authority!r}"
        )
    for primitive in proposal.primitives:
        if AUTHORITY_RANK[world.authority] < AUTHORITY_RANK[primitive.required_authority]:
            reasons.append(
                f"primitive {primitive.primitive_id} requires {primitive.required_authority!r}"
            )
        if primitive.capability in world.dangerous_capabilities and world.authority != "sensitive_action":
            reasons.append(
                f"dangerous capability {primitive.capability!r} requires sensitive_action authority"
            )
    return KantResult("DENY" if reasons else "ALLOW", reasons)


def locke_check(proposal: ActionProposal, world: WorldState) -> LockeResult:
    if proposal.world_state_snapshot_id != world.snapshot_id or proposal.world_state_version != world.version:
        return LockeResult("STALE", ["proposal was formed against a superseded WorldState snapshot"])

    reasons: list[str] = []
    for primitive in proposal.primitives:
        target = primitive.arguments.get("target_pointer")
        if not target:
            continue
        if target in world.forbidden_regions:
            reasons.append(f"target {target!r} is forbidden")
        if isinstance(target, str) and target.startswith("component:"):
            component = target.split(":", 1)[1]
            if component not in world.components:
                reasons.append(f"target component {component!r} is not live")
    return LockeResult("CONTRADICTED" if reasons else "VERIFIED", reasons)


def hume_check(proposal: ActionProposal, world: WorldState) -> HumeResult:
    if proposal.confidence < 0.35:
        return HumeResult("DENY", [f"confidence {proposal.confidence:.2f} is below hard floor"])
    if proposal.ambiguity >= 0.70:
        return HumeResult("OBSERVE_MORE", [f"ambiguity {proposal.ambiguity:.2f} is too high"])
    if proposal.risk_profile in {"high", "critical"} and not proposal.user_confirmed:
        return HumeResult("ASK", ["high-risk proposal requires explicit confirmation"])
    if world.system_load == "high" and proposal.risk_profile != "low":
        return HumeResult("DEFER", ["system load is high for a non-low-risk proposal"])
    return HumeResult("PROCEED", [])


def spinoza_check(proposal: ActionProposal, world: WorldState) -> SpinozaResult:
    # Ranking signal, not a safety veto.
    coherence = 1.0 if proposal.task.strip() and proposal.intent.strip() else 0.25
    goal_alignment = 1.0 if proposal.primitives else 0.0
    continuity = 1.0 if proposal.world_state_version == world.version else 0.0
    trajectory_cost = min(1.0, max(0.0, len(proposal.primitives) / 10.0))
    reasons: list[str] = []
    if coherence < 1.0:
        reasons.append("proposal task/intent metadata is incomplete")
    if not proposal.primitives:
        reasons.append("proposal contains no executable primitives")
    return SpinozaResult(coherence, goal_alignment, continuity, trajectory_cost, reasons)


def evaluate_core4(proposal: ActionProposal, world: WorldState) -> Core4Evaluation:
    kant = kant_check(proposal, world)
    locke = locke_check(proposal, world)
    hume = hume_check(proposal, world)
    spinoza = spinoza_check(proposal, world)

    if kant.outcome == "DENY" or hume.outcome == "DENY":
        disposition = "REJECTED"
    elif locke.outcome in {"STALE", "CONTRADICTED"}:
        disposition = "REPLAN"
    elif locke.outcome == "UNVERIFIED" or hume.outcome in {"OBSERVE_MORE", "ASK", "DEFER"}:
        disposition = "DEFERRED"
    elif not proposal.primitives:
        disposition = "REPLAN"
    else:
        disposition = "ADMISSIBLE"

    return Core4Evaluation(disposition, kant, locke, hume, spinoza)
