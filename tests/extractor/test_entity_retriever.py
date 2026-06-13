"""
Tests for EntityRetriever — scores by semantic memory entity match (Task 5.6).
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from src.core.extractor.entity_retriever import EntityRetriever


@pytest.fixture
def mock_memory_hub():
    hub = MagicMock()
    def query(memory_type, query_text, top_k=5, **filters):
        if query_text == "cerdo":
            return [
                {"entity_id": "e1", "entity_type": "protein_pref",
                 "value": "cerdo", "user_id": "u1", "confidence": 0.9},
            ]
        elif query_text == "pollo":
            return [
                {"entity_id": "e2", "entity_type": "protein_pref",
                 "value": "pollo", "user_id": "u1", "confidence": 0.8},
            ]
        return []
    hub.query = query
    return hub


@pytest.fixture
def retriever(mock_memory_hub):
    return EntityRetriever(memory_hub=mock_memory_hub)


class TestEntityRetriever:
    """EntityRetriever scores items by semantic memory match."""

    def test_retrieve_with_match(self, retriever):
        """Known entity returns scored items."""
        results = retriever.retrieve(
            query="cerdo",
            candidates=["Lomo de cerdo asado a la plancha", "Pechuga a la plancha"],
        )
        scores = {r["item_name"]: r["score"] for r in results}
        assert scores.get("Lomo de cerdo asado a la plancha", 0) > 0
        # "cerdo" query should match "Lomo de cerdo" better than "Pechuga"
        assert scores["Lomo de cerdo asado a la plancha"] >= scores.get("Pechuga a la plancha", 0)

    def test_retrieve_no_match(self, retriever):
        """No entity match returns zero scores."""
        results = retriever.retrieve(
            query="unknown",
            candidates=["Pechuga a la plancha"],
        )
        assert results[0]["score"] == 0.0

    def test_retrieve_empty_candidates(self, retriever):
        """Empty candidates returns empty."""
        results = retriever.retrieve(query="pollo", candidates=[])
        assert results == []

    def test_retrieve_empty_query(self, retriever):
        """Empty query returns zero scores."""
        results = retriever.retrieve(
            query="",
            candidates=["Pechuga a la plancha"],
        )
        assert results[0]["score"] == 0.0


class TestEntityRetrieverNoHub:
    """EntityRetriever with no memory_hub."""

    def test_no_hub_returns_zero(self):
        """No memory_hub → all scores zero."""
        r = EntityRetriever(memory_hub=None)
        results = r.retrieve(query="cerdo", candidates=["Lomo de cerdo"])
        assert all(item["score"] == 0.0 for item in results)
