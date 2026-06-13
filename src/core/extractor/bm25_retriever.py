"""
Task 5.5 — BM25Retriever: keyword index via rank_bm25.

Provides a keyword-based retrieval signal using the BM25 algorithm,
built on the ``rank_bm25`` library. Documents are tokenized and indexed
on construction; retrieval returns scored results sorted by relevance.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


class BM25Retriever:
    """BM25 keyword retriever for RAG v2 signal.

    Indexes a list of document strings using BM25Okapi and returns
    scored results for a given query.

    Args:
        documents: List of document strings to index (typically menu
            item names or descriptions).
        tokenizer: Optional custom tokenizer. Defaults to a simple
            regex tokenizer that splits on non-word characters and
            lowercases.
    """

    def __init__(
        self,
        documents: List[str],
        tokenizer=None,
    ):
        self._documents = documents
        self._tokenizer = tokenizer or self._default_tokenize
        self._index: Optional[BM25Okapi] = None
        if documents:
            tokenized_corpus = [self._tokenizer(doc) for doc in documents]
            self._index = BM25Okapi(tokenized_corpus)
            logger.info("BM25 index built with %d documents", len(documents))

    @staticmethod
    def _default_tokenize(text: str) -> List[str]:
        """Default tokenizer: lowercase, split on non-word chars."""
        return re.findall(r'\w+', text.lower())

    def retrieve(self, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
        """Retrieve scored results for *query*.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return (default 20).

        Returns:
            List of dicts with keys:
                - ``item_name``: The original document text.
                - ``score``: BM25 score.
            Empty list if no documents are indexed or no match found.
        """
        if not self._index or not query or not query.strip():
            return []

        tokenized_query = self._tokenizer(query)
        if not tokenized_query:
            return []

        scores = self._index.get_scores(tokenized_query)
        # Pair each doc with its score and sort
        scored = [
            {"item_name": self._documents[i], "score": float(scores[i])}
            for i in range(len(self._documents))
            if scores[i] > 0
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)

        return scored[:top_k]

    def get_item_names(self) -> List[str]:
        """Return all indexed document names."""
        return list(self._documents)
