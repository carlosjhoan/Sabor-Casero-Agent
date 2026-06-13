# order/application/processors/thought_generator.py

import logging
import re
from typing import List, Dict, Any, Optional
from src.utils.utils import print_section, safe_json_string
from src.infrastructure.prompt_manager import get_prompt_manager
from src.infrastructure.llm_client import LLMClient, get_llm_client_for_stage
from src.core.order.domain.session_repository_interface import SessionRepository
from src.core.order.domain.order_repository_interface import OrderRepository
from src.core.order.application.thought_output import ThoughtOutput, AmbiguityDeclaration


logger = logging.getLogger("ThoughtGenerator")

AMBIGUITY_LINE_PATTERN = re.compile(
    r'Ambigüedad:\s*(Sí|No)\s*(?:[—\-\.–:]\s*(.*))?',
    re.IGNORECASE | re.MULTILINE
)


class ThoughtGenerator:
    """
    [DEPRECATED] — Use synthetic order tools (add-item, remove-item, update-item,
    get-order, confirm-order, cancel-order) via SkillToolAdapter when
    use_llm_planner=True. Kept for legacy pipeline (use_llm_planner=False).

    Responsabilidad ÚNICA: Generar el razonamiento (thought) a partir de 
    los segmentos de orden y el contexto de conversación.
    
    Flujo:
    1. LLM devuelve texto libre con razonamiento en español.
    2. El texto termina con una línea explícita de declaración de ambigüedad.
    3. Se parsea esa línea para construir AmbiguityDeclaration.
    
    Si el LLM devuelve vacío, se usa fallback resiliente (el pipeline continúa).
    
    Desde Fase 3/5, dispone de un ToolOrchestrator con menu tools
    (validate_protein, get_principle_options, get_item_details,
    resolve_menu_reference) para que el LLM valide items contra la
    ontología en tiempo real vía function calling.
    """
    
    def __init__(
        self,
        session_repository: SessionRepository,
        order_repository: OrderRepository,
        llm_client: LLMClient = None,
        owl_client: Optional["OwlClient"] = None,
    ):
        from src.config.environment import settings
        from src.infrastructure.llm_client import get_model_for_stage
        
        if llm_client is None:
            llm_client = get_llm_client_for_stage("thought_generator")
        self.llm_client = llm_client
        self.session_repository = session_repository
        self.order_repository = order_repository
        
        # ── ToolOrchestrator con menu tools (opcional) ──
        self.orchestrator = None
        self._init_tool_orchestrator(owl_client, settings)
    
    def _init_tool_orchestrator(
        self,
        owl_client: Optional["OwlClient"],
        settings,
    ) -> None:
        """
        Inicializa el ToolOrchestrator con menu tools.
        
        Si no se puede cargar OwlClient (falta ontology), el orchestrator
        se queda en None y se usa chat_completion directo (sin tools).
        """
        from src.infrastructure.llm_client import get_model_for_stage
        from src.core.tools import ToolRegistry, register_menu_tools, ToolOrchestrator
        
        if owl_client is None:
            try:
                from src.infrastructure.owl_client import OwlClient
                owl_client = OwlClient(settings.owl_ontology_path)
            except Exception as e:
                logger.warning(
                    "No se pudo cargar OwlClient para tools: %s — "
                    "ThoughtGenerator operará sin tools", e
                )
                return
        
        try:
            registry = ToolRegistry()
            register_menu_tools(registry, owl_client)
            self.orchestrator = ToolOrchestrator(
                llm_client=self.llm_client,
                registry=registry,
                max_turns=5,
                model=get_model_for_stage("thought_generator", settings),
                temperature=0.1,
            )
            logger.info(
                "ThoughtGenerator con %d menu tools",
                len(registry),
            )
        except Exception as e:
            logger.warning(
                "Error inicializando ToolOrchestrator: %s — "
                "ThoughtGenerator operará sin tools", e
            )
    
    async def generate_thought(
        self,
        ordering_segments: list,
        session_id: str,
        summary_conversation: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Genera un thought (razonamiento) sobre qué acciones realizar.
        
        Returns:
            Dict con:
            - success: bool
            - thought: str (el razonamiento generado, texto libre)
            - ambiguity: AmbiguityDeclaration (parseada de la línea final)
            - context: Dict (contexto usado para generación)
            - error: Optional[str]
        """
        # Inicializar fuera del try para disponer en except si algo falla
        context = None
        processor_input = None
        
        try:
            # 1. Cargar contexto de orden
            context = await self._load_order_context(session_id)
            
            # 2. Preparar input para LLM
            processor_input = self._prepare_processor_input(ordering_segments)
            
            # 3. Generar thought como TEXTO LIBRE con línea de ambigüedad
            from src.config.environment import settings
            from src.infrastructure.llm_client import get_model_for_stage
            
            # Obtener prompt desde PromptManager (Langfuse + fallback a archivo)
            prompt = get_prompt_manager(settings.prompt_fallback_map).get(
                "thought-generator",
                current_order_state=context["summary"],
                summary_conversation=summary_conversation or "",
                subquery_focus=processor_input,
            )
            
            # Llamada a LLM — con tools si el Orchestrator está disponible
            if self.orchestrator is not None:
                thought_text, tool_calls = await self.orchestrator.run(
                    messages=[{"role": "system", "content": prompt}],
                    tool_choice="auto",
                )
                if tool_calls:
                    print(f"🔧 Thought usó {len(tool_calls)} tool(s): "
                          f"{[t.name for t in tool_calls]}")
            else:
                # Fallback sin tools (comportamiento original)
                response = await self.llm_client.chat_completion(
                    messages=[{"role": "system", "content": prompt}],
                    temperature=0.1,
                    model=get_model_for_stage("thought_generator", settings),
                    stream=False,
                )
                thought_text = response.strip() if isinstance(response, str) else str(response).strip()
            
            # Validar contenido mínimo
            if not thought_text or len(thought_text) < 20:
                print(f"⚠️ Thought vacío o demasiado corto ({len(thought_text)} chars) — usando fallback")
                return {
                    "success": True,
                    "thought": "El asistente no pudo generar razonamiento detallado. "
                               "Se procederá con acciones por defecto basadas en los segmentos de entrada.",
                    "ambiguity": AmbiguityDeclaration(has_ambiguity=False),
                    "context": context,
                    "processor_input": processor_input,
                    "error": "Thought demasiado corto o vacío"
                }
            
            # Parsear línea de ambigüedad del texto libre
            ambiguity = self._parse_ambiguity_line(thought_text)
            
            print(f"✅ Thought generado ({len(thought_text)} chars) — ambigüedad={ambiguity.has_ambiguity}")
            
            return {
                "success": True,
                "thought": thought_text,
                "ambiguity": ambiguity,
                "context": context,
                "processor_input": processor_input
            }
            
        except Exception as e:
            print(f"💥 Error en generate_thought: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback resiliente: el pipeline CONTINÚA aunque falle el thought
            fallback_context = context or {"summary": "No disponible", "order_id": None, "session": None}
            return {
                "success": True,
                "thought": "El asistente no pudo generar razonamiento detallado. "
                           "Se procederá con acciones por defecto basadas en los segmentos de entrada.",
                "ambiguity": AmbiguityDeclaration(has_ambiguity=False),
                "context": fallback_context,
                "error": str(e)
            }
    
    def _parse_ambiguity_line(self, thought_text: str) -> AmbiguityDeclaration:
        """
        Parsea la línea explícita de ambigüedad del texto generado.
        
        La LLM debe terminar su razonamiento con una línea como:
          Ambigüedad: No. Se puede proceder con la planificación de acciones.
          Ambigüedad: Sí — El pernil no está disponible en tamaño mini.
        
        Si no encuentra la línea, asume has_ambiguity=False (seguro por defecto).
        """
        match = AMBIGUITY_LINE_PATTERN.search(thought_text)
        
        if match:
            has_ambiguity = match.group(1).lower() == 'sí'
            description = match.group(2).strip() if match.group(2) else ""
            
            if has_ambiguity:
                return AmbiguityDeclaration(
                    has_ambiguity=True,
                    ambiguous_topics=[description] if description else [],
                    clarifying_question=description if description else None,
                )
        
        # No se encontró línea de ambigüedad, o dice "No" → safe default
        return AmbiguityDeclaration(has_ambiguity=False)
    
    async def _load_order_context(self, session_id: str) -> Dict[str, Any]:
        """Carga contexto de orden"""
        session = self.session_repository.get_session(session_id)
        order_id = session.order_id if session else None
        order = None
        
        summary = "El cliente no ha realizado pedido"
        if order_id:
            order = self.order_repository.get_order_by_id(order_id)
            summary = order.to_summary() if order else summary
        
        print_section(head="CONTEXTO DE ORDEN", msg=summary, symbol=":: ")
        
        return {
            "session": session,
            "order_id": order_id,
            "summary": summary
        }
    
    def _prepare_processor_input(self, ordering_segments: list) -> str:
        """Formatea segments para el prompt.
        
        Soporta Detail objects (Pydantic), dicts (de model_dump o LLM tool call),
        y strings (fallback del LLM cuando no tiene schema detallado).
        """
        print("\n--- SEGMENTOS DE ORDENING RECIBIDOS ---")
        
        input_lines = []
        for idx, raw in enumerate(ordering_segments):
            # ── Extraer campos según el tipo ──
            if isinstance(raw, str):
                seg_text = raw
                focus = ""
                info = "{}"
                query_type = "ORDERING"
            elif isinstance(raw, dict):
                seg_text = raw.get("segment", str(raw))
                focus = raw.get("focus", "")
                info = safe_json_string(raw.get("info_extracted", {}))
                query_type = raw.get("query_type", "ORDERING")
            else:
                # Detail object (Pydantic)
                seg_text = raw.segment
                focus = raw.focus
                info = safe_json_string(raw.info_extracted)
                query_type = raw.query_type

            focus_line = f"User says: {seg_text} + Focus: {focus}"
            input_lines.append(f"Segmento {idx + 1}:")
            input_lines.append(f"  Focus: {focus_line}")
            input_lines.append(f"  Info: {info}\n")
            
            print(f"   Segment {idx + 1}:")
            print(f"   Focus: {focus_line}")
            print(f"   Query Type: {query_type}\n")
        
        processor_input = "\n".join(input_lines)
        print_section(head="Injected focus and info into LLM", msg=processor_input, symbol=":: ")
        
        return processor_input
