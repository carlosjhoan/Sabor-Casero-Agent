# conversation_log/application/services/conversation_logger.py
from datetime import date
from typing import Optional, Dict, Any, List
from src.core.conversation_log.domain.model import ConversationLogEntry
from src.core.conversation_log.domain.conversation_log_interface import ConversationLogRepository
from src.core.classifier.intent import Detail
from src.utils.utils import print_section

class ConversationLogger:
    """
    Servicio principal para logging de conversaciones.
    Actúa como facade para el repositorio y proporciona métodos convenientes.
    """
    
    def __init__(self, repository: ConversationLogRepository):
        self.repository = repository
        self._current_entry: Optional[ConversationLogEntry] = None
    
    async def start_interaction(self, session_id: str, user_message: str, user_id: Optional[str] = None) -> str:
        """
        Inicia una nueva interacción de log.
        Retorna el ID del log para referencia.
        """
        self._current_entry = ConversationLogEntry(
            session_id=session_id,
            user_message=user_message,
            user_id=user_id,
        )
        
        # Guardar entrada inicial
        log_id = await self.repository.save_entry(self._current_entry)
        
        print_section(head="LOG ID", msg=log_id)
        
        # return log_id
    
    async def log_extraction(self, topic_details: List[Detail]) -> None:
        """Registra resultados de la etapa de extracción"""
        if not self._current_entry:
            return
        
        # Extraer información relevante
        # topic_details = topic_details
        
        # Crear resumen de focus
        # focus_summary = " | ".join([
        #     d.focus for d in topic_details 
        #     if d.focus
        # ])
        
        # self._current_entry.extraction_focus = focus_summary
        # self._current_entry.extracted_info = topic_details
        self._current_entry.topic_details = topic_details
        
        await self._update_entry()
    
    async def log_processor(self, 
                           processor_thought: str, 
                           proposed_actions: List[Dict[str, Any]]) -> None:
        """Registra resultados de la etapa de procesamiento"""
        if not self._current_entry:
            return
        
        self._current_entry.processor_thought = processor_thought
        self._current_entry.proposed_actions = proposed_actions
        
        await self._update_entry()
    
    async def log_result(self, 
                        assistant_response: str,
                        order_before: Optional[Dict[str, Any]] = None,
                        order_after: Optional[Dict[str, Any]] = None,
                        success: bool = True,
                        error_message: Optional[str] = None,
                        processing_time_ms: Optional[float] = None) -> None:
        """Registra el resultado final de la interacción"""
        if not self._current_entry:
            return
        
        self._current_entry.assistant_response = assistant_response
        self._current_entry.order_before = order_before
        self._current_entry.order_after = order_after
        self._current_entry.success = success
        self._current_entry.error_message = error_message
        self._current_entry.processing_time_ms = processing_time_ms
        
        await self._update_entry()
    
    async def add_metadata(self, key: str, value: Any) -> None:
        """Añade metadata adicional a la entrada actual"""
        if not self._current_entry:
            return
        
        self._current_entry.metadata[key] = value
        await self._update_entry()
    
    async def _update_entry(self) -> None:
        """Actualiza la entrada en el repositorio"""
        if not self._current_entry or not self._current_entry.log_id:
            return
        
        await self.repository.update_entry(
            self._current_entry.log_id,
            self._current_entry.model_dump()
        )
    
    async def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Obtiene historial completo de una sesión"""
        entries = await self.repository.get_entries_by_session(session_id)
        
        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "user": e.user_message,
                "assistant": e.assistant_response,
                "success": e.success
            }
            for e in entries
        ]
    
    async def get_daily_summary(self, log_date: Optional[date] = None) -> Dict[str, Any]:
        """Obtiene resumen de un día de conversaciones"""
        if log_date is None:
            log_date = date.today()
        
        entries = await self.repository.get_entries_by_date(log_date)
        
        total = len(entries)
        successful = sum(1 for e in entries if e.success)
        
        return {
            "date": log_date.isoformat(),
            "total_interactions": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": (successful / total * 100) if total > 0 else 0,
            "avg_processing_time": sum(e.processing_time_ms or 0 for e in entries) / total if total > 0 else 0
        }