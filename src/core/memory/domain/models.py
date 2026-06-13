# domain/models/conversation_summary.py
from pydantic import BaseModel, Field
from typing import List, Dict
from datetime import datetime
import uuid

class ConversationSummary(BaseModel):
    """
    Resumen comprimido de la conversación.
    Mantiene < 200 tokens pero captura lo esencial.
    """
    summary_id: str = Field(default_factory=lambda: f"summary_{uuid.uuid4().hex[:6]}")
    session_id: str
    turn_number: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    
    # Resumen ultra-compacto
    summary_text: str  # "Cliente ordenó: pechuga (pendiente talla), luego carne (pendiente)"

    previous_summary: str = ""  # Resumen previo para referencia (opcional)
    
    # Estado actual del pedido (en texto)
    current_order_state: str  # "Items: pechuga (en proceso), carne (pendiente)"
    
    # Referencias activas
    # active_references: Dict[str, str] = Field(default_factory=dict)  # {"la": "pechuga", "ese": "carne"}
    
    # Items pendientes de definir
    #pending_items: List[str] = Field(default_factory=list)  # ["talla de pechuga", "acompañamiento carne"]
    
    # Metadata para debugging
    source_turns: List[int] = Field(default_factory=list)  # Turns que componen este resumen
    tokens_estimated: int = 0  # Tokens originales vs resumen


    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    
    def to_context_string(self) -> str:
        """Convierte el resumen a string para inyectar en prompts."""
        #parts = [f"[CONTEXT: {self.summary_text}"]

        return f"[CONTEXT: {self.summary_text}"
        
        # if self.pending_items:
        #     parts.append(f"Pending: {', '.join(self.pending_items)}")
        
        # if self.active_references:
        #     refs = [f"{k}→{v}" for k, v in self.active_references.items()]
        #     parts.append(f"Refs: {', '.join(refs)}")
        
        # return " | ".join(parts) + "]"