from typing import Dict, Any, Optional, List
from src.core.classifier.intent import UserQueryClassifier, Detail, QueryType
from src.core.order.domain.models import Order
from .order_response_builder import OrderResponseBuilder, OrderChecklist
from .info_response_builder import InfoResponseBuilder
from .response_mixer import ResponseMixer
from langfuse import observe
from src.utils.utils import print_section
from src.infrastructure.prompt_manager import get_prompt_manager


class ResponseBuilder:
    """
    Constructor principal de respuestas.
    
    Coordina:
    1. OrderResponseBuilder → respuestas enfocadas a pedido
    2. InfoResponseBuilder → respuestas enfocadas a información
    3. ResponseMixer → combina ambas según reglas estructuradas
    4. LLM Call → formatea la respuesta de manera natural (build_hybrid)
    
    Uso:
        builder = ResponseBuilder(llm_client=client)
        response = await builder.build_hybrid(
            classification=classification,
            order_state=order,
            orchestrator_result=orchestrator_result,
            user_message=message,
            conversation_history=history,
            brand_voice_path=settings.brand_voice_path,
            settings=settings
        )
    """

    def __init__(self, llm_client=None, extractor=None, tracker=None):
        self.order_builder = OrderResponseBuilder(extractor=extractor, tracker=tracker)
        self.info_builder = InfoResponseBuilder()
        self.mixer = ResponseMixer()
        self.llm_client = llm_client
        self.extractor = extractor

    def build(
        self,
        classification: UserQueryClassifier,
        order_state: Optional[Order] = None,
        orchestrator_result: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Construye la respuesta final mixeando pedido e información (SIN LLM).
        Este método es síncrono y usa solo reglas predefinidas.

        Args:
            classification: Resultado de clasificación (contiene topic_details)
            order_state: Estado actual del pedido (si existe)
            orchestrator_result: Resultado del OrderOrchestrator

        Returns:
            Respuesta final lista para enviar al usuario
        """
        print_section(
            head="🏗️ ResponseBuilder - Construyendo respuesta (sin LLM)",
            msg=f"Topic details: {len(classification.topic_details)} | Order: {'Sí' if order_state else 'No'}",
            symbol="="
        )

        topic_details = classification.topic_details

        ordering_segments = self._filter_ordering_segments(topic_details)
        consulting_segments = self._filter_consulting_segments(topic_details)

        order_response = ""
        if ordering_segments:
            order_response = self.order_builder.process(
                ordering_segments=ordering_segments,
                order_state=order_state,
                orchestrator_result=orchestrator_result
            )

        info_response = ""
        if consulting_segments:
            info_response = self.info_builder.process(
                info_segments=consulting_segments
            )

        final_response = self.mixer.combine(
            order_response=order_response,
            info_response=info_response,
            topic_details=topic_details,
            order_state=order_state
        )

        return final_response

    @observe(name="build_hybrid")
    async def build_hybrid(
        self,
        classification: UserQueryClassifier,
        order_state: Optional[Order] = None,
        orchestrator_result: Optional[Dict[str, Any]] = None,
        user_message: str = "",
        conversation_history: str = "",
        extracted_info: Optional[List[Dict[str, Any]]] = None,
        prompt_template_path: str = "prompts/response/response_generator_prompt_v2.0.txt",
        brand_voice_path: str = None,
        settings = None,
        user_preferences_context: str = "",
    ) -> str:
        """
        Construye la respuesta usando componentes estructurados + LLM.
        
        Flujo:
        1. Genera componentes (order_response, info_response) con reglas
        2. Combina con ResponseMixer
        3. Llama al LLM para formatear naturalmente

        Args:
            classification: Resultado de clasificación
            order_state: Estado actual del pedido
            orchestrator_result: Resultado del OrderOrchestrator
            user_message: Mensaje original del usuario
            conversation_history: Resumen de conversación previa
            extracted_info: Resultados del pipeline RAG (items con scores, nombres, etc.)
            prompt_template_path: Ruta del template de prompt
            brand_voice_path: Ruta del archivo de brand voice
            settings: Configuración del sistema

        Returns:
            Respuesta final formateada por el LLM
        """
        # print_section(
        #     head="🏗️ ResponseBuilder - Construyendo respuesta HÍBRIDA (LLM)",
        #     msg=f"Topic details: {len(classification.topic_details)} | Order: {'Sí' if order_state else 'No'}",
        #     symbol="="
        # )

        if not self.llm_client:
            from src.infrastructure.llm_client import get_llm_client_for_stage
            if settings:
                self.llm_client = get_llm_client_for_stage("response")
            else:
                raise ValueError("LLM client no proporcionado y settings no disponible")

        # Accept both Pydantic object (legacy path) and dict (skill path)
        if isinstance(classification, dict):
            from src.core.classifier.intent import UserQueryClassifier
            classification = UserQueryClassifier(**classification)
        topic_details = classification.topic_details

        # Step 0: Verificar si hay ambigüedad que requiera clarificación
        needs_clarification = orchestrator_result.get("needs_clarification", False) if orchestrator_result else False
        ambiguity_context = orchestrator_result.get("ambiguity_context", "") if orchestrator_result else ""

        # Step 1: Separar segmentos
        ordering_segments = self._filter_ordering_segments(topic_details)
        consulting_segments = self._filter_consulting_segments(topic_details)

        # print_section(
        #     head="📊 Segmentos clasificados",
        #     msg=f"Order: {len(ordering_segments)} | Info: {len(consulting_segments)}",
        #     symbol="-"
        # )

        # Step 2: Generar componentes estructurados (usar método async para retrieval)
        order_response = ""
        next_field = "none"
        base_question = ""
        checklist_summary = "Sin pedido activo"
        checklist_options = ""

        # Info response es independiente — procesar siempre
        info_response = ""
        if consulting_segments:
            info_response = self.info_builder.process(
                info_segments=consulting_segments
            )

        if needs_clarification:
            print_section(
                head="🔍 AMBIGÜEDAD DETECTADA — Modo clarificación activado",
                msg="Saltando procesamiento de orden, se preguntará al usuario",
                symbol="❓"
            )
        elif ordering_segments:
            # Usar método async si hay extractor, si no usar el síncrono
            if self.extractor and hasattr(self.order_builder, 'process_async'):
                order_response = await self.order_builder.process_async(
                    ordering_segments=ordering_segments,
                    order_state=order_state,
                    orchestrator_result=orchestrator_result
                )
                print_section(
                    head="✅ OrderResponseBuilder - Respuesta generada (async)",
                    msg=f"Length: {order_response} chars",
                    symbol="-"
                )
            else:
                order_response = self.order_builder.process(
                    ordering_segments=ordering_segments,
                    order_state=order_state,
                    orchestrator_result=orchestrator_result
                )
            
            # Obtener info del checklist para el prompt
            if self.order_builder.tracker:
                # Tracker is source of truth — suppress stale OrderChecklist
                # IMPORTANT: use last_asked, NOT get_next_field().
                # get_next_field() already advanced inside _build_from_tracker,
                # calling it again would skip the field that was just asked.
                last_asked = self.order_builder.tracker.last_asked
                if last_asked:
                    from src.core.order.application.order_flow_tracker import FIELD_QUESTIONS
                    next_field = last_asked
                    base_question = FIELD_QUESTIONS.get(last_asked, f"¿{last_asked}?")
                else:
                    next_field_data = self.order_builder.tracker.get_next_field()
                    if next_field_data:
                        next_field, base_question, _ = next_field_data
                    else:
                        next_field = "confirm"
                        base_question = "¿Confirmas tu pedido?"
                checklist_summary = self.order_builder.tracker.get_checklist_status()
                print_section(
                    head="📋 build_hybrid — checklist path",
                    msg=f"Usando TRACKER | next_field={next_field} (desde last_asked)" if last_asked else f"Usando TRACKER | next_field={next_field} (desde get_next_field)",
                    symbol="✓"
                )
            else:
                next_field, base_question, _ = OrderChecklist.get_next_field(order_state=order_state, ordering_segments=ordering_segments)
                checklist_summary = OrderChecklist.get_checklist_summary(order_state)
                print_section(
                    head="📋 build_hybrid — checklist path",
                    msg=f"Usando ORDERCHECKLIST (legacy) | next_field={next_field}",
                    symbol="○"
                )

        # Step 4: Usar order_summary (no el thought del Orchestrator)
        if order_state:
            order_summary = order_state.to_summary()
        else:
            order_summary = "Sin pedido activo"
        info_context = info_response if info_response else "Sin información consultada"

        # ── Inject extracted_info from RAG pipeline ──────────────────────
        if extracted_info and isinstance(extracted_info, list) and len(extracted_info) > 0:
            # Check for structured full-menu data (bypasses scoring pipeline)
            first = extracted_info[0]
            if isinstance(first, dict) and first.get("_type") == "menu_structure":
                info_context = "MENÚ COMPLETO (de la carta oficial):\n" + first.get("text", "")
            else:
                # Build a readable context string from scored RAG results
                rag_lines = []
                for item in extracted_info:
                    name = item.get("item_name", "")
                    score = item.get("score", item.get("rrf_score", ""))
                    match = item.get("match_type", item.get("gate_outcome", ""))
                    if name:
                        rag_lines.append(f"- {name}" + (f" (score: {score})" if score else ""))
                if rag_lines:
                    info_context = "INFORMACIÓN DEL MENÚ:\n" + "\n".join(rag_lines)

        # ── Fallback: read raw documents when RAG returned nothing ──────
        if info_context.startswith("[INFO_NO_DISPONIBLE:") or info_context == "Sin información consultada":
            # Check if any consulting segment is about the menu
            has_menu_query = any(
                getattr(s, "topic", None) is not None
                and hasattr(s, "topic") and str(s.topic) in ("menu", "special_offers", "ingredients")
                for s in consulting_segments
            )
            if has_menu_query:
                doc_paths = [
                    settings.documents_path + "/menu.md" if settings and hasattr(settings, "documents_path") else "data/documents/menu.md",
                    settings.documents_path + "/about_us.txt" if settings and hasattr(settings, "documents_path") else "data/documents/about_us.txt",
                ]
                doc_content = []
                for doc_path in doc_paths:
                    try:
                        with open(doc_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        doc_content.append(f"--- {doc_path.split('/')[-1]} ---\n{content}")
                    except (FileNotFoundError, IOError):
                        pass
                if doc_content:
                    info_context = "## INFORMACIÓN DEL RESTAURANTE (de documentos oficiales):\n" + "\n\n".join(doc_content)

        # Retrieval para next_field del checklist (inyección de contexto al LLM)
        if ordering_segments and next_field in OrderChecklist.RETRIEVAL_FIELDS and self.extractor:
            checklist_context = await self.order_builder.retrieve_context_for_field(next_field)
            if checklist_context and checklist_context != f"[INFO_NO_DISPONIBLE: field={next_field}]":
                checklist_options = checklist_context
            print_section(
                head="📋 Contexto del menú para el checklist",
                msg=f"Field: {next_field} | Opciones: {checklist_options[:80] if checklist_options else 'None'}",
                symbol="🍽️"
            )

        print_section(
            head="ORDER SUMMARY (para LLM)",
            msg=order_summary,
            symbol="-"
        )

        print_section(
            head="📋 Variables separadas para el prompt",
            msg=f"info_context: '{info_context[:60]}...' | checklist_options: '{checklist_options[:60] if checklist_options else ''}...'",
            symbol="-"
        )

        # Step 5: Leer brand voice
        brand_voice_content = ""
        if brand_voice_path:
            try:
                with open(brand_voice_path, 'r', encoding='utf-8') as f:
                    brand_voice_content = f.read()
            except Exception as e:
                print(f"⚠️ Error leyendo brand_voice: {e}")
        print_section("Pregunta para el LLM:", f"Next field: {next_field} | Base question: {base_question}", symbol="❓")
        
        # Step 6: Construir prompt con template
        try:
            prompt = self._build_hybrid_prompt(
                template_path=prompt_template_path,
                order_summary=order_summary,
                checklist_summary=checklist_summary,
                next_field=next_field,
                base_question=base_question,
                info_context=info_context,
                checklist_options=checklist_options,
                conversation_history=conversation_history,
                user_message=user_message,
                brand_voice_content=brand_voice_content,
                assistant_name="Luz Stella",
                restaurant_name="Sabor Casero",
                ambiguity_context=ambiguity_context,
                needs_clarification=str(needs_clarification).lower(),
                user_preferences=user_preferences_context,
            )
        except FileNotFoundError as e:
            print_section(head="❌ Error: Ruta no encontrada", msg=str(e), symbol="⚠️")
            raise
        except ValueError as e:
            print_section(head="❌ Error: Configuración requerida", msg=str(e), symbol="⚠️")
            raise
        except Exception as e:
            print_section(head="❌ Error construyendo prompt", msg=str(e), symbol="⚠️")
            raise

        # Step 7: Llamar LLM
        from src.infrastructure.llm_client import get_model_for_stage
        
        llm_response = await self.llm_client.chat_completion(
            messages=[{"role": "system", "content": prompt}],
            model=get_model_for_stage("response", settings) if settings else "gpt-4",
            temperature=0.5,
            stream=False
        )

        print_section(
            head="✅ Respuesta híbrida generada",
            msg=f"Length: {llm_response} chars",
            symbol="="
        )

        return llm_response
    
    def _build_hybrid_prompt(
        self,
        template_path: str,  # Kept for backward compatibility; fallback path from settings
        order_summary: str,
        checklist_summary: str,
        next_field: str,
        base_question: str,
        info_context: str,
        checklist_options: str,
        conversation_history: str,
        user_message: str,
        brand_voice_content: str,
        assistant_name: str,
        restaurant_name: str,
        ambiguity_context: str = "",
        needs_clarification: str = "false",
        user_preferences: str = "",
    ) -> str:
        """Construye el prompt híbrido usando PromptManager (Langfuse + fallback a archivo)."""
        from src.config.environment import settings

        # The PromptManager handles Langfuse first, then falls back to settings paths
        prompt = get_prompt_manager(settings.prompt_fallback_map).get(
            "response",
            order_summary=order_summary,
            checklist_summary=checklist_summary,
            next_field=next_field,
            base_question=base_question,
            info_context=info_context,
            checklist_options=checklist_options,
            conversation_history=conversation_history,
            user_message=user_message,
            brand_voice_content=brand_voice_content,
            assistant_name=assistant_name,
            restaurant_name=restaurant_name,
            ambiguity_context=ambiguity_context,
            needs_clarification=needs_clarification,
            user_preferences=user_preferences,
        )

        return prompt

    def _filter_ordering_segments(self, topic_details: List[Detail]) -> List[Detail]:
        """Filtra segmentos de tipo ORDERING/CONFIRMATION/CANCELLATION/CLARIFICATION"""
        ordering_types = {
            QueryType.ORDERING,
            QueryType.CONFIRMATION,
            QueryType.CANCELLATION,
            QueryType.CLARIFICATION
        }
        return [seg for seg in topic_details if seg.query_type in ordering_types]

    def _filter_consulting_segments(self, topic_details: List[Detail]) -> List[Detail]:
        """Filtra segmentos de tipo CONSULTING"""
        return [seg for seg in topic_details if seg.query_type == QueryType.CONSULTING]

    def build_order_only(
        self,
        ordering_segments: List[Detail],
        order_state: Optional[Order] = None,
        orchestrator_result: Optional[Dict[str, Any]] = None
    ) -> str:
        """Construye solo respuesta de pedido (sin mezcla)"""
        return self.order_builder.process(
            ordering_segments=ordering_segments,
            order_state=order_state,
            orchestrator_result=orchestrator_result
        )

    def build_info_only(
        self,
        consulting_segments: List[Detail]
    ) -> str:
        """Construye solo respuesta de información (sin mezcla)"""
        return self.info_builder.process(
            info_segments=consulting_segments
        )