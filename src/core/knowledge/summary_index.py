"""
SummaryIndex — índice de summaries document-level para routing de queries.

Capa liviana entre DocumentRegistry (summaries cached) y ChromaDB (chunks).

Flujo:
  1. En startup lee document_cache.json, embeddea cada summary vía all-MiniLM-L6-v2
  2. Query de usuario → embed → cos-sim contra summaries → top-k documentos
  3. Solo esos documentos se chunk+embeddean (lazy en ChromaDB)

Escala a miles de docs porque almacena UN embedding por documento, no por chunk.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class SummaryIndex:
    """Índice de summaries para routing semántico de queries a documentos.

    Args:
        cache_path: Ruta al document_cache.json generado por DocumentRegistry.
        model_name: Modelo de embeddings (default all-MiniLM-L6-v2, mismo que HybridRetriever).
    """

    def __init__(
        self,
        cache_path: str = "data/cache/document_cache.json",
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self._cache_path = Path(cache_path)
        self._embedder = SentenceTransformer(model_name)
        # doc_name → summary text
        self._summaries: Dict[str, str] = {}
        # doc_name → embedding vector
        self._embeddings: Dict[str, np.ndarray] = {}
        self._build()

    # ── Public API ────────────────────────────────────────────────────────

    def query(self, query: str, top_k: int = 2) -> List[str]:
        """Rutea una query al/los documentos más relevantes por semántica.

        Args:
            query: Texto de búsqueda del usuario.
            top_k: Cantidad de documentos a retornar.

        Returns:
            Lista de nombres de archivo ordenados por relevancia.
            Vacía si no hay summaries indexados.
        """
        if not query or not self._embeddings:
            return []

        q_emb = self._embedder.encode(query)
        scores = {
            name: float(np.dot(q_emb, emb) / (np.linalg.norm(q_emb) * np.linalg.norm(emb)))
            for name, emb in self._embeddings.items()
        }
        ranked = sorted(scores, key=scores.get, reverse=True)
        return ranked[:top_k]

    def get_summary(self, doc_name: str) -> str:
        """Retorna el summary de un documento, o cadena vacía si no existe."""
        return self._summaries.get(doc_name, "")

    def list_documents(self) -> List[str]:
        """Retorna todos los documentos indexados."""
        return list(self._embeddings.keys())

    def refresh(self) -> None:
        """Reconstruye el índice desde el cache (útil si hubo cambios)."""
        self._summaries.clear()
        self._embeddings.clear()
        self._build()

    # ── Internos ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        """Carga summaries desde el cache y genera embeddings.

        Esto es O(docs) en startups — para 1000 docs son ~5 segundos,
        comparado con embedder miles de chunks por documento.
        """
        cache = self._load_cache()
        for doc_name, entry in cache.items():
            summary = entry.get("summary", "").strip()
            if not summary:
                logger.debug("No summary for %s, skipping index", doc_name)
                continue
            self._summaries[doc_name] = summary
            self._embeddings[doc_name] = self._embedder.encode(summary)

        logger.info(
            "SummaryIndex built: %d docs indexed, %d skipped (no summary)",
            len(self._embeddings),
            len(cache) - len(self._embeddings),
        )

    def _load_cache(self) -> dict:
        """Carga el archivo JSON de cache de documentos."""
        path = self._cache_path
        if not path.exists():
            logger.warning("Document cache not found at %s", path)
            return {}

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning("Cache file is not a dict, ignoring")
                return {}
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load document cache: %s", exc)
            return {}
