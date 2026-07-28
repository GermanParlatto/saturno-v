import pytest

from shared import whatsapp_format
from shared.whatsapp_format import format_for_whatsapp

TRUE_POSITIVES_INLINE = [
    "print(x)",
    "print()",
    "console.log('hola')",
    "suma(a, b)",
    "math.sqrt(16)",
    "obj.metodo(1, 2)",
]

# def/class/import/from son sentencias de línea completa: así es como el LLM las
# emitiría en la práctica (en su propia línea, no incrustadas a mitad de frase).
TRUE_POSITIVES_STATEMENT = [
    "def saluda(nombre):",
    "import os",
    "from math import sqrt",
]

FALSE_POSITIVE_PROSE = [
    "Llama a mamá (o a papá) si te trabas.",
    "Saturno (el planeta) tiene anillos.",
    "Hola(muy buenas) que tal",
    "los niños(pequeños) juegan",
    "cumpleaños(fiesta)",
    "adiós(hasta luego)",
    "¿Qué (esto)?",
    "texto(una cosa muy larga aqui)",
    "dato(a b)",
    "2 * 3 * 4",
    "Es un bucle (repite cosas) sencillo.",
    "La variable (o caja) guarda datos.",
]


@pytest.mark.parametrize("code", TRUE_POSITIVES_INLINE)
def test_heuristic_wraps_undelimited_inline_code(code):
    text = f"Usa {code} aquí."
    result = format_for_whatsapp(text)
    assert f"`{code}`" in result


@pytest.mark.parametrize("code", TRUE_POSITIVES_STATEMENT)
def test_heuristic_wraps_undelimited_statement_code(code):
    text = f"Prueba esto:\n{code}\nY listo."
    result = format_for_whatsapp(text)
    assert f"`{code}`" in result


@pytest.mark.parametrize("prose", FALSE_POSITIVE_PROSE)
def test_heuristic_does_not_touch_spanish_prose(prose):
    assert format_for_whatsapp(prose) == prose


def test_heuristic_idempotent_on_already_backticked_code():
    once = format_for_whatsapp("Usa `print(x)` para mostrar.")
    twice = format_for_whatsapp(once)
    assert once == twice


def test_heuristic_does_not_run_inside_fence_or_inline_or_url():
    text = "```\nprint(x)\n```\n`suma(a, b)`\nhttps://ej.com/print(x)"
    assert format_for_whatsapp(text) == text


def test_heuristic_can_be_disabled(monkeypatch):
    monkeypatch.setattr(whatsapp_format, "ENABLE_CODE_HEURISTIC", False)
    text = "Usa print(x) para mostrar."
    assert format_for_whatsapp(text) == text

    # El resto de transformaciones (negrita, tag de lenguaje) se siguen aplicando.
    assert format_for_whatsapp("Esto es **importante**.") == "Esto es *importante*."
    assert format_for_whatsapp("```py\ncode\n```") == "```\ncode\n```"
