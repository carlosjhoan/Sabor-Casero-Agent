"""
OrderFlowTracker — per-session state machine for order field lifecycle.

Tracks each field's state through: PENDING → ASKED → ANSWERED → CONFIRMED.
Provides the "one source of truth" for what question to ask next,
replacing OrderChecklist's stateless recalculation when the feature flag
use_order_flow_tracker is active.

CONCEPTS > CODE:
───────────────────────────────────────────────────────────────
  The root cause of empty assistant responses was conflating
  "what value does the Order have" with "have we asked the user
  about this field yet?".  OrderChecklist recalculates from
  order_state every turn — it has NO memory of what was asked.
  This state machine decouples those two concerns.
───────────────────────────────────────────────────────────────
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

from src.core.order.domain.models import Order, ServiceCategory
from src.core.user.preferences import UserPreferences
from src.utils.utils import print_section

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# FieldState enum  —  lifecycle of a single order field
# ═══════════════════════════════════════════════════════════

class FieldState(str, Enum):
    """Lifecycle states for a single order field.

    PENDING   → hasn't been asked yet
    ASKED     → we've asked, waiting for the user's answer
    ANSWERED  → user responded (value may be in order_state)
    CONFIRMED → user explicitly confirmed this field's value
    """
    PENDING = "pending"
    ASKED = "asked"
    ANSWERED = "answered"
    CONFIRMED = "confirmed"


# ═══════════════════════════════════════════════════════════
# Constants  —  canonical field definitions
# ═══════════════════════════════════════════════════════════
# NOTE: ORDER_FIELDS MUST exactly match OrderChecklist.STEPS
#       order so that the two implementations are drop-in
#       replaceable behind the feature flag.

ORDER_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("protein", "¿Qué plato deseas ordenar?"),
    ("size", "¿Qué tamaño prefieres?"),
    ("principle", "¿Qué principio prefieres?"),
    ("con_todo", "¿Confirma el almuerzo con todo el acompañamiento?"),
    ("customer_name", "¿A nombre de quién?"),
    ("service_type", "¿Delivery o pasas a recoger?"),
    ("address", "¿Cuál es la dirección de entrega?"),
    ("scheduled_time", "¿A qué hora pasas a recoger?"),
    ("payment_method", "¿Cómo vas a pagar?"),
    ("observations", "¿Tienes alguna observación?"),
)

# Fields whose relevance depends on another field's value.
#   key   = dependent field
#   value = (condition_field, required_value)
CONDITIONAL_FIELDS: Dict[str, Tuple[str, str]] = {
    "address": ("service_type", "delivery"),
    "scheduled_time": ("service_type", "pickup"),
}

# Map ActionPlanner / orchestrator action_type values → tracker field names.
ACTION_TO_FIELD: Dict[str, str] = {
    "ask_dish": "protein",
    "ask_size": "size",
    "ask_side": "principle",
    "ask_method": "service_type",
    "ask_address": "address",
    "ask_payment": "payment_method",
    "ask_observation": "observations",
}

# Full question text per field (includes hint text for some fields).
FIELD_QUESTIONS: Dict[str, str] = {
    "protein": "¿Qué plato deseas ordenar?",
    "size": "¿Qué tamaño prefieres? (Corriente o Mini)",
    "principle": "¿Qué principio prefieres?",
    "customer_name": "¿A nombre de quién?",
    "service_type": "¿Delivery o pasas a recoger?",
    "address": "¿Cuál es la dirección de entrega?",
    "scheduled_time": "¿A qué hora pasas a recoger?",
    "payment_method": "¿Cómo vas a pagar?",
    "observations": "¿Tienes alguna observación?",
}

# Fields that need RAG retrieval (subset of ORDER_FIELDS names).
RETRIEVAL_FIELDS: Set[str] = {
    "protein", "size", "principle", "service_type",
    "scheduled_time", "payment_method", "address",
}

# Keyword → field mapping (mirrors OrderChecklist.KEYWORD_TO_CHECKLIST_FIELD).
KEYWORD_TO_FIELD: Dict[str, str] = {
    "protein": "protein", "plato": "protein", "pedir": "protein",
    "size": "size", "tamaño": "size", "corriente": "size", "mini": "size",
    "principle": "principle", "principio": "principle", "frijoles": "principle",
    "delivery": "service_type", "domicilio": "service_type", "recoger": "service_type",
    "dirección": "address", "direccion": "address",
    "hora": "scheduled_time", "horario": "scheduled_time",
    "pagar": "payment_method", "pago": "payment_method", "efectivo": "payment_method",
    "nombre": "customer_name",
    "observación": "observations", "nota": "observations", "observacion": "observations",
}


# ═══════════════════════════════════════════════════════════
# OrderFlowTracker  —  per-session state machine
# ═══════════════════════════════════════════════════════════

class OrderFlowTracker:
    """Per-session state machine for order field lifecycle.

    Tracks each canonical field through PENDING → ASKED → ANSWERED → CONFIRMED.
    Synchronises with both ActionPlanner actions (via consume_actions) and
    the aggregate Order state (via _sync_from_order_state).

    Usage:
        tracker = OrderFlowTracker(user_id="user_123")
        actions = [{"action_type": "ask_dish"}, ...]
        tracker.consume_actions(actions, order)
        field, question, needs_rag = tracker.get_next_field(order)
        if field:
            tracker.mark_asked(field)
            # ... wait for user response ...
            tracker.mark_answered(field)
    """

    def __init__(self, user_id: str, user_prefs: Optional[UserPreferences] = None):
        """Initialise tracker — all fields start PENDING.

        Args:
            user_id:      Stable user identifier (used for preference lookup).
            user_prefs:   Optional UserPreferences instance for merging
                          observed values into the user's preference profile.
        """
        self._user_id = user_id
        self._user_prefs = user_prefs
        self._field_states: Dict[str, FieldState] = {
            name: FieldState.PENDING for name, _ in ORDER_FIELDS
        }
        self._last_asked: Optional[str] = None
        self._observations_into_prefs: Dict[str, int] = {}
        print_section(
            head="🚀 OrderFlowTracker creado",
            msg=f"user_id={user_id} | prefs={'Sí' if user_prefs else 'No'} | campos={len(self._field_states)}",
            symbol="="
        )

    # ── Public API ──────────────────────────────────────────────────────

    def consume_actions(self, actions: List[Dict], order_state: Optional[Order] = None) -> None:
        """Sync from ActionPlanner actions and (optionally) order state.

        For each action:
          1. If it has an ``action_type`` that maps to a field via
             ACTION_TO_FIELD, transition that field from PENDING → ANSWERED.
          2. If it has the ActionPlanner format (``action`` + ``params``),
             examine params for field data and mark matching fields ANSWERED.
          3. Finally, reconcile with the aggregate Order state so that
             values set directly by the ActionPlanner are reflected.

        Args:
            actions:     List of action dicts from orchestrator / ActionPlanner.
            order_state: Current Order aggregate (optional, used for sync).
        """
        changed = []
        for action in actions:
            # ── Format 1: orchestrator action_type (from _build_from_actions) ──
            action_type = action.get("action_type", "")
            if action_type in ACTION_TO_FIELD:
                field = ACTION_TO_FIELD[action_type]
                if field in self._field_states and self._field_states[field] == FieldState.PENDING:
                    self._field_states[field] = FieldState.ANSWERED
                    changed.append(f"{field}(via action_type={action_type})")

            # ── Format 2: ActionPlanner (action + params) ──
            op = action.get("action", "")
            params = action.get("params", {})
            if op == "CREATE_ITEM":
                for pf in ("protein", "size", "principle"):
                    if pf in params and params[pf]:
                        if pf in self._field_states and self._field_states[pf] == FieldState.PENDING:
                            self._field_states[pf] = FieldState.ANSWERED
                            changed.append(f"{pf}(via CREATE_ITEM)")
            elif op == "UPDATE_ORDER":
                for k in params:
                    if k in self._field_states and self._field_states[k] == FieldState.PENDING:
                        self._field_states[k] = FieldState.ANSWERED
                        changed.append(f"{k}(via UPDATE_ORDER)")

        print_section(
            head="📥 consume_actions",
            msg=f"{len(actions)} acciones | campos marcados ANSWERED: {changed if changed else 'ninguno'}",
            symbol="→"
        )

        # Reconcile with the actual Order values.
        if order_state:
            self._sync_from_order_state(order_state)

    def get_next_field(self, order_state: Optional[Order] = None) -> Optional[Tuple[str, str, bool]]:
        """Return the first PENDING field as ``(field_name, question, needs_retrieval)``.

        Iterates ORDER_FIELDS in canonical order:
          - Skips fields that are already past PENDING.
          - Skips **conditional** fields whose pre-condition is not met
            (e.g. ``address`` is skipped when the order is pickup).
          - Returns the first match, or *None* when every applicable field
            has been answered (ready for the confirm step).

        Args:
            order_state: Optional Order aggregate — required to evaluate
                         conditional-field applicability (delivery vs pickup).

        Returns:
            ``(field_name, question_text, needs_rag_retrieval)`` or *None*.
        """
        for field_name, question in ORDER_FIELDS:
            state = self._field_states.get(field_name, FieldState.PENDING)
            if state == FieldState.PENDING:
                if not self._field_is_applicable(field_name, order_state):
                    print_section(
                        head="⏭️ get_next_field — saltando",
                        msg=f"{field_name} no aplica (condicional)",
                        symbol="→"
                    )
                    continue
                print_section(
                    head="🎯 get_next_field",
                    msg=f"Siguiente: {field_name} | retrieval={'Sí' if field_name in RETRIEVAL_FIELDS else 'No'}",
                    symbol="→"
                )
                needs_retrieval = field_name in RETRIEVAL_FIELDS
                return (field_name, question, needs_retrieval)
        print_section(
            head="🎯 get_next_field",
            msg="No hay más campos pendientes → confirmación",
            symbol="→"
        )
        return None

    def resolve_confirmation(self, segments: List[Any],
                             order_state: Optional[Order] = None) -> Optional[str]:
        """Map a user confirmation ("Sí") to the field being confirmed.

        Resolution strategy:
          1. If the user gave an affirmative answer AND ``last_asked`` is set,
             return ``last_asked``.
          2. Fallback: scan segment text for KEYWORD_TO_FIELD matches against
             fields in ASKED state.
          3. If nothing matches, return *None*.

        Args:
            segments:    List of Detail objects, strings, or dicts from
                         the classifier's ordering_segments.
            order_state: Ignored in v1 (reserved for future use).

        Returns:
            Field name that was confirmed, or *None*.
        """
        # ── Extract confirmation text from the first segment ──
        confirmation_text = self._text_from_segments(segments).lower().strip()

        # ── Strategy 1: affirmative + last_asked ──
        affirmative_keywords = {"sí", "si", "yes", "confirmo", "dale", "ok", "okay"}
        is_affirmative = any(
            kw in confirmation_text for kw in affirmative_keywords
        )
        if is_affirmative and self._last_asked and self._last_asked in self._field_states:
            print_section(
                head="✅ resolve_confirmation",
                msg=f"Strategy 1: texto='{confirmation_text}' → last_asked='{self._last_asked}'",
                symbol="✓"
            )
            return self._last_asked

        # ── Strategy 2: keyword inference ──
        for keyword, field in KEYWORD_TO_FIELD.items():
            if keyword in confirmation_text and field in self._field_states:
                if self._field_states[field] == FieldState.ASKED:
                    print_section(
                        head="✅ resolve_confirmation",
                        msg=f"Strategy 2: keyword='{keyword}' → field='{field}'",
                        symbol="✓"
                    )
                    return field

        print_section(
            head="❌ resolve_confirmation",
            msg=f"No se pudo resolver: texto='{confirmation_text}' | last_asked={self._last_asked}",
            symbol="✗"
        )
        return None

    def mark_asked(self, field: str) -> None:
        """Transition *field* from PENDING → ASKED.

        Only the PENDING → ASKED transition updates ``last_asked``.
        Calling this on an already-ASKED field is a no-op (logged as warning).

        Args:
            field: One of the ORDER_FIELDS names.
        """
        if field not in self._field_states:
            logger.warning("mark_asked: unknown field '%s'", field)
            return
        current = self._field_states[field]
        if current == FieldState.PENDING:
            self._field_states[field] = FieldState.ASKED
            self._last_asked = field
            print_section(
                head="⬆️ mark_asked",
                msg=f"{field}: PENDING → ASKED | last_asked={self._last_asked}",
                symbol="▲"
            )
        elif current == FieldState.ASKED:
            logger.warning("Field '%s' already ASKED — keeping state", field)
        else:
            logger.warning("Field '%s' is %s — marking ASKED anyway", field, current.value)
            self._field_states[field] = FieldState.ASKED
            self._last_asked = field
            print_section(
                head="⬆️ mark_asked (forced)",
                msg=f"{field}: {current.value} → ASKED (no era PENDING)",
                symbol="▲"
            )

    def mark_answered(self, field: str) -> None:
        """Transition *field* → ANSWERED (from any prior state).

        Args:
            field: One of the ORDER_FIELDS names.
        """
        if field not in self._field_states:
            logger.warning("mark_answered: unknown field '%s'", field)
            return
        previous = self._field_states[field].value
        self._field_states[field] = FieldState.ANSWERED
        print_section(
            head="✔️ mark_answered",
            msg=f"{field}: {previous} → ANSWERED",
            symbol="▼"
        )

    def mark_confirmed(self, field: str) -> None:
        """Transition *field* → CONFIRMED.

        Raises:
            ValueError: If *field* is in PENDING state — you cannot confirm
                        something that hasn't been asked yet.
        """
        if field not in self._field_states:
            raise ValueError(f"Unknown field: '{field}'")
        current = self._field_states[field]
        if current == FieldState.PENDING:
            raise ValueError(
                f"Cannot confirm field '{field}' in state {current.value}. "
                "Must be ASKED or ANSWERED first."
            )
        if current == FieldState.ASKED:
            logger.warning(
                "Confirming field '%s' from ASKED state "
                "(user confirmed before we processed their answer)", field
            )
        self._field_states[field] = FieldState.CONFIRMED
        print_section(
            head="✅ mark_confirmed",
            msg=f"{field}: {current.value} → CONFIRMED",
            symbol="✓"
        )

    def get_checklist_status(self) -> str:
        """Format current field states for LLM prompt context.

        Lines are ordered by ORDER_FIELDS and use markers:
          [OK] field: ✅ confirmado
          [OK] field: ✅ capturado
          [WAITING] field: ⏳ preguntado
          [WAITING] field: ⏳ pendiente

        If all applicable fields are accounted for, appends a final
        ``[READY]`` line.
        """
        lines: List[str] = []
        for field_name, _ in ORDER_FIELDS:
            state = self._field_states.get(field_name, FieldState.PENDING)
            if state == FieldState.CONFIRMED:
                lines.append(f"[OK] {field_name}: ✅ confirmado")
            elif state == FieldState.ANSWERED:
                lines.append(f"[OK] {field_name}: ✅ capturado")
            elif state == FieldState.ASKED:
                lines.append(f"[WAITING] {field_name}: ⏳ preguntado")
            else:
                lines.append(f"[WAITING] {field_name}: ⏳ pendiente")

        # Check if ready for final confirmation
        all_done = all(
            self._field_states.get(n) in (FieldState.ANSWERED, FieldState.CONFIRMED)
            for n, _ in ORDER_FIELDS
        )
        if all_done:
            lines.append("[READY] Pedido listo para confirmar")

        return "\n".join(lines)

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def last_asked(self) -> Optional[str]:
        """The most recent field marked as ASKED (via mark_asked)."""
        return self._last_asked

    @property
    def field_states(self) -> Dict[str, FieldState]:
        """Read-only snapshot of current field states."""
        return dict(self._field_states)

    @property
    def all_confirmed(self) -> bool:
        """*True* when every field in ORDER_FIELDS is CONFIRMED."""
        return all(
            self._field_states.get(name) == FieldState.CONFIRMED
            for name, _ in ORDER_FIELDS
        )

    # ── Internal helpers ────────────────────────────────────────────────

    def _sync_from_order_state(self, order: Order) -> None:
        """Reconcile tracker state with the aggregate Order.

        Any field that has a value in the Order but is still PENDING in
        the tracker is promoted to ANSWERED.  This catches values set
        directly by ActionPlanner (e.g. via CREATE_ITEM params) that
        were not routed through the ``action_type`` mapping.
        """
        synced = []
        for field_name, _ in ORDER_FIELDS:
            if self._field_is_set(field_name, order):
                if self._field_states.get(field_name) == FieldState.PENDING:
                    self._field_states[field_name] = FieldState.ANSWERED
                    synced.append(field_name)
        if synced:
            print_section(
                head="🔄 _sync_from_order_state",
                msg=f"Campos promovidos a ANSWERED desde Order: {synced}",
                symbol="~"
            )

    @staticmethod
    def _field_is_set(field: str, order: Order) -> bool:
        """Return *True* when the field has a meaningful value in *order*."""
        if not order:
            return False

        if field == "protein":
            return any(item.protein for item in (order.items or []))
        if field == "size":
            return any(item.size for item in (order.items or []))
        if field == "principle":
            return any(item.principle for item in (order.items or []))
        if field == "customer_name":
            return bool(order.customer_id)
        if field == "service_type":
            return order.service is not None
        if field == "address":
            return bool(order.address)
        if field == "scheduled_time":
            if order.service and order.service.category == ServiceCategory.PICKUP:
                return order.service.details.scheduled_time is not None
            return False  # Not a pickup → no scheduled_time to check
        if field == "payment_method":
            return bool(order.payment_method)
        if field == "observations":
            return bool(order.observations)
        return False

    @staticmethod
    def _field_is_applicable(field: str, order_state: Optional[Order] = None) -> bool:
        """Return *True* if *field* is relevant in the current order context.

        Non-conditional fields are always applicable.  Conditional fields
        (address, scheduled_time) require the order to have the matching
        service category.

        When no order_state is given, all fields are assumed applicable
        (the caller should provide one for correct behaviour).
        """
        if field not in CONDITIONAL_FIELDS:
            return True
        if order_state is None or order_state.service is None:
            return True  # Assume applicable without order context

        if field == "address":
            return order_state.service.category == ServiceCategory.DELIVERY
        if field == "scheduled_time":
            return order_state.service.category == ServiceCategory.PICKUP
        return True

    @staticmethod
    def _get_field_value(field: str, order: Order) -> str:
        """Extract the display value of *field* from the Order.

        Mirrors OrderChecklist._get_field_value for compatibility.
        """
        if field == "protein":
            for item in order.items or []:
                if item.protein:
                    return item.protein
        elif field == "size":
            for item in order.items or []:
                if item.size:
                    return item.size
        elif field == "principle":
            for item in order.items or []:
                if item.principle:
                    return item.principle
        elif field == "customer_name":
            return order.customer_id or ""
        elif field == "service_type":
            return order.service.type_name if order.service else ""
        elif field == "address":
            return order.address or ""
        elif field == "scheduled_time":
            if order.service and order.service.category == ServiceCategory.PICKUP:
                dt = order.service.details.scheduled_time
                return dt.strftime("%H:%M") if dt else ""
            return ""
        elif field == "payment_method":
            return order.payment_method or ""
        elif field == "observations":
            if order.observations:
                return ", ".join(order.observations)
            return "(sin observaciones)"
        return ""

    def _merge_observations_into_prefs(self, value: str) -> None:
        """Stage an observation value for later merge into UserPreferences.

        In a future turn (after the order is confirmed), the accumulated
        observations are flushed into the UserPreferences instance via
        a dedicated ``flush_preferences()`` method.
        """
        self._observations_into_prefs[value] = (
            self._observations_into_prefs.get(value, 0) + 1
        )

    @staticmethod
    def _text_from_segments(segments: List[Any]) -> str:
        """Extract concatenated text from heterogeneous segment types.

        Handles Detail objects (the typical classifier output), plain
        strings, and dicts.

        Args:
            segments: List of Detail objects, strings, or dicts.

        Returns:
            Concatenated text from all segments.
        """
        parts: List[str] = []
        for seg in segments:
            if isinstance(seg, str):
                parts.append(seg)
            elif isinstance(seg, dict):
                parts.append(seg.get("segment", seg.get("focus", "")))
            else:
                # Duck-type for Detail-like objects
                text = getattr(seg, "segment", None) or getattr(seg, "focus", "") or str(seg)
                parts.append(text)
        return " ".join(parts)


# ═══════════════════════════════════════════════════════════
# Stateless checklist builder  —  for Planner context
# ═══════════════════════════════════════════════════════════

def build_checklist_from_order(order: Optional[Order]) -> str:
    """Produce checklist status string directly from the Order aggregate.

    Stateless — no OrderFlowTracker instance needed. Reads the Order and
    reports which canonical fields have values and which are pending.
    Designed to be injected into the Planner's system prompt so the LLM
    knows what fields still need to be collected.

    Args:
        order: The Order aggregate, or None if no order exists.

    Returns:
        Formatted checklist string, one field per line:

        [OK] protein: ✅ Tacos
        [PENDING] size: ⏳ pendiente
        [PENDING] principle: ⏳ pendiente
        ...
    """
    if not order:
        return "No hay pedido activo."

    lines: List[str] = []
    for field_name, _ in ORDER_FIELDS:
        state = order.field_states.get(field_name, "pending")
        value = _get_field_value_static(field_name, order)

        if state == "answered":
            lines.append(f"[OK] {field_name}: ✅ {value}")
        else:
            # Conditional fields: mark as N/A if their precondition is not met
            if field_name in CONDITIONAL_FIELDS:
                cond_field, required_value = CONDITIONAL_FIELDS[field_name]
                cond_val = _get_field_value_static(cond_field, order)
                if cond_val and cond_val != required_value:
                    lines.append(f"[N/A] {field_name}: — no aplica")
                    continue
            lines.append(f"[PEND] {field_name}: ⏳ pendiente")

    return "\n".join(lines)


def _get_field_value_static(field: str, order: Order) -> str:
    """Extract the display value of *field* from the Order.

    Mirrors OrderFlowTracker._get_field_value for stateless use.
    """
    if not order:
        return ""
    if field == "protein":
        for item in order.items or []:
            if item.protein:
                return item.protein
    elif field == "size":
        for item in order.items or []:
            if item.size:
                return item.size
    elif field == "principle":
        for item in order.items or []:
            if item.principle:
                return item.principle
    elif field == "customer_name":
        return order.customer_id or ""
    elif field == "service_type":
        return order.service.type_name if order.service else ""
    elif field == "address":
        return order.address or ""
    elif field == "scheduled_time":
        if order.service and order.service.category == ServiceCategory.PICKUP:
            from datetime import datetime
            dt = order.service.details.scheduled_time
            return dt.strftime("%H:%M") if dt else ""
        return ""
    elif field == "payment_method":
        return order.payment_method or ""
    elif field == "con_todo":
        if order.con_todo == "sí":
            return "sí (sopa + acompañamientos incluídos)"
        return order.con_todo or ""
    elif field == "observations":
        if order.observations:
            return ", ".join(order.observations)
        return ""
    return ""
