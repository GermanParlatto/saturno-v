"""Formatea texto Markdown-ish del LLM al formato de chat que WhatsApp renderiza.

WhatsApp usa la MISMA sintaxis de comillas invertidas que Markdown para monoespaciado
(`inline` y ```bloque```), pero `**negrita**` en vez de eso usa `*negrita*`. El trabajo
real es: (a) quitar el tag de lenguaje de los bloques de código, (b) adaptar la negrita
fuera de código, (c) envolver en backticks el código suelto que el modelo no delimitó.

Arquitectura: segmentar -> transformar -> reensamblar. Nunca se aplica una regex sobre
el texto completo: primero se separan los tramos ya delimitados (bloques, inline, URLs),
que se copian tal cual, y sólo la prosa restante pasa por las transformaciones. Así la
heurística de código nunca corre dentro de código ya delimitado, y las URLs nunca se
manglean, por construcción.
"""

import os
import re

# Ancladas a inicio de línea (^```): una tirada de backticks a mitad de línea (p.ej.
# dentro de un `print('```')`) no puede cerrar el bloque por accidente.
_PROTECTED = re.compile(
    r"(?P<fence>(?m:^)```[^\n`]*\n.*?\n(?m:^)```|```[^\n`]*```)"
    r"|(?P<inline>`[^`\n]+`)"
    r"|(?P<url>(?:https?://|www\.)\S+)",
    re.DOTALL,
)

_FENCE_LANG = re.compile(r"\A```[^\n`]*(?=\n)")

_BOLD_MD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_BOLD_UND = re.compile(r"__(?=\S)(.+?)(?<=\S)__", re.DOTALL)
_HEADING = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+")
_BULLET = re.compile(r"(?m)^([ \t]*)[-*][ \t]+")

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_ARG = r"(?:[A-Za-z_][A-Za-z0-9_.]*|-?\d+(?:\.\d+)?|'[^'\n]*'|\"[^\"\n]*\")"
_ARGS = rf"(?:{_ARG}(?:\s*,\s*{_ARG})*)?"

# Llamada a función/método: print(x), console.log('h'), math.sqrt(16).
_CALL = re.compile(rf"(?<![\w`.])((?:{_IDENT}\.)*{_IDENT}\(\s*{_ARGS}\s*\))")
# Sentencia de declaración/importación al inicio de línea: def f(x):, import os.
_STMT = re.compile(rf"(?m)^[ \t]*((?:def|class|import|from)\s+{_IDENT}[^\n]*)$")

# Interruptor de emergencia: si la heurística se porta mal en producción, se desactiva
# con WHATSAPP_CODE_HEURISTIC=0 sin desplegar código nuevo.
ENABLE_CODE_HEURISTIC = os.environ.get("WHATSAPP_CODE_HEURISTIC", "1") != "0"


def _strip_fence_lang(fence: str) -> str:
    if fence.startswith("```") and fence.endswith("```") and "\n" not in fence:
        # Fence de una línea, p.ej. ```py```: sin cuerpo, no lleva tag de lenguaje.
        return fence
    return _FENCE_LANG.sub("```", fence, count=1)


def _wrap_code_heuristic(text: str) -> str:
    """Envuelve código sin delimitar en backticks.

    STMT y CALL se aplican sobre tramos disjuntos: una línea ya envuelta por STMT
    (p.ej. `def f(x):`) no vuelve a pasar por CALL, o quedaría doblemente envuelta
    (`` `def `f(x)`:` ``, backticks anidados y rotos).
    """
    parts: list[str] = []
    pos = 0
    for m in _STMT.finditer(text):
        if m.start() > pos:
            parts.append(_CALL.sub(r"`\1`", text[pos : m.start()]))
        parts.append(_STMT.sub(r"`\1`", m.group()))
        pos = m.end()
    if pos < len(text):
        parts.append(_CALL.sub(r"`\1`", text[pos:]))
    return "".join(parts)


def _format_prose(text: str) -> str:
    text = _BOLD_MD.sub(r"*\1*", text)
    text = _BOLD_UND.sub(r"*\1*", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub(r"\1• ", text)
    if ENABLE_CODE_HEURISTIC:
        text = _wrap_code_heuristic(text)
    return text


def format_for_whatsapp(text: str) -> str:
    """Convierte texto Markdown-ish en formato de chat de WhatsApp.

    Pura, sin I/O. Nunca lanza: ante cualquier duda, se prefiere devolver la entrada
    (o el segmento) sin tocar antes que arriesgar un mensaje corrupto.
    """
    if not text:
        return text

    try:
        parts: list[str] = []
        pos = 0
        for m in _PROTECTED.finditer(text):
            if m.start() > pos:
                parts.append(_format_prose(text[pos : m.start()]))
            if m.lastgroup == "fence":
                parts.append(_strip_fence_lang(m.group()))
            else:
                parts.append(m.group())
            pos = m.end()
        if pos < len(text):
            parts.append(_format_prose(text[pos:]))
        return "".join(parts)
    except Exception:
        return text


def normalize_content(content: object) -> str:
    """Aplana el `.content` de un mensaje de LangChain a texto plano.

    Con ChatBedrockConverse, `.content` puede ser un `str` o una lista de bloques
    (dicts). Se concatenan sólo los bloques de texto, sin separador (Bedrock ya los
    entrega troceados; añadir "\\n" inventaría saltos de línea que no existían).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
            if not isinstance(block, dict) or block.get("type", "text") == "text"
        )
    return str(content)
