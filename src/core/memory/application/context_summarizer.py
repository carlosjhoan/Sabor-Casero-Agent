# memory/application/services/context_summarizer.py
from typing import Optional, List
import json
from src.infrastructure.llm_client import LLMClient, get_llm_client_for_stage, get_model_for_stage
from src.core.memory.domain.models import ConversationSummary
from src.core.memory.domain.models_memory import ConversationTurn, Entity
from src.core.memory.domain.summary_interface_repository import SummaryRepository
from src.utils.utils import print_section
from src.infrastructure.prompt_manager import get_prompt_manager


class ContextSummarizer:
    """
    Servicio de aplicación que genera resúmenes de conversación.
    Depende de la interfaz, no de la implementación.
    
    P4: También extrae entidades de cada turno si ``semantic_memory_enabled``
    está activo, invocando el callback de extracción a través de MemoryHub.
    """
    
    def __init__(self, summary_repo: SummaryRepository, llm_client: LLMClient = None, memory_hub=None):
        if llm_client is None:
            from src.config.environment import settings
            llm_client = get_llm_client_for_stage("summarizer")
        self.llm_client = llm_client
        self.repo = summary_repo
        self._memory_hub = memory_hub
        
    def set_memory_hub(self, memory_hub) -> None:
        """Inyecta el MemoryHub después de la construcción (evita circular imports)."""
        self._memory_hub = memory_hub
        
    
    async def summarize_turn(
        self,
        session_id: str,
        turn_number: int,
        user_message: str,
        focus: str,
        intents: list,
        order_state: Optional[str] = None,
        assistant_response: str = "",
    ) -> bool:
        """
        Genera un nuevo resumen usando el LLM.
        """
        from src.config.environment import settings
        # 1. Obtener resumen anterior (usando el repositorio)
        previous = await self.repo.get_latest(session_id)

        print_section(head="Resumen previo obtenido", msg=previous.previous_summary if previous else "No previous summary")
        
        # 2. Preparar prompt
        prompt = get_prompt_manager(settings.prompt_fallback_map).get(
            "summary",
            previous_summary=previous.summary_text if previous else "No previous conversation",
            user_message=user_message,
            assistant_response=assistant_response,
            focus=focus,
            intents=", ".join(intents),
            order_state=order_state
        )
        
        # 3. Llamar a LLM
        
        response = await self.llm_client.chat_completion(
            messages=[{"role": "system", "content": prompt}],
            temperature=0.0,
            model=get_model_for_stage("summarizer", settings),
            max_tokens=300,
            stream=False
        )
        
        try:
            # data = json.loads(response)

            # 4. P4: Entity extraction callback (si semantic_memory_enabled)
            await self._extract_entities_from_turn(
                session_id=session_id,
                turn_number=turn_number,
                user_message=user_message,
                assistant_response=assistant_response,
            )
            
            # 5. Crear nuevo resumen
            new_summary = ConversationSummary(
                session_id=session_id,
                turn_number=turn_number,
                previous_summary=previous.summary_text if previous else "",
                summary_text=response,
                current_order_state=order_state,
                source_turns=(previous.source_turns if previous else []) + [turn_number],
                tokens_estimated=len(response)
            )

            # active_references=data.get('active_references', {}),
            # pending_items=data.get('pending_items', []),
            
            # 5. Guardar usando el repositorio
            await self.repo.save(new_summary)

            print_section(
                head=f"Nuevo resumen generado para sesión {session_id}",
                msg=f"Turno: {turn_number}\nResumen: {new_summary.summary_text}\nEstado orden: {new_summary.current_order_state}"
            )
            
            return True
            
        except Exception as e:
            # Fallback
            fallback_msg = await self._fallback_summary(session_id, turn_number, user_message, previous, assistant_response=assistant_response)
            print_section(
                head=f"Fallback summary generated for session {session_id} because of error: {e}",
                msg=f"Turno: {turn_number}\nFallback: {fallback_msg.summary_text}"
            )
            return False
        
    
    async def _extract_entities_from_turn(
        self,
        session_id: str,
        turn_number: int,
        user_message: str,
        assistant_response: str = "",
    ) -> None:
        """
        P4: Extrae entidades estructuradas del turno actual y las persiste
        en memoria semántica vía MemoryHub.

        Solo opera si ``semantic_memory_enabled`` está activo y el
        MemoryHub está configurado.
        """
        from src.config.environment import settings

        if not settings.semantic_memory_enabled:
            return
        if self._memory_hub is None:
            return

        try:
            # Infer user_id desde el session_id (sabor_casero usa session_id
            # con formato que incluye el user_id como prefijo)
            user_id = session_id.split("_")[0] if "_" in session_id else session_id

            turn = ConversationTurn(
                user_id=user_id,
                session_id=session_id,
                turn_number=turn_number,
                user_message=user_message,
                assistant_response=assistant_response,
            )

            entities = self._memory_hub.semantic.extract_from_turn(turn)

            for entity in entities:
                self._memory_hub.store(entity)

            if entities:
                print_section(
                    head=f"P4: {len(entities)} entidades extraídas del turno {turn_number}",
                    msg=", ".join(f"{e.entity_type}: {e.value}" for e in entities),
                )
        except Exception as e:
            # La extracción de entidades NUNCA debe romper el pipeline
            print_section(
                head="P4: Error en extracción de entidades (no crítico)",
                msg=str(e),
            )

    async def _fallback_summary(self, session_id, turn, message, previous, assistant_response="") -> ConversationSummary:
        """Resumen de emergencia si el LLM falla."""
        fallback = ConversationSummary(
            session_id=session_id,
            turn_number=turn,
            summary_text=f"Turno {turn}: {message[:50]}... | Asistente: {assistant_response[:80]}..." if assistant_response else f"Turno {turn}: {message[:50]}...",
            previous_summary=previous.previous_summary if previous else "",
            current_order_state="En proceso",
            source_turns=[turn],
            tokens_estimated=10
        )

        # active_references={},
        # pending_items=[],
        await self.repo.save(fallback)
        return fallback