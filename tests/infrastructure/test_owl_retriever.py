"""
Tests unitarios para OwlRetriever.

Verifica el flujo retrieve() con _route_query async mockeado
y los casos borde del pipeline.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict

import pytest

from src.core.classifier.intent import Detail
from src.core.extractor.owl_retriever import OwlRetriever
from src.core.extractor.owl_router_schema import MenuQuery


@pytest.fixture
def mock_owl_client():
    """Mock de OwlClient con respuestas predecibles."""
    client = MagicMock()
    client.get_section_names.return_value = {
        "Sopa", "Principio", "Acompañamientos", "Proteínas",
    }
    client.get_item_names.return_value = {
        "Crema de verdura", "Bandeja mixta", "Lomo de cerdo asado a la plancha",
    }
    client.get_menu_summary.return_value = "Sopa: 1 items, Principio: 3 items"
    client.get_full_menu.return_value = "Menú completo mock"
    client.get_section_items.return_value = "Items de sección mock"
    client.get_item_price.return_value = "Precio mock"
    client.get_item_options.return_value = "Opciones mock"
    return client


@pytest.fixture
def retriever(mock_owl_client):
    """OwlRetriever con cliente mockeado."""
    return OwlRetriever(owl_client=mock_owl_client)


@pytest.fixture
def menu_detail():
    """Detail con file_source='menu.md'."""
    return Detail(
        segment="¿Qué hay hoy?",
        query_type="consulting",
        topic="menu",
        focus="menú del día de hoy",
        file_source="menu.md",
    )


class TestRouting:
    """Ruteo vía LLM — _route_query mockeado como AsyncMock."""

    @pytest.fixture(autouse=True)
    def mock_route_query(self, retriever):
        """Reemplaza _route_query con un AsyncMock para estas pruebas."""
        mock = AsyncMock()
        mock.return_value = "Resultado mock"
        retriever._route_query = mock
        return mock

    @pytest.mark.asyncio
    async def test_route_query_called_with_segment_and_focus(
        self, retriever, menu_detail
    ):
        """Verifica que retrieve llama a _route_query con segment y focus."""
        menu_detail.segment = "¿Cuánto cuesta el lomo?"
        menu_detail.focus = "precio del lomo de cerdo"
        await retriever.retrieve({"menu.md": [menu_detail]})
        retriever._route_query.assert_awaited_once_with(
            "¿Cuánto cuesta el lomo?", "precio del lomo de cerdo"
        )

    @pytest.mark.asyncio
    async def test_route_query_sets_info_extracted(
        self, retriever, menu_detail
    ):
        """El resultado de _route_query se asigna a info_extracted."""
        retriever._route_query.return_value = "Precio: $13500"
        await retriever.retrieve({"menu.md": [menu_detail]})
        assert menu_detail.info_extracted == "Precio: $13500"

    @pytest.mark.asyncio
    async def test_route_query_none_fallback_to_empty(
        self, retriever, menu_detail
    ):
        """_route_query retorna None → info_extracted queda vacío."""
        retriever._route_query.return_value = None
        await retriever.retrieve({"menu.md": [menu_detail]})
        assert menu_detail.info_extracted == ""

    @pytest.mark.asyncio
    async def test_multiple_details_routed_individually(
        self, retriever
    ):
        """Cada Detail recibe su propio _route_query."""
        details = [
            Detail(
                segment="¿Qué hay de sopa?",
                query_type="consulting",
                topic="menu",
                focus="sopa del día",
                file_source="menu.md",
            ),
            Detail(
                segment="¿Cuánto cuesta el lomo?",
                query_type="consulting",
                topic="menu",
                focus="precio del lomo",
                file_source="menu.md",
            ),
        ]
        results = await retriever.retrieve({"menu.md": details})
        assert len(results) == 2
        assert retriever._route_query.await_count == 2


class TestEdgeCases:
    """Casos borde del OwlRetriever."""

    @pytest.mark.asyncio
    async def test_invalid_doc_name_raises(self, retriever):
        """Documento que no es menu.md lanza ValueError."""
        detail = Detail(
            segment="consulta",
            query_type="consulting",
            topic="menu",
            focus="consulta de prueba",
            file_source="service_info.txt",
        )
        with pytest.raises(ValueError, match="solo maneja menu.md"):
            await retriever.retrieve({"service_info.txt": [detail]})

    @pytest.mark.asyncio
    async def test_error_sets_fallback_message(self, retriever, menu_detail):
        """Error en _route_query se captura y se asigna mensaje de error."""
        # Simular error lanzando excepción desde retrieve
        original_route = retriever._route_query

        async def failing_route(segment, focus):
            raise Exception("Fallo simulado")

        retriever._route_query = failing_route
        menu_detail.segment = "¿Qué hay hoy?"
        await retriever.retrieve({"menu.md": [menu_detail]})
        assert "error" in menu_detail.info_extracted.lower()
