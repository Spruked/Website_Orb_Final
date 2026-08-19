"""
orb/vault/a_priori/loader.py
Loads A Priori vault data from Orb Weaver output.
Reads: site.skg, catalog.json, ontology.json, policy.json, qa.json
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional
import json
from pathlib import Path

from ..shared.types import (
    CatalogEntry, Entity, Relation, EntityType, RelationType,
    QACorrespondence, PolicyRule, VaultTimestamp, IntentType, Confidence
)

from .catalog_cognitive import CatalogCognitiveState
from .ontology_cognitive import OntologyCognitiveState
from .qa_cognitive import QACognitiveState


class PrioriLoader:
    """
    Loads settled truth from Orb Weaver compiled output.
    Site-agnostic: discovers files at runtime.
    """

    def __init__(self, weaver_output_dir: str):
        self.output_dir = Path(weaver_output_dir)

    def load_all(self) -> Dict[str, Any]:
        return {
            "catalog": self.load_catalog(),
            "ontology": self.load_ontology(),
            "qa": self.load_qa(),
            "policies": self.load_policies(),
        }

    def load_catalog(self) -> CatalogCognitiveState:
        state = CatalogCognitiveState()
        catalog_file = self.output_dir / "catalog.json"
        if not catalog_file.exists():
            for alt in ["products.json", "inventory.json", "site_catalog.json"]:
                alt_path = self.output_dir / alt
                if alt_path.exists():
                    catalog_file = alt_path
                    break

        if catalog_file.exists():
            with open(catalog_file, "r") as f:
                data = json.load(f)
            for item in data.get("entries", data if isinstance(data, list) else []):
                entry = CatalogEntry(
                    entry_id=item.get("product_id", item.get("id", f"cat_{hash(str(item))}")),
                    entry_type=EntityType.PRODUCT if "price" in item else EntityType.SERVICE,
                    name=item.get("name", "Unknown"),
                    sku=item.get("sku"),
                    current_price=item.get("current_price"),
                    sale_price=item.get("sale_price"),
                    currency=item.get("currency", "USD"),
                    variant=item.get("variant"),
                    availability=item.get("availability"),
                    specifications=item.get("specifications", {}),
                    source_url=item.get("source_url", ""),
                    source_element=item.get("source_element", ""),
                    crawl_version=item.get("crawl_version", ""),
                    owner_verified=item.get("owner_verified", False),
                )
                state.add_entry(entry)
        return state

    def load_ontology(self) -> OntologyCognitiveState:
        state = OntologyCognitiveState()
        ontology_file = self.output_dir / "ontology.json"
        if not ontology_file.exists():
            ontology_file = self.output_dir / "site.skg"

        if ontology_file.exists():
            with open(ontology_file, "r") as f:
                data = json.load(f)
            for e_data in data.get("entities", []):
                entity = Entity(
                    entity_id=e_data.get("id", e_data.get("entity_id", "")),
                    entity_type=EntityType[e_data.get("type", "CATEGORY").upper()],
                    canonical_name=e_data.get("name", e_data.get("canonical_name", "")),
                    aliases=e_data.get("aliases", []),
                    attributes=e_data.get("attributes", {}),
                    source_url=e_data.get("source_url", ""),
                )
                state.add_entity(entity)
            for r_data in data.get("relations", []):
                relation = Relation(
                    relation_id=r_data.get("id", r_data.get("relation_id", "")),
                    relation_type=RelationType[r_data.get("type", "BELONGS_TO").upper()],
                    source_id=r_data.get("source", r_data.get("source_id", "")),
                    target_id=r_data.get("target", r_data.get("target_id", "")),
                    weight=r_data.get("weight", 1.0),
                    attributes=r_data.get("attributes", {}),
                )
                state.add_relation(relation)
        return state

    def load_qa(self) -> QACognitiveState:
        state = QACognitiveState()
        qa_file = self.output_dir / "qa.json"
        if not qa_file.exists():
            qa_file = self.output_dir / "correspondences.json"

        if qa_file.exists():
            with open(qa_file, "r") as f:
                data = json.load(f)
            for q_data in data.get("qa_pairs", data if isinstance(data, list) else []):
                qa = QACorrespondence(
                    qa_id=q_data.get("id", q_data.get("qa_id", "")),
                    question_patterns=q_data.get("questions", q_data.get("question_patterns", [])),
                    answer_template=q_data.get("answer", q_data.get("answer_template", "")),
                    answer_variables=q_data.get("variables", []),
                    intent=IntentType[q_data.get("intent", "GENERAL").upper()],
                    source=q_data.get("source", "owner"),
                )
                state.add_qa(qa)
        return state

    def load_policies(self) -> List[PolicyRule]:
        policies = []
        policy_file = self.output_dir / "policies.json"
        if policy_file.exists():
            with open(policy_file, "r") as f:
                data = json.load(f)
            for p_data in data.get("policies", data if isinstance(data, list) else []):
                policy = PolicyRule(
                    rule_id=p_data.get("id", p_data.get("rule_id", "")),
                    category=p_data.get("category", "general"),
                    statement=p_data.get("statement", ""),
                    conditions=p_data.get("conditions", []),
                    exceptions=p_data.get("exceptions", []),
                    priority=p_data.get("priority", 5),
                    source=p_data.get("source", "owner"),
                )
                policies.append(policy)
        return policies
