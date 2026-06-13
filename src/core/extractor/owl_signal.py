"""
Task 5.3 — OwlSignal: OWL/SPARQL signal for RRF fusion.

Provides deterministic scores for menu items against the ontology,
query expansion via ontology_synonyms.json, and candidate validation.

This is a DIFFERENT abstraction than OwlClient — OwlSignal is specifically
for RRF scoring pipelines, while OwlClient does general SPARQL queries.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.engine.exceptions import OntologyGateError
from src.infrastructure.owl_client import OwlClient, NS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class OwlMatchResult:
    """Score and evidence for a single candidate against the ontology.

    Attributes:
        match_type: Type of match found.
        score: Deterministic score (0.0–1.0).
        evidence: Human-readable explanation (SPARQL query or synonym key).
    """
    match_type: str  # "exact" | "partial" | "ingredient" | "cooking_method" | "synonym" | "none"
    score: float
    evidence: str


@dataclass
class ExpandedTerm:
    """A single expanded term from query expansion.

    Attributes:
        term: The original or expanded token.
        match_type: How this term can be used for matching.
        sparql: Optional SPARQL fragment for querying.
    """
    term: str
    match_type: str
    sparql: str = ""


@dataclass
class QueryExpansion:
    """Result of expand_query.

    Attributes:
        original_tokens: Tokens extracted from the raw query.
        expanded_terms: List of expanded terms from synonyms.
    """
    original_tokens: List[str] = field(default_factory=list)
    expanded_terms: List[ExpandedTerm] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of validate_candidates.

    Attributes:
        passed: Items that exist in the ontology.
        flagged: Items that matched via related terms (ingredient/method).
        rejected: Items not found in the ontology.
    """
    passed: List[str] = field(default_factory=list)
    flagged: List[Dict[str, str]] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OwlSignal
# ---------------------------------------------------------------------------


class OwlSignal:
    """OWL/SPARQL signal for RRF fusion and ontology validation.

    Uses rdflib via OwlClient for SPARQL queries and a synonyms JSON
    file for query expansion.

    Args:
        owl_client: An instance of OwlClient with loaded menu ontology.
        synonyms_path: Path to ``ontology_synonyms.json``.
    """

    SCORE_MAP = {
        "exact": 1.0,
        "partial": 0.8,
        "ingredient": 0.7,
        "cooking_method": 0.7,
        "synonym": 0.6,
        "none": 0.0,
    }

    def __init__(
        self,
        owl_client: OwlClient,
        synonyms_path: Optional[str] = None,
    ):
        self._owl = owl_client
        self._synonyms: Dict[str, Dict[str, Any]] = {}
        if synonyms_path:
            resolved = Path(synonyms_path)
            if resolved.is_file():
                try:
                    with open(resolved, "r", encoding="utf-8") as f:
                        self._synonyms = json.load(f)
                    logger.info(
                        "Loaded %d synonym entries from %s",
                        len(self._synonyms), synonyms_path,
                    )
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load synonyms: %s", e)
            else:
                logger.warning("Synonyms file not found: %s", synonyms_path)

    # ------------------------------------------------------------------
    # score_candidates
    # ------------------------------------------------------------------

    def score_candidates(
        self,
        query: str,
        candidates: List[str],
    ) -> Dict[str, OwlMatchResult]:
        """Score each candidate item name against the ontology.

        For each candidate, checks (in order):
        1. Exact itemName match → 1.0
        2. Partial itemName (CONTAINS) → 0.8
        3. Ingredient match (hasMainIngredient) → 0.7
        4. Cooking method match (hasCookingMethod) → 0.7
        5. Synonym expansion match → 0.6
        6. None → 0.0

        Args:
            query: The user's raw query string.
            candidates: List of item names to score.

        Returns:
            Dict mapping item_name → OwlMatchResult.
        """
        results: Dict[str, OwlMatchResult] = {}

        # Get ontology item names for exact/partial matching
        ontology_items = self._owl.get_item_names()

        # Build query expansion for synonym/ingredient/method matching
        expansion = self.expand_query(query)

        for item_name in candidates:
            result = self._score_single(
                item_name=item_name,
                ontology_items=ontology_items,
                expansion=expansion,
                query=query,
            )
            results[item_name] = result

        return results

    def _score_single(
        self,
        item_name: str,
        ontology_items: Set[str],
        expansion: QueryExpansion,
        query: str,
    ) -> OwlMatchResult:
        """Score a single candidate item."""
        query_lower = query.lower().strip()
        item_lower = item_name.lower()

        # 1. Exact match — query equals item name
        if query_lower == item_lower:
            return OwlMatchResult(
                match_type="exact",
                score=self.SCORE_MAP["exact"],
                evidence=f"Exact match: query '{query}' = item '{item_name}'",
            )

        # 2. Partial match (CONTAINS) — query is a substring of item name
        if query_lower and query_lower in item_lower:
            return OwlMatchResult(
                match_type="partial",
                score=self.SCORE_MAP["partial"],
                evidence=f"Partial match (CONTAINS): '{query}' in '{item_name}'",
            )

        # 3. Ingredient match via hasMainIngredient
        for term in expansion.expanded_terms:
            if term.match_type == "ingredient":
                ingredient = term.term
                if self._check_ingredient_match(item_name, ingredient):
                    return OwlMatchResult(
                        match_type="ingredient",
                        score=self.SCORE_MAP["ingredient"],
                        evidence=f"Ingredient '{ingredient}' → {item_name}",
                    )

        # 4. Cooking method match via hasCookingMethod
        for term in expansion.expanded_terms:
            if term.match_type == "cooking_method":
                method = term.term
                if self._check_cooking_method_match(item_name, method):
                    return OwlMatchResult(
                        match_type="cooking_method",
                        score=self.SCORE_MAP["cooking_method"],
                        evidence=f"Cooking method '{method}' → {item_name}",
                    )

        # 5. Synonym expansion match
        for term in expansion.expanded_terms:
            if term.match_type == "synonym":
                if self._check_synonym_match(item_name, term.term):
                    return OwlMatchResult(
                        match_type="synonym",
                        score=self.SCORE_MAP["synonym"],
                        evidence=f"Synonym '{term.term}' → {item_name}",
                    )

        # 6. No match
        return OwlMatchResult(
            match_type="none",
            score=self.SCORE_MAP["none"],
            evidence=f"No ontology match for '{item_name}' with query '{query}'",
        )

    # ------------------------------------------------------------------
    # expand_query
    # ------------------------------------------------------------------

    def expand_query(self, query: str) -> QueryExpansion:
        """Expand a raw user query with ontology terms.

        Steps:
        1. Tokenize the query.
        2. Check ontology_synonyms.json for related terms.
        3. Build ExpandedTerm entries for ingredient, cooking_method,
           and synonym match types.

        Args:
            query: The raw user query string.

        Returns:
            A QueryExpansion with original tokens and expanded terms.
        """
        expansion = QueryExpansion()

        if not query or not query.strip():
            return expansion

        # Tokenize — split on whitespace and punctuation
        import re
        tokens = re.findall(r'\w+', query.lower())
        expansion.original_tokens = tokens

        seen_terms: Set[str] = set()

        for token in tokens:
            if token in seen_terms:
                continue
            seen_terms.add(token)

            # Check synonyms
            if token in self._synonyms:
                entry = self._synonyms[token]

                # Ingredient expansion — ingredients may overlap with tokens
                for ingredient in entry.get("related_ingredients", []):
                    ing_term = ingredient.lower()
                    expansion.expanded_terms.append(ExpandedTerm(
                        term=ingredient,
                        match_type="ingredient",
                        sparql=f"?s :hasMainIngredient :{ingredient.capitalize()}",
                    ))
                    if ing_term not in seen_terms:
                        seen_terms.add(ing_term)

                # Cooking method expansion
                method = entry.get("cooking_method", "")
                if method:
                    expansion.expanded_terms.append(ExpandedTerm(
                        term=method,
                        match_type="cooking_method",
                        sparql=f"?s :hasCookingMethod :{method.replace(' ', '')} .",
                    ))

                # Item expansion (synonym-level)
                for item_ref in entry.get("items", []):
                    expansion.expanded_terms.append(ExpandedTerm(
                        term=item_ref,
                        match_type="synonym",
                    ))

        return expansion

    # ------------------------------------------------------------------
    # validate_candidates
    # ------------------------------------------------------------------

    def validate_candidates(
        self,
        candidates: List[str],
        threshold: float = 0.3,
    ) -> ValidationResult:
        """Validate candidate items against the ontology.

        Each candidate is checked against the ontology item names.
        Items found in the ontology → passed.
        Items NOT found → rejected.

        Args:
            candidates: List of item names to validate.
            threshold: Minimum score threshold (unused in current impl).

        Returns:
            A ValidationResult with passed/flagged/rejected lists.

        Raises:
            OntologyGateError: If ALL candidates are rejected or the
                list is empty.
        """
        result = ValidationResult()
        ontology_items = self._owl.get_item_names()

        if not candidates:
            raise OntologyGateError(
                "Ontology validation gate: empty candidates — all rejected."
            )

        for item in candidates:
            if item in ontology_items:
                result.passed.append(item)
            else:
                result.rejected.append(item)

        if result.passed:
            return result

        # All rejected or empty after validation
        raise OntologyGateError(
            f"Ontology validation gate rejected ALL {len(candidates)} "
            f"candidate(s): {candidates[:5]}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_ingredient_match(
        self, item_name: str, ingredient: str
    ) -> bool:
        """Check if *item_name* has *ingredient* as main ingredient via SPARQL."""
        # Check if the item has a hasMainIngredient relation
        # We check by lowercasing the URI fragment (after #)
        sparql = f"""
        SELECT ?ing WHERE {{
            ?itemNode a :MenuItem ; :itemName ?item .
            FILTER(LCASE(?item) = "{item_name.lower()}")
            ?itemNode :hasMainIngredient ?ing .
            ?ing a :Ingredient .
        }}
        """
        try:
            raw = self._owl.query_deterministic(sparql)
            for row in raw:
                ing_str = str(row.get("ing", "")).lower()
                # Extract fragment after # or check full string
                ing_local = ing_str.split("#")[-1] if "#" in ing_str else ing_str
                if ingredient.lower() in ing_local:
                    return True
            return False
        except Exception as e:
            logger.debug("Ingredient match query failed: %s", e)
            # Fallback: check if item_name contains the ingredient name
            return ingredient.lower() in item_name.lower()

    def _check_cooking_method_match(
        self, item_name: str, method: str
    ) -> bool:
        """Check if *item_name* has *method* as cooking method via SPARQL."""
        sparql = f"""
        SELECT ?method WHERE {{
            ?itemNode a :MenuItem ; :itemName ?item .
            FILTER(LCASE(?item) = "{item_name.lower()}")
            ?itemNode :hasCookingMethod ?method .
        }}
        """
        try:
            raw = self._owl.query_deterministic(sparql)
            for row in raw:
                method_str = str(row.get("method", "")).lower()
                method_local = method_str.split("#")[-1] if "#" in method_str else method_str
                if method.lower() in method_local:
                    return True
            return False
        except Exception as e:
            logger.debug("Cooking method query failed: %s", e)
            return method.lower() in item_name.lower()

    def _check_synonym_match(
        self, item_name: str, synonym_term: str
    ) -> bool:
        """Check if *item_name* matches a synonym reference."""
        return synonym_term.lower() in item_name.lower()
