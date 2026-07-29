"""Prueba manual de `send_media` contra un WhatsApp real. NO entra en CI ni en Lambda.

Responde la única pregunta de F2 que no se puede contestar leyendo código:
**¿Kapso acepta una URL externa en `link`, o exige subir el fichero antes y usar un
media ID?** Si estos envíos llegan, F3 puede construirse sobre `send_media` tal cual;
si Kapso los rechaza, hay que añadir un paso de upload ANTES de escribir el runner.

Uso:
    KAPSO_API_KEY=... uv run python tools/send-media-probe.py \
        --to +34600111222 --phone-number-id <id>

    ... --kind video      # probar un solo tipo

Los assets por defecto son los que HOY devuelven 200 en Contabo; 14 de los 43 dan 403
(entre ellos R0-01 y R0-02) y fallarían por el asset, no por el código.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import httpx  # noqa: E402

from shared.kapso_client import send_media  # noqa: E402

BASE = "https://usc1.contabostorage.com/efbb2fde41344653916ec481499f7b4b:waku-code/assets"

# Un asset accesible por cada media_kind. El cheatsheet (E1-07) da 403 hoy, así que para
# `document` se reutiliza un PNG que sí responde: lo que se prueba es el tipo de mensaje,
# no ese fichero en concreto.
CASOS = {
    "image": (f"{BASE}/E1-01.png", "Cómic de Spoky (prueba image)"),
    "video": (f"{BASE}/E1-03.mp4", "Vídeo de Spoky (prueba video)"),
    "document": (f"{BASE}/E1-04.png", "Chuleta de prueba (prueba document)"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Envía media de prueba por Kapso.")
    parser.add_argument("--to", required=True, help="Teléfono destino, formato +34...")
    parser.add_argument("--phone-number-id", required=True)
    parser.add_argument("--kind", choices=sorted(CASOS), help="Solo este tipo (por defecto, todos)")
    args = parser.parse_args()

    if not os.environ.get("KAPSO_API_KEY"):
        print("ERROR: falta KAPSO_API_KEY en el entorno.", file=sys.stderr)
        return 2

    kinds = [args.kind] if args.kind else list(CASOS)
    fallos = 0

    for kind in kinds:
        link, caption = CASOS[kind]
        print(f"\n--- {kind}: {link.rsplit('/', 1)[-1]}")
        try:
            send_media(args.phone_number_id, to=args.to, kind=kind, link=link, caption=caption)
            print("    OK: aceptado por Kapso (confirma en el móvil que LLEGA)")
        except httpx.HTTPStatusError as e:
            # No se aborta: un solo run debe dar el diagnóstico de los tres tipos.
            fallos += 1
            print(f"    FALLO {e.response.status_code}: {e.response.text[:500]}")
        except Exception as e:  # noqa: BLE001 — es una herramienta de diagnóstico
            fallos += 1
            print(f"    FALLO {type(e).__name__}: {e}")

    print(f"\n{len(kinds) - fallos}/{len(kinds)} aceptados por la API.")
    print("Aceptado != recibido: Meta descarga el fichero DESPUÉS de responder 200.")
    print("Si un tipo no llega al móvil pese al 200, el problema es el asset (403/formato).")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
