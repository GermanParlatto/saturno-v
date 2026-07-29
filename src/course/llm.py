"""Los dos modelos del motor, tras una interfaz común.

    EvaluatorModel (Bedrock)  -> responde de la CORRECCIÓN del contenido
    SpokyVoice (endpoint HF)  -> responde del TONO

Es la misma división que ya usa el grafo legacy (`agents/nodes/llm.py` +
`finalizer.py`), y existe por una razón concreta: el LoRA de Spoky es un 2B entrenado
para hablar como el personaje, no para juzgar si un `print()` está bien escrito.

`generar_borrador` es el único punto donde el motor llama a un modelo de contenido. Ese
es el swap: cuando el fine-tuned esté listo, se cambia la implementación aquí y ni
`evaluate.py` ni el runner se enteran.
"""

import json
import os
import re

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage

from shared.observability import logger

_MAX_TOKENS = 500

# Caché por contenedor: construir el cliente en cada invocación es latencia regalada.
_evaluador: ChatBedrockConverse | None = None


def _modelo() -> ChatBedrockConverse:
    global _evaluador
    if _evaluador is None:
        _evaluador = ChatBedrockConverse(
            model=os.environ["MODEL_ID"],
            region_name=os.environ.get("AWS_REGION", "eu-west-1"),
            max_tokens=_MAX_TOKENS,
        )
    return _evaluador


def generar_borrador(system: str, instruccion: str) -> str:
    """Texto del modelo de contenido. Sin voz todavía: eso lo pone `aplicar_voz`."""
    respuesta = _modelo().invoke([SystemMessage(content=system), HumanMessage(content=instruccion)])
    return respuesta.text.strip()


# Un modelo instruido para devolver JSON a veces lo envuelve en ```json ... ```.
# Preferimos tolerarlo a fallar: la alternativa es perder el turno de un alumno.
_JSON_BLOQUE = re.compile(r"\{.*\}", re.DOTALL)


def generar_json(system: str, instruccion: str) -> dict | None:
    """Igual que `generar_borrador`, pero espera un objeto JSON.

    Devuelve `None` si el modelo no produjo JSON utilizable. El llamador decide qué
    hacer con eso: en evaluación, la respuesta segura es tratar el intento como no
    concluyente, nunca como fallo del alumno.
    """
    crudo = generar_borrador(system, instruccion)
    match = _JSON_BLOQUE.search(crudo)
    if not match:
        logger.warning("El evaluador no devolvió JSON", extra={"longitud": len(crudo)})
        return None
    try:
        datos = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("JSON del evaluador inválido")
        return None
    return datos if isinstance(datos, dict) else None
