"""
DEPRECATED — use src/config/environment.py (pydantic-settings) instead.

This module is kept for reference only. All configuration is now
handled by ``Settings`` from ``src.config.environment``, which reads
from ``.env`` via ``pydantic-settings``.
"""
import os
from typing import Dict, Any
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def load_config(config_file: str = None) -> Dict[str, Any]:
    """
    Load configuration from file and environment
    """
    config = {
        # Default configuration
        "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY"),
        "deepseek_base_url": os.getenv("DEEPSEEK_BASE_URL", ""),
        "openai_base_url": os.getenv("OPENAI_BASE_URL", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "storage_path": "conversation_states.json",
        "documents_path": "data/documents",
        "brand_voice_path": "data/templates/brand_templates.json",
        "retriever_type": "vector_db",  # 'llm' or 'vector_db'
        "cache_enabled": True,
        "cache_ttl": 300,  # 5 minutes
        "llm_model": "deepseek-lite",
        "llm_temperature": 0.7,
        "max_tokens": 300,
    }
    
    # Load from YAML if provided
    if config_file and os.path.exists(config_file):
        with open(config_file, 'r') as f:
            file_config = yaml.safe_load(f)
            config.update(file_config)
    
    return config