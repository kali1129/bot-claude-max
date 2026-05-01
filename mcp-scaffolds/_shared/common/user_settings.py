"""user_settings — preferencias del usuario que el bot respeta en runtime.

Reemplaza el patrón anterior de configurar el bot via env vars + plan_content
constants. Todo lo que el USUARIO debería poder cambiar desde el dashboard
vive acá:

  - **mode**: "novato" | "experto"
      - novato: UI oculta tecnicismos, configuración wizard-style
      - experto: UI muestra todo (lots, ATR, Kelly, expectancy, etc.)
  - **goal_usd**: meta de capital (NO hardcoded — antes era $800 fijo)
  - **style**: preset de risk + RR + max_open + max_daily_loss
      - "conservativo" | "balanceado" | "agresivo"
  - **sessions**: lista de sesiones activas
      - ["asia", "london", "ny"] o ["24/7"]
  - **telegram_chat_ids**: lista de chat IDs para notificaciones
  - **referral_partner**: tu link de afiliados (XM por default)
  - **onboarded**: bool, primer wizard completado

Persistencia: ``state/user_settings.json``. Atomic write tmp+rename.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FILE = Path(os.path.expanduser(
    os.environ.get("USER_SETTINGS_FILE",
                   "/opt/trading-bot/state/user_settings.json")
))

_lock = threading.Lock()


# ─────────────────────────── presets ───────────────────────────

STYLE_PRESETS: dict[str, dict] = {
    "conservativo": {
        "label": "Conservativo",
        "description": "Para quien recién empieza. Pocos trades, riesgo bajo, RR alto.",
        "icon": "🛡️",
        "risk_pct": 0.5,
        "min_rr": 2.5,
        "max_open_positions": 1,
        "max_daily_loss_pct": 1.5,
        "max_trades_per_day": 3,
        "max_consecutive_losses": 2,
        "max_lots_per_trade": 0.10,
        "warning": None,
    },
    "balanceado": {
        "label": "Balanceado",
        "description": "Equilibrio entre frecuencia y disciplina. Recomendado.",
        "icon": "⚖️",
        "risk_pct": 1.0,
        "min_rr": 2.0,
        "max_open_positions": 3,
        "max_daily_loss_pct": 3.0,
        "max_trades_per_day": 5,
        "max_consecutive_losses": 3,
        "max_lots_per_trade": 0.30,
        "warning": None,
    },
    "agresivo": {
        "label": "Agresivo",
        "description": "Más trades, más riesgo. Solo para experimentados.",
        "icon": "🔥",
        "risk_pct": 2.0,
        "min_rr": 1.5,
        "max_open_positions": 5,
        "max_daily_loss_pct": 5.0,
        "max_trades_per_day": 15,
        "max_consecutive_losses": 4,
        "max_lots_per_trade": 0.50,
        "warning": (
            "⚠️ MODO AGRESIVO\n\n"
            "Riesgo de pérdida elevado. La estrategia toma más operaciones, "
            "con stops más cercanos y RR menor. Una racha mala puede costar "
            "5%+ del capital en un solo día.\n\n"
            "Solo activá este modo si:\n"
            "  • Ya operaste antes en demo y entendés el riesgo\n"
            "  • Estás dispuesto a perder lo que hay en la cuenta\n"
            "  • Vas a monitorear el bot activamente\n\n"
            "El bot NO es un cajero automático. Operá responsablemente."
        ),
    },
}

# Sesiones de mercado (en UTC)
TRADING_SESSIONS: dict[str, dict] = {
    "asia": {
        "label": "Asia",
        "description": "Tokyo, Sydney, Singapur. Volatilidad media en JPY/AUD.",
        "start_hour_utc": 22,  # 22:00 UTC = 07:00 Tokyo
        "end_hour_utc": 7,
        "icon": "🌏",
    },
    "london": {
        "label": "Londres",
        "description": "Sesión más activa. Volatilidad alta en EUR/GBP.",
        "start_hour_utc": 7,   # 07:00 UTC = 08:00 London
        "end_hour_utc": 16,
        "icon": "🇬🇧",
    },
    "ny": {
        "label": "Nueva York",
        "description": "Solapa con Londres 12-16 UTC. Movimientos grandes en USD.",
        "start_hour_utc": 12,  # 12:00 UTC = 08:00 NY
        "end_hour_utc": 21,
        "icon": "🗽",
    },
    "24/7": {
        "label": "24/7 (todo el día)",
        "description": "El bot opera siempre que haya señales. Recomendado para crypto.",
        "start_hour_utc": 0,
        "end_hour_utc": 24,
        "icon": "🌐",
    },
}


# ─────────────────────────── default ───────────────────────────

def _default_settings() -> dict:
    """Settings iniciales para un usuario nuevo."""
    return {
        "schema_version": 1,
        "mode": "novato",
        "goal_usd": None,                  # se setea en el wizard
        "style": "balanceado",
        "sessions": ["24/7"],
        "telegram_chat_ids": [],
        "telegram_enabled": True,
        "referral_partner": {
            "broker": "xm",
            "url": "https://www.xmglobal.com/referral?token=OtZfgkRKCdH25RlT1gJ7hQ",
            "label": "Crear cuenta en XM Global",
        },
        "onboarded": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────── persistence ───────────────────────────

def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def load() -> dict:
    """Lee settings; si no existe, devuelve defaults."""
    with _lock:
        if not _FILE.exists():
            return _default_settings()
        try:
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            # Merge con defaults (en caso de keys nuevas en upgrades)
            merged = _default_settings()
            merged.update(data)
            return merged
        except (OSError, json.JSONDecodeError):
            return _default_settings()


def save(settings: dict) -> dict:
    """Persiste settings, validando + setteando updated_at."""
    settings = validate(settings)
    settings["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        _atomic_write(_FILE, settings)
    return settings


# ─────────────────────────── validation ───────────────────────────

def validate(settings: dict) -> dict:
    """Valida y normaliza settings. Lanza ValueError si inválido."""
    if not isinstance(settings, dict):
        raise ValueError("settings debe ser dict")

    out = _default_settings()
    out.update(settings)

    # mode
    mode = (out.get("mode") or "novato").strip().lower()
    if mode not in {"novato", "experto"}:
        raise ValueError("mode debe ser 'novato' o 'experto'")
    out["mode"] = mode

    # goal_usd: positivo o None
    goal = out.get("goal_usd")
    if goal is not None:
        try:
            goal = float(goal)
            if goal <= 0:
                raise ValueError
            if goal > 10_000_000:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("goal_usd debe ser un número positivo (o null)")
        out["goal_usd"] = goal

    # style
    style = (out.get("style") or "balanceado").strip().lower()
    if style not in STYLE_PRESETS:
        raise ValueError(f"style debe ser uno de {list(STYLE_PRESETS)}")
    out["style"] = style

    # sessions — distinguir "no enviado" (None → default) de "[] explícito" (rechazar)
    sessions = out.get("sessions")
    if sessions is None:
        sessions = ["24/7"]
    elif not isinstance(sessions, list):
        raise ValueError("sessions debe ser una lista")
    elif len(sessions) == 0:
        raise ValueError("sessions no puede ser lista vacía. Usá ['24/7'] para operar siempre.")
    valid = set(TRADING_SESSIONS.keys())
    sessions = [s.strip().lower() for s in sessions]
    bad = [s for s in sessions if s not in valid]
    if bad:
        raise ValueError(f"sessions inválidas: {bad}. Válidas: {list(valid)}")
    # Si el usuario eligió "24/7" más otra, simplificamos a 24/7
    if "24/7" in sessions and len(sessions) > 1:
        sessions = ["24/7"]
    out["sessions"] = sorted(set(sessions))

    # telegram_chat_ids: lista de int
    tg = out.get("telegram_chat_ids") or []
    if not isinstance(tg, list):
        raise ValueError("telegram_chat_ids debe ser lista")
    cleaned = []
    for v in tg:
        try:
            cleaned.append(int(str(v).strip()))
        except (TypeError, ValueError):
            raise ValueError(f"telegram_chat_id inválido: {v}")
    out["telegram_chat_ids"] = cleaned

    # telegram_enabled
    out["telegram_enabled"] = bool(out.get("telegram_enabled", True))

    # referral_partner: solo lectura por ahora
    out["referral_partner"] = out.get("referral_partner") or _default_settings()["referral_partner"]

    # onboarded
    out["onboarded"] = bool(out.get("onboarded", False))

    return out


# ─────────────────────────── helpers públicos ───────────────────────────

def get_active_style_preset() -> dict:
    """Retorna el preset del estilo activo."""
    s = load()
    return STYLE_PRESETS.get(s.get("style") or "balanceado", STYLE_PRESETS["balanceado"])


def get_goal_usd(fallback: float | None = None) -> float | None:
    """Retorna la meta del usuario, o el fallback (o None)."""
    s = load()
    g = s.get("goal_usd")
    return float(g) if g is not None else (float(fallback) if fallback else None)


def is_session_active(utc_hour: int, settings: dict | None = None) -> bool:
    """¿La hora UTC actual cae en alguna de las sesiones activas?"""
    s = settings if settings is not None else load()
    sessions = s.get("sessions") or ["24/7"]
    if "24/7" in sessions:
        return True
    for sess_id in sessions:
        sess = TRADING_SESSIONS.get(sess_id)
        if not sess:
            continue
        start = sess["start_hour_utc"]
        end = sess["end_hour_utc"]
        # ventana wrap-around (Asia: 22-07)
        if start <= end:
            if start <= utc_hour < end:
                return True
        else:
            if utc_hour >= start or utc_hour < end:
                return True
    return False


def telegram_chat_ids() -> list:
    """Retorna la lista de chat IDs autorizados (para Telegram bot auth +
    notificaciones). El primer elemento es el "principal"."""
    s = load()
    if not s.get("telegram_enabled", True):
        return []
    return list(s.get("telegram_chat_ids") or [])


def add_telegram_chat(chat_id: int) -> dict:
    """Agrega un chat_id a la lista (idempotente)."""
    s = load()
    chats = list(s.get("telegram_chat_ids") or [])
    if chat_id not in chats:
        chats.append(int(chat_id))
        s["telegram_chat_ids"] = chats
        save(s)
    return s


def remove_telegram_chat(chat_id: int) -> dict:
    s = load()
    chats = [c for c in (s.get("telegram_chat_ids") or []) if c != chat_id]
    s["telegram_chat_ids"] = chats
    save(s)
    return s


def mark_onboarded() -> dict:
    s = load()
    s["onboarded"] = True
    return save(s)


def list_styles() -> dict:
    return STYLE_PRESETS


def list_sessions() -> dict:
    return TRADING_SESSIONS


# ─────────────────────────── snapshot público ───────────────────────────

def snapshot() -> dict:
    """Snapshot serializable para el dashboard. Incluye los presets aplicados."""
    s = load()
    style_p = STYLE_PRESETS.get(s.get("style") or "balanceado", STYLE_PRESETS["balanceado"])
    return {
        **s,
        "active_style_preset": style_p,
        "available_styles": STYLE_PRESETS,
        "available_sessions": TRADING_SESSIONS,
    }
