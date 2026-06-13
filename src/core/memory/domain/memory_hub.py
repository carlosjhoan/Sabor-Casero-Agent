"""
MemoryHub: unified facade over all memory stores.

Provides a single entry point for the pipeline to store, query, and recall
across semantic, episodic, and procedural memory. New stores are added as
properties — the caller never needs to know which store implements a
particular operation.

Current stores:
- ``semantic`` (:class:`~src.core.memory.domain.semantic_store.SemanticStore`) —
  structured facts and user preferences.

Future stores (P5/P6):
- ``episodic`` — conversation episode capture with time-range/topic/entity
  query.
- ``procedural`` — pattern learner (co-occurrence rules).
- ``cache`` — semantic cache for LLM response reuse.
"""
import logging
from typing import Any, Dict, List, Optional, Union

from src.core.memory.domain.models_memory import (
    Entity,
    RecallContext,
    RecallResult,
)
from src.core.memory.domain.semantic_store import SemanticStore
from src.core.memory.infrastructure.chroma_memory_repository import (
    ChromaMemoryRepository,
)

logger = logging.getLogger(__name__)


class MemoryHub:
    """
    Facade over all memory stores.

    Usage::

        hub = MemoryHub()
        entity = Entity(entity_type="protein_pref", value="carne asada", ...)
        hub.store(entity)
        hub.query("semantic", "carne")
        result = hub.recall(RecallContext(query="carne", user_id="u1"))
    """

    def __init__(
        self,
        semantic_repository: Optional[ChromaMemoryRepository] = None,
    ):
        self._semantic_store = SemanticStore(
            repository=semantic_repository or ChromaMemoryRepository()
        )

    # ── Store properties ────────────────────────────────────────────────

    @property
    def semantic(self) -> SemanticStore:
        """Access the semantic memory store directly."""
        return self._semantic_store

    @semantic.setter
    def semantic(self, store: SemanticStore) -> None:
        """Allow replacing the semantic store (useful in tests)."""
        self._semantic_store = store

    # ── Unified API ─────────────────────────────────────────────────────

    def store(
        self,
        item: Union[Entity, str],
        **kwargs: Any,
    ) -> str:
        """
        Store an item in the appropriate memory store.

        Args:
            item: An :class:`Entity` (stored in semantic memory) or a
                string memory type for future stores.

        Returns:
            The storage ID assigned by the underlying store.

        Raises:
            ValueError: If *item* is a string (unknown memory type) rather
                than an :class:`Entity`.
        """
        if isinstance(item, Entity):
            return self._semantic_store.store_entity(item)
        raise ValueError(
            f"Unknown memory type: {item!r}. Pass an Entity for semantic "
            f"storage, or a dedicated type for episodic/procedural stores."
        )

    def query(
        self,
        memory_type: str,
        query_text: str,
        top_k: int = 5,
        **filters: Any,
    ) -> List[Dict[str, Any]]:
        """
        Query a specific memory store.

        Args:
            memory_type: ``"semantic"`` (other values will raise).
            query_text: Natural-language query.
            top_k: Maximum results.
            **filters: Store-specific filter kwargs (e.g. ``user_id``).

        Returns:
            List of result dicts.

        Raises:
            ValueError: If *memory_type* is not recognised.
        """
        if memory_type == "semantic":
            user_id = filters.get("user_id")
            entities = self._semantic_store.query_by_semantic(
                text=query_text, top_k=top_k, user_id=user_id
            )
            return [
                {
                    "entity_id": e.entity_id,
                    "entity_type": e.entity_type,
                    "value": e.value,
                    "user_id": e.user_id,
                    "confidence": e.confidence,
                    "created_at": e.created_at.isoformat(),
                    "updated_at": e.updated_at.isoformat(),
                }
                for e in entities
            ]
        raise ValueError(f"Unknown memory type: {memory_type!r}")

    def recall(self, context: RecallContext) -> RecallResult:
        """
        Combined recall across all active memory stores.

        Queries each store independently and merges results into a single
        :class:`RecallResult`.

        Args:
            context: The :class:`RecallContext` with query parameters.

        Returns:
            A :class:`RecallResult` with results per store.
        """
        result = RecallResult(query=context.query, user_id=context.user_id)

        if not context.query:
            return result

        # Semantic memory
        semantic_entities = self._semantic_store.query_by_semantic(
            text=context.query,
            top_k=context.top_k,
            user_id=context.user_id or None,
        )
        result.semantic_results = [
            {
                "entity_id": e.entity_id,
                "entity_type": e.entity_type,
                "value": e.value,
                "user_id": e.user_id,
                "confidence": e.confidence,
            }
            for e in semantic_entities
        ]

        # Episodic and procedural are no-ops until P5/P6
        return result
