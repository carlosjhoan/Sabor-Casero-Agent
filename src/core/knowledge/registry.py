"""
Registro de documentos con descubrimiento dinámico, mapeo YAML, caché
y enriquecimiento LLM opcional.

Reemplaza la lista hardcodeada de DocumentReference con un pipeline que:
1. Escanea data/documents/ en busca de archivos
2. Carga mapeo topic→archivo desde YAML
3. Analiza contenido vía ContentAnalyzer + DocumentCache
4. Enriquecimiento opcional con LLM para resúmenes narrativos
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from ..classifier.intent import QueryTopic
from .content_analyzer import ContentAnalyzer
from .document_cache import DocEntry, DocumentCache

logger = logging.getLogger(__name__)


class DocumentRegistry:
    """Registro dinámico de documentos con mapeo de tópicos.

    Descubre archivos en el directorio de documentos, analiza su contenido
    estructuralmente, y mantiene una caché de resultados. El mapeo de
    tópicos a documentos se configura via YAML.

    Args:
        docs_dir: Directorio donde están los documentos.
        cache_path: Ruta al archivo JSON de caché.
        config_path: Ruta al archivo YAML de mapeo topic→documento.
        llm_client: Cliente LLM opcional para enriquecimiento narrativo.
            Si se provee, cada documento modificado recibe un resumen
            generado por LLM. Si no, solo se usa análisis estructural.
    """

    def __init__(
        self,
        docs_dir: str = "data/documents",
        cache_path: str = "data/cache/document_cache.json",
        config_path: str = "data/config/topic_document_map.yaml",
        llm_client: Optional[object] = None,
    ):
        self._docs_dir = Path(docs_dir)
        self._cache_path = Path(cache_path)
        self._config_path = Path(config_path)
        self._llm_client = llm_client

        # 1. Cargar mapeo topic → documento desde YAML
        self._topic_to_doc: Dict[str, str] = self._load_topic_map()

        # 2. Escanear archivos en el directorio de documentos
        self._scanned_files: List[str] = sorted(
            f.name for f in self._docs_dir.iterdir() if f.is_file()
        )

        # 3. Inicializar caché
        self._cache = DocumentCache(self._cache_path)

        # 4. Procesar cada archivo: detectar cambios, analizar si es necesario
        self._process_files()

    # ── API pública (firmas idénticas al original) ──────────────────────

    def get_doc_for_topic(self, topic: QueryTopic) -> str:
        """Retorna el nombre del documento para un tópico.

        Args:
            topic: Tópico a consultar.

        Returns:
            Nombre del archivo documento, o 'no-file' si no hay mapping.
        """
        if topic in [QueryTopic.GREETING, QueryTopic.FAREWELL]:
            return "no-file"

        doc_name = self._topic_to_doc.get(topic.value)
        if doc_name is None:
            return "no-file"

        # Verificar que el archivo existe en el directorio escaneado
        if doc_name not in self._scanned_files:
            logger.warning(
                "YAML mapea %s → %s pero el archivo no existe en %s",
                topic.value, doc_name, self._docs_dir,
            )
            return "no-file"

        return doc_name

    def get_all_summaries(self) -> str:
        """Genera resumen formateado de todos los documentos.

        Formato (idéntico al original):
        - Document: {name}
          Topics: [{topic1, topic2}]
          Content: {content}

        Returns:
            String con el resumen de todos los documentos.
        """
        lines = []
        for filename in self._scanned_files:
            # Obtener tópicos que mapean a este archivo
            topics = sorted(
                t for t, doc in self._topic_to_doc.items() if doc == filename
            )
            topics_str = ", ".join(topics) if topics else "UNMAPPED"

            # Obtener contenido desde la caché
            entry = self._cache.get(filename)
            content = self._format_entry_content(entry) if entry else "Sin contenido"

            lines.append(
                f"- Document: {filename}\n"
                f"  Topics: [{topics_str}]\n"
                f"  Content: {content}"
            )

        return "\n".join(lines)

    def list_all_documents(self) -> List[str]:
        """Retorna lista de nombres de documentos descubiertos.

        Returns:
            Lista de nombres de archivo.
        """
        return list(self._scanned_files)

    # ── Internos ────────────────────────────────────────────────────────

    def _load_topic_map(self) -> Dict[str, str]:
        """Carga el mapeo topic→documento desde YAML."""
        path = self._config_path
        if not path.exists():
            logger.warning("Config YAML no encontrado en %s", path)
            return {}

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data.get("topic_to_doc", {})
        except Exception as exc:
            logger.warning("Error cargando YAML de %s: %s", path, exc)
            return {}

    def _process_files(self) -> None:
        """Procesa cada archivo: verifica hash, analiza, enriquece si cambió."""
        for filename in self._scanned_files:
            filepath = self._docs_dir / filename
            if not filepath.is_file():
                continue

            # Calcular hash actual
            current_hash = ContentAnalyzer.analyze(filepath).sha256

            if self._cache.has_changed(filename, current_hash):
                # Archivo nuevo o modificado → re-analizar
                result = ContentAnalyzer.analyze(filepath)
                entry = DocEntry(
                    filename=filename,
                    sha256=result.sha256,
                    sections=result.sections,
                )

                # Enriquecimiento LLM opcional (solo para docs no vacíos)
                if (
                    self._llm_client is not None
                    and result.sections
                    and any(s.body.strip() for s in result.sections)
                ):
                    summary = self._generate_llm_summary(filename, result.raw_text)
                    if summary:
                        entry.summary = summary

                self._cache.put(filename, entry)

    def _generate_llm_summary(self, filename: str, raw_text: str) -> str:
        """Genera un resumen narrativo del documento vía LLM.

        Args:
            filename: Nombre del archivo (para logging).
            raw_text: Contenido completo del documento.

        Returns:
            Resumen generado, o cadena vacía si falla.
        """
        if self._llm_client is None:
            return ""

        prompt = (
            "Genera un resumen en español de 2-3 oraciones del siguiente "
            "documento de restaurante. "
            "Devuelve SOLO un JSON con el campo 'summary'.\n\n"
            f"--- {filename} ---\n{raw_text}\n---"
        )

        try:
            result = asyncio.run(
                self._llm_client.extract_json(prompt=prompt)
            )
            if isinstance(result, dict):
                return result.get("summary", str(result))
            return str(result)
        except RuntimeError:
            logger.debug(
                "LLM enrichment skipped for %s: inside running event loop",
                filename,
            )
            return ""
        except Exception as exc:
            logger.warning("LLM enrichment failed for %s: %s", filename, exc)
            return ""

    def _format_entry_content(self, entry: DocEntry) -> str:
        """Formatea el contenido de una entrada de caché para el resumen."""
        parts = []
        for section in entry.sections:
            if section.heading:
                parts.append(f"[{section.heading}]")
            if section.body:
                # Truncar a 300 chars por sección para no saturar el prompt
                body = section.body[:300]
                parts.append(body)
        return " | ".join(parts) if parts else "Sin contenido"
