"""
Caché de documentos con persistencia JSON y escritura atómica.

Almacena entradas de documentos indexados con detección de cambios
vía SHA256. Las escrituras usan patrón .tmp + os.replace para evitar
corrupción por cortes de energía o fallos del sistema.
"""
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from src.core.knowledge.content_analyzer import Section

logger = logging.getLogger(__name__)


@dataclass
class DocEntry:
    """Entrada de un documento en la caché."""
    filename: str = ""
    sha256: str = ""
    sections: List[Section] = field(default_factory=list)
    summary: str = ""
    last_updated: str = ""


class DocumentCache:
    """Caché JSON con escritura atómica y detección de cambios.

    Almacena DocEntry serializados en un archivo JSON.
    Usa patrón de escritura atómica: escribe a .tmp, luego renombra.
    """

    def __init__(self, path: Path):
        """Inicializa la caché desde archivo.

        Args:
            path: Ruta al archivo JSON de caché.
        """
        self.path = Path(path)
        self._data: Dict[str, dict] = {}
        self.rebuild_if_corrupt()

    # ── API pública ─────────────────────────────────────────────────────

    def get(self, filename: str) -> Optional[DocEntry]:
        """Obtiene una entrada de la caché.

        Args:
            filename: Nombre del archivo documento.

        Returns:
            DocEntry si existe, None si no.
        """
        raw = self._data.get(filename)
        if raw is None:
            return None

        return DocEntry(
            filename=raw.get("filename", filename),
            sha256=raw.get("sha256", ""),
            sections=[Section(**s) for s in raw.get("sections", [])],
            summary=raw.get("summary", ""),
            last_updated=raw.get("last_updated", ""),
        )

    def put(self, filename: str, entry: DocEntry) -> None:
        """Guarda una entrada en la caché con escritura atómica.

        Args:
            filename: Nombre del archivo documento.
            entry: Entrada a guardar.
        """
        self._data[filename] = {
            "filename": entry.filename,
            "sha256": entry.sha256,
            "sections": [
                {"heading": s.heading, "body": s.body} for s in entry.sections
            ],
            "summary": entry.summary,
            "last_updated": entry.last_updated
            or datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def has_changed(self, filename: str, sha256: str) -> bool:
        """Verifica si un documento cambió respecto a la caché.

        Args:
            filename: Nombre del archivo documento.
            sha256: Hash SHA256 actual del documento.

        Returns:
            True si el documento es nuevo o cambió.
        """
        raw = self._data.get(filename)
        if raw is None:
            return True
        return raw.get("sha256") != sha256

    def rebuild_if_corrupt(self) -> None:
        """Intenta cargar la caché; si está corrupta, la reinicia."""
        if not self.path.exists():
            return

        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            # Validación básica de estructura
            if not isinstance(loaded, dict):
                raise ValueError("Cache root is not a dict")
            self._data = loaded
        except (json.JSONDecodeError, ValueError, Exception) as exc:
            logger.warning("Cache corrupt at %s, rebuilding: %s", self.path, exc)
            self._data = {}

    # ── Internos ─────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Escritura atómica: .tmp → os.replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(str(tmp_path), str(self.path))
