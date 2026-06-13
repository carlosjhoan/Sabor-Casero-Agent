# memory/infrastructure/persistence/json_summary_repository.py
import json
import aiofiles
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
import asyncio
from src.utils.utils import DateTimeEncoder, print_section
from src.core.memory.domain.models import ConversationSummary
from src.core.memory.domain.summary_interface_repository import SummaryRepository

class JsonSummaryRepository(SummaryRepository):
    """
    Implementación JSON del repositorio de resúmenes.
    Un archivo por sesión: data/summaries/{session_id}.json
    """
    
    def __init__(self, base_path: str = "data/summaries"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._locks: dict = {}  # Locks por sesión para thread-safety
    
    def _get_file_path(self, session_id: str) -> Path:
        """Obtiene la ruta del archivo para una sesión."""
        return self.base_path / f"{session_id}.json"
    
    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """Obtiene o crea un lock para la sesión."""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]
    
    async def save(self, summary: ConversationSummary) -> None:
        """
        Guarda un resumen en el archivo de la sesión.
        Los resúmenes se guardan en orden cronológico.
        """
        lock = self._get_lock(summary.session_id)
        file_path = self._get_file_path(summary.session_id)
        
        async with lock:
            # Leer resúmenes existentes
            summaries = await self._read_file(file_path)
            
            # Añadir nuevo resumen
            summaries.append(summary.model_dump())
            
            # Ordenar por turn_number (por si acaso)
            summaries.sort(key=lambda x: x.get('turn_number', 0))
            
            # Guardar
            await self._write_file(file_path, summaries)
    
    async def get_latest(self, session_id: str) -> Optional[ConversationSummary]:
        """
        Obtiene el último resumen de una sesión.
        
        Returns the last entry by position in the JSON array (chronological
        order), falling back to ``turn_number`` tiebreaker for safety.
        """
        file_path = self._get_file_path(session_id)
        
        if not file_path.exists():
            return None
        
        summaries = await self._read_file(file_path)
        
        if not summaries:
            return None
        
        # The list is in chronological order (appended on each save).
        # Return the LAST entry. turn_number may be unreliable when multiple
        # turns share the same turn_number (e.g. CLI with no session object).
        latest = summaries[-1]
        return ConversationSummary.model_validate(latest)
    
    async def get_by_session(self, session_id: str, limit: int = 10) -> List[ConversationSummary]:
        """
        Obtiene los últimos N resúmenes de una sesión.
        """
        file_path = self._get_file_path(session_id)
        
        if not file_path.exists():
            return []
        
        summaries = await self._read_file(file_path)
        
        # Ordenar por turn_number descendente y limitar
        summaries.sort(key=lambda x: x.get('turn_number', 0), reverse=True)
        latest = summaries[:limit]
        
        return [ConversationSummary.model_validate(s) for s in latest]
    
    async def delete_old(self, days: int = 30) -> int:
        """
        Elimina resúmenes más antiguos que días.
        Retorna número de archivos eliminados.
        """
        cutoff = datetime.now() - timedelta(days=days)
        deleted = 0
        
        for file_path in self.base_path.glob("*.json"):
            # Verificar fecha de modificación del archivo
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            if mtime < cutoff:
                file_path.unlink()
                deleted += 1
                
                # Limpiar lock si existe
                session_id = file_path.stem
                if session_id in self._locks:
                    del self._locks[session_id]
        
        return deleted
    
    async def _read_file(self, file_path: Path) -> list:
        """Lee el archivo JSON de manera segura."""
        if not file_path.exists():
            return []
        
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content) if content else []
        except (json.JSONDecodeError, FileNotFoundError):
            # Si el archivo está corrupto, empezar de nuevo
            return []
    
    async def _write_file(self, file_path: Path, data: list) -> None:
        """Escribe al archivo JSON de manera atómica."""
        # Escribir primero a temporal
        temp_path = file_path.with_suffix('.tmp')
        
        try:
            async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False, cls=DateTimeEncoder))
            
            # Reemplazar archivo original
            temp_path.replace(file_path)
            print_section(head=f"Resumen guardado para sesión {file_path.stem}", msg=f"Archivo: {file_path.name}")
            
        except Exception as e:
            # Limpiar temporal si hay error
            if temp_path.exists():
                temp_path.unlink()
            raise e