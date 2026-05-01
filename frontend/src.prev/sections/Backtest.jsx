/**
 * Backtest — Phase 2 backtesting dashboard section.
 *
 * Allows running backtests per strategy on synthetic/historical data.
 * Shows metrics comparison, equity curve, and trade list.
 *
 * API: GET /api/backtest/strategies, POST /api/backtest/strategy
 */
import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
    Play, BarChart3, TrendingUp, TrendingDown, Target,
    AlertTriangle, Loader2, ChevronDown, ChevronUp
} from "lucide-react";

const TOKEN = process.env.REACT_APP_DASHBOARD_TOKEN || "";
const authHeaders = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};

const fmtNum = (v, dec = 2) =>
    typeof v === "number" ? v.toFixed(dec) : "—";
const fmtPct = (v) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—");
const fmtMoney = (v) =>
    typeof v === "number"
        ? `${v >= 0 ? "+" : ""}$${Math.abs(v).toFixed(2)}`
        : "—";

// ── Equity Curve SVG with Drawdown Overlay ──────────────────────
function EquityCurveWithDD({ data, initialBalance }) {
    if (!data || data.length < 2) {
        return (
            <div className="text-center py-8 text-[var(--text-faint)] text-xs font-mono">
                Sin datos de equity para graficar
            </div>
        );
    }

    const equities = data.map((d) => d.equity);
    const minE = Math.min(...equities);
    const maxE = Math.max(...equities);
    const range = maxE - minE || 1;
    const h = 150;
    const w = Math.max(data.length * 6, 300);

    // Compute drawdown at each point
    let peak = equities[0];
    const drawdowns = equities.map((eq) => {
        if (eq > peak) peak = eq;
        return peak > 0 ? ((peak - eq) / peak) * 100 : 0;
    });
    const maxDD = Math.max(...drawdowns, 1);

    // SVG points for equity
    const eqPoints = data
        .map((d, i) => {
            const x = (i / (data.length - 1)) * w;
            const y = h - ((d.equity - minE) / range) * (h - 20) - 10;
            return `${x},${y}`;
        })
        .join(" ");

    // SVG points for drawdown (inverted, from top)
    const ddH = 40; // height of DD overlay area
    const ddPoints = drawdowns
        .map((dd, i) => {
            const x = (i / (data.length - 1)) * w;
            const y = (dd / maxDD) * ddH;
            return `${x},${y}`;
        })
        .join(" ");

    const lastEq = equities[equities.length - 1];
    const lineColor = lastEq >= initialBalance ? "var(--green)" : "var(--red)";

    return (
        <div className="overflow-x-auto">
            {/* Drawdown bar */}
            <div className="mb-1">
                <span className="text-[9px] text-[var(--text-faint)] font-mono">DRAWDOWN</span>
                <svg width={w} height={ddH} viewBox={`0 0 ${w} ${ddH}`} className="block">
                    <polygon
                        points={`0,0 ${ddPoints} ${w},0`}
                        fill="rgba(239, 68, 68, 0.25)"
                    />
                    <polyline
                        points={ddPoints}
                        fill="none"
                        stroke="var(--red)"
                        strokeWidth={1}
                        opacity={0.6}
                    />
                </svg>
            </div>
            {/* Equity curve */}
            <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="block">
                {/* Initial balance line */}
                <line
                    x1={0}
                    y1={h - ((initialBalance - minE) / range) * (h - 20) - 10}
                    x2={w}
                    y2={h - ((initialBalance - minE) / range) * (h - 20) - 10}
                    stroke="var(--text-faint)"
                    strokeWidth={1}
                    strokeDasharray="4 4"
                    opacity={0.4}
                />
                <polygon
                    points={`0,${h} ${eqPoints} ${w},${h}`}
                    fill={lineColor}
                    opacity={0.08}
                />
                <polyline
                    points={eqPoints}
                    fill="none"
                    stroke={lineColor}
                    strokeWidth={2}
                    strokeLinejoin="round"
                />
            </svg>
            <div className="flex justify-between text-[9px] text-[var(--text-faint)] font-mono mt-1">
                <span>Trade 0</span>
                <span>Trade {data.length - 1}</span>
            </div>
        </div>
    );
}

// ── Trade List ───────────────────────────────────────────────────
function TradeList({ trades }) {
    const [expanded, setExpanded] = useState(false);
    if (!trades || trades.length === 0) return null;

    const shown = expanded ? trades : trades.slice(0, 5);

    return (
        <div className="mt-3">
            <div className="kicker mb-2">TRADES ({trades.length})</div>
            <div className="space-y-1">
                {shown.map((t, i) => (
                    <div
                        key={i}
                        className="flex items-center justify-between text-[11px] font-mono py-1 px-2 rounded"
                        style={{ background: t.pnl > 0 ? "rgba(34,197,94,0.06)" : t.pnl < 0 ? "rgba(239,68,68,0.06)" : "transparent" }}
                    >
                        <span className="text-[var(--text-faint)]">#{i + 1}</span>
                        <span style={{ color: t.side === "LONG" ? "var(--green)" : "var(--red)" }}>
                            {t.side}
                        </span>
                        <span className="text-[var(--text-dim)]">
                            {t.entry_price?.toFixed(5)} → {t.exit_price?.toFixed(5)}
                        </span>
                        <span className="text-[var(--text-faint)]">{t.exit_reason}</span>
                        <span
                            className="font-semibold"
                            style={{ color: t.pnl > 0 ? "var(--green)" : "var(--red)" }}
                        >
                            {fmtMoney(t.pnl)}
                        </span>
                    </div>
                ))}
            </div>
            {trades.length > 5 && (
                <button
                    onClick={() => setExpanded(!expanded)}
                    className="mt-2 text-[10px] text-[var(--text-faint)] hover:text-[var(--text-dim)] font-mono flex items-center gap-1"
                >
                    {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                    {expanded ? "Mostrar menos" : `Mostrar todos (${trades.length})`}
                </button>
            )}
        </div>
    );
}

// ── Main Component ───────────────────────────────────────────────
export default function Backtest({ api }) {
    const [strategies, setStrategies] = useState({});
    const [selectedStrategy, setSelectedStrategy] = useState("trend_rider");
    const [symbol, setSymbol] = useState("EURUSD");
    const [bars, setBars] = useState(1000);
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    // Fetch available strategies
    useEffect(() => {
        axios.get(`${api}/backtest/strategies`)
            .then((res) => setStrategies(res.data.strategies || {}))
            .catch(() => {});
    }, [api]);

    const runBacktest = useCallback(async () => {
        setRunning(true);
        setResult(null);
        setError(null);
        try {
            const res = await axios.post(
                `${api}/backtest/strategy`,
                {
                    strategy_id: selectedStrategy,
                    symbol,
                    bars: Math.min(bars, 5000),
                },
                { headers: authHeaders }
            );
            setResult(res.data);
        } catch (e) {
            setError(e.response?.data?.detail || e.response?.data?.error || e.message);
        } finally {
            setRunning(false);
        }
    }, [api, selectedStrategy, symbol, bars]);

    const SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "XAUUSD", "BTCUSD"];
    const m = result?.metrics || {};

    return (
        <section id="backtest" className="px-6 lg:px-10 py-12 border-b border-[var(--border)]" data-testid="section-backtest">
            <div className="kicker mb-1">// 06</div>
            <h2 className="section-title">Backtesting</h2>
            <p className="text-sm text-[var(--text-dim)] mb-6 max-w-2xl">
                Prueba cada estrategia con datos históricos/sintéticos. Compara rendimiento,
                drawdown y equity curve antes de activar en vivo.
            </p>

            {/* Controls */}
            <div className="panel p-4 mb-6">
                <div className="flex flex-wrap items-end gap-4">
                    <div>
                        <label className="text-[10px] text-[var(--text-faint)] uppercase font-mono block mb-1">
                            Estrategia
                        </label>
                        <select
                            value={selectedStrategy}
                            onChange={(e) => setSelectedStrategy(e.target.value)}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)] min-w-[160px]"
                        >
                            {Object.entries(strategies).map(([id, s]) => (
                                <option key={id} value={id}>{s.name}</option>
                            ))}
                        </select>
                    </div>
                    <div>
                        <label className="text-[10px] text-[var(--text-faint)] uppercase font-mono block mb-1">
                            Símbolo
                        </label>
                        <select
                            value={symbol}
                            onChange={(e) => setSymbol(e.target.value)}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)]"
                        >
                            {SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="text-[10px] text-[var(--text-faint)] uppercase font-mono block mb-1">
                            Barras
                        </label>
                        <input
                            type="number"
                            value={bars}
                            onChange={(e) => setBars(Math.max(100, Math.min(5000, parseInt(e.target.value) || 1000)))}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)] w-24"
                        />
                    </div>
                    <button
                        onClick={runBacktest}
                        disabled={running}
                        className="px-6 py-2 rounded font-mono text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
                        style={{
                            background: "rgba(59,130,246,0.15)",
                            color: "#60a5fa",
                            border: "1px solid rgba(59,130,246,0.3)",
                        }}
                    >
                        {running ? (
                            <span className="flex items-center gap-2">
                                <Loader2 size={14} className="animate-spin" /> Ejecutando...
                            </span>
                        ) : (
                            <span className="flex items-center gap-2">
                                <Play size={14} /> Ejecutar Backtest
                            </span>
                        )}
                    </button>
                </div>
            </div>

            {/* Error */}
            {error && (
                <div className="panel p-4 mb-4 border-[var(--red)]">
                    <span className="text-[var(--red)] text-sm font-mono">{error}</span>
                </div>
            )}

            {/* Results */}
            {result && result.ok && (
                <div className="space-y-4">
                    {/* Metrics Grid */}
                    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Trades</div>
                            <div className="font-display text-xl font-black">{m.trades || 0}</div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Win Rate</div>
                            <div className="font-display text-xl font-black" style={{ color: (m.win_rate || 0) >= 0.5 ? "var(--green)" : "var(--red)" }}>
                                {fmtPct(m.win_rate)}
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">P&L Total</div>
                            <div className="font-display text-xl font-black" style={{ color: (m.total_pnl || 0) > 0 ? "var(--green)" : "var(--red)" }}>
                                {fmtMoney(m.total_pnl)}
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Profit Factor</div>
                            <div className="font-display text-xl font-black" style={{ color: (m.profit_factor || 0) >= 1.0 ? "var(--green)" : "var(--red)" }}>
                                {fmtNum(m.profit_factor, 3)}
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Sharpe</div>
                            <div className="font-display text-xl font-black" style={{ color: (m.sharpe || 0) > 0 ? "var(--green)" : "var(--red)" }}>
                                {fmtNum(m.sharpe, 3)}
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Max DD</div>
                            <div className="font-display text-xl font-black text-[var(--red)]">
                                {fmtNum(m.max_drawdown_pct, 2)}%
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Expectancy</div>
                            <div className="font-display text-xl font-black" style={{ color: (m.expectancy || 0) > 0 ? "var(--green)" : "var(--red)" }}>
                                {fmtMoney(m.expectancy)}
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Balance Final</div>
                            <div className="font-display text-xl font-black">
                                ${fmtNum(m.ending_balance)}
                            </div>
                        </div>
                    </div>

                    {/* Equity Curve with Drawdown */}
                    <div className="panel p-4">
                        <div className="kicker mb-3">CURVA DE EQUITY + DRAWDOWN</div>
                        <div className="flex items-center gap-4 mb-2 text-[9px] font-mono text-[var(--text-faint)]">
                            <span>Estrategia: <strong className="text-[var(--text-dim)]">{result.strategy}</strong></span>
                            <span>Símbolo: <strong className="text-[var(--text-dim)]">{result.symbol}</strong></span>
                            <span>Datos: <strong className="text-[var(--text-dim)]">{result.data_source}</strong></span>
                            <span>Barras: <strong className="text-[var(--text-dim)]">{result.total_bars}</strong></span>
                        </div>
                        <EquityCurveWithDD
                            data={result.equity_curve}
                            initialBalance={result.config?.initial_balance || 800}
                        />
                    </div>

                    {/* Trade list */}
                    <div className="panel p-4">
                        <TradeList trades={result.trades} />
                    </div>
                </div>
            )}

            {/* No result yet */}
            {!result && !running && !error && (
                <div className="panel p-8 text-center">
                    <BarChart3 size={32} className="mx-auto mb-3 text-[var(--text-faint)]" />
                    <p className="text-sm text-[var(--text-dim)]">
                        Selecciona una estrategia y ejecuta un backtest para ver resultados.
                    </p>
                </div>
            )}
        </section>
    );
}
