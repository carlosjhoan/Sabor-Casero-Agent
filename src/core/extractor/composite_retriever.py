"""
CompositeRetriever — delegating retriever with RAG v2 support (Task 5.10).

Maintains backward compatibility with the original ``retrieve()`` method
while adding ``retrieve_v2()`` for the 3-phase RAG pipeline:

Phase 1 — OWL exact match fast-path (<5ms short-circuit)
Phase 2 — Multi-signal RRF (dense + BM25 + entity + OWL partial)
Phase 3 — Ontology Validation Gate (hallucination firewall)

All gated behind ``rag_v2_enabled`` flag.
"""
import logging
from typing import Any, Dict, List, Optional

from src.core.classifier.intent import Detail
from src.core.extractor.retriever_interface import (
    RetrieverInterface,
    RankedResult,
)

logger = logging.getLogger("CompositeRetriever")


class CompositeRetriever(RetrieverInterface):
    """
    Retriever compuesto que rutea por nombre de archivo.

    ``menu.md`` → retriever primario (OwlRetriever).
    Cualquier otro documento → retriever fallback (HybridRetriever).

    Also supports RAG v2 pipeline via :meth:`retrieve_v2` when
    ``rag_v2_enabled=True``.

    Args:
        primary: Retriever for menu documents.
        fallback: Retriever for other documents.
        owl_client: OwlClient instance for SPARQL queries.
        owl_signal: OwlSignal instance for OWL scoring.
        bm25_retriever: Optional BM25Retriever instance.
        entity_retriever: Optional EntityRetriever instance.
        rrf_fuser: Optional RRFFuser instance.
        cross_encoder: Optional CrossEncoderReranker instance.
        ontology_gate: Optional OntologyValidationGate instance.
        rag_v2_enabled: Whether to enable RAG v2 pipeline.
    """

    def __init__(
        self,
        primary: RetrieverInterface,
        fallback: RetrieverInterface,
        owl_client: Optional[Any] = None,
        owl_signal: Optional[Any] = None,
        bm25_retriever: Optional[Any] = None,
        entity_retriever: Optional[Any] = None,
        rrf_fuser: Optional[Any] = None,
        cross_encoder: Optional[Any] = None,
        ontology_gate: Optional[Any] = None,
        rag_v2_enabled: bool = False,
    ):
        self._primary = primary
        self._fallback = fallback

        # RAG v2 components
        self._owl_client = owl_client
        self._owl_signal = owl_signal
        self._bm25 = bm25_retriever
        self._entity = entity_retriever
        self._rrf_fuser = rrf_fuser
        self._cross_encoder = cross_encoder
        self._ontology_gate = ontology_gate
        self._rag_v2_enabled = rag_v2_enabled

    # ── Original retrieval (backward compatible) ─────────────────────────

    async def retrieve(
        self, group_by_doc: Dict[str, List[Detail]]
    ) -> List[Detail]:
        """
        Recupera información delegando según el nombre del documento.

        Args:
            group_by_doc: Diccionario agrupado por nombre de archivo.

        Returns:
            Lista combinada de Details con información recuperada.
        """
        menu_docs: Dict[str, List[Detail]] = {}
        other_docs: Dict[str, List[Detail]] = {}

        for doc_name, details in group_by_doc.items():
            if doc_name == "menu.md":
                menu_docs[doc_name] = details
            else:
                other_docs[doc_name] = details

        results: List[Detail] = []

        if menu_docs:
            try:
                menu_results = await self._primary.retrieve(menu_docs)
                results.extend(menu_results)
            except Exception as e:
                logger.error("Error en retriever primario: %s", e)
                for details in menu_docs.values():
                    for detail in details:
                        detail.info_extracted = (
                            "Ha ocurrido un error al recuperar información "
                            "del menú."
                        )
                    results.extend(details)

        if other_docs:
            try:
                other_results = await self._fallback.retrieve(other_docs)
                results.extend(other_results)
            except Exception as e:
                logger.error("Error en retriever fallback: %s", e)
                for details in other_docs.values():
                    for detail in details:
                        detail.info_extracted = (
                            "Ha ocurrido un error al recuperar información."
                        )
                    results.extend(details)

        return results

    # ── RAG v2 pipeline ─────────────────────────────────────────────────

    async def retrieve_v2(
        self,
        query: str,
        candidates: List[str],
        details: Optional[List[Detail]] = None,
    ) -> List[RankedResult]:
        """
        Multi-signal RAG v2 retrieval.

        **Phase 1** — OWL exact match fast-path:
            If the query matches an ontology item exactly, returns
            immediately (< 5ms) without running other signals.

        **Phase 2** — Multi-signal RRF:
            Runs dense (via primary), BM25, entity, and OWL partial
            signals, then fuses via RRF (k=60). Top 20 results proceed
            to cross-encoder reranking → top 5.

        **Phase 3** — Ontology Validation Gate:
            Validates all candidates against menu.ttl. Invented items
            are rejected/penalized. If ALL rejected, raises
            ``OntologyGateError`` for clarification fallback.

        Args:
            query: The user's search query.
            candidates: Candidate item names to score.
            details: Optional topic details (for dense retrieval).

        Returns:
            List of RankedResult instances sorted by relevance.
        """
        if not self._rag_v2_enabled:
            logger.debug("RAG v2 disabled — returning empty results.")
            return []

        # ── Phase 1: OWL exact match fast-path ──────────────────────
        if self._owl_signal:
            try:
                owl_scores = self._owl_signal.score_candidates(query, candidates)
                exact_items = [
                    item for item, result in owl_scores.items()
                    if result.match_type == "exact"
                ]
                if exact_items:
                    logger.info(
                        "Phase 1 fast-path: %d exact OWL match(es)", len(exact_items)
                    )
                    return [
                        RankedResult(
                            item_name=item,
                            rrf_score=1.0,
                            rerank_score=1.0,
                            signal_count=1,
                            sources=["owl_exact"],
                            gate_outcome="pass",
                            metadata={"match_type": "exact", "evidence": "OWL exact match"},
                        )
                        for item in exact_items
                    ]
            except Exception as e:
                logger.warning("Phase 1 OWL exact match failed: %s", e)

        # ── Phase 2: Multi-signal retrieval → RRF → Cross-encoder ───
        # Collect signals
        dense_scores: List[Dict[str, Any]] = []
        bm25_scores: List[Dict[str, Any]] = []
        entity_scores: List[Dict[str, Any]] = []
        owl_partial_scores: List[Dict[str, Any]] = []

        # Dense signal (via fallback retriever — HybridRetriever with ChromaDB)
        try:
            if self._fallback and hasattr(self._fallback, "retrieve_dense"):
                dense_raw = await self._fallback.retrieve_dense(query, candidates)
                dense_scores = [
                    {"item_name": c, "score": s}
                    for c, s in dense_raw.items()
                ]
        except Exception as e:
            logger.debug("Dense retrieval failed: %s", e)

        # BM25 signal
        try:
            if self._bm25:
                bm25_results = self._bm25.retrieve(query, top_k=20)
                bm25_scores = [
                    {"item_name": r["item_name"], "score": r["score"]}
                    for r in bm25_results
                ]
        except Exception as e:
            logger.debug("BM25 retrieval failed: %s", e)

        # Entity signal
        try:
            if self._entity:
                entity_results = self._entity.retrieve(query, candidates)
                entity_scores = [
                    {"item_name": r["item_name"], "score": r["score"]}
                    for r in entity_results
                ]
        except Exception as e:
            logger.debug("Entity retrieval failed: %s", e)

        # OWL partial signal
        try:
            if self._owl_signal:
                owl_scores = self._owl_signal.score_candidates(query, candidates)
                owl_partial_scores = [
                    {
                        "item_name": item,
                        "score": result.score,
                        "match_type": result.match_type,
                    }
                    for item, result in owl_scores.items()
                    if result.score > 0 and result.match_type != "none"
                ]
        except Exception as e:
            logger.debug("OWL partial scoring failed: %s", e)

        # RRF fusion
        try:
            if self._rrf_fuser:
                fused = self._rrf_fuser.fuse(
                    dense=dense_scores,
                    bm25=bm25_scores,
                    entity=entity_scores,
                    owl=owl_partial_scores,
                    top_k=20,
                )
            else:
                fused = []
        except Exception as e:
            logger.warning("RRF fusion failed: %s", e)
            fused = []

        if not fused:
            return []

        # Cross-encoder reranking (top-20 → top-5)
        try:
            if self._cross_encoder:
                reranked = self._cross_encoder.rerank(query, fused, top_k=5)
            else:
                reranked = fused[:5]
        except Exception as e:
            logger.warning("Cross-encoder reranking failed: %s", e)
            reranked = fused[:5]

        # ── Phase 3: Ontology Validation Gate ────────────────────────
        if self._ontology_gate and self._owl_signal and reranked:
            try:
                from src.core.extractor.ontology_validation_gate import RankedItem

                gate_items = [
                    RankedItem(
                        item_name=r["item_name"],
                        score=r.get("rerank_score", r.get("rrf_score", 0.0)),
                        source="cross_encoder",
                        metadata=r,
                    )
                    for r in reranked
                ]

                validated = self._ontology_gate.validate(gate_items, self._owl_signal)

                # Convert back to RankedResult
                gate_candidate_names = {r.item_name for r in validated}
                validated_dict = {r.item_name: r for r in validated}

                results: List[RankedResult] = []
                for r in reranked:
                    if r["item_name"] in gate_candidate_names:
                        v = validated_dict[r["item_name"]]
                        results.append(RankedResult(
                            item_name=v.item_name,
                            rrf_score=r.get("rrf_score", 0.0),
                            rerank_score=v.score,
                            signal_count=r.get("signal_count", 0),
                            sources=r.get("sources", []),
                            gate_outcome=v.gate_outcome,
                            metadata=v.metadata,
                        ))

                if not results:
                    # All items were rejected — this should raise
                    # OntologyGateError from validate_candidates
                    pass

                return results

            except Exception as e:
                from src.engine.exceptions import OntologyGateError
                if isinstance(e, OntologyGateError):
                    raise
                logger.warning("Ontology validation gate failed: %s", e)

        # No gate — return reranked results as-is
        return [
            RankedResult(
                item_name=r["item_name"],
                rrf_score=r.get("rrf_score", 0.0),
                rerank_score=r.get("rerank_score", None),
                signal_count=r.get("signal_count", 0),
                sources=r.get("sources", []),
                gate_outcome="",
                metadata={},
            )
            for r in reranked
        ]
