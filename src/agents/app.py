"""Entrypoint del grafo: la única función que el worker necesita conocer."""

from agents.graph import build_graph

# Se construye UNA VEZ por contenedor Lambda (no en cada invocación).
GRAPH = build_graph()


def run_graph(user_message: str, thread_id: str) -> str:
    """Ejecuta el grafo para una conversación concreta y devuelve el texto final.

    Args:
        user_message: lo que escribió el usuario.
        thread_id: identificador estable de la conversación. Usamos el número de
            teléfono: es la clave natural del hilo, la misma que ya usábamos para
            idempotencia. El checkpointer lo emplea como clave de partición.
    """
    config = {"configurable": {"thread_id": thread_id}}

    result = GRAPH.invoke({"messages": [("user", user_message)]}, config)

    # `.text` (de BaseMessage) aplana el .content a str: con ChatBedrockConverse
    # puede venir como str o como lista de bloques de contenido.
    return result["messages"][-1].text
