"""
ToolOrchestrator — gestiona el ciclo de function calling con el LLM.

Flujo:
  1. Enviar mensaje + tools al LLM
  2. Si responde con texto → fin
  3. Si responde con tool_calls → ejecutar cada una → append resultado
  4. Repetir hasta max_turns o hasta que el LLM responda texto
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Type

from src.core.tools.tool import Tool, ToolRegistry, ToolCall, ToolResult
from src.infrastructure.llm_client import LLMClient
from src.utils.utils import print_section

logger = logging.getLogger("ToolOrchestrator")


class ToolOrchestrator:
    """
    Orquesta el ciclo LLM ↔ tools.
    
    Args:
        llm_client: Cliente LLM que soporta el parámetro tools.
        registry: ToolRegistry con las herramientas disponibles.
        max_turns: Máximo de iteraciones LLM→tool→LLM.
        model: Modelo a usar (opcional, default del cliente).
        temperature: Temperatura para las llamadas LLM.
    """
    
    def __init__(
        self,
        llm_client: LLMClient,
        registry: ToolRegistry,
        max_turns: int = 5,
        model: Optional[str] = None,
        temperature: float = 0.1,
    ):
        self.llm_client = llm_client
        self.registry = registry
        self.max_turns = max_turns
        self.model = model
        self.temperature = temperature
    
    async def run(
        self,
        messages: List[Dict[str, str]],
        tool_choice: Optional[str] = "auto",
    ) -> Tuple[str, List[ToolCall]]:
        """
        Ejecuta el ciclo tool calling.
        
        Args:
            messages: Mensajes del conversation loop (system + user).
            tool_choice: "auto", "none", "required", o {"type":"function","function":{"name":"..."}}.
        
        Returns:
            (final_response_text, all_tool_calls_executed)
        """
        tools_list = self.registry.to_openai_list()
        all_tool_calls: List[ToolCall] = []
        
        if not tools_list:
            logger.warning("ToolOrchestrator sin tools registradas — llamada directa")
            response = await self.llm_client.chat_completion(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
            )
            return (response if isinstance(response, str) else str(response), [])
        
        for turn in range(self.max_turns):
            print_section(
                head=f"🔧 Tool turn {turn + 1}/{self.max_turns}",
                msg=f"tools disponibles: {len(tools_list)}",
                symbol="·",
            )
            
            # 1. Llamar al LLM con tools
            response = await self.llm_client.chat_completion(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
                tools=tools_list,
                tool_choice=tool_choice,
                tool_choice_required=tool_choice == "required",
            )
            
            # 2. Si la respuesta es string (texto plano) → fin del ciclo
            if isinstance(response, str):
                print_section(
                    head="✅ Tool cycle complete",
                    msg=f"respuesta en {turn + 1} turnos",
                    symbol="·",
                )
                return (response, all_tool_calls)
            
            # 3. Si es un dict con tool_calls → ejecutar
            if isinstance(response, dict) and "tool_calls" in response:
                tool_calls_data = response["tool_calls"]
                assistant_msg = response.get("assistant_message", "")
                
                # Agregar mensaje del asistente al historial
                # Incluir reasoning_content si la API lo devolvió (DeepSeek thinking mode)
                assistant_content = assistant_msg or None
                assistant_msg_dict: Dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"], ensure_ascii=False)
                            }
                        }
                        for tc in tool_calls_data
                    ]
                }
                reasoning_content = response.get("reasoning_content")
                if reasoning_content:
                    assistant_msg_dict["reasoning_content"] = reasoning_content
                messages.append(assistant_msg_dict)
                
                # Ejecutar cada tool
                for tc_data in tool_calls_data:
                    tool_call = ToolCall(
                        id=tc_data["id"],
                        name=tc_data["name"],
                        arguments=tc_data["arguments"],
                    )
                    all_tool_calls.append(tool_call)
                    
                    tool = self.registry.get(tool_call.name)
                    if not tool:
                        result = ToolResult(
                            success=False,
                            error=f"Tool '{tool_call.name}' no encontrada"
                        )
                    else:
                        print_section(
                            head=f"🛠️ Ejecutando {tool_call.name}",
                            msg=str(tool_call.arguments),
                            symbol="→",
                        )
                        result = await tool.execute(**tool_call.arguments)
                    
                    # Agregar resultado de la tool al historial
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result.to_content(),
                    })
                    
                    print_section(
                        head=f"📦 Resultado {tool_call.name}",
                        msg=result.to_content()[:150],
                        symbol="←",
                    )
                
                # tool_choice = "auto" después del primer turno
                tool_choice = "auto"
                continue
            
            # 4. Si no es ni string ni tool_calls, algo raro pasó
            logger.warning(f"ToolOrchestrator: respuesta inesperada del LLM: {type(response)}")
            return (str(response), all_tool_calls)
        
        # Si llegamos acá, se acabaron los turnos
        logger.warning(f"ToolOrchestrator: alcanzó max_turns={self.max_turns} sin respuesta final")
        return ("El asistente no pudo completar el razonamiento.", all_tool_calls)
