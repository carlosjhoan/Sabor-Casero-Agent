"""
Resilience tests for the Sabor Casero Assistant pipeline.

Verifies stage isolation, graceful degradation, and retry behavior
of process_message() after the circuit-breakers refactoring.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import Dict, Any

from src.core.assistant import SaborCaseroAssistant
from src.engine.stage_result import StageResult, SessionContext
from src.utils.retry import retry_with_backoff, STAGE_RETRY_CONFIG
from src.core.classifier.input_guard import GuardResult, FALLBACK_ERROR
from src.core.classifier.intent import UserQueryClassifier, Detail, QueryTopic, QueryType


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def mock_classifier():
    """Returns a classifier that returns a valid classification."""
    classifier = AsyncMock()
    detail = Detail(
        segment="test message",
        query_type=QueryType.CONSULTING,
        topic=QueryTopic.MENU,
        focus="informacion sobre el menu",
        file_source="",
        info_extracted="",
    )
    classification = UserQueryClassifier(
        topic_details=[detail],
        requires_RAG=False,
        requires_reconcilier=False,
    )
    classifier.classify.return_value = classification
    classifier.doc_registry = MagicMock()
    classifier.doc_registry.get_all_summaries.return_value = ""
    return classifier


@pytest.fixture
def mock_orchestrator():
    """Returns an orchestrator with mocked components."""
    orch = AsyncMock()
    orch.process_order_intent.return_value = {
        "success": True,
        "thought": "order processed",
        "actions": [],
    }
    # Mock session repository
    session_repo = MagicMock()
    session = MagicMock()
    session.order_id = None
    session.turn_number = 1
    session.session_id = "test-session"
    session.is_active = True
    session_repo.get_session.return_value = session
    session_repo.update_session.return_value = None
    # Mock order repository
    order_repo = MagicMock()
    order_repo.get_order_by_id.return_value = None
    # Wire up action_planner
    orch.action_planner = MagicMock()
    orch.action_planner.session_repository = session_repo
    orch.action_planner.order_repository = order_repo
    return orch


@pytest.fixture
def mock_response_builder():
    """Returns a response builder that returns a valid response."""
    builder = AsyncMock()
    builder.build_hybrid.return_value = "¡Claro! Aquí tienes la información del menú."
    return builder


@pytest.fixture
def mock_summary_repo():
    """Returns a summary repository with no prior summaries."""
    repo = AsyncMock()
    repo.get_latest.return_value = None
    return repo


@pytest.fixture
def mock_logger():
    """Returns a conversation logger."""
    logger = AsyncMock()
    logger.start_interaction = AsyncMock()
    logger.log_extraction = AsyncMock()
    logger.log_processor = AsyncMock()
    logger.log_result = AsyncMock()
    return logger


@pytest.fixture(autouse=True)
def _disable_skills_pipeline(monkeypatch):
    """Disable skill-based orchestration for pipeline tests.

    These tests mock individual stages and expect the legacy hardcoded pipeline.
    """
    from src.config.environment import settings
    monkeypatch.setattr(settings, "skills_enabled", False)


@pytest.fixture
def assistant(mock_classifier, mock_orchestrator, mock_response_builder, mock_summary_repo, mock_logger):
    """Builds a SaborCaseroAssistant with all mocked components."""
    from src.infrastructure.llm_client import LLMClient

    llm_client = AsyncMock(spec=LLMClient)
    llm_client.chat_completion.return_value = "mock response"

    asst = SaborCaseroAssistant(
        extractor=AsyncMock(),
        order_orchestrator=mock_orchestrator,
        logger_conversation=mock_logger,
        llm_client=llm_client,
    )

    # Replace internal components with mocks
    asst.classifier = mock_classifier
    asst.response_builder = mock_response_builder
    asst.summary_repo = mock_summary_repo
    asst.extractor = AsyncMock()

    return asst


# =========================================================================
# StageResult Tests
# =========================================================================

class TestStageResult:
    """Verify StageResult[T] behavior."""

    def test_ok_creates_success_result(self):
        result = StageResult.ok(42)
        assert result.success is True
        assert result.value == 42
        assert result.error_message is None

    def test_fail_creates_failure_result(self):
        result = StageResult.fail("something went wrong")
        assert result.success is False
        assert result.value is None
        assert result.error_message == "something went wrong"

    def test_unwrap_returns_value_on_success(self):
        result = StageResult.ok("hello")
        assert result.unwrap() == "hello"

    def test_unwrap_raises_on_failure(self):
        result = StageResult.fail("error")
        with pytest.raises(ValueError, match="error"):
            result.unwrap()

    def test_or_else_returns_value_on_success(self):
        result = StageResult.ok(42)
        assert result.or_else(0) == 42

    def test_or_else_returns_default_on_failure(self):
        result = StageResult.fail("error")
        assert result.or_else(0) == 0

    def test_map_transforms_value(self):
        result = StageResult.ok(2).map(lambda x: x * 3)
        assert result.value == 6
        assert result.success is True

    def test_map_passes_through_failure(self):
        result = StageResult.fail("error").map(lambda x: x * 3)
        assert result.success is False
        assert result.error_message == "error"

    def test_map_catches_exception(self):
        result = StageResult.ok(2).map(lambda x: 1 / 0)
        assert result.success is False
        assert "division" in result.error_message

    @pytest.mark.asyncio
    async def test_map_async_transforms_value(self):
        async def double(x):
            return x * 2
        result = await StageResult.ok(5).map_async(double)
        assert result.value == 10
        assert result.success is True

    @pytest.mark.asyncio
    async def test_map_async_passes_through_failure(self):
        async def double(x):
            return x * 2
        result = await StageResult.fail("error").map_async(double)
        assert result.success is False


# =========================================================================
# Retry Tests
# =========================================================================

class TestRetryWithBackoff:
    """Verify retry_with_backoff behavior."""

    @pytest.mark.asyncio
    async def test_succeeds_first_attempt(self):
        fn = AsyncMock(return_value=42)
        result = await retry_with_backoff(fn, max_retries=2, base_delay=0.01, stage_name="test")
        assert result == 42
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        fn = AsyncMock(side_effect=[TimeoutError("first fail"), "success"])
        result = await retry_with_backoff(fn, max_retries=2, base_delay=0.01, stage_name="test")
        assert result == "success"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        fn = AsyncMock(side_effect=TimeoutError("always fails"))
        with pytest.raises(TimeoutError):
            await retry_with_backoff(fn, max_retries=1, base_delay=0.01, stage_name="test")
        assert fn.call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_non_retryable_propagates_immediately(self):
        fn = AsyncMock(side_effect=ValueError("bad input"))
        with pytest.raises(ValueError, match="bad input"):
            await retry_with_backoff(fn, max_retries=3, base_delay=0.01, stage_name="test")
        assert fn.call_count == 1  # no retry

    @pytest.mark.asyncio
    async def test_zero_retries_no_retry(self):
        call_count = 0

        async def fail_once():
            nonlocal call_count
            call_count += 1
            raise TimeoutError("fail")

        with pytest.raises(TimeoutError):
            await retry_with_backoff(fail_once, max_retries=0, stage_name="test")
        assert call_count == 1  # initial attempt only, no retry

    @pytest.mark.asyncio
    async def test_connection_error_is_retryable(self):
        fn = AsyncMock(side_effect=[ConnectionError("connection lost"), "ok"])
        result = await retry_with_backoff(fn, max_retries=1, base_delay=0.01, stage_name="test")
        assert result == "ok"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_asyncio_timeout_is_retryable(self):
        fn = AsyncMock(side_effect=[asyncio.TimeoutError("timeout"), "ok"])
        result = await retry_with_backoff(fn, max_retries=1, base_delay=0.01, stage_name="test")
        assert result == "ok"
        assert fn.call_count == 2


# =========================================================================
# Stage Isolation Tests
# =========================================================================

class TestStageIsolation:
    """Verify each stage fails independently without crashing the pipeline."""

    @pytest.mark.asyncio
    async def test_classification_timeout_returns_fallback(self, assistant):
        """CRITICAL: classification failure should return FALLBACK_ERROR."""
        assistant.classifier.classify.side_effect = TimeoutError("classification timeout")
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == FALLBACK_ERROR
        assert result["classification"] is None
        assert result["extracted_info"] == []
        assert "pipeline_error" in result

    @pytest.mark.asyncio
    async def test_rag_failure_continues_without_rag(self, assistant):
        """NON-CRITICAL: RAG failure should not block the pipeline."""
        # Set up classification requiring RAG
        detail = Detail(
            segment="test",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="informacion sobre el menu",
            file_source="menu.md",
            info_extracted="",
        )
        classification = UserQueryClassifier(
            topic_details=[detail],
            requires_RAG=True,
            requires_reconcilier=False,
        )
        assistant.classifier.classify.return_value = classification
        assistant.extractor.retrieve.side_effect = TimeoutError("RAG failed")

        result = await assistant.process_message("user1", "¿Qué hay en el menú?", "test-session")
        assert result["response"] == "¡Claro! Aquí tienes la información del menú."
        assert result["classification"] is not None
        assert "pipeline_error" not in result

    @pytest.mark.asyncio
    async def test_order_orchestrator_failure_continues(self, assistant):
        """NON-CRITICAL: order orchestrator failure should not block the pipeline."""
        detail = Detail(
            segment="test",
            query_type=QueryType.ORDERING,
            topic=QueryTopic.MENU,
            focus="quiero ordenar tacos",
            file_source="",
            info_extracted="",
        )
        classification = UserQueryClassifier(
            topic_details=[detail],
            requires_RAG=False,
            requires_reconcilier=True,
        )
        assistant.classifier.classify.return_value = classification
        assistant.orchestrator.process_order_intent.side_effect = TimeoutError("orchestrator failed")

        result = await assistant.process_message("user1", "Quiero tacos", "test-session")
        assert result["response"] == "¡Claro! Aquí tienes la información del menú."
        assert result["classification"] is not None
        assert "pipeline_error" not in result

    @pytest.mark.asyncio
    async def test_response_generation_failure_returns_fallback(self, assistant):
        """CRITICAL: response generation failure should return FALLBACK_ERROR."""
        assistant.response_builder.build_hybrid.side_effect = TimeoutError("response failed")
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == FALLBACK_ERROR
        # Classification data should be preserved
        assert result["classification"] is not None
        assert len(result["extracted_info"]) > 0
        assert "pipeline_error" in result

    @pytest.mark.asyncio
    async def test_logging_failure_does_not_block(self, assistant):
        """NON-CRITICAL: logging failure should not block the pipeline."""
        assistant.logger.log_extraction.side_effect = TimeoutError("logging failed")
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == "¡Claro! Aquí tienes la información del menú."
        assert "pipeline_error" not in result

    @pytest.mark.asyncio
    async def test_input_guard_fast_rejection(self, assistant):
        """CRITICAL: fast guard rejection should return guard_rejected dict."""
        with patch(
            "src.core.assistant.check_message_quality_fast",
            return_value=GuardResult(
                is_valid=False,
                reason="mensaje_vacio",
                fallback_response="Por favor, escribe un mensaje.",
            ),
        ):
            result = await assistant.process_message("user1", "", "test-session")
            assert result["guard_rejected"] is True
            assert result["reject_reason"] == "mensaje_vacio"
            assert result["response"] == "Por favor, escribe un mensaje."
            assert result["classification"] is None

    @pytest.mark.asyncio
    async def test_input_guard_llm_rejection(self, assistant):
        """CRITICAL: LLM guard rejection should return guard_rejected dict."""
        with patch(
            "src.core.assistant.llm_guard_check",
            return_value=GuardResult(
                is_valid=False,
                reason="fuera_de_contexto",
                fallback_response="Lo siento, no entendí tu mensaje.",
            ),
        ):
            result = await assistant.process_message("user1", "irrelevant", "test-session")
            assert result["guard_rejected"] is True
            assert result["reject_reason"] == "fuera_de_contexto"

    @pytest.mark.asyncio
    async def test_summarization_failure_does_not_block(self, assistant):
        """NON-CRITICAL: summarization failure should not block the pipeline."""
        assistant.summary_repo.get_latest.side_effect = TimeoutError("summary fetch failed")
        result = await assistant.process_message("user1", "Hola", "test-session")
        # Session prep will use default values, pipeline continues
        assert result["response"] == "¡Claro! Aquí tienes la información del menú."
        assert "pipeline_error" not in result


# =========================================================================
# Graceful Degradation Tests
# =========================================================================

class TestGracefulDegradation:
    """Verify graceful degradation produces reasonable output on partial failure."""

    @pytest.mark.asyncio
    async def test_all_non_critical_fail(self, assistant):
        """When all non-critical stages fail, CRITICAL stages still work."""
        # Session prep will fail because summary_repo.get_latest will fail
        assistant.summary_repo.get_latest.side_effect = TimeoutError("no summaries")
        # But classification and response still work
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == "¡Claro! Aquí tienes la información del menú."
        assert result["classification"] is not None
        assert "guard_rejected" not in result

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self, assistant):
        """Happy path: all stages succeed."""
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == "¡Claro! Aquí tienes la información del menú."
        assert result["classification"] is not None
        assert "extracted_info" in result
        assert "guard_rejected" not in result
        assert "pipeline_error" not in result

    @pytest.mark.asyncio
    async def test_return_type_unchanged(self, assistant):
        """The return type of process_message is always Dict[str, Any]."""
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert isinstance(result, dict)
        assert "response" in result
        assert "classification" in result
        assert "extracted_info" in result


# =========================================================================
# Interface Contract Tests
# =========================================================================

class TestInterfaceContract:
    """Verify the process_message interface hasn't changed."""

    @pytest.mark.asyncio
    async def test_signature_accepts_three_args(self, assistant):
        """process_message accepts (user_id, message, session_id)."""
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_signature_accepts_session_id_none(self, assistant):
        """session_id can be None."""
        result = await assistant.process_message("user1", "Hola", None)
        assert isinstance(result, dict)
        assert "response" in result

    @pytest.mark.asyncio
    async def test_success_response_keys(self, assistant):
        """Successful response has the expected keys."""
        result = await assistant.process_message("user1", "Hola", "test-session")
        expected_keys = {"response", "classification", "extracted_info"}
        assert expected_keys.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_error_response_has_pipeline_error_key(self, assistant):
        """Error response includes pipeline_error key."""
        assistant.classifier.classify.side_effect = RuntimeError("unexpected")
        result = await assistant.process_message("user1", "Hola", "test-session")
        assert "pipeline_error" in result
        assert result["response"] == FALLBACK_ERROR

    @pytest.mark.asyncio
    async def test_guard_rejected_response_keys(self, assistant):
        """Guard-rejected response has guard_rejected and reject_reason."""
        with patch(
            "src.core.assistant.check_message_quality_fast",
            return_value=GuardResult(
                is_valid=False,
                reason="mensaje_vacio",
                fallback_response="Escribe algo.",
            ),
        ):
            result = await assistant.process_message("user1", "", "test-session")
            assert result.get("guard_rejected") is True
            assert "reject_reason" in result


# =========================================================================
# STAGE_RETRY_CONFIG Tests
# =========================================================================

class TestStageRetryConfig:
    """Verify the per-stage retry configuration."""

    def test_classification_has_two_retries(self):
        assert STAGE_RETRY_CONFIG["classification"]["max_retries"] == 2

    def test_response_has_two_retries(self):
        assert STAGE_RETRY_CONFIG["response"]["max_retries"] == 2

    def test_input_guard_has_one_retry(self):
        assert STAGE_RETRY_CONFIG["input_guard"]["max_retries"] == 1

    def test_order_processing_has_one_retry(self):
        assert STAGE_RETRY_CONFIG["order_processing"]["max_retries"] == 1

    def test_rag_has_zero_retries(self):
        assert STAGE_RETRY_CONFIG["rag"]["max_retries"] == 0

    def test_logging_has_zero_retries(self):
        assert STAGE_RETRY_CONFIG["logging"]["max_retries"] == 0

    def test_summarization_has_zero_retries(self):
        assert STAGE_RETRY_CONFIG["summarization"]["max_retries"] == 0

    def test_all_stages_have_config(self):
        expected_stages = {
            "input_guard", "classification", "rag",
            "order_processing", "response", "logging", "summarization",
        }
        assert set(STAGE_RETRY_CONFIG.keys()) == expected_stages
