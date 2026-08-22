from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object JSON at {path}")
    return data


def _load_optional_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return _load_json(path)


@dataclass(frozen=True)
class SiteWorld:
    site_world: Dict[str, Any]
    pointer_map: Dict[str, Any]
    runtime_language: Dict[str, Any]
    tool_cache: Dict[str, Any]
    navigation_world: Dict[str, Any]
    pointer_by_route: Dict[str, List[Dict[str, Any]]]

    @classmethod
    def load(
        cls,
        site_world_path: Path,
        pointer_map_path: Path,
        runtime_language_path: Path,
        tool_cache_path: Path,
        navigation_world_path: Optional[Path] = None,
    ) -> "SiteWorld":
        site_world = _load_json(site_world_path)
        pointer_map = _load_json(pointer_map_path)
        runtime_language = _load_json(runtime_language_path)
        tool_cache = _load_json(tool_cache_path)

        if navigation_world_path is None:
            navigation_world_path = site_world_path.parent / "navigation_world.json"
        navigation_world = _load_optional_json(navigation_world_path)
        if not navigation_world:
            nested = pointer_map.get("navigation_world")
            if isinstance(nested, dict):
                navigation_world = dict(nested)
        if not navigation_world:
            nested = site_world.get("navigation_world")
            if isinstance(nested, dict):
                navigation_world = dict(nested)

        pointer_by_route = _index_pointer_records(pointer_map)
        return cls(
            site_world=site_world,
            pointer_map=pointer_map,
            runtime_language=runtime_language,
            tool_cache=tool_cache,
            navigation_world=navigation_world,
            pointer_by_route=pointer_by_route,
        )

    @property
    def routes(self) -> Dict[str, Dict[str, Any]]:
        routes = self.site_world.get("routes") or {}
        return routes if isinstance(routes, dict) else {}

    @property
    def route_aliases(self) -> Dict[str, str]:
        aliases = self.site_world.get("route_aliases") or {}
        return aliases if isinstance(aliases, dict) else {}

    @property
    def navigation_nodes(self) -> Dict[str, Dict[str, Any]]:
        graph = self.navigation_world.get("route_graph") or {}
        nodes = graph.get("nodes_by_route") or {}
        return nodes if isinstance(nodes, dict) else {}

    @property
    def semantic_tiles(self) -> Dict[str, Dict[str, Any]]:
        tiles = self.navigation_world.get("semantic_tiles") or {}
        return tiles if isinstance(tiles, dict) else {}

    def has_navigation_route(self, route: str) -> bool:
        return normalize_route(route) in self.navigation_nodes

    def localize(self, route_or_url: str) -> Optional[Dict[str, Any]]:
        route = normalize_route(route_or_url)
        index = self.navigation_world.get("localization_index") or {}
        record = index.get(route) if isinstance(index, dict) else None
        if isinstance(record, dict):
            return dict(record)
        node = self.navigation_nodes.get(route)
        if isinstance(node, dict):
            return {
                "node_id": node.get("node_id"),
                "route": route,
                "canonical_url": node.get("url", ""),
                "scanned": True,
            }
        return None

    def neighbors(self, route: str, *, undirected: bool = True) -> List[str]:
        graph = self.navigation_world.get("route_graph") or {}
        key = "undirected_adjacency" if undirected else "adjacency"
        adjacency = graph.get(key) or {}
        if not isinstance(adjacency, dict):
            return []
        return [normalize_route(value) for value in adjacency.get(normalize_route(route), [])]

    def plan_route(self, start: str, target: str) -> List[str]:
        start_route = normalize_route(start)
        target_route = normalize_route(target)
        if start_route not in self.navigation_nodes or target_route not in self.navigation_nodes:
            return []
        if start_route == target_route:
            return [start_route]

        graph = self.navigation_world.get("route_graph") or {}
        adjacency = graph.get("adjacency") or {}
        if not isinstance(adjacency, dict):
            return []
        queue = deque([(start_route, [start_route])])
        visited = {start_route}
        while queue:
            route, path = queue.popleft()
            for raw_neighbor in adjacency.get(route, []):
                neighbor = normalize_route(raw_neighbor)
                if neighbor not in self.navigation_nodes or neighbor in visited:
                    continue
                if neighbor == target_route:
                    return path + [neighbor]
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
        return []

    def local_semantic_tiles(self, route: str, *, neighbor_depth: int = 1) -> List[Dict[str, Any]]:
        current = normalize_route(route)
        if current not in self.semantic_tiles:
            return []
        depth_limit = max(0, int(neighbor_depth))
        queue = deque([(current, 0)])
        visited = {current}
        ordered: List[str] = []
        while queue:
            candidate, depth = queue.popleft()
            ordered.append(candidate)
            if depth >= depth_limit:
                continue
            for neighbor in self.neighbors(candidate, undirected=True):
                if neighbor in self.semantic_tiles and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return [dict(self.semantic_tiles[item]) for item in ordered]

    def stats(self) -> Dict[str, Any]:
        nav_summary = self.navigation_world.get("summary") or {}
        return {
            "schema": self.site_world.get("schema"),
            "routes": len(self.routes),
            "pointer_records": self.pointer_map.get("record_count", len(self.pointer_map.get("records", []))),
            "tools": len(self.tool_cache.get("entries", [])),
            "runtime_contract": self.site_world.get("runtime_contract"),
            "navigation_world_schema": self.navigation_world.get("schema"),
            "navigation_world_version": self.navigation_world.get("version"),
            "topological_route_nodes": nav_summary.get("scanned_route_nodes", len(self.navigation_nodes)),
            "topological_edges": nav_summary.get("topological_edges", 0),
            "unique_entities": nav_summary.get("unique_entities", 0),
            "semantic_tiles": nav_summary.get("semantic_tiles", len(self.semantic_tiles)),
            "guidance_status": nav_summary.get("guidance_status"),
            "orbot_world_etag": (self.navigation_world.get("world_state_seed") or {}).get("etag"),
        }


def _index_pointer_records(pointer_map: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = {}
    for record in pointer_map.get("records", []):
        if not isinstance(record, dict):
            continue
        route = normalize_route(
            record.get("page_route") or record.get("page_url") or record.get("route") or record.get("page") or "/"
        )
        index.setdefault(route, []).append(record)
    return index


def normalize_route(value: Any) -> str:
    raw = str(value or "/").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        raw = "/" + raw.split("/", 3)[3] if len(raw.split("/", 3)) > 3 else "/"
    if not raw.startswith("/"):
        raw = f"/{raw}"
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    return raw.rstrip("/") or "/"
