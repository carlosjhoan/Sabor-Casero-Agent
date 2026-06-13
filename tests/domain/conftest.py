"""
Fixtures compartidas para tests del dominio knowledge.
"""
from pathlib import Path
import pytest


@pytest.fixture
def docs_dir() -> Path:
    """Apunta al directorio real de documentos."""
    return Path(__file__).parent.parent.parent / "data" / "documents"
