import os
import yaml
from typing import Any
from dotenv import load_dotenv

class AppConfig:
    _instance = None

    def __new__(cls):
        """Ensures only one instance of config exists (Singleton)"""
        if cls._instance is None:
            cls._instance = super(AppConfig, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Internal method to load data once"""
        load_dotenv()
        
        # Core data storage
        self._data = {
            "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY"),
            "deepseek_base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            "openai_api_key": os.getenv("OPENAI_API_KEY"),
            "storage_path": "conversation_states.json",
            "documents_path": "data/documents",
            "chroma_path": "chroma_db_storage", # Added for your persistence
            "retriever_type": os.getenv("RETRIEVER_TYPE", "vector_db"),
            "llm_model": "deepseek-lite",
            "llm_temperature": 0.1, # Lowered for more consistent classification
            "vector_db_path": r"D:\MIR\Control Projects\Udemy\Agents", # Path for vector DB storage
        }

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    @property
    def is_vector_mode(self) -> bool:
        return self._data["retriever_type"] == "vector_db"

# Create the singleton instance at the module level
config = AppConfig()