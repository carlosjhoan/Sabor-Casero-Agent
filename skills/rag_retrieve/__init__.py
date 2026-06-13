"""
rag-retrieve skill — RAG v2 pipeline (Task 5.12).

Wraps the full RAG v2 pipeline (dense + BM25 + entity + OWL → RRF →
cross-encoder → ontology gate) for the skill-based architecture.
"""
from typing import Any, Optional

from src.engine.skill_base import BaseSkill
from src.engine.stage_result import SkillResult


class Skill(BaseSkill):
    """RAG v2 retrieval skill."""
    name = "rag-retrieve"
    version = "0.1.0"

    def load(self, context: Any) -> None:
        """Store references to RAG v2 components."""
        self._owl_client = context.get("owl_client") if context else None
        self._owl_signal = context.get("owl_signal") if context else None
        self._memory_hub = context.get("memory_hub") if context else None
        self._retriever = context.get("retriever") if context else None
        self._bm25 = context.get("bm25_retriever") if context else None
        self._entity = context.get("entity_retriever") if context else None
        self._rrf_fuser = context.get("rrf_fuser") if context else None
        self._cross_encoder = context.get("cross_encoder") if context else None
        self._ontology_gate = context.get("ontology_gate") if context else None

    async def run(self, input_data: Any) -> SkillResult:
        """Run RAG v2 retrieval pipeline.

        Input::
            {
                "query": str,          # User's search query
                "candidates": list,    # Candidate item names
                "details": list,       # Optional topic details
            }

        Returns::
            {
                "items": list,         # Ranked and validated items
                "pipeline": str,       # "full" | "fast_path" | "error"
            }
        """
        try:
            query = input_data.get("query", "")
            candidates = input_data.get("candidates", [])
            details = input_data.get("details", [])

            if not query or not candidates:
                return SkillResult.ok(
                    value={"items": [], "pipeline": "none"},
                    skill_name=self.name,
                    skill_version=self.version,
                )

            # Delegate to the composite retriever's v2 pipeline if available
            if self._retriever and hasattr(self._retriever, "retrieve_v2"):
                results = await self._retriever.retrieve_v2(
                    query=query,
                    candidates=candidates,
                    details=details,
                )
                items = [
                    {
                        "item_name": r.item_name,
                        "rrf_score": r.rrf_score,
                        "rerank_score": r.rerank_score,
                        "signal_count": r.signal_count,
                        "sources": r.sources,
                        "gate_outcome": r.gate_outcome,
                    }
                    for r in results
                ]
                pipeline = "full"
            else:
                # Fallback: basic OWL scoring only
                if self._owl_signal:
                    scores = self._owl_signal.score_candidates(query, candidates)
                    items = [
                        {
                            "item_name": item,
                            "score": result.score,
                            "match_type": result.match_type,
                        }
                        for item, result in scores.items()
                    ]
                    items.sort(key=lambda x: x.get("score", 0), reverse=True)
                    pipeline = "owl_only"
                else:
                    items = [{"item_name": c, "score": 0.0} for c in candidates]
                    pipeline = "none"

            return SkillResult.ok(
                value={"items": items, "pipeline": pipeline},
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
        self._memory_hub = None
        self._retriever = None
        self._bm25 = None
        self._entity = None
        self._rrf_fuser = None
        self._cross_encoder = None
        self._ontology_gate = None
