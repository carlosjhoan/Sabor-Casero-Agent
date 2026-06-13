"""
Tests de integración para el pipeline owl-router con ontología real.

Usa el menu.ttl real + OwlClient real para verificar que el
OwlRouterMapper valida y ejecuta correctamente sobre datos
conocidos.
"""
from pathlib import Path

import pytest

from src.infrastructure.owl_client import OwlClient
from src.core.extractor.owl_router_schema import MenuQuery
from src.core.extractor.owl_router_mapper import OwlRouterMapper


@pytest.fixture(scope="module")
def ontology_path():
    """Ruta al archivo menu.ttl del proyecto."""
    return str(
        Path(__file__).resolve().parent.parent.parent
        / "data" / "ontology" / "menu.ttl"
    )


@pytest.fixture(scope="module")
def client(ontology_path):
    """OwlClient con la ontología real."""
    return OwlClient(ontology_path)


@pytest.fixture(scope="module")
def mapper(client):
    """OwlRouterMapper con OwlClient real."""
    return OwlRouterMapper(client)


class TestValidateIntegration:
    """Validación contra la ontología real."""

    def test_validate_known_section_sopa(self, mapper):
        """section='Sopa' existe en la ontología."""
        q = MenuQuery(intent="section_items", section="Sopa", confidence=0.9)
        assert mapper.validate(q) is True

    def test_validate_known_section_proteinas(self, mapper):
        """section='Proteínas' existe en la ontología."""
        q = MenuQuery(intent="section_items", section="Proteínas", confidence=0.9)
        assert mapper.validate(q) is True

    def test_validate_hallucinated_section(self, mapper):
        """section='Postres' no existe en la ontología."""
        q = MenuQuery(intent="section_items", section="Postres", confidence=0.8)
        assert mapper.validate(q) is False

    def test_validate_known_item_bandeja(self, mapper):
        """item='Bandeja mixta' existe en la ontología."""
        q = MenuQuery(intent="item_price", item="Bandeja mixta", confidence=0.9)
        assert mapper.validate(q) is True

    def test_validate_hallucinated_item(self, mapper):
        """item='Filete mignon' no existe en la ontología."""
        q = MenuQuery(intent="item_price", item="Filete mignon", confidence=0.8)
        assert mapper.validate(q) is False

    def test_validate_synonym_item_partial(self, mapper):
        """Nombre parcial como 'lomo' debe resolver."""
        q = MenuQuery(intent="item_price", item="lomo", confidence=0.8)
        # El mapper usa substring matching
        assert mapper.validate(q) is True

    def test_validate_typo_item_fails(self, mapper):
        """Typo como 'Principio misto' falla."""
        q = MenuQuery(
            intent="item_price",
            item="Principio misto",
            confidence=0.8,
        )
        assert mapper.validate(q) is False


class TestExecuteIntegration:
    """Ejecución de MenuQuery contra OwlClient real."""

    def test_execute_full_menu_contains_proteinas(self, client, mapper):
        """full_menu incluye Proteínas."""
        q = MenuQuery(intent="full_menu", confidence=1.0)
        result = mapper.execute(q)
        assert result is not None
        assert "Proteínas" in result

    def test_execute_section_items_sopa(self, client, mapper):
        """section_items('Sopa') retorna Crema de verdura."""
        q = MenuQuery(intent="section_items", section="Sopa", confidence=0.9)
        result = mapper.execute(q)
        assert result is not None
        assert "Crema de verdura" in result

    def test_execute_item_price_bandeja(self, client, mapper):
        """item_price('Bandeja mixta') retorna $15000."""
        q = MenuQuery(intent="item_price", item="Bandeja mixta", confidence=0.9)
        result = mapper.execute(q)
        assert result is not None
        assert "$15000" in result or "15000" in result

    def test_execute_item_options_lomo(self, client, mapper):
        """item_options('Lomo de cerdo') retorna opciones."""
        q = MenuQuery(
            intent="item_options",
            item="Lomo de cerdo asado a la plancha",
            confidence=0.9,
        )
        result = mapper.execute(q)
        assert result is not None
        assert "salsa" in result.lower()

    def test_execute_item_partial_name(self, client, mapper):
        """item_price con nombre parcial resuelve via OwlClient."""
        q = MenuQuery(intent="item_price", item="lomo", confidence=0.8)
        assert mapper.validate(q) is True
        result = mapper.execute(q)
        assert result is not None
        assert "$" in result

    def test_execute_unknown_returns_none(self, client, mapper):
        """unknown → None."""
        q = MenuQuery(intent="unknown", confidence=0.5)
        result = mapper.execute(q)
        assert result is None
