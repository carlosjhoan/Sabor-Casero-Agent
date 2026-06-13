"""
Tests unitarios para MenuQuery schema.

Verifica la creación, validación y límites del modelo Pydantic
usado por el LLM router.
"""
import pytest
from pydantic import ValidationError

from src.core.extractor.owl_router_schema import MenuQuery


class TestMenuQueryValid:
    """Escenarios válidos para MenuQuery."""

    def test_full_menu_intent(self):
        """full_menu con solo intent y confianza."""
        q = MenuQuery(intent="full_menu", confidence=0.95)
        assert q.intent == "full_menu"
        assert q.section is None
        assert q.item is None
        assert q.confidence == 0.95

    def test_section_items_with_section(self):
        """section_items con sección especificada."""
        q = MenuQuery(
            intent="section_items",
            section="Sopa",
            confidence=0.85,
        )
        assert q.intent == "section_items"
        assert q.section == "Sopa"
        assert q.item is None

    def test_item_price_with_item(self):
        """item_price con ítem especificado."""
        q = MenuQuery(
            intent="item_price",
            item="Bandeja mixta",
            confidence=0.9,
        )
        assert q.intent == "item_price"
        assert q.item == "Bandeja mixta"
        assert q.section is None

    def test_item_options_with_item(self):
        """item_options con ítem especificado."""
        q = MenuQuery(
            intent="item_options",
            item="Pechuga gratinada",
            confidence=0.8,
        )
        assert q.intent == "item_options"
        assert q.item == "Pechuga gratinada"

    def test_unknown_intent(self):
        """unknown sin campos adicionales."""
        q = MenuQuery(intent="unknown", confidence=0.5)
        assert q.intent == "unknown"
        assert q.section is None
        assert q.item is None

    def test_default_confidence(self):
        """confidence por defecto es 0.0."""
        q = MenuQuery(intent="full_menu")
        assert q.confidence == 0.0

    def test_section_and_item_both_set(self):
        """Ambos campos opcionales pueden estar seteados."""
        q = MenuQuery(
            intent="section_items",
            section="Proteínas",
            item="Bandeja mixta",
            confidence=0.7,
        )
        assert q.section == "Proteínas"
        assert q.item == "Bandeja mixta"


class TestMenuQueryInvalid:
    """Escenarios inválidos que deben lanzar ValidationError."""

    def test_invalid_intent_value(self):
        """Valor de intent no permitido → ValidationError."""
        with pytest.raises(ValidationError):
            MenuQuery(intent="invalid_value")

    def test_invalid_intent_number(self):
        """Número como intent → ValidationError."""
        with pytest.raises(ValidationError):
            MenuQuery(intent=123)  # type: ignore[arg-type]

    def test_confidence_negative(self):
        """Confianza negativa → ValidationError."""
        with pytest.raises(ValidationError):
            MenuQuery(intent="full_menu", confidence=-0.1)

    def test_confidence_over_one(self):
        """Confianza mayor a 1.0 → ValidationError."""
        with pytest.raises(ValidationError):
            MenuQuery(intent="full_menu", confidence=1.5)

    def test_confidence_at_lower_bound(self):
        """Confianza en 0.0 es válida."""
        q = MenuQuery(intent="full_menu", confidence=0.0)
        assert q.confidence == 0.0

    def test_confidence_at_upper_bound(self):
        """Confianza en 1.0 es válida."""
        q = MenuQuery(intent="full_menu", confidence=1.0)
        assert q.confidence == 1.0

    def test_empty_string_section(self):
        """section como string vacío es válido (None por defecto)."""
        q = MenuQuery(intent="full_menu", section="")
        assert q.section == ""

    def test_empty_string_item(self):
        """item como string vacío es válido (None por defecto)."""
        q = MenuQuery(intent="item_price", item="")
        assert q.item == ""
