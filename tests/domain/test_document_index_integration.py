"""
Tests de integración para el pipeline DocumentRegistry + ContentAnalyzer
+ DocumentCache + LLM enrichment.

Usa tmp_path para aislar el sistema de archivos y mock_llm_client
para verificar enriquecimiento condicional.
"""
from pathlib import Path
from unittest.mock import AsyncMock

import yaml

from src.core.knowledge.registry import DocumentRegistry
from src.core.classifier.intent import QueryTopic


class TestDocumentIndexIntegration:
    """Integración completa del pipeline de indexación."""

    def _setup_docs(self, docs_dir: Path, files: dict[str, str]) -> None:
        """Crea archivos de documento en el directorio."""
        docs_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (docs_dir / name).write_text(content, encoding="utf-8")

    def _setup_config(self, config_dir: Path, mapping: dict[str, str]) -> Path:
        """Crea archivo YAML de mapeo topic→documento."""
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "topic_document_map.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump({"topic_to_doc": mapping}, f)
        return config_file

    def _make_cache_path(self, tmp_path: Path) -> Path:
        """Crea directorio cache y retorna ruta al archivo."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "document_cache.json"

    # ── Pruebas ─────────────────────────────────────────────────────────

    def test_new_file_appears_in_summaries(self, tmp_path: Path):
        """Archivo nuevo aparece en get_all_summaries."""
        docs = tmp_path / "docs"
        self._setup_docs(docs, {"menu.md": "## PLATOS\nPollo asado"})
        config_file = self._setup_config(tmp_path / "cfg", {"menu": "menu.md"})
        cache_file = self._make_cache_path(tmp_path)

        registry = DocumentRegistry(
            docs_dir=str(docs),
            cache_path=str(cache_file),
            config_path=str(config_file),
        )
        summaries = registry.get_all_summaries()
        assert "menu.md" in summaries
        assert "PLATOS" in summaries

    def test_deleted_file_excluded(self, tmp_path: Path):
        """Archivo eliminado no aparece tras recrear el registro."""
        docs = tmp_path / "docs"
        self._setup_docs(docs, {"keep.md": "Contenido", "remove.md": "Eliminado"})
        config_file = self._setup_config(
            tmp_path / "cfg", {"keep": "keep.md", "remove": "remove.md"}
        )
        cache_file = self._make_cache_path(tmp_path)

        # Primera pasada: ambos archivos existen
        r1 = DocumentRegistry(
            docs_dir=str(docs), cache_path=str(cache_file), config_path=str(config_file),
        )
        assert "remove.md" in r1.list_all_documents()

        # Eliminar archivo y recrear
        (docs / "remove.md").unlink()
        r2 = DocumentRegistry(
            docs_dir=str(docs), cache_path=str(cache_file), config_path=str(config_file),
        )
        assert "remove.md" not in r2.list_all_documents()
        assert "keep.md" in r2.list_all_documents()

    def test_llm_fires_only_for_changed_docs(self, tmp_path: Path):
        """LLM enrichment se dispara solo para documentos nuevos/modificados."""
        docs = tmp_path / "docs"
        self._setup_docs(docs, {
            "stable.md": "## SECCION\nContenido estable",
            "changing.md": "## SECCION\nVersión 1",
        })
        config_file = self._setup_config(
            tmp_path / "cfg", {"stable": "stable.md", "changing": "changing.md"}
        )
        cache_file = self._make_cache_path(tmp_path)

        # Mock LLM que devuelve resúmenes
        mock_llm = AsyncMock()
        mock_llm.extract_json.return_value = {"summary": "Resumen generado por LLM"}

        # Primera inicialización: ambos docs son nuevos → LLM llamado 2 veces
        r1 = DocumentRegistry(
            docs_dir=str(docs),
            cache_path=str(cache_file),
            config_path=str(config_file),
            llm_client=mock_llm,
        )

        # Verificar que el LLM fue llamado
        assert mock_llm.extract_json.call_count > 0
        summaries_1 = r1.get_all_summaries()
        assert "stable.md" in summaries_1
        assert "changing.md" in summaries_1

        # Reset mock y cambiar solo un documento
        mock_llm.extract_json.reset_mock()
        (docs / "changing.md").write_text("## SECCION\nVersión 2", encoding="utf-8")

        # Segunda inicialización: solo changing.md cambió → 1 llamada LLM
        r2 = DocumentRegistry(
            docs_dir=str(docs),
            cache_path=str(cache_file),
            config_path=str(config_file),
            llm_client=mock_llm,
        )

        # El LLM debió llamarse solo una vez (para changing.md)
        assert mock_llm.extract_json.call_count == 1
        summaries_2 = r2.get_all_summaries()
        assert "Versión 2" in summaries_2

    def test_empty_doc_skips_llm(self, tmp_path: Path):
        """Documento vacío no dispara llamada LLM."""
        docs = tmp_path / "docs"
        self._setup_docs(docs, {"empty.md": ""})
        config_file = self._setup_config(tmp_path / "cfg", {"empty": "empty.md"})
        cache_file = self._make_cache_path(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.extract_json.return_value = {"summary": "should not be called"}

        registry = DocumentRegistry(
            docs_dir=str(docs),
            cache_path=str(cache_file),
            config_path=str(config_file),
            llm_client=mock_llm,
        )
        # LLM no debe haber sido llamado para documento vacío
        assert mock_llm.extract_json.call_count == 0
        summaries = registry.get_all_summaries()
        assert "empty.md" in summaries

    def test_registry_works_without_llm(self, tmp_path: Path):
        """Registry funciona sin LLM (solo análisis estructural)."""
        docs = tmp_path / "docs"
        self._setup_docs(docs, {"test.md": "## TITULO\nContenido de prueba"})
        config_file = self._setup_config(tmp_path / "cfg", {"test": "test.md"})
        cache_file = self._make_cache_path(tmp_path)

        registry = DocumentRegistry(
            docs_dir=str(docs),
            cache_path=str(cache_file),
            config_path=str(config_file),
            # Sin llm_client
        )
        assert registry.get_doc_for_topic(QueryTopic.UNKNOWN) == "no-file"
        assert "test.md" in registry.get_all_summaries()

    def test_cache_invalidated_on_content_change(self, tmp_path: Path):
        """La caché se invalida cuando el contenido cambia entre instancias."""
        docs = tmp_path / "docs"
        self._setup_docs(docs, {"data.txt": "Versión original"})
        config_file = self._setup_config(tmp_path / "cfg", {"data": "data.txt"})
        cache_file = self._make_cache_path(tmp_path)

        r1 = DocumentRegistry(
            docs_dir=str(docs), cache_path=str(cache_file), config_path=str(config_file),
        )
        original_hash = r1._cache.get("data.txt").sha256

        # Modificar el archivo
        (docs / "data.txt").write_text("Versión modificada", encoding="utf-8")

        r2 = DocumentRegistry(
            docs_dir=str(docs), cache_path=str(cache_file), config_path=str(config_file),
        )
        new_hash = r2._cache.get("data.txt").sha256
        assert new_hash != original_hash
