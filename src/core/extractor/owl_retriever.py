"""
Retriever OWL para el menú del restaurante.

Implementa RetrieverInterface usando OwlClient para consultas SPARQL
deterministas sobre menu.ttl. Solo procesa documentos menu.md;
lanza ValueError para otros documentos.

El ruteo de consultas se realiza mediante un LLM asistido por tools que
explora el menú en tiempo real (resolve_menu_reference, get_item_details,
etc.) y devuelve un MenuQuery estructurado que el OwlRouterMapper valida
y ejecuta contra la ontología.
"""
import json
import logging
from typing import List, Dict, Optional

from src.core.classifier.intent import Detail
from src.core.extractor.retriever_interface import RetrieverInterface
from src.config.environment import settings
from src.infrastructure.owl_client import OwlClient
from src.infrastructure.llm_client import (
    get_llm_client_for_stage,
    get_model_for_stage,
)
from src.core.extractor.owl_router_schema import MenuQuery
from src.core.extractor.owl_router_mapper import OwlRouterMapper
from src.infrastructure.prompt_manager import get_prompt_manager
from src.utils.utils import print_section

logger = logging.getLogger("OwlRetriever")


class OwlRetriever(RetrieverInterface):
    """
    Retriever determinista para el menú usando SPARQL/OWL.

    Utiliza un LLM asistido por tools para clasificar la intención del
    usuario, un OwlRouterMapper para validar y ejecutar la consulta
    contra la ontología del menú.

    Las tools de menú (validate_protein, get_principle_options,
    get_item_details, resolve_menu_reference) permiten al LLM explorar
    el menú en tiempo real en lugar de depender de resúmenes de texto
    frágiles.

    Args:
        owl_client: Instancia opcional de OwlClient. Si no se
            proporciona, se crea una usando la ruta de la configuración.
    """

    def __init__(self, owl_client: OwlClient | None = None):
        self._client = owl_client or OwlClient(settings.owl_ontology_path)
        self._router_mapper = OwlRouterMapper(self._client)
        self._orchestrator = None
        self._init_tool_orchestrator()

    def _init_tool_orchestrator(self) -> None:
        """
        Inicializa el ToolOrchestrator con menu tools para el router.

        Si falla la carga de OwlClient o la creación del orchestrator,
        se deja en None y se usa el fallback a menú completo.
        """
        from src.core.tools import ToolRegistry, register_menu_tools, ToolOrchestrator

        try:
            llm = get_llm_client_for_stage("retriever")
            registry = ToolRegistry()
            register_menu_tools(registry, self._client)
            self._orchestrator = ToolOrchestrator(
                llm_client=llm,
                registry=registry,
                max_turns=3,
                model=get_model_for_stage("retriever", settings),
                temperature=0.1,
            )
            logger.info(
                "Router con %d menu tools",
                len(registry),
            )
        except Exception as e:
            logger.warning(
                "Router: no se pudo inicializar ToolOrchestrator: %s — "
                "usando fallback a menú completo", e
            )

    async def retrieve(
        self, group_by_doc: Dict[str, List[Detail]]
    ) -> List[Detail]:
        """
        Recupera información del menú para cada Detail.

        Args:
            group_by_doc: Diccionario agrupado por nombre de archivo.

        Returns:
            Lista de Details con info_extracted actualizado.

        Raises:
            ValueError: Si algún documento no es 'menu.md'.
        """
        for doc_name, details in group_by_doc.items():
            if doc_name != "menu.md":
                raise ValueError(
                    f"OwlRetriever solo maneja menu.md, recibió: {doc_name}"
                )
            for detail in details:
                try:
                    extracted_info = await self._route_query(
                        detail.segment, detail.focus
                    )
                    detail.info_extracted = extracted_info or ""
                    if extracted_info:
                        preview = extracted_info[:120].replace("\n", " | ")
                        print(f"  🦉 OwlRetriever → '{detail.segment}': {preview}")
                except Exception as e:
                    logger.error(
                        "Error recuperando info para '%s': %s",
                        detail.segment,
                        e,
                    )
                    detail.info_extracted = (
                        "Ha ocurrido un error al recuperar la información "
                        "del menú."
                    )

        return [
            detail
            for details in group_by_doc.values()
            for detail in details
        ]

    async def get_context(self, query: str, doc_name: str) -> str:
        """
        Retrieve context for a specific document.

        Only ``menu.md`` is supported natively via SPARQL/OWL.
        Any other document returns an empty string with a warning.

        Args:
            query: The user's search query.
            doc_name: Target document filename.

        Returns:
            Context string or empty string if unsupported.
        """
        if doc_name != "menu.md":
            logger.warning(
                "OwlRetriever.get_context called for '%s' — "
                "only menu.md is supported, returning empty.", doc_name,
            )
            return ""

        # Delegate to the existing route-query flow via retrieve()
        # ponytail: reuse single-doc retrieve for menu queries
        from src.core.classifier.intent import Detail
        details = await self.retrieve({"menu.md": [
            Detail(segment=query, focus="", doc_name="menu.md", topic="menu"),
        ]})
        return details[0].info_extracted if details else ""

    # ------------------------------------------------------------------
    # Ruteo de consultas vía LLM asistido por tools
    # ------------------------------------------------------------------

    async def _route_query(self, segment: str, focus: str) -> Optional[str]:
        """
        Clasifica la consulta del usuario vía LLM con tools, valida
        contra la ontología y ejecuta la consulta SPARQL correspondiente.

        Flujo:
        1. Envía segment + focus + tools al LLM
        2. LLM puede llamar tools para explorar el menú
        3. LLM responde con JSON estructurado (MenuQuery)
        4. Parsea el JSON como MenuQuery
        5. Valida sección/ítem contra la ontología
        6. Ejecuta el método correcto de OwlClient

        Args:
            segment: Texto de la consulta del usuario.
            focus: Contexto adicional del clasificador.

        Returns:
            Texto con la información recuperada, o None si no se
            pudo clasificar/validar (el caller cae a menú completo).
        """
        # --- Cargar y formatear prompt (sin menu_summary — se usan tools) ---
        try:
            system_prompt = get_prompt_manager(settings.prompt_fallback_map).get(
                "router",
                segment=segment,
                focus=focus,
            )
        except Exception as e:
            logger.error("Error cargando prompt del router: %s", e)
            return None

        # --- Llamar al LLM con tools ---
        try:
            if self._orchestrator is not None:
                response_text, tool_calls = await self._orchestrator.run(
                    messages=[{"role": "system", "content": system_prompt}],
                    tool_choice="auto",
                )
                if tool_calls:
                    print(f"  🛠️ Router usó {len(tool_calls)} tool(s): "
                          f"{[t.name for t in tool_calls]}")
            else:
                # Fallback sin tools (comportamiento original simplificado)
                llm = get_llm_client_for_stage("retriever")
                model = get_model_for_stage("retriever", settings)
                response_text = await llm.chat_completion(
                    messages=[{"role": "system", "content": system_prompt}],
                    model=model,
                    temperature=0.1,
                )
                if not isinstance(response_text, str):
                    response_text = str(response_text)

            # --- Parsear respuesta como JSON MenuQuery ---
            # Buscar el primer bloque JSON en la respuesta
            response_text = response_text.strip()
            if not response_text:
                logger.warning("Router: respuesta vacía del LLM")
                return None

            try:
                # Intentar parse directo
                query = MenuQuery.model_validate_json(response_text)
            except Exception:
                # Fallback: buscar bloque JSON entre llaves
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        query = MenuQuery.model_validate_json(json_match.group())
                    except Exception as e:
                        logger.warning(
                            "Router: JSON inválido en respuesta: %s — %s",
                            response_text[:100], e,
                        )
                        return None
                else:
                    logger.warning(
                        "Router: no se encontró JSON en respuesta: %s",
                        response_text[:100],
                    )
                    return None

            print_section(
                head="🦉 ROUTER RESULT",
                msg=f"intent={query.intent} section={query.section} item={query.item} conf={query.confidence}",
                symbol="·",
            )

        except Exception as e:
            logger.error("LLM router error: %s", e)
            return None

        # --- Validar contra ontología ---
        if not self._router_mapper.validate(query):
            logger.warning(
                "Router: validación falló para intent=%s section=%s item=%s",
                query.intent,
                query.section,
                query.item,
            )
            return None

        # --- Ejecutar ---
        return self._router_mapper.execute(query)
