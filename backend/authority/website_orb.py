from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional
from uuid import uuid4

from ..pointer.pointer_index import route_pointer_targets
from ..runtime.site_world import SiteWorld, normalize_route
from .orbot_ral import (
    ActionProposal,
    AsyncExecutionFabric,
    ExecutionPrimitive,
    TTIValidationMiddleware,
    WorldState,
)


class WebsiteOrbAuthorityError(RuntimeError):
    """Raised when the compiled site world cannot support bounded execution."""


class WebsiteOrbAuthority:
    """
    Adapter between Website ORB navigation/pointer intent and the vendored Orbot
    TTI/RAL authority path.

    This class does not execute browser actions. A PERMITTED result means the
    primitive has passed Core-4 + Hard Admission and is queued in the execution
    fabric. A browser executor must still verify live DOM reality, consume the
    permit before expiry, execute, and return telemetry/correspondence evidence.
    """

    def __init__(self, world: SiteWorld) -> None:
        self.world = world
        self.fabric = AsyncExecutionFabric()
        self.middleware = TTIValidationMiddleware(self.fabric)

    def localize(self, current_route: str) -> Dict[str, Any]:
        localized = self.world.localize(current_route)
        if localized is None:
            raise WebsiteOrbAuthorityError("CURRENT_ROUTE_NOT_IN_NAVIGATION_WORLD")
        return localized

    def world_state(self, current_route: str, *, authority: str = "guidance") -> WorldState:
        navigation = self.world.navigation_world
        if not navigation or navigation.get("schema") != "orb_weaver.navigation_world.v1":
            raise WebsiteOrbAuthorityError("NAVIGATION_WORLD_NOT_AVAILABLE")

        seed = navigation.get("world_state_seed") or {}
        if seed.get("schema") != "orbot.world_state_seed.v1":
            raise WebsiteOrbAuthorityError("ORBOT_WORLD_STATE_SEED_NOT_AVAILABLE")

        localized = self.localize(current_route)
        route = normalize_route(localized.get("route") or current_route)
        node_id = str(localized.get("node_id") or "")
        if not node_id:
            raise WebsiteOrbAuthorityError("ROUTE_NODE_ID_MISSING")

        route_version = _route_version(self.world, route)
        base_snapshot_id = str(seed.get("snapshot_id") or "")
        if not base_snapshot_id:
            raise WebsiteOrbAuthorityError("WORLD_STATE_SNAPSHOT_ID_MISSING")
        version = int(seed.get("version") or 0)
        if version <= 0:
            raise WebsiteOrbAuthorityError("WORLD_STATE_VERSION_INVALID")

        forbidden = set(str(value) for value in seed.get("forbidden_regions") or [] if value)
        registry = navigation.get("pointer_registry") or {}
        for conflict in registry.get("route_locator_conflicts") or []:
            if not isinstance(conflict, dict):
                continue
            forbidden.update(str(target_id) for target_id in conflict.get("target_ids") or [] if target_id)

        components = [str(value) for value in seed.get("components") or [] if value]
        components.extend([f"route:{node_id}", f"route_path:{route}"])
        components = list(dict.fromkeys(components))

        return WorldState(
            snapshot_id=f"{base_snapshot_id}:{node_id}:{route_version}",
            version=version,
            captured_at=str(seed.get("captured_at") or ""),
            authority=authority,  # type: ignore[arg-type]
            route_id=node_id,
            route_version=route_version,
            pointer_map_version=int(seed.get("pointer_map_version") or 0),
            components=components,
            forbidden_regions=sorted(forbidden),
            dangerous_capabilities=[str(value) for value in seed.get("dangerous_capabilities") or [] if value],
            system_load=str(seed.get("system_load") or "normal"),  # type: ignore[arg-type]
            extra={
                **(seed.get("extra") or {}),
                "base_world_etag": seed.get("etag"),
                "current_route": route,
                "navigation_world_version": navigation.get("version"),
                "semantic_tiles": self.world.local_semantic_tiles(route, neighbor_depth=1),
            },
        )

    async def authorize_pointer(
        self,
        *,
        current_route: str,
        query: str,
        target_id: Optional[str] = None,
        cycle_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        readiness = self.world.navigation_world.get("guidance_readiness") or {}
        if readiness.get("pointer_execution_available") is not True:
            return {
                "status": "BLOCKED",
                "reason": "POINTER_GUIDANCE_NOT_READY",
                "guidance_readiness": readiness,
            }

        localized = self.localize(current_route)
        route = normalize_route(localized["route"])
        candidates = route_pointer_targets(self.world, route, query=query, limit=12)
        if target_id:
            candidates = [candidate for candidate in candidates if candidate.get("target_id") == target_id]
        if not candidates:
            return {
                "status": "REPLAN",
                "reason": "NO_VERIFIED_ROUTE_LOCAL_POINTER_TARGET",
                "route": route,
            }

        target = candidates[0]
        target_id_value = str(target.get("target_id") or "")
        locator = str(target.get("semantic_locator") or "")
        if not target_id_value or not locator:
            return {
                "status": "REPLAN",
                "reason": "POINTER_TARGET_IDENTITY_INCOMPLETE",
                "route": route,
            }

        world_state = self.world_state(route, authority="guidance")
        confidence = max(0.0, min(1.0, float(target.get("confidence") or 0.0)))
        cycle = cycle_id or f"web-point-{uuid4().hex[:12]}"
        primitive = ExecutionPrimitive(
            primitive_id=f"pointer-{target_id_value}",
            lane="pointer",
            capability="website.pointer.guide",
            arguments={
                "target_pointer": target_id_value,
                "route": route,
                "semantic_locator": locator,
                "content_fingerprint": target.get("content_fingerprint"),
                "anchor_strategy": target.get("anchor_strategy"),
                "live_dom_verification_required": True,
                "expected_world_etag": world_state.etag,
            },
            required_authority="guidance",
            priority="normal",
            interruptible=True,
            timeout_ms=2500,
            cancel_group=f"pointer:{route}",
            expected_effects=["target_verified_live", "pointer_guidance_presented"],
        )
        proposal = ActionProposal(
            proposal_id=f"proposal-{uuid4().hex}",
            cycle_id=cycle,
            world_state_snapshot_id=world_state.snapshot_id,
            world_state_version=world_state.version,
            task="Guide the visitor to a verified interface target on the current route.",
            intent=query or str(target.get("meaning") or target_id_value),
            required_authority="guidance",
            primitives=[primitive],
            confidence=confidence,
            ambiguity=max(0.0, min(1.0, 1.0 - confidence)),
            risk_profile="low",
            reversible=True,
            user_confirmed=False,
        )
        result = await self.middleware.intercept_and_dispatch(proposal, world_state)
        return {
            **_serializable(result),
            "route": route,
            "target": {
                "target_id": target_id_value,
                "meaning": target.get("meaning"),
                "semantic_locator": locator,
                "confidence": confidence,
                "confidence_class": target.get("confidence_class"),
                "live_dom_verification_required": True,
            },
            "world_etag": world_state.etag,
            "execution_state": "queued_only_not_executed" if result.get("status") == "PERMITTED" else "not_queued",
        }

    async def authorize_navigation(
        self,
        *,
        current_route: str,
        target_route: str,
        intent: str,
        user_confirmed: bool,
        cycle_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        start = normalize_route(current_route)
        target = normalize_route(target_route)
        self.localize(start)
        self.localize(target)
        path = self.world.plan_route(start, target)
        if not path:
            return {
                "status": "REPLAN",
                "reason": "NO_SCANNED_TOPOLOGICAL_PATH",
                "start_route": start,
                "target_route": target,
            }

        world_state = self.world_state(start, authority="action")
        cycle = cycle_id or f"web-nav-{uuid4().hex[:12]}"
        primitive = ExecutionPrimitive(
            primitive_id=f"navigate-{uuid4().hex[:12]}",
            lane="tool",
            capability="website.navigate",
            arguments={
                "start_route": start,
                "target_route": target,
                "planned_path": path,
                "expected_world_etag": world_state.etag,
                "explicit_confirmation_required": True,
            },
            required_authority="action",
            priority="task_critical",
            interruptible=True,
            timeout_ms=5000,
            cancel_group=f"navigation:{world_state.route_id}",
            expected_effects=[f"route_changed:{target}"],
        )
        proposal = ActionProposal(
            proposal_id=f"proposal-{uuid4().hex}",
            cycle_id=cycle,
            world_state_snapshot_id=world_state.snapshot_id,
            world_state_version=world_state.version,
            task="Navigate the visitor across the scanned website topology.",
            intent=intent,
            required_authority="action",
            primitives=[primitive],
            confidence=1.0,
            ambiguity=0.0,
            risk_profile="high",
            reversible=True,
            user_confirmed=user_confirmed,
        )
        result = await self.middleware.intercept_and_dispatch(proposal, world_state)
        return {
            **_serializable(result),
            "start_route": start,
            "target_route": target,
            "planned_path": path,
            "world_etag": world_state.etag,
            "execution_state": "queued_only_not_executed" if result.get("status") == "PERMITTED" else "not_queued",
        }


def _route_version(world: SiteWorld, route: str) -> int:
    tile = world.semantic_tiles.get(normalize_route(route)) or {}
    token = str(tile.get("tile_version") or world.navigation_world.get("version") or "1")
    hexadecimal = "".join(character for character in token if character.lower() in "0123456789abcdef")
    if hexadecimal:
        return max(1, int(hexadecimal[:8], 16))
    return 1


def _serializable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serializable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    return value
