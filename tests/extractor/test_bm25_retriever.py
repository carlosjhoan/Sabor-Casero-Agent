"""
Tests for BM25Retriever — keyword index via rank_bm25 (Task 5.5).
"""
import pytest

from src.core.extractor.bm25_retriever import BM25Retriever


@pytest.fixture
def documents():
    return [
        "Pechuga a la plancha con verduras",
        "Pechuga gratinada con queso",
        "Bocachico criollo frito o sudado",
        "Lomo de cerdo asado a la plancha",
        "Carnes mixtas en vegetales",
        "Crema de verdura",
    ]


@pytest.fixture
def retriever(documents):
    return BM25Retriever(documents=documents)


class TestBM25Retriever:
    """BM25Retriever basic retrieval."""

    def test_retrieve_exact_term(self, retriever):
        """Exact term returns matching documents."""
        results = retriever.retrieve("pechuga", top_k=5)
        assert len(results) >= 2
        scores = {r["item_name"]: r["score"] for r in results}
        assert "Pechuga a la plancha con verduras" in scores
        assert "Pechuga gratinada con queso" in scores

    def test_retrieve_top_k(self, retriever):
        """top_k limits results."""
        results = retriever.retrieve("cerdo", top_k=1)
        assert len(results) == 1

    def test_retrieve_no_match(self, retriever):
        """No matching terms returns empty."""
        results = retriever.retrieve("xyzzy", top_k=5)
        assert len(results) == 0

    def test_retrieve_multi_word(self, retriever):
        """Multi-word query matches relevant docs."""
        results = retriever.retrieve("lomo de cerdo", top_k=5)
        scores = {r["item_name"] for r in results}
        assert "Lomo de cerdo asado a la plancha" in scores

    def test_retrieve_scored_above_zero(self, retriever):
        """Results have positive scores."""
        results = retriever.retrieve("pollo", top_k=5)
        for r in results:
            assert r["score"] > 0

    def test_get_item_names(self, retriever):
        """get_item_names returns all indexed document names."""
        names = retriever.get_item_names()
        assert len(names) == 6
        assert "Pechuga a la plancha con verduras" in names


class TestBM25RetrieverEmpty:
    """BM25Retriever with no documents."""

    def test_empty_documents(self):
        """Empty document list produces no results."""
        r = BM25Retriever(documents=[])
        results = r.retrieve("anything", top_k=5)
        assert len(results) == 0

    def test_empty_documents_get_names(self):
        """Empty document list returns empty names."""
        r = BM25Retriever(documents=[])
        assert r.get_item_names() == []


class TestBM25RetrieverRanking:
    """BM25Retriever ranking order."""

    def test_higher_score_first(self, retriever):
        """Best matching document is first in results."""
        results = retriever.retrieve("pechuga plancha", top_k=5)
        assert len(results) >= 1
        # The best match should have the highest score
        assert results[0]["score"] >= results[-1]["score"]
