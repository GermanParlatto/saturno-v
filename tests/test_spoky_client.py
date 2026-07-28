"""Tests del cliente httpx del endpoint de Spoky."""

import httpx
import pytest
import respx

from shared.spoky_client import (
    SpokyAuthError,
    SpokyConfigError,
    SpokyRateLimitError,
    SpokyResponseError,
    SpokyTimeoutError,
    SpokyTransportError,
    generar,
)

URL = "https://fake-spoky.endpoints.huggingface.cloud/v1/chat/completions"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SPOKY_ENDPOINT_URL", URL)
    monkeypatch.setenv("SPOKY_API_TOKEN", "hf_faketoken123")


def _openai_response(content: str, finish_reason: str = "stop") -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}
        ]
    }


@respx.mock
def test_returns_content_on_valid_response():
    respx.post(URL).mock(return_value=httpx.Response(200, json=_openai_response("¡Waku Code!")))

    assert generar([{"role": "user", "content": "hola"}]) == "¡Waku Code!"


def test_raises_config_error_when_url_missing(monkeypatch):
    monkeypatch.delenv("SPOKY_ENDPOINT_URL", raising=False)

    with respx.mock:
        with pytest.raises(SpokyConfigError):
            generar([{"role": "user", "content": "hola"}])
        assert not respx.calls


def test_raises_config_error_when_token_missing(monkeypatch):
    monkeypatch.delenv("SPOKY_API_TOKEN", raising=False)

    with respx.mock:
        with pytest.raises(SpokyConfigError):
            generar([{"role": "user", "content": "hola"}])
        assert not respx.calls


@respx.mock
def test_sends_bearer_token_header():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_openai_response("ok")))

    generar([{"role": "user", "content": "hola"}])

    assert route.calls.last.request.headers["Authorization"] == "Bearer hf_faketoken123"


@respx.mock
def test_raises_auth_error_on_401():
    route = respx.post(URL).mock(return_value=httpx.Response(401))

    with pytest.raises(SpokyAuthError):
        generar([{"role": "user", "content": "hola"}])
    assert route.call_count == 1  # sin reintento


@respx.mock
def test_raises_auth_error_on_403():
    route = respx.post(URL).mock(return_value=httpx.Response(403))

    with pytest.raises(SpokyAuthError):
        generar([{"role": "user", "content": "hola"}])
    assert route.call_count == 1


@respx.mock
def test_raises_rate_limit_error_on_429():
    route = respx.post(URL).mock(return_value=httpx.Response(429))

    with pytest.raises(SpokyRateLimitError):
        generar([{"role": "user", "content": "hola"}])
    assert route.call_count == 2  # reintentable


@respx.mock
def test_retries_once_on_503_then_succeeds():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=_openai_response("de vuelta en órbita")),
        ]
    )

    assert generar([{"role": "user", "content": "hola"}]) == "de vuelta en órbita"
    assert route.call_count == 2


@respx.mock
def test_raises_timeout_error():
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("timed out"))

    with pytest.raises(SpokyTimeoutError):
        generar([{"role": "user", "content": "hola"}])
    assert route.call_count == 1  # sin reintento: ya se quemó el presupuesto


@respx.mock
def test_raises_transport_error_on_connect_error():
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("connection refused"))

    with pytest.raises(SpokyTransportError):
        generar([{"role": "user", "content": "hola"}])
    assert route.call_count == 1


@respx.mock
def test_raises_response_error_on_missing_choices():
    respx.post(URL).mock(return_value=httpx.Response(200, json={}))

    with pytest.raises(SpokyResponseError):
        generar([{"role": "user", "content": "hola"}])


@respx.mock
def test_raises_response_error_on_empty_content():
    respx.post(URL).mock(return_value=httpx.Response(200, json=_openai_response("   ")))

    with pytest.raises(SpokyResponseError):
        generar([{"role": "user", "content": "hola"}])


@respx.mock
def test_raises_response_error_on_non_json_body():
    respx.post(URL).mock(return_value=httpx.Response(200, content=b"<html>not json</html>"))

    with pytest.raises(SpokyResponseError):
        generar([{"role": "user", "content": "hola"}])


@respx.mock
def test_never_logs_token(caplog):
    respx.post(URL).mock(return_value=httpx.Response(200, json=_openai_response("ok")))

    with caplog.at_level("DEBUG"):
        generar([{"role": "user", "content": "hola"}])

    for record in caplog.records:
        assert "hf_faketoken123" not in record.getMessage()


@respx.mock
def test_never_logs_token_on_config_error(monkeypatch, caplog):
    monkeypatch.setenv("SPOKY_API_TOKEN", "hf_secreto_no_debe_aparecer")

    import contextlib

    with caplog.at_level("DEBUG"), contextlib.suppress(Exception):
        generar([{"role": "user", "content": "hola"}])

    for record in caplog.records:
        assert "hf_secreto_no_debe_aparecer" not in record.getMessage()
