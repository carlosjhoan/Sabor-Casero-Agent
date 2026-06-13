"""
Task 5.4 — OntologyValidationGate: post-cross-encoder hallucination firewall.

Validates each candidate against menu.ttl ontology.

Outcomes:
  - EXACT: itemName matches ontology → confidence preserved
  - RELATED: semantic match (ingredient, method) → tagged "related", confidence boosted
  - REJECTED: not in ontology → penalized ×0.3
  - ALL_REJECTED: raise OntologyGateError → pipeline clarification fallback
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.engine.exceptions import OntologyGateError

logger = logging.getLogger(__name__)


@dataclass
class RankedItem:
    """A single ranked item from the pipeline.

    Attributes:
        item_name: Display name of the menu item.
        score: Current confidence/relevance score.
        source: Which stage produced this item (e.g. "cross_encoder").
        gate_outcome: Result of ontology validation ("" before gate).
        metadata: Arbitrary key-value data.
    """
    item_name: str
    score: float
    source: str = ""
    gate_outcome: str = ""  # "pass" | "related" | "rejected"
    metadata: Dict[str, Any] = field(default_factory=dict)


class OntologyValidationGate:
    """Validates ranked items against the menu ontology.

    The gate is the **hallucination firewall** — any dish name that
    doesn't exist in the ontology is flagged, regardless of what the
    cross-encoder or LLM suggests.

    Args:
        boost_factor: Multiplier for confidence boost on related items.
            Default 1.1 (10% boost).
        penalty_factor: Multiplier for confidence on rejected items.
            Default 0.3.
    """

    def __init__(
        self,
        boost_factor: float = 1.1,
        penalty_factor: float = 0.3,
    ):
        self._boost = boost_factor
        self._penalty = penalty_factor

    def validate(
        self,
        ranked_items: List[RankedItem],
        owl_signal: "OwlSignal",  # type: ignore
    ) -> List[RankedItem]:
        """Validate ranked items against the ontology.

        Args:
            ranked_items: List of RankedItem instances to validate.
            owl_signal: OwlSignal instance with validate_candidates method.

        Returns:
            Ordered list of RankedItem instances — passed items first,
            then flagged/related, then rejected. Rejected items are
            either penalized or removed.

        Raises:
            OntologyGateError: If ALL items are rejected or the
                input list is empty.
        """
        if not ranked_items:
            raise OntologyGateError(
                "Ontology validation gate: empty ranked items — all rejected."
            )

        # Validate all candidate names against the ontology
        candidate_names = [item.item_name for item in ranked_items]
        validation = owl_signal.validate_candidates(candidate_names)

        # Build lookup for validation outcomes
        passed_set = set(validation.passed)
        flagged_names = {f["item"] for f in validation.flagged}
        rejected_set = set(validation.rejected)

        result: List[RankedItem] = []
        all_rejected = True

        for item in ranked_items:
            if item.item_name in passed_set:
                item.gate_outcome = "pass"
                all_rejected = False
                result.append(item)
            elif item.item_name in flagged_names:
                item.gate_outcome = "related"
                item.score = round(item.score * self._boost, 4)
                all_rejected = False
                result.append(item)
            elif item.item_name in rejected_set:
                item.gate_outcome = "rejected"
                item.score = round(item.score * self._penalty, 4)
                result.append(item)
            else:
                # Not in any list — treat as rejected (hallucination)
                item.gate_outcome = "rejected"
                item.score = round(item.score * self._penalty, 4)
                result.append(item)

        # Sort: passed first, then related, then rejected
        outcome_order = {"pass": 0, "related": 1, "rejected": 2}
        result.sort(key=lambda x: (outcome_order.get(x.gate_outcome, 99), -x.score))

        if all_rejected:
            raise OntologyGateError(
                f"Ontology validation gate rejected ALL {len(ranked_items)} "
                f"ranked items."
            )

        return result
