"""Cliente de la API REST de Kapso para ENVIAR mensajes (cabecera X-API-Key)."""

import os

import httpx

from shared.observability import logger


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
