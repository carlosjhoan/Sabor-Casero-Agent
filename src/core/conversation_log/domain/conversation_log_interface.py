# conversation_log/domain/interfaces/conversation_log_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import date
from src.core.conversation_log.domain.model import ConversationLogEntry

class ConversationLogRepository(ABC):
    """Interfaz para el repositorio de logs de conversación"""
    
    @abstractmethod
    async def save_entry(self, entry: ConversationLogEntry) -> str:
        """Guarda una entrada de log"""
        
    
    @abstractmethod
    async def get_entries_by_date(self, log_date: date) -> List[ConversationLogEntry]:
        """Obtiene todas las entradas de un día específico"""
        
    
    @abstractmethod
    async def get_entries_by_session(self, session_id: str) -> List[ConversationLogEntry]:
        """Obtiene todas las entradas de una sesión"""
        
    
    @abstractmethod
    async def get_entry(self, log_id: str) -> Optional[ConversationLogEntry]:
        """Obtiene una entrada específica por ID"""
        
    
    @abstractmethod
    async def update_entry(self, log_id: str, updates: dict) -> bool:
        """Actualiza una entrada existente"""
        