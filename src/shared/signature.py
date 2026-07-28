"""Verificacion de la firma HMAC-SHA256 del webhook de Kapso.

IMPORTANTE: calcular el HMAC sobre el CUERPO CRUDO (bytes tal cual llegaron),
nunca sobre un JSON re-serializado (el orden de claves cambiaria la firma).
"""

import hashlib
import hmac


def verify_signature(raw: bytes, signature: str, secret: str) -> bool:
    """Verifica si el cuerpo está firmado correctamente con el webhook de Kapso."""
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
