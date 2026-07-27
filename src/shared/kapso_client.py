"""Cliente de la API REST de Kapso para ENVIAR mensajes (cabecera X-API-Key)."""

import os

import httpx


def send_text(phone_number_id: str, to: str, body: str):
    url = f"https://api.kapso.ai/meta/whatsapp/v24.0/{phone_number_id}/messages"
    headers = {
        "X-API-Key": os.environ["KAPSO_API_KEY"],
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
        print(resp.status_code, resp.text)
        resp.raise_for_status()
