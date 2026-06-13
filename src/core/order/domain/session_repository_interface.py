# domain/session_repository_interface.py
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class SessionData:
    """Modelo de dominio para datos de sesión"""
    session_id: str
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    log_id: Optional[str] = None
    created_at: datetime = None
    last_activity: datetime = None
    turn_number: int = 0
    metadata: dict = None

class SessionRepository(ABC):
    """Puerto/Interfaz para el repositorio de sesiones.
    Define el contrato que cualquier implementación debe cumplir.
    """
    @abstractmethod
    def create_session(self, customer_id: Optional[str] = None, session_id: Optional[str] = None) -> SessionData:
        """Crea una nueva sesión, con o sin customer_id, y opcionalmente con un session_id específico"""
    
    @abstractmethod
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Obtiene datos de una sesión por su ID"""
    
    @abstractmethod
    def get_active_order_id(self, session_id: str) -> Optional[str]:
        """Recupera el ID de la orden activa para una sesión"""
    
    @abstractmethod
    def link_session_to_order(self, session_id: str, order_id: str) -> None:
        """Asocia una sesión con un ID de orden"""
    
    @abstractmethod
    def link_customer_to_session(self, session_id: str, customer_id: str) -> None:
        """Asocia un cliente autenticado a una sesión"""
    
    @abstractmethod
    def update_session(self, session_id: str, **kwargs) -> bool:
        """
        Actualiza campos específicos de una sesión.
        
        Args:
            session_id: ID de la sesión a actualizar
            **kwargs: Campos a actualizar (ej: log_id="log_123", metadata={"key": "value"})
        
        Returns:
            bool: True si se actualizó, False si no existía la sesión
        
        Ejemplos:
            repo.update_session("sess_123", log_id="log_abc456")
            repo.update_session("sess_123", metadata={"last_intent": "ordering"})
            repo.update_session("sess_123", customer_id="user_789", order_id="ORD-123")
        """
    
    @abstractmethod
    def end_session(self, session_id: str) -> None:
        """Finaliza una sesión explícitamente"""
    
    @abstractmethod
    def get_session_by_customer(self, customer_id: str) -> Optional[SessionData]:
        """Encuentra sesión activa de un cliente"""
