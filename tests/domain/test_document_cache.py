"""
Tests para DocumentCache — persistencia JSON con escritura atómica,
detección de cambios vía SHA256 y recuperación ante corrupción.
"""
import json
import os
from pathlib import Path

from src.core.knowledge.document_cache import DocumentCache, DocEntry
from src.core.knowledge.content_analyzer import Section


class TestDocumentCache:
    """Pruebas unitarias para DocumentCache."""

    def test_put_and_get(self, tmp_path: Path):
        """Guardar y recuperar una entrada."""
        cache = DocumentCache(tmp_path / "cache.json")
        entry = DocEntry(
            filename="test.md",
            sha256="abc123",
            sections=[Section(heading="H1", body="Body")],
            summary="Test summary",
            last_updated="2025-01-01T00:00:00",
        )
        cache.put("test.md", entry)
        retrieved = cache.get("test.md")
        assert retrieved is not None
        assert retrieved.filename == "test.md"
        assert retrieved.sha256 == "abc123"
        assert len(retrieved.sections) == 1
        assert retrieved.sections[0].heading == "H1"
        assert retrieved.summary == "Test summary"

    def test_get_nonexistent(self, tmp_path: Path):
        """Obtener entrada inexistente retorna None."""
        cache = DocumentCache(tmp_path / "cache.json")
        assert cache.get("missing.md") is None

    def test_has_changed_no_entry(self, tmp_path: Path):
        """Sin entrada previa, has_changed es True."""
        cache = DocumentCache(tmp_path / "cache.json")
        assert cache.has_changed("new.md", "abc123") is True

    def test_has_changed_match(self, tmp_path: Path):
        """Hash coincide → no changed."""
        cache = DocumentCache(tmp_path / "cache.json")
        entry = DocEntry(filename="same.md", sha256="match123", sections=[])
        cache.put("same.md", entry)
        assert cache.has_changed("same.md", "match123") is False

    def test_has_changed_mismatch(self, tmp_path: Path):
        """Hash distinto → changed."""
        cache = DocumentCache(tmp_path / "cache.json")
        entry = DocEntry(filename="changed.md", sha256="oldhash", sections=[])
        cache.put("changed.md", entry)
        assert cache.has_changed("changed.md", "newhash") is True

    def test_rebuild_if_corrupt(self, tmp_path: Path):
        """JSON corrupto → warning y estado limpio."""
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{corrupt json!!!", encoding="utf-8")
        cache = DocumentCache(cache_file)
        # Estado interno debe estar limpio
        assert cache.get("anything") is None

    def test_atomic_write_survives_crash(self, tmp_path: Path):
        """Escritura atómica: .tmp no queda tras operación exitosa."""
        cache_file = tmp_path / "cache.json"
        cache = DocumentCache(cache_file)
        entry = DocEntry(filename="test.md", sha256="abc", sections=[])
        cache.put("test.md", entry)

        # El archivo real existe y .tmp fue limpiado
        assert cache_file.exists()
        tmp_file = cache_file.with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_cache_persistence_across_instances(self, tmp_path: Path):
        """Datos persisten entre instancias de cache."""
        cache_file = tmp_path / "cache.json"
        cache1 = DocumentCache(cache_file)
        cache1.put("persist.md", DocEntry(filename="persist.md", sha256="xyz", sections=[]))

        cache2 = DocumentCache(cache_file)
        retrieved = cache2.get("persist.md")
        assert retrieved is not None
        assert retrieved.filename == "persist.md"
        assert retrieved.sha256 == "xyz"

    def test_multiple_entries(self, tmp_path: Path):
        """Múltiples entradas se guardan y recuperan."""
        cache = DocumentCache(tmp_path / "cache.json")
        entries = [
            DocEntry(filename=f"doc{i}.md", sha256=f"hash{i}", sections=[]) for i in range(3)
        ]
        for e in entries:
            cache.put(e.filename, e)
        for e in entries:
            retrieved = cache.get(e.filename)
            assert retrieved is not None
            assert retrieved.sha256 == e.sha256

    def test_no_cache_file_on_startup(self, tmp_path: Path):
        """Sin archivo de cache previo, arranque limpio."""
        cache_file = tmp_path / "nonexistent" / "cache.json"
        cache = DocumentCache(cache_file)
        assert cache.get("any.md") is None
