import json
from uuid import uuid4
from src.core.classifier.intent import  Detail
from src.utils.utils import print_section
from src.utils.utils import build_prompt
from src.infrastructure.prompt_manager import get_prompt_manager
from src.infrastructure.llm_client import LLMClient, get_llm_client_for_stage, get_model_for_stage
from typing import List, Dict, Any, Optional
from src.core.order.domain.models import Order, OrderItem
from src.core.order.domain.order_repository_interface import OrderRepository
from src.core.order.domain.session_repository_interface import SessionRepository, SessionData



class OrderProcessor:
    def __init__(self, order_repository: OrderRepository, session_repository:SessionRepository, llm_client: LLMClient = None ):
        if llm_client is None:
            from src.config.environment import settings
            llm_client = get_llm_client_for_stage("action_planner")
        self.llm_client = llm_client
        self.test_file = "data/orders/order_state_test_v1.1.json"
        self.operations = {
            "CREATE_ITEM": self._create_item,
            "UPDATE_ITEM": self._update_item,
            "DELETE_ITEM": self._delete_item,
            "CREATE_ORDER" : self._initialize_and_save_order
        }
        self.order_repository = order_repository
        self.session_repository = session_repository
        self.max_retries = 2
    
    async def process_order_intent(
        self,
        ordering_segments: List[Detail],
        session_id: str,
        summary_conversation: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Método principal: procesa intención de orden.
        Coordina todo el flujo con separación de responsabilidades.
        """
        try:
            # 1. OBTENER CONTEXTO
            context = await self._load_order_context(session_id)
            
            # 2. PREPARAR INPUT
            processor_input = self._prepare_processor_input(ordering_segments)
            
            # 3. FLUJO PRINCIPAL (con reintentos)
            result = await self._main_flow_with_retry(
                context=context,
                processor_input=processor_input,
                summary_conversation=summary_conversation
            )
            
            # 4. Si falló el flujo principal, activar BYPASS
            if not result.get("success"):
                print("🔄 Activando flujo BYPASS")
                result = await self._bypass_flow(
                    context=context,
                    failed_response=result.get("failed_response"),
                    summary_conversation=summary_conversation
                )
            
            # 5. EJECUTAR ACCIONES (si hay)
            if result.get("actions"):
                # actions = result["actions"]
                execution_result = await self._execute_actions(
                    current_order_id=context["order_id"],
                    actions=result["actions"],
                    session_id=session_id
                )
                result["execution"] = execution_result
            
            return result
            
        except Exception as e:
            print(f"💥 Error en process_order_intent: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "thought": "Error en el procesamiento",
                "actions": []
            }
        
    async def _load_order_context(self, session_id: str) -> Dict[str, Any]:
        """
        Carga el contexto actual de la orden y sesión.
        Responsabilidad única: obtener estado actual.
        """
        session = self.session_repository.get_session(session_id)
        order_id = session.order_id if session else None
        order = None
        summary = "El cliente no ha realizado pedido"
        
        if order_id:
            order = self.order_repository.get_order_by_id(order_id)
            summary = order.to_summary() if order else summary
        
        print_section(head="ESTADO ACTUAL DE LA ORDEN", msg=summary, symbol=":: ")
        
        return {
            "session": session,
            "order_id": order_id,
            "order": order,
            "summary": summary
        }

    def _prepare_processor_input(self, ordering_segments: List[Detail]) -> str:
        """
        Prepara el input para el LLM en formato texto plano.
        Misión: formatear segments para el prompt.
        """
        from src.utils.utils import safe_json_string

        print("\n--- SEGMENTOS DE ORDENING RECIBIDOS ---")
        
        input_lines = []
        for idx, segment in enumerate(ordering_segments):
            focus = f"User says: {segment.segment} + Focus: {segment.focus}"
            info = safe_json_string(segment.info_extracted)
            
            input_lines.append(f"Segmento {idx + 1}:")
            input_lines.append(f"  Focus: {focus}")
            input_lines.append(f"  Info: {info}\n")
            
            print(f"   Segment {idx + 1}:")
            print(f"   Focus: {focus}")
            print(f"   Query Type: {segment.query_type}\n")
        
        processor_input = "\n".join(input_lines)
        print_section(head="Injected focus and info into LLM", msg=processor_input, symbol=":: ")
        
        return processor_input

    async def _main_flow_with_retry(
        self,
        context: Dict[str, Any],
        processor_input: str,
        summary_conversation: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Flujo principal con reintentos.
        Máximo self.max_retries intentos.
        """

        import asyncio
        print("--- ANALIZANDO REQUEST (FLUJO PRINCIPAL) ... ---\n")
        
        last_error = None
        last_raw_response = None
        
        for attempt in range(self.max_retries):
            print(f"\n🔄 Intento principal {attempt + 1} de {self.max_retries}")
            
            try:
                # Construir prompt
                prompt = self._build_main_prompt(
                    current_order_state=context["summary"],
                    subquery_focus=processor_input,
                    summary_conversation=summary_conversation,
                    previous_error=last_error if attempt > 0 else None
                )
                
                # Llamar a LLM
                from src.config.environment import settings
                
                response = await self.llm_client.chat_completion(
                    messages=[{"role": "system", "content": prompt}],
                    temperature=min(0.1 + (attempt * 0.05), 0.3),
                    model=get_model_for_stage("action_planner", settings),
                    stream=False,
                    response_format={"type": "json_object"}
                )
                
                last_raw_response = response
                
                # Parsear y validar
                parse_result = self._parse_llm_response(response)
                
                if parse_result["success"]:
                    print(f"✅ Intento principal {attempt + 1} exitoso")
                    return {
                        "success": True,
                        "thought": parse_result["thought"],
                        "actions": parse_result["actions"],
                        "raw_response": response
                    }
                else:
                    last_error = parse_result["error"]
                    print(f"⚠️ Error en intento {attempt + 1}: {last_error}")
                    
            except Exception as e:
                last_error = str(e)
                print(f"⚠️ Excepción en intento {attempt + 1}: {last_error}")
            
            # Pausa antes de reintentar (backoff)
            if attempt < self.max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
        
        # Si llegamos aquí, todos los intentos fallaron
        return {
            "success": False,
            "error": last_error,
            "failed_response": last_raw_response,
            "thought": None,
            "actions": []
        }

    def _build_main_prompt(
        self,
        current_order_state: str,
        subquery_focus: str,
        summary_conversation: Optional[str] = None,
        previous_error: Optional[str] = None
    ) -> str:
        """
        Construye el prompt principal usando PromptManager.
        """
        from src.config.environment import settings

        prompt = get_prompt_manager(settings.prompt_fallback_map).get(
            "reconcilier",
            current_order_state=current_order_state,
            subquery_focus=subquery_focus,
            summary_conversation=summary_conversation or ""
        )
        
        if previous_error:
            prompt += f"\n\n### FEEDBACK DEL INTENTO ANTERIOR:\n{previous_error}\n"
            prompt += "Asegúrate de responder con un JSON válido y completo."
        
        return prompt

    def _parse_llm_response(self, raw_response: str) -> Dict[str, Any]:
        """
        Parsea y valida la respuesta del LLM.
        Retorna dict con success, thought, actions, error.
        """
        # Limpiar markdown
        clean = raw_response.strip()
        if clean.startswith("```json"):
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif clean.startswith("```"):
            clean = clean.split("```")[1].split("```")[0].strip()
        
        try:
            data = json.loads(clean)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"JSON inválido: {str(e)}",
                "raw": clean
            }
        
        # Validar estructura
        if "thought" not in data:
            return {
                "success": False,
                "error": "Campo 'thought' faltante",
                "raw": clean
            }
        
        actions = data.get("actions", [])
        if not isinstance(actions, list):
            return {
                "success": False,
                "error": "Campo 'actions' debe ser una lista",
                "raw": clean
            }
        
        return {
            "success": True,
            "thought": str(data.get("thought", "")),
            "actions": actions
        }
    
    async def _bypass_flow(
        self,
        context: Dict[str, Any],
        failed_response: Optional[str],
        summary_conversation: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Flujo de bypass: extrae thought de la respuesta fallida
        y genera solo actions.
        """
        print("--- INICIANDO FLUJO BYPASS ---")
        
        # 1. Extraer thought de la respuesta fallida
        thought = self._extract_thought_from_failed(failed_response)
        
        if not thought:
            print("⚠️ No se pudo extraer thought, usando fallback por reglas")
            return await self._rule_based_fallback(context)
        
        print_section(head="THOUGHT EXTRAÍDO PARA BYPASS", msg=thought, symbol="🔍")
        
        # 2. Generar actions desde el thought
        for attempt in range(self.max_retries):
            try:
                prompt = self._build_bypass_prompt(
                    current_order_state=context["summary"],
                    thought_text=thought,
                    summary_conversation=summary_conversation
                )
                
                response = await self.llm_client.chat_completion(
                    messages=[{"role": "system", "content": prompt}],
                    temperature=0.05,
                    model=get_model_for_stage("action_planner", settings),
                    stream=False,
                    response_format={"type": "json_object"}
                )
                
                parse_result = self._parse_bypass_response(response)
                
                if parse_result["success"]:
                    print("✅ Bypass exitoso")
                    return {
                        "success": True,
                        "thought": thought,
                        "actions": parse_result["actions"],
                        "from_bypass": True
                    }
                
            except Exception as e:
                print(f"⚠️ Error en bypass: {e}")
        
        # Si bypass falla, usar reglas
        return await self._rule_based_fallback(context)
    
    def _build_bypass_prompt(
        self,
        current_order_state: str,
        thought_text: str,
        summary_conversation: Optional[str] = None
    ) -> str:
        """
        Construye prompt para bypass.
        """

        from src.config.environment import settings
        
        return build_prompt(
            template_path=settings.reconcilier_bypass_prompt_path,
            current_order_state=current_order_state,
            thought_text=thought_text,
            summary_conversation=summary_conversation or ""
        )
    
    def _extract_thought_from_failed(self, failed_response: Optional[str]) -> Optional[str]:
        """
        Extrae el campo 'thought' de una respuesta JSON fallida.
        """
        if not failed_response:
            return None
        
        # Intentar extraer con regex
        import re
        thought_match = re.search(r'"thought"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', failed_response)
        if thought_match:
            return thought_match.group(1)
        
        # Si no, buscar patrón de texto que parezca un thought
        lines = failed_response.split('\n')
        for line in lines:
            if 'thought' in line.lower() and ':' in line:
                parts = line.split(':', 1)
                if len(parts) > 1:
                    return parts[1].strip().strip('"').strip("'")
        
        return None

    def _parse_bypass_response(self, raw_response: str) -> Dict[str, Any]:
        """
        Parsea respuesta del bypass (debe tener solo 'actions').
        """
        clean = raw_response.strip()
        if clean.startswith("```json"):
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif clean.startswith("```"):
            clean = clean.split("```")[1].split("```")[0].strip()
        
        try:
            data = json.loads(clean)
            actions = data.get("actions", [])
            
            if isinstance(actions, list):
                return {
                    "success": True,
                    "actions": actions
                }
            else:
                return {
                    "success": False,
                    "error": "actions debe ser lista"
                }
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "JSON inválido"
            }

    async def _rule_based_fallback(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fallback basado en reglas cuando todo lo demás falla.
        """
        print("⚠️ Usando fallback basado en reglas")
        
        # Implementación mínima - puedes expandir según necesidades
        return {
            "success": True,
            "thought": "Fallback por reglas - verificar manualmente",
            "actions": [],
            "from_bypass": True,
            "from_rules": True
        }

    async def _execute_actions(self, actions: List[Dict], session_id: str, current_order_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Ejecuta una lista de acciones atómicas sobre la orden.
        
        Args:
            actions: Lista de acciones a ejecutar
            session_id: ID de la sesión actual
            current_order_id: ID de la orden actual (si existe)
        
        Returns:
            Dict con resultado de la ejecución
        """
        if not actions:
            print("📭 No hay acciones para ejecutar")
            return {
                "executed": 0,
                "final_order_id": current_order_id,
                "results": []
            }
        
        # print_section(head="THOUGHT (COGNICIÓN DEL BOT)", msg=thought, symbol="-==-")
        print("\n--- ACCIONES PROPUESTAS ---")
        print(json.dumps(actions, indent=2, ensure_ascii=False))
        
        results = []
        order_id = current_order_id
        
        for idx, action in enumerate(actions, 1):
            operation = action.get("action")
            params = action.get("params", {})
            
            print(f"\n🔧 [{idx}/{len(actions)}] Ejecutando: {operation}")
            
            try:
                result = await self._execute_single_action(
                    operation=operation,
                    params=params,
                    inheritance=action.get("inheritance", {}),
                    order_id=order_id,
                    session_id=session_id
                )
                
                results.append(result)
                
                # Actualizar order_id si se creó una orden
                if operation == "CREATE_ORDER" and result.get("order_id"):
                    order_id = result["order_id"]
                    print(f"   ✅ Nueva orden creada: {order_id}")
                
            except Exception as e:
                error_result = {
                    "action": operation,
                    "success": False,
                    "error": str(e),
                    "params": params
                }
                results.append(error_result)
                print(f"   ❌ Error: {e}")
        
        # Resumen final
        successful = sum(1 for r in results if r.get("success", False))
        print(f"\n📊 Resumen: {successful}/{len(actions)} acciones ejecutadas correctamente")
        
        return {
            "executed": len(results),
            "successful": successful,
            "failed": len(results) - successful,
            "final_order_id": order_id,
            "results": results
        }

    async def _execute_single_action(
        self,
        operation: str,
        params: Dict,
        inheritance: Dict,
        order_id: Optional[str],
        session_id: str
    ) -> Dict[str, Any]:
        """
        Ejecuta una acción individual.
        """
        # Caso especial: CREATE_ORDER
        if operation == "CREATE_ORDER":
            new_order_id = await self._initialize_and_save_order(
                session_id=session_id
            )
            return {
                "action": operation,
                "success": True,
                "order_id": new_order_id,
                "params": params
            }
        
        # Validar que la operación exista
        if operation not in self.operations:
            error_msg = f"Operación desconocida: {operation}"
            print(f"   ❌ {error_msg}")
            return {
                "action": operation,
                "success": False,
                "error": error_msg,
                "params": params
            }
        
        # Validar que haya order_id (excepto para CREATE_ORDER que ya manejamos)
        if not order_id:
            error_msg = "No hay order_id para ejecutar la acción"
            print(f"   ❌ {error_msg}")
            return {
                "action": operation,
                "success": False,
                "error": error_msg,
                "params": params
            }
        
        # Ejecutar según tipo
        try:
            if operation == "CREATE_ITEM":
                print(f"   Parámetros: {params}")
                print(f"   Herencia: {inheritance}")
                await self.operations[operation](order_id, params, inheritance)
            else:
                # UPDATE_ITEM o DELETE_ITEM
                await self.operations[operation](order_id, params)
            
            return {
                "action": operation,
                "success": True,
                "params": params,
                "order_id": order_id
            }
            
        except Exception as e:
            return {
                "action": operation,
                "success": False,
                "error": str(e),
                "params": params,
                "order_id": order_id
            }

    
    async def _initialize_and_save_order(self, session_id: str= None) -> str:
        """
        Crea una estructura de orden inicial y la persiste en el archivo JSON.
        """
        session:  SessionData = self.session_repository.get_session(session_id=session_id)
        order_id = None
        
        if session.customer_id:
            customer_id = session.customer_id
            new_order: Order = self.order_repository.create_order(customer_id=customer_id)
        else:
            new_order: Order = self.order_repository.create_order()
        
        if new_order:
            order_id = new_order.id
            self.session_repository.link_session_to_order(session_id=session_id, order_id=order_id)

        print_section(head="Nuevo order_id", msg=order_id)
        
        return order_id
    

    async def _create_item(self, order_id:str=None, params:dict=None, inheritance:dict=None) -> OrderItem:
        """
        Crea un nuevo OrderItem y lo añade al pedido.
        Maneja la lógica de herencia para no perder detalles (sides, instructions).
        """

        if not order_id:
            print_section(head="ORDER_ID NO PROPORCIONADO!!!", symbol="X")
            return
        
        order = self.order_repository.get_order_by_id(order_id=order_id)
        
        # 1. Extraer datos básicos de los parámetros del LLM
        quantity = params.get("quantity", 1)
        protein = params.get("protein")
        principle = params.get("principle")
        sides = params.get("sides", ["Todo"])
        size = params.get("size", "")
        requirements = params.get("requirements", [])

        # 2. Lógica de Herencia (Crucial para que "el otro sí con pollo" mantenga los macarrones)
        if inheritance and inheritance.get("from_id"):
            source_item = next((item for item in order.items if item.id == inheritance["from_id"]), None)
            
            if source_item:
                # Si el nuevo item no especifica proteína/acompañamiento, heredamos del original
                if not protein and "protein" in inheritance.get("fields", []):
                    protein = source_item.protein
                if not sides and "sides" in inheritance.get("fields", []):
                    sides = source_item.sides
                if not requirements and "requirements" in inheritance.get("fields", []):
                    requirements = source_item.requirements.copy()

                if not principle and "principle" in inheritance.get("fields", []):
                    principle = source_item.principle

        # 3. Crear la instancia del nuevo item
        # Aquí asumo que tu modelo OrderItem se ve algo así:
        print()
        new_item = OrderItem(
            id=f"item-{str(uuid4())[:8]}",  # Generamos un ID corto para la sesión
            quantity=quantity,
            protein=protein,
            principle=principle,
            sides=sides,
            size=size,
            requirements=requirements
        )

        # 4. Registrar la acción y añadir a la orden
        order.items.append(new_item)

        self.order_repository.save_order(order=order)

        print_section(head="✅ ITEM CREADO", msg=new_item.to_summary(), symbol=":: ")
        # print(f"✅ ITEM CREADO: {quantity}x ({protein}/{side})")

        # return new_item
    
    async def _update_item(self, order_id:str=None, params:dict=None):
        """
        Actualiza un OrderItem existente basado en su ID.
        """

        if not order_id:
            print_section(head="ORDER_ID NO PROPORCIONADO!!!", symbol="X")
            return
        
        order = self.order_repository.get_order_by_id(order_id=order_id)

        item_id = params.get("item_id")
        if not item_id:
            print("❌ Error: No se proporcionó 'item_id' para actualizar.")
            return None
        
        item = next((i for i in order.items if i.id == item_id), None)
        if not item:
            print(f"❌ Error: No se encontró el item con ID {item_id} para actualizar.")
            return None
        # updates = params.get("updates", [])
        # Actualizar campos si se proporcionan
        if "quantity" in params:
            item.quantity = params["quantity"]
        if "protein" in params:
            item.protein = params["protein"]
        if "principle" in params:
            item.principle = params["principle"]
        if "sides" in params:
            item.sides = params["sides"]
        if "size" in params:
            item.size = params["size"]
        if "requirements" in params:
            for note in params["requirements"]:
                if note not in item.requirements:
                    item.requirements.append(note)


        self.order_repository.save_order(order=order)

        print_section(head="✅ ITEM ACTUALIZADO", msg=f"{item_id}", symbol=":")

        # print(f"✅ ITEM ACTUALIZADO: {item_id}")
        # return item
    
    async def _delete_item(self, order_id:str=None, params: dict=None):
        """
        Elimina un OrderItem existente basado en su ID.
        """
        item_id = params.get("item_id")
        if not item_id:
            print("❌ Error: No se proporcionó 'item_id' para eliminar.")
            return None
        
        order = self.order_repository.get_order_by_id(order_id=order_id)
        
        item_index = next((index for index, i in enumerate(order.items) if i.id == item_id), None)
        if item_index is None:
            print(f"❌ Error: No se encontró el item con ID {item_id} para eliminar.")
            return None
        
        removed_item = order.items.pop(item_index)
        self.order_repository.save_order(order=order)

        print_section(head="✅ ITEM ELIMINADO", msg=removed_item.to_summary(), symbol=":: ")


        # print(f"✅ ITEM ELIMINADO: {item_id}")
        # return removed_item

    # async def _bypass_action_generator(self, thought, order_state, summary):
    #     """
    #     BYPASS: Genera SOLO acciones basadas en reglas, sin LLM complejo.
    #     """
    #     # 1. Primero, generar thought simple
    #     thought_prompt = self._build_thought_only_prompt(thought, order_state, summary)
    #     thought_response = await self.llm_client.chat_completion(
    #         messages=[{"role": "system", "content": thought_prompt}],
    #         temperature=0.1,
    #         model="deepseek-chat"
    #     )
        
    #     # 2. Luego, generar acciones con un prompt MUY simple
    #     actions_prompt = self._build_actions_only_prompt(
    #         thought=thought_response,
    #         extraction=extraction,
    #         order_state=order_state
    #     )
        
    #     actions_response = await self.llm_client.chat_completion(
    #         messages=[{"role": "system", "content": actions_prompt}],
    #         temperature=0.1,
    #         model="deepseek-chat",
    #         response_format={"type": "json_object"}
    #     )
        
    #     try:
    #         actions_data = json.loads(actions_response)
    #         return {
    #             "thought": thought_response,
    #             "actions": actions_data.get("actions", [])
    #         }
    #     except:
    #         # Último recurso: acciones por reglas
    #         return self._rule_based_actions(extraction, order_state)