# -*- coding: utf-8 -*-
import asyncio, logging, os
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

RED = "\U0001f534"
GREEN = "\U0001f7e2"
WARN = "⚠️"


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
            "Trades today: " + total + "\n"
            "Win rate: " + wr + "%\n"
            "Total PnL: $" + pnl
        )
    except Exception as e:
        msg = "Error fetching status: " + str(e)
    await update.message.reply_text(msg)


async def cmd_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = await _api(BACKEND_URL + "/api/discipline/score")
        score = str(data.get("score", "N/A"))
        window = str(data.get("window", 30))
        msg = "Discipline Score: " + score + "%\nPeriod: last " + window + " trades"
    except Exception as e:
        msg = "Error: " + str(e)
    await update.message.reply_text(msg)


async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = await _api(BACKEND_URL + "/api/journal?limit=5")
        trades = data if isinstance(data, list) else data.get("trades", [])
        if not trades:
            msg = "No recent trades in journal."
        else:
            lines = []
            for t in trades[:5]:
                sym = t.get("symbol", "?")
                side = t.get("side", "?")
                pnl = str(t.get("pnl_usd", "?"))
                lines.append("- " + sym + " " + side + " | PnL: $" + pnl)
            msg = "Recent trades:\n" + "\n".join(lines)
    except Exception as e:
        msg = "Error: " + str(e)
    await update.message.reply_text(msg)


async def cmd_halt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    os.makedirs(os.path.dirname(HALT_FILE), exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with open(HALT_FILE, "w") as f:
        f.write("HALTED by Telegram at " + ts + "\n")
    await update.message.reply_text(RED + " HALT activated. No new trades will execute.")


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(HALT_FILE):
        os.remove(HALT_FILE)
        await update.message.reply_text(GREEN + " HALT removed. Trading resumed.")
    else:
        await update.message.reply_text("System was not halted.")


async def send_alert(app, message):
    try:
        await app.bot.send_message(chat_id=CHAT_ID, text=message)
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
        BotCommand("risk", "Discipline score"),
        BotCommand("news", "Recent trades"),
        BotCommand("halt", "Emergency stop"),
        BotCommand("resume", "Resume after halt"),
    ])
    asyncio.create_task(poll_signals(app))
    await send_alert(app, GREEN + " Trading Bot online.")
    log.info("Telegram bot started, alert sent to chat %s", CHAT_ID)


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("halt", cmd_halt))
    app.add_handler(CommandHandler("resume", cmd_resume))
    log.info("Starting Telegram bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
