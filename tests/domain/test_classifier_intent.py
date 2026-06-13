"""
Domain model tests for Detail and UserQueryClassifier from intent.py.

IMPORTANT: Do NOT test the legacy methods (get_conversation_strategy,
get_response_template, should_ask_clarifying_question, get_clarifying_question)
— they reference old fields that no longer exist in the model.
"""
import pytest
from pydantic import ValidationError

from src.core.classifier.intent import (
    Detail,
    UserQueryClassifier,
    QueryTopic,
    QueryType,
)


# =============================================================================
# Detail Tests
# =============================================================================


class TestDetail:
    """Tests for Detail model."""

    def test_detail_creation(self):
        """Create with all required fields."""
        detail = Detail(
            segment="quiero ordenar tacos",
            query_type=QueryType.ORDERING,
            topic=QueryTopic.MENU,
            focus="quiero ordenar tacos al pastor",
        )
        assert detail.segment == "quiero ordenar tacos"
        assert detail.query_type == QueryType.ORDERING
        assert detail.topic == QueryTopic.MENU
        assert detail.focus == "quiero ordenar tacos al pastor"
        assert detail.file_source == ""
        assert detail.info_extracted == ""

    def test_detail_focus_too_short(self):
        """Focus with <3 words, verify ValueError."""
        with pytest.raises(ValidationError, match="al menos 3 palabras"):
            Detail(
                segment="test",
                query_type=QueryType.CONSULTING,
                topic=QueryTopic.MENU,
                focus="dos palabras",
            )

    def test_detail_focus_too_long(self):
        """Focus with >20 words, verify ValueError."""
        long_focus = " ".join(["word"] * 21)
        with pytest.raises(ValidationError, match="no debe exceder 20 palabras"):
            Detail(
                segment="test",
                query_type=QueryType.CONSULTING,
                topic=QueryTopic.MENU,
                focus=long_focus,
            )

    def test_detail_focus_boundary(self):
        """Focus with exactly 3 words and exactly 20 words, verify valid."""
        # Exactly 3 words
        d3 = Detail(
            segment="test",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="one two three",
        )
        assert d3.focus == "one two three"

        # Exactly 20 words
        focus_20 = " ".join(["word"] * 20)
        d20 = Detail(
            segment="test",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus=focus_20,
        )
        assert d20.focus == focus_20

    def test_detail_empty_focus(self):
        """Empty focus string passes (validator returns early for empty)."""
        detail = Detail(
            segment="test",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="",
        )
        assert detail.focus == ""


# =============================================================================
# UserQueryClassifier Tests
# =============================================================================


class TestUserQueryClassifier:
    """Tests for UserQueryClassifier model."""

    def test_classifier_creation(self):
        """Create with topic_details, requires_RAG, requires_reconcilier."""
        detail = Detail(
            segment="quiero ordenar tacos",
            query_type=QueryType.ORDERING,
            topic=QueryTopic.MENU,
            focus="quiero ordenar tacos al pastor",
        )
        classifier = UserQueryClassifier(
            topic_details=[detail],
            requires_RAG=True,
            requires_reconcilier=True,
        )
        assert len(classifier.topic_details) == 1
        assert classifier.requires_RAG is True
        assert classifier.requires_reconcilier is True

    def test_classifier_defaults(self):
        """Create empty, verify empty topic_details, RAG=false, reconcilier=false."""
        classifier = UserQueryClassifier()
        assert classifier.topic_details == []
        assert classifier.requires_RAG is False
        assert classifier.requires_reconcilier is False

    def test_classifier_serialization(self):
        """model_dump() and model_dump_json() work correctly."""
        detail = Detail(
            segment="test",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.GENERAL,
            focus="consulta informacion general",
        )
        classifier = UserQueryClassifier(
            topic_details=[detail],
            requires_RAG=True,
        )
        dumped = classifier.model_dump()
        assert dumped["requires_RAG"] is True
        assert len(dumped["topic_details"]) == 1
        assert dumped["topic_details"][0]["topic"] == "general"

        json_str = classifier.model_dump_json()
        assert '"requires_RAG":true' in json_str
        assert '"general"' in json_str

    def test_classifier_extra_fields_ignored(self):
        """Pass extra field, verify it's ignored (model_config has extra='ignore')."""
        classifier = UserQueryClassifier(
            topic_details=[],
            requires_RAG=False,
            requires_reconcilier=False,
            unknown_field="should be ignored",
        )
        assert classifier.requires_RAG is False
        # Accessing unknown_field should raise AttributeError
        with pytest.raises(AttributeError):
            _ = classifier.unknown_field

    def test_classifier_with_details(self):
        """Create with multiple Detail entries, verify all present."""
        d1 = Detail(
            segment="quiero menu",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="quiero ver el menu",
        )
        d2 = Detail(
            segment="y horario",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.SERVICE_HOURS,
            focus="cual es el horario",
        )
        classifier = UserQueryClassifier(
            topic_details=[d1, d2],
            requires_RAG=True,
        )
        assert len(classifier.topic_details) == 2
        assert classifier.topic_details[0].topic == QueryTopic.MENU
        assert classifier.topic_details[1].topic == QueryTopic.SERVICE_HOURS
