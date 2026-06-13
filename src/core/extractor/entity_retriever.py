"""
Task 5.6 — EntityRetriever: scores items by semantic memory entity match.

Provides an entity-based signal for RRF fusion by querying the MemoryHub
for user-specific semantic facts and scoring each candidate item based
on how well it matches known entities.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EntityRetriever:
    """Entity match signal for RAG v2.

    Queries the MemoryHub's semantic store for entities that match the
    user's query and scores each candidate item based on entity overlap.

    Args:
        memory_hub: A MemoryHub instance (or None, in which case all
            scores default to 0.0).
    """

    def __init__(self, memory_hub: Optional[Any] = None):
        self._memory_hub = memory_hub

    def retrieve(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 20,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Score candidates by entity match from semantic memory.

        For each candidate item, computes a score based on how well
        known entities from MemoryHub match the item name.

        Args:
            query: The user's search query.
            candidates: List of candidate item names.
            top_k: Maximum results (default 20).
            user_id: Optional user ID to scope entity queries.

        Returns:
            List of dicts with keys:
                - ``item_name``: Candidate item name.
                - ``score``: Entity match score (0.0–1.0).
            Scores are 0.0 when no memory_hub is available or no
            matching entities are found.
        """
        if not self._memory_hub or not candidates:
            return [{"item_name": c, "score": 0.0} for c in candidates]

        if not query or not query.strip():
            return [{"item_name": c, "score": 0.0} for c in candidates]

        # Query semantic memory
        query_lower = query.lower()

        try:
            entities = self._memory_hub.query(
                memory_type="semantic",
                query_text=query,
                top_k=5,
                user_id=user_id or "",
            )
        except Exception as e:
            logger.warning("EntityRetriever: memory query failed: %s", e)
            entities = []

        # Build entity value set for matching
        entity_values: List[str] = []
        for ent in entities:
            val = ent.get("value", "").lower().strip()
            if val:
                entity_values.append(val)

        # Score each candidate
        results: List[Dict[str, Any]] = []
        for candidate in candidates:
            score = 0.0
            candidate_lower = candidate.lower()

            for entity_val in entity_values:
                # Exact substring match
                if entity_val in candidate_lower or candidate_lower in entity_val:
                    score = max(score, 0.8)
                # Partial token overlap
                elif any(
                    token in candidate_lower and len(token) > 2
                    for token in entity_val.split()
                ):
                    score = max(score, 0.5)

            results.append({"item_name": candidate, "score": score})

        # Sort by score desc
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
