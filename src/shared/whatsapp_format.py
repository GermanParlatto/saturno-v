"""Formatea texto Markdown-ish del LLM al formato de chat que WhatsApp renderiza.

WhatsApp NO soporta bloques de código ```triple``` (los muestra como texto literal,
backticks incluidos): el único monoespaciado que entiende es `backtick simple`, y para
negrita usa `*negrita*` en vez de `**negrita**`. El trabajo real es: (a) bajar los
bloques ```triple``` (con o sin tag de lenguaje) a `backtick simple`, (b) adaptar la
negrita fuera de código, (c) envolver en backticks el código suelto que el modelo no
delimitó.

Arquitectura: segmentar -> transformar -> reensamblar. Nunca se aplica una regex sobre
el texto completo: primero se separan los tramos ya delimitados (bloques, inline, URLs),
que se copian tal cual, y sólo la prosa restante pasa por las transformaciones. Así la
heurística de código nunca corre dentro de código ya delimitado, y las URLs nunca se
manglean, por construcción.
"""

import logging
import os
import re

# logging estándar (no shared.observability): este módulo es stdlib puro a propósito,
# para que los tests corran sin instalar aws-lambda-powertools (ver requirements-dev.txt).
logger = logging.getLogger(__name__)

# El cierre de un bloque debe ser un ``` que empieza su propia línea (convención real
# de Markdown): así se distingue de un ``` que aparece como CONTENIDO a mitad de línea
# (p.ej. dentro de `print('```')`). El cuerpo, además, no puede contener ninguna línea
# que empiece con ```: si la contuviera, ese ``` interior sería el cierre "real" más
# cercano, y preferimos no tratar el ``` inicial como apertura antes que tragarnos un
# bloque real más adelante (nunca "de acuerdo" implícito con un bloque sin cerrar).
# La apertura NO exige estar al inicio de línea: un fence puede abrirse a mitad de
# frase ("Aquí tienes: ```python\n...").
_FENCE_MULTI = r"```[^\n`]*\n(?:(?!\n[ \t]*```).)*\n[ \t]*```(?=[ \t]*(?:\n|$))"
_FENCE_ONE = r"```[^\n`]+```"

_PROTECTED = re.compile(
    rf"(?P<fence>{_FENCE_MULTI}|{_FENCE_ONE})"
    r"|(?P<inline>`[^`\n]+`)"
    r"|(?P<url>(?:https?://|www\.)\S+)",
    re.DOTALL,
)

_FENCE_LANG = re.compile(r"\A```[^\n`]*(?=\n)")
_FENCE_CLOSE = re.compile(r"\n[ \t]*```[ \t]*\Z")

_BOLD_MD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
# Exige un espacio dentro del contenido: una frase de negrita casi siempre tiene más
# de una palabra. Esto excluye a propósito identificadores dunder de Python de una
# sola palabra (`__init__`, `__str__`, `__name__`), que de otro modo se corromperían
# (`__init__` -> `*init*`) al aparecer sueltos en la prosa. El costo es no convertir
# `__palabra__` de una sola palabra a negrita; se prefiere ese falso negativo a
# corromper código.
_BOLD_UND = re.compile(r"__(?=\S)([^_\n]*\s[^_\n]*)(?<=\S)__", re.DOTALL)
_HEADING = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+")
_BULLET = re.compile(r"(?m)^([ \t]*)[-*][ \t]+")

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_CALLNAME = rf"(?:{_IDENT}\.)*{_IDENT}"
_NUM = r"-?\d+(?:\.\d+)?"
_STR = r"'[^'\n]*'|\"[^\"\n]*\""
# Un argumento puede ser, además de identificador/número/cadena, una llamada anidada
# de un nivel (p.ej. `print(foo(x))`): sin esto, CALL sólo casaba la llamada más
# interna y dejaba la exterior suelta, produciendo un envoltorio parcial y roto
# (`print(`foo(x)`)` en vez de envolver toda la expresión o dejarla intacta).
_NESTED_CALL = rf"{_CALLNAME}\([^()\n]*\)"
_ARG = rf"(?:{_NESTED_CALL}|{_IDENT}(?:\.{_IDENT})*|{_NUM}|{_STR})"
_ARGS = rf"(?:{_ARG}(?:\s*,\s*{_ARG})*)?"

# Llamada a función/método: print(x), console.log('h'), math.sqrt(16), print(foo(x)).
_CALL = re.compile(rf"(?<![\w`.])({_CALLNAME}\(\s*{_ARGS}\s*\))")
# Sentencia de declaración/importación al inicio de línea: def f(x):, import os.
# Se corta antes de un comentario `#` (nunca válido dentro de la sintaxis de
# def/class/import/from en sí), para no tragarse texto humano tras el código
# ("def f(x): return x  # importante" no debe envolver "# importante").
_STMT = re.compile(rf"(?m)^[ \t]*((?:def|class|import|from)\s+{_IDENT}[^\n#]*?)[ \t]*(?:#.*)?$")


def _enable_code_heuristic() -> bool:
    # Se lee en cada llamada (no se cachea a nivel de módulo) para que el interruptor
    # de emergencia WHATSAPP_CODE_HEURISTIC=0 surta efecto sin reiniciar el contenedor
    # Lambda: un valor cacheado en el import no vería el cambio hasta un cold start.
    return os.environ.get("WHATSAPP_CODE_HEURISTIC", "1") != "0"


def _downgrade_fence(fence: str) -> str:
    if fence.startswith("```") and fence.endswith("```") and "\n" not in fence:
        # Fence de una línea, p.ej. ```py```: sin cuerpo, no lleva tag de lenguaje.
        return fence
    # WhatsApp no tiene noción de bloque de código: no renderiza ``` como
    # delimitador (con o sin tag de lenguaje), sobrevive tal cual, visible como
    # texto literal. El único monoespaciado que WhatsApp entiende es el backtick
    # simple, así que el fence completo se baja a una sola comilla en apertura y
    # cierre en vez de solo pelarle el tag de lenguaje.
    body = _FENCE_LANG.sub("", fence, count=1)
    body = _FENCE_CLOSE.sub("\n", body)
    return f"`{body}`"


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
        # m.group() puede incluir un comentario '# ...' tras la sentencia (ver _STMT):
        # sólo el grupo 1 se envuelve en backticks, el resto del match (el comentario,
        # si lo hay) se conserva tal cual a continuación.
        parts.append(f"`{m.group(1)}`{m.group()[len(m.group(1)) :]}")
        pos = m.end()
    if pos < len(text):
        parts.append(_CALL.sub(r"`\1`", text[pos:]))
    return "".join(parts)


def _format_prose(text: str) -> str:
    text = _BOLD_MD.sub(r"*\1*", text)
    text = _BOLD_UND.sub(r"*\1*", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub(r"\1• ", text)
    if _enable_code_heuristic():
        text = _wrap_code_heuristic(text)
    return text


def format_for_whatsapp(text: str) -> str:
    """Convierte texto Markdown-ish en formato de chat de WhatsApp.

    Pura, sin I/O. Nunca lanza: ante cualquier duda, se prefiere devolver la entrada
    sin tocar antes que arriesgar un mensaje corrupto. Si eso ocurre, se registra
    (con `logger.exception`) para que un fallo real de la heurística sea visible en
    producción en vez de degradar en silencio.
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
                parts.append(_downgrade_fence(m.group()))
            else:
                parts.append(m.group())
            pos = m.end()
        if pos < len(text):
            parts.append(_format_prose(text[pos:]))
        return "".join(parts)
    except Exception:
        logger.exception("Fallo formateando mensaje para WhatsApp; se envía sin formatear")
        return text
