"""
Tests unitarios para OwlRouterMapper.

Usa OwlClient mockeado para verificar la validación de secciones/ítems
y la ejecución de cada intent sin depender de la ontología real.
"""
from unittest.mock import MagicMock

import pytest

from src.core.extractor.owl_router_schema import MenuQuery
from src.core.extractor.owl_router_mapper import OwlRouterMapper


@pytest.fixture
def mock_owl_client():
    """Mock de OwlClient con secciones e ítems conocidos."""
    client = MagicMock()
    client.get_section_names.return_value = {
        "Sopa", "Principio", "Acompañamientos", "Proteínas",
    }
    client.get_item_names.return_value = {
        "Crema de verdura",
        "Macarrón con carne molida",
        "Guiso de yota con huevo",
        "Principio mixto (Ambos principios)",
        "Bandeja mixta",
        "Bocachico criollo frito / sudado",
        "Carnes mixtas en vegetales",
        "Pechuga gratinada",
        "Pechuga a la plancha",
        "Carne a la plancha",
        "Lomo de cerdo asado a la plancha",
    }
    client.get_full_menu.return_value = "Menú completo mock"
    client.get_section_items.return_value = "Items de sección mock"
    client.get_item_price.return_value = "Precio mock"
    client.get_item_options.return_value = "Opciones mock"
    return client


@pytest.fixture
def mapper(mock_owl_client):
    """OwlRouterMapper con cliente mockeado."""
    return OwlRouterMapper(mock_owl_client)


class TestValidate:
    """Validación de MenuQuery contra la ontología conocida."""

    def test_validate_full_menu(self, mapper):
        """full_menu siempre es válido."""
        q = MenuQuery(intent="full_menu", confidence=0.9)
        assert mapper.validate(q) is True

    def test_validate_unknown(self, mapper):
        """unknown siempre es válido."""
        q = MenuQuery(intent="unknown", confidence=0.5)
        assert mapper.validate(q) is True

    def test_validate_section_items_valid(self, mapper):
        """section_items con sección conocida es válido."""
        q = MenuQuery(intent="section_items", section="Sopa", confidence=0.85)
        assert mapper.validate(q) is True

    def test_validate_section_items_invalid(self, mapper):
        """section_items con sección inventada es inválido."""
        q = MenuQuery(intent="section_items", section="Postres", confidence=0.8)
        assert mapper.validate(q) is False

    def test_validate_section_items_no_section(self, mapper):
        """section_items sin sección es inválido."""
        q = MenuQuery(intent="section_items", confidence=0.8)
        assert mapper.validate(q) is False

    def test_validate_item_price_valid(self, mapper):
        """item_price con ítem conocido es válido."""
        q = MenuQuery(intent="item_price", item="Bandeja mixta", confidence=0.9)
        assert mapper.validate(q) is True

    def test_validate_item_price_hallucinated(self, mapper):
        """item_price con ítem inventado es inválido."""
        q = MenuQuery(intent="item_price", item="Filete mignon", confidence=0.8)
        assert mapper.validate(q) is False

    def test_validate_item_price_typo(self, mapper):
        """item_price con typo menor es inválido (no hay match exacto)."""
        q = MenuQuery(intent="item_price", item="Principio misto", confidence=0.8)
        assert mapper.validate(q) is False

    def test_validate_item_price_partial_match(self, mapper):
        """item_price con nombre parcial funciona si hay substring."""
        q = MenuQuery(intent="item_price", item="Lomo", confidence=0.8)
        assert mapper.validate(q) is True

    def test_validate_item_price_no_item(self, mapper):
        """item_price sin ítem es inválido."""
        q = MenuQuery(intent="item_price", confidence=0.8)
        assert mapper.validate(q) is False

    def test_validate_item_options_valid(self, mapper):
        """item_options con ítem conocido es válido."""
        q = MenuQuery(intent="item_options", item="Pechuga gratinada", confidence=0.8)
        assert mapper.validate(q) is True

    def test_validate_item_options_hallucinated(self, mapper):
        """item_options con ítem inventado es inválido."""
        q = MenuQuery(intent="item_options", item="Pizza", confidence=0.7)
        assert mapper.validate(q) is False


class TestExecute:
    """Ejecución de MenuQuery contra OwlClient."""

    def test_execute_full_menu(self, mapper, mock_owl_client):
        """full_menu → get_full_menu()."""
        q = MenuQuery(intent="full_menu", confidence=0.9)
        result = mapper.execute(q)
        assert result == "Menú completo mock"
        mock_owl_client.get_full_menu.assert_called_once()

    def test_execute_section_items(self, mapper, mock_owl_client):
        """section_items → get_section_items(section)."""
        q = MenuQuery(intent="section_items", section="Sopa", confidence=0.85)
        result = mapper.execute(q)
        assert result == "Items de sección mock"
        mock_owl_client.get_section_items.assert_called_once_with("Sopa")

    def test_execute_item_price(self, mapper, mock_owl_client):
        """item_price → get_item_price(item)."""
        q = MenuQuery(intent="item_price", item="Bandeja mixta", confidence=0.9)
        result = mapper.execute(q)
        assert result == "Precio mock"
        mock_owl_client.get_item_price.assert_called_once_with("Bandeja mixta")

    def test_execute_item_options(self, mapper, mock_owl_client):
        """item_options → get_item_options(item)."""
        q = MenuQuery(intent="item_options", item="Pechuga gratinada", confidence=0.8)
        result = mapper.execute(q)
        assert result == "Opciones mock"
        mock_owl_client.get_item_options.assert_called_once_with("Pechuga gratinada")

    def test_execute_unknown(self, mapper, mock_owl_client):
        """unknown → None (sin llamar al cliente)."""
        q = MenuQuery(intent="unknown", confidence=0.5)
        result = mapper.execute(q)
        assert result is None
        mock_owl_client.get_full_menu.assert_not_called()

    def test_execute_client_error(self, mapper, mock_owl_client):
        """Error en OwlClient → None."""
        mock_owl_client.get_full_menu.side_effect = Exception("Fallo")
        q = MenuQuery(intent="full_menu", confidence=0.9)
        result = mapper.execute(q)
        assert result is None
