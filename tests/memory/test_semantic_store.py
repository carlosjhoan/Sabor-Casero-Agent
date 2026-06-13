"""
Task 4.3 — RED: SemanticStore tests.

Tests for store_entity, query_by_semantic, query_by_entity, extract_from_turn.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime


@pytest.fixture
def mock_repo():
    """Creates a mock ChromaMemoryRepository."""
    repo = MagicMock()
    repo.upsert = MagicMock(return_value="entity-id-123")
    repo.query_by_semantic = MagicMock(return_value=[])
    repo.get_by_entity = MagicMock(return_value=None)
    repo.delete = MagicMock()
    return repo


class TestSemanticStoreInit:
    """SemanticStore initialization."""

    def test_init_accepts_repository(self, mock_repo):
        """GIVEN a repository, WHEN SemanticStore created, THEN it stores the reference."""
        from src.core.memory.domain.semantic_store import SemanticStore
        store = SemanticStore(repository=mock_repo)
        assert store.repository is mock_repo

    def test_init_default_repository(self):
        """GIVEN no repository, WHEN SemanticStore created, THEN it creates default."""
        from src.core.memory.domain.semantic_store import SemanticStore
        store = SemanticStore()
        assert store.repository is not None


class TestSemanticStoreStoreEntity:
    """Store entity delegation."""

    def test_store_entity_delegates_to_repo(self, mock_repo):
        """GIVEN an Entity, WHEN store_entity called, THEN repo.upsert is called."""
        from src.core.memory.domain.semantic_store import SemanticStore
        from src.core.memory.domain.models_memory import Entity

        store = SemanticStore(repository=mock_repo)
        entity = Entity(entity_type="test", value="v", user_id="u1", confidence=0.5)

        result = store.store_entity(entity)

        mock_repo.upsert.assert_called_once_with(entity)
        assert result == "entity-id-123"

    def test_store_entity_returns_id(self, mock_repo):
        """GIVEN a valid entity, WHEN stored, THEN the entity ID is returned."""
        from src.core.memory.domain.semantic_store import SemanticStore
        from src.core.memory.domain.models_memory import Entity

        store = SemanticStore(repository=mock_repo)
        entity = Entity(entity_type="test", value="v", user_id="u1", confidence=0.5)
        result = store.store_entity(entity)
        assert isinstance(result, str)
        assert len(result) > 0


class TestSemanticStoreQuery:
    """Semantic query delegation."""

    def test_query_by_semantic_delegates(self, mock_repo):
        """GIVEN a text query, WHEN query_by_semantic called, THEN repo is queried."""
        from src.core.memory.domain.semantic_store import SemanticStore

        store = SemanticStore(repository=mock_repo)
        store.query_by_semantic("carne asada", top_k=3)

        mock_repo.query_by_semantic.assert_called_once_with(text="carne asada", top_k=3, user_id=None)

    def test_query_by_semantic_with_user_filter(self, mock_repo):
        """GIVEN a text query with user_id, WHEN query_by_semantic, THEN filter is passed."""
        from src.core.memory.domain.semantic_store import SemanticStore

        store = SemanticStore(repository=mock_repo)
        store.query_by_semantic("carne", top_k=5, user_id="u1")

        mock_repo.query_by_semantic.assert_called_once_with(text="carne", top_k=5, user_id="u1")

    def test_query_by_entity_delegates(self, mock_repo):
        """GIVEN entity type and value, WHEN query_by_entity, THEN repo is called."""
        from src.core.memory.domain.semantic_store import SemanticStore

        store = SemanticStore(repository=mock_repo)
        store.query_by_entity("protein_pref", "carne asada")

        mock_repo.get_by_entity.assert_called_once()


class TestSemanticStoreExtractFromTurn:
    """Entity extraction from conversation turns."""

    def test_extract_protein_preference(self, mock_repo):
        """GIVEN a turn with "carne bien asada", WHEN extract_from_turn, THEN protein_pref entity."""
        from src.core.memory.domain.semantic_store import SemanticStore
        from src.core.memory.domain.models_memory import ConversationTurn

        store = SemanticStore(repository=mock_repo)
        turn = ConversationTurn(
            user_id="u1",
            session_id="s1",
            turn_number=1,
            user_message="Quiero la carne bien asada",
            assistant_response="¡Claro! carne bien asada",
        )

        entities = store.extract_from_turn(turn)

        assert len(entities) >= 1
        protein_entities = [e for e in entities if e.entity_type == "protein_pref"]
        assert len(protein_entities) >= 1
        # Should capture cooking preference
        assert any("asada" in e.value for e in protein_entities)

    def test_extract_avoid_ingredient(self, mock_repo):
        """GIVEN a turn with "sin cebolla", WHEN extract_from_turn, THEN avoid_ingredient entity."""
        from src.core.memory.domain.semantic_store import SemanticStore
        from src.core.memory.domain.models_memory import ConversationTurn

        store = SemanticStore(repository=mock_repo)
        turn = ConversationTurn(
            user_id="u1",
            session_id="s1",
            turn_number=2,
            user_message="Sin cebolla por favor",
            assistant_response="Entendido, sin cebolla",
        )

        entities = store.extract_from_turn(turn)

        avoid = [e for e in entities if e.entity_type == "avoid_ingredient"]
        assert len(avoid) >= 1
        assert any("cebolla" in e.value for e in avoid)

    def test_extract_dietary_restriction(self, mock_repo):
        """GIVEN a turn with "sin lactosa", WHEN extract_from_turn, THEN dietary_restriction entity."""
        from src.core.memory.domain.semantic_store import SemanticStore
        from src.core.memory.domain.models_memory import ConversationTurn

        store = SemanticStore(repository=mock_repo)
        turn = ConversationTurn(
            user_id="u1",
            session_id="s1",
            turn_number=3,
            user_message="Sin lactosa por favor, soy intolerante",
            assistant_response="Entendido, prepararemos todo sin lactosa",
        )

        entities = store.extract_from_turn(turn)

        dietary = [e for e in entities if e.entity_type == "dietary_restriction"]
        assert len(dietary) >= 1
        assert any("lactosa" in e.value for e in dietary)

    def test_extract_no_entities_from_empty_message(self, mock_repo):
        """GIVEN a turn with no relevant content, WHEN extract_from_turn, THEN empty list."""
        from src.core.memory.domain.semantic_store import SemanticStore
        from src.core.memory.domain.models_memory import ConversationTurn

        store = SemanticStore(repository=mock_repo)
        turn = ConversationTurn(
            user_id="u1",
            session_id="s1",
            turn_number=4,
            user_message="Hola, ¿cómo estás?",
            assistant_response="¡Hola! Bien, ¿en qué puedo ayudarte?",
        )

        entities = store.extract_from_turn(turn)
        assert len(entities) == 0
