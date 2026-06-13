"""
Tests de integración para RetrieverFactory.

Verifica que get_retriever('owl') retorne un CompositeRetriever
con los retrievers internos correctos.
"""
import pytest

from src.core.extractor.retriever_factory import RetrieverFactory
from src.core.extractor.retriever_interface import RetrieverInterface


class TestFactory:
    """Pruebas para la fábrica de retrievers."""

    def test_get_retriever_owl_returns_composite(self):
        """get_retriever('owl') retorna un CompositeRetriever."""
        retriever = RetrieverFactory.get_retriever("owl")
        # Verificar que implementa la interfaz
        assert isinstance(retriever, RetrieverInterface)
        # Verificar que es un CompositeRetriever
        assert retriever.__class__.__name__ == "CompositeRetriever"

    def test_get_retriever_owl_has_primary(self):
        """CompositeRetriever tiene un primary (OwlRetriever)."""
        retriever = RetrieverFactory.get_retriever("owl")
        assert hasattr(retriever, "_primary")
        assert retriever._primary.__class__.__name__ == "OwlRetriever"

    def test_get_retriever_owl_has_fallback(self):
        """CompositeRetriever tiene un fallback (HybridRetriever)."""
        retriever = RetrieverFactory.get_retriever("owl")
        assert hasattr(retriever, "_fallback")
        assert retriever._fallback.__class__.__name__ == "HybridRetriever"

    def test_get_retriever_unknown_raises(self):
        """Tipo desconocido lanza ValueError."""
        with pytest.raises(ValueError, match="Unknown retriever way"):
            RetrieverFactory.get_retriever("unknown_type")
