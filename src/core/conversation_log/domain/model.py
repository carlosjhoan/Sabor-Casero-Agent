# conversation_log/domain/models/conversation_log_entry.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
from src.core.classifier.intent import Detail

class ConversationLogEntry(BaseModel):
    """Modelo para cada entrada de conversación"""
    
    # Identificadores
    log_id: str = Field(default_factory=lambda: f"log_{uuid.uuid4().hex[:8]}")
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # Input del usuario
    user_message: str
    user_id: Optional[str] = None
    
    # Etapa de extracción/clasificación
    # extraction_focus: Optional[str] = None
    # extracted_info: Optional[Dict[str, Any]] = None
    topic_details: Optional[List[Detail]] = None
    
    # Etapa de procesamiento (processor)
    processor_thought: Optional[str] = None
    proposed_actions: Optional[List[Dict[str, Any]]] = None
    
    # Resultado final
    order_before: Optional[Dict[str, Any]] = None
    order_after: Optional[Dict[str, Any]] = None
    assistant_response: Optional[str] = None
    
    # Métricas
    processing_time_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    
    # Metadatos adicionales
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }