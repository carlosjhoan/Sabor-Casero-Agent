"""
Task 4.3 — SemanticStore: domain-layer interface for semantic memory.

Provides:
- ``store_entity`` — persist a structured fact.
- ``query_by_semantic`` — embedding-based similarity search.
- ``query_by_entity`` — exact lookup by ``(user_id, entity_type, value)``.
- ``extract_from_turn`` — lightweight rule-based entity extraction from a
  :class:`ConversationTurn`.
"""
import logging
import re
from typing import List, Optional

from src.core.memory.domain.models_memory import Entity, ConversationTurn
from src.core.memory.infrastructure.chroma_memory_repository import (
    ChromaMemoryRepository,
)

logger = logging.getLogger(__name__)

# Regex patterns for MVP entity extraction (rule-based, no LLM).
# Ordered by specificity — first match wins per pattern type.
_PROTEIN_PATTERNS = [
    (re.compile(r"(bien\s+)?(asada|asado|cocido|termino|punto|jugoso|suave)"), "protein_pref"),
    (re.compile(r"(a la )?plancha"), "protein_pref"),
    (re.compile(r"(al )?horno"), "protein_pref"),
    (re.compile(r"gratinad[oa]"), "protein_pref"),
    (re.compile(r"(a la )?parrilla"), "protein_pref"),
    (re.compile(r"(a la )?brasas?"), "protein_pref"),
]

_AVOID_PATTERN = re.compile(r"sin\s+(\w[\w\sáéíóúñ]*?)(?:[,\.;]|por favor|$)", re.IGNORECASE)
_EXTRA_PATTERN = re.compile(r"(?:extra\s+|adicional\s+|m[áa]s\s+)(\w[\w\sáéíóúñ]*?)(?:[,\.;]|$)", re.IGNORECASE)
_DIETARY_PATTERNS = [
    re.compile(r"(?:intoleran\w+|alérgic\w+|alergia)\s+(?:a\s+)?(\w[\w\sáéíóúñ]*)", re.IGNORECASE),
    re.compile(r"sin\s+(lactosa|gluten|az[úu]car)", re.IGNORECASE),
]


class SemanticStore:
    """
    Domain service for semantic memory operations.

    Wraps a :class:`ChromaMemoryRepository` and adds entity extraction
    logic on top.
    """

    def __init__(self, repository: Optional[ChromaMemoryRepository] = None):
        self.repository = repository or ChromaMemoryRepository()

    # ── Public API ──────────────────────────────────────────────────────

    def store_entity(self, entity: Entity) -> str:
        """
        Persist an entity via the repository.

        Returns the deterministic storage ID.
        """
        return self.repository.upsert(entity)

    def query_by_semantic(
        self,
        text: str,
        top_k: int = 5,
        user_id: Optional[str] = None,
    ) -> List[Entity]:
        """
        Search entities by semantic similarity.
        """
        return self.repository.query_by_semantic(
            text=text, top_k=top_k, user_id=user_id
        )

    def query_by_entity(
        self,
        entity_type: str,
        value: str,
        user_id: Optional[str] = None,
    ) -> Optional[Entity]:
        """
        Look up an exact entity by type and value.

        If *user_id* is provided, scopes the lookup.
        """
        uid = user_id or ""
        return self.repository.get_by_entity(uid, entity_type, value)

    def extract_from_turn(self, turn: ConversationTurn) -> List[Entity]:
        """
        Extract structured :class:`Entity` instances from a conversation
        turn using lightweight rule-based patterns.

        Returns an empty list when no patterns match.
        """
        entities: List[Entity] = []
        text = turn.user_message

        if not text or not text.strip():
            return entities

        # ── Protein / cooking preferences ──────────────────────────────
        for pattern, entity_type in _PROTEIN_PATTERNS:
            for match in pattern.finditer(text):
                # Use the full matched text as value
                value = match.group(0).strip().lower()
                if value and not self._already_extracted(entities, entity_type, value):
                    entities.append(self._make_entity(
                        entity_type=entity_type,
                        value=value,
                        turn=turn,
                        confidence=0.7,
                    ))

        # ── Avoid ingredients ("sin X") ────────────────────────────────
        for match in _AVOID_PATTERN.finditer(text):
            ingredient = match.group(1).strip().lower()
            if ingredient and len(ingredient) > 1:
                # Check if it's actually a dietary restriction
                if ingredient in ("lactosa", "gluten", "azúcar"):
                    if not self._already_extracted(entities, "dietary_restriction", ingredient):
                        entities.append(self._make_entity(
                            entity_type="dietary_restriction",
                            value=ingredient,
                            turn=turn,
                            confidence=0.9,
                        ))
                else:
                    if not self._already_extracted(entities, "avoid_ingredient", ingredient):
                        entities.append(self._make_entity(
                            entity_type="avoid_ingredient",
                            value=ingredient,
                            turn=turn,
                            confidence=0.8,
                        ))

        # ── Extra items ────────────────────────────────────────────────
        for match in _EXTRA_PATTERN.finditer(text):
            extra = match.group(1).strip().lower()
            if extra and len(extra) > 1 and not self._already_extracted(entities, "extra_item", extra):
                entities.append(self._make_entity(
                    entity_type="extra_item",
                    value=extra,
                    turn=turn,
                    confidence=0.7,
                ))

        # ── Dietary restrictions ────────────────────────────────────────
        for pattern in _DIETARY_PATTERNS:
            for match in pattern.finditer(text):
                restriction = match.group(1).strip().lower()
                if restriction and len(restriction) > 1:
                    # Check "sin lactosa" is already handled above
                    if not self._already_extracted(entities, "dietary_restriction", restriction):
                        entities.append(self._make_entity(
                            entity_type="dietary_restriction",
                            value=restriction,
                            turn=turn,
                            confidence=0.85,
                        ))

        return entities

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_entity(
        entity_type: str,
        value: str,
        turn: ConversationTurn,
        confidence: float,
    ) -> Entity:
        return Entity(
            entity_type=entity_type,
            value=value,
            user_id=turn.user_id,
            confidence=confidence,
            source_turns=[turn.turn_number],
            metadata={
                "session_id": turn.session_id,
                "turn_number": turn.turn_number,
            },
        )

    @staticmethod
    def _already_extracted(
        entities: List[Entity],
        entity_type: str,
        value: str,
    ) -> bool:
        return any(
            e.entity_type == entity_type and e.value == value
            for e in entities
        )
