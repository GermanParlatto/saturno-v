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
    assert format_for_whatsapp("Esto es __importante__ hoy.") == "Esto es *importante* hoy."


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
