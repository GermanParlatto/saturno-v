"""Cliente del endpoint de Spoky (HF Inference Endpoints, API compatible OpenAI).

Sirve el modelo `spoky-qwen-merged-v2` con vLLM en /v1/chat/completions. A
diferencia del nodo `llm` (que usa ChatBedrockConverse), esto es httpx directo:
LangSmith no lo traza automáticamente, por eso `generar` va decorada con
@traceable.

La config se lee DENTRO de `generar`, no a nivel de módulo: así el cliente se
puede testear con sólo `monkeypatch.setenv`, sin necesitar el entorno al
importar (al contrario que `agents/nodes/llm.py`, que sí lee env al importar).
"""

import json
import os

import httpx
from langsmith import traceable

from shared.observability import logger


class SpokyError(Exception):
    """Base: cualquier fallo hablando con el endpoint de Spoky."""


class SpokyConfigError(SpokyError):
    """Falta SPOKY_ENDPOINT_URL o SPOKY_API_TOKEN en el entorno."""


class SpokyAuthError(SpokyError):
    """El endpoint rechazó la autenticación (401 / 403)."""


class SpokyRateLimitError(SpokyError):
    """Límite de peticiones alcanzado (429)."""


class SpokyUnavailableError(SpokyError):
    """Endpoint no disponible (502 / 503 / 504) — típico de un arranque en frío."""


class SpokyTimeoutError(SpokyError):
    """La petición superó el timeout configurado."""


class SpokyTransportError(SpokyError):
    """Error de red: DNS, conexión rechazada, etc."""


class SpokyResponseError(SpokyError):
    """Respuesta HTTP con error no cubierto arriba, o estructura/JSON inválidos."""


# Reintento único: el endpoint puede escalar a cero y devolver 503 mientras
# carga el modelo. Sólo se reintenta esto y el 429: un timeout ya quemó el
# presupuesto (ver docs/08-Configuracion.md) y un 401/403 no se arregla
# reintentando. Con BatchSize=3 en SQS, más reintentos amplificarían la
# latencia del lote entero si el endpoint está frío.
_MAX_INTENTOS = 2


def _config() -> tuple[str, str]:
    """Lee URL y token del entorno. Falla ruidosamente si falta alguno."""
    url = os.environ.get("SPOKY_ENDPOINT_URL")
    token = os.environ.get("SPOKY_API_TOKEN")
    if not url or not token:
        # Nunca se loguea el token: sólo qué falta.
        logger.error(
            "Configuración de Spoky incompleta",
            extra={"tiene_url": bool(url), "tiene_token": bool(token)},
        )
        raise SpokyConfigError("Missing SPOKY_ENDPOINT_URL or SPOKY_API_TOKEN")
    return url, token


def _clasificar(resp: httpx.Response) -> None:
    """Traduce el status HTTP a la excepción tipada correspondiente."""
    code = resp.status_code
    if code in (401, 403):
        raise SpokyAuthError(f"Autenticación rechazada por el endpoint ({code})")
    if code == 429:
        raise SpokyRateLimitError("Límite de peticiones alcanzado (429)")
    if code in (502, 503, 504):
        raise SpokyUnavailableError(f"Endpoint no disponible ({code})")
    if code >= 400:
        raise SpokyResponseError(f"Respuesta HTTP inesperada ({code})")


def _extraer_texto(resp: httpx.Response) -> str:
    """Valida la forma OpenAI y devuelve el contenido. Nunca loguea el cuerpo."""
    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        # resp.json() en un cuerpo no-JSON (p.ej. una página de error de un
        # proxy) lanza ValueError, no httpx.HTTPError: hay que envolverlo aquí
        # o se escaparía sin clasificar.
        raise SpokyResponseError("El endpoint devolvió un cuerpo no-JSON") from exc

    try:
        choice = payload["choices"][0]
        contenido = choice["message"]["content"]
        finish = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError) as exc:
        raise SpokyResponseError("Estructura de respuesta inválida") from exc

    if not isinstance(contenido, str) or not contenido.strip():
        raise SpokyResponseError("El endpoint devolvió contenido vacío")

    if finish == "length":
        # No es un error: preferimos un texto truncado con voz a perder la
        # voz de Spoky por completo. Queda registrado para poder subir
        # max_tokens si esto pasa a menudo (ver métrica FinalizerTruncado).
        logger.warning("Respuesta de Spoky truncada", extra={"finish_reason": finish})

    return contenido.strip()


@traceable(run_type="llm", name="finalizer-hf-endpoint")
def generar(mensajes: list[dict], *, max_tokens: int = 200, temperature: float = 0.6) -> str:
    """Llama al endpoint de Spoky y devuelve el texto generado.

    Args:
        mensajes: lista en formato OpenAI [{"role": ..., "content": ...}, ...].

    Raises:
        SpokyError: cualquier fallo (config, red, HTTP, estructura). El nodo
            finalizador captura la base y cae al borrador ante cualquiera.
    """
    url, token = _config()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "model": os.environ.get("SPOKY_MODEL_NAME", "spoky-qwen-merged-v2"),
        "messages": mensajes,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    timeout = httpx.Timeout(
        connect=5.0,
        read=float(os.environ.get("SPOKY_TIMEOUT_SECONDS", "25")),
        write=5.0,
        pool=5.0,
    )

    ultimo: SpokyError | None = None
    for intento in range(1, _MAX_INTENTOS + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise SpokyTimeoutError("Timeout llamando al endpoint de Spoky") from exc
        except httpx.HTTPError as exc:
            raise SpokyTransportError("Error de transporte hablando con Spoky") from exc

        # Igual que kapso_client: SOLO el status, jamás el cuerpo (contiene la
        # conversación de un menor).
        logger.debug("Spoky endpoint response", extra={"status_code": resp.status_code})

        try:
            _clasificar(resp)
            return _extraer_texto(resp)
        except (SpokyUnavailableError, SpokyRateLimitError) as exc:
            ultimo = exc
            logger.warning(
                "Fallo reintentable en Spoky",
                extra={"intento": intento, "tipo": type(exc).__name__},
            )

    assert ultimo is not None  # el bucle sólo termina así si ambos intentos fallaron
    raise ultimo
