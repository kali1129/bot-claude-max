import { useEffect, useState } from "react";
import axios from "axios";
import { RefreshCcw } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const TICKER_ITEMS = [
    "REGLA_01 · MÁXIMO 1% DE RIESGO POR TRADE",
    "REGLA_02 · STOP TOTAL SI EL DÍA CAE -3%",
    "REGLA_03 · SOLO 1 POSICIÓN ABIERTA A LA VEZ",
    "REGLA_04 · RIESGO/RECOMPENSA MÍNIMO 1:2",
    "REGLA_05 · NO OPERAR 30 MIN ANTES O DESPUÉS DE NOTICIA FUERTE",
    "REGLA_06 · 3 PÉRDIDAS SEGUIDAS = STOP DEL DÍA",
    "REGLA_07 · 2 SEMANAS EN DEMO ANTES DE PASAR A REAL",
    "REGLA_08 · EL STOP SOLO SE MUEVE A FAVOR, NUNCA EN CONTRA",
];

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

export default function TopBar({ config, stats, onRefreshStats }) {
    const [time, setTime] = useState(new Date());
    // TopBar polls its own data so it can show LIVE truth even if the
    // parent's `stats` prop is stale (Dashboard polls /api/journal/stats
    // which only knows about CLOSED trades, not the open MT5 position
    // or the bot loop heartbeat).
    const [mt5, setMt5] = useState(null);
    const [botAlive, setBotAlive] = useState(null);

    useEffect(() => {
        const t = setInterval(() => setTime(new Date()), 1000);
        return () => clearInterval(t);
    }, []);

    useEffect(() => {
        const tick = async () => {
            try {
                const [m, p] = await Promise.allSettled([
                    axios.get(`${API}/mt5/status`, { timeout: 3000 }),
                    axios.get(`${API}/process/list`, { timeout: 3000 }),
                ]);
                if (m.status === "fulfilled") setMt5(m.value.data);
                if (p.status === "fulfilled") {
                    const at = (p.value.data?.processes || []).find((x) => x.name === "auto_trader");
                    setBotAlive(!!at?.alive);
                }
            } catch {
                // silent
            }
        };
        tick();
        const id = setInterval(tick, 4000);
        return () => clearInterval(id);
    }, []);

    const utcTime = time.toUTCString().slice(17, 25);

    // Live values; fall back to props.stats / config when /api/mt5/status not yet returned
    const acc = mt5?.account;
    const today = mt5?.today;
    const equity = acc?.equity ?? stats?.current_equity ?? config?.capital ?? 0;
    const todayPnLusd = today?.total_pl_usd ?? stats?.today?.pnl_usd ?? 0;
    const todayPct = today?.total_pl_pct ?? stats?.today?.pnl_pct ?? 0;
    const open = (mt5?.open_positions || []).length || stats?.today?.open_positions || 0;
    const mt5Connected = !!mt5?.connected;
    const tradeAllowed = mt5?.account?.trade_allowed ?? true;

    // Estado combinado: bot + MT5 + trade_allowed. Mantenerlo sincronizado
    // con la realidad evita el viejo bug donde decía "OPERATIVO" mientras
    // auto_trader estaba muerto.
    let stateLabel, stateAccent;
    if (!mt5Connected) {
        stateLabel = "SIN MT5";
        stateAccent = "amber";
    } else if (!tradeAllowed) {
        stateLabel = "BLOQUEADO";
        stateAccent = "red";
    } else if (botAlive === false) {
        stateLabel = "BOT PARADO";
        stateAccent = "red";
    } else if (botAlive === null) {
        stateLabel = "CHECANDO…";
        stateAccent = "amber";
    } else {
        stateLabel = "OPERANDO";
        stateAccent = "green";
    }

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
                        !mt5Connected ? "amber"
                        : equity >= (acc?.balance ?? equity) ? "green"
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
                    value={`${open} / 1`}
                    accent={open > 1 ? "red" : open === 1 ? "amber" : "green"}
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
                    <button
                        type="button"
                        onClick={onRefreshStats}
                        className="btn-sharp"
                        data-testid="refresh-stats-btn"
                        title="Refrescar"
                    >
                        <RefreshCcw size={12} />
                    </button>
                </div>
            </div>

            {/* Ticker */}
            <div className="border-t border-[var(--border)] overflow-hidden bg-[var(--bg)]">
                <div className="ticker-track flex gap-12 py-1.5 px-4">
                    {[...TICKER_ITEMS, ...TICKER_ITEMS].map((it, i) => (
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
