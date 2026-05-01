// Home — la página de inicio. Header friendly + hero card balance + grid 2
// columnas (operaciones abiertas + métricas hoy) + CTA "ver detalle".
// En modo experto agrega EquitySparkline y discipline.

import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
    ArrowRight,
    BookOpen,
    Activity,
    Wallet,
    Cpu,
    Pause,
    Radio,
    PlayCircle,
} from "lucide-react";
import {
    LineChart,
    Line,
    YAxis,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine,
} from "recharts";

import { useSettings } from "@/lib/userMode";
import { lotsToSize } from "@/lib/glossary";
import { apiGet } from "@/lib/api";

import GoalProgress from "@/components/atoms/GoalProgress";
import KpiCard from "@/components/atoms/KpiCard";
import EmptyState from "@/components/atoms/EmptyState";
import SkeletonPanel from "@/components/atoms/SkeletonPanel";
import HaltButton from "@/components/atoms/HaltButton";
import NovatoTooltip from "@/components/atoms/NovatoTooltip";

const TICK_MS = 4000;
const MAX_SAMPLES = 120;

const fmtMoney = (v, fr = 2) =>
    typeof v === "number" && Number.isFinite(v)
        ? `$${v.toLocaleString("en-US", { minimumFractionDigits: fr, maximumFractionDigits: fr })}`
        : "—";

const fmtPct = (v, fr = 2) =>
    typeof v === "number" && Number.isFinite(v)
        ? `${v >= 0 ? "+" : ""}${v.toFixed(fr)}%`
        : "—";

export default function Home() {
    const { settings, isNovato, isExperto } = useSettings();
    const [mt5, setMt5] = useState(null);
    const [stats, setStats] = useState(null);
    const [procs, setProcs] = useState({});
    const [capital, setCapital] = useState(null);
    const [equitySamples, setEquitySamples] = useState([]);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        try {
            const [m, s, p, c] = await Promise.allSettled([
                apiGet("/mt5/status"),
                apiGet("/journal/stats"),
                apiGet("/process/list"),
                apiGet("/capital"),
            ]);
            if (m.status === "fulfilled") {
                setMt5(m.value.data);
                const eq = m.value.data?.account?.equity;
                if (typeof eq === "number" && Number.isFinite(eq)) {
                    setEquitySamples((prev) => {
                        const next = [...prev, { t: Date.now(), equity: eq }];
                        if (next.length > MAX_SAMPLES) {
                            return next.slice(next.length - MAX_SAMPLES);
                        }
                        return next;
                    });
                }
            }
            if (s.status === "fulfilled") setStats(s.value.data);
            if (p.status === "fulfilled") {
                const map = {};
                (p.value.data?.processes || []).forEach((proc) => {
                    map[proc.name] = proc;
                });
                setProcs(map);
            }
            if (c.status === "fulfilled") setCapital(c.value.data);
        } catch (e) {
            console.error("home refresh error", e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, TICK_MS);
        return () => clearInterval(id);
    }, [refresh]);

    const acc = mt5?.account || {};
    const today = mt5?.today || {};
    const balance = acc.balance ?? capital?.current_capital_usd ?? 0;
    const equity = acc.equity ?? balance;
    const positions = mt5?.open_positions || [];
    const todayPnl = today?.total_pl_usd ?? stats?.today?.pnl_usd ?? 0;
    const todayPct = today?.total_pl_pct ?? stats?.today?.pnl_pct ?? 0;
    const goal = settings?.goal_usd;
    const startingBalance = capital?.starting_balance_usd ?? balance;
    const auto = procs?.auto_trader;
    const sync = procs?.sync_loop;
    const allUp = !!auto?.alive && !!sync?.alive;
    const todayTrades = stats?.today?.trades ?? 0;
    const todayWR = stats?.today?.win_rate;

    return (
        <section
            className="px-6 lg:px-10 py-8"
            data-testid="page-home"
        >
            <div className="max-w-[1400px] mx-auto">
                {/* Header */}
                <div className="flex items-end justify-between mb-6 gap-4 flex-wrap">
                    <div>
                        <div className="kicker mb-2">SECCIÓN 00 / INICIO</div>
                        <h1 className="font-display text-3xl md:text-4xl font-black tracking-tight">
                            Hola 👋
                        </h1>
                        <p className="mt-2 text-sm text-[var(--text-dim)]">
                            {isNovato
                                ? "Mirá tu cuenta de un vistazo. Si querés más detalle, todo está a un click."
                                : "Live overview. Refresca cada 4s."}
                        </p>
                    </div>
                </div>

                {loading && !mt5 ? (
                    <SkeletonPanel rows={4} />
                ) : (
                    <>
                        {/* Hero: balance + meta progress */}
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
                            <div className="panel p-6 lg:col-span-2" data-testid="hero-balance">
                                <div className="flex items-start justify-between gap-4 flex-wrap">
                                    <div>
                                        <div className="kicker mb-2 flex items-center gap-2">
                                            <Wallet size={12} className="text-[var(--green)]" />
                                            <NovatoTooltip term="equity">EQUITY EN VIVO</NovatoTooltip>
                                        </div>
                                        <div className="font-display text-4xl md:text-5xl font-black tabular leading-none">
                                            {fmtMoney(equity)}
                                        </div>
                                        <div className="mt-3 flex items-center gap-3 flex-wrap">
                                            <div
                                                className={`text-sm font-mono tabular ${
                                                    todayPnl >= 0
                                                        ? "text-[var(--green-bright)]"
                                                        : "text-[var(--red)]"
                                                }`}
                                            >
                                                {todayPnl >= 0 ? "▲" : "▼"}{" "}
                                                {fmtMoney(Math.abs(todayPnl))} ({fmtPct(todayPct)})
                                            </div>
                                            <span className="text-[var(--text-faint)] text-xs font-mono">
                                                hoy · saldo cerrado: {fmtMoney(balance)}
                                            </span>
                                        </div>
                                    </div>

                                    {/* Bot status pill */}
                                    <BotStatusPill allUp={allUp} auto={auto} sync={sync} />
                                </div>

                                {/* Sparkline solo en experto, novato lo oculta */}
                                {isExperto && equitySamples.length > 1 ? (
                                    <div className="mt-4 h-20" data-testid="equity-sparkline">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <LineChart
                                                data={equitySamples}
                                                margin={{ top: 4, right: 4, bottom: 4, left: 4 }}
                                            >
                                                <YAxis hide domain={["auto", "auto"]} />
                                                <ReferenceLine
                                                    y={equitySamples[0]?.equity}
                                                    stroke="rgba(255,255,255,0.18)"
                                                    strokeDasharray="3 3"
                                                />
                                                <Tooltip
                                                    formatter={(v) => [fmtMoney(v), "equity"]}
                                                    labelFormatter={() => ""}
                                                />
                                                <Line
                                                    type="monotone"
                                                    dataKey="equity"
                                                    stroke={
                                                        todayPnl >= 0 ? "#22c55e" : "#ef4444"
                                                    }
                                                    strokeWidth={2}
                                                    dot={false}
                                                    isAnimationActive={false}
                                                />
                                            </LineChart>
                                        </ResponsiveContainer>
                                    </div>
                                ) : null}
                            </div>

                            <GoalProgress
                                goal={goal}
                                current={equity}
                                starting={startingBalance}
                            />
                        </div>

                        {/* Grid 2 cols: operaciones abiertas + hoy */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                            <OpenPositionsCard positions={positions} isNovato={isNovato} />
                            <TodayCard
                                trades={todayTrades}
                                pnl={todayPnl}
                                wr={todayWR}
                            />
                        </div>

                        {/* CTAs */}
                        <div className="flex flex-wrap gap-3 mt-2">
                            <Link
                                to="/operaciones"
                                className="btn-sharp btn-xl primary flex items-center gap-2"
                                data-testid="cta-trades"
                            >
                                <BookOpen size={14} />
                                Ver operaciones
                                <ArrowRight size={14} />
                            </Link>
                            <Link
                                to="/configuracion"
                                className="btn-sharp btn-xl flex items-center gap-2"
                            >
                                <Cpu size={14} />
                                Configurar
                            </Link>
                            <HaltButton compact />
                        </div>
                    </>
                )}
            </div>
        </section>
    );
}

function BotStatusPill({ allUp, auto, sync }) {
    const partial = (auto?.alive || sync?.alive) && !allUp;
    let color, label, Icon;
    if (allUp) {
        color = "var(--green-bright)";
        label = "OPERANDO";
        Icon = Radio;
    } else if (partial) {
        color = "var(--amber)";
        label = "PARCIAL";
        Icon = Activity;
    } else {
        color = "var(--red)";
        label = "DETENIDO";
        Icon = Pause;
    }
    return (
        <div className="flex flex-col items-end gap-1">
            <div
                className="inline-flex items-center gap-2 px-3 py-1.5 border text-xs font-mono font-bold"
                style={{ color, borderColor: color }}
            >
                <Icon size={12} className={allUp ? "pulse-dot" : ""} />
                {label}
            </div>
            <div className="kicker text-[var(--text-faint)]">
                Estado del bot
            </div>
        </div>
    );
}

function OpenPositionsCard({ positions, isNovato }) {
    if (!positions || positions.length === 0) {
        return (
            <EmptyState
                icon={<Activity size={28} />}
                title="Sin operaciones abiertas"
                body="El bot está escaneando. Cuando encuentre una buena oportunidad, vas a verla acá."
            />
        );
    }

    return (
        <div className="panel p-5">
            <div className="kicker mb-3 flex items-center gap-2">
                <Activity size={12} className="text-[var(--amber)]" />
                OPERACIONES ABIERTAS · {positions.length}
            </div>
            <div className="space-y-2">
                {positions.slice(0, 4).map((p) => (
                    <PositionRow key={p.ticket} p={p} isNovato={isNovato} />
                ))}
                {positions.length > 4 ? (
                    <div className="text-xs text-[var(--text-faint)] font-mono">
                        +{positions.length - 4} más
                    </div>
                ) : null}
            </div>
        </div>
    );
}

function PositionRow({ p, isNovato }) {
    const positivePnL = (p.profit_usd ?? 0) >= 0;
    const sizeLabel = isNovato ? lotsToSize(p.lots) : `${p.lots} lots`;
    const sideLabel = p.side === "buy" ? "COMPRA" : "VENTA";
    return (
        <div className="flex items-center justify-between gap-2 px-3 py-2 panel border-[var(--border)]">
            <div className="min-w-0">
                <div className="font-mono text-sm font-bold">
                    {p.symbol}
                </div>
                <div className="text-[10px] text-[var(--text-faint)] font-mono">
                    {sideLabel} · {sizeLabel}
                </div>
            </div>
            <div
                className={`font-mono text-sm font-bold tabular ${
                    positivePnL ? "text-[var(--green-bright)]" : "text-[var(--red)]"
                }`}
            >
                {positivePnL ? "+" : ""}
                {fmtMoney(p.profit_usd)}
            </div>
        </div>
    );
}

function TodayCard({ trades, pnl, wr }) {
    return (
        <div className="panel p-5" data-testid="today-card">
            <div className="kicker mb-4 flex items-center gap-2">
                <PlayCircle size={12} className="text-[var(--green)]" />
                HOY
            </div>
            <div className="grid grid-cols-3 gap-3">
                <div>
                    <div className="kicker mb-1">Trades</div>
                    <div className="font-mono text-2xl tabular">{trades}</div>
                </div>
                <div>
                    <div className="kicker mb-1">P&L</div>
                    <div
                        className={`font-mono text-2xl tabular ${
                            pnl > 0
                                ? "text-[var(--green-bright)]"
                                : pnl < 0
                                ? "text-[var(--red)]"
                                : ""
                        }`}
                    >
                        {pnl >= 0 ? "+" : ""}
                        {fmtMoney(pnl)}
                    </div>
                </div>
                <div>
                    <div className="kicker mb-1">
                        <NovatoTooltip term="win_rate">WR</NovatoTooltip>
                    </div>
                    <div className="font-mono text-2xl tabular">
                        {wr != null ? `${Number(wr).toFixed(0)}%` : "—"}
                    </div>
                </div>
            </div>
        </div>
    );
}
