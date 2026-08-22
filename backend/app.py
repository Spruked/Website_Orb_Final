from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .authority.website_orb import WebsiteOrbAuthority, WebsiteOrbAuthorityError
from .config import POINTER_MAP_PATH, RUNTIME_LANGUAGE_PATH, SITE_WORLD_PATH, TOOL_CACHE_PATH
from .cognition.answer_engine import answer_from_world
from .cognition.tpc_runtime import tpc_runtime
from .dock_adapter.dockstation_adapter import DockStationAdapter
from .models import (
    AnswerRequest,
    AnswerResponse,
    DockActionRequest,
    NavigationAuthorityRequest,
    PointerAuthorityRequest,
    RouteContextResponse,
)
from .pointer.pointer_index import route_pointer_targets
from .runtime.route_lookup import lookup_route
from .runtime.site_world import SiteWorld


app = FastAPI(title="Website ORB Runtime", version="0.2.0")
WORLD = SiteWorld.load(SITE_WORLD_PATH, POINTER_MAP_PATH, RUNTIME_LANGUAGE_PATH, TOOL_CACHE_PATH)
AUTHORITY = WebsiteOrbAuthority(WORLD)
DOCK = DockStationAdapter()


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "world": WORLD.stats(),
        "dock": DOCK.status(),
        "cognition": tpc_runtime.status(),
        "authority": {
            "orbot_ral_loaded": True,
            "navigation_world_loaded": bool(WORLD.navigation_world),
            "execution_rule": "no_valid_execution_permit_no_normal_execution",
        },
    }


@app.get("/orb/tpc-status")
def tpc_status() -> dict:
    return tpc_runtime.status()


@app.get("/orb/site-world")
def site_world() -> dict:
    return {
        "identity": WORLD.site_world.get("identity"),
        "stats": WORLD.stats(),
        "route_aliases": WORLD.route_aliases,
        "navigation": WORLD.site_world.get("navigation") or {},
        "orbot_authority_contract": WORLD.site_world.get("orbot_authority_contract") or {},
    }


@app.get("/orb/route-context", response_model=RouteContextResponse)
def route_context(route: str = "/") -> RouteContextResponse:
    matched_route, record = lookup_route(WORLD, route)
    return RouteContextResponse(route=route, matched_route=matched_route, record=record)


@app.get("/orb/pointer-map")
def pointer_map(route: str = "/", limit: int = 20) -> dict:
    matched_route, _record = lookup_route(WORLD, route)
    return {
        "route": route,
        "matched_route": matched_route,
        "localized": WORLD.localize(matched_route),
        "records": route_pointer_targets(WORLD, matched_route, limit=limit),
        "guidance_readiness": WORLD.navigation_world.get("guidance_readiness") or {},
    }


@app.get("/orb/navigation/localize")
def navigation_localize(route: str = "/") -> dict:
    localized = WORLD.localize(route)
    if localized is None:
        raise HTTPException(status_code=404, detail="Route is not present in the compiled navigation world")
    return {
        "input": route,
        "localized": localized,
        "neighbors": WORLD.neighbors(localized["route"]),
        "world_etag": (WORLD.navigation_world.get("world_state_seed") or {}).get("etag"),
    }


@app.get("/orb/navigation/plan")
def navigation_plan(from_route: str, to_route: str) -> dict:
    path = WORLD.plan_route(from_route, to_route)
    return {
        "from_route": from_route,
        "to_route": to_route,
        "path": path,
        "status": "PLANNED" if path else "NO_SCANNED_PATH",
        "authority": "planning_only_no_execution_authority",
    }


@app.get("/orb/navigation/tiles")
def navigation_tiles(route: str = "/", depth: int = 1) -> dict:
    bounded_depth = max(0, min(int(depth), 2))
    return {
        "route": route,
        "neighbor_depth": bounded_depth,
        "tiles": WORLD.local_semantic_tiles(route, neighbor_depth=bounded_depth),
    }


@app.post("/orb/authority/point")
async def authority_point(payload: PointerAuthorityRequest) -> dict:
    try:
        return await AUTHORITY.authorize_pointer(
            current_route=payload.current_route,
            query=payload.query,
            target_id=payload.target_id,
            cycle_id=payload.cycle_id,
        )
    except WebsiteOrbAuthorityError as exc:
        return {"status": "BLOCKED", "reason": str(exc), "execution_state": "not_queued"}


@app.post("/orb/authority/navigate")
async def authority_navigate(payload: NavigationAuthorityRequest) -> dict:
    try:
        return await AUTHORITY.authorize_navigation(
            current_route=payload.current_route,
            target_route=payload.target_route,
            intent=payload.intent,
            user_confirmed=payload.user_confirmed,
            cycle_id=payload.cycle_id,
        )
    except WebsiteOrbAuthorityError as exc:
        return {"status": "BLOCKED", "reason": str(exc), "execution_state": "not_queued"}


@app.post("/orb/answer-text", response_model=AnswerResponse)
def answer_text(payload: AnswerRequest) -> AnswerResponse:
    # Knowledge-only answers preserve the existing deterministic/TPC fast path.
    # Pointer execution is separately admitted through /orb/authority/point.
    matched_route, route_record = lookup_route(WORLD, payload.route)
    targets = route_pointer_targets(WORLD, matched_route, payload.message, limit=5) if payload.want_pointer else []
    result = answer_from_world(payload.message, matched_route, route_record, WORLD.runtime_language, targets)
    return AnswerResponse(**result)


@app.post("/orb/dock/action")
def dock_action(payload: DockActionRequest) -> dict:
    return DOCK.call(payload.action, payload.arguments)
