"""
Stripped down — only the stateless checklist builder survives.

The ``OrderFlowTracker`` state machine (FieldState, per-session tracking,
ActionPlanner sync) was removed when ThoughtGenerator and ActionPlanner
were eliminated. The ``build_checklist_from_order()`` function is used by
``OrderOrchestrator.get_order_checklist()`` for the Planner context.
"""
from typing import Dict, Optional, Tuple
import logging

from src.core.order.domain.models import Order, ServiceCategory

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Constants  —  canonical field definitions
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# Stateless checklist builder  —  for Planner context
# ═══════════════════════════════════════════════════════════

def build_checklist_from_order(
    order: Optional[Order],
    field_status: Optional[dict] = None,
) -> str:
    """Produce checklist status string from Order values + conversation state.

    Reads field values from the Order aggregate to determine which fields
    have been answered, and session-level ``field_status`` to know which
    fields were asked but not yet answered (with observation notes).

    Args:
        order: The Order aggregate, or None if no order exists.
        field_status: Session-level dict of field_name → {state, notes[], created_at}.

    Returns:
        Formatted checklist string, one field per line:

        [OK] protein: ✅ Tacos
        [?] principle: ❓ preguntado — el usuario preguntó por precios
        [PEND] size: ⏳ pendiente
        ...
    """
    if not order:
        return "No hay pedido activo."

    field_status = field_status or {}
    lines: list[str] = []
    for field_name, _ in ORDER_FIELDS:
        value = _get_field_value_static(field_name, order)
        fs = field_status.get(field_name)  # {state, notes[], created_at} from session

        if fs and fs.get("state") == "asked":
            notes = fs.get("notes", [])
            note_text = f" — {' | '.join(notes)}" if notes else ""
            lines.append(f"[?] {field_name}: ❓ preguntado{note_text}")
        elif value:
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

    result = "\n".join(lines)

    from src.utils.utils import print_section
    print_section(head="📋 Order Checklist", msg=f"\n{result}", symbol="=")

    return result


def _get_field_value_static(field: str, order: Order) -> str:
    """Extract the display value of *field* from the Order.

    Mirrors the former OrderFlowTracker._get_field_value for stateless use.
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
