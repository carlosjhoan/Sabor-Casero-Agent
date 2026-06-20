# infrastructure/persistence/json_session_repository.py
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import threading

from src.utils.utils import print_section

from src.core.order.domain.session_repository_interface import SessionRepository, SessionData

class JsonSessionRepository(SessionRepository):
    """
    Implementación JSON del repositorio de sesiones.
    Almacena sesiones en archivo JSON con estructura:
    {
        "sessions": {
            "sess_abc123": {
                "customer_id": "user123",
                "order_id": "ORD-456",
                "created_at": "2024-01-01T10:00:00",
                "last_activity": "2024-01-01T10:05:00",
                "metadata": {}
            }
        },
        "customer_index": {
            "user123": "sess_abc123"
        }
    }
    """
    
    def __init__(self, file_path: str = "data/persistence/sessions.json"):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()  # Para operaciones thread-safe
    
    def _read_data(self) -> Dict[str, Any]:
        """Lee todo el archivo de sesiones"""
        if not self.path.exists():
            return {"sessions": {}, "customer_index": {}}
        
        try:
            with self._lock:
                with open(self.path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"sessions": {}, "customer_index": {}}
    
    def _write_data(self, data: Dict[str, Any]) -> None:
        """Escribe datos al archivo de manera atómica usando archivo temporal."""
        with self._lock:
            # Escribir primero a un archivo temporal
            temp_path = self.path.with_suffix('.tmp')
            
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # Renombrar el temporal al definitivo (esto SÍ reemplaza)
                temp_path.replace(self.path)  # replace() funciona en todas plataformas
                
            except Exception as e:
                # Limpiar archivo temporal si existe
                if temp_path.exists():
                    temp_path.unlink()
                raise e
    
    def create_session(self, customer_id: Optional[str] = None, session_id: Optional[str] = None) -> SessionData:
        """Crea nueva sesión"""
        data = self._read_data()
        
        # Generar ID único si no se provee uno
        if session_id is None:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        
        # Crear sesión
        session = {
            "session_id": session_id,
            "customer_id": customer_id,
            "order_id": None,
            "created_at": now,
            "last_activity": now,
            "metadata": {},
            "field_status": {},
        }
        
        data["sessions"][session_id] = session
        
        # Indexar por customer si existe
        if customer_id:
            data["customer_index"][customer_id] = session_id
        
        self._write_data(data)
        
        return SessionData(
            session_id=session_id,
            customer_id=customer_id,
            created_at=datetime.fromisoformat(now),
            last_activity=datetime.fromisoformat(now)
        )
    
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Obtiene sesión por ID"""
        data = self._read_data()
        session = data["sessions"].get(session_id)
        
        if not session:
            return None
        
        return SessionData(**session)
    
    def get_active_order_id(self, session_id: str) -> Optional[str]:
        """Obtiene order_id de una sesión"""
        data = self._read_data()
        session = data["sessions"].get(session_id)
        return session.get("order_id") if session else None
    
    def link_session_to_order(self, session_id: str, order_id: str) -> None:
        """Asocia sesión con orden"""
        print_section(head="RELACIONADO SESSION CON ORDER")
        data = self._read_data()
        if session_id in data["sessions"]:
            print_section(head="Sesión en curso", msg=session_id)
            print_section(head="Orden en curso", msg=order_id)
            data["sessions"][session_id]["order_id"] = order_id
            data["sessions"][session_id]["last_activity"] = datetime.now().isoformat()
            self._write_data(data)
    
    def link_customer_to_session(self, session_id: str, customer_id: str) -> None:
        """Asocia cliente a sesión"""
        data = self._read_data()
        if session_id in data["sessions"]:
            # Remover index anterior si existía
            old_customer = data["sessions"][session_id].get("customer_id")
            if old_customer and old_customer in data["customer_index"]:
                del data["customer_index"][old_customer]
            
            # Actualizar sesión
            data["sessions"][session_id]["customer_id"] = customer_id
            data["sessions"][session_id]["last_activity"] = datetime.now().isoformat()
            
            # Actualizar índice
            data["customer_index"][customer_id] = session_id
            
            self._write_data(data)
    
    def update_session(self, session_id: str, new_turn: bool = False, **kwargs) -> bool:
        """
        Actualiza campos específicos de una sesión.
        
        Args:
            session_id: ID de la sesión a actualizar
            new_turn: Indica si es un nuevo turno de conversación
            **kwargs: Campos a actualizar (log_id, customer_id, order_id, metadata, etc.)
        
        Returns:
            bool: True si se actualizó, False si la sesión no existe
        
        Ejemplos:
            repo.update_session("sess_123", log_id="log_abc456")
            repo.update_session("sess_123", customer_id="user_789", order_id="ORD-999")
            repo.update_session("sess_123", metadata={"last_intent": "ordering"})
            repo.update_session("sess_123", last_activity=datetime.now())
        """
        data = self._read_data()
        
        # Verificar que la sesión existe
        if session_id not in data["sessions"]:
            print(f"⚠️ Sesión {session_id} no encontrada para actualizar")
            return False
        
        session = data["sessions"][session_id]

        if new_turn:
            session["turn_number"] = session.get("turn_number", 0) + 1

        print_section(head="Actualizando sesión", msg=f"Session ID: {session_id}\nNúmero de turnos: {session.get('turn_number', 0)}\nCampos a actualizar: {kwargs}")
        
        # Procesar cada campo según su tipo
        for key, value in kwargs.items():
            if key == "metadata" and isinstance(value, dict):
                # Merge de metadata en lugar de reemplazar
                if "metadata" not in session:
                    session["metadata"] = {}
                session["metadata"].update(value)
            
            elif key == "last_activity":
                # Campo especial con timestamp automático si no se provee
                if value is None:
                    session["last_activity"] = datetime.now().isoformat()
                else:
                    session["last_activity"] = value.isoformat() if hasattr(value, 'isoformat') else str(value)
            
            elif key == "customer_id":
                # Si cambia customer_id, actualizar índices
                old_customer = session.get("customer_id")
                if old_customer and old_customer in data["customer_index"]:
                    del data["customer_index"][old_customer]
                
                session["customer_id"] = value
                
                if value:  # Si hay nuevo customer_id, añadir índice
                    data["customer_index"][value] = session_id
            
            elif key == "order_id":
                # Actualizar order_id
                session["order_id"] = value
            
            elif key == "log_id":
                # Nuevo campo para tracking de conversaciones
                session["log_id"] = value
            
            elif key == "conversation_history":
                # Manejo especial para historial (append)
                if "conversation_history" not in session:
                    session["conversation_history"] = []
                if isinstance(value, list):
                    session["conversation_history"].extend(value)
                else:
                    session["conversation_history"].append(value)
            
            else:
                # Para cualquier otro campo, asignación directa
                session[key] = value
        
        # Siempre actualizar last_activity si no se especificó explícitamente
        if "last_activity" not in kwargs:
            session["last_activity"] = datetime.now().isoformat()
        
        # Guardar cambios
        self._write_data(data)
        return True
    
    def end_session(self, session_id: str) -> None:
        """Finaliza sesión"""
        data = self._read_data()
        if session_id in data["sessions"]:
            # Remover del índice de customer
            customer_id = data["sessions"][session_id].get("customer_id")
            if customer_id and customer_id in data["customer_index"]:
                del data["customer_index"][customer_id]
            
            # Eliminar sesión
            del data["sessions"][session_id]
            self._write_data(data)
    
    def get_session_by_customer(self, customer_id: str) -> Optional[SessionData]:
        """Encuentra sesión activa de un cliente"""
        data = self._read_data()
        session_id = data["customer_index"].get(customer_id)
        
        if session_id and session_id in data["sessions"]:
            session = data["sessions"][session_id]
            return SessionData(
                session_id=session["session_id"],
                customer_id=session.get("customer_id"),
                order_id=session.get("order_id"),
                created_at=datetime.fromisoformat(session["created_at"]),
                last_activity=datetime.fromisoformat(session["last_activity"]),
                metadata=session.get("metadata", {}),
                field_status=session.get("field_status", {}),
            )
        return None
    
    def cleanup_expired(self, max_age_minutes: int = 60) -> int:
        """
        Limpia sesiones inactivas.
        Returns: número de sesiones eliminadas
        """
        data = self._read_data()
        now = datetime.now()
        expired = []
        
        for session_id, session in data["sessions"].items():
            last = datetime.fromisoformat(session["last_activity"])
            if (now - last).total_seconds() > max_age_minutes * 60:
                expired.append(session_id)
        
        for session_id in expired:
            customer_id = data["sessions"][session_id].get("customer_id")
            if customer_id and customer_id in data["customer_index"]:
                del data["customer_index"][customer_id]
            del data["sessions"][session_id]
        
        if expired:
            self._write_data(data)
        
        return len(expired)