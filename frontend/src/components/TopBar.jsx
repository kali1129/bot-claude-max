// TopBar — sticky header global.
//
// Mejoras vs versión anterior:
//   · TICKER_ITEMS dinámico (lee user_settings.active_style_preset)
//   · UserModeBadge + HaltButton siempre visibles
//   · Polling con apiGet (sin axios pelado en cada componente)
//   · Title-case consistente (UTC, Equity, P&L de hoy, Posiciones, Estado)

import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { apiGet } from "@/lib/api";
import { useSettings } from "@/lib/userMode";

import UserModeBadge from "@/components/atoms/UserModeBadge";
import HaltButton from "@/components/atoms/HaltButton";

const fmtMoney = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? `$${n.toFixed(2)}` : "—";
};
const fmtPct = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` : "—";
};

function StatCell({ label, value, accent = "white", testId }) {
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
        </div>
    );
}

export default function TopBar() {
    const { settings } = useSettings();
    const preset = settings?.active_style_preset || {};

    const [time, setTime] = useState(new Date());
    const [mt5, setMt5] = useState(null);
    const [botAlive, setBotAlive] = useState(null);
    const [refreshing, setRefreshing] = useState(false);

    useEffect(() => {
        const t = setInterval(() => setTime(new Date()), 1000);
        return () => clearInterval(t);
    }, []);

    const fetchAll = async () => {
        try {
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
        } catch {
            // silent
        }
    };

    useEffect(() => {
        fetchAll();
        const id = setInterval(fetchAll, 4000);
        return () => clearInterval(id);
    }, []);

    const utcTime = time.toUTCString().slice(17, 25);

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

    // Ticker dinámico: lee del preset activo (si existe), si no, frases genéricas
    const tickerItems = buildTickerItems(preset, settings?.style);

    const handleRefresh = async () => {
        setRefreshing(true);
        await fetchAll();
        setTimeout(() => setRefreshing(false), 400);
    };

    return (
        <header
            className="sticky top-0 z-20 panel border-l-0 border-r-0 border-t-0"
            data-testid="topbar"
        >
            {/* Stat strip */}
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
                    <UserModeBadge compact />
                    <HaltButton compact />
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
