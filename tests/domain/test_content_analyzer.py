"""
Tests para ContentAnalyzer — extracción de secciones y hashing SHA256.

Cubre los 4 documentos reales, archivo vacío, fallback a texto plano,
y estabilidad del hash.
"""
import hashlib
from pathlib import Path

from src.core.knowledge.content_analyzer import ContentAnalyzer, Section, AnalysisResult


class TestContentAnalyzer:
    """Pruebas unitarias para ContentAnalyzer.analyze()."""

    def test_menu_headers_extracted(self, docs_dir: Path):
        """menu.md tiene headers ## → se extraen secciones con heading."""
        result = ContentAnalyzer.analyze(docs_dir / "menu.md")
        assert len(result.sections) > 5
        headings = [s.heading for s in result.sections]
        assert "METADATA" in headings
        assert "SECTION: Proteínas" in headings
        assert "CONTACT" in headings

    def test_menu_non_empty_sections_have_body(self, docs_dir: Path):
        """Las secciones con heading de menu.md que no son adyacentes tienen body."""
        result = ContentAnalyzer.analyze(docs_dir / "menu.md")
        sections_with_body = [s for s in result.sections if s.heading and s.body]
        # Al menos las secciones principales tienen contenido
        assert any("Crema de verdura" in s.body for s in sections_with_body)
        assert any("Pechuga" in s.body for s in sections_with_body)

    def test_service_info_uppercase_headers(self, docs_dir: Path):
        """service_info.txt no tiene ## → usa UPPERCASE_RE o fallback."""
        result = ContentAnalyzer.analyze(docs_dir / "service_info.txt")
        assert len(result.sections) >= 1
        # Al menos debe tener contenido
        total_body = sum(len(s.body) for s in result.sections)
        assert total_body > 0

    def test_waiter_guide_single_section(self, docs_dir: Path):
        """waiter_guide.txt sin headers → una sola sección sin heading."""
        result = ContentAnalyzer.analyze(docs_dir / "waiter_guide.txt")
        assert len(result.sections) == 1
        assert result.sections[0].heading == ""
        assert len(result.sections[0].body) > 0

    def test_about_us_single_section(self, docs_dir: Path):
        """about_us.txt sin headers → una sola sección sin heading."""
        result = ContentAnalyzer.analyze(docs_dir / "about_us.txt")
        assert len(result.sections) == 1
        assert result.sections[0].heading == ""
        assert "Sabor casero fue fundado" in result.sections[0].body

    def test_empty_file(self, tmp_path: Path):
        """Archivo vacío → sections vacío, SHA256 del contenido vacío."""
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        result = ContentAnalyzer.analyze(empty)
        assert len(result.sections) == 0
        assert result.sha256 == hashlib.sha256(b"").hexdigest()

    def test_sha256_stability(self, docs_dir: Path):
        """Mismo contenido produce mismo SHA256 en llamadas repetidas."""
        result1 = ContentAnalyzer.analyze(docs_dir / "menu.md")
        result2 = ContentAnalyzer.analyze(docs_dir / "menu.md")
        assert result1.sha256 == result2.sha256

    def test_raw_text_preserved(self, docs_dir: Path):
        """raw_text contiene el contenido completo del archivo."""
        filepath = docs_dir / "about_us.txt"
        result = ContentAnalyzer.analyze(filepath)
        expected = filepath.read_text(encoding="utf-8")
        assert result.raw_text == expected

    def test_analysis_result_types(self, docs_dir: Path):
        """AnalysisResult tiene los campos esperados con tipos correctos."""
        result = ContentAnalyzer.analyze(docs_dir / "menu.md")
        assert isinstance(result.sections, list)
        assert isinstance(result.sha256, str)
        assert isinstance(result.raw_text, str)
        assert len(result.sha256) == 64  # SHA256 hex string

    def test_section_dataclass(self):
        """Section se construye correctamente."""
        s = Section(heading="Test", body="Contenido")
        assert s.heading == "Test"
        assert s.body == "Contenido"
