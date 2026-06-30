# order/application/orchestrator.py

from typing import Dict, Any
from src.utils.utils import print_section
from src.core.order.domain.order_repository_interface import OrderRepository
from src.core.order.domain.session_repository_interface import SessionRepository


class OrderOrchestrator:
    """
    ORQUESTADOR PRINCIPAL de órdenes — CRUD methods for the Agentic Loop.
    
    Provides atomic order operations called by synthetic tools
    (add-item, remove-item, update-item, get-order, confirm-order,
    cancel-order, update-order, set-field-note, get_order_checklist).
    """
    
    def __init__(
        self,
        order_repository: OrderRepository,
        session_repository: SessionRepository,
        max_retries: int = 2
    ):
        self.order_repository = order_repository
        self.session_repository = session_repository
        self.max_retries = max_retries

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
        return build_checklist_from_order(order, field_status=session.field_status or {})

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

    async def set_field_note(self, session_id: str, field: str, note: str) -> Dict[str, Any]:
        """Marca un campo como 'asked' y guarda una observación.

        Útil cuando el Planner preguntó por un campo pero el usuario
        no respondió (preguntó otra cosa, se desvió, etc.).

        Args:
            session_id: Identificador de la sesión.
            field: Nombre del campo (protein, size, principle, etc.).
            note: Observación de lo que realmente pasó.

        Returns:
            Dict con {success, data: {field, state, note}, error}.
        """
        try:
            session = self.session_repository.get_session(session_id)
            if not session or not session.order_id:
                return {"success": False, "data": None, "error": "No hay pedido activo"}

            from datetime import datetime
            field_status = dict(session.field_status or {})
            existing = field_status.get(field)
            if existing:
                existing["state"] = "asked"
                if note not in existing.get("notes", []):
                    existing.setdefault("notes", []).append(note)
            else:
                field_status[field] = {
                    "state": "asked",
                    "notes": [note],
                    "created_at": datetime.now().isoformat(),
                }
            self.session_repository.update_session(session_id, field_status=field_status)

            from src.utils.utils import print_section
            print_section(
                head="📝 field-note",
                msg=f"{field} → asked | nota: {note}",
                symbol="→"
            )

            return {
                "success": True,
                "data": {"field": field, "state": "asked", "note": note},
                "error": None,
            }
        except Exception as e:
            return {"success": False, "data": None, "error": f"{type(e).__name__}: {e}"}
