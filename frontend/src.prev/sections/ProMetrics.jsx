/**
 * ProMetrics — Phase 1 professional trading metrics dashboard.
 *
 * Shows: Sharpe, Sortino, SQN, Profit Factor, Max Drawdown, Calmar,
 * equity curve, daily P&L heatmap, consecutive streaks, per-strategy breakdown.
 *
 * Data from GET /api/research/summary (pro_metrics, equity_curve, daily_pnl_heatmap, by_strategy fields).
 */
import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
    TrendingUp, TrendingDown, BarChart3, Activity, Shield,
    Flame, Target, Zap, AlertTriangle, Award
} from "lucide-react";

// ── Helpers ──────────────────────────────────────────────────────
const fmtNum = (v, dec = 2) =>
    typeof v === "number" ? (v >= 0 ? `+${v.toFixed(dec)}` : v.toFixed(dec)) : "—";
const fmtPct = (v) => (typeof v === "number" ? `${v.toFixed(1)}%` : "—");
const fmtMoney = (v) =>
    typeof v === "number"
        ? `${v >= 0 ? "+" : ""}$${Math.abs(v).toFixed(2)}`
        : "—";

function ratingColor(label) {
    switch (label) {
        case "Excelente": return "var(--green)";
        case "Bueno": return "#4ade80";
        case "Aceptable": return "var(--amber, #f59e0b)";
        case "Débil": return "#fb923c";
        case "Malo": return "var(--red)";
        default: return "var(--text-dim)";
    }
}

function sqnRating(v) {
    if (v === null || v === undefined) return { label: "—", color: "var(--text-faint)" };
    if (v >= 3.0) return { label: "Excelente", color: ratingColor("Excelente") };
    if (v >= 2.0) return { label: "Bueno", color: ratingColor("Bueno") };
    if (v >= 1.0) return { label: "Aceptable", color: ratingColor("Aceptable") };
    if (v >= 0) return { label: "Débil", color: ratingColor("Débil") };
    return { label: "Malo", color: ratingColor("Malo") };
}

function sharpeRating(v) {
    if (v === null || v === undefined) return { label: "—", color: "var(--text-faint)" };
    if (v >= 2.0) return { label: "Excelente", color: ratingColor("Excelente") };
    if (v >= 1.0) return { label: "Bueno", color: ratingColor("Bueno") };
    if (v >= 0.5) return { label: "Aceptable", color: ratingColor("Aceptable") };
    if (v >= 0) return { label: "Débil", color: ratingColor("Débil") };
    return { label: "Malo", color: ratingColor("Malo") };
}

// ── MetricCard ───────────────────────────────────────────────────
function MetricCard({ icon: Icon, label, value, subtext, rating, color }) {
    return (
        <div className="panel p-4 flex flex-col gap-1">
            <div className="flex items-center gap-2 mb-1">
                <Icon size={14} className="text-[var(--text-faint)]" />
                <span className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider font-mono">
                    {label}
                </span>
            </div>
            <div
                className="font-display text-2xl font-black"
                style={{ color: color || "var(--text)" }}
            >
                {value}
            </div>
            {rating && (
                <span
                    className="text-[10px] font-mono font-semibold tracking-wider"
                    style={{ color: rating.color }}
                >
                    {rating.label}
                </span>
            )}
            {subtext && (
                <span className="text-[10px] text-[var(--text-faint)]">{subtext}</span>
            )}
        </div>
    );
}

// ── MiniEquityCurve with Drawdown overlay ────────────────────────
function MiniEquityCurve({ data }) {
    if (!data || data.length < 2) {
        return (
            <div className="text-center py-8 text-[var(--text-faint)] text-xs font-mono">
                Necesita al menos 2 d\u00edas de datos para la curva de equity
            </div>
        );
    }

    const equities = data.map((d) => d.equity);
    const minE = Math.min(...equities);
    const maxE = Math.max(...equities);
    const range = maxE - minE || 1;
    const h = 120;
    const w = Math.max(data.length * 12, 200);

    // Compute drawdown at each point
    let peak = equities[0];
    const drawdowns = equities.map((eq) => {
        if (eq > peak) peak = eq;
        return peak > 0 ? ((peak - eq) / peak) * 100 : 0;
    });
    const maxDD = Math.max(...drawdowns, 0.1);
    const ddH = 30;

    // SVG polyline for equity
    const points = data
        .map((d, i) => {
            const x = (i / (data.length - 1)) * w;
            const y = h - ((d.equity - minE) / range) * (h - 10) - 5;
            return `${x},${y}`;
        })
        .join(" ");

    // SVG polyline for drawdown
    const ddPoints = drawdowns
        .map((dd, i) => {
            const x = (i / (data.length - 1)) * w;
            const y = (dd / maxDD) * ddH;
            return `${x},${y}`;
        })
        .join(" ");

    const lastEq = equities[equities.length - 1];
    const lineColor = lastEq >= 0 ? "var(--green)" : "var(--red)";
    const areaPoints = `0,${h} ${points} ${w},${h}`;

    return (
        <div className="overflow-x-auto">
            {/* Drawdown overlay */}
            <div className="mb-1">
                <span className="text-[9px] text-[var(--text-faint)] font-mono">
                    DRAWDOWN (max: {maxDD.toFixed(1)}%)
                </span>
                <svg width={w} height={ddH} viewBox={`0 0 ${w} ${ddH}`} className="block">
                    <polygon
                        points={`0,0 ${ddPoints} ${w},0`}
                        fill="rgba(239, 68, 68, 0.2)"
                    />
                    <polyline
                        points={ddPoints}
                        fill="none"
                        stroke="var(--red)"
                        strokeWidth={1}
                        opacity={0.5}
                    />
                </svg>
            </div>
            {/* Equity curve */}
            <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="block">
                {[0.25, 0.5, 0.75].map((pct) => (
                    <line
                        key={pct}
                        x1={0}
                        y1={h - pct * (h - 10) - 5}
                        x2={w}
                        y2={h - pct * (h - 10) - 5}
                        stroke="var(--border)"
                        strokeWidth={0.5}
                        strokeDasharray="4 4"
                    />
                ))}
                {minE < 0 && maxE > 0 && (
                    <line
                        x1={0}
                        y1={h - ((0 - minE) / range) * (h - 10) - 5}
                        x2={w}
                        y2={h - ((0 - minE) / range) * (h - 10) - 5}
                        stroke="var(--text-faint)"
                        strokeWidth={1}
                        strokeDasharray="2 2"
                        opacity={0.5}
                    />
                )}
                <polygon points={areaPoints} fill={lineColor} opacity={0.08} />
                <polyline
                    points={points}
                    fill="none"
                    stroke={lineColor}
                    strokeWidth={2}
                    strokeLinejoin="round"
                />
                {data.length > 0 && (() => {
                    const lastX = w;
                    const lastY = h - ((lastEq - minE) / range) * (h - 10) - 5;
                    return <circle cx={lastX} cy={lastY} r={3} fill={lineColor} />;
                })()}
            </svg>
            <div className="flex justify-between text-[9px] text-[var(--text-faint)] font-mono mt-1 px-1">
                <span>{data[0]?.date}</span>
                {data.length > 2 && <span>{data[Math.floor(data.length / 2)]?.date}</span>}
                <span>{data[data.length - 1]?.date}</span>
            </div>
        </div>
    );
}

// ── DailyPnlHeatmap (calendar-style) ─────────────────────────────
function DailyPnlHeatmap({ data }) {
    if (!data || data.length === 0) {
        return (
            <div className="text-center py-4 text-[var(--text-faint)] text-xs font-mono">
                Sin datos de P&L diario
            </div>
        );
    }

    const maxAbs = Math.max(...data.map((d) => Math.abs(d.pnl)), 1);
    const DAYS = ["L", "M", "X", "J", "V", "S", "D"];

    // Group by week for calendar layout
    const weeks = [];
    let currentWeek = [];
    data.forEach((d) => {
        const date = new Date(d.date + "T00:00:00Z");
        const dow = (date.getUTCDay() + 6) % 7; // Monday=0
        // Pad start of first week
        if (weeks.length === 0 && currentWeek.length === 0) {
            for (let i = 0; i < dow; i++) {
                currentWeek.push(null);
            }
        }
        currentWeek.push(d);
        if (dow === 6) {
            weeks.push(currentWeek);
            currentWeek = [];
        }
    });
    if (currentWeek.length > 0) weeks.push(currentWeek);

    return (
        <div>
            {/* Day headers */}
            <div className="flex gap-0.5 mb-0.5 ml-[24px]">
                {DAYS.map((d) => (
                    <div key={d} className="w-7 text-center text-[8px] text-[var(--text-faint)] font-mono">
                        {d}
                    </div>
                ))}
            </div>
            {/* Calendar grid */}
            {weeks.map((week, wi) => (
                <div key={wi} className="flex gap-0.5 mb-0.5">
                    <div className="w-[20px] text-[8px] text-[var(--text-faint)] font-mono flex items-center">
                        {week.find((d) => d)?.date?.slice(5, 7) || ""}
                    </div>
                    {week.map((d, di) => {
                        if (!d) {
                            return <div key={di} className="w-7 h-7 rounded" />;
                        }
                        const intensity = Math.min(Math.abs(d.pnl) / maxAbs, 1);
                        const bg =
                            d.pnl > 0
                                ? `rgba(34, 197, 94, ${0.15 + intensity * 0.6})`
                                : d.pnl < 0
                                ? `rgba(239, 68, 68, ${0.15 + intensity * 0.6})`
                                : "rgba(156, 163, 175, 0.1)";
                        return (
                            <div
                                key={di}
                                className="w-7 h-7 rounded flex items-center justify-center text-[7px] font-mono cursor-default transition-transform hover:scale-110"
                                style={{ background: bg }}
                                title={`${d.date}: ${d.pnl >= 0 ? "+" : ""}$${Math.abs(d.pnl).toFixed(2)}`}
                            >
                                {d.date.slice(8)}
                            </div>
                        );
                    })}
                </div>
            ))}
            {/* Legend */}
            <div className="flex items-center gap-2 mt-2 text-[8px] text-[var(--text-faint)] font-mono">
                <span>Loss</span>
                <div className="flex gap-0.5">
                    {[0.15, 0.35, 0.55, 0.75].map((op) => (
                        <div key={op} className="w-3 h-3 rounded" style={{ background: `rgba(239, 68, 68, ${op})` }} />
                    ))}
                </div>
                <span className="mx-1">|</span>
                <div className="flex gap-0.5">
                    {[0.15, 0.35, 0.55, 0.75].map((op) => (
                        <div key={op} className="w-3 h-3 rounded" style={{ background: `rgba(34, 197, 94, ${op})` }} />
                    ))}
                </div>
                <span>Profit</span>
            </div>
        </div>
    );
}

// ── StrategyBreakdown ────────────────────────────────────────────
function StrategyBreakdown({ data }) {
    if (!data || Object.keys(data).length === 0) {
        return (
            <div className="text-center py-4 text-[var(--text-faint)] text-xs font-mono">
                Sin datos por estrategia
            </div>
        );
    }

    return (
        <div className="space-y-2">
            {Object.entries(data).map(([sid, s]) => (
                <div
                    key={sid}
                    className="flex items-center justify-between py-2 px-3 rounded"
                    style={{ background: "rgba(255,255,255,0.02)" }}
                >
                    <div>
                        <span className="font-mono text-xs font-semibold">{sid}</span>
                        <span className="text-[10px] text-[var(--text-faint)] ml-2">
                            {s.n} trades
                        </span>
                    </div>
                    <div className="flex items-center gap-4 text-xs font-mono">
                        <span style={{ color: s.win_rate_pct >= 50 ? "var(--green)" : "var(--red)" }}>
                            WR {s.win_rate_pct}%
                        </span>
                        <span style={{ color: s.avg_r >= 0 ? "var(--green)" : "var(--red)" }}>
                            {s.avg_r >= 0 ? "+" : ""}{s.avg_r}R
                        </span>
                        <span
                            className="font-semibold"
                            style={{ color: s.pnl >= 0 ? "var(--green)" : "var(--red)" }}
                        >
                            {fmtMoney(s.pnl)}
                        </span>
                    </div>
                </div>
            ))}
        </div>
    );
}

// ── Main Component ───────────────────────────────────────────────
export default function ProMetrics({ api }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchData = useCallback(async () => {
        try {
            const res = await axios.get(`${api}/research/summary`);
            setData(res.data);
            setError(null);
        } catch (e) {
            setError(e.response?.data?.detail || e.message);
        } finally {
            setLoading(false);
        }
    }, [api]);

    useEffect(() => {
        fetchData();
        const id = setInterval(fetchData, 15000);
        return () => clearInterval(id);
    }, [fetchData]);

    if (loading) {
        return (
            <section id="metrics" className="px-6 lg:px-10 py-12 border-b border-[var(--border)]">
                <div className="text-center py-12 text-[var(--text-faint)] font-mono text-sm">
                    Cargando métricas profesionales...
                </div>
            </section>
        );
    }

    if (error) {
        return (
            <section id="metrics" className="px-6 lg:px-10 py-12 border-b border-[var(--border)]">
                <div className="panel p-6 text-center">
                    <div className="text-[var(--red)] font-mono text-sm mb-2">Error cargando métricas</div>
                    <div className="text-[var(--text-faint)] text-xs">{error}</div>
                </div>
            </section>
        );
    }

    if (!data || data.empty) {
        return (
            <section id="metrics" className="px-6 lg:px-10 py-12 border-b border-[var(--border)]">
                <div className="kicker mb-1">// 05</div>
                <h2 className="section-title">Métricas Pro</h2>
                <div className="panel p-8 text-center">
                    <Activity size={32} className="mx-auto mb-3 text-[var(--text-faint)]" />
                    <p className="text-sm text-[var(--text-dim)]">
                        Sin datos suficientes. Las métricas aparecerán cuando haya trades cerrados en el research log.
                    </p>
                </div>
            </section>
        );
    }

    const pm = data.pro_metrics || {};
    const sharpeR = sharpeRating(pm.sharpe_ratio);
    const sqnR = sqnRating(pm.sqn);

    // P&L color
    const pnlColor = data.total_pnl_usd > 0 ? "var(--green)" : data.total_pnl_usd < 0 ? "var(--red)" : "var(--text-dim)";
    const pfColor = pm.profit_factor >= 1.5 ? "var(--green)" : pm.profit_factor >= 1.0 ? "var(--amber, #f59e0b)" : "var(--red)";

    return (
        <section id="metrics" className="px-6 lg:px-10 py-12 border-b border-[var(--border)]" data-testid="section-metrics">
            <div className="kicker mb-1">// 05</div>
            <h2 className="section-title">Métricas Pro</h2>
            <p className="text-sm text-[var(--text-dim)] mb-6 max-w-2xl">
                Métricas profesionales de rendimiento: Sharpe, Sortino, SQN (Van Tharp),
                Profit Factor, Max Drawdown. Actualizadas en tiempo real desde el research log.
            </p>

            {/* Top-line summary */}
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-6">
                <MetricCard
                    icon={TrendingUp}
                    label="Sharpe Ratio"
                    value={fmtNum(pm.sharpe_ratio, 3)}
                    rating={sharpeR}
                    color={sharpeR.color}
                />
                <MetricCard
                    icon={TrendingUp}
                    label="Sortino Ratio"
                    value={fmtNum(pm.sortino_ratio, 3)}
                    rating={sharpeRating(pm.sortino_ratio)}
                    color={sharpeRating(pm.sortino_ratio).color}
                />
                <MetricCard
                    icon={Target}
                    label="SQN"
                    value={fmtNum(pm.sqn, 3)}
                    subtext="Van Tharp System Quality"
                    rating={sqnR}
                    color={sqnR.color}
                />
                <MetricCard
                    icon={BarChart3}
                    label="Profit Factor"
                    value={pm.profit_factor != null ? pm.profit_factor.toFixed(3) : "—"}
                    subtext={`${fmtMoney(pm.gross_profit)} / ${fmtMoney(pm.gross_loss)}`}
                    color={pfColor}
                />
                <MetricCard
                    icon={AlertTriangle}
                    label="Max Drawdown"
                    value={fmtMoney(pm.max_drawdown_usd)}
                    subtext={fmtPct(pm.max_drawdown_pct)}
                    color="var(--red)"
                />
                <MetricCard
                    icon={Shield}
                    label="Calmar Ratio"
                    value={fmtNum(pm.calmar_ratio, 3)}
                    subtext="Ret. anual / Max DD"
                    color={pm.calmar_ratio > 0 ? "var(--green)" : "var(--red)"}
                />
            </div>

            {/* Secondary stats row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
                <MetricCard
                    icon={Activity}
                    label="P&L Total"
                    value={fmtMoney(data.total_pnl_usd)}
                    color={pnlColor}
                />
                <MetricCard
                    icon={Flame}
                    label="Win Rate"
                    value={fmtPct(data.win_rate_pct)}
                    subtext={`${data.wins}W / ${data.losses}L de ${data.n_closed}`}
                    color={data.win_rate_pct >= 50 ? "var(--green)" : "var(--red)"}
                />
                <MetricCard
                    icon={Award}
                    label="Racha Max Wins"
                    value={pm.max_consecutive_wins || 0}
                    color="var(--green)"
                />
                <MetricCard
                    icon={TrendingDown}
                    label="Racha Max Losses"
                    value={pm.max_consecutive_losses || 0}
                    color="var(--red)"
                />
            </div>

            {/* Equity Curve */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-6">
                <div className="panel p-4">
                    <div className="kicker mb-3">CURVA DE EQUITY</div>
                    <MiniEquityCurve data={data.equity_curve} />
                </div>

                <div className="panel p-4">
                    <div className="kicker mb-3">P&L DIARIO (HEATMAP)</div>
                    <DailyPnlHeatmap data={data.daily_pnl_heatmap} />
                    <div className="flex items-center gap-4 mt-3 text-[9px] text-[var(--text-faint)] font-mono">
                        <span>{pm.n_trading_days || 0} días de trading</span>
                        <span>Promedio diario: {fmtMoney(pm.avg_daily_pnl)}</span>
                    </div>
                </div>
            </div>

            {/* Per-strategy breakdown */}
            <div className="panel p-4">
                <div className="kicker mb-3">RENDIMIENTO POR ESTRATEGIA</div>
                <StrategyBreakdown data={data.by_strategy} />
            </div>
        </section>
    );
}
