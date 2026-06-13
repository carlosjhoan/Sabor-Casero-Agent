"""
Tests para los schemas de synthetic tools (granular-order-tools).

RED phase: los tests referencian las constantes _ADD_ITEM_TOOL ...
_CANCEL_ORDER_TOOL que aún no existen en SkillToolAdapter.
También verifican que list_tools() excluya order-flow.
"""
import pytest
from unittest.mock import MagicMock


# ── Schemas structure tests ───────────────────────────────────────

TOOL_NAMES = [
    "add-item", "remove-item", "update-item",
    "get-order", "confirm-order", "cancel-order",
]


class TestToolSchemasExist:
    """Verifica que cada constante de schema exista en SkillToolAdapter."""

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_tool_schema_constant_exists(self, tool_name):
        """Cada tool tiene una constante _<NAME>_TOOL en SkillToolAdapter."""
        from src.core.agent.skill_tools import SkillToolAdapter

        constant_name = f"_{tool_name.upper().replace('-', '_')}_TOOL"
        assert hasattr(SkillToolAdapter, constant_name), (
            f"Falta la constante {constant_name} para la tool {tool_name}"
        )

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    def test_tool_schema_structure(self, tool_name):
        """Cada schema tiene la estructura esperada: type, function.name, function.parameters."""
        from src.core.agent.skill_tools import SkillToolAdapter

        constant_name = f"_{tool_name.upper().replace('-', '_')}_TOOL"
        schema = getattr(SkillToolAdapter, constant_name)

        assert isinstance(schema, dict), f"{constant_name} debe ser un dict"
        assert schema.get("type") == "function", (
            f"{constant_name} debe tener type='function'"
        )
        func = schema.get("function", {})
        assert func.get("name") == tool_name, (
            f"{constant_name} debe tener function.name='{tool_name}', "
            f"got '{func.get('name')}'"
        )
        assert func.get("description"), (
            f"{constant_name} debe tener description no vacía"
        )
        params = func.get("parameters", {})
        assert params.get("type") == "object", (
            f"{constant_name} debe tener parameters.type='object'"
        )


class TestToolRequiredFields:
    """Verifica los campos requeridos de cada tool."""

    def test_add_item_no_required_fields(self):
        """add-item no tiene campos obligatorios — se puede crear parcialmente."""
        from src.core.agent.skill_tools import _ADD_ITEM_TOOL

        required = _ADD_ITEM_TOOL["function"]["parameters"].get("required", [])
        assert len(required) == 0, "add-item no debe requerir ningún campo — se completa con update-item"

    def test_add_item_has_all_params(self):
        """add-item tiene protein, quantity, size, principle, requirements, unit_price."""
        from src.core.agent.skill_tools import _ADD_ITEM_TOOL

        props = _ADD_ITEM_TOOL["function"]["parameters"].get("properties", {})
        expected = {"protein", "quantity", "size", "principle", "requirements", "unit_price"}
        for p in expected:
            assert p in props, f"add-item debe tener parámetro '{p}'"

    def test_remove_item_requires_item_id(self):
        """remove-item requiere item_id."""
        from src.core.agent.skill_tools import _REMOVE_ITEM_TOOL

        required = _REMOVE_ITEM_TOOL["function"]["parameters"].get("required", [])
        assert "item_id" in required

    def test_update_item_requires_item_id(self):
        """update-item requiere item_id."""
        from src.core.agent.skill_tools import _UPDATE_ITEM_TOOL

        required = _UPDATE_ITEM_TOOL["function"]["parameters"].get("required", [])
        assert "item_id" in required

    def test_get_order_no_required_params(self):
        """get-order no requiere parámetros."""
        from src.core.agent.skill_tools import _GET_ORDER_TOOL

        required = _GET_ORDER_TOOL["function"]["parameters"].get("required", [])
        assert required == []

    def test_confirm_order_no_required_params(self):
        """confirm-order no requiere parámetros."""
        from src.core.agent.skill_tools import _CONFIRM_ORDER_TOOL

        required = _CONFIRM_ORDER_TOOL["function"]["parameters"].get("required", [])
        assert required == []

    def test_cancel_order_no_required_params(self):
        """cancel-order no requiere parámetros."""
        from src.core.agent.skill_tools import _CANCEL_ORDER_TOOL

        required = _CANCEL_ORDER_TOOL["function"]["parameters"].get("required", [])
        assert required == []


class TestListToolsExcludesOrderFlow:
    """Verifica que list_tools() no incluya order-flow como tool."""

    def test_list_tools_excludes_order_flow(self):
        """list_tools() no incluye order-flow en la lista."""
        from src.core.agent.skill_tools import SkillToolAdapter
        from src.core.agent.skill_registry import SkillRegistry

        registry = SkillRegistry()
        registry.discover("skills")
        tools = SkillToolAdapter.list_tools(registry)
        names = {t["function"]["name"] for t in tools}

        assert "order-flow" not in names, (
            "order-flow no debe aparecer como tool llamable por el Planner"
        )

    def test_list_tools_includes_synthetic_order_tools(self):
        """list_tools() incluye los 6 synthetic order tools."""
        from src.core.agent.skill_tools import SkillToolAdapter
        from src.core.agent.skill_registry import SkillRegistry

        registry = SkillRegistry()
        registry.discover("skills")
        tools = SkillToolAdapter.list_tools(registry)
        names = {t["function"]["name"] for t in tools}

        for tool_name in TOOL_NAMES:
            assert tool_name in names, (
                f"list_tools() debe incluir '{tool_name}'"
            )

    def test_list_tools_does_not_include_automatic_skills(self):
        """list_tools() no incluye automatic skills como order-flow."""
        from src.core.agent.skill_tools import SkillToolAdapter, _AUTOMATIC_SKILLS

        assert "order-flow" in _AUTOMATIC_SKILLS, (
            "order-flow debe estar en _AUTOMATIC_SKILLS"
        )
