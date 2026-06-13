"""
Menu tools — herramientas de dominio para function calling sobre la ontología.

Cada tool es una operación semántica del negocio (validar proteína, consultar
principios, etc.) que encapsula una o más consultas SPARQL contra el OwlClient.

Uso:
    registry = ToolRegistry()
    register_menu_tools(registry, owl_client)
    # registry.to_openai_list() → tools list para LLM API
"""

from __future__ import annotations
import logging
from typing import Optional

from src.core.tools.tool import Tool, ToolRegistry, ToolResult
from src.infrastructure.owl_client import OwlClient

logger = logging.getLogger("MenuTools")


# ======================================================================
# Handlers — lógica de cada tool
# ======================================================================

async def _handle_validate_protein(
    owl: OwlClient, protein_name: str
) -> ToolResult:
    """
    Valida si una proteína existe en el menú.

    Busca en la sección Proteínas items cuyo nombre contenga
    ``protein_name`` (case-insensitive). Devuelve los items
    encontrados con sus precios y opciones.

    Args:
        protein_name: Nombre o parte del nombre de la proteína
            (ej: "pechuga", "cerdo", "pescado").
    """
    protein_name = protein_name.strip()
    if not protein_name:
        return ToolResult(
            success=False,
            error="Debe proporcionar un nombre de proteína para validar."
        )

    # Obtener todos los items de la sección Proteínas
    try:
        items_text = owl.get_section_items("Proteínas")
    except Exception as e:
        logger.error("Error consultando Proteínas: %s", e)
        return ToolResult(
            success=False,
            error=f"No se pudo consultar la sección Proteínas: {e}"
        )

    if not items_text or "No hay información" in items_text:
        return ToolResult(
            success=True,
            value="No hay proteínas registradas en el menú."
        )

    # Buscar coincidencias (case-insensitive)
    lines = items_text.split("\n")
    matched: list[str] = []
    current_item: str | None = None
    protein_lower = protein_name.lower()

    for line in lines:
        if line.startswith("- "):
            current_item = line[2:].strip()
            if protein_lower in current_item.lower():
                matched.append(line)
        elif current_item and protein_lower in current_item.lower():
            matched.append(line)
        elif matched:
            # Si ya estamos dentro de un match, seguimos acumulando
            # líneas de precios/opciones hasta el próximo item
            if line.startswith("  "):
                matched.append(line)
            else:
                current_item = None

    # Si no hay coincidencias exactas, escanear de nuevo
    # pero esta vez línea por línea
    if not matched:
        for line in lines:
            if protein_lower in line.lower():
                matched.append(line)

    if not matched:
        # Listar las proteínas disponibles para ayudar al LLM
        available = [line[2:].strip() for line in lines if line.startswith("- ")]
        return ToolResult(
            success=True,
            value=(
                f"'{protein_name}' no encontrado en Proteínas. "
                f"Proteínas disponibles: {', '.join(available)}"
            )
        )

    result = "\n".join(matched)
    return ToolResult(success=True, value=result)


async def _handle_get_principle_options(
    owl: OwlClient, protein_name: Optional[str] = None
) -> ToolResult:
    """
    Obtiene las opciones de principio disponibles.

    Args:
        protein_name: Si se proporciona, se incluye en la respuesta
            para dar contexto (la ontología actual no filtra principios
            por proteína — todas las proteínas usan los mismos principios).
    """
    try:
        principles_text = owl.get_section_items("Principio")
    except Exception as e:
        logger.error("Error consultando Principio: %s", e)
        return ToolResult(
            success=False,
            error=f"No se pudo consultar la sección Principio: {e}"
        )

    if not principles_text or "No hay información" in principles_text:
        # Podría ser una sección descriptiva — devolver un mensaje útil
        return ToolResult(
            success=True,
            value="No hay información de principios disponible en el menú."
        )

    if protein_name:
        return ToolResult(
            success=True,
            value=(
                f"Para '{protein_name}', los principios disponibles son:\n"
                f"{principles_text}"
            )
        )

    return ToolResult(success=True, value=principles_text)


async def _handle_get_item_details(
    owl: OwlClient, item_name: str
) -> ToolResult:
    """
    Obtiene todos los detalles de un item del menú.

    Unifica precio, opciones y cualquier otra información disponible
    en una sola respuesta estructurada.

    Args:
        item_name: Nombre del item (puede ser parcial, ej: "pechuga",
            "bandeja mixta", "lomo").
    """
    item_name = item_name.strip()
    if not item_name:
        return ToolResult(
            success=False,
            error="Debe proporcionar un nombre de item."
        )

    parts: list[str] = []
    errors: list[str] = []

    try:
        price_info = owl.get_item_price(item_name)
        if price_info and "(No se encontró" not in price_info:
            parts.append(f"Precios:\n{price_info}")
    except Exception as e:
        errors.append(f"Error obteniendo precio: {e}")

    try:
        options_info = owl.get_item_options(item_name)
        if options_info and "(No se encontraron" not in options_info:
            parts.append(f"Opciones:\n{options_info}")
    except Exception as e:
        errors.append(f"Error obteniendo opciones: {e}")

    if not parts:
        # Intentar buscar como sección
        try:
            section_info = owl.get_section_items(item_name.capitalize())
            if section_info and "No hay información" not in section_info:
                parts.append(f"Sección '{item_name}':\n{section_info}")
        except Exception:
            pass

    if not parts:
        msg = f"No se encontró información para '{item_name}' en el menú."
        if errors:
            msg += f" Errores: {'; '.join(errors)}"
        return ToolResult(success=True, value=msg)

    result = "\n\n".join(parts)
    if errors:
        result += f"\n\n(Nota: {'; '.join(errors)})"

    return ToolResult(success=True, value=result)


async def _handle_resolve_menu_reference(
    owl: OwlClient, text: str
) -> ToolResult:
    """
    Resuelve texto libre a referencias del menú.

    Busca en todo el menú (secciones, items, opciones) elementos
    que coincidan con el texto dado. Crucial para cuando el LLM
    recibe lenguaje natural ("quiero pechuga", "dame lomo") y
    necesita saber a qué items concretos del menú se refiere.

    Args:
        text: Texto libre del usuario (ej: "pechuga", "bandeja",
            "lomo de cerdo", "pollo", "pescado").
    """
    text = text.strip()
    if not text:
        return ToolResult(
            success=False,
            error="Debe proporcionar texto para buscar en el menú."
        )

    text_lower = text.lower()
    results: list[str] = []
    seen: set[str] = set()

    # 1. Buscar en nombres de items (más preciso)
    try:
        all_items = owl.get_item_names()
        for item in sorted(all_items):
            if text_lower in item.lower():
                if item not in seen:
                    seen.add(item)
                    # Obtener detalles de este item
                    try:
                        price = owl.get_item_price(item)
                        opts = owl.get_item_options(item)
                        details = [f"  - {item}"]
                        if price and "(No se encontró" not in price:
                            details.append(f"    {price}")
                        if opts and "(No se encontraron" not in opts:
                            details.append(f"    Opciones: {opts}")
                        results.extend(details)
                    except Exception:
                        results.append(f"  - {item}")
    except Exception as e:
        logger.warning("Error buscando items para '%s': %s", text, e)

    # 2. Buscar en nombres de secciones
    if not results:
        try:
            sections = owl.get_section_names()
            for section in sorted(sections):
                if text_lower in section.lower():
                    sec_text = owl.get_section_items(section)
                    if sec_text:
                        results.append(f"\nSección '{section}':\n{sec_text}")
                        seen.add(f"__section__{section}")
        except Exception as e:
            logger.warning("Error buscando secciones: %s", e)

    # 3. Si no hay resultados, dar un resumen útil
    if not results:
        try:
            summary = owl.get_menu_summary()
            return ToolResult(
                success=True,
                value=(
                    f"'{text}' no coincide con ningún item del menú. "
                    f"Resumen del menú: {summary}"
                )
            )
        except Exception:
            return ToolResult(
                success=True,
                value=f"'{text}' no coincide con ningún elemento del menú."
            )

    return ToolResult(success=True, value="\n".join(results))


# ======================================================================
# Registro
# ======================================================================

def register_menu_tools(registry: ToolRegistry, owl: OwlClient) -> None:
    """
    Registra todas las tools de menú en un ToolRegistry.

    Args:
        registry: ToolRegistry donde registrar las tools.
        owl: Instancia de OwlClient con la ontología cargada.
    """
    registry.register(Tool(
        name="validate_protein",
        description=(
            "Valida si una proteína existe en el menú. "
            "Útil cuando el usuario pide una proteína (carne, pollo, pescado, "
            "cerdo, pechuga, pernil, etc.) y necesitas verificar que esté "
            "disponible y en qué presentaciones (tamaños, precios, opciones)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "protein_name": {
                    "type": "string",
                    "description": (
                        "Nombre de la proteína a validar. "
                        "Ej: 'pechuga', 'cerdo', 'carne', 'pescado', 'pollo'."
                    ),
                },
            },
            "required": ["protein_name"],
        },
        handler=lambda **kw: _handle_validate_protein(owl, **kw),
    ))

    registry.register(Tool(
        name="get_principle_options",
        description=(
            "Obtiene las opciones de principio (frijoles, lentejas, "
            "garbanzos, verduras) disponibles en el menú. "
            "Usar cuando el usuario pregunta '¿qué principios hay?' o "
            "quiere saber qué puede elegir como principio para su plato."
        ),
        parameters={
            "type": "object",
            "properties": {
                "protein_name": {
                    "type": "string",
                    "description": (
                        "Opcional. Nombre de la proteína elegida, para "
                        "contexto en la respuesta."
                    ),
                },
            },
            "required": [],
        },
        handler=lambda **kw: _handle_get_principle_options(owl, **kw),
    ))

    registry.register(Tool(
        name="get_item_details",
        description=(
            "Obtiene todos los detalles de un item del menú: precio(s), "
            "tamaños disponibles (corriente/mini), y opciones "
            "(salsas, preparaciones). Usar cuando necesites información "
            "completa sobre un plato específico."
        ),
        parameters={
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": (
                        "Nombre del item a consultar. Puede ser parcial "
                        "(ej: 'pechuga' encuentra todos los tipos de "
                        "pechuga)."
                    ),
                },
            },
            "required": ["item_name"],
        },
        handler=lambda **kw: _handle_get_item_details(owl, **kw),
    ))

    registry.register(Tool(
        name="resolve_menu_reference",
        description=(
            "Resuelve texto libre del usuario a items concretos del menú. "
            "Busca en todo el menú (secciones, items, opciones) cualquier "
            "coincidencia con el texto dado. "
            "Usar cuando NO estás seguro de si lo que pide el usuario "
            "existe en el menú — esta tool busca automáticamente y te "
            "dice qué items coinciden."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Texto libre del usuario a buscar en el menú. "
                        "Ej: 'pechuga', 'bandeja', 'lomo', 'pollo', "
                        "'pescado', 'cerdo BBQ'."
                    ),
                },
            },
            "required": ["text"],
        },
        handler=lambda **kw: _handle_resolve_menu_reference(owl, **kw),
    ))
