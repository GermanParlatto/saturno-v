"""Tests del nodo finalizador: sustitución de borrador, fallback y salvaguardas.

No importa `agents.graph` a nivel de módulo: eso arrastraría `agents.nodes.llm`,
que lee `os.environ["MODEL_ID"]` al importar y lanzaría KeyError sin ese env.
"""

from unittest.mock import patch

import httpx
import respx
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from agents.nodes.finalizer import finalizer
from shared.spoky_client import SpokyAuthError, SpokyResponseError, SpokyTimeoutError

URL = "https://fake-spoky.endpoints.huggingface.cloud/v1/chat/completions"


def _openai_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}


def test_replaces_draft_with_spoky_version():
    draft = AIMessage(
        content="Un bucle while repite mientras la condición sea verdadera.", id="abc"
    )

    with patch(
        "agents.nodes.finalizer.spoky_client.generar",
        return_value="¡Waku Code! El bucle sigue mientras la condición aguante.",
    ):
        result = finalizer({"messages": [HumanMessage(content="qué es un while"), draft]})

    assert result["messages"][0] == RemoveMessage(id="abc")
    assert isinstance(result["messages"][1], AIMessage)
    assert (
        result["messages"][1].content == "¡Waku Code! El bucle sigue mientras la condición aguante."
    )


def test_skips_endpoint_call_when_no_messages():
    with patch("agents.nodes.finalizer.spoky_client.generar") as mock_generar:
        result = finalizer({"messages": []})

    mock_generar.assert_not_called()
    assert result == {}


def test_skips_endpoint_call_when_draft_is_blank():
    with patch("agents.nodes.finalizer.spoky_client.generar") as mock_generar:
        result = finalizer({"messages": [AIMessage(content="   ")]})

    mock_generar.assert_not_called()
    assert result == {}


def test_falls_back_to_draft_on_timeout():
    draft = AIMessage(content="Respuesta del tutor.", id="abc")

    with patch(
        "agents.nodes.finalizer.spoky_client.generar", side_effect=SpokyTimeoutError("timeout")
    ):
        result = finalizer({"messages": [draft]})

    assert result == {}


def test_falls_back_to_draft_on_auth_error():
    draft = AIMessage(content="Respuesta del tutor.", id="abc")

    with patch("agents.nodes.finalizer.spoky_client.generar", side_effect=SpokyAuthError("401")):
        result = finalizer({"messages": [draft]})

    assert result == {}


def test_falls_back_to_draft_on_invalid_structure():
    draft = AIMessage(content="Respuesta del tutor.", id="abc")

    with patch(
        "agents.nodes.finalizer.spoky_client.generar", side_effect=SpokyResponseError("bad shape")
    ):
        result = finalizer({"messages": [draft]})

    assert result == {}


def test_falls_back_on_unexpected_exception():
    """CUALQUIER fallo, no solo SpokyError, debe caer al borrador."""
    draft = AIMessage(content="Respuesta del tutor.", id="abc")

    with patch(
        "agents.nodes.finalizer.spoky_client.generar", side_effect=RuntimeError("bug inesperado")
    ):
        result = finalizer({"messages": [draft]})

    assert result == {}


def test_falls_back_when_code_block_altered():
    draft = AIMessage(content="Usa `print(x)` para mostrar el valor.", id="abc")

    # La reescritura pierde el fragmento de código exacto -> se descarta.
    with patch(
        "agents.nodes.finalizer.spoky_client.generar",
        return_value="Usa print(y) para mostrar el valor.",
    ):
        result = finalizer({"messages": [draft]})

    assert result == {}


def test_keeps_rewrite_when_code_block_preserved():
    draft = AIMessage(content="Usa `print(x)` para mostrar el valor.", id="abc")

    with patch(
        "agents.nodes.finalizer.spoky_client.generar",
        return_value="¡Waku Code! Usa `print(x)` para mostrarlo en pantalla.",
    ):
        result = finalizer({"messages": [draft]})

    assert result["messages"][1].content == "¡Waku Code! Usa `print(x)` para mostrarlo en pantalla."


def test_appends_without_remove_when_draft_has_no_id():
    draft = AIMessage(content="Respuesta del tutor.")  # sin id

    with patch("agents.nodes.finalizer.spoky_client.generar", return_value="¡Waku Code!"):
        result = finalizer({"messages": [draft]})

    assert result["messages"] == [AIMessage(content="¡Waku Code!")]


def test_sends_spoky_system_and_draft_in_payload():
    draft = AIMessage(content="Un for recorre cada elemento de la lista.", id="abc")

    with patch(
        "agents.nodes.finalizer.spoky_client.generar", return_value="¡Waku Code!"
    ) as mock_generar:
        finalizer({"messages": [draft]})

    (mensajes,), kwargs = mock_generar.call_args
    assert mensajes[0]["role"] == "system"
    from agents.prompts import SPOKY_SYSTEM

    assert mensajes[0]["content"] == SPOKY_SYSTEM
    assert mensajes[1]["role"] == "user"
    assert "Un for recorre cada elemento de la lista." in mensajes[1]["content"]


@respx.mock
def test_graph_replaces_draft_end_to_end(monkeypatch):
    """llm -> finalizer sobre add_messages real, con el endpoint mockeado."""
    monkeypatch.setenv("SPOKY_ENDPOINT_URL", URL)
    monkeypatch.setenv("SPOKY_API_TOKEN", "hf_faketoken123")
    respx.post(URL).mock(
        return_value=httpx.Response(
            200, json=_openai_response("¡Waku Code! Un for recorre la lista.")
        )
    )

    from langgraph.graph import END, START, StateGraph

    from agents.state import AgentState

    def _stub_llm_node(state):
        return {
            "messages": [
                AIMessage(content="Un for recorre cada elemento de la lista.", id="draft-1")
            ]
        }

    g = StateGraph(AgentState)
    g.add_node("llm", _stub_llm_node)
    g.add_node("finalizer", finalizer)
    g.add_edge(START, "llm")
    g.add_edge("llm", "finalizer")
    g.add_edge("finalizer", END)
    graph = g.compile()

    result = graph.invoke({"messages": [HumanMessage(content="qué es un for")]})

    assert len(result["messages"]) == 2
    assert isinstance(result["messages"][0], HumanMessage)
    assert isinstance(result["messages"][1], AIMessage)
    assert result["messages"][1].content == "¡Waku Code! Un for recorre la lista."
