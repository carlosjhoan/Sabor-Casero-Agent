import logging
import os

from .retriever_interface import RetrieverInterface
from src.config.environment import settings

logger = logging.getLogger(__name__)


def _read_doc(folder: str, doc_name: str) -> str:
    """Lee un documento del disco. Helper para lazy ingestion."""
    path = os.path.join(folder, doc_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Document not found: %s", path)
        return ""


class RetrieverFactory:

    @staticmethod
    def get_retriever(way: str) -> RetrieverInterface:
        # When USE_OWL=False, build a vector-only CompositeRetriever instead
        # of falling back to plain HybridRetriever. This keeps the full
        # multi-signal pipeline (dense + BM25 + entity → RRF → cross-encoder)
        # working for the rag-retrieve skill, just without OWL signals.
        if way == 'owl' and not settings.use_owl:
            logger.info("USE_OWL=False — building vector-only multi-signal pipeline")
            return RetrieverFactory._build_vector_composite()

        if way == 'llm':
            from src.core.extractor.llm_extractor import InformationLlmExtractor
            return InformationLlmExtractor()

        elif way == 'vector_db':
            from src.core.extractor.vector_extractor import HybridRetriever
            retriever = HybridRetriever()
            # Lazy: solo menu.md eager (rag-retrieve lo necesita).
            # El resto de documentos se cargan bajo demanda via doc-query.
            retriever._ingest_single_document(
                "menu.md",
                _read_doc(settings.documents_path, "menu.md"),
            )
            return retriever

        elif way == 'owl':
            from src.core.extractor.owl_retriever import OwlRetriever
            from src.core.extractor.composite_retriever import CompositeRetriever
            from src.core.extractor.vector_extractor import HybridRetriever
            from src.core.extractor.owl_signal import OwlSignal
            from src.core.extractor.bm25_retriever import BM25Retriever
            from src.core.extractor.rrf_fuser import RRFFuser
            from src.core.extractor.cross_encoder_reranker import CrossEncoderReranker
            from src.core.extractor.ontology_validation_gate import OntologyValidationGate
            from src.infrastructure.owl_client import OwlClient

            # ── 1. OWL infrastructure ──────────────────────────────────
            owl_client = OwlClient(settings.owl_ontology_path)
            owl_signal = OwlSignal(
                owl_client,
                synonyms_path="data/ontology/ontology_synonyms.json",
            )
            owl_retriever = OwlRetriever(owl_client=owl_client)

            # ── 2. Vector retriever (ChromaDB + internal CrossEncoder) ──
            hybrid_retriever = HybridRetriever()
            # Lazy: solo menu.md eager (rag-retrieve lo necesita).
            hybrid_retriever._ingest_single_document(
                "menu.md",
                _read_doc(settings.documents_path, "menu.md"),
            )

            # ── 3. BM25 keyword signal ──────────────────────────────────
            item_names = list(owl_client.get_item_names())
            bm25 = BM25Retriever(documents=item_names)

            # ── 4. Entity retriever (semantic memory signal) ──────────────
            entity = RetrieverFactory._build_entity_retriever()

            # ── 5. RRF fusion ───────────────────────────────────────────
            rrf = RRFFuser()

            # ── 6. Cross-encoder reranker ───────────────────────────────
            cross_encoder = CrossEncoderReranker()

            # ── 7. Ontology validation gate (hallucination firewall) ────
            gate = OntologyValidationGate()

            # ── 8. Composite: primary=OWL router, fallback=vector ───────
            return CompositeRetriever(
                primary=owl_retriever,
                fallback=hybrid_retriever,
                owl_client=owl_client,
                owl_signal=owl_signal,
                bm25_retriever=bm25,
                entity_retriever=entity,
                rrf_fuser=rrf,
                cross_encoder=cross_encoder,
                ontology_gate=gate,
                rag_v2_enabled=True,
            )

        raise ValueError(f"Unknown retriever way: {way}")

    @staticmethod
    def _build_vector_composite() -> RetrieverInterface:
        """Build a CompositeRetriever with only vector signals (no OWL).

        Used when USE_OWL=False. The pipeline includes:
        - Dense (ChromaDB) → HybridRetriever
        - BM25 keyword signal → from menu.md item names
        - Entity signal → from semantic memory (ChromaDB)
        - RRF fusion → RRFFuser(k=60)
        - Cross-encoder reranking → cross-encoder/ms-marco-MiniLM-L-6-v2

        OWL-specific components (owl_signal, ontology_gate) are None,
        so retrieve_v2() skips Phase 1 (OWL exact match) and Phase 3
        (ontology validation) gracefully.
        """
        from src.core.extractor.composite_retriever import CompositeRetriever
        from src.core.extractor.vector_extractor import HybridRetriever
        from src.core.extractor.bm25_retriever import BM25Retriever
        from src.core.extractor.rrf_fuser import RRFFuser
        from src.core.extractor.cross_encoder_reranker import CrossEncoderReranker
        from src.infrastructure.owl_client import OwlClient

        # Vector retriever (ChromaDB) — lazy: solo menu.md eager
        hybrid_retriever = HybridRetriever()
        hybrid_retriever._ingest_single_document(
            "menu.md",
            _read_doc(settings.documents_path, "menu.md"),
        )

        # Extract item names from menu.md directly (no OwlClient needed).
        # Used for BM25 index and candidates.
        try:
            import re, os
            md_path = os.path.join(settings.documents_path, "menu.md")
            if os.path.exists(md_path):
                with open(md_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # Extract item names from menu.md:
                # 1. `### ITEM: Name` format (proteins, principales)
                item_names = re.findall(r'###\s*ITEM:\s*(.+)', content)
                # 2. Bullet items under SECTION blocks (e.g. "- Crema de verdura")
                lines = content.split('\n')
                skip_prefixes = ("source:", "currency:", "language:", "prices", "price", "menu")
                for line in lines:
                    line = line.strip()
                    if line.startswith('- ') and not any(
                        line.lower().startswith(p) for p in skip_prefixes
                    ):
                        name = line[2:].strip().rstrip('.')
                        if name:
                            item_names.append(name)
                # Deduplicate preserving order
                seen = set()
                deduped = []
                for name in item_names:
                    if name not in seen:
                        seen.add(name)
                        deduped.append(name)
                item_names = deduped
            else:
                item_names = []
        except Exception:
            item_names = []
        bm25 = BM25Retriever(documents=item_names) if item_names else None

        # Entity signal (semantic memory)
        entity = RetrieverFactory._build_entity_retriever()

        # RRF fusion + cross-encoder
        rrf = RRFFuser()
        cross_encoder = CrossEncoderReranker()

        retriever = CompositeRetriever(
            primary=None,
            fallback=hybrid_retriever,
            owl_client=None,
            owl_signal=None,
            bm25_retriever=bm25,
            entity_retriever=entity,
            rrf_fuser=rrf,
            cross_encoder=cross_encoder,
            ontology_gate=None,
            rag_v2_enabled=True,
        )
        # Expose item names so the assistant can derive candidates without
        # needing OwlClient. Used by getattr(extractor, "_item_names", [])
        # in assistant.py.
        retriever._item_names = item_names
        return retriever

    @staticmethod
    def _build_entity_retriever():
        """Build EntityRetriever from semantic memory, or None if unavailable."""
        try:
            from src.core.memory.domain.memory_hub import MemoryHub
            from src.core.extractor.entity_retriever import EntityRetriever

            memory_hub = MemoryHub()
            return EntityRetriever(memory_hub=memory_hub)
        except Exception as e:
            logger.warning("EntityRetriever not available: %s", e)
            return None
