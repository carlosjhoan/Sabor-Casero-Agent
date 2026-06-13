"""
Tests for OntologyValidationGate — hallucination firewall (Task 5.4).

Covers S-P4-02 through S-P4-05 gate outcomes:
  - exact → pass, confidence preserved
  - related (ingredient/method) → tagged "related", confidence boosted
  - rejected (invented) → penalized ×0.3
  - all-rejected → OntologyGateError
"""
import pytest
from unittest.mock import MagicMock

from src.engine.exceptions import OntologyGateError
from src.core.extractor.ontology_validation_gate import (
    OntologyValidationGate,
    RankedItem,
)


@pytest.fixture
def mock_owl_signal():
    """Returns a mock OwlSignal with canned validation results."""
    signal = MagicMock()

    def validate_candidates(candidates, threshold=0.3):
        from src.core.extractor.owl_signal import ValidationResult
        passed = []
        flagged = []
        rejected = []
        for c in candidates:
            if c == "Pechuga a la plancha":
                passed.append(c)
            elif c == "Lomo de cerdo asado a la plancha":
                flagged.append({"item": c, "reason": "related", "match_type": "ingredient"})
            elif c == "Pollo guisado inventado":
                rejected.append(c)
            elif c == "Chuleta inventada":
                rejected.append(c)
            else:
                passed.append(c)
        return ValidationResult(passed=passed, flagged=flagged, rejected=rejected)

    signal.validate_candidates = validate_candidates
    return signal


@pytest.fixture
def gate():
    return OntologyValidationGate()


# =========================================================================
# Task 5.4 — validate() outcomes
# =========================================================================


class TestGateExactPass:
    """Exact match → confidence preserved."""

    def test_exact_item_unchanged(self, gate, mock_owl_signal):
        """Known item passes with confidence preserved."""
        items = [
            RankedItem(item_name="Pechuga a la plancha", score=0.95, source="test"),
            RankedItem(item_name="Lomo de cerdo asado a la plancha", score=0.80, source="test"),
        ]
        result = gate.validate(items, mock_owl_signal)
        assert result[0].item_name == "Pechuga a la plancha"
        assert result[0].score == 0.95
        assert result[0].gate_outcome == "pass"

    def test_confidence_boosted_for_flagged(self, gate, mock_owl_signal):
        """Related match → tagged 'related', confidence boosted."""
        items = [
            RankedItem(item_name="Lomo de cerdo asado a la plancha", score=0.80, source="test"),
        ]
        result = gate.validate(items, mock_owl_signal)
        assert result[0].item_name == "Lomo de cerdo asado a la plancha"
        assert result[0].score > 0.80  # boosted
        assert result[0].gate_outcome == "related"


class TestGateInvented:
    """Invented dish → penalized or removed."""

    def test_invented_item_penalized(self, gate, mock_owl_signal):
        """Non-existent item penalized ×0.3 when mixed with known items."""
        items = [
            RankedItem(item_name="Pollo guisado inventado", score=0.90, source="test"),
            RankedItem(item_name="Pechuga a la plancha", score=0.95, source="test"),
        ]
        result = gate.validate(items, mock_owl_signal)
        # Passed item first
        assert result[0].item_name == "Pechuga a la plancha"
        assert result[0].gate_outcome == "pass"
        # Invented item penalized
        assert result[1].item_name == "Pollo guisado inventado"
        assert result[1].score == pytest.approx(0.90 * 0.3)
        assert result[1].gate_outcome == "rejected"

    def test_all_rejected_raises_ontology_error(self, gate, mock_owl_signal):
        """ALL candidates rejected → OntologyGateError."""
        items = [
            RankedItem(item_name="Pollo guisado inventado", score=0.90, source="test"),
            RankedItem(item_name="Chuleta inventada", score=0.85, source="test"),
        ]
        with pytest.raises(OntologyGateError):
            gate.validate(items, mock_owl_signal)


class TestGateEdgeCases:
    """Edge cases for the ontology validation gate."""

    def test_empty_items_list(self, gate, mock_owl_signal):
        """Empty items list raises OntologyGateError."""
        with pytest.raises(OntologyGateError):
            gate.validate([], mock_owl_signal)

    def test_mixed_items_filter_order(self, gate, mock_owl_signal):
        """Mixed items: passed items first, rejected last."""
        items = [
            RankedItem(item_name="Pollo guisado inventado", score=0.90, source="test"),
            RankedItem(item_name="Pechuga a la plancha", score=0.80, source="test"),
        ]
        result = gate.validate(items, mock_owl_signal)
        # Passed items should come first
        assert result[0].item_name == "Pechuga a la plancha"
        assert result[1].gate_outcome == "rejected"


# =========================================================================
# Task 5.4 — RankedItem dataclass
# =========================================================================


class TestRankedItem:
    """RankedItem dataclass behavior."""

    def test_ranked_item_defaults(self):
        """RankedItem has correct default values."""
        item = RankedItem(item_name="Pechuga a la plancha", score=0.95, source="cross_encoder")
        assert item.item_name == "Pechuga a la plancha"
        assert item.score == 0.95
        assert item.source == "cross_encoder"
        assert item.gate_outcome == ""  # not yet validated
        assert item.metadata == {}

    def test_ranked_item_with_metadata(self):
        """RankedItem can hold metadata."""
        item = RankedItem(
            item_name="Test Item", score=0.5, source="test",
            gate_outcome="pass", metadata={"key": "val"},
        )
        assert item.gate_outcome == "pass"
        assert item.metadata["key"] == "val"
