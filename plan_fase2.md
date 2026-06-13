# Plan Fase 2: Anclajes Fuertes

Dos etapas consecutivas. Orden: primero Etapa 1, luego Etapa 3.

---

## Etapa 1: Summary Estructurado

**Archivo:** `src/core/assistant.py` (~30 lines modificadas)
**Tiempo:** 1 dia
**Impacto:** Confiabilidad [++], Operatibilidad [+], Latencia [=]

### Cambios

**1a. Aumentar truncamiento (asistant.py:813-814)**

Actual: `message[:120]` y `response_text[:120]`
Nuevo: `message[:250]` y `response_text[:250]`

Esto captura mensajes completos. Un "sin sopa, porfa" o "si, eso es lo que pedi"
entran enteros.

**1b. Formato estructurado por turno (asistant.py:812-818)**

Actual:
```
Turno 5: sin sopa, porfa | Asistente: ¡Listo! ✅ Ya anoté sin sopa... | Intento: ordering | Items: Macarrón
```

Nuevo:
```

  [Turno 5]
  >>> sin sopa, porfa
  <<< ¡Listo! ✅ Ya anoté sin sopa para tu pedido.
  > intencion: ordering
  > items: Macarron con carne molida

```

Esto le da al LLM una estructura visual clara: lo que dijo el usuario, lo que
respondio el asistente, y los metadatos. Cada turno es un bloque auto-contenido
con separacion clara.

**1c. Acumulacion (asistant.py:820-823)**

La acumulacion via `previous_summary` ya funciona. Cada nuevo turno se agrega
al resumen anterior. El nuevo formato hace que la acumulacion sea mas legible.

### Archivos modificados:
- `src/core/assistant.py` — ~15 lines (formato sync fallback + truncamiento)
- (opcional) `prompts/planner/system_prompt.txt` — si queremos ajustar como
  se muestra la seccion de historial



## Etapa 3: Estados de Campo en Checklist

**Archivos:** 3 archivos, ~80 lines total
**Tiempo:** 2 dias
**Impacto:** Confiabilidad [++], Operatibilidad [++], Latencia [=]

### Modelo de estados

```
PENDING  →  nunca preguntado / no tiene valor
ASKED    →  el Planner pregunto, esperando respuesta (futuro)
ANSWERED →  el usuario respondio, el campo tiene valor
SKIPPED  →  no aplica (campo condicional, como address si es pickup)
```

Para la implementacion inicial arrancamos con tres estados visibles:
`[PEND]`, `[OK]`, `[N/A]` — pero con semantica mejorada.

### Cambios

**3a. Agregar field_states al modelo Order (models.py)**

```python
# En Order class, despues de con_todo:
field_states: Dict[str, str] = Field(default_factory=dict)
```

Esto persiste el estado de cada campo entre turnos. Ejemplo:
```json
{
  "protein": "answered",
  "size": "answered",
  "principle": "answered",
  "con_todo": "pending",
  "customer_name": "answered"
}
```

**3b. Marcar campos como answered desde la orquestacion (orchestrator.py)**

En `update_order()`, cuando un field se setea exitosamente:
```python
if "customer_name" in params:
    order.customer_id = params["customer_name"]
    order.field_states["customer_name"] = "answered"
    updated.append("customer_name")
```

En `add_item()`, cuando se crea un item:
```python
if params.get("protein"):
    order.field_states["protein"] = "answered"
if params.get("principle"):
    order.field_states["principle"] = "answered"
if params.get("size"):
    order.field_states["size"] = "answered"
```

**3c. Actualizar build_checklist_from_order() (order_flow_tracker.py)**

Actual: solo mira si el campo tiene valor.
Nuevo: mira el valor + el estado del campo.

```python
for field_name, _ in ORDER_FIELDS:
    value = _get_field_value_static(field_name, order)
    state = order.field_states.get(field_name, "pending")
    
    if state == "answered":
        lines.append(f"[OK] {field_name}: ✅ {value}")
    elif field_name in CONDITIONAL_FIELDS:
        # check N/A logic (same as today)
        ...
    else:
        lines.append(f"[PEND] {field_name}: ⏳ pendiente")
```

Esto es casi identico al codigo actual, pero la diferencia es: el estado
`[OK]` ahora significa "el usuario respondio", no solo "el campo tiene un
valor default". Y cuando un campo tiene valor pero NO esta en field_states
como "answered" (ej: valor default de fabrica), se muestra como `[PEND]`.

### Archivos modificados:
- `src/core/order/domain/models.py` — +1 field
- `src/core/order/application/orchestrator.py` — ~15 lines (marcar estados)
- `src/core/order/application/order_flow_tracker.py` — ~20 lines
  (build_checklist_from_order usa field_states)



## Orden de Implementacion

1. **Etapa 1** .mdj → Summary estructurado (~30 min de codigo)
2. **Etapa 3a** → field_states en Order model (~5 min)
3. **Etapa 3b** → Marcar campos desde orchestrator (~15 min)
4. **Etapa 3c** → build_checklist_from_order mejorado (~15 min)
5. **Tests** → Verificar que todo sigue funcionando (~15 min)

Tiempo total estimado: ~1.5-2 horas de codigo, no dias.

---

¿Arrancamos con la Etapa 1?
