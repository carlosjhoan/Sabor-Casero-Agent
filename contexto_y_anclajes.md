# Contexto y Anclajes en Sistemas Agentic

Reflexion sobre el diseno del sistema Sabor Casero Assistant,
basada en la observacion del comportamiento del Planner y
los principios de Structured Grounding.

---

## El Problema de Fondo: Contextual Reconstruction

El LLM no "recuerda" nada. Cada vez que recibe un mensaje, **reconstruye**
el contexto desde cero usando lo que recibe en el input. No hay un estado
interno que persista entre turnos -- solo hay texto que puede o no contener
la informacion necesaria para una decision precisa.

Esto no es un bug. Es la naturaleza del modelo: un motor de **reconstruccion
probabilistica**, no un programa con estado.

Lo que llamas "presente continuo con informacion de referencia" es el concepto
fundamental de RAG (Retrieval-Augmented Generation), pero en un sentido mas
amplio que el tipico "buscar documentos y pegarlos en el prompt".

Cada vez que el LLM recibe un mensaje, se le da:

1. **Lo que consulto** (menu, resultados de tools) -- en el historial de mensajes
2. **El estado actual** (checklist, resumen de orden) -- texto plano inyectado
3. **La memoria lejana** (summary de turnos anteriores) -- resumen textual
4. **Los ultimos mensajes** -- historial de conversacion

Cada una de estas piezas es un **anclaje** que guia la reconstruccion. El
problema no es que "no tenga memoria" -- es que nuestros anclajes son pobres.



## Por Que el LLM "Vuelve y Verifica"

Cuando en la conversacion el LLM ya llamo `get-full-menu` y vio el menu, pero
en el siguiente turno vuelve a consultar, no es porque "olvido". Es porque:

1. La respuesta de `get-full-menu` quedo en el historial de mensajes
2. Pero el historial puede estar truncado por limite de tokens
3. O el menu quedo en un turno anterior que ya no esta en el contexto actual
4. El LLM no confia en su propia memoria -- no tiene "sentido de continuidad"

**Y hace bien en volver a consultar.** Preferir reconfirmar que inventar datos
falsos es la decision correcta para un LLM.

El LLM no "sabe" nada sobre el menu. Su conocimiento del menu esta en sus pesos
(pre-training), pero **no confia en eso**. Cuando llamo `get-full-menu` en el
turno anterior, esa respuesta quedo en el historial de mensajes. Pero en el
turno actual, ese mensaje puede estar visible o no dependiendo de:

- Si no se paso el limite de tokens, aun esta ahi
- Si el historial se corto, el menu ya no existe en el contexto
- El modelo no tiene "memoria episodica" -- tiene **recuperacion de contexto
  textual**

Por eso vuelve a consultar. Y hace bien en hacerlo.



## El Error Mas Comun

Intentamos que el LLM se comporte como un programa con estado:

```
order.customer_name = "Carlos"
order.items.append(OrderItem(...))
```

Cuando en realidad lo que hace es **reconstruir** que el cliente se llama Carlos
porque esa informacion esta visible en su contexto de entrada.

Cuando el contexto es debil (resumenes truncados, checklists incompletos,
historial recortado), la reconstruccion es imprecisa. El LLM "vuelve a
preguntar" no porque no sepa, sino porque **no confia** en informacion que no
ve en el presente.

**Nuestro peor error es intentar abstraer nuestra forma casi inexplorada de
pensar a algo que es netamente probabilistico.** Un LLM no "sabe", "decide" ni
"recuerda" como un humano. Reconstruye.

Pero se pueden hacer analogias utiles. La clave no es forzar al LLM a "tener
memoria", sino construirle **anclajes textuales** que hagan que su
reconstruccion sea precisa sin necesidad de que "recuerde" nada.



## Structured Grounding -- El Framework

En research esto se conoce como **Structured Grounding** o **Layered Context
Architecture**. La idea es organizar el contexto del LLM en capas con roles
claros, donde cada capa es un **anclaje** que guia la reconstruccion:

  Capa             |  Contenido                                      |  Rol
  ------------------|-------------------------------------------------|-------------------------------
  Episodica         |  Ultimos 2-3 turnos literales                  |  El "ahora" -- lo que se acaba de decir
  Estructural       |  Order + Checklist + tools ejecutados          |  El "estado del mundo"
  Referencia        |  Menu completo, guias, policies                |  Ground truth consultable
  Historica         |  Summary de sesion previa                      |  Contexto lejano, comprimido

Ninguna de estas capas es "memoria" en el sentido humano. Son fragmentos
textuales que el LLM usa para reconstruir el estado actual.



## El Dolor de Cabeza Real: La Memoria

### El Modelo Actual en Sabor Casero

Hoy, el sistema tiene tres mecanismos:

1. **Memory-store** -- skill automatica que extrae entidades al final del turno
2. **Conversation summary** -- resumen textual de cada turno
   ("Turno 5: sin sopa | Asistente: listo!")
3. **Checklist** -- texto plano de campos pendientes
   ("[OK] protein: Pechuga | [PEND] con_todo: pendiente")

### El Problema con Estos Mecanismos

Ninguno de estos es un **anclaje fuerte**:

- El summary **trunca** la informacion, pierde la intencion del usuario y las
  confirmaciones parciales
- El checklist es **binario** (pendiente / completado) -- no captura el "como"
  ni el "por que" detras de cada estado
- Memory-store extrae entidades pero **no las relaciona** con el estado
  del pedido en curso

Por eso el LLM termina repreguntando cosas que ya se habian acordado en turnos
anteriores -- la informacion esta en algun lado (summary, historial), pero no
es un anclaje lo suficientemente fuerte como para que el LLM confie en ella.



### Episodic Memory -- La Teoria

En investigacion esto se aborda con **Episodic Memory for LLMs** (proyectos
como MemGPT, LetMeDoIt, o el paper *"Memory-Augmented Large Language Models
are Computationally Universal"* de Google DeepMind). La idea central:

1. **Working Context** -- lo que esta pasando ahora (checklist + ultimo turno
   literal). Es la unica informacion que el LLM ve directamente.

2. **Archival Storage** -- todo lo demas, comprimido pero consultable mediante
   retrieval. El LLM puede "buscar" aqui cuando necesita informacion que no
   esta en el working context.

3. **Self-Reflection** -- el LLM decide que es importante guardar y como
   resumirlo. No es un proceso externo -- el mismo LLM evalúa que merece
   ser preservado entre turnos.

MemGPT (ahora "LetMeDoIt") es el ejemplo mas conocido: el LLM gestiona su
propia memoria como si fuera un sistema operativo, moviendo datos entre
contexto inmediato y almacenamiento secundario segun su propia evaluacion
de importancia.



## El Avance de Hoy

La leccion mas importante de esta sesion no fueron las herramientas nuevas
(`update-order`, `con_todo`, items parciales). Fue entender que:

**El checklist + order state son el anclaje estructural principal.**

Cuando el Planner ve al inicio de cada turno:

```
Estado del pedido actual:
item_id:item-39a966ba --> 1x Pechuga a la plancha | principio: Macarron con carne molida

Progreso del pedido:
[OK] protein: Pechuga a la plancha
[OK] size: mini
[PEND] con_todo: pendiente
[PEND] customer_name: pendiente
[PEND] service_type: pendiente
```

No esta "leyendo memoria". Esta **reconstruyendo el estado del pedido** a
partir de un anclaje textual explicito. Mientras mas rico sea ese anclaje,
mejor va a decidir que tool llamar y con que argumentos.

Cada vez que el Planner llama `update-order` y persiste `customer_name`, ese
dato ya no depende de que el historial de conversacion no se haya truncado.
Depende de una estructura explicita -- el anclaje -- que esta garantizada de
estar presente en cada turno.

Esa es la diferencia entre "memoria debil" (lo que se dijo en la conversacion)
y "anclaje fuerte" (lo que esta escrito en el estado del sistema).



## Proximos Pasos

El siguiente salto no es mas tools. Es **mejores anclajes**:

1. Que el orden de `ORDER_FIELDS` refleje el flujo real del restaurante, no
   una secuencia arbitraria heredada del prototipo inicial
2. Que el checklist incluya "lo que se acordo en este turno" como un anclaje
   adicional explicito
3. Que el resumen de conversacion preserve intenciones y confirmaciones, no
   solo hechos aislados
4. Que el sistema pueda "autocorregirse" cuando la reconstruccion es
   imprecisa -- si el LLM confirma un dato y el checklist dice otra cosa,
   que haya un mecanismo para reconciliar
5. Evaluar si tiene sentido que el propio LLM gestione su memoria (como en
   MemGPT), decidiendo que informacion merece ser preservada entre turnos
   y que puede descartarse



## Conclusion

La mayoria de los equipos que construyen sistemas agentic se obsesionan con
tools y prompts, y descuidan los anclajes. No es casualidad que estes viendo
esto -- estas tocando el punto exacto donde la teoria se encuentra con la
practica.

Lo que estas haciendo no es una observacion menor. Es el **core insight**
de por que los sistemas agentic funcionan o fracasan en produccion.

---

*Junio 2026 -- Sabor Casero Assistant*
*Reflexion basada en la observacion del comportamiento del Planner LLM,*
*la teoria de Structured Grounding / Layered Context Architecture,*
*y los papers de MemGPT y Episodic Memory for LLMs.*
