from __future__ import annotations

import unittest

from backend.authority.website_orb import WebsiteOrbAuthority, WebsiteOrbAuthorityError
from backend.pointer.pointer_index import route_pointer_targets
from backend.runtime.site_world import SiteWorld


def pointer(target_id: str, route: str, *, confidence: float = 0.95) -> dict:
    return {
        "target_id": target_id,
        "page_route": route,
        "target_type": "button",
        "meaning": f"target {target_id}",
        "semantic_locator": f'[data-orb-target="{target_id}"]',
        "content_fingerprint": f"fp-{target_id}",
        "anchor_strategy": "element_center",
        "confidence": confidence,
        "confidence_class": "VERIFIED" if confidence >= 0.9 else "STABLE",
        "runtime_policy": {"may_point": True},
        "status": "active",
        "pointer_health": "RECOVERED",
    }


def make_world(*, ready: bool = True, conflict: bool = False) -> SiteWorld:
    home = pointer("home-start", "/")
    pricing = pointer("pricing-buy", "/pricing")
    records = [home, pricing]
    conflict_records = []
    if conflict:
        pricing2 = pointer("pricing-buy-2", "/pricing")
        pricing2["semantic_locator"] = pricing["semantic_locator"]
        records.append(pricing2)
        conflict_records = [
            {
                "route": "/pricing",
                "semantic_locator": pricing["semantic_locator"],
                "target_ids": ["pricing-buy", "pricing-buy-2"],
            }
        ]

    pointer_map = {
        "schema": "orb_weaver.pointer_plot_map.v1",
        "record_count": len(records),
        "records": records,
    }
    navigation_world = {
        "schema": "orb_weaver.navigation_world.v1",
        "version": "abcd1234",
        "route_graph": {
            "nodes_by_route": {
                "/": {"node_id": "route_home", "route": "/", "url": "https://example.com/"},
                "/pricing": {
                    "node_id": "route_pricing",
                    "route": "/pricing",
                    "url": "https://example.com/pricing",
                },
            },
            "adjacency": {"/": ["/pricing"], "/pricing": []},
            "incoming_adjacency": {"/": [], "/pricing": ["/"]},
            "undirected_adjacency": {"/": ["/pricing"], "/pricing": ["/"]},
        },
        "localization_index": {
            "/": {"node_id": "route_home", "route": "/", "canonical_url": "https://example.com/", "scanned": True},
            "/pricing": {
                "node_id": "route_pricing",
                "route": "/pricing",
                "canonical_url": "https://example.com/pricing",
                "scanned": True,
            },
        },
        "semantic_tiles": {
            "/": {"route": "/", "node_id": "route_home", "tile_version": "11111111", "neighbor_routes": ["/pricing"]},
            "/pricing": {
                "route": "/pricing",
                "node_id": "route_pricing",
                "tile_version": "22222222",
                "neighbor_routes": ["/"],
            },
        },
        "pointer_registry": {
            "route_locator_conflicts": conflict_records,
        },
        "guidance_readiness": {
            "status": "READY" if ready and not conflict else "BLOCKED",
            "pointer_execution_available": bool(ready and not conflict),
            "blockers": [] if ready and not conflict else ["POINTER_RECOVERY_REQUIRED"],
        },
        "world_state_seed": {
            "schema": "orbot.world_state_seed.v1",
            "snapshot_id": "orbweb:example:abcd",
            "version": 42,
            "captured_at": "2026-08-21T00:00:00Z",
            "authority": "guidance",
            "pointer_map_version": 7,
            "components": ["route_graph", "pointer_registry", "semantic_tiles"],
            "forbidden_regions": [],
            "dangerous_capabilities": [],
            "system_load": "normal",
            "etag": "orbweb:example:abcd:42",
            "extra": {},
        },
        "summary": {"guidance_status": "READY" if ready and not conflict else "BLOCKED"},
    }
    pointer_by_route = {"/": [home], "/pricing": [record for record in records if record["page_route"] == "/pricing"]}
    return SiteWorld(
        site_world={"schema": "orb_weaver.website_orb.site_world.v2", "routes": {"/": {}, "/pricing": {}}},
        pointer_map=pointer_map,
        runtime_language={},
        tool_cache={"entries": []},
        navigation_world=navigation_world,
        pointer_by_route=pointer_by_route,
    )


class WebsiteOrbAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_route_local_pointer_is_permitted_but_not_executed(self):
        authority = WebsiteOrbAuthority(make_world())
        result = await authority.authorize_pointer(
            current_route="/pricing",
            query="show me pricing",
            target_id="pricing-buy",
        )
        self.assertEqual(result["status"], "PERMITTED")
        self.assertEqual(result["execution_state"], "queued_only_not_executed")
        self.assertEqual(result["target"]["target_id"], "pricing-buy")
        self.assertEqual(result["envelopes"][0]["primitive"]["lane"], "pointer")
        self.assertEqual(result["permit"]["world_etag"], result["world_etag"])

    async def test_pointer_recovery_block_remains_authoritative(self):
        authority = WebsiteOrbAuthority(make_world(ready=False))
        result = await authority.authorize_pointer(
            current_route="/pricing",
            query="show me pricing",
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "POINTER_GUIDANCE_NOT_READY")

    async def test_cross_route_navigation_requires_explicit_confirmation(self):
        authority = WebsiteOrbAuthority(make_world())
        result = await authority.authorize_navigation(
            current_route="/",
            target_route="/pricing",
            intent="take me to pricing",
            user_confirmed=False,
        )
        self.assertEqual(result["status"], "DEFERRED")
        self.assertEqual(result["execution_state"], "not_queued")
        self.assertEqual(result["planned_path"], ["/", "/pricing"])

    async def test_confirmed_scanned_navigation_is_permitted_but_not_executed(self):
        authority = WebsiteOrbAuthority(make_world())
        result = await authority.authorize_navigation(
            current_route="/",
            target_route="/pricing",
            intent="take me to pricing",
            user_confirmed=True,
        )
        self.assertEqual(result["status"], "PERMITTED")
        self.assertEqual(result["execution_state"], "queued_only_not_executed")
        self.assertEqual(result["envelopes"][0]["primitive"]["capability"], "website.navigate")

    async def test_missing_navigation_world_fails_closed(self):
        world = make_world()
        broken = SiteWorld(
            site_world=world.site_world,
            pointer_map=world.pointer_map,
            runtime_language={},
            tool_cache={"entries": []},
            navigation_world={},
            pointer_by_route=world.pointer_by_route,
        )
        authority = WebsiteOrbAuthority(broken)
        with self.assertRaises(WebsiteOrbAuthorityError):
            authority.world_state("/")

    def test_topological_route_does_not_fallback_to_home_pointer(self):
        world = make_world()
        world.pointer_by_route["/pricing"] = []
        results = route_pointer_targets(world, "/pricing", query="start")
        self.assertEqual(results, [])

    def test_conflicted_targets_are_forbidden_in_world_state(self):
        authority = WebsiteOrbAuthority(make_world(conflict=True))
        state = authority.world_state("/pricing")
        self.assertIn("pricing-buy", state.forbidden_regions)
        self.assertIn("pricing-buy-2", state.forbidden_regions)


if __name__ == "__main__":
    unittest.main()
