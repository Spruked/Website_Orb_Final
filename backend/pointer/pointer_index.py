from __future__ import annotations

from typing import Any, Dict, List

from ..runtime.site_world import SiteWorld, normalize_route


def route_pointer_targets(world: SiteWorld, route: str, query: str = "", limit: int = 5) -> List[Dict[str, Any]]:
    normalized = normalize_route(route)

    # Once a navigation-world readiness contract exists, it is authoritative
    # for whether pointer candidates may leave the knowledge layer at all.
    # This prevents legacy answer responses from surfacing pointer candidates
    # while Pointer Recovery or route/locator conflict resolution is blocking
    # runtime guidance.
    if world.navigation_world:
        readiness = world.navigation_world.get("guidance_readiness") or {}
        if readiness and readiness.get("pointer_execution_available") is not True:
            return []

    records = list(world.pointer_by_route.get(normalized, []))

    # Legacy packages without a navigation world used the home route as a broad
    # fallback. Once topological localization is available, that behavior is
    # unsafe: an ORB localized to one route must never point at a POI from a
    # different route merely because the current route has no pointer records.
    if not records and normalized != "/" and not world.has_navigation_route(normalized):
        records = list(world.pointer_by_route.get("/", []))

    records = [record for record in records if _guidance_candidate(record)]
    if query:
        records.sort(key=lambda record: _score_record(record, query), reverse=True)
    else:
        records.sort(key=lambda record: float(record.get("confidence") or 0), reverse=True)
    return records[:limit]


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
