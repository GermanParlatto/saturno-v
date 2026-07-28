from shared.whatsapp_format import normalize_content


def test_str_passthrough():
    assert normalize_content("hola") == "hola"


def test_single_text_block():
    assert normalize_content([{"type": "text", "text": "hola"}]) == "hola"


def test_multiple_text_blocks_concatenated_without_separator():
    content = [{"type": "text", "text": "hola "}, {"type": "text", "text": "mundo"}]
    assert normalize_content(content) == "hola mundo"


def test_non_text_block_discarded():
    content = [
        {"type": "reasoning_content", "text": "pensando..."},
        {"type": "text", "text": "respuesta"},
    ]
    assert normalize_content(content) == "respuesta"


def test_empty_list_is_empty_string():
    assert normalize_content([]) == ""


def test_none_falls_back_to_str():
    assert normalize_content(None) == "None"


def test_unexpected_object_falls_back_to_str_without_raising():
    assert normalize_content(42) == "42"
