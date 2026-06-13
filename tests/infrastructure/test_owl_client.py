"""
Tests unitarios para OwlClient.

Verifica que todas las consultas SPARQL sean deterministas
(misma consulta ×3 = mismo resultado) y que los métodos de
conveniencia retornen datos correctos.
"""
import copy
from pathlib import Path

import pytest

from src.infrastructure.owl_client import OwlClient


@pytest.fixture(scope="module")
def ontology_path():
    """Ruta al archivo menu.ttl del proyecto."""
    return str(
        Path(__file__).resolve().parent.parent.parent
        / "data" / "ontology" / "menu.ttl"
    )


@pytest.fixture(scope="module")
def client(ontology_path):
    """Instancia de OwlClient con la ontología real."""
    return OwlClient(ontology_path)


class TestDeterminism:
    """Todas las consultas deben ser deterministas — mismo resultado 3 veces."""

    def test_query_deterministic_same_result_three_times(self, client):
        """query_deterministic retorna el mismo resultado en 3 ejecuciones."""
        sparql = """
        SELECT ?section WHERE {
            ?sec a :MenuSection ; :sectionName ?section .
        }
        ORDER BY ?section
        """
        r1 = client.query_deterministic(sparql)
        r2 = client.query_deterministic(sparql)
        r3 = client.query_deterministic(sparql)
        assert r1 == r2 == r3

    def test_get_full_menu_deterministic(self, client):
        """get_full_menu retorna el mismo texto en 3 llamadas."""
        m1 = client.get_full_menu()
        m2 = client.get_full_menu()
        m3 = client.get_full_menu()
        assert m1 == m2 == m3

    def test_get_section_items_deterministic(self, client):
        """get_section_items retorna el mismo texto en 3 llamadas."""
        s1 = client.get_section_items("Proteínas")
        s2 = client.get_section_items("Proteínas")
        s3 = client.get_section_items("Proteínas")
        assert s1 == s2 == s3

    def test_get_item_price_deterministic(self, client):
        """get_item_price retorna el mismo texto en 3 llamadas."""
        p1 = client.get_item_price("Bocachico")
        p2 = client.get_item_price("Bocachico")
        p3 = client.get_item_price("Bocachico")
        assert p1 == p2 == p3

    def test_get_item_options_deterministic(self, client):
        """get_item_options retorna el mismo texto en 3 llamadas."""
        o1 = client.get_item_options("Bandeja mixta")
        o2 = client.get_item_options("Bandeja mixta")
        o3 = client.get_item_options("Bandeja mixta")
        assert o1 == o2 == o3


class TestSectionQueries:
    """Consultas por sección."""

    def test_get_section_items_sopa(self, client):
        """Sopa contiene Crema de verdura."""
        result = client.get_section_items("Sopa")
        assert "Crema de verdura" in result

    def test_get_section_items_proteinas(self, client):
        """Proteínas contiene items esperados."""
        result = client.get_section_items("Proteínas")
        assert "Bandeja mixta" in result
        assert "Bocachico" in result
        assert "Lomo de cerdo" in result

    def test_get_section_items_principio(self, client):
        """Principio contiene 3 items."""
        result = client.get_section_items("Principio")
        assert "Macarrón" in result
        assert "Guiso de yota" in result
        assert "Principio mixto" in result

    def test_get_section_items_acompanamientos(self, client):
        """Acompañamientos retorna descripción (no tiene items)."""
        result = client.get_section_items("Acompañamientos")
        assert "Yuca al vapor" in result
        assert "arroz" in result


class TestItemPrice:
    """Consultas de precio."""

    def test_get_item_price_exact(self, client):
        """Precio exacto para Bocachico."""
        result = client.get_item_price("Bocachico criollo frito / sudado")
        assert "$13500" in result

    def test_get_item_price_partial_match(self, client):
        """Coincidencia parcial para 'lomo'."""
        result = client.get_item_price("lomo")
        assert "$13500" in result

    def test_get_item_price_with_size_variants(self, client):
        """Items con tamaño Corriente/mini muestran ambos precios."""
        result = client.get_item_price("Carne a la plancha")
        assert "$13500 (Corriente)" in result
        assert "$12000 (mini)" in result

    def test_get_item_price_not_found(self, client):
        """Item inexistente retorna mensaje de no encontrado."""
        result = client.get_item_price("ItemQueNoExiste")
        assert "no se encontró" in result.lower()


class TestItemOptions:
    """Consultas de opciones/sub-variantes."""

    def test_get_item_options_bandeja_mixta(self, client):
        """Bandeja mixta tiene 3 opciones de proteína."""
        result = client.get_item_options("Bandeja mixta")
        assert "Pechuga - Carne" in result
        assert "Pechuga - Lomo de cerdo" in result
        assert "Carne - Lomo de cerdo" in result

    def test_get_item_options_lomo(self, client):
        """Lomo de cerdo tiene 3 opciones de salsa."""
        result = client.get_item_options("Lomo de cerdo")
        assert "salsa BBQ" in result
        assert "salsa miel-mostaza" in result
        assert "Sin ninguna salsa" in result

    def test_get_item_options_no_options(self, client):
        """Item sin opciones retorna mensaje."""
        result = client.get_item_options("Bocachico")
        assert "no se encontraron" in result.lower()


class TestMenuSummary:
    """Resumen compacto del menú para el LLM router."""

    def test_get_menu_summary_contains_sections(self, client):
        """El resumen contiene todas las secciones."""
        summary = client.get_menu_summary()
        assert "Sopa" in summary
        assert "Principio" in summary
        assert "Proteínas" in summary

    def test_get_menu_summary_has_counts(self, client):
        """El resumen incluye conteo de items por sección."""
        summary = client.get_menu_summary()
        assert "items" in summary

    def test_get_menu_summary_deterministic(self, client):
        """Misma llamada produce mismo resultado."""
        s1 = client.get_menu_summary()
        s2 = client.get_menu_summary()
        assert s1 == s2

    def test_get_menu_summary_cached(self, client):
        """Llamadas repetidas usan el caché."""
        # La primera llamada establece el caché
        s1 = client.get_menu_summary()
        # La segunda debe devolver lo mismo sin recomputar
        s2 = client.get_menu_summary()
        assert s1 is s2  # misma referencia de objeto (caché)

    def test_get_menu_summary_under_200_tokens(self, client):
        """El resumen debe ser compacto (< 200 tokens aprox)."""
        summary = client.get_menu_summary()
        # Aproximación: un token ~ 4 caracteres en español
        token_estimate = len(summary) / 4
        assert token_estimate < 200, (
            f"Resumen demasiado largo: ~{token_estimate:.0f} tokens estimados"
        )


class TestFullMenu:
    """Menú completo."""

    def test_get_full_menu_contains_all_sections(self, client):
        """El menú completo contiene las 4 secciones."""
        result = client.get_full_menu()
        assert "Sopa" in result
        assert "Principio" in result
        assert "Acompañamientos" in result
        assert "Proteínas" in result

    def test_get_full_menu_contains_items(self, client):
        """El menú completo contiene items conocidos."""
        result = client.get_full_menu()
        assert "Crema de verdura" in result
        assert "Bandeja mixta" in result
        assert "Precios" in result
