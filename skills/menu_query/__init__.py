"""
menu-query skill — OWL signal with ontology validation (Task 5.11).

Wraps the OwlSignal + OntologyValidationGate for the skill-based architecture.
Provides deterministic menu query responses using SPARQL.
"""
from typing import Any, Optional

from src.engine.skill_base import BaseSkill
from src.engine.stage_result import SkillResult


class Skill(BaseSkill):
    """Ontology-driven menu query skill."""
    name = "menu-query"
    version = "0.1.0"

    def load(self, context: Any) -> None:
        """Store references to OWL client and signal."""
        self._owl_client = context.get("owl_client") if context else None
        self._owl_signal = context.get("owl_signal") if context else None
        self._ontology_gate = context.get("ontology_gate") if context else None

    async def run(self, input_data: Any) -> SkillResult:
        """Run menu query against the OWL ontology.

        Input::
            {
                "query": str,          # User's natural language query
                "candidates": list,    # Candidate item names
            }

        Returns::
            {
                "items": list,         # Ranked items with scores
                "match_type": str,     # "exact" | "partial" | "none"
            }
        """
        try:
            query = input_data.get("query", "")
            candidates = input_data.get("candidates", [])

            if not query:
                return SkillResult.ok(
                    value={"items": [], "match_type": "none"},
                    skill_name=self.name,
                    skill_version=self.version,
                )

            if not self._owl_signal:
                return SkillResult.fail(
                    skill_name=self.name,
                    skill_version=self.version,
                    error=RuntimeError("OwlSignal not configured"),
                )

            # Phase 1: OWL scoring
            scores = self._owl_signal.score_candidates(query, candidates)

            items = []
            for item_name, result in scores.items():
                items.append({
                    "item_name": item_name,
                    "score": result.score,
                    "match_type": result.match_type,
                    "evidence": result.evidence,
                })

            # Sort by score descending
            items.sort(key=lambda x: x["score"], reverse=True)

            # Determine overall match type
            match_types = {i["match_type"] for i in items}
            if "exact" in match_types:
                overall = "exact"
            elif "partial" in match_types:
                overall = "partial"
            elif match_types - {"none"}:
                overall = "related"
            else:
                overall = "none"

            return SkillResult.ok(
                value={"items": items, "match_type": overall},
                skill_name=self.name,
                skill_version=self.version,
            )

        except Exception as e:
            return SkillResult.fail(
                skill_name=self.name,
                skill_version=self.version,
                error=e,
            )

    def unload(self) -> None:
        self._owl_client = None
        self._owl_signal = None
        self._ontology_gate = None
