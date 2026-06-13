"""
Tests for OrderFlowTracker state machine — T2 of the order-flow-tracker SDD change.

Covers 17 scenarios (scenarios 18-20 were implemented in T1 as part of
UserPreferences tests).  All tests are pure logic: no filesystem, no LLM,
no async.
"""
import pytest
from datetime import datetime

from src.core.order.domain.models import (
    Order,
    OrderItem,
    OrderStatus,
    ServiceCategory,
)
from src.core.order.application.order_flow_tracker import (
    OrderFlowTracker,
    FieldState,
    ORDER_FIELDS,
    ACTION_TO_FIELD,
    FIELD_QUESTIONS,
    RETRIEVAL_FIELDS,
    CONDITIONAL_FIELDS,
    KEYWORD_TO_FIELD,
)
from tests.helpers.fixtures import make_sample_order, make_pickup_order, make_empty_order


# ── Helper factories ──────────────────────────────────────────────────────

def _make_delivery_order_no_address() -> Order:
    """Return an Order with delivery service category but no address set."""
    order = make_empty_order()
    order.set_delivery(address="")
    return order


def _make_pickup_order_no_time() -> Order:
    """Return an Order with pickup service category but no scheduled_time."""
    order = make_empty_order()
    order.set_pickup(scheduled_time=None)
    return order


# ══════════════════════════════════════════════════════════════════════════
# Test 1:  Initial state — all PENDING
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerInitialState:
    """Escenario 1: Estado inicial — todos los campos en PENDING."""

    def test_initial_state_all_pending(self):
        """Crear tracker, verificar que todos los campos estén en PENDING,
        que last_asked sea None y all_confined sea False."""
        tracker = OrderFlowTracker(user_id="test_user")

        for name, _ in ORDER_FIELDS:
            assert tracker.field_states[name] == FieldState.PENDING, (
                f"Campo '{name}' debería estar PENDING"
            )
        assert tracker.last_asked is None
        assert not tracker.all_confirmed


# ══════════════════════════════════════════════════════════════════════════
# Test 2:  consume_actions with CREATE_ITEM sets protein to ANSWERED
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerConsumeActions:
    """Escenarios 2 y 16: consume_actions con acciones del ActionPlanner."""

    def test_consume_actions_create_item_sets_protein(self):
        """Enviar acción CREATE_ITEM con protein → verificar que protein
        pasa a ANSWERED."""
        tracker = OrderFlowTracker(user_id="test_user")
        actions = [{"action": "CREATE_ITEM", "params": {"protein": "Tacos al Pastor"}}]

        tracker.consume_actions(actions)

        assert tracker.field_states["protein"] == FieldState.ANSWERED

    def test_consume_actions_multiple_processes_all(self):
        """Enviar múltiples acciones con action_type y verificar que todas
        se procesan correctamente."""
        tracker = OrderFlowTracker(user_id="test_user")
        actions = [
            {"action_type": "ask_dish"},
            {"action_type": "ask_size"},
            {"action_type": "ask_side"},
        ]

        tracker.consume_actions(actions)

        assert tracker.field_states["protein"] == FieldState.ANSWERED
        assert tracker.field_states["size"] == FieldState.ANSWERED
        assert tracker.field_states["principle"] == FieldState.ANSWERED
        # Otros campos deben seguir PENDING
        assert tracker.field_states["customer_name"] == FieldState.PENDING
        assert tracker.field_states["service_type"] == FieldState.PENDING


# ══════════════════════════════════════════════════════════════════════════
# Test 3:  get_next_field returns size after protein answered
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerGetNextField:
    """Escenario 3: get_next_field retorna el primer campo PENDING."""

    def test_get_next_field_returns_size_after_protein_answered(self):
        """Con protein ANSWERED, get_next_field debe retornar size."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._field_states["protein"] = FieldState.ANSWERED

        result = tracker.get_next_field()

        assert result is not None
        assert result[0] == "size"
        assert isinstance(result[1], str)  # question
        assert isinstance(result[2], bool)  # needs_retrieval
        assert len(result) == 3

    def test_get_next_field_returns_none_when_all_done(self):
        """Con todos los campos ANSWERED, get_next_field retorna None
        (listo para confirmar)."""
        tracker = OrderFlowTracker(user_id="test_user")
        for name, _ in ORDER_FIELDS:
            tracker._field_states[name] = FieldState.ANSWERED

        result = tracker.get_next_field()
        assert result is None

    def test_get_next_field_needs_retrieval_for_rag_fields(self):
        """Los campos en RETRIEVAL_FIELDS deben marcar needs_retrieval=True."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._field_states["protein"] = FieldState.ANSWERED

        result = tracker.get_next_field()
        assert result is not None
        # size está en RETRIEVAL_FIELDS
        assert result[2] is True

        # Para un campo NO retrieval
        tracker._field_states["size"] = FieldState.ANSWERED
        tracker._field_states["principle"] = FieldState.ANSWERED
        tracker._field_states["con_todo"] = FieldState.ANSWERED
        tracker._field_states["customer_name"] = FieldState.ANSWERED
        result = tracker.get_next_field()
        assert result is not None
        # service_type está en RETRIEVAL_FIELDS
        assert result[0] == "service_type"


# ══════════════════════════════════════════════════════════════════════════
# Tests 4-6:  resolve_confirmation
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerResolveConfirmation:
    """Escenarios 4, 5 y 6: resolve_confirmation mapea "Sí" al campo."""

    def test_resolve_confirmation_with_last_asked(self):
        """Con last_asked='service_type' y afirmación, debe retornar
        'service_type'."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._last_asked = "service_type"
        tracker._field_states["service_type"] = FieldState.ASKED

        result = tracker.resolve_confirmation(["sí, confirmo"])
        assert result == "service_type"

    def test_resolve_confirmation_infers_from_keywords(self):
        """Si el segmento contiene una keyword (e.g. 'delivery') y el campo
        está ASKED, debe inferir el campo incluso si last_asked es otro."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._field_states["service_type"] = FieldState.ASKED
        tracker._last_asked = "protein"  # last_asked es otro campo

        result = tracker.resolve_confirmation([{"segment": "delivery"}])
        assert result == "service_type"

    def test_resolve_confirmation_returns_none_when_no_match(self):
        """Sin afirmación, sin keywords y sin last_asked → retorna None."""
        tracker = OrderFlowTracker(user_id="test_user")

        result = tracker.resolve_confirmation(["completamente diferente"])
        assert result is None

    def test_resolve_confirmation_affirmative_keywords_spanish(self):
        """Verificar que variantes de 'sí' en español son detectadas."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._last_asked = "payment_method"
        tracker._field_states["payment_method"] = FieldState.ASKED

        for word in ["sí", "si", "confirmo", "dale", "ok"]:
            result = tracker.resolve_confirmation([word])
            assert result == "payment_method", (
                f"Palabra '{word}' debería coincidir con afirmación"
            )

    def test_resolve_confirmation_ignores_non_asked_fields(self):
        """Si el campo inferido por keyword no está ASKED, no debe retornarlo."""
        tracker = OrderFlowTracker(user_id="test_user")
        # service_type está PENDING, no ASKED
        tracker._field_states["service_type"] = FieldState.PENDING

        result = tracker.resolve_confirmation([{"segment": "delivery"}])
        assert result is None


# ══════════════════════════════════════════════════════════════════════════
# Tests 7-8:  all_confirmed
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerAllConfirmed:
    """Escenarios 7 y 8: all_confirmed property."""

    def test_all_confirmed_true_after_all_confirmed(self):
        """Con todos los campos en CONFIRMED, all_confirmed debe ser True."""
        tracker = OrderFlowTracker(user_id="test_user")
        for name, _ in ORDER_FIELDS:
            tracker._field_states[name] = FieldState.CONFIRMED

        assert tracker.all_confirmed is True

    def test_all_confirmed_false_with_pending_fields(self):
        """Tracker recién creado (todos PENDING) → all_confirmed False."""
        tracker = OrderFlowTracker(user_id="test_user")
        assert tracker.all_confirmed is False

    def test_all_confirmed_false_with_one_pending(self):
        """Un solo campo PENDING → all_confirmed False."""
        tracker = OrderFlowTracker(user_id="test_user")
        for name, _ in ORDER_FIELDS:
            tracker._field_states[name] = FieldState.CONFIRMED
        # Dejar el último campo PENDING
        last = ORDER_FIELDS[-1][0]
        tracker._field_states[last] = FieldState.PENDING

        assert tracker.all_confirmed is False


# ══════════════════════════════════════════════════════════════════════════
# Tests 9-11:  mark_asked / mark_confirmed operations
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerMarkOperations:
    """Escenarios 9, 10 y 11: Transiciones de estado manuales."""

    def test_mark_asked_twice_stays_asked(self):
        """Llamar mark_asked dos veces sobre el mismo campo:
        - Primera llamada: PENDING → ASKED, se actualiza last_asked
        - Segunda llamada: se mantiene ASKED, last_asked no cambia"""
        tracker = OrderFlowTracker(user_id="test_user")

        tracker.mark_asked("protein")
        assert tracker.field_states["protein"] == FieldState.ASKED
        first_asked = tracker.last_asked

        tracker.mark_asked("protein")
        assert tracker.field_states["protein"] == FieldState.ASKED
        assert tracker.last_asked == first_asked, "last_asked no debe cambiar"

    def test_mark_confirmed_on_pending_raises_value_error(self):
        """Hacer mark_confirmed en un campo PENDING debe lanzar ValueError."""
        tracker = OrderFlowTracker(user_id="test_user")

        with pytest.raises(ValueError) as exc:
            tracker.mark_confirmed("protein")
        assert "state pending" in str(exc.value) or "PENDING" in str(exc.value)

    def test_mark_confirmed_on_asked_succeeds(self):
        """Hacer mark_confirmed en un campo ASKED debe funcionar."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker.mark_asked("protein")

        tracker.mark_confirmed("protein")

        assert tracker.field_states["protein"] == FieldState.CONFIRMED

    def test_mark_confirmed_on_answered_succeeds(self):
        """Hacer mark_confirmed en un campo ANSWERED también debe funcionar."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._field_states["protein"] = FieldState.ANSWERED

        tracker.mark_confirmed("protein")

        assert tracker.field_states["protein"] == FieldState.CONFIRMED

    def test_mark_answered_transitions_from_any_state(self):
        """mark_answered debe funcionar desde ASKED o PENDING."""
        tracker = OrderFlowTracker(user_id="test_user")

        # Desde PENDING
        tracker.mark_answered("size")
        assert tracker.field_states["size"] == FieldState.ANSWERED

        # Desde ASKED
        tracker.mark_asked("protein")
        tracker.mark_answered("protein")
        assert tracker.field_states["protein"] == FieldState.ANSWERED

    def test_mark_asked_sets_last_asked(self):
        """mark_asked debe actualizar last_asked SOLO en PENDING→ASKED."""
        tracker = OrderFlowTracker(user_id="test_user")

        tracker.mark_asked("protein")
        assert tracker.last_asked == "protein"

        tracker.mark_asked("size")
        assert tracker.last_asked == "size"  # se actualiza al nuevo campo


# ══════════════════════════════════════════════════════════════════════════
# Tests 12-14:  Conditional field handling
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerConditionalFields:
    """Escenarios 12, 13 y 14: Campos condicionales (address, scheduled_time)."""

    def test_conditional_delivery_address_relevant(self):
        """Con servicio delivery y address PENDING, get_next_field debe
        retornar address como siguiente campo."""
        tracker = OrderFlowTracker(user_id="test_user")
        # Marcar todos los campos anteriores como ANSWERED
        for name, _ in ORDER_FIELDS:
            if name == "address":
                break
            tracker._field_states[name] = FieldState.ANSWERED

        order = _make_delivery_order_no_address()
        result = tracker.get_next_field(order_state=order)

        assert result is not None
        assert result[0] == "address"

    def test_conditional_pickup_scheduled_time_relevant(self):
        """Con servicio pickup y scheduled_time PENDING, get_next_field debe
        retornar scheduled_time (no address)."""
        tracker = OrderFlowTracker(user_id="test_user")
        # Marcar todos los campos anteriores como ANSWERED
        for name, _ in ORDER_FIELDS:
            if name == "address":
                break
            tracker._field_states[name] = FieldState.ANSWERED

        order = _make_pickup_order_no_time()
        result = tracker.get_next_field(order_state=order)

        assert result is not None
        # address debe saltarse para pickup
        assert result[0] != "address"
        assert result[0] == "scheduled_time"

    def test_conditional_address_skipped_for_pickup(self):
        """Pickup: get_next_field NO debe retornar address aunque esté
        PENDING (porque no aplica para recogida)."""
        tracker = OrderFlowTracker(user_id="test_user")
        for name, _ in ORDER_FIELDS:
            if name == "address":
                break
            tracker._field_states[name] = FieldState.ANSWERED

        order = _make_pickup_order_no_time()
        # address sigue PENDING pero no aplica
        assert tracker.field_states["address"] == FieldState.PENDING

        result = tracker.get_next_field(order_state=order)

        # No debe retornar address aunque esté PENDING
        if result is not None:
            assert result[0] != "address"

    def test_conditional_field_applicable_without_order_state(self):
        """Sin order_state, los campos condicionales se asumen aplicables."""
        tracker = OrderFlowTracker(user_id="test_user")
        for name, _ in ORDER_FIELDS:
            if name == "address":
                break
            tracker._field_states[name] = FieldState.ANSWERED

        # Sin order_state → address se considera aplicable
        result = tracker.get_next_field()

        assert result is not None
        assert result[0] == "address"


# ══════════════════════════════════════════════════════════════════════════
# Test 15:  get_checklist_status format
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerChecklistStatus:
    """Escenario 15: Formato del checklist_status."""

    def test_checklist_status_all_pending(self):
        """Tracker nuevo → todos los campos muestran [WAITING] pendiente."""
        tracker = OrderFlowTracker(user_id="test_user")
        status = tracker.get_checklist_status()

        for name, _ in ORDER_FIELDS:
            assert f"[WAITING] {name}: ⏳ pendiente" in status
        # Sin [READY] porque no todos están completos
        assert "[READY]" not in status

    def test_checklist_status_shows_confirmed(self):
        """Campos confirmados muestran [OK]."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._field_states["protein"] = FieldState.CONFIRMED
        tracker._field_states["size"] = FieldState.CONFIRMED

        status = tracker.get_checklist_status()
        assert "[OK] protein: ✅ confirmado" in status
        assert "[OK] size: ✅ confirmado" in status

    def test_checklist_status_shows_answered(self):
        """Campos respondidos (sin confirmar) muestran [OK] capturado."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._field_states["protein"] = FieldState.ANSWERED

        status = tracker.get_checklist_status()
        assert "[OK] protein: ✅ capturado" in status

    def test_checklist_status_shows_asked(self):
        """Campos preguntados muestran [WAITING] preguntado."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._field_states["protein"] = FieldState.ASKED

        status = tracker.get_checklist_status()
        assert "[WAITING] protein: ⏳ preguntado" in status

    def test_checklist_status_ready_when_all_done(self):
        """Todos los campos respondidos/confirmados → muestra [READY]."""
        tracker = OrderFlowTracker(user_id="test_user")
        for name, _ in ORDER_FIELDS:
            tracker._field_states[name] = FieldState.CONFIRMED

        status = tracker.get_checklist_status()
        assert "[READY] Pedido listo para confirmar" in status

    def test_checklist_status_format_lines(self):
        """El status debe ser multilínea, una por campo."""
        tracker = OrderFlowTracker(user_id="test_user")
        status = tracker.get_checklist_status()
        lines = status.strip().split("\n")
        # Debe haber una línea por cada ORDER_FIELDS
        assert len(lines) == len(ORDER_FIELDS)


# ══════════════════════════════════════════════════════════════════════════
# Test 16:  consume_actions with multiple actions processes all
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerConsumeActionsExtended:
    """Escenario 16: consume_actions con múltiples acciones variadas."""

    def test_consume_actions_mixed_formats(self):
        """Procesar acciones en ambos formatos (action_type y ActionPlanner)."""
        tracker = OrderFlowTracker(user_id="test_user")
        actions = [
            {"action": "CREATE_ITEM", "params": {"protein": "Tacos"}},
            {"action_type": "ask_size"},
            {"action_type": "ask_side"},
            {"action_type": "ask_method"},
        ]

        tracker.consume_actions(actions)

        assert tracker.field_states["protein"] == FieldState.ANSWERED
        assert tracker.field_states["size"] == FieldState.ANSWERED
        assert tracker.field_states["principle"] == FieldState.ANSWERED
        assert tracker.field_states["service_type"] == FieldState.ANSWERED
        # customer_name no se tocó → PENDING
        assert tracker.field_states["customer_name"] == FieldState.PENDING

    def test_consume_actions_with_order_state_sync(self):
        """Al pasar order_state, campos con valor en la orden se sincronizan."""
        order = make_sample_order()  # Tiene protein, delivery, address, etc.
        tracker = OrderFlowTracker(user_id="test_user")

        # Sin acciones, solo con order_state
        tracker.consume_actions([], order_state=order)

        # Debe sincronizar campos que tienen valor
        assert tracker.field_states["protein"] == FieldState.ANSWERED
        # size está en None en make_sample_order → PENDING
        assert tracker.field_states["size"] == FieldState.PENDING

    def test_consume_actions_update_order(self):
        """UPDATE_ORDER debe marcar los campos del params como ANSWERED."""
        tracker = OrderFlowTracker(user_id="test_user")
        actions = [
            {"action": "UPDATE_ORDER", "params": {"customer_name": "Juan"}},
        ]

        tracker.consume_actions(actions)

        assert tracker.field_states["customer_name"] == FieldState.ANSWERED


# ══════════════════════════════════════════════════════════════════════════
# Test 17:  resolve_confirmation + mark_confirmed chain
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerConfirmationChain:
    """Escenario 17: resolve_confirmation desencadena mark_confirmed."""

    def test_resolve_confirmation_triggers_mark_confirmed(self):
        """Flujo completo: marcar como ASKED, recibir confirmación,
        resolver el campo y marcarlo como CONFIRMED."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._last_asked = "service_type"
        tracker._field_states["service_type"] = FieldState.ASKED

        # 1. Resolver la confirmación
        field = tracker.resolve_confirmation(["sí, confirmo"])
        assert field == "service_type"

        # 2. Marcar como confirmado
        tracker.mark_confirmed(field)
        assert tracker.field_states["service_type"] == FieldState.CONFIRMED

    def test_resolve_confirmation_with_keyword_then_confirm(self):
        """Flujo con keyword inference: delivery → service_type,
        luego marcar como confirmado."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker._field_states["service_type"] = FieldState.ASKED
        tracker._last_asked = "protein"

        # 1. Inferir por keyword
        field = tracker.resolve_confirmation([{"segment": "delivery"}])
        assert field == "service_type"

        # 2. Confirmar
        tracker.mark_confirmed(field)
        assert tracker.field_states["service_type"] == FieldState.CONFIRMED


# ══════════════════════════════════════════════════════════════════════════
# Additional edge cases
# ══════════════════════════════════════════════════════════════════════════

class TestOrderFlowTrackerEdgeCases:
    """Casos borde adicionales para robustez."""

    def test_mark_confirmed_unknown_field_raises_value_error(self):
        """Campo desconocido → ValueError."""
        tracker = OrderFlowTracker(user_id="test_user")
        with pytest.raises(ValueError, match="Unknown field"):
            tracker.mark_confirmed("nonexistent")

    def test_consume_actions_empty_list_no_errors(self):
        """Lista de acciones vacía no debe causar errores."""
        tracker = OrderFlowTracker(user_id="test_user")
        tracker.consume_actions([])

        for name, _ in ORDER_FIELDS:
            assert tracker.field_states[name] == FieldState.PENDING

    def test_field_is_set_with_empty_order_returns_false(self):
        """_field_is_set debe retornar False para orden vacía."""
        empty = make_empty_order()
        for name, _ in ORDER_FIELDS:
            if name == "observations":
                continue
            assert not OrderFlowTracker._field_is_set(name, empty), (
                f"Campo '{name}' no debería estar set en orden vacía"
            )

    def test_get_field_value_returns_empty_for_missing(self):
        """_get_field_value debe retornar string vacío si no hay valor."""
        empty = make_empty_order()
        for name, _ in ORDER_FIELDS:
            val = OrderFlowTracker._get_field_value(name, empty)
            assert isinstance(val, str)
