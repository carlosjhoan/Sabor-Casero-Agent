# Propuesta de Mejora: Anclajes del Sistema

Basada en el mapa de codigo actual y el framework de Structured Grounding.

---

## Resumen de Hallazgos Clave

Antes de proponer etapas, estos son los descubrimientos mas importantes
que hice revisando el codigo:

1. **El Planner borra TODO el historial** cada turno (`self._messages.clear()`,
   planner.py:188). No pasa mensajes entre turnos via el array de messages.
   Todo viaja por el system prompt como texto plano.

2. **El conversation summary se trunca a 120 caracteres** en el fallback
   sincronico (assistant.py:813-814), que es el que SIEMPRE se escribe antes
   del fire-and-forget asincronico. El LLM-based asincronico no corre a
   tiempo para el proximo turno. **El resumen que ve el Planner es SIEMPRE
   el truncado.**

3. **`to_summary()` no incluye metadatos de la orden.** Solo items + tipo
   de servicio. customer_name, con_todo, payment_method, observations no
   aparecen en el resumen de orden que ve el Planner.

4. **El checklist es binario en el stateless path.** El `OrderFlowTracker`
   tiene estados mas ricos (ASKED, ANSWERED, CONFIRMED, PENDING) pero el
   Planner usa `build_checklist_from_order()` que solo sabe OK/PENDING/NA.

5. **Memory store nunca retroalimenta al Planner.** Las entidades extraidas
   van a ChromaDB pero nunca se leen para inyectar en el contexto del
   siguiente turno.

6. **El menu se lee de disco cada vez.** Sin cache.

7. **El evaluador corre siempre que esta habilitado.** LLM call por turno.

---

## Etapas Propuestas

### Etapa 1: Conversation Summary Estructurado (Dias 1-2)

**Problema:** El resumen que ve el Planner es un texto truncado a 120 chars
por turno, sin estructura semantica. Pierde confirmaciones, intenciones, y
referentes cruzados.

**Cambios en codigo:**

**1a. Formato estructurado en el fallback sincronico (assistant.py:807-831)**

Actual:
```python
f"Turno {turn_number}: {message[:120]} | Asistente: {response_text[:120]} | Intento: ..."
```

Propuesto:
```python
f"[Turno {turn_number}]\n"
f"usuario: {message[:200]}\n"
f"asistente: {response_text[:200]}\n"
f"campos_afectados: {', '.join(affected_fields)}\n"
f"confirmaciones: {extracted_confirmations}\n"
f"intencion: {', '.join(intents_list[:3])}"
```

Donde `affected_fields` y `extracted_confirmations` se extraen del
`result["classification"]` o de la respuesta del Orquestador.

**1b. Aumentar limite de truncamiento**

De [:120] a [:200] para capturar mensajes completos en lugar de cortarlos
en medio de la frase. Esto afecta solo al fallback sincronico.

**1c. Incluir campos afectados en el summary**

Cada vez que el Planner llama `add-item`, `update-item`, `update-order`,
`confirm-order` o `cancel-order`, el sistema deberia registrar que campos
se modificaron. Esto permite que el summary del siguiente turno incluya
"lo que cambio" en lugar de solo "lo que se dijo".

**Impacto:**
- Confiabilidad: [++] El LLM sabe que se confirmo y que no
- Operatibilidad: [+] El summary preserva intencion, no solo texto
- Latencia: [=] Sin cambio (mismo codigo, mismo costo)

**Archivos a modificar:**
- `src/core/assistant.py` (~30 lines)
- `prompts/planner/system_prompt.txt` (opcional, para usar el nuevo formato)



### Etapa 2: Order State Completo (Dias 2-3)

**Problema:** `Order.to_summary()` solo muestra items + servicio. Los
metadatos de la orden (customer_name, con_todo, payment_method,
observations) no estan en el resumen que ve el Planner.

**Cambios en codigo:**

**2a. Ampliar `Order.to_summary()` (models.py:188-196)**

Actual:
```python
items_summary + service_info
```

Propuesto:
```python
items_summary + service_info + metadata_block
```

Donde `metadata_block` es algo como:
```
| Nombre: Carlos | Con todo: si | Pago: efectivo | Obs: sin sopa
```

**2b. O bien: inyectar un bloque separado de metadatos en el system prompt**

En vez de tocar `to_summary()`, agregar un placeholder `{order_metadata}`
en el system prompt y poblarlo desde el `PlannerContext`. Esto es mas
limpio porque no mezcla items con metadatos.

**Impacto:**
- Confiabilidad: [++] El Planner ve el estado completo del pedido
- Operatibilidad: [+] Mas facil mantener coherencia entre campos
- Latencia: [=] Sin cambio

**Archivos a modificar:**
- `src/core/order/domain/models.py` (opcional, ~5 lines)
- `src/core/agent/planner.py` (~5 lines para agregar placeholder + poblado)
- `prompts/planner/system_prompt.txt` (~2 lines)



### Etapa 3: Estados de Campo en el Checklist (Dias 3-5)

**Problema:** El checklist que ve el Planner solo tiene OK/PENDING/NA.
No sabe si un campo ya fue preguntado, si el usuario respondio parcialmente,
o si nunca se toco.

**Cambio en codigo:**

**3a. Agregar estados al stateless checklist**

`build_checklist_from_order()` necesita saber no solo si un campo TIENE
valor, sino si fue "asked" (preguntado), "answered" (respondido),
"confirmed" (confirmado) o "pending" (nunca preguntado).

Esto requiere persistir el estado de cada campo entre turnos. La opcion
mas simple: guardar un dict `{field: state}` en el Order como metadata,
o en un archivo separado por sesion.

**Propuesta de implementacion minima:**

1. Agregar `field_states: Dict[str, str] = {}` al modelo `Order`
2. En `update_order()` y `add_item()`, marcar el field como "answered"
3. `build_checklist_from_order()` usa field_states ademas del valor:

```
[OK] protein: Pechuga (confirmado)
[PEND] con_todo: nunca preguntado
[PREG] customer_name: preguntado, esperando respuesta
```

**3b. Maquina de estados simplificada**

```
PENDING -> ASKED -> ANSWERED -> CONFIRMED
                   -> SKIPPED (N/A)
```

- `PENDING`: nunca preguntado
- `ASKED`: se pregunto, esperando respuesta
- `ANSWERED`: el usuario respondio
- `CONFIRMED`: el usuario confirmo explicitamente
- `SKIPPED`: no aplica (campo condicional)

El cambio de `ASKED -> ANSWERED` ocurre cuando el Planner llama
`update-order` o `add-item`. El cambio de `ANSWERED -> CONFIRMED`
ocurre cuando el usuario dice "si" o "confirmo".

**Impacto:**
- Confiabilidad: [++] El LLM sabe exactamente que paso con cada campo
- Operatibilidad: [++] La maquina de estados evita repreguntas infinitas
- Latencia: [-] Un dict extra en memoria por sesion, ~0ms

**Archivos a modificar:**
- `src/core/order/domain/models.py` (~5 lines)
- `src/core/order/application/order_flow_tracker.py` (~40 lines)
- `src/core/order/application/orchestrator.py` (~10 lines)



### Etapa 4: Cache de Menu (Dia 3)

**Problema:** `get-full-menu` lee menu.md del disco cada vez. Si el Planner
lo pide 3 veces en una sesion, son 3 lecturas de disco + ~2K tokens cada una.

**Cambio en codigo:**

**4a. Cache en memoria por sesion**

En `assistant.py`, al iniciar la sesion, leer el menu y guardarlo en el
`PlannerContext`. El system prompt ya tiene un placeholder donde podria
inyectarse.

Pero esto no es ideal -- el menu completo en el prompt consume tokens
cada turno aunque no se necesite.

**4b. Cache lazy: guardar el resultado de la primera llamada**

La opcion mas practica: en `skill_tools.py`, cachear el resultado de
`get-full-menu` en memoria. Si se vuelve a llamar en la misma sesion,
devolver el cache.

```python
_menu_cache: dict[str, str] = {}

if name == "get-full-menu":
    session_id = context.get("session_id")
    if session_id in _menu_cache:
        return {"success": True, "result": {"menu": _menu_cache[session_id]}}
    # ... leer del disco/API ...
    _menu_cache[session_id] = menu_text
    return ...
```

**4c. Limpiar cache al cerrar sesion**

Agregar `clear_menu_cache(session_id)` llamado desde `process_message`
cuando la sesion termina.

**Impacto:**
- Confiabilidad: [=] Sin cambio
- Operatibilidad: [=] Sin cambio
- Latencia: [++] Elimina 1-2 lecturas de disco por sesion

**Archivos a modificar:**
- `src/core/agent/skill_tools.py` (~15 lines)



### Etapa 5: Feedback Loop de Memory Store (Dias 4-6)

**Problema:** Memory store extrae entidades pero nunca las inyecta en el
contexto del Planner. La informacion se pierde entre turnos.

**Cambio en codigo:**

**5a. Consultar entidades al inicio de cada turno**

En `assistant.py`, durante session prep, consultar ChromaDB por entidades
relevantes a la sesion actual e inyectarlas como un bloque estructurado:

```python
user_preferences_context = UserPreferences.load(user_id).to_prompt_context()
# Nuevo: agregar entidades de memoria
entities = memory_hub.semantic.get_entities_for_session(session_id)
user_preferences_context += "\n\n## Datos recordados del cliente\n" + entities
```

**5b. Agregar placeholder en system prompt**

Agregar `{memory_entities}` al template del system prompt.

**Impacto:**
- Confiabilidad: [++] El Planner sabe lo que el usuario ya dijo antes
- Operatibilidad: [+] Mantiene coherencia en sesiones largas
- Latencia: [-] Consulta a ChromaDB agrega ~100-300ms por turno

**Archivos a modificar:**
- `src/core/assistant.py` (~10 lines)
- `src/core/agent/planner.py` (~5 lines)
- `prompts/planner/system_prompt.txt` (~2 lines)



### Etapa 6: History Prioritization (Dias 5-7)

**Problema:** El historial se borra cada turno. No hay priorizacion de que
informacion preservar entre turnos.

**Cambio en codigo:**

**6a. En vez de borrar todo, preservar los ultimos N mensajes clave**

En planner.py, en vez de:
```python
self._messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": message},
]
```

Hacer:
```python
# Preservar los ultimos 2 turnos completos (system + user + assistant + tools)
self._messages = self._compress_history(self._messages, max_turns=2)
self._messages.insert(0, {"role": "system", "content": system_prompt})
self._messages.append({"role": "user", "content": message})
```

**6b. Compresion inteligente**

Cuando el historial excede el limite de tokens, priorizar:
1. Confirmaciones del usuario (peso alto)
2. Tool calls exitosos (peso medio-alto)
3. Resultados de tools (peso medio)
4. Mensajes de cortesia (peso bajo, descartar primero)

**Impacto:**
- Confiabilidad: [++] El LLM ve la historia literal, no resumida
- Operatibilidad: [++] Mantiene coherencia en sesiones larguiiiisimas
- Latencia: [+] Mas tokens por turno = inferencia ligeramente mas lenta

**Archivos a modificar:**
- `src/core/agent/planner.py` (~50 lines)



### Etapa 7: Evaluacion Condicional (Dia 2)

**Problema:** El evaluador corre en cada turno. Agrega latencia y costo
innecesarios cuando el mensaje es simple.

**Cambio en codigo:**

Ejecutar la evaluacion SOLO cuando:
- El pedido cambio (add-item, update-order, confirm-order, etc.)
- El usuario pidio informacion del menu
- Es el primer mensaje de la sesion

Para mensajes simples como "hola", "gracias", "si", saltar la evaluacion.

```python
if settings.evaluation_enabled and _should_evaluate(result):
    asyncio.create_task(self._run_evaluation(...))
```

**Impacto:**
- Confiabilidad: [=] Sin cambio (se evalua cuando importa)
- Operatibilidad: [=] Sin cambio
- Latencia: [++] Evita 1 LLM call en ~60% de los turnos

**Archivos a modificar:**
- `src/core/assistant.py` (~15 lines)



## Resumen de Etapas por Impacto

  Etapa | Descripcion                            | Confiabilidad | Operatibilidad | Latencia | Esfuerzo
  ------|----------------------------------------|:-------------:|:--------------:|:--------:|:-------:
  1     | Summary estructurado + mas ancho       | [++]          | [+]            | [=]      | 1-2 dias
  2     | Order state con metadatos              | [++]          | [+]            | [=]      | 1 dia
  3     | Estados de campo en checklist          | [++]          | [++]           | [=]      | 2-3 dias
  4     | Cache de menu                          | [=]           | [=]            | [++]     | 1 dia
  5     | Memory store feedback                  | [++]          | [+]            | [-]      | 2-3 dias
  6     | History prioritization                 | [++]          | [++]           | [-]      | 2-3 dias
  7     | Evaluacion condicional                 | [=]           | [=]            | [++]     | 1 dia

## Orden Recomendado

**Fase 1 (impacto rapido, 2-3 dias):**
1. Etapa 4: Cache de menu (1 dia, latencia)
2. Etapa 7: Evaluacion condicional (1 dia, latencia)
3. Etapa 2: Order state completo (1 dia, confiabilidad)

**Fase 2 (anclajes fuertes, 4-5 dias):**
4. Etapa 1: Summary estructurado (2 dias, confiabilidad + operatibilidad)
5. Etapa 3: Estados de campo (2-3 dias, confiabilidad + operatibilidad)

**Fase 3 (coherencia a largo plazo, 4-6 dias):**
6. Etapa 5: Memory store feedback (2-3 dias, confiabilidad)
7. Etapa 6: History prioritization (2-3 dias, operatibilidad)

---

*Junio 2026 -- Sabor Casero Assistant*
*Propuesta basada en el analisis de gaps del sistema actual.*
