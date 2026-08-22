from __future__ import annotations

from typing import Any, Dict, List

from ..runtime.site_world import SiteWorld, normalize_route


def route_pointer_targets(world: SiteWorld, route: str, query: str = "", limit: int = 5) -> List[Dict[str, Any]]:
    normalized = normalize_route(route)

    records = list(world.pointer_by_route.get(normalized, []))

    # Legacy packages without a navigation world used the home route as a broad
    # fallback. Once topological localization is available, that behavior is
    # unsafe: an ORB localized to one route must never point at a POI from a
    # different route merely because the current route has no pointer records.
    if not records and normalized != "/" and not world.has_navigation_route(normalized):
        records = list(world.pointer_by_route.get("/", []))

    records = [
        record
        for record in records
        if _guidance_candidate(record)
        and _navigation_guidance_candidate(world, normalized, record)
    ]
    if query:
        records.sort(key=lambda record: _score_record(record, query), reverse=True)
    else:
        records.sort(key=lambda record: float(record.get("confidence") or 0), reverse=True)
    return records[:limit]


def _navigation_guidance_candidate(
    world: SiteWorld,
    route: str,
    record: Dict[str, Any],
) -> bool:
    """Apply navigation-world authority only to this route/target identity."""
    navigation = world.navigation_world or {}
    if not navigation:
        return True

    readiness = navigation.get("guidance_readiness") or {}
    route_status = readiness.get("route_status") or {}
    state = route_status.get(route) if isinstance(route_status, dict) else None

    # Route-local readiness may fail closed. Global map readiness may not veto
    # an otherwise verified target on this route.
    if isinstance(state, dict) and state.get("status") == "NO_ELIGIBLE_TARGET":
        return False

    registry = navigation.get("pointer_registry") or {}
    if not isinstance(registry, dict):
        registry = {}

    target_id = str(record.get("target_id") or "")

    conflicted_target_ids = {
        str(value)
        for value in registry.get("conflicted_target_ids") or []
        if value
    }

    # Backward compatibility with navigation worlds created before the
    # flattened conflicted_target_ids field existed.
    for conflict in registry.get("route_locator_conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        conflicted_target_ids.update(
            str(value)
            for value in conflict.get("target_ids") or []
            if value
        )

    if target_id and target_id in conflicted_target_ids:
        return False

    pois = registry.get("pois") or {}
    poi = pois.get(target_id) if isinstance(pois, dict) and target_id else None

    if isinstance(poi, dict):
        if poi.get("identity_conflict") is True:
            return False
        if poi.get("guidance_eligible") is False:
            return False

        poi_route = poi.get("route")
        if poi_route and normalize_route(poi_route) != route:
            return False

    return True


def _guidance_candidate(record: Dict[str, Any]) -> bool:
    if record.get("status") not in (None, "active"):
        return False
    confidence_class = str(record.get("confidence_class") or "").upper()
    policy = record.get("runtime_policy") if isinstance(record.get("runtime_policy"), dict) else {}
    if confidence_class and confidence_class not in {"VERIFIED", "STABLE"}:
        return False
    if policy and policy.get("may_point") is not True:
        return False
    if str(record.get("pointer_health") or "") in {"OWNER_REJECTED", "DEPRECATED", "REMOVED"}:
        return False
    if record.get("finding_subreason") == "owner_rejected_pointer_identity":
        return False
    return True


def _score_record(record: Dict[str, Any], query: str) -> float:
    text = " ".join(
        str(record.get(field, ""))
        for field in ("target_id", "meaning", "target_type", "semantic_locator")
    ).lower()
    aliases = record.get("direct_aliases") or record.get("intent_aliases") or []
    text += " " + " ".join(str(alias).lower() for alias in aliases)
    words = [part for part in query.lower().split() if len(part) > 2]
    keyword_score = sum(1 for word in words if word in text)
    return keyword_score + float(record.get("confidence") or 0)
