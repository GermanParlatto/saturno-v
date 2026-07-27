# WAKU-CODE — Alcance del Script Generador de Dataset
## Proyecto Waku-Code · Documento 6
### `generate_spoky_dataset.py` — Qué resuelve y qué NO resuelve

---

## 1. Propósito

El script genera el **dataset sintético JSONL** para entrenar un adaptador LoRA que
enseñe al modelo base los reflejos de comportamiento de Spoky: voz del personaje, tono,
elogio de proceso, brevedad WhatsApp, manejo de analogías y estilo socrático de guía.

**El LoRA no reemplaza al system prompt ni a los guardrails**: enseña *cómo hablar*,
no *qué límites respetar*. La frontera entre ambos está definida en el Documento 07.

---

## 2. Qué produce el script

| Archivo | Contenido | Uso |
|---|---|---|
| `dataset_master_{phase}.jsonl` | Ejemplos validados + metadatos (nivel, escenario, concepto, persona, split) | Referencia y auditoría |
| `train_{phase}.jsonl` | 80% estratificado — solo `{"messages": [...]}` | Entrenamiento del LoRA |
| `val_{phase}.jsonl` | 10% estratificado | Evaluación durante entrenamiento (loss) |
| `test_{phase}.jsonl` | 10% estratificado | Evaluación final (métricas de calidad) |
| `rejected_{phase}.jsonl` | Ejemplos que no pasaron validación + razón + respuesta cruda | Diagnóstico de la tasa de rechazo |

Fases disponibles:
- **v0 (piloto)**: ~101 ejemplos — 4 conceptos representativos (1 por nivel) + transversales reducidos. Para validar formato, tono y que el LoRA no degrade el conocimiento Python del modelo base.
- **v1 (producción)**: ~577 ejemplos — 30 conceptos completos + transversales completos. Primer LoRA desplegable.

---

## 3. Qué resuelve (lo que el fine-tuning enseña)

### 3.1 Voz y personalidad de Spoky
- Vocabulario del Lore: Contenedores de Energía, Medalla del Millón, Segundo Despegue,
  Radio de la Tripulación, Reactor de Constancia, Bitácora de Vuelo, Juramento del Cadete.
- «¡Waku Code!» solo en celebraciones (acierto, fin de tema).
- Emojis temáticos con moderación (🚀🛸📡🔋⚡🏅), máximo 2 por mensaje.
- **SPOKY_SYSTEM enriquecido** (~326 tokens): incluye backstory resumida (crash, 847.203
  fallos, radar), las 3 Leyes Físicas de Waku-9, las 6 mecánicas narrativas con nombre,
  la progresión de rangos, y las reglas de tono. Se embebe en cada ejemplo del JSONL para
  que el LoRA aprenda a responder condicionado al universo completo.
- **META_PROMPT con Lore completo** (~1.480 tokens): incluye backstory extendida, los 11
  rasgos de personalidad, sistemas de la nave mapeados a niveles, manejo de analogías con
  desvanecimiento por rango, y 4 few-shot examples de referencia (acierto, error,
  frustración, pista). Solo se usa durante la generación — no se embebe en el JSONL.

### 3.2 Formato WhatsApp
- Respuestas de 1-3 burbujas, máximo 350 caracteres por burbuja.
- Mensajes cortos, directos, una pregunta por turno.

### 3.3 Reflejos pedagógicos
- **Elogio de proceso**: nombra la estrategia o la persistencia, nunca la inteligencia.
  Frases prohibidas validadas: «eres un genio», «qué inteligente», «esto es fácil».
- **Error = avance**: +1 Medalla del Millón, explicar el porqué como descubrimiento.
  Nunca «incorrecto» ni «mal».
- **Regla socrática**: en escenarios de error, pista y re-explicación, Spoky señala
  dónde/por qué pero **no entrega la solución**; termina con pregunta para que el alumno
  intente. Validado: el último mensaje de Spoky debe terminar en `?`.
- **Manejo de analogías**: introduce el término real de Python en la misma explicación;
  señala el punto de ruptura cuando corresponde.
- **Desvanecimiento por rango**: a mayor nivel, más vocabulario técnico y menos metáfora
  (instruido en el META_PROMPT, no validable automáticamente — depende de curaduría).

### 3.4 Escenarios cubiertos (15 tipos)

**Ligados a concepto (7 × 30 conceptos):**
- Explicación inicial, re-explicación, acierto, error (×4 variantes), pista, sobreextensión de analogía, conversación multiturno.

**Transversales (8 escenarios):**
- Onboarding/Juramento, frustración/«no puedo», recordatorio, fuera de tema, progreso,
  fin de tema/rango, seguridad (derivar a adulto), OCR ilegible.

### 3.5 Diversidad del alumno
- 5 personas rotadas (10-14 años, tímida/entusiasta/apurada/curiosa/distraída).
- Typos, abreviaciones y emojis realistas de WhatsApp en los mensajes del alumno.

---

## 4. Qué NO resuelve (responsabilidad del system prompt / guardrails / sistema)

| Aspecto | Por qué NO lo cubre el LoRA | Dónde se resuelve |
|---|---|---|
| **Guardrails de seguridad (menores)** | Un LoRA puede fallar en distribución nueva; reglas de seguridad exigen garantía explícita, no estadística | System prompt + capa de clasificación externa (Doc 07) |
| **Alcance funcional** (no contestar fuera de Python) | El LoRA generaliza a partir de ~25 ejemplos de `fuera_tema`, pero no garantiza al 100% | Guardrail de alcance en system prompt + clasificador (Doc 07) |
| **Contexto dinámico** (nivel actual, rango, juramento, concepto en curso, datos del RAG) | Cambia por sesión; imposible de hornear en pesos fijos | Variables inyectadas en el system prompt en tiempo real |
| **Retención y privacidad de datos** (fotos, nombres de menores) | Es política del sistema, no comportamiento del modelo | Infraestructura (WhatsApp/Kapso) + políticas de datos |
| **Calidad del conocimiento Python** | El modelo base ya lo domina; re-entrenarlo con ejemplos simples (L0-L3) puede degradarlo (catastrophic forgetting) | El LoRA se entrena solo en estilo; el conocimiento se verifica con el test split + LLM as Judge |
| **Evaluación continua del tutor** | El LoRA no se evalúa a sí mismo | Golden dataset + LLM as Judge + Langfuse (fuera de este script) |
| **Decisiones de orquestación** (cuándo proponer ejercicio, cuándo subir de nivel, cuándo enviar recordatorio) | Son lógica de aplicación, no estilo | Agente orquestador (LangGraph) |

---

## 5. Validaciones automáticas del script

| Validación | Criterio de rechazo |
|---|---|
| Estructura JSON | Sin campo `messages` o formato inválido |
| Alternancia de roles | Dos mensajes seguidos del mismo rol |
| Inicio/fin | No empieza en `user` o no termina en `assistant` |
| Longitud por burbuja | Burbuja >350 caracteres |
| Cantidad de burbujas | Más de 3 burbujas por mensaje de Spoky |
| Frases prohibidas | «eres un genio», «qué inteligente», «esto es fácil», «incorrecto», «nakama», «waku waku» |
| Waku Code fuera de celebración | «waku code» en escenarios distintos de acierto/fin_tema/multiturno |
| Heurística socrática | En `error`, `pista` y `reexplicacion`, el último mensaje de Spoky no termina en `?` |

### Validaciones que NO hace (dependen de curaduría humana)

- **Apropiado para la edad**: el META_PROMPT lo instruye, pero no hay clasificador de edad integrado.
- **Corrección del Python**: el script no ejecuta el código de los ejemplos.
- **Desvanecimiento real de analogías por nivel**: instruido pero no medible automáticamente.
- **Diversidad real**: si el modelo genera ejemplos muy similares entre semillas, solo la revisión humana lo detecta.

---

## 6. Flujo de uso recomendado

```
1. --dry-run             Ver la matriz sin gastar API
2. --phase v0            Generar piloto (~101 ejemplos)
3. Curaduría manual      Revisar ~20 ejemplos aleatorios del master
                         (priorizar: sobreextension, seguridad, error)
4. Ajustar               Editar META_PROMPT o SPOKY_SYSTEM si el tono necesita corrección
5. --phase v1            Generar producción (~577 ejemplos)
6. Curaduría v1          Revisar rejected + muestreo del master
7. Entrenar LoRA         Usar train/val/test JSONL con el mismo SPOKY_SYSTEM
8. Evaluar               Test split + Golden Dataset (LLM as Judge)
9. Iterar                Si las métricas fallan, volver al paso 4
```

---

## 7. Dependencias y requisitos

- **Python 3.10+**
- **SDK**: `pip install anthropic`
- **API key**: `ANTHROPIC_API_KEY` en variables de entorno.
- **Modelo generador**: `claude-sonnet-4-6` por defecto (configurable en `GENERATOR_MODEL`).
  Recomendado: Sonnet para v0 (piloto), Opus 4.7/4.8 para v1 (producción).
- **Costo estimado** (con META_PROMPT enriquecido ~1.480 tokens input + ~1.200 output):
  - v0 con Sonnet 4.6: ~$0.50
  - v1 con Sonnet 4.6: ~$2.80
  - v1 con Opus 4.7: ~$12.50 (input $5/M + output $25/M)
- **Rate limit**: controlado con `--sleep` (default 0.4s entre llamadas).
