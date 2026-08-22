from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
COMPILED = PACKAGE_ROOT / "compiled_orb"


def main() -> None:
    runtime_language = load_json(COMPILED / "runtime_language.json")
    pointer_map = load_json(COMPILED / "pointer_plot_map.json")
    tool_cache = load_json(COMPILED / "tool_cache.json")
    latest_context = load_json(COMPILED / "latest_context.json")
    self_scan = load_json(COMPILED / "self_scan_summary.json")
    navigation_world = load_optional_json(COMPILED / "navigation_world.json")
    if not navigation_world and isinstance(pointer_map.get("navigation_world"), dict):
        navigation_world = dict(pointer_map["navigation_world"])

    records_by_route = group_records(pointer_map.get("records", []))
    route_hints = runtime_language.get("route_hints") or {}
    nav_nodes = ((navigation_world.get("route_graph") or {}).get("nodes_by_route") or {}) if navigation_world else {}
    routes = sorted(
        set(records_by_route)
        | {normalize_route(value) for value in route_hints.values()}
        | {normalize_route(route) for route in nav_nodes}
    )
    if "/" not in routes:
        routes.insert(0, "/")

    route_records = {
        route: build_route_record(
            route,
            records_by_route.get(route, []),
            runtime_language,
            latest_context,
            navigation_world,
        )
        for route in routes
    }

    navigation_summary = navigation_world.get("summary") or {}
    has_navigation_world = bool(navigation_world.get("schema"))
    world = {
        "schema": "orb_weaver.website_orb.site_world.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_contract": (
            "precompiled_skg_plus_topological_navigation"
            if has_navigation_world
            else "precompiled_skg_lookup_only"
        ),
        "site": {
            "name": runtime_language.get("site_name", "Orb Weaver"),
            "domain": runtime_language.get("domain", "orbweaver.spruked.com"),
            "canonical_url": runtime_language.get("canonical_url", "https://orbweaver.spruked.com/"),
        },
        "identity": runtime_language.get("first_person_identity", {}),
        "site_summary": runtime_language.get("site_summary", ""),
        "primary_user_tasks": runtime_language.get("primary_user_tasks", []),
        "guiderails": runtime_language.get("allowed_guidance", []),
        "answer_boundaries": runtime_language.get("answer_boundaries", []),
        "route_aliases": {normalize_route(value): normalize_route(value) for value in route_hints.values()},
        "routes": route_records,
        "navigation": {
            "available": has_navigation_world,
            "schema": navigation_world.get("schema"),
            "version": navigation_world.get("version"),
            "summary": navigation_summary,
            "world_state_seed": navigation_world.get("world_state_seed") or {},
            "artifact": "navigation_world.json" if has_navigation_world else None,
            "semantic_context_policy": "current_tile_plus_bounded_neighbors",
            "planning_policy": "topological_path_planning_does_not_authorize_execution",
        },
        "orbot_authority_contract": {
            "required_for_execution_lanes": ["pointer", "motion", "tool"],
            "knowledge_only_answer_lane": "does_not_require_execution_permit",
            "sequence": [
                "world_state",
                "ral_proposal",
                "core4",
                "hard_admission",
                "execution_permit",
                "executor",
                "telemetry_correspondence",
            ],
            "hard_rule": "no_valid_execution_permit_no_normal_execution",
        },
        "source_inventory": {
            "pointer_records": pointer_map.get("record_count", len(pointer_map.get("records", []))),
            "routes_with_pointers": len(records_by_route),
            "tool_cache_entries": len(tool_cache.get("entries", [])),
            "pages_scanned": self_scan.get("pages_scanned"),
            "orb_ready_score": latest_context.get("orb_ready_score"),
            "topological_route_nodes": navigation_summary.get("scanned_route_nodes", 0),
            "topological_edges": navigation_summary.get("topological_edges", 0),
            "unique_entities": navigation_summary.get("unique_entities", 0),
            "entity_relationships": navigation_summary.get("entity_relationships", 0),
            "semantic_tiles": navigation_summary.get("semantic_tiles", 0),
            "route_locator_conflicts": navigation_summary.get("route_locator_conflicts", 0),
            "navigation_guidance_status": navigation_summary.get("guidance_status"),
        },
    }

    out = COMPILED / "site_world.json"
    out.write_text(json.dumps(world, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(
        f"routes={len(route_records)} "
        f"pointer_records={world['source_inventory']['pointer_records']} "
        f"navigation_world={has_navigation_world}"
    )


def build_route_record(
    route: str,
    records: List[Dict[str, Any]],
    runtime_language: Dict[str, Any],
    latest_context: Dict[str, Any],
    navigation_world: Dict[str, Any],
) -> Dict[str, Any]:
    top = sorted(records, key=lambda record: float(record.get("confidence") or 0), reverse=True)
    top_value = top[:8]
    secondary = top[8:24]
    route_name = route.strip("/") or "home"
    page_purpose = infer_page_purpose(route, runtime_language)
    keywords = sorted(set(words_from_route(route)) | set(words_from_records(top_value)))

    graph = navigation_world.get("route_graph") or {}
    nav_nodes = graph.get("nodes_by_route") or {}
    nav_node = nav_nodes.get(route) if isinstance(nav_nodes, dict) else None
    nav_node = nav_node if isinstance(nav_node, dict) else {}
    adjacency = graph.get("adjacency") or {}
    incoming = graph.get("incoming_adjacency") or {}
    tiles = navigation_world.get("semantic_tiles") or {}
    tile = tiles.get(route) if isinstance(tiles, dict) else None
    tile = tile if isinstance(tile, dict) else {}
    readiness = navigation_world.get("guidance_readiness") or {}
    route_readiness = readiness.get("route_status") or {}
    route_readiness = route_readiness.get(route) if isinstance(route_readiness, dict) else None

    return {
        "route": route,
        "page_purpose": page_purpose,
        "summary": infer_summary(route, page_purpose, runtime_language),
        "keywords": keywords[:40],
        "topological_localization": {
            "node_id": nav_node.get("node_id"),
            "route_class": nav_node.get("route_class"),
            "outgoing_neighbors": list(adjacency.get(route, [])) if isinstance(adjacency, dict) else [],
            "incoming_neighbors": list(incoming.get(route, [])) if isinstance(incoming, dict) else [],
            "entity_ids": nav_node.get("entity_ids", []),
            "semantic_tile_version": tile.get("tile_version"),
            "guidance_readiness": route_readiness or {},
        },
        "target_tiering": {
            "top_value_targets": summarize_targets(top_value),
            "secondary_targets": summarize_targets(secondary),
            "full_route_scoped_targets": [record.get("target_id") for record in records if record.get("target_id")],
        },
        "permitted_action_boundaries": [
            "voice_answer",
            "point_only_after_live_dom_resolution_and_execution_permit",
            "cross_page_navigation_requires_explicit_confirmation_and_execution_permit",
            "no_site_modification_without_owner_confirmation",
        ],
        "doctrine_conditions": {
            "canonical_hash_status": "source_package_reference",
            "conditions": [
                "localize_current_route_before_pointer_lookup",
                "resolve_pointer_before_visual_guidance",
                "voice_only_when_target_unresolved",
                "route_planning_never_equals_execution_authority",
                "do_not_claim_desktop_tools_by_default",
            ],
        },
        "tpc_output_classes": {
            "precleared": ["answer", "explain_current_route"],
            "requires_execution_permit": ["point_if_resolved", "navigate_cross_page", "site_modification", "desktop_tool"],
        },
        "playbooks": playbooks_for_route(route, route_name),
        "guiderails": runtime_language.get("allowed_guidance", []),
        "answer_boundaries": runtime_language.get("answer_boundaries", []),
        "context_refs": {
            "latest_context_keys": list(latest_context.keys()),
            "navigation_world": "navigation_world.json" if navigation_world else None,
            "semantic_tile_route": route if tile else None,
        },
    }


def infer_page_purpose(route: str, runtime_language: Dict[str, Any]) -> str:
    if route == "/":
        return "Explain Orb Weaver and guide visitors toward preflight, demo, marketplace, or account paths."
    if "preflight" in route:
        return "Help visitors start or understand public website readiness checks."
    if "marketplace" in route:
        return "Help visitors compare Website ORB products, packs, diagnostics, skins, and upgrades."
    if "demo" in route:
        return "Demonstrate Website ORB behavior and Orb Weaver capabilities."
    if "login" in route:
        return "Explain account access for saved scans, reports, audits, and owner controls."
    if "privacy" in route or "terms" in route:
        return "Explain policy and trust boundaries for Orb Weaver visitors."
    return runtime_language.get("orb_role", "Help visitors understand Orb Weaver.")


def infer_summary(route: str, page_purpose: str, runtime_language: Dict[str, Any]) -> str:
    if route == "/":
        return runtime_language.get("site_summary", page_purpose)
    return page_purpose


def playbooks_for_route(route: str, route_name: str) -> List[str]:
    playbooks = ["answer_short_for_tts", "pointer_resolve_before_ping", "localize_before_guidance"]
    if route != "/":
        playbooks.append(f"route_specific_guidance:{route_name}")
    if "marketplace" in route:
        playbooks.append("explain_product_boundary")
    if "preflight" in route:
        playbooks.append("preflight_readiness_guidance")
    return playbooks


def summarize_targets(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "target_id": record.get("target_id"),
            "type": record.get("target_type"),
            "meaning": record.get("meaning"),
            "confidence": record.get("confidence"),
            "confidence_class": record.get("confidence_class"),
            "allowed_actions": record.get("allowed_actions", []),
            "must_verify_live_dom": True,
        }
        for record in records
    ]


def group_records(records: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        if not isinstance(record, dict):
            continue
        grouped[normalize_route(record.get("page_route") or record.get("page_url") or "/")].append(record)
    return dict(grouped)


def words_from_route(route: str) -> List[str]:
    return [part for part in route.replace("-", " ").replace("/", " ").split() if len(part) > 2]


def words_from_records(records: Iterable[Dict[str, Any]]) -> List[str]:
    words: List[str] = []
    for record in records:
        for field in ("meaning", "target_type"):
            words.extend(str(record.get(field, "")).replace(":", " ").split())
        for alias in record.get("direct_aliases") or []:
            words.extend(str(alias).split())
    return [word.lower().strip() for word in words if len(word.strip()) > 2]


def normalize_route(value: Any) -> str:
    raw = str(value or "/").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        parts = raw.split("/", 3)
        raw = "/" + parts[3] if len(parts) > 3 else "/"
    if not raw.startswith("/"):
        raw = f"/{raw}"
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    return raw.rstrip("/") or "/"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object JSON at {path}")
    return data


def load_optional_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


if __name__ == "__main__":
    main()
