"""
Tests for RRFFuser — 4-signal fusion (dense + BM25 + entity + OWL) (Task 5.7).

k=60 standard. Final score = sum(RRF_score) over all 4 signals.
"""
import pytest
from src.core.extractor.rrf_fuser import RRFFuser


@pytest.fixture
def fuser():
    return RRFFuser(k=60)


class TestRRFFuserBasic:
    """RRF fusion with all 4 signals."""

    def test_single_signal_fusion(self, fuser):
        """Single signal → RRF score = 1/(k + rank)."""
        dense = [
            {"item_name": "A", "score": 0.9},
            {"item_name": "B", "score": 0.8},
        ]
        results = fuser.fuse(dense=dense, bm25=[], entity=[], owl=[])
        scores = {r["item_name"]: r["rrf_score"] for r in results}
        assert scores["A"] > 0
        assert scores["A"] > scores["B"]

    def test_two_signals_boost(self, fuser):
        """Items appearing in 2 signals get rank boost."""
        dense = [
            {"item_name": "A", "score": 0.9},
            {"item_name": "B", "score": 0.8},
        ]
        bm25 = [
            {"item_name": "A", "score": 0.7},
            {"item_name": "C", "score": 0.6},
        ]
        results = fuser.fuse(dense=dense, bm25=bm25, entity=[], owl=[])
        scores = {r["item_name"]: r["rrf_score"] for r in results}
        # A appears in both signals → should have higher RRF score than B or C
        assert scores["A"] > scores["B"]
        assert scores["A"] > scores["C"]

    def test_owl_signal_contributes(self, fuser):
        """OWL signal feeds into RRF as deterministic scores."""
        dense = [
            {"item_name": "X", "score": 0.5},
        ]
        owl = [
            {"item_name": "X", "score": 1.0, "match_type": "exact"},
        ]
        results = fuser.fuse(dense=dense, bm25=[], entity=[], owl=owl)
        # With OWL on top, X's RRF score should be higher than dense alone
        dense_only = fuser.fuse(dense=dense, bm25=[], entity=[], owl=[])
        assert results[0]["rrf_score"] > dense_only[0]["rrf_score"]

    def test_all_four_signals(self, fuser):
        """All 4 signals fused correctly."""
        dense = [{"item_name": "A", "score": 0.9}]
        bm25 = [{"item_name": "A", "score": 0.8}]
        entity = [{"item_name": "A", "score": 0.7}]
        owl = [{"item_name": "A", "score": 1.0, "match_type": "exact"}]
        results = fuser.fuse(dense=dense, bm25=bm25, entity=entity, owl=owl)
        # A gets contributions from all 4 signals
        assert results[0]["rrf_score"] > 0
        assert results[0]["item_name"] == "A"
        assert results[0]["signal_count"] == 4

    def test_results_sorted_by_score_desc(self, fuser):
        """Results sorted by rrf_score descending."""
        dense = [
            {"item_name": "B", "score": 0.5},
            {"item_name": "A", "score": 0.9},
        ]
        results = fuser.fuse(dense=dense, bm25=[], entity=[], owl=[])
        assert results[0]["rrf_score"] >= results[1]["rrf_score"]


class TestRRFFuserEdgeCases:
    """Edge cases for RRF fusion."""

    def test_all_empty(self, fuser):
        """All empty signals returns empty."""
        results = fuser.fuse(dense=[], bm25=[], entity=[], owl=[])
        assert results == []

    def test_single_item_all_signals(self, fuser):
        """Single item in all 4 signals gets high score."""
        item = {"item_name": "A", "score": 0.5}
        results = fuser.fuse(
            dense=[item], bm25=[item], entity=[item], owl=[item],
        )
        assert results[0]["signal_count"] == 4

    def test_custom_k(self):
        """Custom k parameter changes score magnitude."""
        fuser_k10 = RRFFuser(k=10)
        fuser_k100 = RRFFuser(k=100)

        items = [{"item_name": "A", "score": 0.9}]
        r1 = fuser_k10.fuse(dense=items, bm25=[], entity=[], owl=[])
        r2 = fuser_k100.fuse(dense=items, bm25=[], entity=[], owl=[])
        # k smaller → RRF score higher (1/(10+1) > 1/(100+1))
        assert r1[0]["rrf_score"] > r2[0]["rrf_score"]


class TestRRFFuserIdentity:
    """RRF signal_count metadata."""

    def test_signal_count_present(self, fuser):
        """Every result has signal_count and sources metadata."""
        dense = [{"item_name": "A", "score": 0.9}]
        results = fuser.fuse(dense=dense, bm25=[], entity=[], owl=[])
        assert "signal_count" in results[0]
        assert "sources" in results[0]
        assert "dense" in results[0]["sources"]

    def test_top_k_limit(self, fuser):
        """top_k limits results."""
        dense = [{"item_name": chr(65 + i), "score": 1.0 - i * 0.1} for i in range(10)]
        results = fuser.fuse(dense=dense, bm25=[], entity=[], owl=[], top_k=3)
        assert len(results) == 3
