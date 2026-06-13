"""
Application logic tests for ResponseMixer (response_mixer.py).

Tests pure logic — no LLM, no I/O, no async.
"""
import pytest
from src.core.response.response_mixer import ResponseMixer
from src.core.classifier.intent import Detail, QueryType, QueryTopic
from tests.helpers.fixtures import make_sample_order, make_empty_order


class TestResponseMixerCombine:
    """Tests for ResponseMixer.combine()."""

    def test_combine_order_only(self):
        """Only order response → returns order response."""
        mixer = ResponseMixer()
        result = mixer.combine(
            order_response="Tu pedido: 3x Tacos al Pastor",
            info_response="",
            topic_details=[],
            order_state=None,
        )
        assert result == "Tu pedido: 3x Tacos al Pastor"

    def test_combine_info_only(self):
        """Only info response → returns info response."""
        mixer = ResponseMixer()
        result = mixer.combine(
            order_response="",
            info_response="El horario es de 10:00 a 22:00",
            topic_details=[],
            order_state=None,
        )
        assert result == "El horario es de 10:00 a 22:00"

    def test_combine_neither(self):
        """Both empty → returns default message."""
        mixer = ResponseMixer()
        result = mixer.combine(
            order_response="",
            info_response="",
            topic_details=[],
            order_state=None,
        )
        assert result == "¿En qué puedo ayudarte?"

    def test_combine_both_no_mix(self):
        """Both empty strings → default ('¿En qué puedo ayudarte?')."""
        mixer = ResponseMixer()
        result = mixer.combine(
            order_response="",
            info_response="",
            topic_details=[],
            order_state=None,
        )
        assert result == "¿En qué puedo ayudarte?"

    def test_combine_order_first_then_info(self):
        """Active order with consulting → order first."""
        mixer = ResponseMixer()
        order = make_sample_order()
        detail = Detail(
            segment="dame información del menú",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="dame información del menú por favor",
        )
        result = mixer.combine(
            order_response="Tu pedido: 3x Tacos al Pastor",
            info_response="Tenemos Tacos, Burritos, Quesadillas",
            topic_details=[detail],
            order_state=order,
        )
        assert result == "Tu pedido: 3x Tacos al Pastor | Además: Tenemos Tacos, Burritos, Quesadillas"

    def test_combine_info_first_then_order(self):
        """Consulting + ordering (new order flow) → info first."""
        mixer = ResponseMixer()
        detail_consult = Detail(
            segment="dame información del menú",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="dame información del menú por favor",
        )
        detail_order = Detail(
            segment="quiero ordenar tacos",
            query_type=QueryType.ORDERING,
            topic=QueryTopic.MENU,
            focus="quiero ordenar tacos al pastor",
        )
        result = mixer.combine(
            order_response="¿Qué plato deseas ordenar?",
            info_response="Tenemos Tacos, Burritos, Quesadillas",
            topic_details=[detail_consult, detail_order],
            order_state=make_empty_order(),
        )
        assert result == "Tenemos Tacos, Burritos, Quesadillas | ¿Qué plato deseas ordenar?"

    def test_combine_confirmation_active(self):
        """Confirmation on active order → order response."""
        mixer = ResponseMixer()
        order = make_sample_order()
        detail = Detail(
            segment="confirmo mi pedido",
            query_type=QueryType.CONFIRMATION,
            topic=QueryTopic.MENU,
            focus="confirmo mi pedido por favor",
        )
        result = mixer.combine(
            order_response="Tu pedido: 3x Tacos al Pastor. ¿Confirmas?",
            info_response="Información adicional",
            topic_details=[detail],
            order_state=order,
        )
        assert result == "Tu pedido: 3x Tacos al Pastor. ¿Confirmas?"


class TestResponseMixerDetermineOrder:
    """Tests for ResponseMixer.determine_order()."""

    def test_determine_order_order_only(self):
        """Only ordering/confirmation/cancellation → 'order_only'."""
        mixer = ResponseMixer()
        detail = Detail(
            segment="quiero ordenar tacos",
            query_type=QueryType.ORDERING,
            topic=QueryTopic.MENU,
            focus="quiero ordenar tacos al pastor",
        )
        result = mixer.determine_order([detail], order_state=None)
        assert result == "order_only"

    def test_determine_order_info_only(self):
        """Only consulting → 'info_only'."""
        mixer = ResponseMixer()
        detail = Detail(
            segment="cuál es el horario",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.SERVICE_HOURS,
            focus="cuál es el horario de atención",
        )
        result = mixer.determine_order([detail], order_state=None)
        assert result == "info_only"

    def test_determine_order_info_first(self):
        """Consulting + ordering → 'info_first'."""
        mixer = ResponseMixer()
        detail_consult = Detail(
            segment="dame información del menú",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="dame información del menú completo",
        )
        detail_order = Detail(
            segment="quiero ordenar tacos",
            query_type=QueryType.ORDERING,
            topic=QueryTopic.MENU,
            focus="quiero ordenar tacos al pastor",
        )
        result = mixer.determine_order([detail_consult, detail_order], order_state=None)
        assert result == "info_first"

    def test_determine_order_active_with_info(self):
        """Active order with consulting → 'order_first'."""
        mixer = ResponseMixer()
        order = make_sample_order()
        detail = Detail(
            segment="dime el horario",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.SERVICE_HOURS,
            focus="dime el horario de atención",
        )
        result = mixer.determine_order([detail], order_state=order)
        assert result == "order_first"


class TestResponseMixerExtractQueryTypes:
    """Tests for ResponseMixer._extract_query_types()."""

    def test_extract_query_types(self):
        """Returns unique query types from details."""
        mixer = ResponseMixer()
        details = [
            Detail(
                segment="dame información",
                query_type=QueryType.CONSULTING,
                topic=QueryTopic.MENU,
                focus="dame información del menú por favor",
            ),
            Detail(
                segment="quiero ordenar",
                query_type=QueryType.ORDERING,
                topic=QueryTopic.MENU,
                focus="quiero ordenar algo delicioso",
            ),
        ]
        result = mixer._extract_query_types(details)
        assert result == {QueryType.CONSULTING, QueryType.ORDERING}
