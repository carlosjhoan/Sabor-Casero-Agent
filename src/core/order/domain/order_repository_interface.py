from abc import ABC, abstractmethod
from src.core.order.domain.models import Order

class OrderRepository(ABC):
    "Repositorio para el modelo de Order"
    
    @abstractmethod
    def create_order(self, customer_id: str) -> Order:
        """Crea una nueva orden para un cliente dado."""

    @abstractmethod
    def save_order(self, order: Order):
        """Guarda o actualiza una orden en el repositorio."""

    @abstractmethod
    def get_order_by_id(self, order_id: str) -> Order:
        """Recupera una orden por su ID."""

    @abstractmethod
    def delete_order(self, order_id: str):
        """Elimina una orden del repositorio."""