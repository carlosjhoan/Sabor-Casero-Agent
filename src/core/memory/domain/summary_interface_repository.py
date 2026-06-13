# memory/domain/repositories/summary_repository.py
from abc import ABC, abstractmethod
from typing import Optional, List
from src.core.memory.domain.models import ConversationSummary

class SummaryRepository(ABC):
    """
    Puerto/Interfaz para el repositorio de resúmenes.
    Define el contrato que cualquier implementación debe cumplir.
    """
    
    @abstractmethod
    async def save(self, summary: ConversationSummary) -> None:
        """Guarda un resumen."""
        
    
    @abstractmethod
    async def get_latest(self, session_id: str) -> Optional[ConversationSummary]:
        """Obtiene el último resumen de una sesión."""
        
    
    @abstractmethod
    async def get_by_session(self, session_id: str, limit: int = 10) -> List[ConversationSummary]:
        """Obtiene los últimos N resúmenes de una sesión."""
        
    
    @abstractmethod
    async def delete_old(self, days: int = 30) -> int:
        """Elimina resúmenes más antiguos que días."""
        