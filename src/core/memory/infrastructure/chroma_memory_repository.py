"""
Task 4.2 — ChromaMemoryRepository: persistent storage for semantic memory.

Manages the ``memory_semantic`` ChromaDB collection with:
- Idempotent upsert by ``(user_id, entity_type, value)`` composite key.
- Semantic (embedding-based) query.
- Exact lookup by composite key.
- Delete by entity ID.
"""
import hashlib
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any

import chromadb
from sentence_transformers import SentenceTransformer

from src.core.memory.domain.models_memory import Entity

logger = logging.getLogger(__name__)

# Default embedding model — same as HybridRetriever for consistency
_DEFAULT_EMBEDDER: Optional[SentenceTransformer] = None


def _get_default_embedder() -> SentenceTransformer:
    global _DEFAULT_EMBEDDER
    if _DEFAULT_EMBEDDER is None:
        _DEFAULT_EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
    return _DEFAULT_EMBEDDER


class ChromaMemoryRepository:
    """
    ChromaDB-backed repository for :class:`Entity` persistence.

    Uses a single collection (``memory_semantic``) and a deterministic ID
    derived from ``(user_id, entity_type, value)`` for idempotent upserts.

    Args:
        chroma_path: Filesystem path for the ChromaDB persistent store.
            Falls back to ``settings.chroma_path`` if ``None``.
        embedder: A callable ``(list[str]) → list[list[float]]`` that
            produces embeddings. Defaults to ``all-MiniLM-L6-v2``.
    """

    def __init__(
        self,
        chroma_path: Optional[str] = None,
        embedder: Optional[Callable] = None,
    ):
        if chroma_path is None:
            from src.config.environment import settings
            chroma_path = settings.chroma_path

        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.collection = self.chroma_client.get_or_create_collection(
            "memory_semantic"
        )
        self.embedder = embedder or _get_default_embedder()

    # ── Public API ──────────────────────────────────────────────────────

    def _embed(self, texts: List[str]) -> List[float]:
        """
        Produce an embedding for *texts*, handling both SentenceTransformer
        instances and plain callables (e.g. test mocks).
        """
        if hasattr(self.embedder, "encode"):
            # SentenceTransformer or similar
            raw = self.embedder.encode(texts)
            return raw[0].tolist() if hasattr(raw[0], "tolist") else list(raw[0])
        # Plain callable — call it directly
        result = self.embedder(texts)
        if hasattr(result, "tolist"):
            return result[0].tolist()
        if isinstance(result[0], (list, tuple)):
            return list(result[0])
        return list(result)

    def upsert(self, entity: Entity) -> str:
        """
        Persist an entity to the ``memory_semantic`` collection.

        The storage ID is deterministically derived from
        ``(user_id, entity_type, value)`` so that storing the same logical
        fact twice updates the existing record rather than creating a
        duplicate (idempotent upsert).

        Args:
            entity: The :class:`Entity` to store. ``entity_id`` is
                overwritten with the deterministic ID.

        Returns:
            The deterministic storage ID.
        """
        storage_id = self._make_id(entity.user_id, entity.entity_type, entity.value)
        entity.entity_id = storage_id
        entity.updated_at = datetime.now()

        # Compute embedding if not already set
        embedding = entity.embedding
        if not embedding:
            embedding = self._embed([entity.value])

        metadata = {
            "entity_type": entity.entity_type,
            "value": entity.value,
            "user_id": entity.user_id,
            "confidence": str(entity.confidence),
            "created_at": entity.created_at.isoformat(),
            "updated_at": entity.updated_at.isoformat(),
        }

        self.collection.upsert(
            ids=[storage_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[entity.value],
        )
        return storage_id

    def query_by_semantic(
        self,
        text: str,
        top_k: int = 5,
        user_id: Optional[str] = None,
    ) -> List[Entity]:
        """
        Search entities by semantic similarity to *text*.

        Args:
            text: The search query  (natural language).
            top_k: Maximum number of results.
            user_id: If provided, results are filtered to this user.

        Returns:
            A list of :class:`Entity` instances ordered by relevance
            (closest first).
        """
        query_embedding = self._embed([text])

        where: Optional[Dict[str, str]] = None
        if user_id:
            where = {"user_id": user_id}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )

        return self._results_to_entities(results)

    def get_by_entity(
        self,
        user_id: str,
        entity_type: str,
        value: str,
    ) -> Optional[Entity]:
        """
        Look up an entity by its composite key.

        Returns ``None`` if no entity matches.
        """
        storage_id = self._make_id(user_id, entity_type, value)
        results = self.collection.get(ids=[storage_id])
        entities = self._results_to_entities(results)
        return entities[0] if entities else None

    def delete(self, entity_id: str) -> None:
        """Delete an entity by its storage ID."""
        self.collection.delete(ids=[entity_id])

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_id(user_id: str, entity_type: str, value: str) -> str:
        """
        Deterministic storage ID from the triple
        ``(user_id, entity_type, value)``.

        Uses MD5 so the ID is short, stable, and unlikely to collide.
        """
        raw = f"{user_id}|{entity_type}|{value.lower().strip()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _results_to_entities(self, results: Dict[str, Any]) -> List[Entity]:
        """
        Convert raw ChromaDB query/get output into a list of :class:`Entity`
        instances.
        """
        entities: List[Entity] = []
        if not results or not results.get("ids"):
            return entities

        # ChromaDB returns lists of lists — each outer list is one query
        id_list = results["ids"][0] if results["ids"] and isinstance(results["ids"][0], list) else results["ids"]
        meta_list = results["metadatas"][0] if results["metadatas"] and isinstance(results["metadatas"][0], list) else results["metadatas"]
        doc_list = results["documents"][0] if results["documents"] and isinstance(results["documents"][0], list) else results["documents"]

        if not id_list:
            return entities

        for i in range(len(id_list)):
            meta: Dict[str, str] = meta_list[i] if i < len(meta_list) else {}

            try:
                created_at = datetime.fromisoformat(meta.get("created_at", datetime.now().isoformat()))
                updated_at = datetime.fromisoformat(meta.get("updated_at", datetime.now().isoformat()))
            except (ValueError, TypeError):
                created_at = datetime.now()
                updated_at = datetime.now()

            entity = Entity(
                entity_id=id_list[i],
                entity_type=meta.get("entity_type", ""),
                value=meta.get("value", doc_list[i] if i < len(doc_list) else ""),
                user_id=meta.get("user_id", ""),
                confidence=float(meta.get("confidence", 1.0)),
                created_at=created_at,
                updated_at=updated_at,
            )
            entities.append(entity)

        return entities
