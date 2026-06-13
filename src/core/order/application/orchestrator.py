# order/application/processors/order_orchestrator.py

from typing import Dict, Any, Optional, List
from src.utils.utils import print_section
from src.core.order.domain.order_repository_interface import OrderRepository
from src.core.order.domain.session_repository_interface import SessionRepository
from src.core.order.application.thought_generator import ThoughtGenerator
from src.core.order.application.action_planner import ActionPlanner
from src.core.order.application.ambiguity_resolver import AmbiguityResolver
from src.core.classifier.intent import Detail


class OrderOrchestrator:
    """
    ORQUESTADOR PRINCIPAL de órdenes.
    
    Coordina el flujo completo:
    1. ThoughtGenerator → Genera razonamiento
    2. ActionPlanner → Genera y ejecuta acciones
    
    Este es el verdadero OrderProcessor que expones al exterior.
    """
    
    def __init__(
        self,
        order_repository: OrderRepository,
        session_repository: SessionRepository,
        max_retries: int = 2
    ):
        # Inicializar componentes especializados
        self.thought_generator = ThoughtGenerator(
            session_repository=session_repository,
            order_repository=order_repository,
        )
        
        self.action_planner = ActionPlanner(
            order_repository=order_repository,
            session_repository=session_repository
        )

        self.ambiguity_resolver = AmbiguityResolver()
        
        # Referencias directas a repositorios (no via action_planner.*)
        self.order_repository = order_repository
        self.session_repository = session_repository
        
        # Configuración
        self.max_retries = max_retries
        
        print_section(
            head="🚀 OrderOrchestrator Inicializado",
            msg="ThoughtGenerator + ActionPlanner listos",
            symbol="✅"
        )
    
    async def process_order_intent(
        self,
        ordering_segments: list,
        session_id: str,
        summary_conversation: Optional[str] = None,
        skip_actions: bool = False
    ) -> Dict[str, Any]:
        """
        Método principal: procesa intención de orden.
        
        Flujo:
        1. Genera thought (razonamiento)
        2. Genera y ejecuta acciones basadas en el thought
        
        Args:
            ordering_segments: Segmentos de orden del extractor
            session_id: ID de sesión
            summary_conversation: Resumen de conversación previa
            skip_actions: Si True, solo genera thought y acciones (no ejecuta)
        
        Returns:
            Dict con resultado completo del proceso
        """
        print_section(
            head="📦 OrderOrchestrator procesando orden",
            msg=f"Session: {session_id} | Segmentos: {len(ordering_segments)}",
            symbol="🔄"
        )
        
        # PASO 1: Generar thought (razonamiento)
        thought_result = await self.thought_generator.generate_thought(
            ordering_segments=ordering_segments,
            session_id=session_id,
            summary_conversation=summary_conversation
        )
        
        if not thought_result["success"]:
            error_msg = thought_result.get("error", "Error desconocido en generación de thought")
            print_section(
                head="❌ Error en generación de thought",
                msg=error_msg,
                symbol="💥"
            )
            return {
                "success": False,
                "error": error_msg,
                "stage": "thought_generation",
                "thought": None,
                "actions": [],
                "execution": None
            }
        
        thought = thought_result["thought"]
        context = thought_result.get("context", {})
        
        print_section(
            head="🧠 Thought generado",
            msg=thought,
            symbol="::"
        )
        
        # PASO 2: Generar acciones desde el thought (SIN ejecutar aún)
        actions = await self.action_planner.plan_actions(
            thought=thought,
            context=context,
            session_id=session_id,
            summary_conversation=summary_conversation
        )

        print_section(
            head="📋 Acciones planificadas",
            msg=f"{len(actions)} acciones generadas",
            symbol="⚡"
        )

        # PASO 3: Resolver ambigüedades usando declaración estructurada
        ambiguity_declaration = thought_result.get("ambiguity")
        ambiguity_result = self.ambiguity_resolver.resolve(
            thought=thought,
            actions=actions,
            context=context,
            ambiguity_declaration=ambiguity_declaration,
        )

        if ambiguity_result["is_ambiguous"]:
            print_section(
                head="⚠️ AMBIGÜEDAD DETECTADA — No se ejecutarán acciones",
                msg=f"Señales: {ambiguity_result['signals']} | Confianza: {ambiguity_result['confidence']:.2f}",
                symbol="🔍"
            )
            print_section(
                head="📝 Contexto de ambigüedad para el response",
                msg=ambiguity_result["ambiguity_context"][:200],
                symbol="::"
            )
            return {
                "success": True,
                "thought": thought,
                "actions": [],
                "execution": None,
                "needs_clarification": True,
                "ambiguity_context": ambiguity_result["ambiguity_context"],
                "ambiguity_signals": ambiguity_result["signals"],
                "context": {
                    "order_id": context.get("order_id"),
                    "order_summary": context.get("summary"),
                },
                "metadata": {
                    "thought_generation": {
                        "attempts": thought_result.get("attempts", 1),
                        "success": True,
                    },
                    "ambiguity_resolution": {
                        "detected": True,
                        "confidence": ambiguity_result["confidence"],
                    },
                },
            }

        # PASO 4: Sin ambigüedad — ejecutar acciones normalmente
        execution_result = await self.action_planner.execute_actions(
            actions=actions,
            session_id=session_id,
            current_order_id=context.get("order_id"),
        )

        print_section(
            head="✅ Acciones ejecutadas sin ambigüedad",
            msg=f"{execution_result.get('successful', 0)}/{len(actions)} exitosas",
            symbol="📊"
        )

        # Resultado consolidado
        return {
            "success": True,
            "thought": thought,
            "actions": actions,
            "execution": execution_result,
            "needs_clarification": False,
            "context": {
                "order_id": context.get("order_id"),
                "order_summary": context.get("summary"),
            },
            "metadata": {
                "thought_generation": {
                    "attempts": thought_result.get("attempts", 1),
                    "success": True,
                },
                "ambiguity_resolution": {
                    "detected": False,
                },
            },
        }
    
    async def preview_actions(
        self,
        ordering_segments: List[Detail],
        session_id: str,
        summary_conversation: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Versión de solo preview: genera thought y acciones, pero NO las ejecuta.
        Útil para testing, debugging o mostrar al usuario antes de confirmar.
        """
        return await self.process_order_intent(
            ordering_segments=ordering_segments,
            session_id=session_id,
            summary_conversation=summary_conversation,
            skip_actions=True
        )

    async def reprocess_with_thought(
        self,
        thought: str,
        session_id: str,
        summary_conversation: Optional[str] = None,
        execute: bool = True
    ) -> Dict[str, Any]:
        """
        Reprocesa usando un think existente (útil para bypass).
        """
        context = await self.thought_generator._load_order_context(session_id)
        
        if execute:
            result = await self.action_planner.plan_and_execute(
                thought=thought,
                context=context,
                session_id=session_id,
                summary_conversation=summary_conversation
            )
            return {
                "success": True,
                "thought": thought,
                "actions": result.get("actions", []),
                "execution": result.get("execution"),
                "context": context
            }
        else:
            actions = await self.action_planner._generate_actions(
                thought=thought,
                context=context,
                summary_conversation=summary_conversation
            )
            return {
                "success": True,
                "thought": thought,
                "actions": actions,
                "execution": None,
                "context": context
            }

    # ── CRUD methods for synthetic tools (granular-order-tools) ────
    # Métodos reales de la clase, ya no parcheados desde el módulo.

    async def get_or_create_order(self, session_id: str) -> "Order":
        """Obtiene la orden activa para una sesión, o crea una nueva si no existe.

        Args:
            session_id: Identificador de la sesión.

        Returns:
            Order: La orden activa (existente o recién creada).
        """
        session = self.session_repository.get_session(session_id)
        order_id = session.order_id if session else None

        if order_id:
            order = self.order_repository.get_order_by_id(order_id)
            if order:
                return order

        # Crear nueva orden
        order = self.order_repository.create_order(
            customer_id=session.customer_id if session else None
        )
        if session_id:
            self.session_repository.link_session_to_order(
                session_id=session_id, order_id=order.id
            )
        return order

    async def _execute_order_operation(
        self,
        session_id: str,
        operation: str,
        mutator,
    ) -> Dict[str, Any]:
        """Ejecuta una operación atómica sobre la orden: load → mutate → save → return.

        Args:
            session_id: Identificador de la sesión.
            operation: Nombre de la operación (para logging).
            mutator: Callable que recibe (Order) y retorna dict con datos del resultado.

        Returns:
            Dict con {success, data, error}.
        """
        try:
            order = await self.get_or_create_order(session_id)
            data = mutator(order)
            self.order_repository.save_order(order)
            return {"success": True, "data": data, "error": None}
        except ValueError as e:
            return {"success": False, "data": None, "error": str(e)}
        except Exception as e:
            return {"success": False, "data": None, "error": f"{type(e).__name__}: {e}"}

    async def add_item(self, session_id: str, params: dict) -> Dict[str, Any]:
        """Agrega un item a la orden activa.

        Args:
            session_id: Identificador de la sesión.
            params: Dict con protein, quantity, size, principle, requirements, unit_price.

        Returns:
            Dict con {success, data: {item_id, order_summary}, error}.
        """
        def _add_item(order):
            from src.core.order.domain.models import OrderItem
            from uuid import uuid4

            item = OrderItem(
                id=f"item-{str(uuid4())[:8]}",
                quantity=params.get("quantity", 1),
                protein=params.get("protein"),
                principle=params.get("principle"),
                size=params.get("size", ""),
                unit_price=float(params.get("unit_price", 0)),
                requirements=params.get("requirements", []) or [],
            )
            order.add_item(item)
            # Marcar campos del item como respondidos
            for field in ("protein", "principle", "size"):
                if params.get(field):
                    order.field_states[field] = "answered"
            return {
                "item_id": item.id,
                "order_summary": order.to_summary(),
            }

        return await self._execute_order_operation(session_id, "add_item", _add_item)

    async def remove_item(self, session_id: str, item_id: str) -> Dict[str, Any]:
        """Elimina un item de la orden activa por su ID.

        Args:
            session_id: Identificador de la sesión.
            item_id: ID del item a eliminar.

        Returns:
            Dict con {success, data: {removed_item_id, order_summary}, error}.
        """
        def _remove_item(order):
            removed = order.remove_item(item_id)
            return {
                "removed_item_id": item_id,
                "order_summary": order.to_summary(),
            }

        return await self._execute_order_operation(session_id, "remove_item", _remove_item)

    async def update_item(self, session_id: str, item_id: str, changes: dict) -> Dict[str, Any]:
        """Actualiza un item existente en la orden activa.

        Args:
            session_id: Identificador de la sesión.
            item_id: ID del item a actualizar.
            changes: Dict con campos a actualizar (quantity, protein, size, etc.).

        Returns:
            Dict con {success, data: {item_id, order_summary}, error}.
        """
        def _update_item(order):
            order.update_item(item_id, **changes)
            # Marcar campos del item como respondidos
            for field in ("protein", "principle", "size"):
                if changes.get(field):
                    order.field_states[field] = "answered"
            return {
                "item_id": item_id,
                "order_summary": order.to_summary(),
            }

        return await self._execute_order_operation(session_id, "update_item", _update_item)

    async def get_order(self, session_id: str) -> Dict[str, Any]:
        """Obtiene el resumen de la orden activa.

        Args:
            session_id: Identificador de la sesión.

        Returns:
            Dict con {success, data: {order_id, items, status, total}, error}.
        """
        try:
            session = self.session_repository.get_session(session_id)
            if not session or not session.order_id:
                return {
                    "success": True,
                    "data": {"order_id": None, "items": [], "status": None, "total": 0.0},
                    "error": None,
                }

            order = self.order_repository.get_order_by_id(session.order_id)
            if not order:
                return {
                    "success": True,
                    "data": {"order_id": None, "items": [], "status": None, "total": 0.0},
                    "error": None,
                }

            return {
                "success": True,
                "data": {
                    "order_id": order.id,
                    "items": [item.to_dict() for item in order.items],
                    "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                    "total": order.total_amount,
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "data": None, "error": f"{type(e).__name__}: {e}"}

    async def confirm_order(self, session_id: str) -> Dict[str, Any]:
        """Confirma la orden activa (cambia estado a confirmed).

        Args:
            session_id: Identificador de la sesión.

        Returns:
            Dict con {success, data: {order_id, status}, error}.
        """
        def _confirm(order):
            if not order.items:
                raise ValueError("No items to confirm. Add items to the order first.")
            from src.core.order.domain.models import OrderStatus
            order.status = OrderStatus.CONFIRMED
            return {"order_id": order.id, "status": "confirmed"}

        return await self._execute_order_operation(session_id, "confirm_order", _confirm)

    async def cancel_order(self, session_id: str) -> Dict[str, Any]:
        """Cancela la orden activa (cambia estado a cancelled).

        Args:
            session_id: Identificador de la sesión.

        Returns:
            Dict con {success, data: {order_id, status}, error}.
        """
        def _cancel(order):
            from src.core.order.domain.models import OrderStatus
            order.status = OrderStatus.CANCELLED
            order.items.clear()
            return {"order_id": order.id, "status": "cancelled"}

        return await self._execute_order_operation(session_id, "cancel_order", _cancel)

    async def get_order_checklist(self, session_id: str) -> str:
        """Return a structured checklist string of all order fields.

        Stateless — reads the current Order aggregate and reports which
        canonical fields have values and which are pending.
        Designed to be injected into the Planner's system prompt context.

        Args:
            session_id: Current session identifier.

        Returns:
            Checklist string (one field per line), or "No hay pedido activo."
        """
        from src.core.order.application.order_flow_tracker import build_checklist_from_order
        session = self.session_repository.get_session(session_id)
        if not session or not session.order_id:
            return "No hay pedido activo."
        order = self.order_repository.get_order_by_id(session.order_id)
        return build_checklist_from_order(order)

    # ── Order metadata (update-order) ─────────────────────────────

    async def update_order(self, session_id: str, params: dict) -> Dict[str, Any]:
        """Actualiza metadatos de la orden (campos a nivel de orden, no de item).

        Acepta los campos: customer_name, con_todo, service_type, address,
        scheduled_time, payment_method, observations.

        Args:
            session_id: Identificador de la sesión.
            params: Dict con los campos a actualizar.

        Returns:
            Dict con {success, data: {updated_fields, order_summary}, error}.
        """
        try:
            from datetime import datetime
            from src.core.order.domain.models import ServiceCategory

            order = await self.get_or_create_order(session_id)
            updated = []

            if "customer_name" in params:
                order.customer_id = params["customer_name"]
                updated.append("customer_name")

            if "con_todo" in params:
                order.con_todo = params["con_todo"]
                updated.append("con_todo")

            if "service_type" in params:
                st = params["service_type"].lower()
                if st in ("delivery", "a domicilio", "domicilio"):
                    addr = params.get("address", order.address or "")
                    order.set_delivery(address=addr)
                    updated.append("service_type")
                elif st in ("pickup", "recoger", "para llevar"):
                    order.set_pickup()
                    updated.append("service_type")

            if "address" in params:
                addr_val = params["address"]
                if order.service and order.service.category == ServiceCategory.DELIVERY:
                    order.service.details.address = addr_val
                else:
                    order.set_delivery(address=addr_val)
                updated.append("address")

            if "scheduled_time" in params:
                st_val = params["scheduled_time"]
                if order.service and order.service.category == ServiceCategory.PICKUP:
                    try:
                        dt = datetime.fromisoformat(st_val)
                        order.service.details.scheduled_time = dt
                    except (ValueError, TypeError):
                        pass
                else:
                    order.set_pickup()
                    try:
                        dt = datetime.fromisoformat(st_val)
                        order.service.details.scheduled_time = dt
                    except (ValueError, TypeError):
                        pass
                updated.append("scheduled_time")

            if "payment_method" in params:
                order.payment_method = params["payment_method"]
                updated.append("payment_method")

            if "observations" in params:
                obs = params["observations"]
                if isinstance(obs, list):
                    order.observations.extend(o for o in obs if o not in order.observations)
                elif isinstance(obs, str) and obs not in order.observations:
                    order.observations.append(obs)
                updated.append("observations")

            # Marcar campos como respondidos
            for field in updated:
                order.field_states[field] = "answered"

            self.order_repository.save_order(order)

            return {
                "success": True,
                "data": {
                    "updated_fields": updated,
                    "order_summary": order.to_summary(),
                },
                "error": None,
            }
        except Exception as e:
            return {"success": False, "data": None, "error": f"{type(e).__name__}: {e}"}
