"""
Domain model tests for DocumentRegistry from knowledge/registry.py.
"""
from pathlib import Path
import yaml

from src.core.knowledge.registry import DocumentRegistry
from src.core.classifier.intent import QueryTopic


class TestDocumentRegistry:
    """Pruebas para DocumentRegistry con descubrimiento dinámico."""

    def test_get_doc_for_topic(self):
        """Topic conocido retorna nombre de archivo correcto."""
        registry = DocumentRegistry()
        assert registry.get_doc_for_topic(QueryTopic.MENU) == "menu.md"
        assert registry.get_doc_for_topic(QueryTopic.DELIVERY) == "service_info.txt"
        assert registry.get_doc_for_topic(QueryTopic.ABOUT) == "about_us.txt"
        assert registry.get_doc_for_topic(QueryTopic.CUTLERY_REQUEST) == "waiter_guide.txt"

    def test_get_doc_for_topic_greeting(self):
        """GREETING/FAREWELL retorna 'no-file'."""
        registry = DocumentRegistry()
        assert registry.get_doc_for_topic(QueryTopic.GREETING) == "no-file"
        assert registry.get_doc_for_topic(QueryTopic.FAREWELL) == "no-file"

    def test_get_doc_for_topic_unknown(self):
        """Topic desconocido retorna 'no-file'."""
        registry = DocumentRegistry()
        assert registry.get_doc_for_topic(QueryTopic.UNKNOWN) == "no-file"

    def test_get_all_summaries_format(self):
        """get_all_summaries() retorna formato estructurado."""
        registry = DocumentRegistry()
        summaries = registry.get_all_summaries()
        # Formato: - Document: {name}\n  Topics: [...]\n  Content: ...
        assert "- Document:" in summaries
        assert "Topics:" in summaries
        assert "Content:" in summaries
        # Cada documento conocido aparece
        assert "menu.md" in summaries
        assert "service_info.txt" in summaries
        assert "waiter_guide.txt" in summaries
        assert "about_us.txt" in summaries

    def test_list_all_documents(self):
        """list_all_documents() retorna los nombres de archivo escaneados."""
        registry = DocumentRegistry()
        docs = registry.list_all_documents()
        assert "menu.md" in docs
        assert "service_info.txt" in docs
        assert "waiter_guide.txt" in docs
        assert "about_us.txt" in docs

    def test_registry_with_tmp_path(self, tmp_path: Path):
        """Registry funciona con directorio de docs temporal + YAML."""
        # Crear docs temporales
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir()
        (docs_dir / "test_menu.md").write_text("## PLATOS\nPollo asado", encoding="utf-8")
        (docs_dir / "test_info.txt").write_text("Información general", encoding="utf-8")

        # Crear YAML temporal
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        yaml_data = {"topic_to_doc": {"menu": "test_menu.md", "general": "test_info.txt"}}
        config_file = config_dir / "topic_document_map.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f)

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_file = cache_dir / "document_cache.json"

        registry = DocumentRegistry(
            docs_dir=str(docs_dir),
            cache_path=str(cache_file),
            config_path=str(config_file),
        )

        assert registry.get_doc_for_topic(QueryTopic.MENU) == "test_menu.md"
        assert "test_menu.md" in registry.get_all_summaries()
        assert "test_info.txt" in registry.list_all_documents()

    def test_yaml_entry_missing_file_logs_warning(self, tmp_path: Path, caplog):
        """Entrada YAML que apunta a archivo inexistente → warning."""
        import logging
        caplog.set_level(logging.WARNING)

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "real.md").write_text("real content", encoding="utf-8")

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        yaml_data = {"topic_to_doc": {"menu": "real.md", "about": "missing.md"}}
        config_file = config_dir / "topic_document_map.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f)

        cache_file = tmp_path / "cache.json"
        registry = DocumentRegistry(
            docs_dir=str(docs_dir),
            cache_path=str(cache_file),
            config_path=str(config_file),
        )

        # missing.md no está en disco, get_doc_for_topic debe retornar no-file
        assert registry.get_doc_for_topic(QueryTopic.ABOUT) == "no-file"
        # real.md sí existe y está mapeado
        assert registry.get_doc_for_topic(QueryTopic.MENU) == "real.md"

    def test_unmapped_doc_appears_as_unmapped(self, tmp_path: Path):
        """Documento sin entrada en YAML aparece como [UNMAPPED]."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "orphan.txt").write_text("sin mapeo", encoding="utf-8")

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        yaml_data = {"topic_to_doc": {}}
        config_file = config_dir / "topic_document_map.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f)

        cache_file = tmp_path / "cache.json"
        registry = DocumentRegistry(
            docs_dir=str(docs_dir),
            cache_path=str(cache_file),
            config_path=str(config_file),
        )

        summaries = registry.get_all_summaries()
        assert "orphan.txt" in summaries
        assert "UNMAPPED" in summaries
        assert registry.get_doc_for_topic(QueryTopic.UNKNOWN) == "no-file"
