"""
Tests de integración para el dispatch de synthetic order tools.

Verifica que SkillToolAdapter.execute_tool() enrute cada uno de los 6
tool names al método CRUD correcto en OrderOrchestrator, y que normalize
el formato de retorno de {success, data, error} a {success, result, error}.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.agent.skill_tools import (
    SkillToolAdapter,
    _SYNTHETIC_ORDER_TOOL_MAP,
)


# ── Helpers ───────────────────────────────────────────────────────

@pytest.fixture
def mock_orchestrator():
    """Creates an OrderOrchestrator mock with all CRUD methods as AsyncMock."""
    orch = MagicMock()
    orch.add_item = AsyncMock(return_value={
        "success": True, "data": {"item_id": "item-abc", "order_summary": {}}, "error": None,
    })
    orch.remove_item = AsyncMock(return_value={
        "success": True, "data": {"removed_item_id": "item-abc", "order_summary": {}}, "error": None,
    })
    orch.update_item = AsyncMock(return_value={
        "success": True, "data": {"item_id": "item-abc", "order_summary": {}}, "error": None,
    })
    orch.get_order = AsyncMock(return_value={
        "success": True, "data": {"order_id": "ORD-1", "items": [], "status": "draft", "total": 0.0}, "error": None,
    })
    orch.confirm_order = AsyncMock(return_value={
        "success": True, "data": {"order_id": "ORD-1", "status": "confirmed"}, "error": None,
    })
    orch.cancel_order = AsyncMock(return_value={
        "success": True, "data": {"order_id": "ORD-1", "status": "cancelled"}, "error": None,
    })
    return orch


@pytest.fixture
def dispatch_context(mock_orchestrator):
    """Builds the orchestration context dict that execute_tool() expects."""
    return {
        "order_orchestrator": mock_orchestrator,
        "session_id": "test-session-001",
        "llm_client": MagicMock(),
        "skill_orchestrator": MagicMock(),
        "streamer": None,
        "settings": MagicMock(),
        "trace_id": "trace-001",
    }


# ─── Tests ────────────────────────────────────────────────────────

class TestAddItemDispatch:
    """Verifica que 'add-item' se enrute a order_orchestrator.add_item()."""

    async def test_dispatch_add_item(self, dispatch_context, mock_orchestrator):
        result = await SkillToolAdapter.execute_tool(
            "add-item", {"protein": "Tacos", "quantity": 2}, dispatch_context,
        )
        mock_orchestrator.add_item.assert_awaited_once_with(
            "test-session-001", {"protein": "Tacos", "quantity": 2},
        )
        assert result["success"] is True
        assert result["result"] == {"item_id": "item-abc", "order_summary": {}}


class TestRemoveItemDispatch:
    """Verifica que 'remove-item' se enrute a order_orchestrator.remove_item()."""

    async def test_dispatch_remove_item(self, dispatch_context, mock_orchestrator):
        result = await SkillToolAdapter.execute_tool(
            "remove-item", {"item_id": "item-abc"}, dispatch_context,
        )
        mock_orchestrator.remove_item.assert_awaited_once_with(
            "test-session-001", "item-abc",
        )
        assert result["success"] is True
        assert result["result"]["removed_item_id"] == "item-abc"


class TestUpdateItemDispatch:
    """Verifica que 'update-item' se enrute a order_orchestrator.update_item()."""

    async def test_dispatch_update_item(self, dispatch_context, mock_orchestrator):
        result = await SkillToolAdapter.execute_tool(
            "update-item", {"item_id": "item-abc", "quantity": 5}, dispatch_context,
        )
        mock_orchestrator.update_item.assert_awaited_once_with(
            "test-session-001", "item-abc", {"quantity": 5},
        )
        assert result["success"] is True

    async def test_dispatch_update_item_excludes_item_id_from_changes(self, dispatch_context, mock_orchestrator):
        """item_id se extrae de args y no se pasa en changes."""
        result = await SkillToolAdapter.execute_tool(
            "update-item", {"item_id": "item-abc", "quantity": 3, "protein": "Pollo"}, dispatch_context,
        )
        mock_orchestrator.update_item.assert_awaited_once_with(
            "test-session-001", "item-abc", {"quantity": 3, "protein": "Pollo"},
        )
        assert result["success"] is True


class TestGetOrderDispatch:
    """Verifica que 'get-order' se enrute a order_orchestrator.get_order()."""

    async def test_dispatch_get_order(self, dispatch_context, mock_orchestrator):
        result = await SkillToolAdapter.execute_tool(
            "get-order", {}, dispatch_context,
        )
        mock_orchestrator.get_order.assert_awaited_once_with("test-session-001")
        assert result["success"] is True
        assert result["result"]["status"] == "draft"


class TestConfirmOrderDispatch:
    """Verifica que 'confirm-order' se enrute a order_orchestrator.confirm_order()."""

    async def test_dispatch_confirm_order(self, dispatch_context, mock_orchestrator):
        result = await SkillToolAdapter.execute_tool(
            "confirm-order", {}, dispatch_context,
        )
        mock_orchestrator.confirm_order.assert_awaited_once_with("test-session-001")
        assert result["success"] is True
        assert result["result"]["status"] == "confirmed"


class TestCancelOrderDispatch:
    """Verifica que 'cancel-order' se enrute a order_orchestrator.cancel_order()."""

    async def test_dispatch_cancel_order(self, dispatch_context, mock_orchestrator):
        result = await SkillToolAdapter.execute_tool(
            "cancel-order", {}, dispatch_context,
        )
        mock_orchestrator.cancel_order.assert_awaited_once_with("test-session-001")
        assert result["success"] is True
        assert result["result"]["status"] == "cancelled"


# ── Error handling tests ──────────────────────────────────────────

class TestDispatchErrors:
    """Verifica el manejo de errores en el dispatch."""

    async def test_missing_order_orchestrator_returns_error(self, dispatch_context):
        """Sin order_orchestrator en context, retorna error."""
        del dispatch_context["order_orchestrator"]
        result = await SkillToolAdapter.execute_tool(
            "add-item", {"protein": "Tacos"}, dispatch_context,
        )
        assert result["success"] is False
        assert "order_orchestrator" in result["error"]

    async def test_missing_session_id_returns_error(self, dispatch_context):
        """Sin session_id en context, retorna error."""
        del dispatch_context["session_id"]
        result = await SkillToolAdapter.execute_tool(
            "add-item", {"protein": "Tacos"}, dispatch_context,
        )
        assert result["success"] is False
        assert "session_id" in result["error"]

    async def test_error_from_crud_is_propagated(self, dispatch_context, mock_orchestrator):
        """Si el CRUD retorna error, execute_tool lo propaga."""
        mock_orchestrator.add_item.return_value = {
            "success": False, "data": None, "error": "Something went wrong",
        }
        result = await SkillToolAdapter.execute_tool(
            "add-item", {"protein": "Tacos"}, dispatch_context,
        )
        assert result["success"] is False
        assert result["error"] == "Something went wrong"

    async def test_unknown_synthetic_tool_returns_error(self, dispatch_context):
        """Tool name desconocido en el mapa retorna error antes de tocar el CRUD."""
        result = await SkillToolAdapter.execute_tool(
            "nonexistent-tool", {}, dispatch_context,
        )
        # Should fall through to skill_orchestrator, but since it's a MagicMock
        # without proper setup, it should fail there — NOT in the synthetic branch.
        assert result["success"] is False  # falls through to skill load → fails
