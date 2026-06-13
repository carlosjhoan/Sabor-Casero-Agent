"""
Tests de validación para el script de ingesta menu.md → menu.ttl.

Verifica que el script produce Turtle válido que rdflib puede
cargar sin errores.
"""
from pathlib import Path

import rdflib
import pytest

from scripts.ingest_menu_to_owl import (
    parse_menu_md,
    generate_ttl,
    _to_uri,
)


@pytest.fixture(scope="module")
def menu_md_content():
    """Contenido del archivo menu.md real."""
    path = (
        Path(__file__).resolve().parent.parent.parent
        / "data" / "documents" / "menu.md"
    )
    return path.read_text(encoding="utf-8")


class TestParseMenuMd:
    """Pruebas del parseador de menu.md."""

    def test_parses_sections(self, menu_md_content):
        """Se encuentran las 4 secciones principales."""
        sections = parse_menu_md(menu_md_content)
        section_names = [s.name for s in sections]
        assert any(n.startswith("Acompañamientos") for n in section_names)
        assert "Proteínas" in section_names

    def test_sopa_has_one_item(self, menu_md_content):
        """Sopa tiene Crema de verdura."""
        sections = parse_menu_md(menu_md_content)
        sopa = next(s for s in sections if s.name == "Sopa")
        assert len(sopa.items) == 1
        assert sopa.items[0].name == "Crema de verdura"

    def test_proteinas_has_seven_items(self, menu_md_content):
        """Proteínas tiene 7 items."""
        sections = parse_menu_md(menu_md_content)
        proteinas = next(s for s in sections if s.name == "Proteínas")
        assert len(proteinas.items) == 7

    def test_bandeja_mixta_has_options(self, menu_md_content):
        """Bandeja mixta tiene 3 opciones."""
        sections = parse_menu_md(menu_md_content)
        proteinas = next(s for s in sections if s.name == "Proteínas")
        bandeja = next(i for i in proteinas.items if "Bandeja" in i.name)
        assert len(bandeja.options) == 3
        assert "Pechuga - Carne" in bandeja.options

    def test_bandeja_mixta_has_price(self, menu_md_content):
        """Bandeja mixta tiene precio 15000."""
        sections = parse_menu_md(menu_md_content)
        proteinas = next(s for s in sections if s.name == "Proteínas")
        bandeja = next(i for i in proteinas.items if "Bandeja" in i.name)
        assert len(bandeja.prices) == 1
        assert bandeja.prices[0][0] == "15000"

    def test_carne_plancha_has_two_prices(self, menu_md_content):
        """Carne a la plancha tiene 2 precios (Corriente y mini)."""
        sections = parse_menu_md(menu_md_content)
        proteinas = next(s for s in sections if s.name == "Proteínas")
        item = next(i for i in proteinas.items if "Carne a la plancha" in i.name)
        assert len(item.prices) == 2
        sizes = [p[1] for p in item.prices]
        assert "Corriente" in sizes
        assert "mini" in sizes

    def test_acompanamientos_has_items_and_description(self, menu_md_content):
        """Acompañamientos tiene items y descripción (incluído por defecto)."""
        sections = parse_menu_md(menu_md_content)
        acompanamientos = next(s for s in sections if s.name.startswith("Acompañamientos"))
        assert acompanamientos.description is not None
        assert len(acompanamientos.items) > 0
        assert "yuca al vapor" in acompanamientos.description.lower()


class TestGenerateTtl:
    """Pruebas de generación de Turtle."""

    def test_generates_valid_turtle(self, menu_md_content):
        """El Turtle generado se carga sin error con rdflib."""
        sections = parse_menu_md(menu_md_content)
        ttl_content = generate_ttl(sections)

        graph = rdflib.Graph()
        graph.parse(data=ttl_content, format="turtle")
        assert len(graph) > 0, "El grafo no debe estar vacío"

    def test_generated_ttl_has_sections(self, menu_md_content):
        """El Turtle generado contiene las secciones."""
        sections = parse_menu_md(menu_md_content)
        ttl_content = generate_ttl(sections)
        assert ":Sopa" in ttl_content
        assert ":Principio" in ttl_content
        assert ":Proteinas" in ttl_content
        assert ":Acompanamientos" in ttl_content

    def test_generated_ttl_matches_ontology(self, menu_md_content):
        """El Turtle generado tiene clases y propiedades de la ontología."""
        sections = parse_menu_md(menu_md_content)
        ttl_content = generate_ttl(sections)
        assert ":MenuItem a owl:Class" in ttl_content
        assert ":MenuSection a owl:Class" in ttl_content
        assert "owl:ObjectProperty" in ttl_content
        assert "owl:DatatypeProperty" in ttl_content

    def test_to_uri_simple(self):
        """_to_uri convierte nombres a CamelCase."""
        assert _to_uri("Crema de verdura") == "CremaDeVerdura"
        assert _to_uri("Carne a la plancha") == "CarneALaPlancha"
        assert _to_uri("Sopa") == "Sopa"


class TestEndToEnd:
    """Prueba completa: parsear → generar → cargar con rdflib."""

    def test_roundtrip(self, menu_md_content):
        """El pipeline completo produce Turtle válido y con datos."""
        sections = parse_menu_md(menu_md_content)
        ttl_content = generate_ttl(sections)

        graph = rdflib.Graph()
        graph.parse(data=ttl_content, format="turtle")

        # Verificar que hay triples con las clases esperadas
        has_menu_item = False
        for s, p, o in graph:
            if "MenuItem" in str(o):
                has_menu_item = True
                break
        assert has_menu_item, "Debe haber al menos un MenuItem en el grafo"

    def test_no_parse_errors(self, menu_md_content):
        """No debe haber errores de sintaxis en el Turtle generado."""
        sections = parse_menu_md(menu_md_content)
        ttl_content = generate_ttl(sections)

        # rdflib lanza excepción si el Turtle está mal formado
        graph = rdflib.Graph()
        graph.parse(data=ttl_content, format="turtle")
        # Si llegamos aquí, el Turtle es válido
        assert True
