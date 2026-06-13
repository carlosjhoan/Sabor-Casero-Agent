"""
Tool — definición de herramientas para LLM function calling.

Cada Tool tiene un nombre, descripción, schema JSON de parámetros,
y un handler asíncrono que ejecuta la lógica (generalmente SPARQL).
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable


@dataclass
class ToolResult:
    """Resultado de la ejecución de una tool."""
    success: bool
    value: Any = None
    error: Optional[str] = None
    
    def to_content(self) -> str:
        """Convierte el resultado a texto para enviar de vuelta al LLM."""
        if not self.success:
            return json.dumps({"error": self.error}, ensure_ascii=False)
        if isinstance(self.value, str):
            return self.value
        return json.dumps(self.value, ensure_ascii=False, default=str)


@dataclass
class ToolCall:
    """Tool call emitida por el LLM (parsed)."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class Tool:
    """
    Herramienta invocable por el LLM vía function calling.
    
    Attributes:
        name: Nombre único de la tool (snake_case).
        description: Descripción para que el LLM entienda cuándo usarla.
        parameters: JSON Schema de los parámetros que recibe.
        handler: Función asíncrona que recibe **kwargs y retorna ToolResult.
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Awaitable[ToolResult]]
    strict: bool = False
    
    def to_openai_tool(self) -> Dict[str, Any]:
        """Convierte al formato que espera la API de OpenAI/DeepSeek."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
                "strict": self.strict,
            }
        }
    
    async def execute(self, **kwargs) -> ToolResult:
        """Ejecuta el handler con los argumentos dados."""
        try:
            return await self.handler(**kwargs)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ToolRegistry:
    """
    Registro de herramientas disponibles para una etapa del pipeline.
    
    Facilita armar el array `tools` que se pasa a la API,
    y resolver ejecuciones por nombre.
    """
    
    def __init__(self, tools: Optional[List[Tool]] = None):
        self._tools: Dict[str, Tool] = {}
        if tools:
            for tool in tools:
                self.register(tool)
    
    def register(self, tool: Tool) -> None:
        """Registra una herramienta."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' ya está registrada")
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> Optional[Tool]:
        """Obtiene una tool por nombre."""
        return self._tools.get(name)
    
    def to_openai_list(self) -> List[Dict[str, Any]]:
        """Lista de tools en formato OpenAI API."""
        return [t.to_openai_tool() for t in self._tools.values()]
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __iter__(self):
        return iter(self._tools.values())
