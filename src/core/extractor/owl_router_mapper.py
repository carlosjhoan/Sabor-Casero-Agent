"""
Mapper que valida y ejecuta MenuQuery contra la ontología del menú.

OwlRouterMapper recibe un MenuQuery (generado por el LLM), verifica
que los nombres de sección e ítem existan en la ontología TTL, y
dispara el método correcto de OwlClient según el intent.
"""
import logging
from typing import Optional

from src.infrastructure.owl_client import OwlClient
from src.core.extractor.owl_router_schema import MenuQuery

logger = logging.getLogger("OwlRouterMapper")


class OwlRouterMapper:
    """
    Valida y ejecuta consultas MenuQuery contra la ontología.

    En __init__ carga los nombres conocidos de secciones e ítems
    desde el OwlClient para usarlos como referencia de validación.

    Args:
        owl_client: Instancia de OwlClient con la ontología cargada.
    """

    def __init__(self, owl_client: OwlClient):
        self._client = owl_client
        self._known_sections: set[str] = owl_client.get_section_names()
        self._known_items: set[str] = owl_client.get_item_names()
        logger.debug(
            "Mapper cargado: %d secciones, %d ítems",
            len(self._known_sections),
            len(self._known_items),
        )

    # ------------------------------------------------------------------
    # Validación
    # ------------------------------------------------------------------

    def validate(self, query: MenuQuery) -> bool:
        """
        Valida que los campos del MenuQuery correspondan a nombres
        conocidos en la ontología.

        Reglas:
        - Si query.section está presente, debe existir en la ontología.
        - Si query.item está presente, debe existir en la ontología.
        - full_menu y unknown no requieren validación de campos.

        Args:
            query: MenuQuery a validar.

        Returns:
            True si la consulta es válida, False en caso contrario.
        """
        if query.intent in ("full_menu", "unknown"):
            return True

        if query.intent == "section_items":
            if not query.section:
                logger.warning("section_items sin section")
                return False
            if query.section not in self._known_sections:
                logger.warning(
                    "Sección desconocida: '%s' (conocidas: %s)",
                    query.section,
                    sorted(self._known_sections),
                )
                return False
            return True

        if query.intent in ("item_price", "item_options"):
            if not query.item:
                logger.warning("%s sin item", query.intent)
                return False
            # Búsqueda exacta o parcial en ítems conocidos
            if not self._item_exists(query.item):
                logger.warning(
                    "Ítem desconocido: '%s' (conocidos: %d)",
                    query.item,
                    len(self._known_items),
                )
                return False
            return True

        logger.warning("Intento desconocido: %s", query.intent)
        return False

    def _item_exists(self, item_name: str) -> bool:
        """
        Verifica si un nombre de ítem existe, probando coincidencia
        exacta primero y luego substring.

        Args:
            item_name: Nombre del ítem a buscar.

        Returns:
            True si se encuentra alguna coincidencia.
        """
        item_lower = item_name.lower().strip()

        # Coincidencia exacta (case-insensitive)
        for known in self._known_items:
            if known.lower() == item_lower:
                return True

        # Coincidencia por substring (el LLM puede dar nombre parcial)
        for known in self._known_items:
            if item_lower in known.lower() or known.lower() in item_lower:
                return True

        return False

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------

    def execute(self, query: MenuQuery) -> Optional[str]:
        """
        Ejecuta el MenuQuery contra OwlClient según el intent.

        Args:
            query: MenuQuery validado.

        Returns:
            Texto con la información solicitada, o None si el intent
            es unknown o no se pudo ejecutar.
        """
        try:
            if query.intent == "full_menu":
                return self._client.get_full_menu()

            if query.intent == "section_items":
                return self._client.get_section_items(query.section)

            if query.intent == "item_price":
                return self._client.get_item_price(query.item)

            if query.intent == "item_options":
                return self._client.get_item_options(query.item)

            if query.intent == "unknown":
                return None

            logger.warning("Intento no manejado: %s", query.intent)
            return None

        except Exception as e:
            logger.error("Error ejecutando MenuQuery: %s", e)
            return None
