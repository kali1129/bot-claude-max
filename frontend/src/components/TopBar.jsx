// TopBar — sticky header global.
//
// v3.2 (multi-cuenta): la barra de equity/P&L solo muestra datos REALES
// para admin (su MT5). Para users no-admin, muestra placeholders y el
// estado de SU bot personal. Anónimos ven la barra del admin (preview
// público).

import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { apiGet } from "@/lib/api";
import { useSettings } from "@/lib/userMode";

import UserModeBadge from "@/components/atoms/UserModeBadge";
import HaltButton from "@/components/atoms/HaltButton";
import AuthCorner from "@/components/atoms/AuthCorner";
import { useAuth } from "@/lib/AuthProvider";

const fmtMoney = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? `$${n.toFixed(2)}` : "—";
};
const fmtPct = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` : "—";
};

function StatCell({ label, value, accent = "white", testId, sublabel }) {
    const color =
        accent === "green"
            ? "text-[var(--green-bright)]"
            : accent === "red"
            ? "text-[var(--red)]"
            : accent === "amber"
            ? "text-[var(--amber)]"
            : "text-white";
    return (
        <div className="px-5 py-3 border-r border-[var(--border)] flex flex-col justify-center min-w-[140px]">
            <div className="kicker mb-0.5">{label}</div>
            <div
                className={`font-mono text-[15px] font-semibold tabular ${color}`}
                data-testid={testId}
            >
                {value}
            </div>
            {sublabel ? (
                <div className="text-[9px] text-[var(--text-faint)] font-mono mt-0.5 truncate">
                    {sublabel}
                </div>
            ) : null}
        </div>
    );
}

export default function TopBar() {
    const { settings } = useSettings();
    const preset = settings?.active_style_preset || {};
    const { isAdmin, isAuthenticated } = useAuth();

    const [time, setTime] = useState(new Date());
    const [mt5, setMt5] = useState(null);
    const [botAlive, setBotAlive] = useState(null);
    // Per-user: su broker activo + estado de SU bot
    const [userBroker, setUserBroker] = useState(null);
    const [userBot, setUserBot] = useState(null);
    const [refreshing, setRefreshing] = useState(false);

    useEffect(() => {
        const t = setInterval(() => setTime(new Date()), 1000);
        return () => clearInterval(t);
    }, []);

    const fetchAll = async () => {
        try {
            // Datos del admin (siempre, para admin / anon preview)
            const [m, p] = await Promise.allSettled([
                apiGet("/mt5/status", { timeout: 3000 }),
                apiGet("/process/list", { timeout: 3000 }),
            ]);
            if (m.status === "fulfilled") setMt5(m.value.data);
            if (p.status === "fulfilled") {
                const at = (p.value.data?.processes || []).find(
                    (x) => x.name === "auto_trader"
                );
                setBotAlive(!!at?.alive);
            }
            // Datos del user logueado (no admin)
            if (isAuthenticated && !isAdmin) {
                const [b, bot] = await Promise.allSettled([
                    apiGet("/users/me/broker", { timeout: 3000 }),
                    apiGet("/users/me/bot", { timeout: 3000 }),
                ]);
                if (b.status === "fulfilled") setUserBroker(b.value.data);
                if (bot.status === "fulfilled") setUserBot(bot.value.data);
            }
        } catch {
            // silent
        }
    };

    useEffect(() => {
        fetchAll();
        const id = setInterval(fetchAll, 4000);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isAdmin, isAuthenticated]);

    const utcTime = time.toUTCString().slice(17, 25);
    const isUserView = isAuthenticated && !isAdmin;

    // Ticker dinámico: lee del preset activo
    const tickerItems = buildTickerItems(preset, settings?.style);

    const handleRefresh = async () => {
        setRefreshing(true);
        await fetchAll();
        setTimeout(() => setRefreshing(false), 400);
    };

    // ─── RENDER: USER NO-ADMIN VIEW ───
    if (isUserView) {
        const active = userBroker?.active;
        const hasActive = !!active;
        const userBotRunning = !!userBot?.running;
        let stateLabel, stateAccent, stateSub;
        if (!hasActive) {
            stateLabel = "Sin Broker";
            stateAccent = "amber";
            stateSub = "conectá tu cuenta";
        } else if (!userBotRunning) {
            stateLabel = "Detenido";
            stateAccent = "amber";
            stateSub = "presioná Iniciar bot";
        } else {
            stateLabel = "Activo";
            stateAccent = "green";
            stateSub = userBot?.is_admin ? "sin trial" : userBot?.is_paid ? "pago" : "trial 24h";
        }

        return (
            <header className="sticky top-0 z-20 panel border-l-0 border-r-0 border-t-0" data-testid="topbar">
                <div className="flex items-stretch overflow-x-auto">
                    <StatCell label="UTC" value={utcTime} testId="utc-time" />
                    <StatCell
                        label="Tu cuenta"
                        value={hasActive
                            ? (active.is_demo ? "📊 DEMO" : "💰 REAL")
                            : "—"}
                        sublabel={hasActive ? `login ${active.mt5_login}` : "no conectada"}
                        accent={hasActive ? (active.is_demo ? "white" : "amber") : "amber"}
                        testId="user-account"
                    />
                    <StatCell
                        label="Equity"
                        value={hasActive ? "—" : "—"}
                        sublabel={hasActive ? "datos en vivo en tu broker" : ""}
                        accent="white"
                        testId="equity-value"
                    />
                    <StatCell
                        label="P&L de hoy"
                        value="—"
                        sublabel={hasActive ? "consultá tu MT5" : ""}
                        accent="white"
                        testId="today-pnl"
                    />
                    <StatCell
                        label="Estado del bot"
                        value={stateLabel}
                        sublabel={stateSub}
                        accent={stateAccent}
                        testId="trade-status"
                    />
                    <div className="flex-1" />
                    <div className="flex items-center gap-2 px-4 border-l border-[var(--border)]">
                        <AuthCorner />
                        <button
                            type="button"
                            onClick={handleRefresh}
                            className="btn-sharp"
                            data-testid="refresh-stats-btn"
                            title="Refrescar"
                            aria-label="Refrescar datos"
                            disabled={refreshing}
                        >
                            <RefreshCcw size={12} className={refreshing ? "animate-spin" : ""} />
                        </button>
                    </div>
                </div>

                {/* Banner explicativo */}
                <div
                    className="border-t border-[var(--border)] px-4 py-1.5 text-[10px] font-mono"
                    style={{ background: "rgba(59,130,246,0.05)" }}
                >
                    <span className="text-[var(--blue)]">ℹ</span>{" "}
                    <span className="text-[var(--text-dim)]">
                        Tu cuenta está {hasActive ? "conectada" : "sin conectar"}.
                        El equity y P&L en vivo los ves directo en tu app MT5
                        (acá sólo configurás el bot que opera por vos).
                    </span>
                </div>

                {/* Ticker */}
                <div className="border-t border-[var(--border)] overflow-hidden bg-[var(--bg)]">
                    <div className="ticker-track flex gap-12 py-1.5 px-4">
                        {[...tickerItems, ...tickerItems].map((it, i) => (
                            <span
                                key={i}
                                className="kicker text-[var(--text-dim)] whitespace-nowrap"
                            >
                                <span className="text-[var(--green)]">›</span> {it}
                            </span>
                        ))}
                    </div>
                </div>
            </header>
        );
    }

    // ─── RENDER: ADMIN o ANÓNIMO VIEW (admin's MT5 = preview público) ───
    const acc = mt5?.account;
    const today = mt5?.today;
    const equity = acc?.equity ?? 0;
    const todayPnLusd = today?.total_pl_usd ?? 0;
    const todayPct = today?.total_pl_pct ?? 0;
    const open = (mt5?.open_positions || []).length;
    const mt5Connected = !!mt5?.connected;
    const tradeAllowed = mt5?.account?.trade_allowed ?? true;
    const maxPos = preset.max_pos ?? 1;

    let stateLabel, stateAccent;
    if (!mt5Connected) {
        stateLabel = "Sin MT5";
        stateAccent = "amber";
    } else if (!tradeAllowed) {
        stateLabel = "Bloqueado";
        stateAccent = "red";
    } else if (botAlive === false) {
        stateLabel = "Bot Parado";
        stateAccent = "red";
    } else if (botAlive === null) {
        stateLabel = "Checando";
        stateAccent = "amber";
    } else {
        stateLabel = "Operando";
        stateAccent = "green";
    }

    return (
        <header className="sticky top-0 z-20 panel border-l-0 border-r-0 border-t-0" data-testid="topbar">
            <div className="flex items-stretch overflow-x-auto">
                <StatCell label="UTC" value={utcTime} testId="utc-time" />
                <StatCell
                    label="Equity"
                    value={fmtMoney(equity)}
                    accent={
                        !mt5Connected
                            ? "amber"
                            : equity >= (acc?.balance ?? equity)
                            ? "green"
                            : "red"
                    }
                    testId="equity-value"
                />
                <StatCell
                    label="P&L de hoy"
                    value={`${todayPnLusd >= 0 ? "+" : ""}${fmtMoney(todayPnLusd)} · ${fmtPct(todayPct)}`}
                    accent={todayPnLusd > 0 ? "green" : todayPnLusd < 0 ? "red" : "white"}
                    testId="today-pnl"
                />
                <StatCell
                    label="Posiciones"
                    value={`${open} / ${maxPos}`}
                    accent={open > maxPos ? "red" : open >= 1 ? "amber" : "green"}
                    testId="open-positions"
                />
                <StatCell
                    label="Estado"
                    value={stateLabel}
                    accent={stateAccent}
                    testId="trade-status"
                />
                <div className="flex-1" />
                <div className="flex items-center gap-2 px-4 border-l border-[var(--border)]">
                    {isAdmin ? <UserModeBadge compact /> : null}
                    {isAdmin ? <HaltButton compact /> : null}
                    <AuthCorner />
                    <button
                        type="button"
                        onClick={handleRefresh}
                        className="btn-sharp"
                        data-testid="refresh-stats-btn"
                        title="Refrescar"
                        aria-label="Refrescar datos"
                        disabled={refreshing}
                    >
                        <RefreshCcw size={12} className={refreshing ? "animate-spin" : ""} />
                    </button>
                </div>
            </div>

            <div className="border-t border-[var(--border)] overflow-hidden bg-[var(--bg)]">
                <div className="ticker-track flex gap-12 py-1.5 px-4">
                    {[...tickerItems, ...tickerItems].map((it, i) => (
                        <span
                            key={i}
                            className="kicker text-[var(--text-dim)] whitespace-nowrap"
                        >
                            <span className="text-[var(--green)]">›</span> {it}
                        </span>
                    ))}
                </div>
            </div>
        </header>
    );
}

function buildTickerItems(preset, style = "balanceado") {
    const items = [];
    if (preset?.risk_pct != null) {
        items.push(
            `REGLA · MÁXIMO ${preset.risk_pct}% DE RIESGO POR TRADE`
        );
    }
    if (preset?.max_daily_loss_pct != null) {
        items.push(
            `REGLA · STOP TOTAL SI EL DÍA CAE -${preset.max_daily_loss_pct}%`
        );
    }
    if (preset?.max_pos != null) {
        items.push(
            `REGLA · MÁXIMO ${preset.max_pos} POSICIÓN${preset.max_pos !== 1 ? "ES" : ""} ABIERTAS A LA VEZ`
        );
    }
    if (preset?.min_rr != null) {
        items.push(
            `REGLA · RIESGO/RECOMPENSA MÍNIMO 1:${preset.min_rr}`
        );
    }
    items.push(`ESTILO ACTIVO · ${String(style).toUpperCase()}`);
    items.push("REGLA · NO OPERAR 30 MIN ANTES O DESPUÉS DE NOTICIA FUERTE");
    items.push("REGLA · EL STOP SOLO SE MUEVE A FAVOR, NUNCA EN CONTRA");
    return items.length ? items : ["TRADING AUTOMÁTICO"];
}
