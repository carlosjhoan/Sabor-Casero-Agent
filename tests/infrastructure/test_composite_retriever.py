"""
Tests unitarios para CompositeRetriever.

Verifica que el ruteo por nombre de documento funcione correctamente:
menu.md → primary, otros docs → fallback.
"""
from unittest.mock import AsyncMock, MagicMock
from typing import List, Dict

import pytest

from src.core.classifier.intent import Detail
from src.core.extractor.composite_retriever import CompositeRetriever


@pytest.fixture
def mock_primary():
    """Mock del retriever primario (OwlRetriever)."""
    retriever = AsyncMock()
    retriever.retrieve.return_value = [
        Detail(
            segment="¿Qué hay hoy?",
            query_type="consulting",
            topic="menu",
            focus="menú del día",
            file_source="menu.md",
            info_extracted="Info del menú desde OWL",
        )
    ]
    return retriever


@pytest.fixture
def mock_fallback():
    """Mock del retriever fallback (HybridRetriever)."""
    retriever = AsyncMock()
    retriever.retrieve.return_value = [
        Detail(
            segment="¿Cuál es el horario?",
            query_type="consulting",
            topic="delivery",
            focus="horario de atención",
            file_source="service_info.txt",
            info_extracted="Info desde ChromaDB",
        )
    ]
    return retriever


@pytest.fixture
def composite(mock_primary, mock_fallback):
    """CompositeRetriever con ambos mocks."""
    return CompositeRetriever(primary=mock_primary, fallback=mock_fallback)


class TestDelegation:
    """Delegación correcta según doc_name."""

    @pytest.mark.asyncio
    async def test_menu_md_goes_to_primary(self, composite, mock_primary, mock_fallback):
        """menu.md se envía al retriever primario."""
        detail = Detail(
            segment="¿Qué hay hoy?",
            query_type="consulting",
            topic="menu",
            focus="menú del día",
            file_source="menu.md",
        )
        await composite.retrieve({"menu.md": [detail]})
        mock_primary.retrieve.assert_awaited_once()
        mock_fallback.retrieve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_other_doc_goes_to_fallback(self, composite, mock_primary, mock_fallback):
        """Documento que no es menu.md se envía al fallback."""
        detail = Detail(
            segment="¿Cuál es el horario?",
            query_type="consulting",
            topic="delivery",
            focus="horario de atención",
            file_source="service_info.txt",
        )
        await composite.retrieve({"service_info.txt": [detail]})
        mock_fallback.retrieve.assert_awaited_once()
        mock_primary.retrieve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_both_docs_routed_correctly(
        self, composite, mock_primary, mock_fallback
    ):
        """Ambos tipos de documentos se rutean correctamente."""
        menu_detail = Detail(
            segment="¿Qué hay hoy?",
            query_type="consulting",
            topic="menu",
            focus="menú del día",
            file_source="menu.md",
        )
        service_detail = Detail(
            segment="¿Cuál es el horario?",
            query_type="consulting",
            topic="delivery",
            focus="horario de atención",
            file_source="service_info.txt",
        )
        group = {
            "menu.md": [menu_detail],
            "service_info.txt": [service_detail],
        }
        results = await composite.retrieve(group)

        mock_primary.retrieve.assert_awaited_once_with({"menu.md": [menu_detail]})
        mock_fallback.retrieve.assert_awaited_once_with(
            {"service_info.txt": [service_detail]}
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_multiple_non_menu_docs(self, composite, mock_primary, mock_fallback):
        """Varios documentos no-menu se envían juntos al fallback."""
        details = [
            Detail(
                segment="consulta1",
                query_type="consulting",
                topic="delivery",
                focus="consulta de prueba 1",
                file_source="service_info.txt",
            ),
            Detail(
                segment="consulta2",
                query_type="consulting",
                topic="about",
                focus="consulta de prueba 2",
                file_source="about_us.txt",
            ),
        ]
        group = {
            "service_info.txt": [details[0]],
            "about_us.txt": [details[1]],
        }
        await composite.retrieve(group)
        mock_fallback.retrieve.assert_awaited_once_with(group)
        mock_primary.retrieve.assert_not_awaited()


class TestErrorHandling:
    """Manejo de errores en el composite."""

    @pytest.mark.asyncio
    async def test_primary_error_sets_fallback_message(
        self, mock_fallback
    ):
        """Error en primary.js no interrumpe y asigna mensaje de error."""
        errored_primary = AsyncMock()
        errored_primary.retrieve.side_effect = Exception("Fallo primario")

        composite = CompositeRetriever(
            primary=errored_primary, fallback=mock_fallback
        )
        detail = Detail(
            segment="¿Qué hay hoy?",
            query_type="consulting",
            topic="menu",
            focus="menú del día",
            file_source="menu.md",
        )
        results = await composite.retrieve({"menu.md": [detail]})
        assert "error" in detail.info_extracted.lower()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_fallback_error_sets_fallback_message(
        self, mock_primary
    ):
        """Error en fallback no interrumpe y asigna mensaje de error."""
        errored_fallback = AsyncMock()
        errored_fallback.retrieve.side_effect = Exception("Fallo fallback")

        composite = CompositeRetriever(
            primary=mock_primary, fallback=errored_fallback
        )
        detail = Detail(
            segment="¿Cuál es el horario?",
            query_type="consulting",
            topic="delivery",
            focus="horario de atención",
            file_source="service_info.txt",
        )
        results = await composite.retrieve({"service_info.txt": [detail]})
        assert "error" in detail.info_extracted.lower()
        assert len(results) == 1
