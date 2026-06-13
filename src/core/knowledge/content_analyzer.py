"""
Analizador de contenido para documentos de conocimiento.

Extrae secciones estructuradas de documentos markdown y texto plano
mediante regex, y computa SHA256 para detección de cambios.
"""
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class Section:
    """Una sección extraída de un documento."""
    heading: str = ""
    body: str = ""


@dataclass
class AnalysisResult:
    """Resultado completo del análisis de un documento."""
    sections: List[Section] = field(default_factory=list)
    sha256: str = ""
    raw_text: str = ""


class ContentAnalyzer:
    """Analizador de contenido estático. Sin estado, sin efectos secundarios.

    Extrae secciones mediante regex sobre headers markdown (##/###) o,
    como fallback, sobre líneas en mayúsculas que parecen títulos de sección.
    Si no encuentra ninguna estructura, retorna el documento completo como
    una sola sección sin heading.
    """

    HEADER_RE = re.compile(r'^#{2,3}\s+(.+)$', re.MULTILINE)
    UPPERCASE_RE = re.compile(
        r'^([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ\s/()]+):\s*$',
        re.MULTILINE,
    )

    @staticmethod
    def analyze(filepath: Path) -> AnalysisResult:
        """Analiza un documento y extrae secciones + SHA256.

        Args:
            filepath: Ruta al archivo a analizar.

        Returns:
            AnalysisResult con secciones extraídas, hash SHA256 y texto crudo.
        """
        raw_text = filepath.read_text(encoding="utf-8")
        sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        sections = ContentAnalyzer._extract_sections(raw_text)

        return AnalysisResult(sections=sections, sha256=sha256, raw_text=raw_text)

    @staticmethod
    def _extract_sections(raw_text: str) -> List[Section]:
        """Extrae secciones del texto probando estrategias en orden."""
        # Estrategia 1: headers markdown ## o ###
        md_matches = list(ContentAnalyzer.HEADER_RE.finditer(raw_text))
        if md_matches:
            return ContentAnalyzer._build_sections_from_matches(raw_text, md_matches)

        # Estrategia 2: líneas en mayúsculas con posible ':' al final
        uc_matches = list(ContentAnalyzer.UPPERCASE_RE.finditer(raw_text))
        if uc_matches:
            return ContentAnalyzer._build_sections_from_matches(raw_text, uc_matches)

        # Estrategia 3: sin estructura → una sola sección
        text = raw_text.strip()
        if not text:
            return []
        return [Section(heading="", body=text)]

    @staticmethod
    def _build_sections_from_matches(
        raw_text: str, matches: List[re.Match],
    ) -> List[Section]:
        """Construye secciones a partir de matches de regex."""
        sections: List[Section] = []

        # Contenido antes del primer header
        if matches[0].start() > 0:
            preamble = raw_text[:matches[0].start()].strip()
            if preamble:
                sections.append(Section(heading="", body=preamble))

        for i, match in enumerate(matches):
            heading = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
            body = raw_text[start:end].strip()
            sections.append(Section(heading=heading, body=body))

        return sections
