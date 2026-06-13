from typing import List, Dict, Any, Optional
from src.core.classifier.intent import Detail, QueryType
from src.core.order.domain.models import Order
from src.utils.utils import print_section


class ResponseMixer:
    """
    Combina respuestas de pedido (Order) e información (Info) según reglas estructuradas.
    
    Reglas de mezcla:
    - Usuario pide info Y quiere ordenar → Info primero → luego Order
    - Usuario en flujo de orden + hace pregunta → Order (siguiente paso) → luego Info
    - Solo consulta → Solo Info
    - Solo ordenar → Solo Order
    """

    def __init__(self):
        pass

    def combine(
        self,
        order_response: str,
        info_response: str,
        topic_details: List[Detail],
        order_state: Optional[Order] = None
    ) -> str:
        """
        Combina respuestas de Order e Info en una respuesta final.

        Args:
            order_response: Respuesta del OrderResponseBuilder
            info_response: Respuesta del InfoResponseBuilder  
            topic_details: Lista de segmentos clasificados
            order_state: Estado actual del pedido (para determinar flujo)

        Returns:
            Respuesta final combinada
        """
        print_section(
            head="🎛️ ResponseMixer combinando respuestas",
            msg=f"Order: {'Sí' if order_response else 'No'} | Info: {'Sí' if info_response else 'No'}",
            symbol="⚡"
        )

        # Caso 1: Solo respuesta de orden
        if order_response and not info_response:
            return order_response

        # Caso 2: Solo respuesta de información
        if info_response and not order_response:
            return info_response

        # Caso 3: Ambos tienen contenido - aplicar reglas de mezcla
        if order_response and info_response:
            return self._apply_mix_rules(
                order_response, 
                info_response, 
                topic_details, 
                order_state
            )

        # Caso 4: Ninguno tiene contenido
        return "¿En qué puedo ayudarte?"

    def _apply_mix_rules(
        self,
        order_response: str,
        info_response: str,
        topic_details: List[Detail],
        order_state: Optional[Order] = None
    ) -> str:
        """Aplica reglas de mezcla estructurada"""
        
        # Clasificar tipos de query presentes
        query_types = self._extract_query_types(topic_details)
        
        # Regla 1: Si usuario está en flujo activo de orden Y hace pregunta de info
        if order_state and order_state.items and QueryType.CONSULTING in query_types:
            return self._mix_order_first_then_info(order_response, info_response)
        
        # Regla 2: Si usuario pide info Y quiere ordenar (nueva intención)
        if QueryType.CONSULTING in query_types and QueryType.ORDERING in query_types:
            return self._mix_info_first_then_order(info_response, order_response)
        
        # Regla 3: Si hay confirmation/clarification sobre orden activa
        if QueryType.CONFIRMATION in query_types or QueryType.CLARIFICATION in query_types:
            if order_state and order_state.items:
                return order_response  # Priorizar order en confirmaciones
        
        # Regla 4: Por defecto, info primero (para no interrumpir al cliente)
        return self._mix_info_first_then_order(info_response, order_response)

    def _extract_query_types(self, topic_details: List[Detail]) -> set:
        """Extrae conjunto de tipos de query únicos"""
        return set(seg.query_type for seg in topic_details)

    def _mix_order_first_then_info(self, order_response: str, info_response: str) -> str:
        """Mezcla: Order primero, luego Info"""
        return f"{order_response} | Además: {info_response}"

    def _mix_info_first_then_order(self, info_response: str, order_response: str) -> str:
        """Mezcla: Info primero, luego Order"""
        return f"{info_response} | {order_response}"

    def _mix_alternate(self, order_response: str, info_response: str) -> str:
        """Mezcla alternada (alternativa)"""
        return f"{info_response} — {order_response}"

    def determine_order(
        self,
        topic_details: List[Detail],
        order_state: Optional[Order] = None
    ) -> str:
        """
        Determina qué respuesta debe ir primero.
        
        Returns:
            "order_first" | "info_first" | "order_only" | "info_only"
        """
        query_types = self._extract_query_types(topic_details)
        
        has_order_segments = bool(query_types & {
            QueryType.ORDERING, 
            QueryType.CONFIRMATION, 
            QueryType.CANCELLATION,
            QueryType.CLARIFICATION
        })
        
        has_info_segments = QueryType.CONSULTING in query_types
        
        # Si hay orden activa y hace pregunta de info → order primero
        if order_state and order_state.items and has_info_segments:
            return "order_first"
        
        # Si pide info Y ordena → info primero
        if has_info_segments and has_order_segments:
            return "info_first"
        
        # Solo order
        if has_order_segments and not has_info_segments:
            return "order_only"
        
        # Solo info
        if has_info_segments and not has_order_segments:
            return "info_only"
        
        return "info_only"  # Default