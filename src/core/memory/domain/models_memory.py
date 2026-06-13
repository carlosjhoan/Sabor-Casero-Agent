"""
Task 4.1 — Entity + ConversationTurn + RecallContext Pydantic models for
semantic memory.

The ``Entity`` model represents a single fact or preference extracted from a
conversation turn. ``ConversationTurn`` is a lightweight view of a single
interaction. ``RecallContext`` carries query parameters for combined recall
across memory stores.
"""
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class ConversationTurn(BaseModel):
    """
    A single user↔assistant interaction in a conversation session.

    Used as input to ``SemanticStore.extract_from_turn()`` for entity
    extraction.
    """
    user_id: str
    session_id: str
    turn_number: int
    user_message: str
    assistant_response: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Entity(BaseModel):
    """
    A structured fact extracted from a conversation turn.

    Design intent:
    - ``entity_id``: auto-generated UUID, may be overridden (e.g. for
      deterministic IDs from :func:`ChromaMemoryRepository._make_id`).
    - ``entity_type``: semantic category — ``"protein_pref"``,
      ``"avoid_ingredient"``, ``"dietary_restriction"``, ``"address"``,
      ``"payment_method"``, ``"known_dish"``, etc.
    - ``embedding``: optional vector; computed lazily by the repository
      layer if not provided.
    - ``source_turns``: provenance — which conversation turn numbers
      contributed to this entity.
    - ``metadata``: extensible bag of additional context (e.g. extraction
      source, LLM confidence, language).
    """
    entity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    entity_type: str
    value: str
    user_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_turns: List[int] = Field(default_factory=list)
    embedding: List[float] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @field_validator("entity_type")
    @classmethod
    def entity_type_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("entity_type must not be empty")
        return v.strip()

    @field_validator("value")
    @classmethod
    def value_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("value must not be empty")
        return v.strip()

    @field_validator("user_id")
    @classmethod
    def user_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("user_id must not be empty")
        return v.strip()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class RecallContext(BaseModel):
    """
    Parameters for :meth:`MemoryHub.recall` — combines signals from all
    memory stores into a single recall result.
    """
    query: str = ""
    user_id: str = ""
    top_k: int = Field(default=5, ge=1, le=50)
    entity_type_filter: Optional[str] = None
    time_range_days: Optional[int] = None


class RecallResult(BaseModel):
    """
    Combined result from :meth:`MemoryHub.recall`.

    Each memory store contributes a separate list so the caller can
    distinguish signal origin.
    """
    query: str
    user_id: str
    semantic_results: List[Dict[str, Any]] = Field(default_factory=list)
    episodic_results: List[Dict[str, Any]] = Field(default_factory=list)
    procedural_results: List[Dict[str, Any]] = Field(default_factory=list)
