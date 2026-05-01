/**
 * Strategies — Multi-strategy engine dashboard section.
 *
 * Shows all available strategies as cards with:
 *   - Theoretical performance (from research/backtest)
 *   - Real performance (from our own trade log)
 *   - Side-by-side comparison
 *   - One-click activate button
 *
 * Data comes from GET /api/strategies, activate via POST /api/strategies/:id/activate.
 */
import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Zap, TrendingUp, BarChart3, Target, Shield, ChevronRight } from "lucide-react";

const TOKEN = process.env.REACT_APP_DASHBOARD_TOKEN || "";
const authHeaders = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};

const STRATEGY_ICONS = {
    trend: TrendingUp,
    breakout: Zap,
    mean_reversion: BarChart3,
};

const STRATEGY_COLORS = {
    blue: { bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.3)", text: "#60a5fa", accent: "#3b82f6" },
    green: { bg: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.3)", text: "#4ade80", accent: "#22c55e" },
    amber: { bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.3)", text: "#fbbf24", accent: "#f59e0b" },
    purple: { bg: "rgba(168,85,247,0.12)", border: "rgba(168,85,247,0.3)", text: "#c084fc", accent: "#a855f7" },
    gray: { bg: "rgba(156,163,175,0.10)", border: "rgba(156,163,175,0.25)", text: "#9ca3af", accent: "#6b7280" },
    red: { bg: "rgba(239,68,68,0.12)", border: "rgba(239,68,68,0.3)", text: "#f87171", accent: "#ef4444" },
};

const fmtPct = (v) => (typeof v === "number" ? `${v.toFixed(1)}%` : "—");
const fmtR = (v) => (typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(3)}R` : "—");
const fmtMoney = (v) =>
    typeof v === "number"
        ? `${v >= 0 ? "+" : ""}$${Math.abs(v).toFixed(2)}`
        : "—";

// --------------------------------------------------------------------------
// StatBar — side-by-side comparison bar
// --------------------------------------------------------------------------
function StatBar({ label, theoretical, real, unit, isGood }) {
    const tVal = typeof theoretical === "number" ? theoretical : null;
    const rVal = typeof real === "number" ? real : null;

    const goodColor = isGood ? "var(--green)" : "var(--red)";
    const neutralColor = "var(--text-faint)";

    return (
        <div className="flex items-center justify-between py-1.5 text-xs">
            <span className="text-[var(--text-dim)] w-24 shrink-0">{label}</span>
            <div className="flex items-center gap-3 flex-1 justify-end">
                <div className="text-right">
                    <span className="text-[var(--text-faint)] text-[10px] mr-1">TEO</span>
                    <span className="font-mono text-[var(--text-dim)]">
                        {tVal !== null ? (unit === "%" ? fmtPct(tVal) : unit === "R" ? fmtR(tVal) : tVal) : "—"}
                    </span>
                </div>
                <ChevronRight size={10} className="text-[var(--text-faint)]" />
                <div className="text-right min-w-[70px]">
                    <span className="text-[var(--text-faint)] text-[10px] mr-1">REAL</span>
                    <span
                        className="font-mono font-semibold"
                        style={{ color: rVal !== null && rVal > 0 ? goodColor : rVal !== null && rVal < 0 ? "var(--red)" : neutralColor }}
                    >
                        {rVal !== null ? (unit === "%" ? fmtPct(rVal) : unit === "R" ? fmtR(rVal) : unit === "$" ? fmtMoney(rVal) : rVal) : "—"}
                    </span>
                </div>
            </div>
        </div>
    );
}

// --------------------------------------------------------------------------
// StrategyCard
// --------------------------------------------------------------------------
function StrategyCard({ strategy, onActivate, activatingId, readOnly = false }) {
    const colors = STRATEGY_COLORS[strategy.color] || STRATEGY_COLORS.gray;
    const Icon = STRATEGY_ICONS[strategy.type] || Target;
    const isActive = strategy.active;
    const real = strategy.real || {};
    const theo = strategy.theoretical || {};

    return (
        <div
            className="panel relative overflow-hidden transition-all duration-200"
            style={{
                borderColor: isActive ? colors.accent : "var(--border)",
                borderWidth: isActive ? "2px" : "1px",
            }}
        >
            {/* Active badge */}
            {isActive && (
                <div
                    className="absolute top-0 right-0 px-3 py-1 text-[10px] font-bold tracking-wider"
                    style={{ background: colors.accent, color: "#000" }}
                >
                    ACTIVA
                </div>
            )}

            {/* Header */}
            <div className="p-4 pb-3">
                <div className="flex items-center gap-2 mb-2">
                    <div
                        className="w-8 h-8 rounded flex items-center justify-center"
                        style={{ background: colors.bg }}
                    >
                        <Icon size={16} style={{ color: colors.text }} />
                    </div>
                    <div>
                        <h3 className="font-display font-bold text-sm">{strategy.name}</h3>
                        <span
                            className="text-[10px] font-mono tracking-wider"
                            style={{ color: colors.text }}
                        >
                            {strategy.type?.toUpperCase() || "CUSTOM"}
                        </span>
                    </div>
                </div>
                <p className="text-[11px] text-[var(--text-dim)] leading-relaxed">
                    {strategy.description}
                </p>
            </div>

            {/* Stats comparison */}
            <div className="px-4 py-2 border-t border-[var(--border)]">
                <div className="kicker mb-1" style={{ color: colors.text }}>
                    RENDIMIENTO
                </div>
                <StatBar
                    label="Win Rate"
                    theoretical={theo.win_rate}
                    real={real.win_rate}
                    unit="%"
                    isGood={real.win_rate > 0}
                />
                <StatBar
                    label="Avg R"
                    theoretical={theo.expectancy}
                    real={real.avg_r}
                    unit="R"
                    isGood={(real.avg_r || 0) > 0}
                />
                <StatBar
                    label="P&L Total"
                    theoretical={null}
                    real={real.total_pnl}
                    unit="$"
                    isGood={(real.total_pnl || 0) > 0}
                />
                <div className="flex items-center justify-between py-1.5 text-xs">
                    <span className="text-[var(--text-dim)] w-24 shrink-0">Trades</span>
                    <div className="flex items-center gap-2 font-mono">
                        <span className="text-[var(--green)]">{real.wins || 0}W</span>
                        <span className="text-[var(--text-faint)]">/</span>
                        <span className="text-[var(--red)]">{real.losses || 0}L</span>
                        <span className="text-[var(--text-faint)]">= {real.trades || 0}</span>
                    </div>
                </div>
            </div>

            {/* Schedule & markets */}
            {(strategy.schedule || strategy.trading_hours?.length > 0 || strategy.preferred_symbols) && (
                <div className="px-4 py-2 border-t border-[var(--border)]">
                    <div className="kicker mb-1" style={{ color: colors.text }}>
                        HORARIO & MERCADOS
                    </div>
                    {strategy.schedule && (
                        <div className="flex items-center gap-2 text-[11px] mb-1">
                            <span className="text-[var(--text-faint)]">Horario:</span>
                            <span className="font-mono text-[var(--text-dim)]">{strategy.schedule}</span>
                        </div>
                    )}
                    {strategy.preferred_symbols && (
                        <div className="flex flex-wrap gap-1 mt-1">
                            {strategy.preferred_symbols.map((sym) => (
                                <span
                                    key={sym}
                                    className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                                    style={{ background: colors.bg, color: colors.text }}
                                >
                                    {sym}
                                </span>
                            ))}
                        </div>
                    )}
                    {!strategy.preferred_symbols && (
                        <div className="text-[11px] text-[var(--text-faint)] mt-1">
                            Todos los pares del watchlist
                        </div>
                    )}
                </div>
            )}

            {/* Theoretical params */}
            <div className="px-4 py-2 border-t border-[var(--border)]">
                <div className="kicker mb-1">PARÁMETROS</div>
                <div className="grid grid-cols-3 gap-2 text-[11px]">
                    {strategy.params &&
                        Object.entries(strategy.params).map(([k, v]) => (
                            <div key={k} className="text-center">
                                <div className="text-[var(--text-faint)] text-[9px] uppercase">
                                    {k.replace(/_/g, " ")}
                                </div>
                                <div className="font-mono font-semibold text-[var(--text-dim)]">
                                    {typeof v === "number" ? (v % 1 === 0 ? v : v.toFixed(2)) : v}
                                </div>
                            </div>
                        ))}
                </div>
            </div>

            {/* Activate button */}
            <div className="p-3 border-t border-[var(--border)]">
                {isActive ? (
                    <div
                        className="w-full text-center py-2 text-xs font-mono font-semibold rounded"
                        style={{ background: colors.bg, color: colors.text }}
                    >
                        <Shield size={12} className="inline mr-1" />
                        ESTRATEGIA ACTIVA
                    </div>
                ) : readOnly ? (
                    <div
                        className="w-full text-center py-2 text-[10px] font-mono text-[var(--text-faint)] border border-[var(--border)] rounded"
                        title="Solo el admin puede activar estrategias"
                    >
                        — solo lectura —
                    </div>
                ) : (
                    <button
                        onClick={() => onActivate(strategy.id)}
                        disabled={!!activatingId}
                        className="w-full py-2 text-xs font-mono font-semibold rounded transition-all hover:brightness-110 disabled:opacity-50"
                        style={{
                            background: colors.bg,
                            color: colors.text,
                            border: `1px solid ${colors.border}`,
                        }}
                    >
                        {activatingId === strategy.id ? "ACTIVANDO..." : "ACTIVAR ESTRATEGIA"}
                    </button>
                )}
            </div>
        </div>
    );
}

// --------------------------------------------------------------------------
// PerformanceSummary — overall real stats
// --------------------------------------------------------------------------
function PerformanceSummary({ strategies }) {
    const allReal = strategies.filter((s) => s.real && s.real.trades > 0);
    const totalTrades = allReal.reduce((sum, s) => sum + (s.real.trades || 0), 0);
    const totalWins = allReal.reduce((sum, s) => sum + (s.real.wins || 0), 0);
    const totalPnl = allReal.reduce((sum, s) => sum + (s.real.total_pnl || 0), 0);
    const overallWR = totalTrades > 0 ? (totalWins / totalTrades) * 100 : 0;

    return (
        <div className="panel p-4 mb-6">
            <div className="kicker mb-3">RESUMEN GLOBAL DE ESTRATEGIAS</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                    <div className="text-[var(--text-faint)] text-[10px] uppercase">Estrategias</div>
                    <div className="font-display text-2xl font-black">{strategies.length}</div>
                </div>
                <div>
                    <div className="text-[var(--text-faint)] text-[10px] uppercase">Trades Totales</div>
                    <div className="font-display text-2xl font-black">{totalTrades}</div>
                </div>
                <div>
                    <div className="text-[var(--text-faint)] text-[10px] uppercase">Win Rate Global</div>
                    <div className="font-display text-2xl font-black" style={{ color: overallWR >= 50 ? "var(--green)" : overallWR > 0 ? "var(--amber, #f59e0b)" : "var(--text-dim)" }}>
                        {fmtPct(overallWR)}
                    </div>
                </div>
                <div>
                    <div className="text-[var(--text-faint)] text-[10px] uppercase">P&L Total</div>
                    <div
                        className="font-display text-2xl font-black"
                        style={{ color: totalPnl > 0 ? "var(--green)" : totalPnl < 0 ? "var(--red)" : "var(--text-dim)" }}
                    >
                        {fmtMoney(totalPnl)}
                    </div>
                </div>
            </div>
        </div>
    );
}

// --------------------------------------------------------------------------
// Strategies — main exported component
// --------------------------------------------------------------------------
export default function Strategies({ api, novato = false, readOnly = false }) {
    // novato: actualmente Strategies muestra todo. La página wrapper agrega
    // banner explicativo en novato. Aquí podríamos ocultar params crudos en
    // un futuro pase — por ahora basta con el wrapper externo.
    const [strategies, setStrategies] = useState([]);
    const [activeId, setActiveId] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activatingId, setActivatingId] = useState(null);
    const [error, setError] = useState(null);

    const fetchStrategies = useCallback(async () => {
        try {
            const res = await axios.get(`${api}/strategies`);
            setStrategies(res.data.strategies || []);
            setActiveId(res.data.active || null);
            setError(null);
        } catch (e) {
            console.error("strategies fetch error", e);
            setError(e.response?.data?.detail || e.message);
        } finally {
            setLoading(false);
        }
    }, [api]);

    useEffect(() => {
        fetchStrategies();
        const id = setInterval(fetchStrategies, 10000);
        return () => clearInterval(id);
    }, [fetchStrategies]);

    const handleActivate = async (strategyId) => {
        setActivatingId(strategyId);
        try {
            await axios.post(`${api}/strategies/${strategyId}/activate`, {}, { headers: authHeaders });
            toast.success(`Estrategia "${strategyId}" activada`);
            await fetchStrategies();
        } catch (e) {
            toast.error(e.response?.data?.detail || e.message || "Error activando estrategia");
        } finally {
            setActivatingId(null);
        }
    };

    return (
        <section id="strategies" className="px-6 lg:px-10 py-12 border-b border-[var(--border)]" data-testid="section-strategies">
            <div className="kicker mb-1">// 04</div>
            <h2 className="section-title">Estrategias</h2>
            <p className="text-sm text-[var(--text-dim)] mb-6 max-w-2xl">
                Motor multi-estrategia con comparación teórica vs real.
                Cambia la estrategia activa con un click — el bot usará la nueva estrategia en el próximo ciclo de escaneo.
            </p>

            {/* Toast renderizado por sonner globalmente — ya no hay toast local */}

            {loading ? (
                <div className="text-center py-12 text-[var(--text-faint)] font-mono text-sm">
                    Cargando estrategias...
                </div>
            ) : error ? (
                <div className="panel p-6 text-center">
                    <div className="text-[var(--red)] font-mono text-sm mb-2">Error cargando estrategias</div>
                    <div className="text-[var(--text-faint)] text-xs">{error}</div>
                </div>
            ) : (
                <>
                    <PerformanceSummary strategies={strategies} />
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                        {strategies.map((s) => (
                            <StrategyCard
                                key={s.id}
                                strategy={s}
                                onActivate={handleActivate}
                                activatingId={activatingId}
                                readOnly={readOnly}
                            />
                        ))}
                    </div>
                </>
            )}
        </section>
    );
}
