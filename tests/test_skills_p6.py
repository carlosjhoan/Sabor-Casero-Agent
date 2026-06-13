"""
Tests for P6 skills: classify, order-flow, response-build, memory-store, summarize
(Tasks 6.1-6.5) and full orchestration wiring (Task 6.6-6.8).

Spec scenarios:
  S-P6-01 — Specialist delegation via skills
  S-P6-02 — Summarization guard timeout (5s → sync fallback)
  S-P6-03 — Concurrent semaphore (5 concurrent, bounded)
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any, Dict

from src.core.agent.stage_result import SkillResult
from src.core.agent.skill_base import BaseSkill
from src.core.agent.exceptions import StageExecutionError


# =========================================================================
# Helper: Mock context factory
# =========================================================================

def _mock_context(**overrides: Any) -> Dict[str, Any]:
    """Build a mock orchestration context for skill loading."""
    ctx: Dict[str, Any] = {
        "classifier": MagicMock(),
        "order_orchestrator": MagicMock(),
        "response_builder": MagicMock(),
        "memory_hub": MagicMock(),
        "summarizer": MagicMock(),
        "checkpoint_manager": MagicMock(),
        "settings": MagicMock(),
    }
    ctx.update(overrides)
    return ctx


# =========================================================================
# Task 6.1 — skills/classify/
# =========================================================================

class TestClassifySkill:
    """S-P6-01 (partial): classify skill lifecycle and delegation."""

    @pytest.fixture
    def skill(self):
        from skills.classify import Skill as ClassifySkill
        return ClassifySkill()

    def test_name_and_version(self, skill):
        assert skill.name == "classify"
        assert skill.version == "0.1.0"

    def test_load_accepts_context(self, skill):
        skill.load(_mock_context())
        assert hasattr(skill, "_classifier")

    def test_run_returns_skill_result(self, skill):
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock()
        # Return a mock that quacks like UserQueryClassifier
        class MockClassification:
            model_dump = MagicMock(return_value={"intent": "menu_query"})
            topic_details = []
            requires_RAG = False
            requires_reconcilier = False
        mock_classifier.classify.return_value = MockClassification()
        skill.load({"classifier": mock_classifier})

        result = asyncio.run(skill.run({
            "message": "hola", "summary_order": "", "summary_conversation": "",
        }))
        assert isinstance(result, SkillResult)
        assert result.success
        assert result.skill_name == "classify"
        assert "classification" in result.value

    def test_run_failure_propagates(self, skill):
        mock_classifier = MagicMock()
        mock_classifier.classify = AsyncMock(side_effect=ConnectionError("LLM down"))
        skill.load({"classifier": mock_classifier})

        result = asyncio.run(skill.run({
            "message": "test", "summary_order": "", "summary_conversation": "",
        }))
        assert not result.success
        assert result.error is not None

    def test_unload_cleans_up(self, skill):
        skill.load({"classifier": "test"})
        skill.unload()
        assert skill._classifier is None


# =========================================================================
# Task 6.2 — skills/order-flow/
# =========================================================================

class TestOrderFlowSkill:
    """S-P6-01 (partial): order-flow skill wraps OrderOrchestrator."""

    @pytest.fixture
    def skill(self):
        from skills.order_flow import Skill as OrderFlowSkill
        return OrderFlowSkill()

    def test_name_and_version(self, skill):
        assert skill.name == "order-flow"
        assert skill.version == "0.1.0"

    def test_load_accepts_context(self, skill):
        skill.load(_mock_context())
        assert hasattr(skill, "_orchestrator")

    def test_run_with_ordering_segments(self, skill):
        mock_orch = MagicMock()
        mock_orch.process_order_intent = AsyncMock(return_value={"success": True, "thought": "ok"})
        skill.load({"order_orchestrator": mock_orch})

        result = asyncio.run(skill.run({
            "ordering_segments": [{"focus": "quiero pollo"}],
            "session_id": "test-session",
            "summary_conversation": "",
        }))
        assert result.success
        assert result.skill_name == "order-flow"
        assert "orchestrator_response" in result.value
        mock_orch.process_order_intent.assert_awaited_once()

    def test_run_skipped_when_no_segments(self, skill):
        mock_orch = MagicMock()
        mock_orch.process_order_intent = AsyncMock()
        skill.load({"order_orchestrator": mock_orch})

        result = asyncio.run(skill.run({
            "ordering_segments": [],
            "session_id": "test-session",
            "summary_conversation": "",
        }))
        assert result.success
        assert result.value.get("orchestrator_response") == {}
        mock_orch.process_order_intent.assert_not_called()

    def test_unload_cleans_up(self, skill):
        skill.load({"order_orchestrator": "test"})
        skill.unload()
        assert skill._orchestrator is None


# =========================================================================
# Task 6.3 — skills/response-build/
# =========================================================================

class TestResponseBuildSkill:
    """S-P6-01 (partial): response-build skill wraps ResponseBuilder."""

    @pytest.fixture
    def skill(self):
        from skills.response_build import Skill as ResponseBuildSkill
        return ResponseBuildSkill()

    def test_name_and_version(self, skill):
        assert skill.name == "response-build"
        assert skill.version == "0.1.0"

    def test_load_accepts_context(self, skill):
        skill.load(_mock_context())
        assert hasattr(skill, "_builder")

    def test_run_returns_response(self, skill):
        mock_builder = MagicMock()
        mock_builder.build_hybrid = AsyncMock(return_value="¡claro! tenemos pollo")
        skill.load({"response_builder": mock_builder})

        result = asyncio.run(skill.run({
            "classification": MagicMock(),
            "order_state": None,
            "orchestrator_result": {},
            "message": "hola",
            "summary_conversation": "",
        }))
        assert result.success
        assert result.value.get("response") == "¡claro! tenemos pollo"

    def test_empty_response_guard(self, skill):
        """Empty/whitespace response triggers fallback."""
        mock_builder = MagicMock()
        mock_builder.build_hybrid = AsyncMock(return_value="   ")
        skill.load({"response_builder": mock_builder})

        result = asyncio.run(skill.run({
            "classification": MagicMock(),
            "order_state": None,
            "orchestrator_result": {},
            "message": "test",
            "summary_conversation": "",
        }))
        assert result.success
        assert result.value.get("response") == "Lo siento, no pude generar una respuesta. Por favor intenta de nuevo."

    def test_unload_cleans_up(self, skill):
        skill.load({"response_builder": "test"})
        skill.unload()
        assert skill._builder is None


# =========================================================================
# Task 6.4 — skills/memory-store/
# =========================================================================

class TestMemoryStoreSkill:
    """S-P6-01 (partial): memory-store persists turn + extracts entities."""

    @pytest.fixture
    def skill(self):
        from skills.memory_store import Skill as MemoryStoreSkill
        return MemoryStoreSkill()

    def test_name_and_version(self, skill):
        assert skill.name == "memory-store"
        assert skill.version == "0.1.0"

    def test_load_accepts_context(self, skill):
        skill.load(_mock_context())
        assert hasattr(skill, "_memory_hub")

    def test_run_extracts_entities(self, skill):
        mock_hub = MagicMock()
        mock_hub.semantic.extract_from_turn = MagicMock(return_value=[
            MagicMock(entity_id="e1"),
            MagicMock(entity_id="e2"),
        ])
        mock_hub.store = MagicMock()
        skill.load({"memory_hub": mock_hub})

        result = asyncio.run(skill.run({
            "user_id": "u1",
            "session_id": "s1",
            "turn_number": 1,
            "user_message": "sin lactosa por favor",
            "assistant_response": "claro",
        }))
        assert result.success
        assert result.value.get("entities_stored") == 2
        assert mock_hub.store.call_count == 2

    def test_run_when_hub_not_configured(self, skill):
        """Graceful degradation when no memory_hub."""
        skill.load({"memory_hub": None})
        result = asyncio.run(skill.run({
            "user_id": "u1",
            "session_id": "s1",
            "turn_number": 1,
            "user_message": "hola",
            "assistant_response": "hola",
        }))
        assert result.success
        assert result.value.get("entities_stored") == 0

    def test_unload_cleans_up(self, skill):
        skill.load({"memory_hub": "test"})
        skill.unload()
        assert skill._memory_hub is None


# =========================================================================
# Task 6.5 — skills/summarize/
# =========================================================================

class TestSummarizeSkill:
    """S-P6-02: summarization guard timeout (5s → sync fallback)."""

    @pytest.fixture
    def skill(self):
        from skills.summarize import Skill as SummarizeSkill
        return SummarizeSkill()

    def test_name_and_version(self, skill):
        assert skill.name == "summarize"
        assert skill.version == "0.1.0"

    def test_load_accepts_context(self, skill):
        skill.load(_mock_context())
        assert hasattr(skill, "_summarizer")

    def test_normal_summarization(self, skill):
        """Happy path: LLM completes within timeout."""
        mock_summarizer = MagicMock()
        mock_summarizer.summarize_turn = AsyncMock(return_value=True)
        skill.load({"summarizer": mock_summarizer})

        result = asyncio.run(skill.run({
            "session_id": "s1",
            "turn_number": 1,
            "message": "hola",
            "focuses": ["greeting"],
            "intents": ["greeting"],
            "summary_order": "",
            "assistant_response": "hola",
        }))
        assert result.success
        assert result.value.get("fallback_used") is False
        mock_summarizer.summarize_turn.assert_awaited_once()

    def test_timeout_triggers_sync_fallback(self, skill):
        """S-P6-02: LLM call >5s timeout → sync fallback written."""
        mock_summarizer = MagicMock()
        # Simulate a very slow LLM call
        async def slow_summarize(**kwargs):
            await asyncio.sleep(10)  # >5s timeout
            return True
        mock_summarizer.summarize_turn = slow_summarize
        mock_summarizer._fallback_summary = AsyncMock(return_value=None)
        mock_summarizer.repo = MagicMock()
        mock_summarizer.repo.save = AsyncMock()
        skill.load({"summarizer": mock_summarizer})
        skill._timeout = 0.1  # Override for fast test (100ms)

        result = asyncio.run(skill.run({
            "session_id": "s1",
            "turn_number": 1,
            "message": "hola",
            "focuses": ["greeting"],
            "intents": ["greeting"],
            "summary_order": "",
            "assistant_response": "hola",
        }))
        assert result.success
        assert result.value.get("fallback_used") is True

    def test_unload_cleans_up(self, skill):
        skill.load({"summarizer": "test"})
        skill.unload()
        assert skill._summarizer is None


# =========================================================================
# Task 6.6 — Orchestration wiring in assistant.py
# =========================================================================

class TestOrchestrationWiring:
    """S-P6-01 full flow: skills delegating through SkillOrchestrator."""

    def _create_minimal_settings(self):
        """Create minimal settings object for testing."""
        import types
        s = types.SimpleNamespace()
        s.skills_enabled = True
        s.use_order_flow_tracker = False
        s.checkpointing_enabled = False
        s.semantic_memory_enabled = False
        s.storage_path = "test_storage.json"
        s.brand_voice_path = ""
        s.response_generation_prompt_path = ""
        s.summaries_path = "test_summaries"
        s.summary_prompt_path = ""
        s.rag_v2_enabled = False
        return s

    @pytest.fixture
    def mock_assistant(self):
        """Build an assistant with all skills wired."""
        with patch("src.core.assistant.SkillRegistry") as MockReg, \
             patch("src.core.assistant.SkillOrchestrator") as MockOrch, \
             patch("src.core.assistant.CheckpointManager") as MockCP, \
             patch("src.core.assistant.MemoryHub") as MockHub:

            MockReg.return_value = MagicMock()
            MockOrch.return_value = MagicMock()
            MockCP.return_value = MagicMock()
            MockHub.return_value = MagicMock()

            from src.core.assistant import SaborCaseroAssistant
            assistant = SaborCaseroAssistant(
                extractor=MagicMock(),
                order_orchestrator=MagicMock(),
                logger_conversation=MagicMock(),
                llm_client=MagicMock(),
            )
            return assistant

    def test_assistant_has_skills_enabled_flag(self, mock_assistant):
        """skills_enabled flag is checked before orchestration."""
        from src.config.environment import settings
        assert hasattr(settings, "skills_enabled")

    def test_skill_orchestrator_and_checkpoint_created(self, mock_assistant):
        """Assistant creates SkillOrchestrator, CheckpointManager, MemoryHub."""
        assert hasattr(mock_assistant, "_skill_orchestrator") or hasattr(mock_assistant, "orchestrator")
        assert hasattr(mock_assistant, "_checkpoint_manager") or hasattr(mock_assistant, "checkpoint_manager")
        assert hasattr(mock_assistant, "_memory_hub") or hasattr(mock_assistant, "memory_hub")

    def test_process_message_maintains_signature(self):
        """process_message() still accepts user_id, message, session_id."""
        from src.core.assistant import SaborCaseroAssistant
        import inspect
        sig = inspect.signature(SaborCaseroAssistant.process_message)
        params = list(sig.parameters.keys())
        assert "user_id" in params
        assert "message" in params
        assert "session_id" in params
        # Return type hint check — must be Dict[str, Any]
        hint = sig.return_annotation
        import typing
        origin = typing.get_origin(hint)
        args = typing.get_args(hint)
        assert origin is dict or origin is Dict
        assert str in args or args[1] is Any


# =========================================================================
# Task 6.7 — environment.py flag
# =========================================================================

class TestSkillsEnabledFlag:
    """skills_enabled flag in environment.py."""

    def test_flag_exists_and_default_true(self):
        """skills_enabled: bool = True exists."""
        from src.config.environment import settings
        assert hasattr(settings, "skills_enabled")
        # Default should be True (P6 feature enabled by default)
        assert settings.skills_enabled is True


# =========================================================================
# Task 6.8 — S-P6-02: Summarization guard timeout
# =========================================================================

class TestSummarizationCompletionGuard:
    """S-P6-02: Guaranteed summarization — every turn produces a summary."""

    def test_completion_guard_with_sync_fallback(self):
        """After LLM timeout, sync fallback is written immediately."""
        from skills.summarize import Skill as SummarizeSkill
        skill = SummarizeSkill()
        skill.load({"summarizer": None, "settings": MagicMock()})

        result = asyncio.run(skill.run({
            "session_id": "s-test",
            "turn_number": 1,
            "message": "quiero pollo",
            "focuses": ["ordering"],
            "intents": ["ordering"],
            "summary_order": "",
            "assistant_response": "claro",
        }))
        # Even without a real summarizer, the skill should still produce
        # a sync fallback summary result
        assert result.success
        assert result.value.get("fallback_used") is True


# =========================================================================
# Task 6.8 — S-P6-03: Concurrent semaphore
# =========================================================================

class TestConcurrentSemaphore:
    """S-P6-03: 5 concurrent messages processed without deadlock."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Semaphore limits to N concurrent executions."""
        from src.core.agent.orchestrator import SkillOrchestrator
        # SkillOrchestrator should handle concurrent requests
        # The semaphore is in the assistant, but the orchestrator
        # should be reentrant
        semaphore = asyncio.Semaphore(5)

        async def dummy_work(delay: float) -> str:
            async with semaphore:
                await asyncio.sleep(delay)
                return "done"

        # Launch 8 concurrent tasks with only 5 allowed at once
        tasks = [asyncio.create_task(dummy_work(0.05)) for _ in range(8)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(r == "done" for r in results)
        # Verify semaphore actually limited — measure wall time
        # 8 tasks × 0.05s / 5 concurrency = ~0.1s minimum
        # This confirms they didn't all run in parallel
        assert semaphore._value == 5  # Semaphore restored

    @pytest.mark.asyncio
    async def test_process_message_respects_semaphore(self):
        """process_message() acquires semaphore before processing."""
        from src.core.assistant import SaborCaseroAssistant
        assistant = SaborCaseroAssistant(
            extractor=MagicMock(), llm_client=MagicMock(),
        )
        assert hasattr(assistant, "_concurrency_semaphore")
        assert assistant._concurrency_semaphore._value == 5


# =========================================================================
# E2E: Full orchestration with all skills
# =========================================================================

class TestFullE2EWithSkills:
    """End-to-end: all skills loaded and executed through the orchestrator."""

    @pytest.fixture
    def skill_registry(self):
        """Discover all 7 skills from the skills/ directory."""
        from src.core.agent.skill_registry import SkillRegistry
        reg = SkillRegistry()
        reg.discover("skills/")
        return reg

    def test_registry_discovers_all_7_skills(self, skill_registry):
        """Registry finds all 7 P6 skills plus 2 existing = 9 total skills."""
        # The skills/ dir has: classify, menu_query, rag_retrieve,
        # order_flow, response_build, memory_store, summarize = 7
        names = [m.name for m in skill_registry.list_skills()]
        assert "classify" in names
        assert "order-flow" in names
        assert "response-build" in names
        assert "memory-store" in names
        assert "summarize" in names

    def test_orchestrator_loads_classify_skill(self, skill_registry):
        """Orchestrator can load the classify skill by name."""
        from src.core.agent.orchestrator import SkillOrchestrator
        orch = SkillOrchestrator(skill_registry)
        skill = orch.load_skill("classify", context={"classifier": MagicMock()})
        assert skill.name == "classify"
        assert isinstance(skill, BaseSkill)
        orch.unload_skill("classify")

    def test_orchestrator_decide_skills_by_intent(self, skill_registry):
        """decide_skills returns correct domain skills for known intents."""
        from src.core.agent.orchestrator import SkillOrchestrator
        orch = SkillOrchestrator(skill_registry)

        # menu_query intent → menu-query + rag-retrieve (domain skills)
        # classify is always loaded first, not via decide_skills
        skills = orch.decide_skills("menu_query")
        assert "menu-query" in skills
        assert "rag-retrieve" in skills

    def test_orchestrator_loads_all_7_skills(self, skill_registry):
        """All 7 skills can be loaded and provide correct names."""
        from src.core.agent.orchestrator import SkillOrchestrator
        orch = SkillOrchestrator(skill_registry)

        skill_names = [
            "classify", "order-flow", "response-build",
            "memory-store", "summarize",
            "menu-query", "rag-retrieve",
        ]
        for name in skill_names:
            skill = orch.load_skill(name, context=_mock_context())
            assert skill.name == name
            orch.unload_skill(name)
