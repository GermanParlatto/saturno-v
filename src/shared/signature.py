"""Verificacion de la firma HMAC-SHA256 del webhook de Kapso.

IMPORTANTE: calcular el HMAC sobre el CUERPO CRUDO (bytes tal cual llegaron),
nunca sobre un JSON re-serializado (el orden de claves cambiaria la firma).
"""
import hmac
import hashlib

def verify_signature(raw: bytes, signature: str, secret: str) -> bool:
    """Verifica si el cuercpo es firmado correctamante con webhook de kapso"""
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
