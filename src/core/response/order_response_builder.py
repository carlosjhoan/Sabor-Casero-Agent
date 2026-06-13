from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from src.core.classifier.intent import Detail, QueryType, QueryTopic
from src.core.order.domain.models import Order, OrderItem, ServiceCategory
from src.core.knowledge.registry import DocumentRegistry
from src.utils.utils import print_section


class OrderChecklist:
    """
    Gestiona el workflow de captura del checklist de pedido.
    Define la secuencia de campos y la lógica de retrieval por cada campo.
    """
    
    STEPS = [
        ("protein", "¿Qué plato deseas ordenar?"),
        ("size", "¿Qué tamaño prefieres?"),
        ("principle", "¿Qué principio prefieres?"),
        ("customer_name", "¿A nombre de quién?"),
        ("service_type", "¿Delivery o pasas a recoger?"),
        ("address", "¿Cuál es la dirección de entrega?"),
        ("scheduled_time", "¿A qué hora pasas a recoger?"),
        ("payment_method", "¿Cómo vas a pagar?"),
        ("observations", "¿Tienes alguna observación?"),
    ]
    
    RETRIEVAL_FIELDS = ["protein", "size", "principle", "service_type", "scheduled_time", "payment_method", "address"]
    
    # Mapeo de campo → QueryTopic para retrieval (USAR ESTE para _retrieve_field_options)
    FIELD_TO_TOPIC = {
        "protein": QueryTopic.MENU,
        "size": QueryTopic.MENU,
        "principle": QueryTopic.MENU,
        "service_type": QueryTopic.DELIVERY,
        "address": QueryTopic.DELIVERY,
        "scheduled_time": QueryTopic.SERVICE_HOURS,
        "payment_method": QueryTopic.PAYMENT,
    }
    
    # Mapeo de QueryTopic → campo del checklist (para inferencia opcional)
    TOPIC_TO_CHECKLIST_FIELD = {
        QueryTopic.MENU: "protein",
        QueryTopic.DELIVERY: "service_type",
        QueryTopic.PAYMENT: "payment_method",
        QueryTopic.SERVICE_HOURS: "scheduled_time",
    }
    
    # Palabras clave en focus → campo del checklist
    KEYWORD_TO_CHECKLIST_FIELD = {
        "protein": "protein", "plato": "protein", "pedir": "protein",
        "size": "size", "tamaño": "size", "corriente": "size", "mini": "size",
        "principle": "principle", "principio": "principle", "frijoles": "principle",
        "delivery": "service_type", "domicilio": "service_type", "recoger": "service_type",
        "dirección": "address", "direccion": "address",
        "hora": "scheduled_time", "horario": "scheduled_time",
        "pagar": "payment_method", "pago": "payment_method", "efectivo": "payment_method",
        "nombre": "customer_name",
        "observación": "observations", "nota": "observations", "observacion": "observations",
    }
    
    # Preguntas por campo
    FIELD_QUESTIONS = {
        "protein": "¿Qué plato deseas ordenar?",
        "size": "¿Qué tamaño prefieres? (Corriente o Mini)",
        "principle": "¿Qué principio prefieres?",
        "customer_name": "¿A nombre de quién?",
        "service_type": "¿Delivery o pasas a recoger?",
        "address": "¿Cuál es la dirección de entrega?",
        "scheduled_time": "¿A qué hora pasas a recoger?",
        "payment_method": "¿Cómo vas a pagar?",
        "observations": "¿Tienes alguna observación?",
    }
    
    @classmethod
    def get_next_field(
        cls, 
        order_state: Optional[Order],
        ordering_segments: List[Detail]
    ) -> Tuple[str, str, bool]:
        """Determina el siguiente campo del checklist a capturar.
        
        Flujo:
        1. Si no hay pedido → protein (inicio)
        2. ITERAR sobre STEPS para encontrar primer campo faltante
        3. Si todos completos → confirmar pedido
        """

        # print_section(
        #     head="Determinando siguiente campo del checklist",
        #     msg=f"Order state: {'Sí' if order_state else 'No'} | Items: {len(order_state.items) if order_state and order_state.items else 0}",
        #     symbol="🔍"
        # )

        if not order_state or not order_state.items:
            return cls.STEPS[0][0], cls.STEPS[0][1], True
        
        # print_section(
        #     head="Evaluando checklist de pedido",
        #     msg=f"Items en el pedido: {len(order_state.items)}",
        #     symbol="📋"
        # )

        print_section(
            head="VALIDANDO IETMS DEL PEDIDO",
            msg=f"I+tems: {order_state.items if order_state and order_state.items else {}}",
            symbol="🔍"
        )

        if not cls._has_valid_items(order_state):
            print_section(
                head="Checklist: No hay items válidos",
                msg="Reiniciando checklist desde proteína",
                symbol="⚠️"
            )
            return cls.STEPS[0][0], cls.STEPS[0][1], True
        
        for field_name, question in cls.STEPS:
            if cls._field_is_missing(field_name, order_state):
                needs_retrieval = field_name in cls.RETRIEVAL_FIELDS
                print_section(
                    head="📋 Siguiente pregunta",
                    msg=f"Campo: {field_name} | Retrieval: {needs_retrieval}",
                    symbol="→"
                )
                return field_name, question, needs_retrieval
        
        return "confirm", "¿Confirmas tu pedido?", False
    
    @classmethod
    def _field_is_missing(cls, field: str, order: Order) -> bool:
        """Verifica si el campo no tiene información en el pedido."""
        if field == "size":
            return any(not i.size and cls._item_has_size_variants(i) for i in order.items)
        if field == "principle":
            return any(not i.principle for i in order.items)
        if field == "customer_name":
            return not order.customer_id
        if field == "service_type":
            return not order.service
        if field == "address":
            return (order.service and 
                    order.service.category.value == "delivery" and 
                    not order.address)
        if field == "scheduled_time":
            return (order.service and 
                    order.service.category.value == "pickup" and 
                    not order.service.details.scheduled_time)
        if field == "payment_method":
            return not order.payment_method
        if field == "observations":
            return True
        return False
    
    @classmethod
    def _has_valid_items(cls, order: Order) -> bool:
        if not order or not order.items:
            return False
        return any(item.protein for item in order.items)
    
    @classmethod
    def _item_has_size_variants(cls, item: OrderItem) -> bool:
        if not item.protein:
            return False
        protein_lower = item.protein.lower()
        return ("pechuga" in protein_lower or 
                "carne" in protein_lower or 
                "lomo" in protein_lower or
                "carnes" in protein_lower)
    
    @classmethod
    def get_retrieval_query(cls, field: str) -> str:
        queries = {
            "protein": "listado de proteínas del menú con precios y opciones",
            "size": "opciones de tamaño con precios actuales",
            "principle": "principios disponibles con nombres completos",
            "service_type": "tipos de servicio disponibles para entrega o recoger",
            "address": "zonas de cobertura para delivery",
            "scheduled_time": "horario de atención y disponibilidad",
            "payment_method": "métodos de pago aceptados actualmente"
        }
        return queries.get(field, field)

    @classmethod
    def get_checklist_summary(cls, order_state: Optional[Order]) -> str:
        """Genera un resumen del checklist indicando campos capturados y faltantes."""
        if not order_state or not order_state.items:
            return "Sin pedido activo"

        lines = []
        for field_name, _ in cls.STEPS:
            if not cls._field_is_missing(field_name, order_state):
                value = cls._get_field_value(field_name, order_state)
                lines.append(f"[OK] {field_name}: {value}")
            else:
                lines.append(f"[WAITING] {field_name}")

        next_field, _, _ = cls.get_next_field(order_state, [])
        if next_field == "confirm":
            lines.append("[READY] Pedido listo para confirmar")

        return "\n".join(lines)

    @classmethod
    def _get_field_value(cls, field_name: str, order: Order) -> str:
        """Obtiene el valor capturado de un campo del checklist."""
        if field_name == "protein":
            for item in order.items:
                if item.protein:
                    return item.protein
        elif field_name == "size":
            for item in order.items:
                if item.size:
                    return item.size
        elif field_name == "principle":
            for item in order.items:
                if item.principle:
                    return item.principle
        elif field_name == "customer_name":
            return order.customer_id or ""
        elif field_name == "service_type":
            return order.service.type_name if order.service else ""
        elif field_name == "address":
            return order.address or ""
        elif field_name == "scheduled_time":
            if order.service and order.service.category == ServiceCategory.PICKUP:
                dt = order.service.details.scheduled_time
                return dt.strftime("%H:%M") if dt else ""
            return ""
        elif field_name == "payment_method":
            return order.payment_method or ""
        elif field_name == "observations":
            if order.observations:
                return ", ".join(order.observations)
            return "(sin observaciones)"
        return ""


class OrderResponseBuilder:
    """
    Construye respuestas enfocadas en la gestión de pedidos (orden).
    Maneja: ORDERING, CONFIRMATION, CANCELLATION, CLARIFICATION
    
    Incluye workflow de checklist con retrieval del menú.
    """

    def __init__(self, extractor=None, tracker=None):
        self.current_order: Optional[Order] = None
        self.extractor = extractor
        self.tracker = tracker
        self.doc_registry = DocumentRegistry()
    
    def process(
        self,
        ordering_segments: List[Detail],
        order_state: Optional[Order] = None,
        orchestrator_result: Optional[Dict[str, Any]] = None
    ) -> str:
        """Método síncrono - para uso básico sin retrieval."""
        self.current_order = order_state

        if not ordering_segments:
            return ""

        # print_section(
        #     head="📦 OrderResponseBuilder procesando",
        #     msg=f"Segmentos: {len(ordering_segments)} | Order: {'Sí' if order_state else 'No'}",
        #     symbol="🔄"
        # )

        query_types = [seg.query_type for seg in ordering_segments]
        
        if QueryType.CANCELLATION in query_types:
            return self._handle_cancellation(ordering_segments, order_state)
        
        if QueryType.CONFIRMATION in query_types:
            return self._handle_confirmation(ordering_segments, order_state, orchestrator_result)
        
        if QueryType.CLARIFICATION in query_types:
            return self._handle_clarification(ordering_segments, order_state)
        
        return self._handle_ordering(ordering_segments, order_state, orchestrator_result)

    async def process_async(
        self,
        ordering_segments: List[Detail],
        order_state: Optional[Order] = None,
        orchestrator_result: Optional[Dict[str, Any]] = None
    ) -> str:
        """Método asíncrono - con retrieval del menú."""
        self.current_order = order_state

        # print_section(
        #     head="🚀 OrderResponseBuilder - Método asíncrono llamado",
        #     msg=f"Segmentos: {len(ordering_segments)} | Order: {'Sí' if order_state else 'No'}",
        #     symbol="🔄"
        # )

        if not ordering_segments:
            return ""

        # print_section(
        #     head="📦 OrderResponseBuilder procesando (async)",
        #     msg=f"Segmentos: {ordering_segments} | Order: {'Sí' if order_state else 'No'}",
        #     symbol="🔄"
        # )

        query_types = [seg.query_type for seg in ordering_segments]
        
        if QueryType.CANCELLATION in query_types:
            return self._handle_cancellation(ordering_segments, order_state)
        
        if QueryType.CONFIRMATION in query_types:
            if self.tracker:
                return await self._build_from_tracker(ordering_segments, order_state, orchestrator_result)
            return self._handle_confirmation(ordering_segments, order_state, orchestrator_result)
        
        if QueryType.CLARIFICATION in query_types:
            return self._handle_clarification(ordering_segments, order_state)
        
        if self.tracker:
            return await self._build_from_tracker(ordering_segments, order_state, orchestrator_result)
        return await self._handle_ordering_async(ordering_segments, order_state, orchestrator_result)

    def _handle_cancellation(self, segments: List[Detail], order_state: Optional[Order]) -> str:
        """Maneja cancelación de pedido"""
        if not order_state or not order_state.items:
            return "No tengo ningún pedido activo para cancelar. ¿Deseas hacer un nuevo pedido?"
        return f"Tengo tu pedido actual: {order_state.to_summary()}. ¿Confirmas que deseas cancelarlo?"

    def _handle_confirmation(
        self,
        segments: List[Detail],
        order_state: Optional[Order],
        orchestrator_result: Optional[Dict[str, Any]]
    ) -> str:
        """Maneja confirmación (sí/no) del usuario"""
        if not order_state or not order_state.items:
            return "No hay ningún pedido activo para confirmar."
        actions = orchestrator_result.get("actions", []) if orchestrator_result else []
        if actions:
            first_action = actions[0]
            action_type = first_action.get("action_type", "")
            if action_type == "confirm_order":
                return self._generate_confirmation_message(order_state)
            elif action_type == "modify_order":
                return f"Perfecto, procedo a modificar: {first_action.get('details', '')}"
            elif action_type == "cancel_order":
                return "Tu pedido ha sido cancelado. ¿En qué más puedo ayudarte?"
        return self._generate_confirmation_message(order_state)

    def _handle_clarification(self, segments: List[Detail], order_state: Optional[Order]) -> str:
        """Maneja solicitudes de clarificación"""
        clarification_focus = ""
        for seg in segments:
            if seg.query_type == QueryType.CLARIFICATION:
                clarification_focus = seg.focus
                break
        if not order_state or not order_state.items:
            return "Disculpa, ¿podrías aclarar tu solicitud?"
        if "precio" in clarification_focus.lower() or "cuánto" in clarification_focus.lower():
            total = order_state.total_amount
            return f"El total de tu pedido es ${total:.0f}. ¿Confirmas el pedido?"
        if "dirección" in clarification_focus.lower() or "domicilio" in clarification_focus.lower():
            addr = order_state.address if order_state.service else None
            return f"Tu dirección de entrega es: {addr or 'No registrada'}. ¿Confirmas?"
        return "¿Qué aspecto de tu pedido necesitas clarificar?"

    def _handle_ordering(
        self,
        segments: List[Detail],
        order_state: Optional[Order],
        orchestrator_result: Optional[Dict[str, Any]]
    ) -> str:
        """Maneja intención de ordenar - flujo síncrono sin retrieval"""
        if orchestrator_result and orchestrator_result.get("success"):
            actions = orchestrator_result.get("actions", [])
            if actions:
                return self._build_from_actions(actions, order_state)
        return self._build_checklist_question(order_state, segments)

    async def _handle_ordering_async(
        self,
        segments: List[Detail],
        order_state: Optional[Order],
        orchestrator_result: Optional[Dict[str, Any]]
    ) -> str:
        """Maneja intención de ordenar - flujo asíncrono con retrieval"""
        if orchestrator_result and orchestrator_result.get("success"):
            actions = orchestrator_result.get("actions", [])
            if actions:
                return self._build_from_actions(actions, order_state)
        return await self._build_checklist_question_async(order_state, segments)

    async def _build_from_tracker(
        self,
        segments: List[Detail],
        order_state: Optional[Order],
        orchestrator_result: Optional[Dict[str, Any]],
    ) -> str:
        """Build response using OrderFlowTracker state machine.
        
        Flow:
        1. tracker.consume_actions(actions, order_state)
        2. If CONFIRMATION in segments: resolve + mark_confirmed
        3. get_next_field() → mark_asked → return question (with retrieval if needed)
        4. If all_confirmed → confirmation message
        5. Fallback to checklist question
        """
        actions = (orchestrator_result or {}).get("actions", [])
        print_section(
            head="🚦 _build_from_tracker",
            msg=f"Inicio | segments={len(segments)} | actions={len(actions)} | order={'Sí' if order_state else 'No'}",
            symbol="="
        )
        
        # Step 1: Consume actions from ActionPlanner
        self.tracker.consume_actions(actions, order_state)
        
        # Step 2: Resolve confirmations
        query_types = [seg.query_type for seg in segments]
        if QueryType.CONFIRMATION in query_types:
            print_section(
                head="🚦 _build_from_tracker — Step 2",
                msg="QueryType.CONFIRMATION detectado → resolviendo",
                symbol="→"
            )
            confirmed = self.tracker.resolve_confirmation(segments, order_state)
            if confirmed:
                self.tracker.mark_confirmed(confirmed)
        else:
            print_section(
                head="🚦 _build_from_tracker — Step 2",
                msg="No hay CONFIRMATION en segments",
                symbol="→"
            )
        
        # Step 3: Determine next field
        next_field = self.tracker.get_next_field()
        
        if next_field:
            field_name, question, needs_retrieval = next_field
            self.tracker.mark_asked(field_name)
            
            if field_name == "confirm":
                result = self._generate_confirmation_message(order_state)
                print_section(
                    head="🚦 _build_from_tracker — Step 3",
                    msg=f"Campo 'confirm' → mensaje de confirmación",
                    symbol="→"
                )
                return result
            
            if not needs_retrieval:
                print_section(
                    head="🚦 _build_from_tracker — Step 3",
                    msg=f"Campo={field_name} | sin retrieval | pregunta directa",
                    symbol="→"
                )
                return question
            
            menu_context = await self._retrieve_field_options(field_name)
            if menu_context:
                print_section(
                    head="🚦 _build_from_tracker — Step 3",
                    msg=f"Campo={field_name} | con retrieval | {len(menu_context)} chars de contexto",
                    symbol="→"
                )
                return f"{question}\n\nTenemos disponibles: {menu_context}"
            print_section(
                head="🚦 _build_from_tracker — Step 3",
                msg=f"Campo={field_name} | retrieval sin resultados → pregunta sola",
                symbol="→"
            )
            return question
        
        # Step 4: All confirmed → summary
        if self.tracker.all_confirmed:
            print_section(
                head="🚦 _build_from_tracker — Step 4",
                msg="all_confirmed=True → mensaje de confirmación final",
                symbol="→"
            )
            return self._generate_confirmation_message(order_state)
        
        # Step 5: Fallback
        print_section(
            head="🚦 _build_from_tracker — Step 5",
            msg="Sin campos pendientes y no all_confirmed → fallback a checklist",
            symbol="→"
        )
        return await self._build_checklist_question_async(order_state, segments)

    def _build_checklist_question(
        self,
        order_state: Optional[Order],
        segments: List[Detail]
    ) -> str:
        """Construye siguiente pregunta sin retrieval."""
        field_name, base_question, needs_retrieval = OrderChecklist.get_next_field(order_state, segments)
        if field_name == "confirm":
            return self._generate_confirmation_message(order_state)
        if not needs_retrieval:
            return base_question
        return base_question + "\n\n" + self._get_hardcoded_options(field_name)

    async def _build_checklist_question_async(
        self,
        order_state: Optional[Order],
        segments: List[Detail]
    ) -> str:
        """Construye siguiente pregunta con retrieval del menú."""
        field_name, base_question, needs_retrieval = OrderChecklist.get_next_field(order_state, segments)
        
        if field_name == "confirm":
            return self._generate_confirmation_message(order_state)
        
        if not needs_retrieval:
            return base_question
        
        menu_context = await self._retrieve_field_options(field_name)
        
        if menu_context:
            return f"{base_question}\n\nTenemos disponibles: {menu_context}"
        
        return base_question

    async def _retrieve_field_options(self, field: str) -> str:
        """Retrieve opciones del menú para el campo específico usando extractor."""
        if not self.extractor:
            return self._get_hardcoded_options(field)
        
        query = OrderChecklist.get_retrieval_query(field)
        topic = OrderChecklist.FIELD_TO_TOPIC.get(field, QueryTopic.MENU)
        doc_name = self.doc_registry.get_doc_for_topic(topic)
        
        detail = Detail(
            segment=query,
            query_type=QueryType.CONSULTING,
            topic=topic,
            focus=query,
            file_source=doc_name
        )
        
        try:
            group_by_doc = {doc_name: [detail]}
            retrieved_details = await self.extractor.retrieve(group_by_doc)
            
            if retrieved_details:
                results = []
                for d in retrieved_details:
                    if d.info_extracted:
                        results.append(d.info_extracted)
                if results:
                    print_section(
                        head=f"Opciones retrieved para {field}",
                        msg=f"{len(results)} opciones encontradas",
                        symbol="✅"
                    )
                    return " | ".join(results)
        
        except Exception as e:
            print(f"⚠️ Retrieval error: {e}")
        
        return self._get_hardcoded_options(field)

    async def retrieve_context_for_field(self, field: str) -> str:
        """Retrieve opciones del menú para el campo del checklist.

        Args:
            field: Nombre del campo (protein, size, principle, etc.)

        Returns:
            String con las opciones retrieved, o hardcoded fallback
        """
        return await self._retrieve_field_options(field)

    def _get_hardcoded_options(self, field: str) -> str:
        """Opciones fallback cuando el retrieval falla - SIN hallucination"""
        return f"[INFO_NO_DISPONIBLE: field={field}]"

    def _build_from_actions(self, actions: List[Dict], order_state: Optional[Order]) -> str:
        """Construye mensaje a partir de acciones del ActionPlanner"""
        print_section(
            head="Construyendo respuesta desde acciones",
            msg=f"Acciones recibidas: {len(actions)}",
            symbol="⚙️")
        
        if not actions:
            return "¿Qué te gustaría ordenar?"
        first_action = actions[0]
        action_type = first_action.get("action_type", "")
        action_messages = {
            "ask_dish": "Con gusto,¿qué plato deseas ordenar?",
            "ask_size": "¿Lo prefieres en tamaño Corriente o Mini?",
            "ask_side": "¿Qué principio deseas?",
            "ask_beverage": "¿Qué bebida prefieres?",
            "ask_method": "¿Deseas delivery o pasar a recoger?",
            "ask_address": "¿Cuál es la dirección de entrega?",
            "ask_payment": "¿Cómo deseas pagar?",
            "ask_observation": "¿Tienes alguna observación para tu pedido?",
            "confirm_order": self._generate_confirmation_message(order_state) if order_state else "¿Confirmas tu pedido?",
            "modify_item": f"Vamos a modificar: {first_action.get('details', '')}",
            "add_item": f"Agregando: {first_action.get('item', '')}",
            "remove_item": f"Eliminando: {first_action.get('item', '')}"
        }
        return action_messages.get(action_type, first_action.get("message", "¿Qué más necesitas de tu pedido?"))

    def _generate_confirmation_message(self, order_state: Optional[Order]) -> str:
        """Genera mensaje de confirmación del pedido"""
        if not order_state or not order_state.items:
            return "¿Confirmas tu pedido?"
        items_summary = []
        for item in order_state.items:
            parts = [f"{item.quantity}x {item.protein}"]
            if item.size:
                parts.append(f"({item.size})")
            if item.principle:
                parts.append(f"c/w {item.principle}")
            items_summary.append(" ".join(parts))
        items_str = ", ".join(items_summary)
        confirmation_parts = [f"Tu pedido: {items_str}"]
        if order_state.service:
            confirmation_parts.append(f"Entrega: {order_state.service_type}")
        if order_state.address:
            confirmation_parts.append(f"Dirección: {order_state.address}")
        total = order_state.total_amount
        confirmation_parts.append(f"Total: ${total:.0f}")
        return " | ".join(confirmation_parts) + ". ¿Confirmas?"