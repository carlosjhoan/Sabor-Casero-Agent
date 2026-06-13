"""
Task 4.4 — RED: MemoryHub facade tests.

Tests for store/query/recall delegation to internal stores.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime


@pytest.fixture
def mock_semantic_store():
    """Creates a mock SemanticStore."""
    store = MagicMock()
    store.store_entity = MagicMock(return_value="entity-id")
    store.query_by_semantic = MagicMock(return_value=[])
    store.query_by_entity = MagicMock(return_value=[])
    store.extract_from_turn = MagicMock(return_value=[])
    return store


class TestMemoryHubInit:
    """MemoryHub initialization."""

    def test_init_creates_semantic_store(self):
        """GIVEN no arguments, WHEN MemoryHub created, THEN it has a semantic store."""
        from src.core.memory.domain.memory_hub import MemoryHub
        hub = MemoryHub()
        assert hub.semantic is not None

    def test_init_with_custom_repository(self):
        """GIVEN a custom repository, WHEN MemoryHub created, THEN semantic store uses it."""
        from src.core.memory.domain.memory_hub import MemoryHub
        from src.core.memory.domain.semantic_store import SemanticStore

        repo = MagicMock()
        hub = MemoryHub(semantic_repository=repo)
        assert hub.semantic.repository is repo


class TestMemoryHubStore:
    """MemoryHub.store() delegation."""

    def test_store_routes_to_semantic_with_entity_type(self, mock_semantic_store):
        """GIVEN memory_type='semantic' with an Entity, WHEN store, THEN semantic.store_entity."""
        from src.core.memory.domain.memory_hub import MemoryHub
        from src.core.memory.domain.models_memory import Entity

        hub = MemoryHub()
        hub.semantic = mock_semantic_store

        entity = Entity(entity_type="test", value="v", user_id="u1", confidence=0.5)
        result = hub.store(entity)

        mock_semantic_store.store_entity.assert_called_once_with(entity)
        assert result == "entity-id"

    def test_store_unknown_memory_type_raises(self, mock_semantic_store):
        """GIVEN an unknown memory_type, WHEN store, THEN ValueError."""
        from src.core.memory.domain.memory_hub import MemoryHub

        hub = MemoryHub()
        hub.semantic = mock_semantic_store

        with pytest.raises(ValueError, match="Unknown memory type"):
            hub.store("not_an_entity")


class TestMemoryHubQuery:
    """MemoryHub.query() delegation."""

    def test_query_semantic_delegates(self, mock_semantic_store):
        """GIVEN memory_type='semantic', WHEN query, THEN semantic.query_by_semantic."""
        from src.core.memory.domain.memory_hub import MemoryHub

        hub = MemoryHub()
        hub.semantic = mock_semantic_store

        hub.query("semantic", "carne asada", top_k=3)
        mock_semantic_store.query_by_semantic.assert_called_once_with(
            text="carne asada", top_k=3, user_id=None
        )

    def test_query_unknown_type_raises(self):
        """GIVEN an unknown memory type, WHEN query, THEN ValueError."""
        from src.core.memory.domain.memory_hub import MemoryHub

        hub = MemoryHub()
        with pytest.raises(ValueError, match="Unknown memory type"):
            hub.query("nonexistent", "test")


class TestMemoryHubRecall:
    """MemoryHub.recall() — combined recall across stores."""

    def test_recall_queries_semantic(self, mock_semantic_store):
        """GIVEN a recall context, WHEN recall, THEN semantic is queried."""
        from src.core.memory.domain.memory_hub import MemoryHub
        from src.core.memory.domain.models_memory import RecallContext

        hub = MemoryHub()
        hub.semantic = mock_semantic_store
        mock_semantic_store.query_by_semantic.return_value = [
            MagicMock(value="carne asada", entity_type="protein_pref", confidence=0.9,
                      user_id="u1", entity_id="e1")
        ]

        ctx = RecallContext(query="carne", user_id="u1")
        result = hub.recall(ctx)

        assert result.query == "carne"
        assert len(result.semantic_results) >= 1
        assert result.semantic_results[0]["value"] == "carne asada"

    def test_recall_empty_context_returns_empty(self):
        """GIVEN an empty recall context, WHEN recall, THEN empty result."""
        from src.core.memory.domain.memory_hub import MemoryHub
        from src.core.memory.domain.models_memory import RecallContext

        hub = MemoryHub()
        ctx = RecallContext(query="", user_id="u1")
        result = hub.recall(ctx)
        assert result.query == ""
        assert result.semantic_results == []
