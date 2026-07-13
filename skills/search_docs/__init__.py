"""
search-docs skill — document-scoped semantic search.

Wraps HybridRetriever._get_context() with a source filter
for targeted document retrieval. Zero new retrieval code.
"""
from typing import Any

from src.engine.skill_base import BaseSkill
from src.engine.stage_result import SkillResult


class Skill(BaseSkill):
    """Document-scoped semantic search skill."""
    name = "search-docs"
    version = "0.1.0"

    def load(self, context: Any) -> None:
        """Store reference to retriever from orchestration context."""
        self._retriever = context.get("retriever") if context else None

    async def run(self, input_data: Any) -> SkillResult:
        """Search a specific document by name.

        Input::
            {
                "query": str,     # User's search query
                "doc_name": str,  # Target document filename
            }

        Returns::
            {
                "result": str,       # Top-3 chunks joined by newlines
                "chunks_found": int, # Number of matching chunks
                "summary": str,      # One-liner for streamer display
            }
        """
        try:
            query = input_data.get("query", "")
            doc_name = input_data.get("doc_name", "")

            if not query or not doc_name:
                return SkillResult.ok(
                    value={
                        "result": "",
                        "chunks_found": 0,
                        "summary": "Faltan parámetros: query y doc_name son requeridos",
                    },
                    skill_name=self.name,
                    skill_version=self.version,
                )

            if self._retriever is None:
                return SkillResult.fail(
                    skill_name=self.name,
                    skill_version=self.version,
                    error="Retriever not available in context",
                )

            # Reuse get_context with existing source filter
            # ponytail: get_context already supports where={"source": doc_name}
            result_text = await self._retriever.get_context(query, doc_name)

            if not result_text or not result_text.strip():
                return SkillResult.ok(
                    value={
                        "result": "",
                        "chunks_found": 0,
                        "summary": f"No se encontró información en {doc_name}",
                    },
                    skill_name=self.name,
                    skill_version=self.version,
                )

            chunks = result_text.split("\n---\n")
            return SkillResult.ok(
                value={
                    "result": result_text,
                    "chunks_found": len(chunks),
                    "summary": f"{len(chunks)} fragmentos encontrados en {doc_name}",
                },
                skill_name=self.name,
                skill_version=self.version,
            )

        except Exception as e:
            return SkillResult.fail(
                skill_name=self.name,
                skill_version=self.version,
                error=e,
            )

    def unload(self) -> None:
        self._retriever = None
