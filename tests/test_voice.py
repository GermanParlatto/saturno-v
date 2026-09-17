"""Tests de la voz de Spoky: reescritura, fallback al borrador y salvaguarda del código.

`aplicar_voz` es la única ruta por la que el alumno recibe texto generado, así que lo
que se fija aquí es un CONTRATO DE DEGRADACIÓN: pase lo que pase con el endpoint, la
función devuelve algo enviable y nunca lanza.
"""

from unittest.mock import patch

import httpx
import pytest
import respx

from shared.prompts import SPOKY_SYSTEM
from shared.spoky_client import SpokyAuthError, SpokyResponseError, SpokyTimeoutError
from shared.voice import MAX_TOKENS, TEMPERATURE, aplicar_voz, codigo_preservado

URL = "https://fake-spoky.endpoints.huggingface.cloud/v1/chat/completions"


def _openai_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}


def test_returns_spoky_rewrite_on_success():
    with patch(
        "shared.voice.spoky_client.generar",
        return_value="¡Waku Code! El bucle sigue mientras la condición aguante.",
    ):
        final = aplicar_voz("Un bucle while repite mientras la condición sea verdadera.")

    assert final == "¡Waku Code! El bucle sigue mientras la condición aguante."


@pytest.mark.parametrize("borrador", ["", "   ", "\n\t ", None])
def test_skips_endpoint_when_draft_blank(borrador):
    """Sin borrador no hay nada que reescribir: ni se llama al endpoint."""
    with patch("shared.voice.spoky_client.generar") as mock_generar:
        final = aplicar_voz(borrador)

    mock_generar.assert_not_called()
    assert final == ""


@pytest.mark.parametrize(
    "error",
    [
        SpokyTimeoutError("timeout"),
        SpokyAuthError("401"),
        SpokyResponseError("bad shape"),
        # CUALQUIER fallo, no solo SpokyError: fija el `except Exception` de voice.py.
        RuntimeError("bug inesperado"),
    ],
)
def test_falls_back_to_draft_on_any_failure(error):
    borrador = "Respuesta del tutor."

    with patch("shared.voice.spoky_client.generar", side_effect=error):
        final = aplicar_voz(borrador)

    assert final == borrador


def test_falls_back_when_code_altered():
    """Si la reescritura toca el código, sale el borrador: código roto > sin personaje."""
    borrador = "Usa `print(x)` para mostrar el valor."

    with patch(
        "shared.voice.spoky_client.generar",
        return_value="Usa print(y) para mostrar el valor.",
    ):
        final = aplicar_voz(borrador)

    assert final == borrador


def test_keeps_rewrite_when_code_preserved():
    borrador = "Usa `print(x)` para mostrar el valor."

    with patch(
        "shared.voice.spoky_client.generar",
        return_value="¡Waku Code! Usa `print(x)` para mostrarlo en pantalla.",
    ):
        final = aplicar_voz(borrador)

    assert final == "¡Waku Code! Usa `print(x)` para mostrarlo en pantalla."


def test_sends_spoky_system_and_draft_in_payload():
    borrador = "Un for recorre cada elemento de la lista."

    with patch("shared.voice.spoky_client.generar", return_value="¡Waku Code!") as mock_generar:
        aplicar_voz(borrador)

    (mensajes,), kwargs = mock_generar.call_args
    assert mensajes[0]["role"] == "system"
    assert mensajes[0]["content"] == SPOKY_SYSTEM
    assert mensajes[1]["role"] == "user"
    assert borrador in mensajes[1]["content"]
    assert kwargs["max_tokens"] == MAX_TOKENS
    assert kwargs["temperature"] == TEMPERATURE


@pytest.mark.parametrize(
    ("borrador", "final", "esperado"),
    [
        ("Usa `print(x)` aquí.", "¡Waku! Usa `print(x)` ahora.", True),
        ("Usa `print(x)` aquí.", "¡Waku! Usa `print(y)` ahora.", False),
        ("Prueba:\n```\nfor i in x:\n```", "¡Waku!\n```\nfor i in x:\n```", True),
        ("Prueba:\n```\nfor i in x:\n```", "¡Waku!\n```\nfor j in x:\n```", False),
        ("Sin código ninguno.", "¡Waku Code! Sin código ninguno.", True),
    ],
)
def test_codigo_preservado(borrador, final, esperado):
    assert codigo_preservado(borrador, final) is esperado


@respx.mock
def test_end_to_end_through_real_spoky_client(monkeypatch):
    """aplicar_voz -> spoky_client.generar -> httpx, con el endpoint mockeado."""
    monkeypatch.setenv("SPOKY_ENDPOINT_URL", URL)
    monkeypatch.setenv("SPOKY_API_TOKEN", "hf_faketoken123")
    respx.post(URL).mock(
        return_value=httpx.Response(
            200, json=_openai_response("¡Waku Code! Un for recorre la lista.")
        )
    )

    final = aplicar_voz("Un for recorre cada elemento de la lista.")

    assert final == "¡Waku Code! Un for recorre la lista."
