from shared.whatsapp_format import format_for_whatsapp


def test_fence_preserves_newlines_and_indentation():
    text = "Mira:\n```python\ndef f(x):\n    if x:\n        return 1\n```\nListo."
    expected = "Mira:\n```\ndef f(x):\n    if x:\n        return 1\n```\nListo."
    assert format_for_whatsapp(text) == expected


def test_fence_strips_language_tag_variants():
    assert format_for_whatsapp("```javascript\ncode\n```") == "```\ncode\n```"
    assert format_for_whatsapp("```py\ncode\n```") == "```\ncode\n```"
    assert format_for_whatsapp("```\ncode\n```") == "```\ncode\n```"


def test_fence_one_liner_untouched():
    assert format_for_whatsapp("```py```") == "```py```"
    assert format_for_whatsapp("```x```") == "```x```"


def test_fence_with_nested_triple_backtick_not_split():
    text = "```py\nprint('```')\n```"
    expected = "```\nprint('```')\n```"
    assert format_for_whatsapp(text) == expected


def test_fence_opened_mid_line_after_prose_is_protected():
    # La apertura ``` no tiene por qué estar al inicio de línea: es un patrón real
    # de salida del LLM ("Aquí tienes: ```python\n...").
    text = "Aquí tienes: ```python\nclass Foo:\n    def __init__(self):\n        pass\n```"
    expected = "Aquí tienes: ```\nclass Foo:\n    def __init__(self):\n        pass\n```"
    assert format_for_whatsapp(text) == expected


def test_unclosed_fence_does_not_swallow_a_later_real_fence():
    text = "Abre ```\ny sigue\nmas\n```js\nreal code\n```"
    result = format_for_whatsapp(text)
    # El ``` suelto queda como prosa literal; el bloque real más adelante se protege
    # y pierde su tag de lenguaje como cualquier otro fence bien formado.
    assert result == "Abre ```\ny sigue\nmas\n```\nreal code\n```"


def test_fence_special_chars_not_transformed():
    text = "```\n*bold* _it_ **b** # h - item\n```"
    assert format_for_whatsapp(text) == text


def test_inline_mid_sentence():
    text = "Usa `print(x)` para mostrar el valor."
    assert format_for_whatsapp(text) == text


def test_multiple_inline_in_one_line():
    text = "Compara `a` con `b` y usa `c` si hace falta."
    assert format_for_whatsapp(text) == text


def test_no_code_text_unchanged():
    text = "Hola, esto es una respuesta normal sin nada especial."
    assert format_for_whatsapp(text) == text


def test_urls_with_special_chars_intact():
    text = "Mira https://ejemplo.com/a_b*c y también www.foo.com/x_y."
    assert format_for_whatsapp(text) == text


def test_emoji_accents_and_punctuation_intact():
    text = "¿Qué tal? ¡Genial! Los niños jugarán con ñoños 🎉🐍 mañana."
    assert format_for_whatsapp(text) == text


def test_bold_md_to_whatsapp():
    assert format_for_whatsapp("Esto es **importante** hoy.") == "Esto es *importante* hoy."


def test_bold_underscore_to_whatsapp():
    assert format_for_whatsapp("Esto es __muy importante__ hoy.") == "Esto es *muy importante* hoy."


def test_bold_underscore_single_word_left_untouched_to_protect_dunders():
    # __word__ de una sola palabra no se convierte a propósito: así se evitan falsos
    # positivos sobre identificadores dunder de Python (__init__, __str__, __name__)
    # que de otro modo se corromperían al aparecer sueltos en la prosa.
    assert format_for_whatsapp("Esto es __importante__ hoy.") == "Esto es __importante__ hoy."
    assert format_for_whatsapp("dunder tipico: __name__") == "dunder tipico: __name__"


def test_bold_lookaround_does_not_match_math():
    assert format_for_whatsapp("a ** b ** c") == "a ** b ** c"
    assert format_for_whatsapp("2 * 3 * 4") == "2 * 3 * 4"


def test_bold_markers_inside_fence_or_inline_not_converted():
    assert format_for_whatsapp("```\n**x**\n```") == "```\n**x**\n```"
    assert format_for_whatsapp("`**x**`") == "`**x**`"


def test_unbalanced_backticks_degrade_gracefully():
    text = "Backtick suelto ` sin cerrar, nada más."
    assert format_for_whatsapp(text) == text

    text2 = "Abre ``` sin cerrar el bloque."
    assert format_for_whatsapp(text2) == text2


def test_headings_stripped():
    assert format_for_whatsapp("# Título\nTexto") == "Título\nTexto"
    assert format_for_whatsapp("## Sub\nTexto") == "Sub\nTexto"


def test_bullets_converted():
    assert format_for_whatsapp("- uno\n- dos") == "• uno\n• dos"
    assert format_for_whatsapp("* uno\n* dos") == "• uno\n• dos"


def test_empty_and_whitespace_input():
    assert format_for_whatsapp("") == ""
    assert format_for_whatsapp("   ") == "   "
    assert format_for_whatsapp("\n\n") == "\n\n"
