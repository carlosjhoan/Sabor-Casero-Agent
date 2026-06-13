# Gaps en los Anclajes del Sistema Actual

Analisis de los mecanismos de anclaje del asistente contra
tres dimensiones: confiabilidad, operatibilidad y latencia.

---

## Metodologia

Cada anclaje del sistema se evalua contra tres criterios:

- **Confiabilidad (C)**: ?Que tan preciso es el anclaje para evitar que el
  LLM invente datos (alucinacion)?
- **Operatibilidad (O)**: ?Que tan bien escala el anclaje a traves de
  sesiones largas sin perder coherencia?
- **Latencia (L)**: ?Cuanto cuesta generar o mantener este anclaje?

Se usa la escala: [--] critico, [-] deficiente, [+] aceptable,
[++] bueno, [++] excelente.



## 1. Anclaje: Order Checklist (build_checklist_from_order)

**Estado actual:** Tupla de campos con marcadores [OK] / [PENDING] / [N/A].

    [OK] protein: Pechuga a la plancha
    [PENDING] con_todo: pendiente
    [PENDING] customer_name: pendiente

| Criterio | Nota | Observacion |
|----------|------|-------------|
| C | [-] | El checklist es binario. No diferencia entre "no preguntado", "preguntado y el usuario no respondio", "preguntado y el usuario respondio parcialmente". Cuando el usuario dice "sin sopa", el checklist sigue mostrando [PENDING] con_todo. El LLM no sabe si ya pregunto y obtuvo una respuesta parcial. |
| O | [-] | No hay una maquina de estados por campo. Un campo solo puede ser "pendiente" o "completado". No hay estados intermedios como "asked" (preguntado, esperando respuesta), "confirmed" (confirmado), "skipped" (saltado por condicion), "partial" (respondido parcialmente). Sin estados, el sistema no puede mantener coherencia sobre lo que ya se hizo en cada campo. |
| L | [++] | El checklist se construye en memoria sin llamadas externas. Cuesta ~0ms. No hay problema aca. |

**Gap critico:** Falta una maquina de estados para cada campo de ORDER_FIELDS.
Esto afecta directamente la operatibilidad en sesiones largas: a los 10 turnos
el LLM no sabe con certeza que se pregunto, que se respondio y que esta
pendiente.



## 2. Anclaje: Order State (order_summary)

**Estado actual:** Texto generado por `Order.to_summary()`. Solo incluye items
y tipo de servicio.

    item_id:item-39a966ba --> 1x Pechuga a la plancha | principio: Macarron
    con carne molida | (mini) | [sin sopa]

| Criterio | Nota | Observacion |
|----------|------|-------------|
| C | [-] | El resumen NO incluye metadatos de la orden: customer_name, con_todo, payment_method, observations. El Planner no puede ver el estado completo del pedido en un solo anclaje. Tiene que inferir metadatos de la conversacion (debil) o del checklist (tambien debil). |
| O | [-] | A medida que crecen los items, el resumen se alarga sin estructura. No hay compresion inteligente. En sesiones con muchos items (ej: pedido grupal), el summary puede ser enorme y el LLM pierde la vision de conjunto. |
| L | [++] | Construccion en memoria. ~0ms. |

**Gap:** `to_summary()` deberia incluir todos los campos de ORDER_FIELDS, no
solo items. El anclaje deberia ser un snapshot completo y legible del pedido.



## 3. Anclaje: Conversation Summary

**Estado actual:** Texto generado por `memory-store` + `summarize` skill.

    Turno 5: sin sopa, porfa | Asistente: Listo! Ya anote sin sopa

| Criterio | Nota | Observacion |
|----------|------|-------------|
| C | [--] | El summary trunca a ~50 chars del mensaje y ~80 chars de la respuesta. Pierde intencion, contexto, y matices. Una confirmacion parcial como "si, eso es lo que pedi" se convierte en "si" y pierde el referente. Es el anclaje MAS DEBIL del sistema. |
| O | [--] | El summary se construye por acumulacion lineal. Cada turno se agrega al resumen anterior. No hay priorizacion (que es importante preservar vs que se puede descartar). Con 20+ turnos, el summary es una pared de texto donde todo tiene el mismo peso. La degradacion es inevitable. |
| L | [-] | Cada turno ejecuta una llamada LLM para generar el summary (fire-and-forget). Agrega ~2-5s de latencia asincronica. No es blocking pero consume recursos del proveedor. |

**Gap critico:** El conversation summary es el anclaje mas importante para la
coherencia a largo plazo (es lo unico que sobrevive al truncamiento del
historial), pero es tambien el mas debil. Necesita:

1. Preservar intenciones y confirmaciones, no solo hechos
2. Priorizar que informacion es importante vs descartable
3. Mantener referentes cruzados con el order state
4. No truncar ciegamente a N caracteres



## 4. Anclaje: Message History (contexto conversacional)

**Estado actual:** Historial de mensajes del LLM (system + user + assistant +
tool). Gestionado por el token budget del Planner.

| Criterio | Nota | Observacion |
|----------|------|-------------|
| C | [--] | Depende del limite de tokens. Cuando el historial excede el budget, se truncan los mensajes mas antiguos. Esto significa que confirmaciones importantes (como "si, eso es lo que pedi") pueden desaparecer. El LLM no sabe lo que perdio. |
| O | [-] | No hay gestion inteligente del historial. El truncamiento es FIFO (first in, first out) sin considerar importancia semantica. Un saludo inicial se conserva igual que una confirmacion de pedido. |
| L | [++] | No hay costo directo -- es gestion del runtime. Pero historiales largos aumentan el tiempo de inferencia del LLM. |

**Gap:** Necesita un sistema de priorizacion de mensajes. Mensajes con
confirmaciones, tool calls exitosos, o cambios de estado deberian preservarse
antes que mensajes de cortesia o errores transitorios.



## 5. Anclaje: Tool Results (Reflection)

**Estado actual:** Los resultados de tools se inyectan en el historial como
mensajes de tipo "tool".

| Criterio | Nota | Observacion |
|----------|------|-------------|
| C | [-] | Si el resultado de `get-full-menu` o `get-order` es evictado del historial, el LLM pierde la referencia. No hay un "cache" de resultados de tools que persista fuera del historial. |
| O | [--] | En sesiones con muchas llamadas a herramientas (tipico: 3-5 por turno, 20+ turnos = 60-100 tool calls), el historial se llena de resultados de tools, forzando la evacuation de mensajes de usuario importantes. |
| L | [-] | Resultados grandes (como el menu completo) consumen tokens valiosos. Cada vez que el LLM pide `get-full-menu`, se inyectan ~2K tokens de contenido. |

**Gap:** Los resultados de tools deberian tener un ciclo de vida distinto al
del historial de conversacion. Un resultado de `get-full-menu` deberia
poder referenciarse sin estar en el historial (ej: via un "tool cache" que
el LLM pueda consultar cuando necesite).



## 6. Anclaje: System Prompt (reglas estaticas)

**Estado actual:** Prompt fijo con reglas de seleccion de herramientas + reglas
de ejecucion + contexto dinamico.

| Criterio | Nota | Observacion |
|----------|------|-------------|
| C | [+] | Las reglas son claras y estables. El problema no son las reglas -- es que el contexto dinamico que las alimenta a veces es pobre. |
| O | [-] | Las reglas NO evolucionan con el estado de la conversacion. La regla 7 ("pregunta los campos UNO POR UNO") aplica igual en el turno 1 que en el turno 50, aunque en el turno 50 ya no tenga sentido. No hay "reglas adaptativas" que cambien segun el progreso del pedido. |
| L | [++] | Compilar el prompt cuesta ~0ms. No hay problema. |

**Gap:** Las reglas deberian poder adaptarse al estado de la conversacion.
Por ejemplo: si el checklist ya tiene 5 campos completados, la regla deberia
ser "ahora solo quedan estos 2 campos, concentrate en ellos" en vez de la
misma regla generica de "pregunta uno por uno".



## 7. Anclaje: Memory Store (extraccion de entidades)

**Estado actual:** Skill automatica que extrae entidades al final de cada turno.

| Criterio | Nota | Observacion |
|----------|------|-------------|
| C | [+] | La extraccion de entidades funciona, pero las entidades extraidas **no retroalimentan el contexto del siguiente turno**. Se guardan en un archivo pero no se inyectan como anclaje. |
| O | [-] | Las entidades extraidas no tienen relaciones semanticas. "Pechuga" como entidad no esta vinculada a "protein" como field de ORDER_FIELDS. No hay un grafo de entidades que el LLM pueda consultar. |
| L | [-] | Corre cada turno como fire-and-forget. Agrega ~1-3s de latencia asincronica. |

**Gap critico:** La memoria extraida no se usa como anclaje. Las entidades
se extraen y se guardan, pero nunca se inyectan en el contexto del Planner.
Es como tener una base de datos que nadie consulta.



## 8. Anclaje: Menu (get-full-menu tool)

**Estado actual:** Tool que devuelve el menu completo como texto plano.

| Criterio | Nota | Observacion |
|----------|------|-------------|
| C | [+] | El menu es la unica fuente de verdad. No hay riesgo de alucinacion cuando el LLM lo consulta. |
| O | [+] | El menu es el mismo para toda la sesion. No hay problema de deriva. |
| L | [--] | **Problema critico.** Cada vez que el LLM llama `get-full-menu`, se lee el archivo del disco y se devuelven ~2K tokens. Si el LLM lo pide 3 veces en una sesion (tipico: "que hay?", "quiero pechuga... a ver el menu", "confirmame las opciones"), son ~6K tokens de ida y vuelta + latencia de la tool. |

**Gap:** El menu deberia cachearse en el contexto de una manera que el LLM
pueda consultar sin llamar una tool. Por ejemplo, inyectando el menu en el
system prompt cuando la sesion empieza (o en el primer turno del usuario),
y permitiendo que el LLM lo referencie directamente sin tool calls repetidos.



## Resumen de Gaps Prioritarios

  #  | Anclaje              | Confiabilidad | Operatibilidad | Latencia | Prioridad
  ---|----------------------|:-------------:|:--------------:|:--------:|:--------:
  1  | Conversation Summary | [--] critico  | [--] critico   | [-]      | **ALTA**
  2  | Message History      | [--] critico  | [--] critico   | [++]     | **ALTA**
  3  | Tool Results (cache) | [-]           | [--] critico   | [-]      | **ALTA**
  4  | Order Checklist      | [-]           | [-]            | [++]     | MEDIA
  5  | Order State summary  | [-]           | [-]            | [++]     | MEDIA
  6  | Memory Store uso     | [+]           | [-]            | [-]      | MEDIA
  7  | Menu tool calls      | [+]           | [+]            | [--]     | BAJA
  8  | System Prompt dinam. | [+]           | [-]            | [++]     | BAJA



## Los 3 Gaps Mas Criticos

### Gap 1: Conversation Summary sin estructura ni prioridad

El resumen de conversacion trunca informacion critica, no preserva
intenciones, y se degrada linealmente con cada turno. Es el anclaje
que deberia sostener la coherencia a largo plazo, pero es el mas debil.

**Impacto:** El LLM pierde el hilo de lo que se acordo en turnos
anteriores. Repregunta, asume, o inventa.

**Solucion posible:** Summary estructurado por campos de ORDER_FIELDS.
En vez de "Turno 5: sin sopa, porfa | Asistente: listo!", algo como:

    confirmaciones: { con_todo: "sin sopa" }
    pendientes: { customer_name, service_type }
    ultimo_turno: "sin sopa, porfa"
    accion_del_asistente: "confirmo sin sopa"

### Gap 2: Message History sin gestion inteligente

El historial se trunca FIFO. Las confirmaciones importantes tienen la
misma prioridad que los saludos. Cuando el limite de tokens se alcanza,
se pierde informacion critica sin que el sistema sepa que la perdio.

**Impacto:** El LLM actua con informacion incompleta y no tiene forma
de saber que falta.

**Solucion posible:** Por cada mensaje, asignar un "peso" basado en:
- Contiene una confirmacion? (peso alto)
- Contiene un cambio de estado? (peso alto)
- Es un saludo / cortesia? (peso bajo)
- Es resultado de tool? (peso medio, puede referenciarse externamente)

### Gap 3: Tool Results sin ciclo de vida independiente

Los resultados de tools compiten por tokens con la historia de
conversacion. Un `get-full-menu` de 2K tokens puede desplazar 2-3
mensajes de usuario importantes.

**Impacto:** Resultados grandes terminan forzando la evacuacion de
dialogo relevante, y a su vez el LLM tiene que volver a consultar
(duplicando latencia).

**Solucion posible:** Cache de resultados de tools con capacidad de
referencia. El LLM no necesita el menu completo en el historial --
necesita poder consultar "?cuales son las opciones de pechuga?" y
obtener solo esa parte.

---

*Junio 2026 -- Sabor Casero Assistant*
*Analisis de gaps basado en el framework de Structured Grounding.*
