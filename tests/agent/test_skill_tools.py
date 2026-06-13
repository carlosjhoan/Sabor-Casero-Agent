"""
Tests for SkillToolAdapter (Task 1.3).

RED phase: tests reference SkillToolAdapter, list_tools, execute_tool before they exist.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestListTools:
    """Verify SkillToolAdapter.list_tools() builds tool definitions from registry."""

    def test_list_tools_importable(self):
        """SkillToolAdapter can be imported."""
        from src.engine.skill_tools import SkillToolAdapter
        assert SkillToolAdapter is not None

    def test_list_tools_returns_list(self):
        """list_tools() returns a list."""
        from src.engine.skill_tools import SkillToolAdapter
        registry = MagicMock()
        registry.get_tool_definitions.return_value = [
            {"type": "function", "function": {"name": "classify", "description": "test"}},
            {"type": "function", "function": {"name": "menu-query", "description": "test"}},
        ]
        tools = SkillToolAdapter.list_tools(registry)
        assert isinstance(tools, list)

    def test_list_tools_filters_automatic_skills(self):
        """list_tools() filters out memory-store, summarize, response-build."""
        from src.engine.skill_tools import SkillToolAdapter
        registry = MagicMock()
        registry.get_tool_definitions.return_value = [
            {"type": "function", "function": {"name": "classify", "description": "test"}},
            {"type": "function", "function": {"name": "memory-store", "description": "test"}},
            {"type": "function", "function": {"name": "menu-query", "description": "test"}},
        ]
        tools = SkillToolAdapter.list_tools(registry)
        names = {t["function"]["name"] for t in tools}
        assert "classify" in names, "classify should be available as optional tool"
        assert "memory-store" not in names, "memory-store should be filtered"

    def test_list_tools_excludes_order_flow_includes_synthetic(self):
        """list_tools() excludes order-flow (now automatic) and includes synthetic order tools."""
        from src.engine.skill_tools import SkillToolAdapter
        from src.engine.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover("skills")
        tools = SkillToolAdapter.list_tools(registry)
        names = {t["function"]["name"] for t in tools}
        assert "classify" in names
        assert "order-flow" not in names, "order-flow moved to _AUTOMATIC_SKILLS"
        for tool_name in ("add-item", "remove-item", "update-item",
                          "get-order", "confirm-order", "cancel-order"):
            assert tool_name in names, f"synthetic tool '{tool_name}' should be in list_tools()"

    def test_list_tools_includes_owl_skills_when_enabled(self):
        """When USE_OWL=True, OWL-dependent skills should be present."""
        from src.engine.skill_tools import SkillToolAdapter
        from src.engine.skill_registry import SkillRegistry
        from src.config.environment import settings
        # Only assert OWL skills exist if OWL is enabled in this env
        if settings.use_owl:
            registry = SkillRegistry()
            registry.discover("skills")
            tools = SkillToolAdapter.list_tools(registry)
            names = {t["function"]["name"] for t in tools}
            assert "menu-query" in names, "menu-query requires OWL"
            assert "rag-retrieve" in names, "rag-retrieve requires OWL"
            assert "get-full-menu" in names, "get-full-menu requires OWL"

    def test_list_tools_descriptions_are_non_empty(self):
        """Each tool definition has a non-empty description."""
        from src.engine.skill_tools import SkillToolAdapter
        from src.engine.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover("skills")
        tools = SkillToolAdapter.list_tools(registry)
        for tool in tools:
            desc = tool["function"]["description"]
            assert desc, f"Tool '{tool['function']['name']}' has empty description"


class TestExecuteTool:
    """Verify SkillToolAdapter.execute_tool() loads skill and runs it."""

    @pytest.fixture
    def tool_context(self):
        """Build a minimal context dict for tool execution.

        ``skill_orchestrator`` is a ``MagicMock`` because ``load_skill``
        is synchronous (returns ``BaseSkill`` directly). The returned
        mock skill, however, is an ``AsyncMock`` because ``execute()`` is async.
        """
        orchestrator = MagicMock()
        orchestrator.load_skill = MagicMock()  # sync method
        return {
            "llm_client": AsyncMock(),
            "skill_orchestrator": orchestrator,
            "streamer": AsyncMock(),
            "settings": MagicMock(),
            "summary_conversation": "",
            "summary_order": "",
            "user_preferences_context": "",
            "candidates": [],
            "trace_id": "test-trace",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_skill_result(self, success: bool, value=None, error_msg: str = ""):
        """Build a mock SkillResult that behaves like SkillResult."""
        mock_result = MagicMock(spec=["success", "value", "error"])
        mock_result.success = success
        mock_result.value = value
        mock_result.error = RuntimeError(error_msg) if not success else None
        # Serialize as dict for the return
        return mock_result

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    async def test_execute_tool_calls_orchestrator_load_skill(self, tool_context):
        """execute_tool() loads the skill via orchestrator.load_skill()."""
        from src.engine.skill_tools import SkillToolAdapter

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = self._make_skill_result(True, {"result": "ok"})
        tool_context["skill_orchestrator"].load_skill.return_value = mock_skill

        await SkillToolAdapter.execute_tool(
            "classify", {"message": "hello"}, tool_context
        )

        tool_context["skill_orchestrator"].load_skill.assert_called_once_with(
            "classify", context=tool_context
        )

    async def test_execute_tool_runs_skill(self, tool_context):
        """execute_tool() calls skill.execute() with input_data."""
        from src.engine.skill_tools import SkillToolAdapter

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = self._make_skill_result(
            True, {"classification": {"intent": "greeting"}}
        )
        tool_context["skill_orchestrator"].load_skill.return_value = mock_skill

        await SkillToolAdapter.execute_tool(
            "classify", {"message": "hello"}, tool_context
        )

        mock_skill.execute.assert_called_once()

    async def test_execute_tool_returns_success_dict(self, tool_context):
        """execute_tool() returns a dict with success=True on normal execution."""
        from src.engine.skill_tools import SkillToolAdapter

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = self._make_skill_result(True, {"result": "data"})
        tool_context["skill_orchestrator"].load_skill.return_value = mock_skill

        result = await SkillToolAdapter.execute_tool(
            "classify", {"message": "hello"}, tool_context
        )

        assert result["success"] is True
        assert result["result"] == {"result": "data"}

    async def test_execute_tool_returns_error_on_load_failure(self, tool_context):
        """execute_tool() returns {'success': False, 'error': ...} when load_skill fails."""
        from src.engine.skill_tools import SkillToolAdapter

        tool_context["skill_orchestrator"].load_skill.side_effect = KeyError("skill not found")

        result = await SkillToolAdapter.execute_tool("nonexistent", {}, tool_context)

        assert result["success"] is False
        assert "error" in result
        assert "skill not found" in result["error"]

    async def test_execute_tool_returns_error_on_skill_failure(self, tool_context):
        """execute_tool() returns error dict when skill execution fails."""
        from src.engine.skill_tools import SkillToolAdapter

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = self._make_skill_result(
            False, error_msg="SPARQL query failed"
        )
        tool_context["skill_orchestrator"].load_skill.return_value = mock_skill

        result = await SkillToolAdapter.execute_tool("menu-query", {"query": "tacos"}, tool_context)

        assert result["success"] is False
        assert "SPARQL query failed" in result["error"]

    async def test_execute_tool_injects_context_for_classify(self, tool_context):
        """execute_tool() auto-injects summary_conversation + summary_order for classify."""
        from src.engine.skill_tools import SkillToolAdapter

        tool_context["summary_conversation"] = "Previous conversation summary"
        tool_context["summary_order"] = "2 tacos al pastor"

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = self._make_skill_result(True, {"classification": {}})
        tool_context["skill_orchestrator"].load_skill.return_value = mock_skill

        await SkillToolAdapter.execute_tool("classify", {"message": "hello"}, tool_context)

        call_args, _ = mock_skill.execute.call_args
        input_data = call_args[0] if call_args else {}
        assert input_data.get("summary_conversation") == "Previous conversation summary"
        assert input_data.get("summary_order") == "2 tacos al pastor"

    async def test_execute_tool_injects_candidates_for_menu_query(self, tool_context):
        """execute_tool() auto-injects candidates for menu-query."""
        from src.engine.skill_tools import SkillToolAdapter

        tool_context["candidates"] = ["tacos", "burritos"]

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = self._make_skill_result(True, {"items": []})
        tool_context["skill_orchestrator"].load_skill.return_value = mock_skill

        await SkillToolAdapter.execute_tool("menu-query", {"query": "tacos"}, tool_context)

        call_args, _ = mock_skill.execute.call_args
        input_data = call_args[0] if call_args else {}
        assert input_data.get("candidates") == ["tacos", "burritos"]

    async def test_execute_tool_injects_candidates_for_rag_retrieve(self, tool_context):
        """execute_tool() auto-injects candidates for rag-retrieve."""
        from src.engine.skill_tools import SkillToolAdapter

        tool_context["candidates"] = ["tacos", "burritos", "enchiladas"]

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = self._make_skill_result(True, {"items": []})
        tool_context["skill_orchestrator"].load_skill.return_value = mock_skill

        await SkillToolAdapter.execute_tool(
            "rag-retrieve", {"query": "tacos"}, tool_context
        )

        call_args, _ = mock_skill.execute.call_args
        input_data = call_args[0] if call_args else {}
        assert input_data.get("candidates") == ["tacos", "burritos", "enchiladas"]

    async def test_execute_tool_injects_summary_for_order_flow(self, tool_context):
        """execute_tool() auto-injects summary_conversation for order-flow."""
        from src.engine.skill_tools import SkillToolAdapter

        tool_context["summary_conversation"] = "El cliente quiere dos tacos"
        tool_context["summary_order"] = "2x tacos al pastor"

        mock_skill = AsyncMock()
        mock_skill.execute.return_value = self._make_skill_result(True, {"result": "ok"})
        tool_context["skill_orchestrator"].load_skill.return_value = mock_skill

        await SkillToolAdapter.execute_tool(
            "order-flow",
            {"ordering_segments": ["dos tacos"], "session_id": "s1"},
            tool_context,
        )

        call_args, _ = mock_skill.execute.call_args
        input_data = call_args[0] if call_args else {}
        assert input_data.get("summary_conversation") == "El cliente quiere dos tacos"
        assert input_data.get("ordering_segments") == ["dos tacos"]
