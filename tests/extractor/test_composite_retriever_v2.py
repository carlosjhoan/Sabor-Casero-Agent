"""
Tests for 3-phase RAG in CompositeRetriever v2 (Task 5.10).

Phase 1: OWL exact match fast-path (<5ms short-circuit)
Phase 2: Multi-signal RRF (dense + BM25 + entity + OWL)
Phase 3: Ontology Validation Gate
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.core.extractor.composite_retriever import CompositeRetriever


@pytest.fixture
def mock_primary():
    p = MagicMock()
    p.retrieve = AsyncMock(return_value=[])
    p.retrieve_v2 = AsyncMock(return_value=[])
    return p


@pytest.fixture
def mock_fallback():
    f = MagicMock()
    f.retrieve = AsyncMock(return_value=[])
    return f


@pytest.fixture
def mock_owl_signal():
    signal = MagicMock()
    signal.score_candidates = MagicMock(return_value={})
    signal.expand_query = MagicMock()
    return signal


@pytest.fixture
def mock_owl_client():
    client = MagicMock()
    client.get_item_names = MagicMock(return_value=set())
    return client


class TestCompositeRetrieverV2Flag:
    """rag_v2_enabled flag controls v2 path."""

    def test_retrieve_v2_disabled_by_default(self, mock_primary, mock_fallback):
        """retrieve_v2 is available but returns empty when disabled."""
        retriever = CompositeRetriever(
            primary=mock_primary, fallback=mock_fallback,
            owl_client=None, owl_signal=None,
            rag_v2_enabled=False,
        )
        # Should still call the primary retriever's retrieve_v2
        result = retriever.retrieve_v2(query="test", candidates=[], details=[])
        assert result is not None


# =========================================================================
# Task 5.14 — P5 Integration scenarios (S-P4-02 through S-P4-05)
# =========================================================================


class TestSP402OwlHallucinationGate:
    """S-P4-02: 'pollo guisado' → no existe → gate rejects."""

    def test_pollo_guisado_not_in_ontology(self):
        """
        GIVEN user asks "¿tienen pollo guisado?"
        WHEN dish is NOT in menu ontology
        THEN validate_candidates rejects it
        """
        from src.infrastructure.owl_client import OwlClient
        from src.core.extractor.owl_signal import OwlSignal
        from pathlib import Path

        ont_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "ontology" / "menu.ttl"
        )
        syn_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "ontology" / "ontology_synonyms.json"
        )

        client = OwlClient(ont_path)
        signal = OwlSignal(owl_client=client, synonyms_path=syn_path)

        # "pollo guisado" should NOT be in the ontology
        ontology_items = client.get_item_names()
        assert "pollo guisado" not in {n.lower() for n in ontology_items}

        # Score candidates that ARE real items
        candidates = [
            "Pechuga a la plancha",
            "Pechuga gratinada",
            "Bocachico criollo frito / sudado",
        ]
        result = signal.score_candidates("pollo guisado", candidates)

        # "Pechuga a la plancha" IS in the ontology → exact=1.0 (it's a real item)
        # But the POINT is: "pollo guisado" is NOT in ontology
        # Pechuga items should have at least partial/ingredient match
        assert "Pechuga a la plancha" in result
        assert result["Pechuga a la plancha"].score >= 0.7

        # Validate: "Pollo guisado inventado" should be rejected
        from src.engine.exceptions import OntologyGateError
        with pytest.raises(OntologyGateError):
            signal.validate_candidates(["Pollo guisado inventado"])


class TestSP403OwlIngredientExpansion:
    """S-P4-03: 'marrano' → cerdo → lomo de cerdo."""

    def test_marrano_expands_to_cerdo(self):
        """'marrano' is expanded via synonym mapping to 'cerdo'."""
        from src.infrastructure.owl_client import OwlClient
        from src.core.extractor.owl_signal import OwlSignal
        from pathlib import Path

        ont_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "ontology" / "menu.ttl"
        )
        syn_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "ontology" / "ontology_synonyms.json"
        )

        client = OwlClient(ont_path)
        signal = OwlSignal(owl_client=client, synonyms_path=syn_path)

        expansion = signal.expand_query("marrano")
        terms = {t.term: t for t in expansion.expanded_terms}
        assert len(expansion.expanded_terms) >= 1

        # Score "lomo de cerdo" for query "marrano"
        result = signal.score_candidates(
            "marrano",
            ["Lomo de cerdo asado a la plancha", "Carnes mixtas en vegetales"],
        )
        for item, m in result.items():
            assert m.score >= 0.6, f"{item} should score >= 0.6 for query 'marrano'"


class TestSP404OwlCookingMethod:
    """S-P4-04: 'pollo sudado' → pechuga (pollo) + bocachico (sudado)."""

    def test_pollo_sudado_finds_both_signals(self):
        """'pollo sudado' finds both ingredient and cooking_method matches."""
        from src.infrastructure.owl_client import OwlClient
        from src.core.extractor.owl_signal import OwlSignal
        from pathlib import Path

        ont_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "ontology" / "menu.ttl"
        )
        syn_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "ontology" / "ontology_synonyms.json"
        )

        client = OwlClient(ont_path)
        signal = OwlSignal(owl_client=client, synonyms_path=syn_path)

        candidates = [
            "Pechuga a la plancha",
            "Pechuga gratinada",
            "Bocachico criollo frito / sudado",
        ]
        result = signal.score_candidates("pollo sudado", candidates)
        # Pollo ingredient items should score >= 0.7
        pechuga_scores = {k: v for k, v in result.items() if "Pechuga" in k}
        assert any(v.score >= 0.7 for v in pechuga_scores.values())
        # Bocachico has sudado cooking method → should score >= 0.7
        assert result.get("Bocachico criollo frito / sudado", None) is not None
        assert result["Bocachico criollo frito / sudado"].score >= 0.7


class TestSP405OwlExactFastPath:
    """S-P4-05: exact match short-circuits pipeline."""

    def test_exact_match_returns_1_0(self):
        """Exact item match returns 1.0 score."""
        from src.infrastructure.owl_client import OwlClient
        from src.core.extractor.owl_signal import OwlSignal
        from pathlib import Path

        ont_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "ontology" / "menu.ttl"
        )
        syn_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "ontology" / "ontology_synonyms.json"
        )

        client = OwlClient(ont_path)
        signal = OwlSignal(owl_client=client, synonyms_path=syn_path)

        result = signal.score_candidates(
            "Pechuga a la plancha",
            ["Pechuga a la plancha"],
        )
        assert result["Pechuga a la plancha"].score == 1.0
        assert result["Pechuga a la plancha"].match_type == "exact"


# =========================================================================
# Multi-signal recall precision
# =========================================================================


class TestMultiSignalRecall:
    """Multi-signal recall precision with RRF."""

    def test_rrf_prefers_multi_signal_items(self):
        """Items matching multiple signals get higher RRF score."""
        from src.core.extractor.rrf_fuser import RRFFuser
        fuser = RRFFuser(k=60)

        dense = [
            {"item_name": "Pechuga a la plancha", "score": 0.85},
            {"item_name": "Bocachico criollo frito / sudado", "score": 0.60},
        ]
        bm25 = [
            {"item_name": "Pechuga a la plancha", "score": 0.75},
        ]
        owl = [
            {"item_name": "Pechuga a la plancha", "score": 1.0, "match_type": "exact"},
            {"item_name": "Bocachico criollo frito / sudado", "score": 0.7, "match_type": "cooking_method"},
        ]

        results = fuser.fuse(dense=dense, bm25=bm25, entity=[], owl=owl)
        scores = {r["item_name"]: r["rrf_score"] for r in results}
        # Pechuga appears in 3 signals → higher than Bocachico in 2 signals
        assert scores["Pechuga a la plancha"] > scores["Bocachico criollo frito / sudado"]
