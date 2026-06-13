"""
Domain model tests for Order, OrderItem, ServiceDetails, DeliveryDetails, PickupDetails.
"""
import pytest
from datetime import datetime
from pydantic import ValidationError

from src.core.order.domain.models import (
    Order,
    OrderItem,
    OrderStatus,
    ServiceDetails,
    ServiceCategory,
    DeliveryDetails,
    PickupDetails,
)
from tests.helpers.fixtures import make_sample_order, make_empty_order, make_pickup_order


# =============================================================================
# OrderItem Tests
# =============================================================================


class TestOrderItem:
    """Tests for OrderItem model."""

    def test_create_order_item(self):
        """Create with required fields, verify defaults."""
        item = OrderItem(protein="Tacos al Pastor")
        assert item.id.startswith("item_")
        assert item.quantity == 1
        assert item.unit_price == 0.0
        assert item.protein == "Tacos al Pastor"
        assert item.principle is None
        assert item.size is None
        assert item.requirements == []

    def test_order_item_subtotal(self):
        """Verify subtotal = quantity * unit_price."""
        item = OrderItem(protein="Tacos", quantity=3, unit_price=45.0)
        assert item.subtotal == 135.0

        item2 = OrderItem(protein="Guacamole", quantity=2, unit_price=30.0)
        assert item2.subtotal == 60.0

    def test_order_item_to_summary(self):
        """Verify summary format for item with protein, principle, requirements."""
        item = OrderItem(
            protein="Tacos",
            principle="frijoles",
            quantity=2,
            unit_price=45.0,
            requirements=["sin cebolla", "bien cocido"],
        )
        summary = item.to_summary()
        assert "2x Tacos" in summary
        assert "frijoles" in summary
        assert "sin cebolla" in summary
        assert "bien cocido" in summary

    def test_order_item_to_dict(self):
        """Verify dict output includes all fields."""
        item = OrderItem(
            protein="Tacos",
            quantity=3,
            unit_price=45.0,
            size="mini",
            requirements=["sin cebolla"],
        )
        d = item.to_dict()
        assert d["item_id"] == item.id
        assert d["quantity"] == 3
        assert d["protein"] == "Tacos"
        assert d["size"] == "mini"
        assert d["unit_price"] == 45.0
        assert d["requirements"] == ["sin cebolla"]
        assert d["subtotal"] == 135.0

    def test_order_item_quantity_validation(self):
        """Verify ge(1) constraint (quantity must be >= 1)."""
        with pytest.raises(ValidationError):
            OrderItem(quantity=0)


# =============================================================================
# Order Tests
# =============================================================================


class TestOrder:
    """Tests for Order model."""

    def test_create_order(self):
        """Create with default values, verify DRAFT status, empty items, auto-generated id."""
        order = Order()
        assert order.status == OrderStatus.DRAFT
        assert order.items == []
        assert order.customer_id is None
        assert order.service is None
        assert order.payment_method is None
        assert order.payment_status == "pending"
        assert order.observations == []
        assert order.id.startswith("ORD-")

    def test_add_item(self):
        """Add OrderItem, verify items list grows, verify updated_at changes."""
        order = make_empty_order()
        updated_before = order.updated_at

        item = OrderItem(protein="Tacos", quantity=2, unit_price=45.0)
        order.add_item(item)

        assert len(order.items) == 1
        assert order.items[0] is item
        assert order.updated_at > updated_before

    def test_remove_item(self):
        """Add then remove, verify item removed."""
        order = make_empty_order()
        item = OrderItem(protein="Tacos", quantity=2, unit_price=45.0)
        order.add_item(item)
        item_id = item.id

        removed = order.remove_item(item_id)
        assert removed is item
        assert len(order.items) == 0

    def test_remove_item_not_found(self):
        """Remove non-existent item, verify ValueError."""
        order = make_empty_order()
        with pytest.raises(ValueError, match="no encontrado"):
            order.remove_item("nonexistent_id")

    def test_update_item(self):
        """Update quantity, verify change persisted."""
        order = make_empty_order()
        item = OrderItem(protein="Tacos", quantity=2, unit_price=45.0)
        order.add_item(item)
        item_id = item.id

        order.update_item(item_id, quantity=5)
        assert item.quantity == 5

    def test_update_item_not_found(self):
        """Update non-existent item, verify ValueError."""
        order = make_empty_order()
        with pytest.raises(ValueError, match="no encontrado"):
            order.update_item("nonexistent_id", quantity=3)

    def test_update_item_requirements(self):
        """Add requirements, remove requirements, requirements replacement."""
        order = make_empty_order()
        item = OrderItem(protein="Tacos", quantity=1)
        order.add_item(item)
        item_id = item.id

        # Add requirements
        order.update_item(item_id, add_requirements=["sin cebolla", "bien cocido"])
        assert "sin cebolla" in item.requirements
        assert "bien cocido" in item.requirements

        # Remove requirement
        order.update_item(item_id, remove_requirements=["sin cebolla"])
        assert "sin cebolla" not in item.requirements
        assert "bien cocido" in item.requirements

        # Replace all requirements
        order.update_item(item_id, requirements=["nuevo requerimiento"])
        assert item.requirements == ["nuevo requerimiento"]

    def test_order_subtotal(self):
        """Computed field sums item subtotals."""
        order = make_sample_order()  # 3x45 + 1x35 = 170
        assert order.subtotal == 170.0

    def test_order_total_amount_delivery(self):
        """With delivery service, verify fee is added."""
        order = make_sample_order()  # subtotal=170, delivery fee=15
        assert order.total_amount == 185.0

    def test_order_total_amount_pickup(self):
        """With pickup service, verify no fee added."""
        order = make_pickup_order()  # subtotal=90, pickup (no fee)
        assert order.total_amount == 90.0

    def test_order_total_amount_no_service(self):
        """Without service, equals subtotal."""
        items = [OrderItem(protein="Test", quantity=2, unit_price=25.0)]
        order = Order(items=items)
        assert order.subtotal == 50.0
        assert order.total_amount == 50.0

    def test_order_to_summary(self):
        """Verify compact format."""
        order = make_empty_order()
        assert order.to_summary() == "Pedido vacío."

        populated = make_sample_order()
        summary = populated.to_summary()
        assert "Tacos al Pastor" in summary
        assert "Guacamole" in summary
        assert "A domicilio" in summary

    def test_order_to_dict(self):
        """Verify dictionary format."""
        order = make_sample_order()
        d = order.to_dict()
        assert d["id"] == order.id
        assert d["customer_id"] is None
        assert d["status"] == OrderStatus.CONFIRMED
        assert d["subtotal"] == 170.0
        assert d["total"] == 185.0
        assert len(d["items"]) == 2
        assert d["service"] is not None
        assert "observations" in d

    def test_validate_order_valid(self):
        """Valid order returns empty errors."""
        order = make_sample_order()
        errors = order.validate_order()
        assert errors == []

    def test_validate_order_empty(self):
        """Empty order returns errors."""
        order = make_empty_order()
        errors = order.validate_order()
        assert len(errors) >= 1
        assert any("al menos un item" in e for e in errors)

    def test_validate_order_missing_protein(self):
        """Item without protein triggers error."""
        order = make_empty_order()
        item = OrderItem(quantity=1, unit_price=10.0)  # no protein
        order.add_item(item)
        errors = order.validate_order()
        assert any("proteína" in e for e in errors)

    def test_is_valid(self):
        """Verify is_valid() returns correct boolean."""
        assert make_sample_order().is_valid() is True
        assert make_empty_order().is_valid() is False

    def test_set_delivery(self):
        """set_delivery creates ServiceDetails with delivery category."""
        order = make_empty_order()
        order.set_delivery(address="Calle 123", fee=10.0)
        assert order.service is not None
        assert order.service.category == ServiceCategory.DELIVERY
        assert order.service.type_name == "A domicilio"
        assert isinstance(order.service.details, DeliveryDetails)
        assert order.service.details.address == "Calle 123"
        assert order.service.details.fee == 10.0

    def test_set_pickup(self):
        """set_pickup creates ServiceDetails with pickup category."""
        order = make_empty_order()
        order.set_pickup(scheduled_time=datetime(2026, 5, 19, 14, 0, 0))
        assert order.service is not None
        assert order.service.category == ServiceCategory.PICKUP
        assert order.service.type_name == "Para recoger"
        assert isinstance(order.service.details, PickupDetails)

    def test_update_order_metadata_customer(self):
        """customer_name sets customer_id."""
        order = make_empty_order()
        order.update_order_metadata(customer_name="Juan Pérez")
        assert order.customer_id == "Juan Pérez"

    def test_update_order_metadata_service_type_delivery(self):
        """service_type='delivery' with address."""
        order = make_empty_order()
        order.update_order_metadata(
            service_type="delivery",
            address="Calle Principal 456",
        )
        assert order.service is not None
        assert order.service.category == ServiceCategory.DELIVERY
        assert order.service.details.address == "Calle Principal 456"

    def test_update_order_metadata_service_type_pickup(self):
        """service_type='pickup' with scheduled_time."""
        order = make_empty_order()
        sched = datetime(2026, 5, 19, 15, 0, 0)
        order.update_order_metadata(
            service_type="pickup",
            scheduled_time=sched,
        )
        assert order.service is not None
        assert order.service.category == ServiceCategory.PICKUP

    def test_update_order_metadata_observations(self):
        """observations as string and as list."""
        order = make_empty_order()
        # As string
        order.update_order_metadata(observations="First note")
        assert "First note" in order.observations
        assert len(order.observations) == 1
        # As list
        order.update_order_metadata(observations=["Second note", "Third note"])
        assert "Second note" in order.observations
        assert "Third note" in order.observations
        assert len(order.observations) == 3


# =============================================================================
# ServiceDetails Tests
# =============================================================================


class TestServiceDetails:
    """Tests for ServiceDetails, DeliveryDetails, PickupDetails."""

    def test_service_details_create_delivery(self):
        """Factory method, verify category and type_name."""
        sd = ServiceDetails.create_delivery(address="Av. Siempre Viva 742", fee=12.0)
        assert sd.category == ServiceCategory.DELIVERY
        assert sd.type_name == "A domicilio"
        assert isinstance(sd.details, DeliveryDetails)
        assert sd.details.address == "Av. Siempre Viva 742"
        assert sd.details.fee == 12.0

    def test_service_details_create_pickup(self):
        """Factory method, verify category and type_name."""
        sd = ServiceDetails.create_pickup(scheduled_time=datetime(2026, 5, 19, 16, 0, 0))
        assert sd.category == ServiceCategory.PICKUP
        assert sd.type_name == "Para recoger"
        assert isinstance(sd.details, PickupDetails)

    def test_delivery_calculate_total_with_fee(self):
        """DeliveryDetails.calculate_total_with_fee adds fee."""
        dd = DeliveryDetails(address="Test", fee=15.0)
        assert dd.calculate_total_with_fee(100.0) == 115.0
        assert dd.calculate_total_with_fee(0.0) == 15.0

    def test_pickup_calculate_total_with_fee(self):
        """PickupDetails.calculate_total_with_fee returns subtotal unchanged."""
        pd = PickupDetails()
        assert pd.calculate_total_with_fee(100.0) == 100.0
        assert pd.calculate_total_with_fee(0.0) == 0.0
