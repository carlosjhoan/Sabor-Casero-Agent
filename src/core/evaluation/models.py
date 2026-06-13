"""
Pydantic models for LLM-as-Judge evaluation results.

Phase 1: Observer mode — post-response quality assessment across
multiple criteria, scored via a single structured LLM call.
"""

from pydantic import BaseModel, Field
from enum import Enum


class Criterion(str, Enum):
    """Evaluation criteria assessed by the judge."""

    CORRECTNESS = "correctness"
    """Factual accuracy against available context."""

    BRAND_VOICE = "brand_voice"
    """Tone, warmth, professionalism, Luz Stella style."""

    COMPLETENESS = "completeness"
    """All user questions addressed."""

    ORDER_HANDLING = "order_handling"
    """Correct order operations without hallucination."""

    SAFETY = "safety"
    """No harmful, offensive, or inappropriate content."""


class CriterionScore(BaseModel):
    """Score for a single evaluation criterion."""

    criterion: Criterion
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="0.0 = worst, 1.0 = best",
    )
    reasoning: str = Field(
        default="",
        description="Brief justification for the score",
    )


class EvaluationResult(BaseModel):
    """Complete evaluation of a single assistant response."""

    scores: list[CriterionScore]
    overall_score: float = Field(ge=0.0, le=1.0)
    summary: str = Field(
        default="",
        description="One-line summary of the evaluation",
    )
    passed: bool = Field(
        default=True,
        description="True if overall_score >= threshold",
    )
    trace_id: str = Field(
        default="",
        description="Langfuse trace ID for correlation",
    )
