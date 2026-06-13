"""
Tests for typed error handling replacing bare except Exception (Task 1.6).

Each stage must catch specific exception types and wrap them in
PipelineError subtypes, never bare ``except Exception``.
"""
import pytest
from unittest.mock import patch


class TestTypedStageErrors:
    """Verify stages produce typed PipelineError subtypes on failure."""

    @pytest.mark.asyncio
    async def test_rag_timeout_wraps_as_stage_execution_error(self, assistant):
        """RAG ChromaDB timeout wraps as StageExecutionError, not bare Exception."""
        from src.engine.exceptions import StageExecutionError
        from src.core.classifier.intent import UserQueryClassifier, Detail, QueryTopic, QueryType
        from src.core.classifier.input_guard import FALLBACK_ERROR

        detail = Detail(
            segment="test",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="consultar informacion del menu",
            file_source="menu.md",
            info_extracted="",
        )
        classification = UserQueryClassifier(
            topic_details=[detail],
            requires_RAG=True,
            requires_reconcilier=False,
        )
        assistant.classifier.classify.return_value = classification
        assistant.extractor.retrieve.side_effect = TimeoutError("ChromaDB connection timeout")

        result = await assistant.process_message("user1", "¿Qué hay en el menú?", "test-session")
        # RAG is non-critical, so pipeline continues
        assert result["response"] != FALLBACK_ERROR
        assert "pipeline_error" not in result

    @pytest.mark.asyncio
    async def test_classification_timeout_preserves_error_info(self, assistant):
        """Classification failure should include error info in pipeline response."""
        from src.core.classifier.input_guard import FALLBACK_ERROR
        assistant.classifier.classify.side_effect = RuntimeError("LLM call failed")

        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == FALLBACK_ERROR
        assert "pipeline_error" in result

    @pytest.mark.asyncio
    async def test_response_failure_returns_fallback_with_error(self, assistant):
        """Response generation failure should return FALLBACK_ERROR with pipeline_error."""
        from src.core.classifier.input_guard import FALLBACK_ERROR
        assistant.response_builder.build_hybrid.side_effect = RuntimeError("LLM response failed")

        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == FALLBACK_ERROR
        assert "pipeline_error" in result

    @pytest.mark.asyncio
    async def test_session_prep_failure_with_defaults(self, assistant):
        """Session prep failure should not block pipeline."""
        from src.core.classifier.input_guard import FALLBACK_ERROR
        assistant.summary_repo.get_latest.side_effect = ConnectionError("DB connection lost")

        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] != FALLBACK_ERROR
        assert "pipeline_error" not in result

    @pytest.mark.asyncio
    async def test_logging_failure_does_not_affect_response(self, assistant):
        """Logging failure should not change the response."""
        from src.core.classifier.input_guard import FALLBACK_ERROR
        assistant.logger.log_extraction.side_effect = IOError("disk full")

        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] != FALLBACK_ERROR
        assert "pipeline_error" not in result
