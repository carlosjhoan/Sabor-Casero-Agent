"""
Task 5.7 — RRFFuser: 4-signal fusion (dense + BM25 + entity + OWL).

Reciprocal Rank Fusion (RRF) combines multiple ranked result lists into
a single scored ranking. The formula:

    RRF(d, q) = Σ( 1 / (k + rank_i(d, q)) )  for each retriever i

Where:
    - k = 60 (standard)
    - rank_i is the position of document d in retriever i's results (1-based)
    - The OWL signal converts its deterministic score (0.0–1.0) to a
      pseudo-rank: rank = max_rank - score * max_rank + 1
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RRFFuser:
    """Reciprocal Rank Fusion for up to 4 signals.

    Args:
        k: RRF constant (default 60). Higher values give more weight
            to lower-ranked documents across all systems.
    """

    def __init__(self, k: int = 60):
        self._k = k

    def fuse(
        self,
        dense: List[Dict[str, Any]],
        bm25: List[Dict[str, Any]],
        entity: List[Dict[str, Any]],
        owl: List[Dict[str, Any]],
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Fuse 4 ranked signal lists into a single ranked result.

        Each input list must contain dicts with at least ``item_name``
        and ``score`` keys. OWL signal dicts should additionally have
        ``match_type``.

        Args:
            dense: Dense vector (ChromaDB) results.
            bm25: BM25 keyword results.
            entity: Entity retriever results.
            owl: OWL/SPARQL signal results.
            top_k: Maximum number of fused results.

        Returns:
            List of dicts sorted by ``rrf_score`` descending, each with:
                - ``item_name``: The item name.
                - ``rrf_score``: The fused RRF score.
                - ``signal_count``: How many signals contributed.
                - ``sources``: Which signals contributed.
                - ``original_scores``: Per-signal original scores.
        """
        # Build signal → ranked item mapping
        signal_names = ["dense", "bm25", "entity", "owl"]
        signal_lists = [dense, bm25, entity, owl]

        # Collect item → {signal → score} mapping
        item_scores: Dict[str, Dict[str, float]] = {}
        item_owl_meta: Dict[str, Dict[str, Any]] = {}

        for sig_name, sig_list in zip(signal_names, signal_lists):
            for rank, entry in enumerate(sig_list):
                item_name = entry.get("item_name", "")
                if not item_name:
                    continue
                if item_name not in item_scores:
                    item_scores[item_name] = {}
                    item_owl_meta[item_name] = {}

                score = entry.get("score", 0.0)
                item_scores[item_name][sig_name] = {
                    "score": score,
                    "rank": rank + 1,  # 1-based rank
                }

                if sig_name == "owl" and "match_type" in entry:
                    item_owl_meta[item_name] = {
                        "match_type": entry["match_type"],
                        "owl_score": score,
                    }

        if not item_scores:
            return []

        # Compute RRF score per item
        fused: List[Dict[str, Any]] = []
        for item_name, signals in item_scores.items():
            rrf_total = 0.0
            contributing_signals: List[str] = []

            for sig_name in signal_names:
                if sig_name in signals:
                    rank = signals[sig_name]["rank"]
                    rrf_total += 1.0 / (self._k + rank)
                    contributing_signals.append(sig_name)

            entry: Dict[str, Any] = {
                "item_name": item_name,
                "rrf_score": round(rrf_total, 6),
                "signal_count": len(contributing_signals),
                "sources": contributing_signals,
                "original_scores": {
                    sig: signals[sig]["score"]
                    for sig in signals
                },
            }

            if item_name in item_owl_meta:
                entry["owl_match_type"] = item_owl_meta[item_name].get("match_type", "")

            fused.append(entry)

        # Sort by RRF score descending
        fused.sort(key=lambda x: x["rrf_score"], reverse=True)
        return fused[:top_k]
