# -*- coding: utf-8 -*-
"""Telegram bot — control y reporting del trading bot.

Cambios clave vs versión anterior:
  - **Authorization**: cada handler verifica que ``update.effective_chat.id``
    esté en ``ALLOWED_CHAT_IDS``. Antes cualquiera con el username del bot
    podía /halt el trading.
  - **Comandos nuevos**:
        /capital              snapshot completo del capital_ledger
        /reset_balance N      marca nuevo starting_balance (post-recarga demo)
        /deposit N            registra un depósito
        /withdrawal N         registra un retiro
        /expectancy [N]       top combos por expectancy real
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
log = logging.getLogger("telegram-bot")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
DASH_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
HALT_FILE = os.path.expanduser(os.getenv("HALT_FILE", "/opt/trading-bot/state/.HALT"))

# === Authorization: solo chat_ids declarados pueden usar el bot ===
# Múltiples chat ids separados por coma en TELEGRAM_ALLOWED_CHATS, o
# default = el chat_id principal.
_raw_allowed = os.getenv("TELEGRAM_ALLOWED_CHATS", CHAT_ID)
ALLOWED_CHAT_IDS = {
    int(s.strip()) for s in _raw_allowed.split(",") if s.strip().lstrip("-").isdigit()
}

# Hookear con _shared/common para acceder al capital ledger y expectancy
sys.path.insert(0, "/opt/trading-bot/app/mcp-scaffolds/_shared")
try:
    from common import capital_ledger, expectancy_tracker  # type: ignore
    _SHARED_OK = True
except ImportError as exc:
    log.warning("shared modules not importable: %s", exc)
    capital_ledger = None  # type: ignore
    expectancy_tracker = None  # type: ignore
    _SHARED_OK = False

RED = "\U0001f534"
GREEN = "\U0001f7e2"
WARN = "⚠️"


def _authorized(update: Update) -> bool:
    """True si el chat es uno de los autorizados."""
    chat = update.effective_chat
    if chat is None:
        return False
    return int(chat.id) in ALLOWED_CHAT_IDS


def authorize(handler):
    """Decorator: rechaza silenciosamente updates no autorizados.

    Logueamos para auditoría pero NO respondemos al chat — no queremos
    revelar que el bot existe a quien no debe tener acceso.
    """
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _authorized(update):
            log.warning("UNAUTHORIZED %s from chat_id=%s",
                        getattr(update.message, "text", "?"),
                        getattr(update.effective_chat, "id", "?"))
            return
        return await handler(update, ctx)
    return wrapper


async def _api(url, method="GET", json_body=None):
    headers = {}
    if DASH_TOKEN:
        headers["Authorization"] = "Bearer " + DASH_TOKEN
    async with httpx.AsyncClient(timeout=15) as client:
        if method == "POST":
            r = await client.post(url, json=json_body, headers=headers)
        else:
            r = await client.get(url, headers=headers)
        return r.json()


# ──────────────────────── handlers ────────────────────────

@authorize
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        health = await _api(BACKEND_URL + "/api/health")
        stats = await _api(BACKEND_URL + "/api/journal/stats")
        halted = os.path.exists(HALT_FILE)
        icon = RED if halted else GREEN
        state = "HALTED" if halted else "RUNNING"
        db_ok = "OK" if health.get("db") else "DOWN"
        total = str(stats.get("total_trades", "N/A"))
        wr = str(stats.get("win_rate", "N/A"))
        pnl = str(stats.get("total_pnl", "N/A"))
        msg = (
            icon + " " + state + "\n"
            "DB: " + db_ok + "\n"
            "Trades: " + total + "\n"
            "Win rate: " + wr + "%\n"
            "Total PnL: $" + pnl
        )
    except Exception as e:
        msg = "Error fetching status: " + str(e)
    await update.message.reply_text(msg)


@authorize
async def cmd_capital(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Snapshot del capital_ledger: target vs starting vs current vs peak."""
    if not _SHARED_OK or capital_ledger is None:
        await update.message.reply_text("capital_ledger no disponible")
        return
    try:
        m = capital_ledger.metrics()
        target = m["target_capital_usd"]
        cur = m["current_balance_usd"]
        starting = m["starting_balance_usd"]
        peak = m["peak_equity_usd"]
        pl_session = m["pl_session_usd"]
        pl_pct = m["pl_session_pct"]
        dd_peak = m["dd_from_peak_usd"]
        dd_peak_pct = m["dd_from_peak_pct"]
        target_remaining = m["pl_target_remaining_usd"]
        msg = (
            "💰 *Capital*\n"
            f"Meta: `${target:.2f}`\n"
            f"Actual: `${cur:.2f}`\n"
            f"Inicio sesión: `${starting:.2f}`\n"
            f"Peak: `${peak:.2f}`\n"
            "\n"
            f"P&L sesión: *${pl_session:+.2f}* ({pl_pct:+.2f}%)\n"
            f"DD desde peak: ${dd_peak:.2f} ({dd_peak_pct:.2f}%)\n"
            f"Falta a la meta: ${target_remaining:+.2f}"
        )
    except Exception as e:
        msg = "Error: " + str(e)
    await update.message.reply_text(msg, parse_mode="Markdown")


@authorize
async def cmd_reset_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """``/reset_balance [N]`` — marca el balance actual (o N) como nuevo
    starting_balance. Uso: cuando recargás cuenta demo o querés empezar a
    medir desde cero. Sin parámetro: usa el balance live de MT5."""
    if not _SHARED_OK or capital_ledger is None:
        await update.message.reply_text("capital_ledger no disponible")
        return
    args = ctx.args or []
    new_balance = None
    if args:
        try:
            new_balance = float(args[0])
        except ValueError:
            await update.message.reply_text(
                "Uso: /reset_balance 1000  (o sin argumento para usar live MT5)"
            )
            return
    if new_balance is None:
        try:
            data = await _api(BACKEND_URL + "/api/")
            new_balance = float(data.get("capital") or 0)
        except Exception as e:
            await update.message.reply_text(f"No pude leer balance live: {e}")
            return
    if new_balance <= 0:
        await update.message.reply_text("El balance debe ser > 0")
        return
    try:
        ledger = capital_ledger.reset(
            new_balance,
            note=f"telegram /reset_balance from chat {update.effective_chat.id}",
        )
        await update.message.reply_text(
            f"✅ Balance reset a ${ledger['starting_balance_usd']:.2f}.\n"
            f"DD/expectancy se mide desde aquí."
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


@authorize
async def cmd_deposit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """``/deposit N`` — registra un depósito de N USD."""
    if not _SHARED_OK or capital_ledger is None:
        await update.message.reply_text("capital_ledger no disponible")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text("Uso: /deposit 500")
        return
    try:
        amount = float(args[0])
        if amount <= 0:
            raise ValueError("amount must be > 0")
    except ValueError:
        await update.message.reply_text("Cantidad inválida")
        return
    try:
        data = await _api(BACKEND_URL + "/api/")
        current_balance = float(data.get("capital") or 0)
        new_balance = current_balance + amount
        ledger = capital_ledger.record_deposit(
            amount, balance_after=new_balance,
            note=f"telegram /deposit from chat {update.effective_chat.id}",
        )
        await update.message.reply_text(
            f"✅ Depósito de ${amount:.2f} registrado.\n"
            f"Nuevo starting_balance: ${ledger['starting_balance_usd']:.2f}"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


@authorize
async def cmd_withdrawal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """``/withdrawal N`` — registra un retiro de N USD (no cuenta como pérdida)."""
    if not _SHARED_OK or capital_ledger is None:
        await update.message.reply_text("capital_ledger no disponible")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text("Uso: /withdrawal 200")
        return
    try:
        amount = float(args[0])
        if amount <= 0:
            raise ValueError("amount must be > 0")
    except ValueError:
        await update.message.reply_text("Cantidad inválida")
        return
    try:
        data = await _api(BACKEND_URL + "/api/")
        current_balance = float(data.get("capital") or 0)
        new_balance = max(0.0, current_balance - amount)
        ledger = capital_ledger.record_withdrawal(
            amount, balance_after=new_balance,
            note=f"telegram /withdrawal from chat {update.effective_chat.id}",
        )
        await update.message.reply_text(
            f"✅ Retiro de ${amount:.2f} registrado.\n"
            f"Nuevo starting_balance: ${ledger['starting_balance_usd']:.2f}\n"
            f"(no contará como pérdida en el DD)"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


@authorize
async def cmd_expectancy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Top combos por expectancy. Uso: /expectancy [min_n]"""
    if not _SHARED_OK or expectancy_tracker is None:
        await update.message.reply_text("expectancy_tracker no disponible")
        return
    args = ctx.args or []
    min_n = int(args[0]) if args and args[0].isdigit() else 0
    try:
        combos = expectancy_tracker.list_combos(min_n=min_n)
        if not combos:
            await update.message.reply_text("Sin datos de expectancy todavía.")
            return
        lines = ["📈 *Expectancy por combo* (strategy:symbol)"]
        for k, s in list(combos.items())[:15]:
            lines.append(
                f"`{k}` n={s['n']} wr={s['wr']*100:.0f}% "
                f"avg\\_R={s['avg_r']:+.2f} *exp={s['expectancy_r']:+.3f}R*"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


@authorize
async def cmd_halt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    os.makedirs(os.path.dirname(HALT_FILE), exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with open(HALT_FILE, "w") as f:
        f.write("HALTED by Telegram at " + ts + "\n")
    await update.message.reply_text(RED + " HALT activated. No new trades will execute.")


@authorize
async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(HALT_FILE):
        os.remove(HALT_FILE)
        await update.message.reply_text(GREEN + " HALT removed. Trading resumed.")
    else:
        await update.message.reply_text("System was not halted.")


@authorize
async def cmd_journal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = await _api(BACKEND_URL + "/api/journal?limit=5")
        trades = data if isinstance(data, list) else data.get("trades", [])
        if not trades:
            msg = "No hay trades recientes en el journal."
        else:
            lines = []
            for t in trades[:5]:
                sym = t.get("symbol", "?")
                side = t.get("side", "?")
                pnl = str(t.get("pnl_usd", "?"))
                lines.append("- " + sym + " " + side + " | PnL: $" + pnl)
            msg = "Últimos trades:\n" + "\n".join(lines)
    except Exception as e:
        msg = "Error: " + str(e)
    await update.message.reply_text(msg)


@authorize
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "*Comandos*\n"
        "/status — estado del bot + WR + PnL\n"
        "/capital — capital actual vs meta vs peak\n"
        "/reset\\_balance \\[N\\] — nuevo starting balance\n"
        "/deposit N — registrar depósito\n"
        "/withdrawal N — registrar retiro\n"
        "/expectancy \\[min\\_n\\] — top combos\n"
        "/journal — últimos 5 trades\n"
        "/halt — parar el bot\n"
        "/resume — reanudar"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def send_alert(app, message):
    try:
        for cid in ALLOWED_CHAT_IDS:
            await app.bot.send_message(chat_id=cid, text=message)
    except Exception as e:
        log.error("Failed to send Telegram alert: %s", e)


async def poll_signals(app):
    log.info("Starting signal poller (interval=%ds)", POLL_INTERVAL)
    while True:
        try:
            health = await _api(BACKEND_URL + "/api/health")
            if not health.get("db"):
                await send_alert(app, WARN + " Database connection lost!")
            if os.path.exists(HALT_FILE):
                log.debug("System halted, skipping poll")
            else:
                log.debug("Poll cycle complete, all clear")
        except Exception as e:
            log.error("Poll error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("status", "System status + daily PnL"),
        BotCommand("capital", "Capital vs target vs peak"),
        BotCommand("reset_balance", "New starting balance"),
        BotCommand("deposit", "Record deposit"),
        BotCommand("withdrawal", "Record withdrawal"),
        BotCommand("expectancy", "Top profitable combos"),
        BotCommand("journal", "Recent trades"),
        BotCommand("halt", "Emergency stop"),
        BotCommand("resume", "Resume after halt"),
        BotCommand("help", "Show commands"),
    ])
    asyncio.create_task(poll_signals(app))
    await send_alert(app, GREEN + " Trading Bot online (auth enabled).")
    log.info("Telegram bot started, allowed chats: %s", ALLOWED_CHAT_IDS)


def main():
    if not ALLOWED_CHAT_IDS:
        log.error("TELEGRAM_ALLOWED_CHATS empty — refusing to start without auth")
        sys.exit(1)
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("capital", cmd_capital))
    app.add_handler(CommandHandler("reset_balance", cmd_reset_balance))
    app.add_handler(CommandHandler("deposit", cmd_deposit))
    app.add_handler(CommandHandler("withdrawal", cmd_withdrawal))
    app.add_handler(CommandHandler("expectancy", cmd_expectancy))
    app.add_handler(CommandHandler("journal", cmd_journal))
    # Aliases legacy
    app.add_handler(CommandHandler("news", cmd_journal))
    app.add_handler(CommandHandler("risk", cmd_capital))
    # Control
    app.add_handler(CommandHandler("halt", cmd_halt))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    log.info("Starting Telegram bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
