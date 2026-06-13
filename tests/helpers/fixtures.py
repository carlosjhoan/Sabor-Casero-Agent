"""
Shared test data factories.

NOTE: These factories use the real domain model field names as defined in
src/core/order/domain/models.py and src/core/classifier/intent.py.
"""
from datetime import datetime
from src.core.order.domain.models import (
    Order,
    OrderItem,
    OrderStatus,
    ServiceDetails,
    DeliveryDetails,
    PickupDetails,
    ServiceCategory,
)


def make_sample_order(**overrides) -> Order:
    """Create a fully populated sample Order with delivery service."""
    items = [
        OrderItem(
            protein="Tacos al Pastor",
            quantity=3,
            unit_price=45.0,
        ),
        OrderItem(
            protein="Guacamole",
            quantity=1,
            unit_price=35.0,
        ),
    ]
    service = ServiceDetails.create_delivery(
        address="Calle Principal 123",
        fee=15.0,
    )
    order = Order(
        status=OrderStatus.CONFIRMED,
        items=items,
        service=service,
        observations=["Test order"],
    )
    for key, value in overrides.items():
        setattr(order, key, value)
    return order


def make_pickup_order(**overrides) -> Order:
    """Create a fully populated sample Order with pickup service."""
    items = [
        OrderItem(
            protein="Tacos al Pastor",
            quantity=2,
            unit_price=45.0,
        ),
    ]
    service = ServiceDetails.create_pickup(
        scheduled_time=datetime(2026, 5, 19, 13, 0, 0),
    )
    order = Order(
        status=OrderStatus.CONFIRMED,
        items=items,
        service=service,
    )
    for key, value in overrides.items():
        setattr(order, key, value)
    return order


def make_empty_order(**overrides) -> Order:
    """Create an empty order (no items)."""
    order = Order(
        status=OrderStatus.DRAFT,
        items=[],
    )
    for key, value in overrides.items():
        setattr(order, key, value)
    return order


def make_sample_classification():
    """Create a sample UserQueryClassifier for tests."""
    from src.core.classifier.intent import (
        UserQueryClassifier,
        Detail,
        QueryTopic,
        QueryType,
    )
    detail = Detail(
        segment="quiero ordenar tacos al pastor",
        focus="quiero ordenar tacos al pastor",
        topic=QueryTopic.MENU,
        query_type=QueryType.ORDERING,
        file_source="menu_platos_fuertes",
    )
    return UserQueryClassifier(
        topic_details=[detail],
        requires_RAG=True,
        requires_reconcilier=True,
    )
