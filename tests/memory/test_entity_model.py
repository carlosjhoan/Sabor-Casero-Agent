"""
Task 4.1 — RED: Entity Pydantic model tests.

Tests for the Entity model in models_memory.py:
- Required fields and defaults
- Entity ID auto-generation
- Field validation (confidence range, entity_type values)
- Serialization roundtrip
"""
import pytest
from datetime import datetime
from pydantic import ValidationError


class TestEntityModel:
    """Entity Pydantic model — field validation."""

    def test_entity_required_fields(self):
        """GIVEN minimal Entity data, WHEN constructed, THEN all required fields are set."""
        from src.core.memory.domain.models_memory import Entity
        now = datetime.now()
        entity = Entity(
            entity_type="protein_pref",
            value="carne bien asada",
            user_id="u1",
            confidence=0.9,
        )
        assert entity.entity_type == "protein_pref"
        assert entity.value == "carne bien asada"
        assert entity.user_id == "u1"
        assert entity.confidence == 0.9
        assert entity.entity_id is not None  # auto-generated UUID
        assert entity.source_turns == []
        assert entity.metadata == {}
        assert isinstance(entity.created_at, datetime)
        assert isinstance(entity.updated_at, datetime)

    def test_entity_auto_generates_id(self):
        """GIVEN no entity_id, WHEN constructed, THEN UUID is auto-generated."""
        from src.core.memory.domain.models_memory import Entity
        e1 = Entity(entity_type="address", value="Calle 123", user_id="u1", confidence=0.8)
        e2 = Entity(entity_type="address", value="Calle 123", user_id="u1", confidence=0.8)
        # Two separate entities should have different IDs
        assert e1.entity_id != e2.entity_id

    def test_entity_with_explicit_id(self):
        """GIVEN an explicit entity_id, WHEN constructed, THEN it is NOT overwritten."""
        from src.core.memory.domain.models_memory import Entity
        entity = Entity(
            entity_id="my-custom-id",
            entity_type="dietary_restriction",
            value="sin lactosa",
            user_id="u2",
            confidence=1.0,
        )
        assert entity.entity_id == "my-custom-id"

    def test_entity_confidence_default(self):
        """GIVEN no confidence, WHEN constructed, THEN default is 1.0."""
        from src.core.memory.domain.models_memory import Entity
        entity = Entity(
            entity_type="payment_method",
            value="efectivo",
            user_id="u1",
        )
        assert entity.confidence == 1.0

    def test_entity_confidence_range_validation(self):
        """GIVEN confidence out of [0, 1] range, WHEN constructed, THEN ValidationError."""
        from src.core.memory.domain.models_memory import Entity
        with pytest.raises(ValidationError):
            Entity(entity_type="test", value="v", user_id="u1", confidence=1.5)
        with pytest.raises(ValidationError):
            Entity(entity_type="test", value="v", user_id="u1", confidence=-0.1)

    def test_entity_source_turns_defaults_empty(self):
        """GIVEN no source_turns, WHEN constructed, THEN defaults to empty list."""
        from src.core.memory.domain.models_memory import Entity
        entity = Entity(entity_type="test", value="v", user_id="u1", confidence=0.5)
        assert entity.source_turns == []

    def test_entity_metadata_defaults_empty(self):
        """GIVEN no metadata, WHEN constructed, THEN defaults to empty dict."""
        from src.core.memory.domain.models_memory import Entity
        entity = Entity(entity_type="test", value="v", user_id="u1", confidence=0.5)
        assert entity.metadata == {}

    def test_entity_serialization_roundtrip(self):
        """GIVEN an Entity, WHEN serialized to dict and back, THEN data is preserved."""
        from src.core.memory.domain.models_memory import Entity
        now = datetime.now()
        original = Entity(
            entity_type="dietary_restriction",
            value="sin lactosa",
            user_id="u3",
            confidence=0.95,
            source_turns=[1, 2],
            metadata={"source": "user_message"},
            created_at=now,
            updated_at=now,
        )
        data = original.model_dump()
        restored = Entity.model_validate(data)
        assert restored.entity_id == original.entity_id
        assert restored.entity_type == original.entity_type
        assert restored.value == original.value
        assert restored.user_id == original.user_id
        assert restored.confidence == original.confidence
        assert restored.source_turns == original.source_turns
        assert restored.metadata == original.metadata
