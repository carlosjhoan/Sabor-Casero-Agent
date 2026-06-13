from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from src.core.classifier.intent import Detail


class RankedResult:
    """
    A scored result from the RAG v2 pipeline (Task 5.9).

    Attributes:
        item_name: The candidate item name.
        rrf_score: Fused RRF score across all signals.
        rerank_score: Cross-encoder rerank score (if available).
        signal_count: Number of signals that contributed.
        sources: List of contributing signal names.
        gate_outcome: Ontology validation outcome (if validated).
        metadata: Additional per-item metadata.
    """

    def __init__(
        self,
        item_name: str,
        rrf_score: float = 0.0,
        rerank_score: Optional[float] = None,
        signal_count: int = 0,
        sources: Optional[List[str]] = None,
        gate_outcome: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.item_name = item_name
        self.rrf_score = rrf_score
        self.rerank_score = rerank_score
        self.signal_count = signal_count
        self.sources = sources or []
        self.gate_outcome = gate_outcome
        self.metadata = metadata or {}


class RetrieverInterface(ABC):
    """
    Interface for retriever components
    """

    @abstractmethod
    async def retrieve(self, group_by_doc: Dict[str, List[Detail]]) -> List[Detail]:
        """
        Retrieve relevant documents based on the query

        Args:
            group_by_doc (Dict[str, List[Detail]]): The grouped topic details to retrieve information for

        Returns:
            List[Detail]: List of updated topic details with retrieved information
        """
        pass

    async def retrieve_v2(
        self,
        query: str,
        candidates: List[str],
        details: Optional[List[Detail]] = None,
    ) -> List[RankedResult]:
        """
        Multi-signal retrieval (RAG v2).

        Retrieves using a fused pipeline of dense + BM25 + entity + OWL
        signals, reranked by cross-encoder and validated by ontology gate.

        Args:
            query: The user's search query.
            candidates: Candidate item names to score.
            details: Optional topic details for context.

        Returns:
            List of RankedResult instances sorted by relevance.
        """
        return []