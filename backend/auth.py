"""auth.py — autenticación JWT con roles admin/user para el dashboard.

Reemplaza el patrón anterior (un solo `DASHBOARD_TOKEN` compartido en el
bundle JS) por un sistema multi-usuario con:

  - **users** collection en Mongo: email + password_hash (bcrypt) + role.
  - **JWT** con expiración (default 7 días) + secret en env.
  - **Roles**: "admin" (vos, control total) | "user" (solo su propio bot,
    Fase 2). Hoy todos los writes requieren admin — Fase 1.
  - **Bootstrap**: el primer arranque crea el admin desde env vars
    ``ADMIN_EMAIL`` + ``ADMIN_PASSWORD`` si la collection users está vacía.
  - **Compat con DASHBOARD_TOKEN**: si el header tiene Bearer == TOKEN
    legacy, se acepta como admin (para no romper integraciones antiguas
    como el sync_loop, telegram bot, etc.). Lo migramos en Fase 2.

Endpoints (montados en server.py):
  - POST /api/auth/register {email, password} → 201 + JWT
  - POST /api/auth/login {email, password}     → 200 + JWT
  - GET  /api/auth/me  (Bearer)                → user info
  - POST /api/auth/logout                       → no-op (cliente borra JWT)

Decorators:
  - require_user(authorization)   → cualquier usuario autenticado
  - require_admin(authorization)  → solo role=admin (o legacy token)
"""
from __future__ import annotations

import logging
import os
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field

log = logging.getLogger("auth")

# ─────────────────────────── config ───────────────────────────

# Secret para firmar JWTs. SI NO ESTÁ EN ENV, generamos uno random al
# arranque y lo loggeamos UNA VEZ — los tokens emitidos invalidan en cada
# restart. Para producción, definir JWT_SECRET en backend/.env.
_JWT_SECRET = os.environ.get("JWT_SECRET")
if not _JWT_SECRET:
    _JWT_SECRET = _secrets.token_urlsafe(48)
    log.warning("JWT_SECRET no definido en env — generado random. "
                "Tokens invalidan al reiniciar el backend. "
                "Para producción: agrega JWT_SECRET=... a backend/.env")

JWT_ALGORITHM = "HS256"
JWT_EXP_DAYS = int(os.environ.get("JWT_EXP_DAYS", "7"))

# DASHBOARD_TOKEN legacy — se acepta como "admin token" hasta Fase 2.
LEGACY_TOKEN = (os.environ.get("DASHBOARD_TOKEN") or "").strip()

# Bcrypt para passwords. 12 rounds = ~250ms hash, balance security/UX.
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto",
                         bcrypt__rounds=12)


# ─────────────────────────── models ───────────────────────────

class RegisterPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # Para Fase 2: nombre opcional para mostrar
    display_name: Optional[str] = Field(default=None, max_length=64)


class LoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    """Lo que devolvemos al cliente — NUNCA incluye password_hash."""
    id: str
    email: EmailStr
    display_name: Optional[str] = None
    role: str = "user"
    created_at: str


class AuthResponse(BaseModel):
    ok: bool = True
    token: str
    expires_at: str
    user: UserPublic


# ─────────────────────────── helpers ───────────────────────────

def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_ctx.verify(plain, hashed)
    except Exception:
        return False


def make_jwt(user_id: str, email: str, role: str) -> tuple[str, str]:
    """Devuelve (token, expires_at_iso)."""
    exp = datetime.now(timezone.utc) + timedelta(days=JWT_EXP_DAYS)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
    }
    token = pyjwt.encode(payload, _JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, exp.isoformat()


def decode_jwt(token: str) -> dict:
    """Devuelve el payload o lanza HTTPException(401) si inválido/expirado."""
    try:
        return pyjwt.decode(token, _JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "token expirado, hacé login de nuevo")
    except pyjwt.InvalidTokenError:
        raise HTTPException(401, "token inválido")


def _user_to_public(u: dict) -> UserPublic:
    """Convierte doc Mongo a respuesta pública."""
    return UserPublic(
        id=str(u.get("_id") or u.get("id")),
        email=u["email"],
        display_name=u.get("display_name"),
        role=u.get("role", "user"),
        created_at=u.get("created_at") or datetime.now(timezone.utc).isoformat(),
    )


# ─────────────────────────── auth dependencies ───────────────────────────

class _CurrentUser:
    """Stand-in para `current_user` — incluye flag `legacy_admin` cuando
    se usa DASHBOARD_TOKEN compartido (sync_loop, telegram bot)."""
    def __init__(self, *, id: str, email: str, role: str,
                 legacy_admin: bool = False):
        self.id = id
        self.email = email
        self.role = role
        self.legacy_admin = legacy_admin

    @property
    def is_admin(self) -> bool:
        return self.role == "admin" or self.legacy_admin


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    """Extrae el token de un header Authorization. None si vacío/malo."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def require_auth_optional(
    authorization: Optional[str] = Header(default=None),
) -> Optional[_CurrentUser]:
    """Si hay token válido, retorna el current user. Si NO hay header,
    retorna None (acceso público). Si hay token PERO es inválido, 401."""
    token = _parse_bearer(authorization)
    if not token:
        return None

    # Path legacy: DASHBOARD_TOKEN como Bearer → admin "del sistema".
    if LEGACY_TOKEN and _secrets.compare_digest(token, LEGACY_TOKEN):
        return _CurrentUser(id="__legacy__", email="legacy@bot",
                             role="admin", legacy_admin=True)

    payload = decode_jwt(token)
    return _CurrentUser(
        id=str(payload.get("sub") or ""),
        email=str(payload.get("email") or ""),
        role=str(payload.get("role") or "user"),
    )


def require_user(
    authorization: Optional[str] = Header(default=None),
) -> _CurrentUser:
    """Cualquier usuario autenticado. 401 si no hay token o es inválido."""
    user = require_auth_optional(authorization)
    if user is None:
        raise HTTPException(401, "autenticación requerida")
    return user


def require_admin(
    authorization: Optional[str] = Header(default=None),
) -> _CurrentUser:
    """Solo admin. 403 si autenticado pero no es admin."""
    user = require_user(authorization)
    if not user.is_admin:
        raise HTTPException(403, "se requiere rol admin")
    return user


def optional_user(
    authorization: Optional[str] = Header(default=None),
) -> Optional[_CurrentUser]:
    """Retorna el user si hay token válido, None si no. NO lanza 401.
    Util para endpoints que tienen contenido tanto público como
    personalizado (ej. /api/strategies — anónimo ve config global,
    user logueado ve su config personal)."""
    return require_auth_optional(authorization)


# ─────────────────────────── DB ops ───────────────────────────

async def ensure_users_collection(db) -> None:
    """Crea índices únicos en users.email + bootstrap admin si la
    collection está vacía y hay ADMIN_EMAIL/ADMIN_PASSWORD en env."""
    if db is None:
        return
    try:
        await db.users.create_index("email", unique=True)
    except Exception as exc:
        log.warning("users index create failed: %s", exc)

    count = await db.users.count_documents({})
    if count > 0:
        return

    admin_email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    admin_pwd = (os.environ.get("ADMIN_PASSWORD") or "").strip()
    if not admin_email or not admin_pwd:
        log.warning(
            "users collection vacía y ADMIN_EMAIL/ADMIN_PASSWORD no "
            "están en env. Crea el admin manualmente con "
            "POST /api/auth/register + UPDATE role='admin' en mongo."
        )
        return

    if len(admin_pwd) < 8:
        log.error("ADMIN_PASSWORD muy corta (mín 8). Saltando bootstrap.")
        return

    doc = {
        "_id": "admin-" + _secrets.token_urlsafe(8),
        "email": admin_email,
        "password_hash": hash_password(admin_pwd),
        "display_name": os.environ.get("ADMIN_DISPLAY_NAME", "Admin"),
        "role": "admin",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.users.insert_one(doc)
        log.info("admin bootstrap OK: %s", admin_email)
    except Exception as exc:
        log.warning("admin bootstrap failed: %s", exc)


# ─────────────────────────── route handlers ───────────────────────────

async def register_handler(payload: RegisterPayload, db) -> AuthResponse:
    """Crea usuario nuevo (role=user). 409 si email ya existe."""
    if db is None:
        raise HTTPException(503, "DB no disponible")
    email_norm = payload.email.lower().strip()
    existing = await db.users.find_one({"email": email_norm})
    if existing:
        raise HTTPException(409, "ese email ya está registrado")

    user_id = "u-" + _secrets.token_urlsafe(10)
    doc = {
        "_id": user_id,
        "email": email_norm,
        "password_hash": hash_password(payload.password),
        "display_name": payload.display_name,
        "role": "user",     # admins se promueven manualmente
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)

    token, exp = make_jwt(user_id, email_norm, "user")
    return AuthResponse(
        ok=True, token=token, expires_at=exp,
        user=_user_to_public(doc),
    )


async def login_handler(payload: LoginPayload, db) -> AuthResponse:
    """Verifica password, devuelve JWT. 401 si email/password mal.
    Mismo error code para ambos para no leak existencia del email."""
    if db is None:
        raise HTTPException(503, "DB no disponible")
    email_norm = payload.email.lower().strip()
    user = await db.users.find_one({"email": email_norm})
    if not user:
        raise HTTPException(401, "email o contraseña incorrectos")
    if not verify_password(payload.password, user.get("password_hash") or ""):
        raise HTTPException(401, "email o contraseña incorrectos")

    role = user.get("role", "user")
    token, exp = make_jwt(str(user["_id"]), email_norm, role)
    return AuthResponse(
        ok=True, token=token, expires_at=exp,
        user=_user_to_public(user),
    )


async def me_handler(current: _CurrentUser, db) -> dict:
    """Devuelve info del usuario autenticado."""
    if current.legacy_admin:
        return {
            "id": "__legacy__",
            "email": "legacy@bot",
            "role": "admin",
            "legacy_token": True,
            "warning": "estás usando el DASHBOARD_TOKEN compartido — migrá a JWT",
        }
    if db is None:
        return {"id": current.id, "email": current.email,
                "role": current.role}
    user = await db.users.find_one({"_id": current.id}, {"password_hash": 0})
    if not user:
        raise HTTPException(404, "usuario no existe")
    public = _user_to_public(user)
    return public.model_dump()
