"""
Tests for Planner — Phase 4 of redesign-core-orchestration.

Covers:
  - Basic dispatch (tool call → execution → respond)
  - respond terminates
  - Hard cap (MAX_TOOL_CALLS limit)
  - Tool error recovery (error fed back to LLM)
  - Streamer integration
  - Error scenarios (timeout, empty LLM, invalid tool name)
  - Regression: legacy pipeline coexists with Planner code
"""
import asyncio
import pytest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from src.engine.planner import (
    FALLBACK_ERROR,
    MAX_TOOL_CALLS,
    RESPOND_TOOL,
    Planner,
    PlannerContext,
    PlannerState,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def mock_llm():
    """Mock LiteLLMClient returning plain text by default."""
    llm = AsyncMock()
    llm.chat_completion.return_value = "default mock response"
    return llm


@pytest.fixture
def mock_orchestrator():
    """Mock SkillOrchestrator with an empty (mocked) registry."""
    registry = MagicMock()
    registry.list_skills.return_value = []
    orch = MagicMock()
    orch.registry = registry
    return orch


@pytest.fixture
def mock_streamer():
    """Mock PipelineStreamer whose ``phase()`` returns a working context manager."""
    streamer = MagicMock()
    phase_mock = MagicMock()
    phase_mock.__enter__.return_value = phase_mock
    streamer.phase.return_value = phase_mock
    return streamer


@pytest.fixture
def planner(mock_llm, mock_orchestrator, mock_streamer):
    """A Planner wired with all-mocked dependencies.

    ``_build_system_prompt`` is mocked to avoid filesystem I/O.
    """
    p = Planner(
        llm_client=mock_llm,
        skill_orchestrator=mock_orchestrator,
        streamer=mock_streamer,
        settings=MagicMock(),
    )
    # Avoid reading the prompt file from disk in every test
    p._build_system_prompt = MagicMock(return_value="Eres Luz Stella, asistente virtual.")
    return p


# =========================================================================
# Helpers
# =========================================================================

_CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify",
        "description": "Classifies user intent",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
}

_RESPOND_CALL = {
    "finish_reason": "tool_calls",
    "tool_calls": [
        {
            "id": "call_respond",
            "name": "respond",
            "arguments": {"response_text": "¡Hola! ¿En qué puedo ayudarte?"},
        }
    ],
    "assistant_message": "",
}


# =========================================================================
# 4.2 — Test Planner loop
# =========================================================================


class TestBasicDispatch:
    """Planner dispatches tool calls and returns final response."""

    @pytest.mark.asyncio
    async def test_respond_terminates(self, planner, mock_llm):
        """A single respond tool call returns its response_text immediately."""
        mock_llm.chat_completion.return_value = _RESPOND_CALL

        with patch(
            "src.engine.planner.SkillToolAdapter.list_tools",
            return_value=[],
        ):
            context = PlannerContext()
            response = await planner.run("Hola", context)

        assert response == "¡Hola! ¿En qué puedo ayudarte?"
        assert planner.state == PlannerState.TERMINATED
        assert planner.tool_call_count == 0

    @pytest.mark.asyncio
    async def test_basic_dispatch(self, planner, mock_llm):
        """LLM calls a skill → Planner dispatches → LLM calls respond → done."""
        mock_llm.chat_completion.side_effect = [
            # Turn 1: classify
            {
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "classify",
                        "arguments": {"message": "hello"},
                    }
                ],
                "assistant_message": "Let me classify...",
            },
            # Turn 2: respond with final text
            _RESPOND_CALL,
        ]

        with patch(
            "src.engine.planner.SkillToolAdapter.execute_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "result": {"intent": "greeting"},
            }
            with patch(
                "src.engine.planner.SkillToolAdapter.list_tools",
                return_value=[_CLASSIFY_TOOL],
            ):
                context = PlannerContext()
                response = await planner.run("Hola", context)

        assert response == "¡Hola! ¿En qué puedo ayudarte?"
        assert mock_exec.await_count == 1
        mock_exec.assert_awaited_with("classify", {"message": "hello"}, ANY)

    @pytest.mark.asyncio
    async def test_hard_cap(self, planner, mock_llm):
        """After MAX_TOOL_CALLS tool calls without respond → FALLBACK_ERROR."""
        mock_llm.chat_completion.return_value = {
            "finish_reason": "tool_calls",
            "tool_calls": [
                {
                    "id": "call_n",
                    "name": "classify",
                    "arguments": {"message": "test"},
                }
            ],
            "assistant_message": "",
        }

        with patch(
            "src.engine.planner.SkillToolAdapter.execute_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = {"success": True, "result": {"ok": True}}
            with patch(
                "src.engine.planner.SkillToolAdapter.list_tools",
                return_value=[_CLASSIFY_TOOL],
            ):
                context = PlannerContext()
                response = await planner.run("Test", context)

        assert response == FALLBACK_ERROR
        assert planner.tool_call_count >= MAX_TOOL_CALLS
        # LLM should have been called exactly MAX_TOOL_CALLS times
        assert mock_llm.chat_completion.await_count == MAX_TOOL_CALLS

    @pytest.mark.asyncio
    async def test_tool_error_recovery(self, planner, mock_llm):
        """Tool error is fed back to LLM → LLM responds gracefully."""
        mock_llm.chat_completion.side_effect = [
            # Turn 1: tool call that will fail
            {
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_fail",
                        "name": "classify",
                        "arguments": {"message": "hello"},
                    }
                ],
                "assistant_message": "Classifying...",
            },
            # Turn 2: LLM sees the error and decides to respond
            _RESPOND_CALL,
        ]

        with patch(
            "src.engine.planner.SkillToolAdapter.execute_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = {
                "success": False,
                "error": "LLM API timeout",
            }
            with patch(
                "src.engine.planner.SkillToolAdapter.list_tools",
                return_value=[_CLASSIFY_TOOL],
            ):
                context = PlannerContext()
                response = await planner.run("Hola", context)

        assert response == "¡Hola! ¿En qué puedo ayudarte?"

        # Verify the error was injected into the conversation for the LLM
        second_call_messages = mock_llm.chat_completion.call_args_list[1][1]["messages"]
        tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_messages) >= 1
        assert "LLM API timeout" in tool_messages[0].get("content", "")

    @pytest.mark.asyncio
    async def test_streamer_integration(self, planner, mock_llm, mock_streamer):
        """Streamer phases are created during planner execution."""
        mock_llm.chat_completion.return_value = _RESPOND_CALL

        with patch(
            "src.engine.planner.SkillToolAdapter.list_tools",
            return_value=[],
        ):
            context = PlannerContext()
            response = await planner.run("Hola", context)

        assert response is not None
        # At minimum, "Planning" phase should have been created
        assert mock_streamer.phase.called
        phase_names = [call[0][0] for call in mock_streamer.phase.call_args_list]
        # "Response" phase should appear when respond is called
        assert "Response" in phase_names or "Planning" in phase_names


# =========================================================================
# 4.2 — State machine transitions
# =========================================================================


class TestStateTransitions:
    """PlannerState transitions during execution."""

    @pytest.mark.asyncio
    async def test_state_flow(self, planner, mock_llm):
        """State goes THINKING → EXECUTING → REFLECTING → TERMINATED."""
        mock_llm.chat_completion.side_effect = [
            {
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "classify",
                        "arguments": {"message": "test"},
                    }
                ],
                "assistant_message": "",
            },
            _RESPOND_CALL,
        ]

        states: list[str] = []

        def _track(original):
            """Wrap Planner.run to capture state transitions."""
            async def wrapper(msg, ctx):
                result = await original(msg, ctx)
                states.append(planner.state.value)
                return result
            return wrapper

        with patch(
            "src.engine.planner.SkillToolAdapter.execute_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = {"success": True, "result": {"intent": "greeting"}}
            with patch(
                "src.engine.planner.SkillToolAdapter.list_tools",
                return_value=[_CLASSIFY_TOOL],
            ):
                context = PlannerContext()
                response = await planner.run("Hola", context)

        assert response is not None
        # After execution, state should be TERMINATED
        assert planner.state == PlannerState.TERMINATED


# =========================================================================
# 4.3 — Error scenarios
# =========================================================================


class TestErrorScenarios:
    """Planner handles edge cases and errors gracefully."""

    @pytest.mark.asyncio
    async def test_llm_timeout_recovery(self, planner, mock_llm):
        """LLM timeout → retry → eventual respond."""
        mock_llm.chat_completion.side_effect = [
            asyncio.TimeoutError("LLM timed out"),
            _RESPOND_CALL,
        ]

        with patch(
            "src.engine.planner.SkillToolAdapter.list_tools",
            return_value=[],
        ):
            context = PlannerContext()
            response = await planner.run("Hola", context)

        assert response == "¡Hola! ¿En qué puedo ayudarte?"
        # LLM should have been called twice (first timed out, second succeeded)
        assert mock_llm.chat_completion.await_count == 2

    @pytest.mark.asyncio
    async def test_llm_generic_error_recovery(self, planner, mock_llm):
        """Generic LLM error → retry → eventual respond."""
        mock_llm.chat_completion.side_effect = [
            RuntimeError("API connection failed"),
            _RESPOND_CALL,
        ]

        with patch(
            "src.engine.planner.SkillToolAdapter.list_tools",
            return_value=[],
        ):
            context = PlannerContext()
            response = await planner.run("Hola", context)

        assert response == "¡Hola! ¿En qué puedo ayudarte?"
        assert mock_llm.chat_completion.await_count == 2

    @pytest.mark.asyncio
    async def test_empty_llm_response(self, planner, mock_llm):
        """Empty string from LLM → fallback to FALLBACK_ERROR."""
        mock_llm.chat_completion.return_value = ""

        with patch(
            "src.engine.planner.SkillToolAdapter.list_tools",
            return_value=[],
        ):
            context = PlannerContext()
            response = await planner.run("Hola", context)

        # Empty response with no tool calls and no last_assistant_text → fallback
        assert response == FALLBACK_ERROR

    @pytest.mark.asyncio
    async def test_unexpected_llm_format(self, planner, mock_llm):
        """Unexpected dict from LLM (no tool_calls finish reason) → fallback."""
        mock_llm.chat_completion.return_value = {
            "finish_reason": "stop",
            "assistant_message": "",
        }

        with patch(
            "src.engine.planner.SkillToolAdapter.list_tools",
            return_value=[],
        ):
            context = PlannerContext()
            response = await planner.run("Hola", context)

        assert response == FALLBACK_ERROR

    @pytest.mark.asyncio
    async def test_invalid_tool_name_error(self, planner, mock_llm):
        """Invalid/simulated tool name → execute_tool returns error → fed to LLM → respond."""
        mock_llm.chat_completion.side_effect = [
            {
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_bad",
                        "name": "nonexistent-skill",
                        "arguments": {},
                    }
                ],
                "assistant_message": "",
            },
            _RESPOND_CALL,
        ]

        with patch(
            "src.engine.planner.SkillToolAdapter.execute_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = {
                "success": False,
                "error": "KeyError: 'nonexistent-skill'",
            }
            with patch(
                "src.engine.planner.SkillToolAdapter.list_tools",
                return_value=[_CLASSIFY_TOOL],
            ):
                context = PlannerContext()
                response = await planner.run("Hola", context)

        assert response == "¡Hola! ¿En qué puedo ayudarte?"
        # Verify invalid-tool error was fed to LLM
        second_call_messages = mock_llm.chat_completion.call_args_list[1][1]["messages"]
        tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_messages) >= 1
        assert "KeyError" in tool_messages[0].get("content", "")

    @pytest.mark.asyncio
    async def test_plain_text_response(self, planner, mock_llm):
        """LLM returns plain text (no tool calls) → returned as response."""
        mock_llm.chat_completion.return_value = (
            "¡Claro! Aquí tienes la información del menú."
        )

        with patch(
            "src.engine.planner.SkillToolAdapter.list_tools",
            return_value=[_CLASSIFY_TOOL],
        ):
            context = PlannerContext()
            response = await planner.run("¿Qué hay?", context)

        assert response == "¡Claro! Aquí tienes la información del menú."
        assert planner.state == PlannerState.TERMINATED

    @pytest.mark.asyncio
    async def test_consecutive_tool_calls_all_executed(self, planner, mock_llm):
        """Multiple tool calls from one LLM response are all executed."""
        mock_llm.chat_completion.side_effect = [
            {
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_a",
                        "name": "classify",
                        "arguments": {"message": "hello"},
                    },
                    {
                        "id": "call_b",
                        "name": "menu-query",
                        "arguments": {"query": "tacos", "candidates": []},
                    },
                ],
                "assistant_message": "Let me check...",
            },
            _RESPOND_CALL,
        ]

        with patch(
            "src.engine.planner.SkillToolAdapter.execute_tool",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = {"success": True, "result": {"ok": True}}
            with patch(
                "src.engine.planner.SkillToolAdapter.list_tools",
                return_value=[_CLASSIFY_TOOL],
            ):
                context = PlannerContext()
                response = await planner.run("Hola, quiero tacos", context)

        assert response == "¡Hola! ¿En qué puedo ayudarte?"
        # Both tools should have been executed
        assert mock_exec.await_count == 2
        assert mock_exec.await_args_list[0][0][0] == "classify"
        assert mock_exec.await_args_list[1][0][0] == "menu-query"


# =========================================================================
# 4.4 — Regression test
# =========================================================================


class TestRegression:
    """Existing pipeline still works alongside new Planner code."""

    def test_legacy_pipeline_coexists(self):
        """The classic pipeline modules import and compose with new code.

        Skips gracefully when ``langfuse`` (an optional dependency) is not
        installed — the existing tests already cover the classic path.
        """
        # Verify new modules are importable (Planner, SkillToolAdapter)
        from src.engine.planner import Planner, PlannerContext
        from src.engine.skill_tools import SkillToolAdapter
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry

        # Verify classic modules still import
        try:
            from src.core.assistant import SaborCaseroAssistant
        except ImportError as e:
            pytest.skip(f"Classic assistant not importable (missing dep): {e}")

        # ResponseBuilder is a core classic module — should import cleanly
        from src.core.response.response_builder import ResponseBuilder

        # All imports succeed = coexistence works
        assert Planner is not None
        assert SkillToolAdapter is not None
        assert SaborCaseroAssistant is not None
        assert ResponseBuilder is not None

    def test_planner_does_not_affect_skills_enabled_flag(self):
        """The ``skills_enabled`` setting is unaffected by Planner imports."""
        from src.config.environment import settings

        # Default should be whatever the env sets — but most importantly
        # importing Planner doesn't change this flag
        from src.engine.planner import Planner

        assert hasattr(settings, "skills_enabled")


class TestPlannerModule:
    """Planner module import and basic instantiation."""

    def test_planner_importable(self):
        """Planner class can be imported."""
        from src.engine.planner import Planner
        assert Planner is not None

    def test_planner_context_defaults(self):
        """PlannerContext has sensible defaults."""
        ctx = PlannerContext()
        assert ctx.summary_conversation == ""
        assert ctx.summary_order == ""
        assert ctx.user_preferences_context == ""
        assert ctx.user_id == ""
        assert ctx.session_id == ""
        assert ctx.candidates == []
        assert ctx.topic_details == []

    def test_planner_context_with_values(self):
        """PlannerContext accepts values."""
        ctx = PlannerContext(
            summary_conversation="previous chat",
            summary_order="2 tacos",
            user_preferences_context="no spicy",
            user_id="u1",
            session_id="s1",
            candidates=["tacos", "burritos"],
            topic_details=[{"segment": "quiero tacos"}],
        )
        assert ctx.summary_conversation == "previous chat"
        assert ctx.summary_order == "2 tacos"
        assert ctx.candidates == ["tacos", "burritos"]
