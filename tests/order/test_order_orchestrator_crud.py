"""
Tests para los nuevos métodos CRUD de OrderOrchestrator (granular-order-tools).

RED phase: estos tests referencian métodos que aún no existen en
OrderOrchestrator (add_item, remove_item, update_item, get_order,
confirm_order, cancel_order).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.order.domain.models import Order, OrderItem, OrderStatus
from tests.helpers.mock_repositories import InMemoryOrderRepository, InMemorySessionRepository


# ── Helpers ───────────────────────────────────────────────────────

def make_crud_orchestrator() -> tuple:
    """Create an OrderOrchestrator with in-memory repos for CRUD testing.

    Returns:
        (orchestrator, order_repo, session_repo) tuple.
    """
    order_repo = InMemoryOrderRepository()
    session_repo = InMemorySessionRepository()
    session = session_repo.create_session(customer_id="test-customer")
    session_id = session.session_id

    from src.core.order.application.orchestrator import OrderOrchestrator
    orchestrator = OrderOrchestrator(
        order_repository=order_repo,
        session_repository=session_repo,
    )
    return orchestrator, order_repo, session_repo, session_id


def add_sample_item(order: Order, protein: str = "Tacos", quantity: int = 2,
                    unit_price: float = 45.0) -> OrderItem:
    """Helper para agregar un item de prueba a una orden."""
    item = OrderItem(protein=protein, quantity=quantity, unit_price=unit_price)
    order.add_item(item)
    return item


# ── Tests: get_or_create_order ────────────────────────────────────

class TestGetOrCreateOrder:
    """Pruebas para el helper get_or_create_order."""

    async def test_get_or_create_order_creates_new_order(self):
        """Sin orden existente, crea y retorna una nueva orden."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        order = await orchestrator.get_or_create_order(session_id)

        assert order is not None
        assert order.id.startswith("ORD-")
        assert order.status == OrderStatus.DRAFT
        # Verificar que la orden se vinculó a la sesión
        updated_session = session_repo.get_session(session_id)
        assert updated_session.order_id == order.id

    async def test_get_or_create_order_returns_existing_order(self):
        """Si ya hay una orden vinculada, la retorna sin crear duplicado."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        first = await orchestrator.get_or_create_order(session_id)
        second = await orchestrator.get_or_create_order(session_id)

        assert second.id == first.id
        assert len(order_repo.get_all_orders()) == 1


# ── Tests: add_item ───────────────────────────────────────────────

class TestAddItem:
    """Pruebas para OrderOrchestrator.add_item()."""

    async def test_add_item_creates_order_and_adds_item(self):
        """add_item crea orden si no existe y agrega el item."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        result = await orchestrator.add_item(session_id, {
            "protein": "Tacos al Pastor",
            "quantity": 2,
            "unit_price": 45.0,
        })

        assert result["success"] is True
        data = result["data"]
        assert data["item_id"] is not None
        assert "order_summary" in data
        # Verificar que la orden se guardó
        orders = order_repo.get_all_orders()
        assert len(orders) == 1
        assert len(orders[0].items) == 1
        assert orders[0].items[0].protein == "Tacos al Pastor"

    async def test_add_item_with_minimal_params(self):
        """add_item funciona solo con protein (mínimo requerido)."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        result = await orchestrator.add_item(session_id, {
            "protein": "Tacos",
        })

        assert result["success"] is True
        data = result["data"]["order_summary"]
        assert "Tacos" in data or "items" in str(result["data"])

    async def test_add_item_with_full_params(self):
        """add_item acepta todos los parámetros opcionales."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        result = await orchestrator.add_item(session_id, {
            "protein": "Pollo",
            "quantity": 3,
            "size": "mini",
            "principle": "arroz",
            "requirements": ["sin cebolla"],
            "unit_price": 35.0,
        })

        assert result["success"] is True
        orders = order_repo.get_all_orders()
        item = orders[0].items[0]
        assert item.protein == "Pollo"
        assert item.quantity == 3
        assert item.size == "mini"
        assert item.principle == "arroz"
        assert "sin cebolla" in item.requirements
        assert item.unit_price == 35.0

    async def test_add_item_to_existing_order(self):
        """add_item agrega items a una orden existente."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        await orchestrator.add_item(session_id, {"protein": "Item A", "quantity": 1})
        await orchestrator.add_item(session_id, {"protein": "Item B", "quantity": 2})

        orders = order_repo.get_all_orders()
        assert len(orders) == 1
        assert len(orders[0].items) == 2


# ── Tests: remove_item ────────────────────────────────────────────

class TestRemoveItem:
    """Pruebas para OrderOrchestrator.remove_item()."""

    async def test_remove_item_removes_existing_item(self):
        """remove_item elimina un item existente y retorna éxito."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        add_result = await orchestrator.add_item(session_id, {"protein": "Tacos", "quantity": 1})
        item_id = add_result["data"]["item_id"]

        result = await orchestrator.remove_item(session_id, item_id)

        assert result["success"] is True
        assert result["data"]["removed_item_id"] == item_id
        orders = order_repo.get_all_orders()
        assert len(orders[0].items) == 0

    async def test_remove_nonexistent_item_returns_error(self):
        """remove_item con item_id inválido retorna error estructurado."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()
        await orchestrator.add_item(session_id, {"protein": "Tacos", "quantity": 1})

        result = await orchestrator.remove_item(session_id, "item-nonexistent")

        assert result["success"] is False
        assert result["error"] is not None

    async def test_remove_item_from_empty_order_returns_error(self):
        """remove_item sin orden activa retorna error."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        result = await orchestrator.remove_item(session_id, "item-any")

        assert result["success"] is False
        assert result["error"] is not None


# ── Tests: update_item ────────────────────────────────────────────

class TestUpdateItem:
    """Pruebas para OrderOrchestrator.update_item()."""

    async def test_update_item_quantity(self):
        """update_item cambia la cantidad de un item."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        add_result = await orchestrator.add_item(session_id, {"protein": "Tacos", "quantity": 1, "unit_price": 45.0})
        item_id = add_result["data"]["item_id"]

        result = await orchestrator.update_item(session_id, item_id, {"quantity": 5})

        assert result["success"] is True
        order = order_repo.get_all_orders()[0]
        item = order._find_item(item_id)
        assert item.quantity == 5

    async def test_update_nonexistent_item_returns_error(self):
        """update_item con item_id inválido retorna error."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        result = await orchestrator.update_item(session_id, "item-nonexistent", {"quantity": 3})

        assert result["success"] is False
        assert result["error"] is not None


# ── Tests: get_order ──────────────────────────────────────────────

class TestGetOrder:
    """Pruebas para OrderOrchestrator.get_order()."""

    async def test_get_order_returns_order_summary(self):
        """get_order retorna resumen de la orden activa."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()
        await orchestrator.add_item(session_id, {"protein": "Tacos", "quantity": 2, "unit_price": 45.0})

        result = await orchestrator.get_order(session_id)

        assert result["success"] is True
        data = result["data"]
        assert data["order_id"] is not None
        assert len(data["items"]) == 1
        assert data["status"] == "draft"
        assert data["total"] == 90.0

    async def test_get_order_no_active_order(self):
        """get_order sin orden activa retorna estado informativo."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        result = await orchestrator.get_order(session_id)

        assert result["success"] is True
        data = result["data"]
        assert data["items"] == []
        assert data["total"] == 0.0
        assert data["status"] is None or data["status"] == ""


# ── Tests: confirm_order ──────────────────────────────────────────

class TestConfirmOrder:
    """Pruebas para OrderOrchestrator.confirm_order()."""

    async def test_confirm_order_sets_status_confirmed(self):
        """confirm_order cambia el estado de la orden a confirmed."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()
        await orchestrator.add_item(session_id, {"protein": "Tacos", "quantity": 2})

        result = await orchestrator.confirm_order(session_id)

        assert result["success"] is True
        assert result["data"]["status"] == "confirmed"
        order = order_repo.get_all_orders()[0]
        assert order.status == OrderStatus.CONFIRMED

    async def test_confirm_empty_order_returns_error(self):
        """confirm_order con carrito vacío retorna error."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        # Crear orden vacía primero
        await orchestrator.get_or_create_order(session_id)

        result = await orchestrator.confirm_order(session_id)

        assert result["success"] is False
        assert result["error"] is not None
        assert "No items" in result["error"] or "vacío" in result["error"] or "empty" in result["error"].lower()

    async def test_confirm_without_order_returns_error(self):
        """confirm_order sin orden activa retorna error."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        result = await orchestrator.confirm_order(session_id)

        assert result["success"] is False
        assert result["error"] is not None


# ── Tests: cancel_order ───────────────────────────────────────────

class TestCancelOrder:
    """Pruebas para OrderOrchestrator.cancel_order()."""

    async def test_cancel_order_sets_status_cancelled(self):
        """cancel_order cambia el estado de la orden a cancelled."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()
        await orchestrator.add_item(session_id, {"protein": "Tacos", "quantity": 2})

        result = await orchestrator.cancel_order(session_id)

        assert result["success"] is True
        assert result["data"]["status"] == "cancelled"
        order = order_repo.get_all_orders()[0]
        assert order.status == OrderStatus.CANCELLED

    async def test_cancel_without_order_creates_and_cancels(self):
        """cancel_order sin orden activa crea una y la cancela."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()

        result = await orchestrator.cancel_order(session_id)

        assert result["success"] is True
        assert result["data"]["status"] == "cancelled"


# ── Tests: return format (R-ORCH-11) ──────────────────────────────

class TestReturnFormat:
    """Verifica que todos los métodos retornen {success, data, error}."""

    TOOL_METHODS = ["add_item", "remove_item", "update_item", "get_order", "confirm_order", "cancel_order"]

    async def test_all_methods_return_standard_format(self):
        """Cada método retorna dict con success, data, error."""
        orchestrator, order_repo, session_repo, session_id = make_crud_orchestrator()
        add_result = await orchestrator.add_item(session_id, {"protein": "Test", "quantity": 1})

        results = {
            "add_item": add_result,
            "get_order": await orchestrator.get_order(session_id),
            "cancel_order": await orchestrator.cancel_order(session_id),
        }

        for name, result in results.items():
            assert "success" in result, f"{name} missing 'success'"
            assert "data" in result, f"{name} missing 'data'"
            assert "error" in result, f"{name} missing 'error'"
