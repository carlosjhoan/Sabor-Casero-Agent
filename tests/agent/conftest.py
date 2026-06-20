"""
Shared fixtures for agent tests.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.classifier.intent import UserQueryClassifier, Detail, QueryTopic, QueryType
from src.core.classifier.input_guard import GuardResult


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
    session_repo = MagicMock()
    session = MagicMock()
    session.order_id = None
    session.turn_number = 1
    session.session_id = "test-session"
    session.is_active = True
    session_repo.get_session.return_value = session
    session_repo.update_session.return_value = None
    order_repo = MagicMock()
    order_repo.get_order_by_id.return_value = None
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


@pytest.fixture
def assistant(mock_classifier, mock_orchestrator, mock_response_builder, mock_summary_repo, mock_logger):
    """Builds a SaborCaseroAssistant with all mocked components."""
    from src.infrastructure.llm_client import LLMClient
    from src.core.assistant import SaborCaseroAssistant

    llm_client = AsyncMock(spec=LLMClient)
    llm_client.chat_completion.return_value = "mock response"

    asst = SaborCaseroAssistant(
        extractor=AsyncMock(),
        order_orchestrator=mock_orchestrator,
        logger_conversation=mock_logger,
        llm_client=llm_client,
    )

    asst.classifier = mock_classifier
    asst.response_builder = mock_response_builder
    asst.summary_repo = mock_summary_repo
    asst.extractor = AsyncMock()

    return asst
