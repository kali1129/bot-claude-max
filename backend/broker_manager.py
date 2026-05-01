"""broker_manager.py — gestión de credenciales MT5 per-user.

Encapsula las operaciones contra la collection ``broker_creds``:
  - save_creds(user_id, login, password, server, path, demo)
  - get_creds(user_id) → datos PARA UI (no incluye password en plain)
  - get_decrypted(user_id) → password en plain (solo para conexiones live)
  - delete_creds(user_id)
  - test_connection(login, password, server, path) → ok/error sin guardar

Schema en Mongo:
    {
      _id: ObjectId,
      user_id: str,
      broker: "mt5_xm",
      mt5_login: int,
      mt5_server: str,
      mt5_path: str | None,
      is_demo: bool,
      pwd_encrypted: str,           # crypto_box.encrypt(password)
      created_at: iso,
      updated_at: iso,
      last_test_at: iso | null,
      last_test_ok: bool | null,
      last_test_error: str | null,
    }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import crypto_box

log = logging.getLogger("broker_manager")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ad_for(user_id: str) -> bytes:
    """Associated data: bindea el blob al user_id. Si alguien copia el
    encrypted blob a otro user, descifrar va a fallar."""
    return f"user:{user_id}".encode("utf-8")


def _doc_to_public(doc: dict) -> dict:
    """Devuelve la versión segura para el cliente (sin password ni hash)."""
    if not doc:
        return None
    return {
        "broker": doc.get("broker", "mt5_xm"),
        "mt5_login": doc.get("mt5_login"),
        "mt5_server": doc.get("mt5_server"),
        "mt5_path": doc.get("mt5_path"),
        "is_demo": bool(doc.get("is_demo", True)),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "last_test_at": doc.get("last_test_at"),
        "last_test_ok": doc.get("last_test_ok"),
        "last_test_error": doc.get("last_test_error"),
        "has_creds": True,
    }


async def get_creds(db, user_id: str) -> Optional[dict]:
    """Retorna info de las creds (sin password) o None si no hay."""
    if db is None:
        return None
    doc = await db.broker_creds.find_one({"user_id": user_id})
    return _doc_to_public(doc)


async def has_creds(db, user_id: str) -> bool:
    if db is None:
        return False
    n = await db.broker_creds.count_documents({"user_id": user_id})
    return n > 0


async def get_decrypted_password(db, user_id: str) -> Optional[str]:
    """SOLO para usar al iniciar conexión MT5. NO devolver al cliente."""
    if db is None:
        return None
    doc = await db.broker_creds.find_one({"user_id": user_id})
    if not doc:
        return None
    enc = doc.get("pwd_encrypted")
    if not enc:
        return None
    try:
        return crypto_box.decrypt(enc, associated_data=_ad_for(user_id))
    except crypto_box.CryptoError as exc:
        log.warning("decrypt failed for user %s: %s", user_id, exc)
        return None


async def save_creds(
    db,
    user_id: str,
    *,
    mt5_login: int,
    mt5_password: str,
    mt5_server: str,
    mt5_path: Optional[str] = None,
    is_demo: bool = True,
) -> dict:
    """Inserta o actualiza las creds para un usuario. Encripta password."""
    if db is None:
        raise RuntimeError("DB no disponible")
    encrypted = crypto_box.encrypt(mt5_password,
                                    associated_data=_ad_for(user_id))
    now = _now_iso()
    update = {
        "$set": {
            "user_id": user_id,
            "broker": "mt5_xm",
            "mt5_login": int(mt5_login),
            "mt5_server": mt5_server.strip(),
            "mt5_path": (mt5_path or None) and mt5_path.strip(),
            "is_demo": bool(is_demo),
            "pwd_encrypted": encrypted,
            "updated_at": now,
        },
        "$setOnInsert": {
            "created_at": now,
        },
    }
    res = await db.broker_creds.update_one(
        {"user_id": user_id}, update, upsert=True
    )
    log.info("broker creds saved for user=%s upserted=%s",
             user_id, res.upserted_id is not None)
    doc = await db.broker_creds.find_one({"user_id": user_id})
    return _doc_to_public(doc)


async def delete_creds(db, user_id: str) -> bool:
    """Elimina las creds. Retorna True si había algo, False si nada."""
    if db is None:
        return False
    res = await db.broker_creds.delete_one({"user_id": user_id})
    return res.deleted_count > 0


async def record_test_result(db, user_id: str, *,
                              ok: bool, error: Optional[str] = None) -> None:
    """Persiste el resultado del último test de conexión."""
    if db is None:
        return
    await db.broker_creds.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "last_test_at": _now_iso(),
                "last_test_ok": bool(ok),
                "last_test_error": (error or None) if not ok else None,
            }
        },
    )


async def ensure_indexes(db) -> None:
    """Índices para la collection broker_creds."""
    if db is None:
        return
    try:
        await db.broker_creds.create_index("user_id", unique=True)
    except Exception as exc:
        log.warning("broker_creds index create failed: %s", exc)


# ─────────────────────────── live test (no save) ───────────────────────────
# Esta función prueba creds CONTRA MT5 sin almacenarlas. Útil para el
# botón "Probar conexión" en el wizard de onboarding.
#
# IMPORTANTE: corre en el proceso del backend (Linux). Si el backend NO
# tiene MetaTrader5 instalado (lo está en Wine), retornamos un error
# explicativo para que el cliente no se confunda.

async def test_connection_live(*, mt5_login: int, mt5_password: str,
                                mt5_server: str,
                                mt5_path: Optional[str] = None) -> dict:
    """Intenta conectar a MT5 con las creds dadas. Best-effort.

    En el backend Linux NO podemos importar MetaTrader5 (es Windows-only).
    Por eso, este test delega a un endpoint del trading-mt5-mcp (Wine
    Python) si está disponible, o retorna un placeholder informativo.

    Por ahora retornamos un placeholder — la integración real con Wine
    Python para test es FASE 3.
    """
    # FASE 2 placeholder: NO conectamos realmente, solo validamos shape.
    if not mt5_login or not mt5_server or not mt5_password:
        return {
            "ok": False,
            "error": "login, password y server son obligatorios",
        }
    if mt5_login <= 0:
        return {"ok": False, "error": "mt5_login debe ser un número positivo"}
    if len(mt5_password) < 4:
        return {"ok": False, "error": "password parece muy corto"}
    # Heurística simple: server debe parecer un nombre de XM, FBS, etc.
    if not any(
        marker in mt5_server.lower()
        for marker in ["xm", "mt5", "real", "demo", "icmarkets", "fbs"]
    ):
        return {
            "ok": True,
            "warning": (
                "no pude verificar el servidor — guardé las creds pero "
                "tendrás que probar al iniciar el bot. Server inusual: "
                + mt5_server
            ),
            "note": "FASE 3: conexión real con Wine pendiente",
        }
    return {
        "ok": True,
        "note": (
            "Validación básica OK. La conexión real con MT5 se va a "
            "verificar cuando arranques el bot (FASE 3 — pronto)."
        ),
    }
