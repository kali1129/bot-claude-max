/**
 * Optimizer — Phase 3 advanced analysis dashboard.
 *
 * Provides:
 *   - Hyperparameter optimization (Optuna)
 *   - Walk-Forward Analysis (out-of-sample validation)
 *   - Monte Carlo Simulation (risk/outcome distribution)
 *
 * API: POST /api/optimize/run, /api/optimize/walkforward, /api/optimize/montecarlo
 */
import { useState, useCallback } from "react";
import axios from "axios";
import {
    Zap, TrendingUp, Shuffle, BarChart3, Target,
    AlertTriangle, Loader2, Play, ChevronDown, ChevronUp
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

// ── Tabs ─────────────────────────────────────────────────────────
const TABS = [
    { id: "optimize", label: "Optimizar", icon: Zap },
    { id: "walkforward", label: "Walk-Forward", icon: TrendingUp },
    { id: "montecarlo", label: "Monte Carlo", icon: Shuffle },
];

// ── Histogram Chart ──────────────────────────────────────────────
function Histogram({ data, label, profitableThreshold = 0 }) {
    if (!data || data.length === 0) return null;
    const maxCount = Math.max(...data.map((d) => d.count), 1);

    return (
        <div>
            <div className="kicker mb-2">{label}</div>
            <div className="flex items-end gap-0.5" style={{ height: 100 }}>
                {data.map((bin, i) => {
                    const h = (bin.count / maxCount) * 100;
                    // Antes hardcodeaba 800 (capital inicial original). Ahora
                    // depende del threshold pasado por prop — el caller le pasa
                    // el initial_balance del backtest.
                    const isProfitable = bin.bin_start >= profitableThreshold;
                    return (
                        <div
                            key={i}
                            className="flex-1 rounded-t transition-all hover:opacity-80 cursor-default"
                            style={{
                                height: `${h}%`,
                                background: isProfitable
                                    ? "rgba(34, 197, 94, 0.5)"
                                    : "rgba(239, 68, 68, 0.4)",
                                minWidth: 8,
                            }}
                            title={`$${bin.bin_start.toFixed(0)}-${bin.bin_end.toFixed(0)}: ${bin.count} sims (${bin.pct}%)`}
                        />
                    );
                })}
            </div>
            <div className="flex justify-between text-[8px] text-[var(--text-faint)] font-mono mt-1">
                <span>${data[0]?.bin_start?.toFixed(0)}</span>
                <span>${data[data.length - 1]?.bin_end?.toFixed(0)}</span>
            </div>
        </div>
    );
}

// ── Walk-Forward Folds Viz ───────────────────────────────────────
function WalkForwardFolds({ folds }) {
    if (!folds || folds.length === 0) return null;

    return (
        <div className="space-y-2">
            {folds.map((fold) => {
                if (fold.skipped) {
                    return (
                        <div key={fold.fold} className="flex items-center gap-2 text-xs text-[var(--text-faint)]">
                            <span className="font-mono">Fold {fold.fold}</span>
                            <span>— skipped ({fold.reason})</span>
                        </div>
                    );
                }
                const m = fold.test_metrics || {};
                const pnlColor = (m.total_pnl || 0) > 0 ? "var(--green)" : "var(--red)";
                return (
                    <div
                        key={fold.fold}
                        className="flex items-center justify-between py-2 px-3 rounded"
                        style={{ background: "rgba(255,255,255,0.02)" }}
                    >
                        <div className="flex items-center gap-3">
                            <span className="font-mono text-xs font-semibold text-[var(--text-dim)]">
                                Fold {fold.fold}
                            </span>
                            <span className="text-[9px] text-[var(--text-faint)]">
                                {fold.train_bars}tr / {fold.test_bars}test
                            </span>
                        </div>
                        <div className="flex items-center gap-4 text-xs font-mono">
                            <span className="text-[var(--text-faint)]">{m.trades || 0} trades</span>
                            <span style={{ color: (m.win_rate || 0) >= 0.5 ? "var(--green)" : "var(--red)" }}>
                                WR {((m.win_rate || 0) * 100).toFixed(0)}%
                            </span>
                            <span className="font-semibold" style={{ color: pnlColor }}>
                                {fmtMoney(m.total_pnl)}
                            </span>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

// ── Optimize Tab ─────────────────────────────────────────────────
function OptimizeTab({ api }) {
    const [strategy, setStrategy] = useState("score_v3");
    const [metric, setMetric] = useState("expectancy");
    const [trials, setTrials] = useState(50);
    const [bars, setBars] = useState(2000);
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const run = useCallback(async () => {
        setRunning(true);
        setResult(null);
        setError(null);
        try {
            const res = await axios.post(
                `${api}/optimize/run`,
                { strategy_id: strategy, metric, n_trials: trials, bars },
                { headers: authHeaders, timeout: 120000 }
            );
            setResult(res.data);
        } catch (e) {
            setError(e.response?.data?.error || e.message);
        } finally {
            setRunning(false);
        }
    }, [api, strategy, metric, trials, bars]);

    const bt = result?.backtest_result?.metrics || {};

    return (
        <div>
            <div className="panel p-4 mb-4">
                <div className="flex flex-wrap items-end gap-3">
                    <div>
                        <label className="text-[9px] text-[var(--text-faint)] uppercase font-mono block mb-1">Estrategia</label>
                        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)]">
                            <option value="trend_rider">Trend Rider</option>
                            <option value="mean_reverter">Mean Reverter</option>
                            <option value="breakout_hunter">Breakout Hunter</option>
                            <option value="score_v3">Score v3</option>
                        </select>
                    </div>
                    <div>
                        <label className="text-[9px] text-[var(--text-faint)] uppercase font-mono block mb-1">Metric</label>
                        <select value={metric} onChange={(e) => setMetric(e.target.value)}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)]">
                            <option value="expectancy">Expectancy</option>
                            <option value="sharpe">Sharpe</option>
                            <option value="profit_factor">Profit Factor</option>
                            <option value="total_pnl">Total P&L</option>
                        </select>
                    </div>
                    <div>
                        <label className="text-[9px] text-[var(--text-faint)] uppercase font-mono block mb-1">Trials</label>
                        <input type="number" value={trials} onChange={(e) => setTrials(Math.min(200, Math.max(10, +e.target.value)))}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)] w-20" />
                    </div>
                    <div>
                        <label className="text-[9px] text-[var(--text-faint)] uppercase font-mono block mb-1">Barras</label>
                        <input type="number" value={bars} onChange={(e) => setBars(Math.min(5000, Math.max(500, +e.target.value)))}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)] w-24" />
                    </div>
                    <button onClick={run} disabled={running}
                        className="px-5 py-2 rounded font-mono text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
                        style={{ background: "rgba(168,85,247,0.15)", color: "#c084fc", border: "1px solid rgba(168,85,247,0.3)" }}>
                        {running ? <span className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" />Optimizando...</span>
                            : <span className="flex items-center gap-2"><Zap size={14} />Optimizar</span>}
                    </button>
                </div>
            </div>

            {error && <div className="panel p-3 mb-4 text-[var(--red)] text-sm font-mono">{error}</div>}

            {result && (
                <div className="space-y-4">
                    <div className="panel p-4">
                        <div className="kicker mb-3" style={{ color: "#c084fc" }}>MEJORES PARÁMETROS (Optuna)</div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {Object.entries(result.best_params || {}).map(([k, v]) => (
                                <div key={k} className="text-center">
                                    <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">{k.replace(/_/g, " ")}</div>
                                    <div className="font-display text-xl font-black text-[#c084fc]">{typeof v === "number" ? v.toFixed(2) : v}</div>
                                </div>
                            ))}
                            <div className="text-center">
                                <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Best {result.metric}</div>
                                <div className="font-display text-xl font-black text-[var(--green)]">{fmtNum(result.best_value, 4)}</div>
                            </div>
                        </div>
                    </div>
                    {result.backtest_result?.ok && (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <div className="panel p-3 text-center">
                                <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Trades</div>
                                <div className="font-display text-lg font-black">{bt.trades}</div>
                            </div>
                            <div className="panel p-3 text-center">
                                <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Win Rate</div>
                                <div className="font-display text-lg font-black" style={{ color: bt.win_rate >= 0.5 ? "var(--green)" : "var(--red)" }}>{fmtPct(bt.win_rate)}</div>
                            </div>
                            <div className="panel p-3 text-center">
                                <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">P&L</div>
                                <div className="font-display text-lg font-black" style={{ color: bt.total_pnl > 0 ? "var(--green)" : "var(--red)" }}>{fmtMoney(bt.total_pnl)}</div>
                            </div>
                            <div className="panel p-3 text-center">
                                <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Sharpe</div>
                                <div className="font-display text-lg font-black">{fmtNum(bt.sharpe, 3)}</div>
                            </div>
                        </div>
                    )}
                    {result.param_importance && Object.keys(result.param_importance).length > 0 && (
                        <div className="panel p-4">
                            <div className="kicker mb-2">IMPORTANCIA DE PARÁMETROS</div>
                            {Object.entries(result.param_importance).map(([k, v]) => (
                                <div key={k} className="flex items-center gap-2 mb-1">
                                    <span className="text-xs font-mono text-[var(--text-dim)] w-28">{k.replace(/_/g, " ")}</span>
                                    <div className="flex-1 h-3 bg-[var(--bg-card)] rounded overflow-hidden">
                                        <div className="h-full rounded" style={{ width: `${v * 100}%`, background: "#c084fc" }} />
                                    </div>
                                    <span className="text-xs font-mono text-[var(--text-faint)] w-12 text-right">{(v * 100).toFixed(1)}%</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ── Walk-Forward Tab ─────────────────────────────────────────────
function WalkForwardTab({ api }) {
    const [strategy, setStrategy] = useState("score_v3");
    const [splits, setSplits] = useState(5);
    const [bars, setBars] = useState(3000);
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const run = useCallback(async () => {
        setRunning(true);
        setResult(null);
        setError(null);
        try {
            const res = await axios.post(
                `${api}/optimize/walkforward`,
                { strategy_id: strategy, n_splits: splits, bars },
                { headers: authHeaders, timeout: 300000 }
            );
            setResult(res.data);
        } catch (e) {
            setError(e.response?.data?.error || e.message);
        } finally {
            setRunning(false);
        }
    }, [api, strategy, splits, bars]);

    const agg = result?.aggregate || {};

    return (
        <div>
            <div className="panel p-4 mb-4">
                <div className="flex flex-wrap items-end gap-3">
                    <div>
                        <label className="text-[9px] text-[var(--text-faint)] uppercase font-mono block mb-1">Estrategia</label>
                        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)]">
                            <option value="trend_rider">Trend Rider</option>
                            <option value="mean_reverter">Mean Reverter</option>
                            <option value="breakout_hunter">Breakout Hunter</option>
                            <option value="score_v3">Score v3</option>
                        </select>
                    </div>
                    <div>
                        <label className="text-[9px] text-[var(--text-faint)] uppercase font-mono block mb-1">Splits</label>
                        <input type="number" value={splits} onChange={(e) => setSplits(Math.min(10, Math.max(2, +e.target.value)))}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)] w-16" />
                    </div>
                    <div>
                        <label className="text-[9px] text-[var(--text-faint)] uppercase font-mono block mb-1">Barras</label>
                        <input type="number" value={bars} onChange={(e) => setBars(Math.min(5000, Math.max(1000, +e.target.value)))}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)] w-24" />
                    </div>
                    <button onClick={run} disabled={running}
                        className="px-5 py-2 rounded font-mono text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
                        style={{ background: "rgba(34,197,94,0.15)", color: "#4ade80", border: "1px solid rgba(34,197,94,0.3)" }}>
                        {running ? <span className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" />Analizando...</span>
                            : <span className="flex items-center gap-2"><TrendingUp size={14} />Analizar</span>}
                    </button>
                </div>
            </div>

            {error && <div className="panel p-3 mb-4 text-[var(--red)] text-sm font-mono">{error}</div>}

            {result && (
                <div className="space-y-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">OOS Trades</div>
                            <div className="font-display text-xl font-black">{agg.total_oos_trades}</div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">OOS P&L</div>
                            <div className="font-display text-xl font-black" style={{ color: (agg.total_oos_pnl || 0) > 0 ? "var(--green)" : "var(--red)" }}>
                                {fmtMoney(agg.total_oos_pnl)}
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Avg OOS WR</div>
                            <div className="font-display text-xl font-black" style={{ color: (agg.avg_oos_win_rate || 0) >= 0.5 ? "var(--green)" : "var(--red)" }}>
                                {fmtPct(agg.avg_oos_win_rate)}
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Folds</div>
                            <div className="font-display text-xl font-black">{agg.folds_with_data}/{result.n_splits}</div>
                        </div>
                    </div>
                    <div className="panel p-4">
                        <div className="kicker mb-3">FOLDS OUT-OF-SAMPLE</div>
                        <WalkForwardFolds folds={result.folds} />
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Monte Carlo Tab ──────────────────────────────────────────────
function MonteCarloTab({ api }) {
    const [sims, setSims] = useState(1000);
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const run = useCallback(async () => {
        setRunning(true);
        setResult(null);
        setError(null);
        try {
            const res = await axios.post(
                `${api}/optimize/montecarlo`,
                { n_simulations: sims },
                { headers: authHeaders }
            );
            setResult(res.data);
        } catch (e) {
            setError(e.response?.data?.error || e.message);
        } finally {
            setRunning(false);
        }
    }, [api, sims]);

    const fb = result?.final_balance || {};
    const dd = result?.max_drawdown_pct || {};

    return (
        <div>
            <div className="panel p-4 mb-4">
                <div className="flex flex-wrap items-end gap-3">
                    <div>
                        <label className="text-[9px] text-[var(--text-faint)] uppercase font-mono block mb-1">Simulaciones</label>
                        <input type="number" value={sims} onChange={(e) => setSims(Math.min(5000, Math.max(100, +e.target.value)))}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-3 py-2 text-sm font-mono text-[var(--text)] w-24" />
                    </div>
                    <button onClick={run} disabled={running}
                        className="px-5 py-2 rounded font-mono text-sm font-semibold transition-all hover:brightness-110 disabled:opacity-50"
                        style={{ background: "rgba(245,158,11,0.15)", color: "#fbbf24", border: "1px solid rgba(245,158,11,0.3)" }}>
                        {running ? <span className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" />Simulando...</span>
                            : <span className="flex items-center gap-2"><Shuffle size={14} />Simular</span>}
                    </button>
                </div>
                <p className="text-[10px] text-[var(--text-faint)] mt-2">
                    Usa los {result?.input_trades || "?"} trades reales del research log como pool de bootstrap.
                </p>
            </div>

            {error && <div className="panel p-3 mb-4 text-[var(--red)] text-sm font-mono">{error}</div>}

            {result && !result.error && (
                <div className="space-y-4">
                    {/* Risk metrics */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Riesgo de Ruina</div>
                            <div className="font-display text-xl font-black" style={{ color: result.risk_of_ruin_pct > 5 ? "var(--red)" : "var(--green)" }}>
                                {result.risk_of_ruin_pct}%
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Riesgo -50%</div>
                            <div className="font-display text-xl font-black" style={{ color: result.risk_of_50pct_loss > 10 ? "var(--red)" : "var(--amber, #f59e0b)" }}>
                                {result.risk_of_50pct_loss}%
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">Balance Mediano</div>
                            <div className="font-display text-xl font-black" style={{ color: fb.p50 >= (result.initial_balance ?? 0) ? "var(--green)" : "var(--red)" }}>
                                ${fb.p50?.toFixed(0)}
                            </div>
                        </div>
                        <div className="panel p-3 text-center">
                            <div className="text-[9px] text-[var(--text-faint)] uppercase font-mono">DD Mediano</div>
                            <div className="font-display text-xl font-black text-[var(--red)]">
                                {dd.p50?.toFixed(1)}%
                            </div>
                        </div>
                    </div>

                    {/* Percentile table */}
                    <div className="panel p-4">
                        <div className="kicker mb-3">DISTRIBUCIÓN DE BALANCE FINAL</div>
                        <div className="grid grid-cols-7 gap-2 text-center mb-4">
                            {[5, 10, 25, 50, 75, 90, 95].map((p) => (
                                <div key={p}>
                                    <div className="text-[9px] text-[var(--text-faint)] font-mono">P{p}</div>
                                    <div className="font-mono text-sm font-semibold" style={{ color: (fb[`p${p}`] || 0) >= (result.initial_balance ?? 0) ? "var(--green)" : "var(--red)" }}>
                                        ${(fb[`p${p}`] || 0).toFixed(0)}
                                    </div>
                                </div>
                            ))}
                        </div>
                        <Histogram data={result.histogram} label="HISTOGRAMA DE RESULTADOS" />
                    </div>

                    {/* Summary stats */}
                    <div className="panel p-4">
                        <div className="kicker mb-2">ESTADÍSTICAS</div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
                            <div>
                                <span className="text-[var(--text-faint)]">Media: </span>
                                <span className="font-semibold">${fb.mean?.toFixed(2)}</span>
                            </div>
                            <div>
                                <span className="text-[var(--text-faint)]">Std Dev: </span>
                                <span className="font-semibold">${fb.std?.toFixed(2)}</span>
                            </div>
                            <div>
                                <span className="text-[var(--text-faint)]">Min: </span>
                                <span className="font-semibold text-[var(--red)]">${fb.min?.toFixed(2)}</span>
                            </div>
                            <div>
                                <span className="text-[var(--text-faint)]">Max: </span>
                                <span className="font-semibold text-[var(--green)]">${fb.max?.toFixed(2)}</span>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {result?.error && (
                <div className="panel p-4 text-[var(--red)] text-sm font-mono">{result.error}</div>
            )}
        </div>
    );
}

// ── Main Component ───────────────────────────────────────────────
export default function Optimizer({ api }) {
    const [activeTab, setActiveTab] = useState("optimize");

    return (
        <section id="optimizer" className="px-6 lg:px-10 py-12 border-b border-[var(--border)]" data-testid="section-optimizer">
            <div className="kicker mb-1">// 07</div>
            <h2 className="section-title">Análisis Avanzado</h2>
            <p className="text-sm text-[var(--text-dim)] mb-6 max-w-2xl">
                Optimización de hiperparámetros con Optuna, validación Walk-Forward
                out-of-sample, y simulación Monte Carlo de distribuciones de resultados.
            </p>

            {/* Tab bar */}
            <div className="flex gap-1 mb-6 p-1 rounded bg-[rgba(255,255,255,0.02)]" style={{ width: "fit-content" }}>
                {TABS.map((tab) => {
                    const Icon = tab.icon;
                    const active = activeTab === tab.id;
                    return (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`flex items-center gap-2 px-4 py-2 rounded text-xs font-mono font-semibold transition-all ${
                                active
                                    ? "bg-[rgba(255,255,255,0.08)] text-[var(--text)]"
                                    : "text-[var(--text-faint)] hover:text-[var(--text-dim)]"
                            }`}
                        >
                            <Icon size={14} />
                            {tab.label}
                        </button>
                    );
                })}
            </div>

            {activeTab === "optimize" && <OptimizeTab api={api} />}
            {activeTab === "walkforward" && <WalkForwardTab api={api} />}
            {activeTab === "montecarlo" && <MonteCarloTab api={api} />}
        </section>
    );
}
