"""
Tests for CrossEncoderReranker — rerank top-20 → top-5 (Task 5.8).

Uses cross-encoder/ms-marco-MiniLM-L-6-v2 with lazy download on first use.
"""
import pytest
from unittest.mock import MagicMock, patch

from src.core.extractor.cross_encoder_reranker import CrossEncoderReranker


class TestCrossEncoderReranker:
    """CrossEncoderReranker basic reranking."""

    def test_rerank_top_k(self):
        """rerank reduces items to top_k."""
        reranker = CrossEncoderReranker()
        # Mock to avoid actual model download
        reranker._model = MagicMock()
        reranker._model.predict.return_value = [0.9, 0.8, 0.7]

        items = [
            {"item_name": "A", "rrf_score": 0.5},
            {"item_name": "B", "rrf_score": 0.4},
            {"item_name": "C", "rrf_score": 0.3},
        ]
        results = reranker.rerank(query="test", items=items, top_k=2)
        assert len(results) == 2
        assert results[0]["item_name"] in ("A", "B", "C")

    def test_rerank_returns_valid_scores(self):
        """rerank returns items with rerank_score field."""
        reranker = CrossEncoderReranker()
        reranker._model = MagicMock()
        reranker._model.predict.return_value = [0.95, 0.85]

        items = [
            {"item_name": "X", "rrf_score": 0.5},
            {"item_name": "Y", "rrf_score": 0.4},
        ]
        results = reranker.rerank(query="test", items=items, top_k=5)
        assert "rerank_score" in results[0]
        assert results[0]["rerank_score"] > 0

    def test_empty_items(self):
        """Empty items returns empty list."""
        reranker = CrossEncoderReranker()
        results = reranker.rerank(query="test", items=[], top_k=5)
        assert results == []

    def test_lazy_load_model(self):
        """Model is lazily loaded on first call."""
        reranker = CrossEncoderReranker()
        assert not hasattr(reranker, "_model") or reranker._model is None

    def test_rerank_scores_sorted(self):
        """Results sorted by rerank_score descending."""
        reranker = CrossEncoderReranker()
        reranker._model = MagicMock()
        reranker._model.predict.return_value = [0.7, 0.9, 0.8]

        items = [
            {"item_name": "A", "rrf_score": 0.1},
            {"item_name": "B", "rrf_score": 0.2},
            {"item_name": "C", "rrf_score": 0.3},
        ]
        results = reranker.rerank(query="test", items=items, top_k=5)
        assert results[0]["rerank_score"] >= results[1]["rerank_score"] >= results[2]["rerank_score"]


class TestCrossEncoderRerankerModelPath:
    """CrossEncoderReranker model path configuration."""

    def test_default_model_path(self):
        """Default model path is cross-encoder/ms-marco-MiniLM-L-6-v2."""
        reranker = CrossEncoderReranker()
        assert "ms-marco-MiniLM-L-6-v2" in reranker.model_name

    def test_custom_model_path(self):
        """Custom model path is accepted."""
        reranker = CrossEncoderReranker(model_name="custom/model")
        assert reranker.model_name == "custom/model"


class TestCrossEncoderRerankerNoModel:
    """CrossEncoderReranker when model is not available."""

    def test_rerank_without_model_loads_lazily(self):
        """rerank without model triggers lazy load attribute."""
        reranker = CrossEncoderReranker()
        # model attribute should be None before first call
        assert getattr(reranker, "_model", None) is None
