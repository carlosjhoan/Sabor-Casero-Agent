#!/usr/bin/env python3
"""
Script de ingesta: lee menu.md y genera data/ontology/menu.ttl.

Uso:
    uv run python scripts/ingest_menu_to_owl.py

El archivo de salida se escribe en data/ontology/menu.ttl (ruta
por defecto configurada en settings.owl_ontology_path).
"""
import re
import sys
import unicodedata
from pathlib import Path
from typing import List, Tuple, Optional


# ---------------------------------------------------------------------------
# Modelos de datos internos
# ---------------------------------------------------------------------------

class MenuItem:
    """Representa un item del menú."""
    def __init__(self, name: str):
        self.name = name
        self.prices: List[Tuple[str, Optional[str]]] = []  # (amount, size)
        self.options: List[str] = []


class MenuSection:
    """Representa una sección del menú."""
    def __init__(self, name: str):
        self.name = name
        self.items: List[MenuItem] = []
        self.description: str = ""


# ---------------------------------------------------------------------------
# Parseador de menu.md
# ---------------------------------------------------------------------------

def parse_menu_md(content: str) -> List[MenuSection]:
    """
    Parsea el contenido de menu.md y retorna una lista de secciones.

    Args:
        content: Contenido completo del archivo menu.md.

    Returns:
        Lista de MenuSection con sus items, precios y opciones.
    """
    sections: List[MenuSection] = []
    current_section: Optional[MenuSection] = None
    current_item: Optional[MenuItem] = None

    # Regex para las líneas significativas
    re_section = re.compile(r"^##\s+SECTION:\s*(.+)$")
    re_item = re.compile(r"^###\s+ITEM:\s*(.+)$")
    re_option = re.compile(r"^####\s+OPTION:\s*(.+)$")
    re_price = re.compile(r"^PRICES?:\s*(.+)$")

    skip_remaining = False  # Saltar bloques ## sin SECTION (NOTES, CONTACT, etc.)

    lines = content.split("\n")
    for raw_line in lines:
        line = raw_line.strip()

        # Saltar líneas vacías
        if not line:
            continue

        # Detectar bloques ## nivel-1 (## Algo) que NO son SECTION
        # Nota: ### ITEM: no debe activar skip porque empieza con ###, no ##
        if re.match(r"^## [A-Z]", line) and not line.startswith("## SECTION"):
            skip_remaining = True
            continue

        # Salir del modo skip al encontrar una SECTION
        if line.startswith("## SECTION"):
            skip_remaining = False

        if skip_remaining:
            continue

        # Saltar líneas de metadatos globales
        if line.startswith("# MENU") or line.startswith("- Source") \
                or line.startswith("- Currency") or line.startswith("- Language") \
                or line.startswith("- Prices") or line.startswith('"'):
            continue

        # Detectar sección
        m = re_section.match(line)
        if m:
            current_section = MenuSection(m.group(1).strip())
            sections.append(current_section)
            current_item = None
            continue

        if current_section is None:
            continue

        # Detectar item explícito (### ITEM:)
        m = re_item.match(line)
        if m:
            current_item = MenuItem(m.group(1).strip())
            current_section.items.append(current_item)
            continue

        # Detectar opción (pertenece al item actual)
        m = re_option.match(line)
        if m and current_item is not None:
            current_item.options.append(m.group(1).strip())
            continue

        # Detectar precio
        m = re_price.match(line)
        if m and current_item is not None:
            price_text = m.group(1).strip()
            _parse_prices(price_text, current_item)
            continue

        # Línea " - Item" (item sin ### ITEM, ej. Sopa)
        if line.startswith("- "):
            item_name = line[2:].strip()
            current_item = MenuItem(item_name)
            current_section.items.append(current_item)
            continue

        # Línea descriptiva (para Acompañamientos y otras secciones
        # sin items con ### ITEM o -)
        if current_section and not current_section.items and not line.startswith("##"):
            if current_section.description:
                current_section.description += " " + line
            else:
                current_section.description = line

    return sections


def _parse_prices(price_text: str, item: MenuItem) -> None:
    """
    Parsea el texto de precio y agrega PriceOption al item.

    Formatos aceptados:
        "15000"
        "13500 (Corriente), 12000 (mini)"
    """
    # Separar por coma para variantes múltiples
    variants = [p.strip() for p in price_text.split(",")]

    for variant in variants:
        # Buscar patrón: "cantidad (tamaño)"
        m = re.match(r"^(\d+)\s*\((.+)\)$", variant)
        if m:
            amount = m.group(1)
            size = m.group(2).strip()
            item.prices.append((amount, size))
        else:
            # Precio único sin tamaño
            m2 = re.match(r"^(\d+)$", variant)
            if m2:
                item.prices.append((m2.group(1), None))


# ---------------------------------------------------------------------------
# Generador de Turtle
# ---------------------------------------------------------------------------

def _to_uri(name: str) -> str:
    """Convierte un nombre a un URI-safe CamelCase.

    Normaliza caracteres acentuados a ASCII (ej. "Proteínas" → "Proteinas")
    y remueve caracteres no alfanuméricos.
    """
    # Normalizar Unicode: separar caracteres de sus acentos
    nfkd = unicodedata.normalize('NFKD', name)
    # Quitar marcas diacríticas (acentos) y quedarse solo con ASCII
    ascii_text = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    # Remover cualquier otro caracter no alfanumérico
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", ascii_text)
    words = cleaned.strip().split()
    return "".join(w.capitalize() for w in words)


def generate_ttl(sections: List[MenuSection]) -> str:
    """
    Genera el contenido Turtle a partir de las secciones parseadas.

    Args:
        sections: Lista de secciones del menú.

    Returns:
        Contenido Turtle como string.
    """
    lines: List[str] = [
        '@prefix : <http://saborcasero.com/menu#> .',
        '@prefix owl: <http://www.w3.org/2002/07/owl#> .',
        '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .',
        '@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .',
        '',
        '# ============================================================',
        '# Ontología — Menú Sabor Casero (generado automáticamente)',
        '# ============================================================',
        '',
        '# --- Clases ---',
        ':MenuItem a owl:Class .',
        ':MenuSection a owl:Class .',
        ':ItemOption a owl:Class .',
        ':PriceOption a owl:Class .',
        '',
        '# --- Propiedades de objeto ---',
        ':hasSection a owl:ObjectProperty .',
        ':hasItem a owl:ObjectProperty .',
        ':hasOption a owl:ObjectProperty .',
        ':hasPriceOption a owl:ObjectProperty .',
        '',
        '# --- Propiedades de dato ---',
        ':sectionName a owl:DatatypeProperty .',
        ':itemName a owl:DatatypeProperty .',
        ':optionName a owl:DatatypeProperty .',
        ':sectionDescription a owl:DatatypeProperty .',
        ':hasAmount a owl:DatatypeProperty .',
        ':hasSize a owl:DatatypeProperty .',
        '',
    ]

    # --- Secciones ---
    for section in sections:
        section_uri = _to_uri(section.name)
        lines.append(f"# SECCIÓN: {section.name}")
        lines.append(f":{section_uri} a :MenuSection ;")
        lines.append(f'    :sectionName "{section.name}" ;')

        if section.description:
            lines.append(f'    :sectionDescription "{section.description}" ;')

        if section.items:
            item_uris = [_to_uri(it.name) for it in section.items]
            items_list = ", ".join(f":{u}" for u in item_uris)
            lines.append(f"    :hasItem {items_list} .")
        else:
            lines[-1] = lines[-1].rstrip(" ;") + " ."

        lines.append("")

        # --- Items de la sección ---
        for item in section.items:
            item_uri = _to_uri(item.name)
            lines.append(f":{item_uri} a :MenuItem ;")
            lines.append(f'    :itemName "{item.name}" ;')

            # Precios
            for amount, size in item.prices:
                price_uri = f"{item_uri}_{_to_uri(size or 'Price')}"
                lines.append(f"    :hasPriceOption :{price_uri} ;")
            for opt_name in item.options:
                opt_uri = f"{item_uri}_{_to_uri(opt_name)}"
                lines.append(f"    :hasOption :{opt_uri} ;")

            # Reemplazar último " ;" por " ."
            if lines[-1].endswith(" ;"):
                lines[-1] = lines[-1][:-2] + " ."
            elif lines[-1].endswith(";"):
                lines[-1] = lines[-1][:-1] + " ."
            else:
                lines[-1] = lines[-1] + " ."
            lines.append("")

            # --- PriceOptions ---
            for amount, size in item.prices:
                price_uri = f"{item_uri}_{_to_uri(size or 'Price')}"
                lines.append(f":{price_uri} a :PriceOption ;")
                lines.append(f'    :hasAmount "{amount}"^^xsd:decimal ;')
                if size:
                    lines.append(f'    :hasSize "{size}" ;')
                lines[-1] = lines[-1][:-2] + " ."
                lines.append("")

            # --- ItemOptions ---
            for opt_name in item.options:
                opt_uri = f"{item_uri}_{_to_uri(opt_name)}"
                lines.append(f":{opt_uri} a :ItemOption ;")
                lines.append(f'    :optionName "{opt_name}" .')
                lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """Punto de entrada: lee menu.md y escribe menu.ttl."""
    # Resolver rutas relativas al directorio raíz del proyecto
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent  # sabor_casero_assistant/

    menu_md_path = project_root / "data" / "documents" / "menu.md"
    ttl_output_path = project_root / "data" / "ontology" / "menu.ttl"

    if not menu_md_path.exists():
        print(f"ERROR: No se encontró {menu_md_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Leyendo menú desde: {menu_md_path}")
    content = menu_md_path.read_text(encoding="utf-8")

    sections = parse_menu_md(content)
    print(f"Secciones encontradas: {len(sections)}")
    for sec in sections:
        print(f"  - {sec.name}: {len(sec.items)} items")

    ttl_content = generate_ttl(sections)

    ttl_output_path.parent.mkdir(parents=True, exist_ok=True)
    ttl_output_path.write_text(ttl_content, encoding="utf-8")
    print(f"Ontología escrita en: {ttl_output_path}")
    print("¡Hecho!")


if __name__ == "__main__":
    main()
