"""
Shared test fixtures and configuration.
"""
import pytest
from unittest.mock import AsyncMock
from pathlib import Path
import sys

# Ensure src is on the path
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


@pytest.fixture
def mock_llm_client():
    """Returns an AsyncMock LLM client with canned responses."""
    from src.infrastructure.llm_client import LLMClient
    client = AsyncMock(spec=LLMClient)
    client.chat_completion.return_value = '{"response": "mock response"}'
    client.extract_json.return_value = {"parsed": "data"}
    client.analyze_with_schema.return_value = {"analyzed": "data"}
    return client


@pytest.fixture
def test_settings(monkeypatch):
    """Override global settings with test-safe values using Settings.for_test()."""
    from src.config.environment import settings, Settings
    test_settings = Settings.for_test(
        storage_path="/tmp/test_storage.json",
        llm_provider_classifier="mock",
        retriever_type="mock",
    )
    # Monkeypatch each relevant attribute
    monkeypatch.setattr(settings, "storage_path", test_settings.storage_path)
    monkeypatch.setattr(settings, "llm_provider_classifier", test_settings.llm_provider_classifier)
    monkeypatch.setattr(settings, "retriever_type", test_settings.retriever_type)
    return test_settings


@pytest.fixture
def temp_data_dir(tmp_path):
    """Creates a temporary directory structure mimicking data/."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "orders").mkdir()
    (d / "persistence").mkdir()
    (d / "conversation_logs").mkdir()
    (d / "summaries").mkdir()
    return d


@pytest.fixture
def sample_order_dict():
    """Returns a sample order dictionary for repository tests."""
    return {
        "order_id": "ord-001",
        "status": "pending",
        "items": [
            {
                "name": "Tacos al Pastor",
                "quantity": 3,
                "unit_price": 45.0,
                "notes": ""
            }
        ],
        "total_amount": 135.0,
        "customer_name": "Test Customer",
        "order_type": "pickup"
    }


@pytest.fixture
def sample_session_dict():
    """Returns a sample session dictionary."""
    return {
        "session_id": "ses-001",
        "user_id": "test_user",
        "order_id": None,
        "turn_number": 0,
        "is_active": True
    }
