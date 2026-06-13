# conversation_log/infrastructure/repositories/json_conversation_log_repository.py
import json
from pathlib import Path
from datetime import date, datetime
from typing import List, Optional
import asyncio
import aiofiles
from src.core.conversation_log.domain.conversation_log_interface import ConversationLogRepository
from src.core.conversation_log.domain.model import ConversationLogEntry
from src.utils.utils import DateTimeEncoder

class JsonConversationLogRepository(ConversationLogRepository):
    """
    Implementación JSON que crea un archivo por día.
    Estructura:
    logs/
    ├── 2026/
    │   ├── 02/
    │   │   ├── 2026-02-28.json
    │   │   ├── 2026-03-01.json
    │   │   └── ...
    """
    
    def __init__(self, base_path: str = "data/conversation_logs"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()  # Para operaciones thread-safe
    
    def _get_daily_file_path(self, log_date: Optional[date] = None) -> Path:
        """Obtiene la ruta del archivo para un día específico"""
        if log_date is None:
            log_date = date.today()
        
        # Estructura: logs/YYYY/MM/YYYY-MM-DD.json
        year_path = self.base_path / str(log_date.year)
        month_path = year_path / f"{log_date.month:02d}"
        month_path.mkdir(parents=True, exist_ok=True)
        
        return month_path / f"{log_date.isoformat()}.json"
    
    async def save_entry(self, entry: ConversationLogEntry) -> str:
        """Guarda una entrada en el archivo del día correspondiente"""
        async with self._lock:
            file_path = self._get_daily_file_path(entry.timestamp.date())
            
            # Leer entradas existentes
            entries = await self._read_entries(file_path)
            
            # Añadir nueva entrada
            entries.append(entry.model_dump())
            
            # Guardar todo el archivo
            await self._write_entries(file_path, entries)
            
            return entry.log_id
    
    async def get_entries_by_date(self, log_date: date) -> List[ConversationLogEntry]:
        """Obtiene todas las entradas de una fecha específica"""
        file_path = self._get_daily_file_path(log_date)
        
        if not file_path.exists():
            return []
        
        entries_data = await self._read_entries(file_path)
        
        return [
            ConversationLogEntry.model_validate(entry_data)
            for entry_data in entries_data
        ]
    
    async def get_entries_by_session(self, session_id: str) -> List[ConversationLogEntry]:
        """Obtiene todas las entradas de una sesión (buscando en todos los archivos)"""
        all_entries = []
        
        # Recorrer todos los archivos de logs (esto podría optimizarse con índices)
        for year_path in self.base_path.iterdir():
            if not year_path.is_dir():
                continue
            
            for month_path in year_path.iterdir():
                if not month_path.is_dir():
                    continue
                
                for file_path in month_path.glob("*.json"):
                    entries_data = await self._read_entries(file_path)
                    
                    for entry_data in entries_data:
                        if entry_data.get("session_id") == session_id:
                            all_entries.append(ConversationLogEntry.model_validate(entry_data))
        
        # Ordenar por timestamp
        all_entries.sort(key=lambda x: x.timestamp)
        
        return all_entries
    
    async def get_entry(self, log_id: str) -> Optional[ConversationLogEntry]:
        """Busca una entrada por ID en todos los archivos"""
        for year_path in self.base_path.iterdir():
            if not year_path.is_dir():
                continue
            
            for month_path in year_path.iterdir():
                if not month_path.is_dir():
                    continue
                
                for file_path in month_path.glob("*.json"):
                    entries_data = await self._read_entries(file_path)
                    
                    for entry_data in entries_data:
                        if entry_data.get("log_id") == log_id:
                            return ConversationLogEntry.model_validate(entry_data)
        
        return None
    
    async def update_entry(self, log_id: str, updates: dict) -> bool:
        """Actualiza una entrada existente"""
        async with self._lock:
            # Buscar el archivo que contiene la entrada
            for year_path in self.base_path.iterdir():
                if not year_path.is_dir():
                    continue
                
                for month_path in year_path.iterdir():
                    if not month_path.is_dir():
                        continue
                    
                    for file_path in month_path.glob("*.json"):
                        entries_data = await self._read_entries(file_path)
                        updated = False
                        
                        for i, entry_data in enumerate(entries_data):
                            if entry_data.get("log_id") == log_id:
                                # Actualizar campos
                                entries_data[i].update(updates)
                                entries_data[i]["updated_at"] = datetime.now().isoformat()
                                updated = True
                                break
                        
                        if updated:
                            await self._write_entries(file_path, entries_data)
                            return True
            
            return False
    
    async def _read_entries(self, file_path: Path) -> list:
        """Lee entradas de un archivo JSON"""
        if not file_path.exists():
            return []
        
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content) if content else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    async def _write_entries(self, file_path: Path, entries: list) -> None:
        """Escribe entradas a un archivo JSON"""
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            # Usar el encoder personalizado
            json_str = json.dumps(entries, indent=2, ensure_ascii=False, cls=DateTimeEncoder)
            await f.write(json_str)