"""Typed contracts for the Orbot TTI / RAL authority path."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

AuthorityTier = Literal["none", "truth", "guidance", "action", "sensitive_action"]
RiskProfile = Literal["low", "medium", "high", "critical"]
ExecutionLane = Literal["tool", "speech", "motion", "pointer"]
Priority = Literal["emergency_stop", "safety", "user_interrupt", "task_critical", "normal", "ambient"]
Disposition = Literal["ADMISSIBLE", "REJECTED", "DEFERRED", "REPLAN"]

KantOutcome = Literal["ALLOW", "DENY"]
LockeOutcome = Literal["VERIFIED", "UNVERIFIED", "STALE", "CONTRADICTED"]
HumeOutcome = Literal["PROCEED", "OBSERVE_MORE", "ASK", "DEFER", "DENY"]

AUTHORITY_RANK: Dict[str, int] = {
    "none": 0,
    "truth": 1,
    "guidance": 2,
    "action": 3,
    "sensitive_action": 4,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WorldState:
    snapshot_id: str
    version: int
    captured_at: str
    authority: AuthorityTier = "guidance"
    route_id: str = ""
    route_version: int = 0
    pointer_map_version: int = 0
    components: List[str] = field(default_factory=list)
    forbidden_regions: List[str] = field(default_factory=list)
    dangerous_capabilities: List[str] = field(default_factory=list)
    system_load: Literal["low", "normal", "high"] = "normal"
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def etag(self) -> str:
        return f"{self.snapshot_id}:{self.version}"


@dataclass(frozen=True)
class ExecutionDependency:
    condition: str
    primitive_id: Optional[str] = None


@dataclass(frozen=True)
class ExecutionPrimitive:
    primitive_id: str
    lane: ExecutionLane
    capability: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    required_authority: AuthorityTier = "none"
    priority: Priority = "normal"
    interruptible: bool = True
    timeout_ms: int = 5000
    cancel_group: str = "default"
    dependencies: List[ExecutionDependency] = field(default_factory=list)
    expected_effects: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    cycle_id: str
    world_state_snapshot_id: str
    world_state_version: int
    task: str
    intent: str
    required_authority: AuthorityTier
    primitives: List[ExecutionPrimitive]
    confidence: float = 0.8
    ambiguity: float = 0.0
    risk_profile: RiskProfile = "low"
    reversible: bool = True
    user_confirmed: bool = False


@dataclass(frozen=True)
class KantResult:
    outcome: KantOutcome
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LockeResult:
    outcome: LockeOutcome
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class HumeResult:
    outcome: HumeOutcome
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SpinozaResult:
    coherence_score: float
    goal_alignment_score: float
    continuity_score: float
    trajectory_cost: float
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Core4Evaluation:
    disposition: Disposition
    kant: KantResult
    locke: LockeResult
    hume: HumeResult
    spinoza: SpinozaResult


@dataclass(frozen=True)
class ExecutionPermit:
    permit_id: str
    proposal_id: str
    cycle_id: str
    world_state_snapshot_id: str
    world_state_version: int
    world_etag: str
    issued_at: str
    expires_at: str
    approved_primitive_ids: List[str]
    required_authority: AuthorityTier
    constraints: Dict[str, Any]
    tribunal_receipt: Dict[str, Any]
    hard_admission: Literal["PASS"] = "PASS"
