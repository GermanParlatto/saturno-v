"""Tests de `send_media`: envío de media por URL externa a través de Kapso.

`send_text` no se toca en F2 y tiene su propio contrato; aquí solo se cubre la función
nueva. Lo que se verifica es la FORMA del payload de Meta, porque un error ahí no se
manifiesta como excepción sino como un mensaje que nunca llega al alumno.
"""

from unittest.mock import MagicMock

import httpx
import pytest
import respx

from shared.kapso_client import send_media

PHONE_NUMBER_ID = "123456789"
URL = f"https://api.kapso.ai/meta/whatsapp/v24.0/{PHONE_NUMBER_ID}/messages"
COMIC = "https://usc1.contabostorage.com/bucket:waku-code/assets/E1-01.png"
VIDEO = "https://usc1.contabostorage.com/bucket:waku-code/assets/E1-03.mp4"
CHEATSHEET = "https://usc1.contabostorage.com/bucket:waku-code/assets/E1-07.png"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KAPSO_API_KEY", "kapso_faketoken123")


def _enviado(route) -> dict:
    import json

    return json.loads(route.calls.last.request.content)


@respx.mock
def test_image_payload():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "1"}]}))

    send_media(PHONE_NUMBER_ID, to="+34600111222", kind="image", link=COMIC)

    assert _enviado(route) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "+34600111222",
        "type": "image",
        "image": {"link": COMIC},
    }


@respx.mock
def test_video_payload_with_caption():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={}))

    send_media(PHONE_NUMBER_ID, to="+34600111222", kind="video", link=VIDEO, caption="¡Mira esto!")

    body = _enviado(route)
    assert body["type"] == "video"
    assert body["video"] == {"link": VIDEO, "caption": "¡Mira esto!"}


@respx.mock
def test_caption_omitido_si_es_vacio():
    # Un caption "" no debe viajar como clave vacía: Meta la rechaza.
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={}))

    send_media(PHONE_NUMBER_ID, to="+34600111222", kind="image", link=COMIC, caption="")

    assert "caption" not in _enviado(route)["image"]


@respx.mock
def test_document_deriva_filename_de_la_url():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={}))

    send_media(PHONE_NUMBER_ID, to="+34600111222", kind="document", link=CHEATSHEET)

    assert _enviado(route)["document"] == {"link": CHEATSHEET, "filename": "E1-07.png"}


@respx.mock
def test_document_respeta_filename_explicito():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={}))

    send_media(
        PHONE_NUMBER_ID,
        to="+34600111222",
        kind="document",
        link=CHEATSHEET,
        filename="Chuleta de Python.png",
    )

    assert _enviado(route)["document"]["filename"] == "Chuleta de Python.png"


@respx.mock
def test_filename_solo_en_document():
    # `filename` no es válido en image/video: Meta devuelve 400 si se envía.
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={}))

    send_media(PHONE_NUMBER_ID, to="+34600111222", kind="image", link=COMIC, filename="x.png")

    assert "filename" not in _enviado(route)["image"]


@respx.mock
def test_envia_la_cabecera_api_key():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={}))

    send_media(PHONE_NUMBER_ID, to="+34600111222", kind="image", link=COMIC)

    assert route.calls.last.request.headers["X-API-Key"] == "kapso_faketoken123"


def test_kind_invalido_no_llega_a_hacer_peticion():
    # media_kind mal derivado en el catálogo: se detecta aquí, no en Meta.
    with respx.mock:
        with pytest.raises(ValueError, match="kind no soportado"):
            send_media(PHONE_NUMBER_ID, to="+34600111222", kind="gif", link=COMIC)
        assert not respx.calls


def test_falta_api_key(monkeypatch):
    monkeypatch.delenv("KAPSO_API_KEY", raising=False)

    with respx.mock:
        with pytest.raises(RuntimeError):
            send_media(PHONE_NUMBER_ID, to="+34600111222", kind="image", link=COMIC)
        assert not respx.calls


@respx.mock
def test_error_de_meta_relanza_y_registra_el_motivo(monkeypatch):
    # El caso real: asset con 403 en Contabo -> Meta no puede descargarlo.
    #
    # Se mockea el logger en vez de leer stdout o caplog: Powertools captura sys.stdout
    # al construirse (antes de que pytest lo sustituya) y serializa los `extra` allí, así
    # que ninguna de las dos capturas de pytest los ve. Con el mock, la aserción es sobre
    # lo que el código PIDE registrar, que es justamente el contrato que interesa.
    logger_mock = MagicMock()
    monkeypatch.setattr("shared.kapso_client.logger", logger_mock)
    respx.post(URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "Media download failed", "code": 131053}}
        )
    )

    with pytest.raises(httpx.HTTPStatusError):
        send_media(PHONE_NUMBER_ID, to="+34600111222", kind="image", link=COMIC)

    registrado = logger_mock.error.call_args.kwargs["extra"]
    assert "Media download failed" in registrado["body"]
    assert registrado["status_code"] == 400
    assert registrado["link"] == COMIC
