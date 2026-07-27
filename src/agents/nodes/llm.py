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
    "Eres un asistente que atiende por WhatsApp. "
    "Responde en español, breve y claro (2-3 frases como máximo). "
    "No uses markdown ni listas: WhatsApp no las renderiza bien."
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
