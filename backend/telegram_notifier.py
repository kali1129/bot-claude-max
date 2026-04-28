"""Telegram notifications — best effort, never blocks the dashboard.

Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from ``backend/.env``.
Used for: bot lifecycle (start/stop), trades (open/close), drawdown,
kill-switch, and alerts the supervisor wants to surface.

Safe to call from any endpoint — failures are swallowed and logged. The
notifier does not retry, does not block, and does not leak the token.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("telegram-notifier")


def _env() -> tuple[str | None, str | None, bool]:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    enabled = (os.environ.get("TELEGRAM_NOTIFICATIONS_ENABLED", "true") or "")\
        .strip().lower() in {"1", "true", "yes", "on"}
    return token or None, chat or None, enabled


def is_configured() -> bool:
    token, chat, _ = _env()
    return bool(token and chat)


def status() -> dict:
    token, chat, enabled = _env()
    return {
        "enabled": enabled,
        "configured": bool(token and chat),
        "chat_id": chat,
        # never expose the full token; just the bot id prefix
        "bot_prefix": (token.split(":", 1)[0] if token else None),
    }


def send(text: str, *, parse_mode: str = "Markdown",
         disable_preview: bool = True, timeout: float = 5.0) -> dict:
    """Best-effort send. Always returns a dict; never raises."""
    token, chat, enabled = _env()
    if not enabled:
        return {"ok": False, "reason": "DISABLED"}
    if not token or not chat:
        return {"ok": False, "reason": "NOT_CONFIGURED"}

    payload = {
        "chat_id": chat,
        "text": text[:3500],
        "disable_web_page_preview": disable_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    body = json.dumps(payload).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": bool(data.get("ok")), "result": data.get("result", {})}
    except urllib.error.HTTPError as exc:
        log.warning("telegram HTTPError %s: %s", exc.code, exc.reason)
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            detail = {"raw": str(exc)}
        return {"ok": False, "reason": "HTTP_ERROR",
                "status": exc.code, "detail": detail}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("telegram delivery failed: %s", exc)
        return {"ok": False, "reason": "NETWORK", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram unexpected error: %s", exc)
        return {"ok": False, "reason": "UNEXPECTED", "detail": str(exc)}


# --------------------------- domain helpers ---------------------------

def _fmt_money(v: float, currency: str = "USD") -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:.2f} {currency}"


def notify_trade_opened(*, symbol: str, side: str, lots: float,
                         entry: float, sl: float, tp: float,
                         score: int | str = "?", source: str = "bot",
                         mode: str = "paper") -> dict:
    side_es = "COMPRA" if side == "buy" else "VENTA"
    text = (
        f"🟢 *Trade abierto* ({mode})\n"
        f"`{symbol}` {side_es}  ·  {lots} lots\n"
        f"Entrada: `{entry}`\n"
        f"SL `{sl}`  ·  TP `{tp}`\n"
        f"Score: `{score}`  ·  vía: {source}"
    )
    return send(text)


def notify_trade_closed(*, symbol: str, side: str, exit_price: float,
                         pnl_usd: float, r_multiple: float, reason: str,
                         currency: str = "USD") -> dict:
    side_es = "compra" if side == "buy" else "venta"
    icon = "🟢" if pnl_usd > 0 else ("🔴" if pnl_usd < 0 else "⚪")
    text = (
        f"{icon} *Trade cerrado* ({reason})\n"
        f"`{symbol}` {side_es} @ `{exit_price}`\n"
        f"P&L: *{_fmt_money(pnl_usd, currency)}*  ·  {r_multiple:+.2f}R"
    )
    return send(text)


def notify_halt(reason: str) -> dict:
    return send(f"🛑 *Trading detenido*\nRazón: {reason}")


def notify_resume() -> dict:
    return send("▶ *Trading reanudado*")


def notify_alert(text: str) -> dict:
    return send(f"⚠ *Alerta*\n{text}")


def notify_summary(*, balance: float, equity: float,
                    today_pnl: float, today_pct: float,
                    open_count: int, wins: int, losses: int,
                    total_pnl: float, currency: str = "USD") -> dict:
    text = (
        "📊 *Resumen del bot*\n"
        f"Equity: `{_fmt_money(equity, currency)}`  ·  Balance: `{_fmt_money(balance, currency)}`\n"
        f"Hoy: *{_fmt_money(today_pnl, currency)}* ({today_pct:+.2f}%)\n"
        f"Posiciones abiertas: `{open_count}`\n"
        f"Acumulado: {wins}W / {losses}L  ·  *{_fmt_money(total_pnl, currency)}*"
    )
    return send(text)


__all__ = [
    "is_configured", "status", "send",
    "notify_trade_opened", "notify_trade_closed",
    "notify_halt", "notify_resume", "notify_alert", "notify_summary",
]
