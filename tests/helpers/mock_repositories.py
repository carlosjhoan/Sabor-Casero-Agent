"""
In-memory repository implementations for testing.
"""
from typing import Optional, Dict
from datetime import datetime
from src.core.order.domain.order_repository_interface import OrderRepository
from src.core.order.domain.session_repository_interface import SessionRepository, SessionData
from src.core.order.domain.models import Order


class InMemoryOrderRepository(OrderRepository):
    """In-memory implementation of OrderRepository for tests."""

    def __init__(self):
        self._orders: Dict[str, Order] = {}

    def create_order(self, customer_id: str) -> Order:
        order = Order(customer_id=customer_id)
        self._orders[order.id] = order
        return order

    def save_order(self, order: Order) -> None:
        self._orders[order.id] = order

    def get_order_by_id(self, order_id: str) -> Order:
        return self._orders.get(order_id)

    def delete_order(self, order_id: str) -> None:
        self._orders.pop(order_id, None)

    # Convenience helpers for test assertions

    def get_all_orders(self) -> list[Order]:
        """Return all stored orders."""
        return list(self._orders.values())

    def clear(self):
        """Remove all orders from the repository."""
        self._orders.clear()


class InMemorySessionRepository(SessionRepository):
    """In-memory implementation of SessionRepository for tests."""

    def __init__(self):
        self._sessions: Dict[str, SessionData] = {}

    def create_session(self, customer_id: Optional[str] = None) -> SessionData:
        session_id = f"ses-{len(self._sessions) + 1:03d}"
        now = datetime.now()
        session = SessionData(
            session_id=session_id,
            customer_id=customer_id,
            order_id=None,
            created_at=now,
            last_activity=now,
            turn_number=0,
            metadata={},
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionData]:
        return self._sessions.get(session_id)

    def get_active_order_id(self, session_id: str) -> Optional[str]:
        session = self._sessions.get(session_id)
        return session.order_id if session else None

    def link_session_to_order(self, session_id: str, order_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.order_id = order_id

    def link_customer_to_session(self, session_id: str, customer_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.customer_id = customer_id

    def update_session(self, session_id: str, **kwargs) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)
        session.last_activity = datetime.now()
        return True

    def end_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def get_session_by_customer(self, customer_id: str) -> Optional[SessionData]:
        for session in self._sessions.values():
            if session.customer_id == customer_id:
                return session
        return None

    def clear(self):
        """Remove all sessions from the repository."""
        self._sessions.clear()
