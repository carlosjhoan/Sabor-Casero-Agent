"""
MockLLMClient for testing pipeline components.
"""
from unittest.mock import AsyncMock
from src.infrastructure.llm_client import LLMClient


class MockLLMClient(AsyncMock):
    """
    Pre-configured AsyncMock for LLMClient.
    
    Usage:
        client = MockLLMClient()
        client.chat_completion.return_value = '{"thought": "..."}'
    """
    
    def __init__(self, **kwargs):
        super().__init__(spec=LLMClient, **kwargs)
        self.chat_completion.return_value = '{"response": "mock response"}'
        self.extract_json.return_value = {"parsed": "data"}
        self.analyze_with_schema.return_value = {"analyzed": "data"}
