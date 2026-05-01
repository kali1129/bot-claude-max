"""crypto_box.py — encripta/desencripta credenciales sensibles del usuario
(passwords MT5, tokens broker, etc.) con AES-256-GCM.

Diseño:
  - Master key viene de env ``MASTER_ENCRYPTION_KEY`` (base64-url, 32 bytes).
    Si no está definida, el módulo genera una al arranque y la loggea —
    esto invalida todo el storage previo (usuarios tendrán que re-conectar
    MT5). Para producción, definir ``MASTER_ENCRYPTION_KEY`` en .env y
    NUNCA committearla.
  - Cada blob encriptado tiene su propio nonce de 12 bytes (96 bits) —
    standard GCM. Nonce + ciphertext + auth tag se serializan en un solo
    string base64.
  - Formato: ``<nonce_b64>:<ciphertext_b64>``
  - ``encrypt(plaintext: str) → str`` y ``decrypt(blob: str) → str``.
  - Errores de descifrado (clave cambiada, blob corrupto) → ``CryptoError``.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("crypto_box")


class CryptoError(Exception):
    """Error de cifrado/descifrado. Indica que el blob no se puede leer
    con la master key actual (clave rotada / corrupto / formato malo)."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def _resolve_master_key() -> bytes:
    """Carga la clave maestra del env o genera una efímera al arranque."""
    raw = (os.environ.get("MASTER_ENCRYPTION_KEY") or "").strip()
    if raw:
        try:
            key = _b64url_decode(raw)
            if len(key) != 32:
                raise ValueError(f"key debe tener 32 bytes, tiene {len(key)}")
            return key
        except Exception as exc:
            log.error("MASTER_ENCRYPTION_KEY inválida: %s — generando una "
                      "efímera (storage previo invalidado)", exc)

    # Efímera — solo para dev. Loggeamos UNA vez con warning fuerte.
    key = secrets.token_bytes(32)
    log.warning(
        "⚠️  MASTER_ENCRYPTION_KEY no configurada. Generada efímera. "
        "Las credenciales encriptadas anteriormente ya NO se pueden leer. "
        "Para producción, agregar a backend/.env: "
        "MASTER_ENCRYPTION_KEY=%s",
        _b64url_encode(key),
    )
    return key


_MASTER_KEY: Optional[bytes] = None


def _get_aesgcm() -> AESGCM:
    global _MASTER_KEY
    if _MASTER_KEY is None:
        _MASTER_KEY = _resolve_master_key()
    return AESGCM(_MASTER_KEY)


def encrypt(plaintext: str, *, associated_data: Optional[bytes] = None) -> str:
    """Encripta plaintext (UTF-8). Retorna ``<nonce_b64>:<ct_b64>``.

    ``associated_data`` opcional se autentica pero no se cifra. Útil para
    bindear el ciphertext a un user_id (si alguien copia el blob a otro
    user, descifrar va a fallar)."""
    if not isinstance(plaintext, str):
        raise TypeError("plaintext debe ser str")
    aes = _get_aesgcm()
    nonce = secrets.token_bytes(12)
    ad = associated_data or b""
    try:
        ct = aes.encrypt(nonce, plaintext.encode("utf-8"), ad)
    except Exception as exc:
        raise CryptoError(f"encrypt failed: {exc}") from exc
    return f"{_b64url_encode(nonce)}:{_b64url_encode(ct)}"


def decrypt(blob: str, *, associated_data: Optional[bytes] = None) -> str:
    """Descifra un blob producido por ``encrypt``. Lanza ``CryptoError``
    si el formato es inválido, la clave cambió, o el AD no coincide."""
    if not isinstance(blob, str) or ":" not in blob:
        raise CryptoError("formato inválido — se esperaba 'nonce:ct'")
    parts = blob.split(":", 1)
    try:
        nonce = _b64url_decode(parts[0])
        ct = _b64url_decode(parts[1])
    except Exception as exc:
        raise CryptoError(f"base64 decode failed: {exc}") from exc
    if len(nonce) != 12:
        raise CryptoError(f"nonce debe ser 12 bytes, es {len(nonce)}")
    aes = _get_aesgcm()
    ad = associated_data or b""
    try:
        pt = aes.decrypt(nonce, ct, ad)
    except Exception as exc:
        raise CryptoError(
            "no se pudo descifrar — clave maestra cambió o blob corrupto"
        ) from exc
    return pt.decode("utf-8")


def health() -> dict:
    """Diagnóstico: si la master key está configurada o es efímera."""
    raw = (os.environ.get("MASTER_ENCRYPTION_KEY") or "").strip()
    return {
        "master_key_from_env": bool(raw),
        "warning": (
            None
            if raw
            else "Master key efímera — definir MASTER_ENCRYPTION_KEY para persistencia"
        ),
    }


def mask(value: str, keep: int = 3) -> str:
    """Helper: muestra primeros ``keep`` chars + asteriscos. Para UI."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)
