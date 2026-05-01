"""broker_manager.py — gestión de credenciales MT5 per-user.

Multi-cuenta: cada usuario puede tener UNA cuenta DEMO + UNA cuenta REAL
conectadas al mismo tiempo. Solo UNA está marcada como ``is_active`` —
ese es el conjunto de credenciales que el bot usa cuando arranca o tras
un switch.

Schema en Mongo (collection ``broker_creds``):
    {
      _id, user_id, broker: "mt5_xm",
      mt5_login, mt5_server, mt5_path,
      is_demo: bool,                # demo vs real
      is_active: bool,              # cuál usa el bot ahora
      pwd_encrypted: str,           # crypto_box.encrypt(password)
      created_at, updated_at,
      last_test_at, last_test_ok, last_test_error
    }

Constraint: único por (user_id, is_demo). Eso permite max 2 docs por user
(1 demo + 1 real). Solo UNO puede tener is_active=true por user.
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
    """Associated data — bindea el blob al user_id."""
    return f"user:{user_id}".encode("utf-8")


def _doc_to_public(doc: dict) -> dict:
    """Versión segura para el cliente (sin password)."""
    if not doc:
        return None
    return {
        "id": str(doc.get("_id")) if doc.get("_id") else None,
        "broker": doc.get("broker", "mt5_xm"),
        "mt5_login": doc.get("mt5_login"),
        "mt5_server": doc.get("mt5_server"),
        "mt5_path": doc.get("mt5_path"),
        "is_demo": bool(doc.get("is_demo", True)),
        "is_active": bool(doc.get("is_active", False)),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "last_test_at": doc.get("last_test_at"),
        "last_test_ok": doc.get("last_test_ok"),
        "last_test_error": doc.get("last_test_error"),
    }


# ─────────────────────────── lectura ───────────────────────────

async def list_creds(db, user_id: str) -> list[dict]:
    """Lista todas las cuentas conectadas (DEMO + REAL si las dos).
    Cuenta activa primero."""
    if db is None:
        return []
    cursor = db.broker_creds.find({"user_id": user_id})
    docs = await cursor.to_list(length=10)
    out = [_doc_to_public(d) for d in docs]
    # active first, luego demo, luego real
    out.sort(key=lambda d: (not d.get("is_active"), not d.get("is_demo")))
    return out


async def get_creds(db, user_id: str, *, is_demo: bool | None = None) -> Optional[dict]:
    """Retorna las creds de un tipo específico, o las activas si is_demo
    es None. Sin password en plain."""
    if db is None:
        return None
    if is_demo is None:
        # Compatibilidad: si nadie especifica, retorna la activa
        return await get_active_creds(db, user_id)
    doc = await db.broker_creds.find_one({"user_id": user_id, "is_demo": bool(is_demo)})
    return _doc_to_public(doc)


async def get_active_creds(db, user_id: str) -> Optional[dict]:
    """Retorna la cuenta marcada como is_active=true. None si no hay."""
    if db is None:
        return None
    doc = await db.broker_creds.find_one({"user_id": user_id, "is_active": True})
    if doc:
        return _doc_to_public(doc)
    # Fallback: si tiene cuentas pero ninguna activa (migración pre-multi),
    # devolver la primera y marcarla como activa.
    doc = await db.broker_creds.find_one({"user_id": user_id})
    if not doc:
        return None
    await db.broker_creds.update_one(
        {"_id": doc["_id"]}, {"$set": {"is_active": True}}
    )
    log.info("auto-activate first creds for user=%s is_demo=%s",
             user_id, doc.get("is_demo"))
    doc["is_active"] = True
    return _doc_to_public(doc)


async def has_creds(db, user_id: str) -> bool:
    if db is None:
        return False
    n = await db.broker_creds.count_documents({"user_id": user_id})
    return n > 0


async def has_active_creds(db, user_id: str) -> bool:
    """¿Hay al menos una cuenta marcada is_active?"""
    if db is None:
        return False
    n = await db.broker_creds.count_documents(
        {"user_id": user_id, "is_active": True}
    )
    return n > 0


async def get_decrypted_password(db, user_id: str,
                                   *, is_demo: bool | None = None) -> Optional[str]:
    """SOLO para iniciar conexión MT5. Si is_demo es None, usa la activa."""
    if db is None:
        return None
    query = {"user_id": user_id}
    if is_demo is None:
        query["is_active"] = True
    else:
        query["is_demo"] = bool(is_demo)
    doc = await db.broker_creds.find_one(query)
    if not doc:
        # Fallback como en get_active_creds
        if is_demo is None:
            doc = await db.broker_creds.find_one({"user_id": user_id})
            if not doc:
                return None
        else:
            return None
    enc = doc.get("pwd_encrypted")
    if not enc:
        return None
    try:
        return crypto_box.decrypt(enc, associated_data=_ad_for(user_id))
    except crypto_box.CryptoError as exc:
        log.warning("decrypt failed for user %s: %s", user_id, exc)
        return None


# ─────────────────────────── escritura ───────────────────────────

async def save_creds(
    db,
    user_id: str,
    *,
    mt5_login: int,
    mt5_password: str,
    mt5_server: str,
    mt5_path: Optional[str] = None,
    is_demo: bool = True,
    set_active: bool = True,
) -> dict:
    """Inserta o actualiza las creds para un (user_id, is_demo).
    Si ``set_active=True`` (default) y no había cuenta activa, esta queda
    como activa. Si ya hay otra cuenta activa, queda inactiva por default
    (el usuario debe llamar /switch explícitamente).
    """
    if db is None:
        raise RuntimeError("DB no disponible")
    encrypted = crypto_box.encrypt(mt5_password,
                                    associated_data=_ad_for(user_id))
    now = _now_iso()

    has_any_active = await has_active_creds(db, user_id)
    # Si no había NINGUNA activa, esta nueva queda activa. Si ya había
    # otra activa, esta queda inactiva (usuario hace switch luego).
    will_be_active = set_active and not has_any_active

    update = {
        "$set": {
            "user_id": user_id,
            "broker": "mt5_xm",
            "mt5_login": int(mt5_login),
            "mt5_server": mt5_server.strip(),
            "mt5_path": (mt5_path or None) and mt5_path.strip(),
            "is_demo": bool(is_demo),
            "is_active": will_be_active,
            "pwd_encrypted": encrypted,
            "updated_at": now,
        },
        "$setOnInsert": {
            "created_at": now,
        },
    }
    res = await db.broker_creds.update_one(
        {"user_id": user_id, "is_demo": bool(is_demo)},
        update, upsert=True,
    )
    log.info("broker creds saved user=%s is_demo=%s active=%s upserted=%s",
             user_id, is_demo, will_be_active, res.upserted_id is not None)

    doc = await db.broker_creds.find_one(
        {"user_id": user_id, "is_demo": bool(is_demo)}
    )
    return _doc_to_public(doc)


async def set_active(db, user_id: str, *, is_demo: bool) -> Optional[dict]:
    """Marca la cuenta (user_id, is_demo) como activa, las demás del
    user como inactivas. Retorna la cuenta que quedó activa o None
    si no existe."""
    if db is None:
        return None
    target = await db.broker_creds.find_one(
        {"user_id": user_id, "is_demo": bool(is_demo)}
    )
    if not target:
        return None
    # Inactivar todas las del user, activar la target
    await db.broker_creds.update_many(
        {"user_id": user_id},
        {"$set": {"is_active": False}},
    )
    await db.broker_creds.update_one(
        {"_id": target["_id"]},
        {"$set": {"is_active": True, "updated_at": _now_iso()}},
    )
    log.info("active broker switched user=%s is_demo=%s", user_id, is_demo)
    doc = await db.broker_creds.find_one({"_id": target["_id"]})
    return _doc_to_public(doc)


async def delete_creds(db, user_id: str, *,
                        is_demo: bool | None = None) -> dict:
    """Elimina la cuenta de un tipo (demo o real), o ambas si is_demo=None.
    Retorna {deleted: n, was_active: bool}."""
    if db is None:
        return {"deleted": 0, "was_active": False}
    query = {"user_id": user_id}
    if is_demo is not None:
        query["is_demo"] = bool(is_demo)
    # Buscar primero para saber si la borrada estaba activa
    target = await db.broker_creds.find_one(query)
    was_active = bool(target and target.get("is_active"))
    res = await db.broker_creds.delete_many(query)
    # Si la borrada era la activa y queda OTRA cuenta, marcar la otra activa
    if was_active and is_demo is not None:
        other = await db.broker_creds.find_one({"user_id": user_id})
        if other:
            await db.broker_creds.update_one(
                {"_id": other["_id"]}, {"$set": {"is_active": True}}
            )
            log.info("auto-promote other account to active user=%s", user_id)
    return {"deleted": res.deleted_count, "was_active": was_active}


async def record_test_result(db, user_id: str, *, is_demo: bool,
                              ok: bool, error: Optional[str] = None) -> None:
    if db is None:
        return
    await db.broker_creds.update_one(
        {"user_id": user_id, "is_demo": bool(is_demo)},
        {
            "$set": {
                "last_test_at": _now_iso(),
                "last_test_ok": bool(ok),
                "last_test_error": (error or None) if not ok else None,
            }
        },
    )


async def ensure_indexes(db) -> None:
    """Índices para la collection broker_creds.

    Migración: si existe el índice viejo (unique en user_id solo), lo
    dropea y crea el nuevo (user_id, is_demo).
    """
    if db is None:
        return
    try:
        # Listar índices actuales
        existing = await db.broker_creds.list_indexes().to_list(length=20)
        for idx in existing:
            name = idx.get("name", "")
            keys = idx.get("key", {})
            # Si encontramos el viejo (unique solo en user_id), dropear
            if (name != "_id_" and
                set(keys.keys()) == {"user_id"} and
                idx.get("unique")):
                log.info("dropping old unique index %s", name)
                await db.broker_creds.drop_index(name)
        # Crear nuevo índice compuesto
        await db.broker_creds.create_index(
            [("user_id", 1), ("is_demo", 1)],
            unique=True, name="user_id_is_demo_unique",
        )
        # Migrar docs viejos que no tienen is_active: marcar el primer
        # doc por user como activo
        cursor = db.broker_creds.find({"is_active": {"$exists": False}})
        seen_users = set()
        async for doc in cursor:
            uid = doc.get("user_id")
            if uid in seen_users:
                # Ya hay uno marcado activo para este user, este queda inactive
                await db.broker_creds.update_one(
                    {"_id": doc["_id"]}, {"$set": {"is_active": False}}
                )
            else:
                await db.broker_creds.update_one(
                    {"_id": doc["_id"]}, {"$set": {"is_active": True}}
                )
                seen_users.add(uid)
    except Exception as exc:
        log.warning("broker_creds index/migration failed: %s", exc)


# ─────────────────────────── live test ───────────────────────────

async def test_connection_live(*, mt5_login: int, mt5_password: str,
                                mt5_server: str,
                                mt5_path: Optional[str] = None) -> dict:
    """Validación básica de creds. La conexión REAL contra MT5 ocurre
    al arrancar el bot — este test es liviano (shape + heurística)."""
    if not mt5_login or not mt5_server or not mt5_password:
        return {"ok": False, "error": "login, password y server son obligatorios"}
    if mt5_login <= 0:
        return {"ok": False, "error": "mt5_login debe ser un número positivo"}
    if len(mt5_password) < 4:
        return {"ok": False, "error": "password parece muy corto"}
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
        }
    return {
        "ok": True,
        "note": (
            "Validación básica OK. La conexión real con MT5 se va a "
            "verificar cuando arranques el bot."
        ),
    }
