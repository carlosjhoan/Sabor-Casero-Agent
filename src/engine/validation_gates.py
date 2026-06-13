"""
ValidationGates — Pydantic-based validators for pipeline stage outputs.

Each stage output should pass through the corresponding gate before being
consumed by the next stage. Gates raise ``ValidationGateError`` when
null/empty/invalid values are detected.

Feature-flagged via ``pipeline_validation_enabled`` (see ``environment.py``).
When disabled, gates are no-ops that always return True.
"""
from typing import Any, Optional

from src.engine.exceptions import ValidationGateError
from src.engine.stage_result import StageResult


class ValidationGates:
    """Collection of stage output validators.

    Usage:
        ValidationGates.validate_classification(classification)
        ValidationGates.validate_response(response_text)
    """

    @staticmethod
    def validate_classification(
        value: Any,
        *,
        stage_name: str = "classification",
        enabled: bool = True,
    ) -> bool:
        """Validate classifier output: reject null/empty values.

        Args:
            value: The classifier output (dict or UserQueryClassifier).
            stage_name: Stage name for error context.
            enabled: When False, skip validation (feature flag).

        Returns:
            True if valid.

        Raises:
            ValidationGateError: When value is None or all fields are None.
        """
        if not enabled:
            return True

        violations: list[str] = []

        if value is None:
            violations.append("NULL_FIELDS: classifier output is None")
        elif isinstance(value, dict):
            if value.get("topic_details") is None:
                violations.append("NULL_FIELDS: topic_details is None")
            if value.get("requires_RAG") is None:
                violations.append("NULL_FIELDS: requires_RAG is None")
            if value.get("requires_reconcilier") is None:
                violations.append("NULL_FIELDS: requires_reconcilier is None")
        elif hasattr(value, "topic_details"):
            if value.topic_details is None:
                violations.append("NULL_FIELDS: topic_details is None")

        if violations:
            raise ValidationGateError(
                "Classification validation failed",
                stage_name=stage_name,
                violations=violations,
            )

        return True

    @staticmethod
    async def validate_classification_async(
        value: Any,
        *,
        stage_name: str = "classification",
        enabled: bool = True,
    ) -> bool:
        """Async variant of validate_classification."""
        return ValidationGates.validate_classification(
            value, stage_name=stage_name, enabled=enabled,
        )

    @staticmethod
    def validate_response(
        value: Optional[str],
        *,
        stage_name: str = "response",
        enabled: bool = True,
    ) -> bool:
        """Validate response text: reject empty/whitespace-only strings.

        Args:
            value: The response text to validate.
            stage_name: Stage name for error context.
            enabled: When False, skip validation (feature flag).

        Returns:
            True if valid.

        Raises:
            ValidationGateError: When value is None, empty, or whitespace-only.
        """
        if not enabled:
            return True

        violations: list[str] = []

        if value is None:
            violations.append("EMPTY_RESPONSE: response is None")
        elif not value.strip():
            violations.append(
                f"EMPTY_RESPONSE: response is empty/whitespace (len={len(value)})"
            )

        if violations:
            raise ValidationGateError(
                "Response validation failed",
                stage_name=stage_name,
                violations=violations,
            )

        return True

    @staticmethod
    def validate_stage_result(
        result: StageResult,
        *,
        stage_name: str = "unknown",
        enabled: bool = True,
    ) -> bool:
        """Validate a StageResult: reject success=True with None value.

        Args:
            result: The StageResult to validate.
            stage_name: Stage name for error context.
            enabled: When False, skip validation (feature flag).

        Returns:
            True if valid.

        Raises:
            ValidationGateError: When result is success but value is None.
        """
        if not enabled:
            return True

        violations: list[str] = []

        if result.success and result.value is None:
            violations.append(
                f"NULL_VALUE: StageResult(success=True) has value=None for stage '{stage_name}'"
            )

        if violations:
            raise ValidationGateError(
                f"StageResult validation failed for stage '{stage_name}'",
                stage_name=stage_name,
                violations=violations,
            )

        return True
