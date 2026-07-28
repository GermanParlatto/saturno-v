"""Nodo LLM: el único nodo funcional de la Fase 5.

Usa ChatBedrockConverse, que por debajo llama a la MISMA Converse API que
montaste a mano en la Fase 4. No cambias de tecnología: envuelves lo que ya
entiendes con la interfaz de LangChain.

Como recibe la lista COMPLETA de mensajes (el historial que el checkpointer
recuperó), el modelo ve el contexto previo. Ahí está la memoria.
"""

import os

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage

from agents.state import AgentState

SYSTEM_PROMPT = (
    "Eres un tutor de Python que enseña a niños de 10 a 14 años por WhatsApp. "
    "Tu única responsabilidad es que el CONTENIDO sea correcto, claro y adecuado "
    "a esa edad. El tono y la personalidad los aplica otro componente después: "
    "no intentes ser gracioso ni adoptar ningún personaje.\n"
    "Responde en español, de forma breve y directa (2-3 frases como máximo). "
    "Usa el término real de Python siempre que introduzcas un concepto. "
    "Si el alumno comete un error, explica QUÉ falla y POR QUÉ, sin juzgar.\n"
    "No uses markdown para dar formato al texto: nada de encabezados, "
    "tablas ni enlaces con corchetes. "
    "SÍ debes usar comillas invertidas para el código: `codigo` para fragmentos "
    "dentro de una frase y un bloque con tres comillas invertidas para código de "
    "varias líneas, indicando el lenguaje en la primera línea."
)

# A nivel de módulo: se crea una vez por contenedor, no en cada invocación.
llm = ChatBedrockConverse(
    model=os.environ["MODEL_ID"],
    region_name=os.environ.get("AWS_REGION", "eu-west-1"),
    max_tokens=500,
)


def llm_node(state: AgentState) -> dict:
    """Invoca el modelo con el historial y devuelve su respuesta."""

    respuesta = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), *state["messages"]])

    # Devolvemos sólo lo nuevo: el reducer `add_messages` lo añade al historial.
    return {"messages": [respuesta]}
