"""Cliente de la API REST de Kapso para ENVIAR mensajes (cabecera X-API-Key).

Kapso proxea la Cloud API de Meta, así que el payload es el de Meta tal cual.
"""

import os
from urllib.parse import unquote, urlparse

import httpx

from shared.observability import logger

# media_kind del catálogo -> tipo de mensaje de Meta. Es 1:1 a propósito: el seeder ya
# hizo la traducción desde `tb_nodes.type` (comic->image, gif->image, cheatsheet->
# document), y duplicar aquí ese mapeo crearía dos sitios donde equivocarse.
MEDIA_KINDS = ("image", "video", "document")


def send_text(phone_number_id: str, to: str, body: str):
    url = f"https://api.kapso.ai/meta/whatsapp/v24.0/{phone_number_id}/messages"
    api_key = os.environ.get("KAPSO_API_KEY")
    if not api_key:
        logger.error("Falta KAPSO_API_KEY en el entorno")
        raise RuntimeError("Missing KAPSO_API_KEY environment variable")
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        logger.debug("Kapso API response", extra={"status_code": resp.status_code})
        resp.raise_for_status()


def _filename_from(link: str) -> str:
    """Nombre que WhatsApp muestra en un `document`. Sin él aparece un genérico."""
    return unquote(urlparse(link).path.rsplit("/", 1)[-1]) or "documento"


def send_media(
    phone_number_id: str,
    to: str,
    kind: str,
    link: str,
    caption: str | None = None,
    filename: str | None = None,
):
    """Envía media por URL EXTERNA (los assets viven en Contabo, no se suben a Meta).

    `kind` es el `media_kind` del catálogo: image | video | document. Meta descarga el
    fichero desde `link` al recibir la petición, así que la URL debe ser públicamente
    accesible y respetar los límites de Meta (imagen 5MB, vídeo 16MB, documento 100MB).
    Un asset con 403 o un formato no soportado se manifiesta como un 400 de esta llamada,
    no como un fallo silencioso.
    """
    if kind not in MEDIA_KINDS:
        # Antes de la llamada HTTP: un kind inválido es un error de datos del catálogo
        # (media_kind mal derivado), no algo que deba viajar a la API para que la rechace.
        raise ValueError(f"kind no soportado: {kind!r}. Esperado uno de {MEDIA_KINDS}")

    url = f"https://api.kapso.ai/meta/whatsapp/v24.0/{phone_number_id}/messages"
    api_key = os.environ.get("KAPSO_API_KEY")
    if not api_key:
        logger.error("Falta KAPSO_API_KEY en el entorno")
        raise RuntimeError("Missing KAPSO_API_KEY environment variable")
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }

    media: dict[str, str] = {"link": link}
    if caption:
        media["caption"] = caption
    if kind == "document":
        media["filename"] = filename or _filename_from(link)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": kind,
        kind: media,
    }

    # 15s, no 10: el POST solo entrega la URL, pero Kapso proxea a Meta y puede validar
    # el asset en la misma petición.
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        logger.debug(
            "Kapso API response (media)",
            extra={"status_code": resp.status_code, "kind": kind},
        )
        if resp.is_error:
            # El cuerpo trae el motivo real de Meta ("Media download failed", formato no
            # soportado, tamaño). Sin esto, un asset roto es un 400 opaco en CloudWatch.
            # Aquí el cuerpo es seguro de loguear: son URLs públicas, no texto del alumno.
            logger.error(
                "Kapso rechazó el envío de media",
                extra={"status_code": resp.status_code, "body": resp.text[:1000], "link": link},
            )
        resp.raise_for_status()
