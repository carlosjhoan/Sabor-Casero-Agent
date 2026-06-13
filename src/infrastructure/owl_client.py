"""
Cliente OWL para consultas SPARQL deterministas sobre el menú.

Wrap de rdflib que carga la ontología Turtle (menu.ttl) y expone
métodos tipados para consultar secciones, items, precios y opciones.
Todas las consultas son deterministas — mismo SPARQL → mismo resultado.
"""
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import rdflib
from rdflib import Graph, Namespace
from rdflib.plugins.sparql import prepareQuery

from src.utils.utils import print_section

logger = logging.getLogger("OwlClient")

NS = Namespace("http://saborcasero.com/menu#")


class OwlClient:
    """
    Cliente SPARQL determinista sobre la ontología del menú.

    Carga un archivo Turtle (.ttl) y provee métodos tipados
    para consultar la información del menú de forma determinista.

    Args:
        ontology_path: Ruta al archivo Turtle con la ontología.
    """

    def __init__(self, ontology_path: str):
        self._graph = Graph()
        self._parse_path(str(ontology_path))
        self._menu_summary: str | None = None
        logger.info("Ontología cargada desde %s", ontology_path)

    def _parse_path(self, path: str) -> None:
        """Carga el archivo Turtle en el grafo RDF."""
        resolved = Path(path)
        if not resolved.exists():
            raise FileNotFoundError(
                f"Archivo de ontología no encontrado: {resolved.absolute()}"
            )
        self._graph.parse(str(resolved), format="turtle")

    # ------------------------------------------------------------------
    # Resumen del menú (para LLM router)
    # ------------------------------------------------------------------

    def get_menu_summary(self) -> str:
        """
        Retorna un resumen compacto del menú con secciones y conteo
        de ítems, pensado para incluirlo en el prompt del LLM router.

        El resultado se cachea en ``self._menu_summary`` para no
        recomputarlo en llamadas sucesivas.

        Returns:
            Texto como ``"Sopa: 1 items, Principio: 3 items, ..."``
            con menos de 200 tokens.
        """
        if self._menu_summary is not None:
            return self._menu_summary

        sparql = """
        SELECT ?section (COUNT(?item) AS ?count) WHERE {
            ?sec a :MenuSection ; :sectionName ?section .
            OPTIONAL { ?sec :hasItem ?itemNode . ?itemNode :itemName ?item }
        }
        GROUP BY ?section
        ORDER BY ?section
        """
        raw = self.query_deterministic(sparql)
        parts: List[str] = []
        for row in raw:
            sec = row.get("section", "?")
            cnt = row.get("count", "0")
            parts.append(f"{sec}: {cnt} items")
        self._menu_summary = ", ".join(parts)
        return self._menu_summary

    # ------------------------------------------------------------------
    # Método base
    # ------------------------------------------------------------------

    def query_deterministic(self, sparql: str) -> List[Dict[str, Any]]:
        """
        Ejecuta una consulta SPARQL SELECT y retorna resultados como
        lista de diccionarios {nombre_variable: valor_string}.

        Args:
            sparql: Consulta SPARQL completa.

        Returns:
            Lista de diccionarios con los resultados.

        Raises:
            ValueError: Si la consulta SPARQL es inválida.
        """
        results: List[Dict[str, Any]] = []
        try:
            # Mostrar la consulta SPARQL
            sparql_preview = sparql.strip().replace("\n", " | ")
            if len(sparql_preview) > 180:
                sparql_preview = sparql_preview[:177] + "..."
            print_section(
                head="📡 SPARQL",
                msg=sparql_preview,
                symbol="·",
            )

            query = prepareQuery(sparql, initNs={"": NS})
            for row in self._graph.query(query):
                result: Dict[str, Any] = {}
                for var_name, val in row.asdict().items():
                    if isinstance(val, rdflib.term.Literal):
                        result[var_name] = str(val)
                    else:
                        result[var_name] = str(val)
                results.append(result)

            print_section(
                head=f"📊 SPARQL → {len(results)} filas",
                msg=str(results[:5])[:200] if results else "(vacío)",
                symbol="·",
            )
        except Exception as e:
            logger.error("Error en consulta SPARQL: %s", e)
            raise ValueError(f"Error ejecutando SPARQL: {e}") from e
        return results

    # ------------------------------------------------------------------
    # Métodos de consulta de metadatos
    # ------------------------------------------------------------------

    def get_section_names(self) -> set[str]:
        """
        Retorna los nombres de todas las secciones del menú.

        Returns:
            Set con nombres como ``{"Sopa", "Principio", ...}``.
        """
        sparql = """
        SELECT ?section WHERE {
            ?sec a :MenuSection ; :sectionName ?section .
        }
        ORDER BY ?section
        """
        raw = self.query_deterministic(sparql)
        return {row["section"] for row in raw if row.get("section")}

    def get_item_names(self) -> set[str]:
        """
        Retorna los nombres de todos los ítems del menú.

        Returns:
            Set con nombres completos de ítems.
        """
        sparql = """
        SELECT ?item WHERE {
            ?itemNode a :MenuItem ; :itemName ?item .
        }
        ORDER BY ?item
        """
        raw = self.query_deterministic(sparql)
        return {row["item"] for row in raw if row.get("item")}

    # ------------------------------------------------------------------
    # Métodos de conveniencia
    # ------------------------------------------------------------------

    def get_menu_structure(self) -> List[Dict[str, Any]]:
        """
        Retorna el menú completo como estructura de datos (dicts lists).

        Returns:
            Lista de secciones, cada una con:
            - name: str — nombre de la sección
            - description: str — descripción (si tiene)
            - items: list[dict] — cada item con name, prices[], options[]
        """
        sparql = """
        SELECT ?section ?desc ?item ?amount ?size ?opt WHERE {
            ?sec a :MenuSection .
            ?sec :sectionName ?section .
            OPTIONAL { ?sec :sectionDescription ?desc }
            OPTIONAL {
                ?sec :hasItem ?itemNode .
                ?itemNode :itemName ?item .
                OPTIONAL {
                    ?itemNode :hasPriceOption ?po .
                    ?po :hasAmount ?amount .
                    OPTIONAL { ?po :hasSize ?size }
                }
                OPTIONAL {
                    ?itemNode :hasOption ?optNode .
                    ?optNode :optionName ?opt .
                }
            }
        }
        ORDER BY ?section ?item
        """
        raw = self.query_deterministic(sparql)
        return self._build_menu_structure(raw)

    def get_full_menu(self) -> str:
        """
        Retorna el menú completo como texto legible con secciones,
        precios y opciones. Ideal para incluir en prompts LLM.

        Returns:
            Texto formateado del menú completo.
        """
        return self._format_full_menu(self.get_menu_structure())

    def get_section_items(self, section_name: str) -> str:
        """
        Retorna los items de una sección como texto legible.

        Args:
            section_name: Nombre exacto de la sección (ej. "Proteínas").
        """
        sparql = f"""
        SELECT ?item ?amount ?size ?opt WHERE {{
            ?sec a :MenuSection ; :sectionName "{section_name}" .
            OPTIONAL {{ ?sec :sectionDescription ?desc }}
            OPTIONAL {{
                ?sec :hasItem ?itemNode .
                ?itemNode :itemName ?item .
                OPTIONAL {{
                    ?itemNode :hasPriceOption ?po .
                    ?po :hasAmount ?amount .
                    OPTIONAL {{ ?po :hasSize ?size }}
                }}
                OPTIONAL {{
                    ?itemNode :hasOption ?optNode .
                    ?optNode :optionName ?opt .
                }}
            }}
        }}
        ORDER BY ?item
        """
        raw = self.query_deterministic(sparql)

        # Si no hay items, puede ser una sección descriptiva
        if not raw or all(r.get("item") is None for r in raw):
            desc_sparql = f"""
            SELECT ?desc WHERE {{
                ?sec a :MenuSection ; :sectionName "{section_name}" ;
                    :sectionDescription ?desc .
            }}
            """
            desc_result = self.query_deterministic(desc_sparql)
            if desc_result and desc_result[0].get("desc"):
                return desc_result[0]["desc"]
            return f"(No hay información disponible para {section_name})"

        return self._format_section_items(raw)

    def get_item_price(self, item_name: str) -> str:
        """
        Retorna el precio de un item como texto legible.
        Busca por coincidencia parcial (case-insensitive).

        Args:
            item_name: Nombre del item (puede ser parcial).
        """
        sparql = f"""
        SELECT ?item ?amount ?size WHERE {{
            ?itemNode a :MenuItem ; :itemName ?item .
            FILTER(CONTAINS(LCASE(?item), LCASE("{item_name}")))
            ?itemNode :hasPriceOption ?po .
            ?po :hasAmount ?amount .
            OPTIONAL {{ ?po :hasSize ?size }}
        }}
        ORDER BY ?item ?size
        """
        raw = self.query_deterministic(sparql)
        if not raw:
            return f"(No se encontró precio para '{item_name}')"
        return self._format_prices(raw)

    def get_item_options(self, item_name: str) -> str:
        """
        Retorna las opciones (sub-variantes) de un item como texto.

        Args:
            item_name: Nombre del item (puede ser parcial).
        """
        sparql = f"""
        SELECT ?item ?opt WHERE {{
            ?itemNode a :MenuItem ; :itemName ?item .
            FILTER(CONTAINS(LCASE(?item), LCASE("{item_name}")))
            ?itemNode :hasOption ?optNode .
            ?optNode :optionName ?opt .
        }}
        ORDER BY ?item ?opt
        """
        raw = self.query_deterministic(sparql)
        if not raw:
            return f"(No se encontraron opciones para '{item_name}')"
        return self._format_options(raw)

    # ------------------------------------------------------------------
    # Formateadores internos
    # ------------------------------------------------------------------

    def _build_menu_structure(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convierte filas SPARQL en estructura de secciones con items."""
        sections_map: Dict[str, Dict[str, Any]] = {}
        sec_order: List[str] = []

        for row in rows:
            sec = row.get("section", "")
            if not sec:
                continue
            if sec not in sections_map:
                sections_map[sec] = {
                    "name": sec,
                    "description": row.get("desc", "") or "",
                    "items": {},
                }
                sec_order.append(sec)

            item_name = row.get("item")
            if item_name:
                if item_name not in sections_map[sec]["items"]:
                    sections_map[sec]["items"][item_name] = {
                        "name": item_name,
                        "prices": [],
                        "options": [],
                    }
                amt = row.get("amount")
                sz = row.get("size")
                if amt:
                    price_str = f"${amt}" + (f" ({sz})" if sz else "")
                    if price_str not in sections_map[sec]["items"][item_name]["prices"]:
                        sections_map[sec]["items"][item_name]["prices"].append(price_str)
                opt = row.get("opt")
                if opt and opt not in sections_map[sec]["items"][item_name]["options"]:
                    sections_map[sec]["items"][item_name]["options"].append(opt)

        # Convertir a lista ordenada (canonical order + any extras)
        canonical_order = ["Sopa", "Principio", "Acompañamientos", "Proteínas"]
        result: List[Dict[str, Any]] = []
        for sec_name in canonical_order:
            if sec_name not in sections_map:
                continue
            section = sections_map.pop(sec_name)
            items_list = list(section["items"].values())
            result.append({
                "name": section["name"],
                "description": section["description"],
                "items": items_list,
            })
        # Append any extra sections not in canonical order
        for sec_name, section in sections_map.items():
            items_list = list(section["items"].values())
            result.append({
                "name": section["name"],
                "description": section["description"],
                "items": items_list,
            })
        return result

    def _format_full_menu(self, structure: List[Dict[str, Any]]) -> str:
        """Formatea la estructura de get_menu_structure en texto legible."""
        lines: List[str] = []
        for section in structure:
            lines.append(f"\n## {section['name']}")
            if section["description"] and not section["items"]:
                # Sección descriptiva sin items (ej. Acompañamientos)
                lines.append(section["description"])
            else:
                for item in section["items"]:
                    parts = [f"  - {item['name']}"]
                    if item["prices"]:
                        parts.append(f"    Precios: {', '.join(item['prices'])}")
                    if item["options"]:
                        parts.append(f"    Opciones: {', '.join(item['options'])}")
                    lines.extend(parts)
        return "\n".join(lines).strip()

    def _format_section_items(self, rows: List[Dict[str, Any]]) -> str:
        """Formatea resultados de get_section_items."""
        items: Dict[str, Dict] = {}
        for row in rows:
            item_name = row.get("item", "")
            if item_name not in items:
                items[item_name] = {"prices": set(), "opts": set()}
            amt = row.get("amount")
            sz = row.get("size")
            if amt:
                price_str = f"${amt}" + (f" ({sz})" if sz else "")
                items[item_name]["prices"].add(price_str)
            opt = row.get("opt")
            if opt:
                items[item_name]["opts"].add(opt)

        lines: List[str] = []
        for item_name, data in items.items():
            parts = [f"- {item_name}"]
            if data["prices"]:
                parts.append(f"  Precios: {', '.join(sorted(data['prices']))}")
            if data["opts"]:
                parts.append(f"  Opciones: {', '.join(sorted(data['opts']))}")
            lines.extend(parts)
        return "\n".join(lines)

    def _format_prices(self, rows: List[Dict[str, Any]]) -> str:
        """Formatea resultados de get_item_price."""
        items: Dict[str, List[str]] = {}
        for row in rows:
            item_name = row["item"]
            if item_name not in items:
                items[item_name] = []
            amt = row.get("amount", "")
            sz = row.get("size")
            price_str = f"${amt}" + (f" ({sz})" if sz else "")
            items[item_name].append(price_str)

        lines: List[str] = []
        for item_name, prices in items.items():
            lines.append(f"{item_name}: {', '.join(prices)}")
        return "\n".join(lines)

    def _format_options(self, rows: List[Dict[str, Any]]) -> str:
        """Formatea resultados de get_item_options."""
        items: Dict[str, List[str]] = {}
        for row in rows:
            item_name = row["item"]
            if item_name not in items:
                items[item_name] = []
            items[item_name].append(row.get("opt", ""))

        lines: List[str] = []
        for item_name, opts in items.items():
            lines.append(f"{item_name}:")
            for opt in opts:
                lines.append(f"  - {opt}")
        return "\n".join(lines)
