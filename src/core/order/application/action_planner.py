# # order/application/processors/action_planner.py

# import json
# from uuid import uuid4
# from typing import List, Dict, Any, Optional
# from src.utils.utils import print_section, build_prompt
# from src.config.environment import settings
# from src.infrastructure.llm_client import DeepSeekClient
# from src.core.order.domain.models import Order, OrderItem
# from src.core.order.domain.order_repository_interface import OrderRepository
# from src.core.order.domain.session_repository_interface import SessionRepository, SessionData


# class ActionPlanner:
#     """
#     Responsabilidad ÚNICA: Recibir un thought y convertirlo en acciones atómicas,
#     y luego ejecutar esas acciones usando los métodos CRUD.
    
#     NO genera pensamiento, solo ejecuta lo que el thought indica.
#     """
    
#     def __init__(self, order_repository: OrderRepository, session_repository: SessionRepository):
#         self.order_repository = order_repository
#         self.session_repository = session_repository
#         self.llm_client = DeepSeekClient(
#             api_key=settings.deepseek_api_key,
#             base_url=settings.deepseek_base_url
#         )
        
#         # Mapeo de operaciones a métodos
#         self.operations = {
#             "CREATE_ORDER": self._create_order,
#             "CREATE_ITEM": self._create_item,
#             "UPDATE_ITEM": self._update_item,
#             "DELETE_ITEM": self._delete_item
#         }
    
#     async def plan_and_execute(
#         self,
#         thought: str,
#         context: Dict[str, Any],
#         session_id: str,
#         summary_conversation: str
#     ) -> Dict[str, Any]:
#         """
#         Planifica y ejecuta acciones basadas en un thought.
        
#         Args:
#             thought: El razonamiento generado por ThoughtGenerator
#             context: Contexto de la orden (incluye order_id, summary, etc.)
#             session_id: ID de la sesión
            
#         Returns:
#             Dict con resultado de la planificación y ejecución
#         """
#         print_section(head="PLANIFICANDO ACCIONES DESDE THOUGHT", msg=thought[:200] + "...", symbol="🤖")
        
#         # 1. Extraer acciones del thought (aquí podrías usar un LLM ligero o reglas)
#         actions = await self._generate_actions(
#             thought=thought,
#             context=context,
#             summary_conversation=summary_conversation
#         )
        
#         # 2. Ejecutar acciones
#         if actions:
#             execution_result = await self._execute_actions(
#                 current_order_id=context.get("order_id"),
#                 actions=actions,
#                 session_id=session_id
#             )
#         else:
#             execution_result = {
#                 "executed": 0,
#                 "message": "No se pudieron extraer acciones del thought"
#             }
        
#         return {
#             "thought": thought,
#             "actions": actions,
#             "execution": execution_result
#         }
    
#     async def _generate_actions(
#         self,
#         thought: str,
#         context: Dict[str, Any],
#         summary_conversation: Optional[str] = None,
#         max_retries: int = 2
#     ) -> List[Dict[str, Any]]:
#         """
#         Genera acciones atómicas a partir de un thought usando el LLM.
        
#         Args:
#             thought: El razonamiento generado previamente
#             context: Contexto de la orden (incluye order_id, summary, etc.)
#             summary_conversation: Resumen de la conversación
#             max_retries: Número máximo de intentos
        
#         Returns:
#             List[Dict[str, Any]]: Lista de acciones a ejecutar
#         """
#         import asyncio

#         print_section(head="GENERANDO ACCIONES DESDE THOUGHT", msg=thought[:100] + "...", symbol="⚡")
        
#         last_error = None
        
#         for attempt in range(max_retries):
#             print(f"\n🔄 Intento {attempt + 1} de {max_retries} para generar acciones")
            
#             try:
#                 # Construir prompt específico para generación de acciones
#                 prompt = build_prompt(
#                     template_path=settings.action_planner_prompt_path,
#                     current_order_state=context.get("summary", "Resumen del pedido no disponible"),
#                     thought_text=thought,
#                     summary_conversation=summary_conversation
#                 )
                
#                 # Llamar a LLM con response_format JSON
#                 response = await self.llm_client.chat_completion(
#                     messages=[{"role": "system", "content": prompt}],
#                     temperature=min(0.05 + (attempt * 0.05), 0.2),  # Baja temperatura para precisión
#                     model="deepseek-chat",
#                     stream=False,
#                     response_format={"type": "json_object"}
#                 )
                
#                 # Parsear respuesta
#                 parse_result = self._parse_llm_response(response)
                
#                 if parse_result["success"]:
#                     actions = parse_result["actions"]
#                     print(f"✅ Acciones generadas exitosamente ({len(actions)} acciones)")
#                     return actions
#                 else:
#                     last_error = parse_result["error"]
#                     print(f"⚠️ Error en intento {attempt + 1}: {last_error}")
                    
#             except Exception as e:
#                 last_error = str(e)
#                 print(f"⚠️ Excepción en intento {attempt + 1}: {last_error}")
            
#             # Pequeña pausa antes de reintentar
#             if attempt < max_retries - 1:
#                 await asyncio.sleep(0.5)
        
#         # Si todos los intentos fallan, usar fallback basado en reglas
#         print("⚠️ Usando fallback basado en reglas para generar acciones")
#         return [] # Aquí se pueden implementar reglas simples para generar acciones mínimas si el LLM falla repetidamente


#     def _parse_llm_response(self, raw_response: str) -> Dict[str, Any]:
#         """
#         Parsea y valida la respuesta del LLM.
#         """
#         clean = raw_response.strip()
#         if clean.startswith("```json"):
#             clean = clean.split("```json")[1].split("```")[0].strip()
#         elif clean.startswith("```"):
#             clean = clean.split("```")[1].split("```")[0].strip()
        
#         try:
#             data = json.loads(clean)
#             actions = data.get("actions", [])
            
#             if isinstance(actions, list):
#                 return {
#                     "success": True,
#                     "actions": actions
#                 }
#             else:
#                 return {
#                     "success": False,
#                     "error": "actions debe ser lista"
#                 }
#         except json.JSONDecodeError:
#             return {
#                 "success": False,
#                 "error": "JSON inválido"
#             }
    
#     async def _execute_actions(
#         self,
#         actions: List[Dict],
#         session_id: str,
#         current_order_id: Optional[str] = None
#     ) -> Dict[str, Any]:
#         """
#         Ejecuta una lista de acciones atómicas (copy-paste de tu método original).
#         """
#         if not actions:
#             print("📭 No hay acciones para ejecutar")
#             return {
#                 "executed": 0,
#                 "final_order_id": current_order_id,
#                 "results": []
#             }
        
#         print("\n--- ACCIONES A EJECUTAR ---")
#         print(json.dumps(actions, indent=2, ensure_ascii=False))
        
#         results = []
#         order_id = current_order_id
        
#         for idx, action in enumerate(actions, 1):
#             operation = action.get("action")
#             params = action.get("params", {})
            
#             print(f"\n🔧 [{idx}/{len(actions)}] Ejecutando: {operation}")
            
#             try:
#                 result = await self._execute_single_action(
#                     operation=operation,
#                     params=params,
#                     inheritance=action.get("inheritance", {}),
#                     order_id=order_id,
#                     session_id=session_id
#                 )
                
#                 results.append(result)
                
#                 if operation == "CREATE_ORDER" and result.get("order_id"):
#                     order_id = result["order_id"]
#                     print(f"   ✅ Nueva orden creada: {order_id}")
                
#             except Exception as e:
#                 results.append({
#                     "action": operation,
#                     "success": False,
#                     "error": str(e),
#                     "params": params
#                 })
#                 print(f"   ❌ Error: {e}")
        
#         successful = sum(1 for r in results if r.get("success", False))
#         print(f"\n📊 Resumen: {successful}/{len(actions)} acciones ejecutadas correctamente")
        
#         return {
#             "executed": len(results),
#             "successful": successful,
#             "failed": len(results) - successful,
#             "final_order_id": order_id,
#             "results": results
#         }
    
#     async def _execute_single_action(
#         self,
#         operation: str,
#         params: Dict,
#         inheritance: Dict,
#         order_id: Optional[str],
#         session_id: str
#     ) -> Dict[str, Any]:
#         """Ejecuta una acción individual (copy-paste de tu método)"""
#         if operation == "CREATE_ORDER":
#             new_order_id = await self._create_order(session_id=session_id)
#             return {
#                 "action": operation,
#                 "success": True,
#                 "order_id": new_order_id,
#                 "params": params
#             }
        
#         if operation not in self.operations:
#             return {
#                 "action": operation,
#                 "success": False,
#                 "error": f"Operación desconocida: {operation}",
#                 "params": params
#             }
        
#         if not order_id:
#             return {
#                 "action": operation,
#                 "success": False,
#                 "error": "No hay order_id para ejecutar la acción",
#                 "params": params
#             }
        
#         try:
#             if operation == "CREATE_ITEM":
#                 await self.operations[operation](order_id, params, inheritance)
#             else:
#                 await self.operations[operation](order_id, params)
            
#             return {
#                 "action": operation,
#                 "success": True,
#                 "params": params,
#                 "order_id": order_id
#             }
#         except Exception as e:
#             return {
#                 "action": operation,
#                 "success": False,
#                 "error": str(e),
#                 "params": params,
#                 "order_id": order_id
#             }
    
#     # ========== MÉTODOS CRUD (igual que en tu original) ==========
    
#     async def _create_order(self, session_id: str = None) -> str:
#         """Crea una nueva orden"""
#         session = self.session_repository.get_session(session_id=session_id)
        
#         if session and session.customer_id:
#             new_order: Order = self.order_repository.create_order(customer_id=session.customer_id)
#         else:
#             new_order: Order = self.order_repository.create_order()
        
#         if new_order and session_id:
#             self.session_repository.link_session_to_order(
#                 session_id=session_id, 
#                 order_id=new_order.id
#             )
        
#         print_section(head="Nuevo order_id", msg=new_order.id)
#         return new_order.id
    
#     async def _create_item(self, order_id: str, params: dict, inheritance: dict = None) -> None:
#         """Crea un nuevo OrderItem"""
#         order = self.order_repository.get_order_by_id(order_id=order_id)
        
#         quantity = params.get("quantity", 1)
#         protein = params.get("protein")
#         principle = params.get("principle")
#         # sides = params.get("sides", ["Todo"])
#         size = params.get("size", "")
#         requirements = params.get("requirements", [])
        
#         # Lógica de herencia
#         if inheritance and inheritance.get("from_id"):
#             source_item = next(
#                 (item for item in order.items if item.id == inheritance["from_id"]), 
#                 None
#             )
#             if source_item:
#                 if not protein and "protein" in inheritance.get("fields", []):
#                     protein = source_item.protein
#                 # if not sides and "sides" in inheritance.get("fields", []):
#                 #     sides = source_item.sides
#                 if not requirements and "requirements" in inheritance.get("fields", []):
#                     requirements = source_item.requirements.copy()
#                 if not principle and "principle" in inheritance.get("fields", []):
#                     principle = source_item.principle
        
#         new_item = OrderItem(
#             id=f"item-{str(uuid4())[:8]}",
#             quantity=quantity,
#             protein=protein,
#             principle=principle,
#             # sides=sides,
#             size=size,
#             requirements=requirements
#         )
        
#         order.items.append(new_item)
#         self.order_repository.save_order(order=order)
        
#         print_section(head="✅ ITEM CREADO", msg=new_item.to_summary(), symbol=":: ")
    
#     async def _update_item(self, order_id: str, params: dict) -> None:
#         """Actualiza un OrderItem existente"""
#         order = self.order_repository.get_order_by_id(order_id=order_id)
#         item_id = params.get("item_id")
        
#         if not item_id:
#             print("❌ Error: No se proporcionó 'item_id' para actualizar.")
#             return
        
#         item = next((i for i in order.items if i.id == item_id), None)
#         if not item:
#             print(f"❌ Error: No se encontró el item con ID {item_id}")
#             return
        
#         if "quantity" in params:
#             item.quantity = params["quantity"]
#         if "protein" in params:
#             item.protein = params["protein"]
#         if "principle" in params:
#             item.principle = params["principle"]
#         # if "sides" in params:
#         #     item.sides = params["sides"]
#         if "size" in params:
#             item.size = params["size"]
#         if "add_requirements" in params:
#             for note in params["add_requirements"]:
#                 if note not in item.requirements:
#                     item.requirements.append(note)
#         if "remove_requirements" in params:
#             for note in params["remove_requirements"]:
#                 if note in item.requirements:
#                     item.requirements.remove(note)
            
        
#         self.order_repository.save_order(order=order)
#         print_section(head="✅ ITEM ACTUALIZADO", msg=item_id, symbol=":")
    
#     async def _delete_item(self, order_id: str, params: dict) -> None:
#         """Elimina un OrderItem"""
#         item_id = params.get("item_id")
#         if not item_id:
#             print("❌ Error: No se proporcionó 'item_id' para eliminar.")
#             return
        
#         order = self.order_repository.get_order_by_id(order_id=order_id)
#         item_index = next(
#             (index for index, i in enumerate(order.items) if i.id == item_id), 
#             None
#         )
        
#         if item_index is None:
#             print(f"❌ Error: No se encontró el item con ID {item_id}")
#             return
        
#         removed_item = order.items.pop(item_index)
#         self.order_repository.save_order(order=order)
        
#         print_section(head="✅ ITEM ELIMINADO", msg=removed_item.to_summary(), symbol=":: ")

# order/application/processors/action_planner.py

import json
from uuid import uuid4
from typing import List, Dict, Any, Optional
from src.utils.utils import print_section
from src.infrastructure.prompt_manager import get_prompt_manager
from src.infrastructure.llm_client import LLMClient, get_llm_client_for_stage, get_model_for_stage
from src.core.order.domain.models import Order, OrderItem
from src.core.order.domain.order_repository_interface import OrderRepository
from src.core.order.domain.session_repository_interface import SessionRepository


class ActionPlanner:
    """
    Responsabilidad ÚNICA: Recibir un thought y convertirlo en acciones atómicas,
    y luego aplicar esas acciones al agregado Order.
    
    NO genera pensamiento, solo ejecuta lo que el thought indica.
    El repositorio solo persiste el agregado completo.
    """
    
    def __init__(self, order_repository: OrderRepository, session_repository: SessionRepository, llm_client: LLMClient = None):
        self.order_repository = order_repository
        self.session_repository = session_repository
        if llm_client is None:
            from src.config.environment import settings
            llm_client = get_llm_client_for_stage("action_planner")
        self.llm_client = llm_client
    
    async def plan_and_execute(
        self,
        thought: str,
        context: Dict[str, Any],
        session_id: str,
        summary_conversation: str
    ) -> Dict[str, Any]:
        """
        Planifica y ejecuta acciones basadas en un thought.
        """
        print_section(head="PLANIFICANDO ACCIONES DESDE THOUGHT", msg=thought[:200] + "...", symbol="🤖")
        
        # 1. Extraer acciones del thought usando LLM
        actions = await self._generate_actions(
            thought=thought,
            context=context,
            summary_conversation=summary_conversation
        )
        
        # 2. Si no hay acciones, terminar
        if not actions:
            return {
                "thought": thought,
                "actions": [],
                "execution": {
                    "executed": 0,
                    "message": "No se pudieron extraer acciones del thought"
                }
            }
        
        # 3. APLICAR acciones al agregado Order
        execution_result = await self._apply_actions_to_aggregate(
            actions=actions,
            session_id=session_id,
            current_order_id=context.get("order_id")
        )
        
        return {
            "thought": thought,
            "actions": actions,
            "execution": execution_result
        }
    
    async def plan_actions(
        self,
        thought: str,
        context: Dict[str, Any],
        session_id: str,
        summary_conversation: str
    ) -> List[Dict[str, Any]]:
        """
        Genera acciones desde un thought SIN ejecutarlas.
        
        Útil para el flujo: generar → resolver ambigüedades → ejecutar.
        """
        return await self._generate_actions(
            thought=thought,
            context=context,
            summary_conversation=summary_conversation
        )

    async def execute_actions(
        self,
        actions: List[Dict],
        session_id: str,
        current_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Ejecuta acciones pre-generadas contra el agregado Order.
        
        Útil para el flujo: generar → resolver ambigüedades → ejecutar.
        """
        return await self._apply_actions_to_aggregate(
            actions=actions,
            session_id=session_id,
            current_order_id=current_order_id
        )

    async def _apply_actions_to_aggregate(
        self,
        actions: List[Dict],
        session_id: str,
        current_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        APLICA las acciones al agregado Order y guarda usando el repositorio.
        Esta es la parte CRÍTICA del cambio de arquitectura.
        """
        print("\n--- APLICANDO ACCIONES AL AGREGADO ORDER ---")
        print(json.dumps(actions, indent=2, ensure_ascii=False))
        
        results = []
        final_order_id = current_order_id
        current_order: Optional[Order] = None
        
        for idx, action in enumerate(actions, 1):
            print(f"\n🔧 [{idx}/{len(actions)}] Procesando: {action.get('action')}")
            
            try:
                result = await self._apply_single_action(
                    action=action,
                    session_id=session_id,
                    current_order=current_order,
                    current_order_id=final_order_id
                )
                
                results.append(result)
                
                # Actualizar estado para siguientes acciones
                if result.get("order"):
                    current_order = result["order"]
                    final_order_id = current_order.id
                
                if result.get("success"):
                    print(f"   ✅ {result.get('message', 'OK')}")
                else:
                    print(f"   ⚠️ {result.get('message', 'Falló')}")
                
            except Exception as e:
                results.append({
                    "action": action.get("action"),
                    "success": False,
                    "error": str(e)
                })
                print(f"   ❌ Error: {e}")
        
        # Si todo fue exitoso, guardar la orden final
        final_save_result = None
        if current_order:
            try:
                self.order_repository.save_order(current_order)
                final_save_result = {
                    "success": True,
                    "order_id": current_order.id,
                    "message": "Orden guardada exitosamente"
                }
                print(f"\n💾 Orden {current_order.id} guardada en repositorio")
            except Exception as e:
                final_save_result = {
                    "success": False,
                    "error": str(e),
                    "message": "Error guardando orden"
                }
                print(f"❌ Error guardando orden: {e}")
        
        return {
            "actions_processed": len(results),
            "successful": sum(1 for r in results if r.get("success", False)),
            "failed": sum(1 for r in results if not r.get("success", False)),
            "final_order_id": final_order_id,
            "results": results,
            "save_result": final_save_result
        }
    
    async def _apply_single_action(
        self,
        action: Dict,
        session_id: str,
        current_order: Optional[Order],
        current_order_id: Optional[str]
    ) -> Dict[str, Any]:
        """
        Aplica UNA acción al agregado Order.
        NO llama al repositorio, solo modifica el objeto en memoria.
        """
        op = action.get("action")
        params = action.get("params", {})
        inheritance = action.get("inheritance", {})
        
        # CASO 1: CREATE_ORDER - Crear nueva orden
        if op == "CREATE_ORDER":
            session = self.session_repository.get_session(session_id=session_id)
            customer_id = session.customer_id if session else None
            
            new_order = Order(customer_id=customer_id)
            if session_id:
                self.session_repository.link_session_to_order(
                    session_id=session_id,
                    order_id=new_order.id
                )
            
            return {
                "action": op,
                "success": True,
                "order": new_order,
                "order_id": new_order.id,
                "message": f"Orden {new_order.id} creada"
            }
        
        # Para el resto de operaciones, necesitamos la orden actual
        if not current_order and current_order_id:
            current_order = self.order_repository.get_order_by_id(current_order_id)
        
        if not current_order:
            return {
                "action": op,
                "success": False,
                "message": "No hay orden activa para aplicar la acción"
            }
        
        # CASO 2: CREATE_ITEM
        if op == "CREATE_ITEM":
            new_item = self._create_item_from_params(params, inheritance, current_order)
            current_order.add_item(new_item)
            
            return {
                "action": op,
                "success": True,
                "order": current_order,
                "item_id": new_item.id,
                "message": f"Item {new_item.id} creado: {new_item.to_summary()}"
            }
        
        # CASO 3: UPDATE_ITEM
        if op == "UPDATE_ITEM":
            item_id = params.get("item_id")
            if not item_id:
                return {"action": op, "success": False, "message": "Falta item_id"}
            
            # Extraer cambios (sin item_id)
            changes = {k: v for k, v in params.items() if k != "item_id"}
            current_order.update_item(item_id, **changes)
            
            return {
                "action": op,
                "success": True,
                "order": current_order,
                "item_id": item_id,
                "message": f"Item {item_id} actualizado"
            }
        
        # CASO 4: DELETE_ITEM
        if op == "DELETE_ITEM":
            item_id = params.get("item_id")
            if not item_id:
                return {"action": op, "success": False, "message": "Falta item_id"}
            
            removed = current_order.remove_item(item_id)
            
            return {
                "action": op,
                "success": True,
                "order": current_order,
                "item_id": item_id,
                "message": f"Item {item_id} eliminado: {removed.to_summary() if removed else 'desconocido'}"
            }
        
        # CASO 5: UPDATE_ORDER - Actualizar metadatos del pedido
        if op == "UPDATE_ORDER":
            current_order.update_order_metadata(**params)
            
            return {
                "action": op,
                "success": True,
                "order": current_order,
                "message": f"Metadatos de orden {current_order.id} actualizados"
            }
        
        return {
            "action": op,
            "success": False,
            "message": f"Operación desconocida: {op}"
        }
    
    def _create_item_from_params(self, params: Dict, inheritance: Dict, order: Order) -> OrderItem:
        """
        Crea un OrderItem a partir de parámetros, con lógica de herencia.
        
        Args:
            params: Parámetros de la acción (quantity, protein, size, etc.)
            inheritance: Datos heredados de otro item
            order: Orden actual
        """
        quantity = params.get("quantity", 1)
        protein = params.get("protein")
        principle = params.get("principle")
        size = params.get("size", "")
        requirements = params.get("requirements", [])
        
        unit_price = 0.0
        if params.get("unit_price") is not None:
            unit_price = float(params["unit_price"])
        
        # Lógica de herencia
        if inheritance and inheritance.get("from_id"):
            source_item = next(
                (item for item in order.items if item.id == inheritance["from_id"]),
                None
            )
            if source_item:
                if not protein and "protein" in inheritance.get("fields", []):
                    protein = source_item.protein
                if not requirements and "requirements" in inheritance.get("fields", []):
                    requirements = source_item.requirements.copy()
                if not principle and "principle" in inheritance.get("fields", []):
                    principle = source_item.principle
                if not size and "size" in inheritance.get("fields", []):
                    size = source_item.size
                if not unit_price and "unit_price" in inheritance.get("fields", []):
                    unit_price = source_item.unit_price
        
        return OrderItem(
            id=f"item-{str(uuid4())[:8]}",
            quantity=quantity,
            protein=protein,
            principle=principle,
            size=size,
            unit_price=unit_price,
            requirements=requirements or ["Con todo"]
        )
    
    async def _generate_actions(
        self,
        thought: str,
        context: Dict[str, Any],
        summary_conversation: Optional[str] = None,
        max_retries: int = 2
    ) -> List[Dict[str, Any]]:
        """
        [DEPRECATED] — Use synthetic order tools (add-item, remove-item, update-item,
        get-order, confirm-order, cancel-order) via SkillToolAdapter when
        use_llm_planner=True. Kept for legacy pipeline (use_llm_planner=False).

        Genera acciones atómicas a partir de un thought usando el LLM.
        (Este método se queda IGUAL, solo llama al LLM)
        """
        import asyncio
        from src.config.environment import settings

        print_section(head="GENERANDO ACCIONES DESDE THOUGHT", msg=thought[:100] + "...", symbol="⚡")
        
        last_error = None
        
        for attempt in range(max_retries):
            print(f"\n🔄 Intento {attempt + 1} de {max_retries} para generar acciones")
            
            try:
                prompt = get_prompt_manager(settings.prompt_fallback_map).get(
                    "action-planner",
                    current_order_state=context.get("summary", "Resumen del pedido no disponible"),
                    thought_text=thought,
                    summary_conversation=summary_conversation
                )
                
                response = await self.llm_client.chat_completion(
                    messages=[{"role": "system", "content": prompt}],
                    temperature=min(0.05 + (attempt * 0.05), 0.2),
                    model=get_model_for_stage("action_planner", settings),
                    stream=False,
                    response_format={"type": "json_object"}
                )
                
                parse_result = self._parse_llm_response(response)
                
                if parse_result["success"]:
                    actions = parse_result["actions"]
                    print(f"✅ Acciones generadas exitosamente ({len(actions)} acciones)")
                    return actions
                else:
                    last_error = parse_result["error"]
                    print(f"⚠️ Error en intento {attempt + 1}: {last_error}")
                    
            except Exception as e:
                last_error = str(e)
                print(f"⚠️ Excepción en intento {attempt + 1}: {last_error}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
        
        print("⚠️ Usando fallback basado en reglas para generar acciones")
        return []

    def _parse_llm_response(self, raw_response: str) -> Dict[str, Any]:
        """Parsea respuesta del LLM (igual que antes)"""
        clean = raw_response.strip()
        if clean.startswith("```json"):
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif clean.startswith("```"):
            clean = clean.split("```")[1].split("```")[0].strip()
        
        try:
            data = json.loads(clean)
            actions = data.get("actions", [])
            
            if isinstance(actions, list):
                return {"success": True, "actions": actions}
            else:
                return {"success": False, "error": "actions debe ser lista"}
        except json.JSONDecodeError:
            return {"success": False, "error": "JSON inválido"}