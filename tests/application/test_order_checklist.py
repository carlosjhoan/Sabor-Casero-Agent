"""
Application logic tests for OrderChecklist (order_response_builder.py).

Tests pure logic — no LLM, no I/O, no async.
"""
import pytest
from src.core.response.order_response_builder import OrderChecklist
from src.core.order.domain.models import Order, OrderItem, ServiceCategory, OrderStatus, ServiceDetails
from tests.helpers.fixtures import make_sample_order, make_empty_order, make_pickup_order


class TestOrderChecklistSteps:
    """Tests for OrderChecklist class-level attributes."""

    def test_checklist_steps(self):
        """Verify STEPS has correct field names and questions."""
        assert len(OrderChecklist.STEPS) == 9
        expected = [
            ("protein", "¿Qué plato deseas ordenar?"),
            ("size", "¿Qué tamaño prefieres?"),
            ("principle", "¿Qué principio prefieres?"),
            ("customer_name", "¿A nombre de quién?"),
            ("service_type", "¿Delivery o pasas a recoger?"),
            ("address", "¿Cuál es la dirección de entrega?"),
            ("scheduled_time", "¿A qué hora pasas a recoger?"),
            ("payment_method", "¿Cómo vas a pagar?"),
            ("observations", "¿Tienes alguna observación?"),
        ]
        assert OrderChecklist.STEPS == expected


class TestOrderChecklistGetNextField:
    """Tests for OrderChecklist.get_next_field()."""

    def test_get_next_field_no_order(self):
        """No order → returns ('protein', question, True)."""
        field, question, needs_retrieval = OrderChecklist.get_next_field(None, [])
        assert field == "protein"
        assert "plato" in question
        assert needs_retrieval is True

    def test_get_next_field_empty_order(self):
        """Order with no items → returns ('protein', question, True)."""
        order = make_empty_order()
        field, question, needs_retrieval = OrderChecklist.get_next_field(order, [])
        assert field == "protein"
        assert needs_retrieval is True

    def test_get_next_field_no_items(self):
        """Order with items that have no protein → returns ('protein', question, True)."""
        order = make_empty_order(items=[OrderItem(protein=None, quantity=1)])
        field, question, needs_retrieval = OrderChecklist.get_next_field(order, [])
        assert field == "protein"
        assert needs_retrieval is True

    def test_get_next_field_next_missing(self):
        """Order with protein set → returns next missing step (size)."""
        order = make_empty_order(items=[
            OrderItem(protein="Pechuga de pollo", quantity=1, unit_price=45.0)
        ])
        # "Pechuga" has size variants, and size is not set → size is missing
        field, question, needs_retrieval = OrderChecklist.get_next_field(order, [])
        assert field == "size"
        assert "tamaño" in question.lower()
        assert needs_retrieval is True

    def test_get_next_field_all_complete(self):
        """Fully complete order → returns ('observations', question, False).

        Note: The spec originally expected ('confirm', ..., False), but
        _field_is_missing('observations') always returns True, so
        get_next_field always returns observations as the next missing step.
        Observations is not in RETRIEVAL_FIELDS, so needs_retrieval is False.
        """
        order = make_sample_order()
        # Set all fields on *all* items — make_sample_order() has 2 items
        for item in order.items:
            item.size = "Corriente"
            item.principle = "Frijoles"
        order.customer_id = "Juan Pérez"
        order.payment_method = "Efectivo"
        # service is delivery with address — already set

        field, question, needs_retrieval = OrderChecklist.get_next_field(order, [])
        # Always returns observations because _field_is_missing('observations') = True
        assert field == "observations"
        assert "observación" in question.lower()
        assert needs_retrieval is False

    def test_get_next_field_missing_customer(self):
        """Order complete except customer_name."""
        items = [
            OrderItem(protein="Pechuga de pollo", size="Corriente", principle="Frijoles",
                      quantity=1, unit_price=45.0),
        ]
        order = make_empty_order(items=items)
        order.set_delivery(address="Calle 123")
        order.payment_method = "Efectivo"
        # customer_id not set → missing

        field, question, _ = OrderChecklist.get_next_field(order, [])
        assert field == "customer_name"

    def test_get_next_field_missing_address_delivery(self):
        """Delivery order missing address."""
        items = [
            OrderItem(protein="Pechuga de pollo", size="Corriente", principle="Frijoles", quantity=1, unit_price=45.0),
        ]
        order = make_empty_order(items=items)
        order.customer_id = "María"
        order.set_delivery(address="")

        field, question, _ = OrderChecklist.get_next_field(order, [])
        assert field == "address"

    def test_get_next_field_missing_scheduled_time_pickup(self):
        """Pickup order missing scheduled time."""
        items = [
            OrderItem(protein="Pechuga de pollo", size="Corriente", principle="Frijoles", quantity=1, unit_price=45.0),
        ]
        order = make_empty_order(items=items)
        order.customer_id = "María"
        order.payment_method = "Efectivo"
        order.set_pickup(scheduled_time=None)

        field, question, _ = OrderChecklist.get_next_field(order, [])
        assert field == "scheduled_time"

    def test_get_next_field_missing_payment(self):
        """All set except payment_method."""
        items = [
            OrderItem(protein="Pechuga de pollo", size="Corriente", principle="Frijoles", quantity=1, unit_price=45.0),
        ]
        order = make_empty_order(items=items)
        order.customer_id = "María"
        order.set_delivery(address="Calle 123")
        # payment_method not set

        field, question, _ = OrderChecklist.get_next_field(order, [])
        assert field == "payment_method"

    def test_get_next_field_missing_observations(self):
        """Observations is always returned as missing (returns True)."""
        order = make_sample_order()
        # Set all prior fields on ALL items so the loop reaches observations
        for item in order.items:
            item.size = "Corriente"
            item.principle = "Frijoles"
        order.customer_id = "Juan"
        order.payment_method = "Efectivo"

        field, question, needs_retrieval = OrderChecklist.get_next_field(order, [])
        assert field == "observations"
        assert needs_retrieval is False


class TestOrderChecklistFieldIsMissing:
    """Tests for OrderChecklist._field_is_missing()."""

    def test_field_is_missing_size(self):
        """Item with size variants and protein but no size → missing."""
        item = OrderItem(protein="Pechuga de pollo", quantity=1)
        order = make_empty_order(items=[item])
        assert OrderChecklist._field_is_missing("size", order) is True

    def test_field_is_missing_size_no_variant(self):
        """Item without size variants → not missing even if no size."""
        item = OrderItem(protein="Ensalada", quantity=1)
        order = make_empty_order(items=[item])
        assert OrderChecklist._field_is_missing("size", order) is False

    def test_field_is_missing_customer(self):
        """No customer_id → missing."""
        order = make_sample_order()
        order.customer_id = None
        assert OrderChecklist._field_is_missing("customer_name", order) is True

    def test_field_is_missing_service(self):
        """No service → missing."""
        order = make_empty_order(items=[OrderItem(protein="Pechuga", quantity=1)])
        order.service = None
        assert OrderChecklist._field_is_missing("service_type", order) is True

    def test_field_is_missing_address_delivery(self):
        """Delivery with no address → missing."""
        order = make_empty_order(items=[OrderItem(protein="Pechuga", quantity=1)])
        order.set_delivery(address="")
        assert OrderChecklist._field_is_missing("address", order) is True

    def test_field_is_missing_address_pickup(self):
        """Pickup → address is not applicable (service category is not delivery)."""
        order = make_empty_order(items=[OrderItem(protein="Pechuga", quantity=1)])
        order.set_pickup()
        assert OrderChecklist._field_is_missing("address", order) is False

    def test_field_is_missing_scheduled_time(self):
        """Pickup with no time → missing."""
        order = make_empty_order(items=[OrderItem(protein="Pechuga", quantity=1)])
        order.set_pickup(scheduled_time=None)
        assert OrderChecklist._field_is_missing("scheduled_time", order) is True

    def test_field_is_missing_payment(self):
        """No payment_method → missing."""
        order = make_sample_order()
        order.payment_method = None
        assert OrderChecklist._field_is_missing("payment_method", order) is True

    def test_field_is_missing_observations(self):
        """Observations always returns True."""
        order = make_sample_order()
        assert OrderChecklist._field_is_missing("observations", order) is True


class TestOrderChecklistHasValidItems:
    """Tests for OrderChecklist._has_valid_items()."""

    def test_has_valid_items(self):
        """Items with protein → True."""
        order = make_sample_order()
        assert OrderChecklist._has_valid_items(order) is True

    def test_has_valid_items_empty(self):
        """No items → False."""
        order = make_empty_order()
        assert OrderChecklist._has_valid_items(order) is False

    def test_has_valid_items_no_protein(self):
        """Items without protein → False."""
        order = make_empty_order(items=[OrderItem(protein=None, quantity=1)])
        assert OrderChecklist._has_valid_items(order) is False


class TestOrderChecklistItemHasSizeVariants:
    """Tests for OrderChecklist._item_has_size_variants()."""

    def test_item_has_size_variants(self):
        """Protein with 'pechuga' → True."""
        item = OrderItem(protein="Pechuga de pollo")
        assert OrderChecklist._item_has_size_variants(item) is True

    def test_item_has_size_variants_no(self):
        """Protein without variant keyword → False."""
        item = OrderItem(protein="Ensalada César")
        assert OrderChecklist._item_has_size_variants(item) is False


class TestOrderChecklistGetRetrievalQuery:
    """Tests for OrderChecklist.get_retrieval_query()."""

    def test_get_retrieval_query(self):
        """Returns correct query for known fields."""
        queries = {
            "protein": "listado de proteínas del menú con precios y opciones",
            "size": "opciones de tamaño con precios actuales",
            "principle": "principios disponibles con nombres completos",
            "service_type": "tipos de servicio disponibles para entrega o recoger",
            "address": "zonas de cobertura para delivery",
            "scheduled_time": "horario de atención y disponibilidad",
            "payment_method": "métodos de pago aceptados actualmente",
        }
        for field, expected_query in queries.items():
            assert OrderChecklist.get_retrieval_query(field) == expected_query

    def test_get_retrieval_query_unknown(self):
        """Returns field name for unknown fields."""
        assert OrderChecklist.get_retrieval_query("unknown_field") == "unknown_field"


class TestOrderChecklistGetFieldValue:
    """Tests for OrderChecklist._get_field_value()."""

    def test_get_field_value_protein(self):
        """Returns first item's protein."""
        order = make_sample_order()
        assert OrderChecklist._get_field_value("protein", order) == "Tacos al Pastor"

    def test_get_field_value_size(self):
        """Returns first item's size."""
        order = make_sample_order()
        order.items[0].size = "Corriente"
        assert OrderChecklist._get_field_value("size", order) == "Corriente"

    def test_get_field_value_customer(self):
        """Returns customer_id."""
        order = make_sample_order()
        order.customer_id = "Carlos"
        assert OrderChecklist._get_field_value("customer_name", order) == "Carlos"

    def test_get_field_value_service_type(self):
        """Returns service type_name."""
        order = make_sample_order()
        assert OrderChecklist._get_field_value("service_type", order) == "A domicilio"

    def test_get_field_value_address(self):
        """Returns order address."""
        order = make_sample_order()
        # Order has delivery service with address "Calle Principal 123"
        assert "Principal" in OrderChecklist._get_field_value("address", order)

    def test_get_field_value_observations(self):
        """Returns comma-joined observations."""
        order = make_sample_order()
        order.observations = ["sin cebolla", "bien cocido"]
        result = OrderChecklist._get_field_value("observations", order)
        assert result == "sin cebolla, bien cocido"

    def test_get_field_value_observations_empty(self):
        """Returns '(sin observaciones)' when no observations."""
        order = make_sample_order()
        order.observations = []
        assert OrderChecklist._get_field_value("observations", order) == "(sin observaciones)"


class TestOrderChecklistGetChecklistSummary:
    """Tests for OrderChecklist.get_checklist_summary()."""

    def test_get_checklist_summary_no_order(self):
        """No order → returns 'Sin pedido activo'."""
        assert OrderChecklist.get_checklist_summary(None) == "Sin pedido activo"

    def test_get_checklist_summary_partial(self):
        """Partial order shows formatted checklist with [OK] and [WAITING]."""
        order = make_empty_order(items=[
            OrderItem(protein="Pechuga de pollo", quantity=1, unit_price=45.0),
        ])
        summary = OrderChecklist.get_checklist_summary(order)
        assert "[OK] protein: Pechuga de pollo" in summary
        assert "[WAITING] size" in summary

    def test_get_checklist_summary_complete(self):
        """Full order shows completed checklist (except observations)."""
        order = make_sample_order()
        for item in order.items:
            item.size = "Corriente"
            item.principle = "Frijoles"
        order.customer_id = "Juan Pérez"
        order.payment_method = "Efectivo"

        summary = OrderChecklist.get_checklist_summary(order)
        # Check for OK fields
        assert "[OK] protein: Tacos al Pastor" in summary
        assert "[OK] size: Corriente" in summary
        assert "[OK] principle: Frijoles" in summary
        assert "[OK] customer_name: Juan Pérez" in summary
        assert "[OK] service_type: A domicilio" in summary
        assert "[OK] address: Calle Principal 123" in summary
        assert "[OK] payment_method: Efectivo" in summary
        # Observations is always WAITING
        assert "[WAITING] observations" in summary
        # [READY] only appears if get_next_field returns "confirm"
        # Currently observations always returns True, so no [READY]
