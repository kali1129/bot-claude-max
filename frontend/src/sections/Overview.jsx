import { ArrowUpRight, AlertTriangle } from "lucide-react";

function MetricBig({ label, value, sublabel, color = "white", testId }) {
    const colorClass =
        color === "green"
            ? "text-[var(--green-bright)]"
            : color === "red"
              ? "text-[var(--red)]"
              : color === "amber"
                ? "text-[var(--amber)]"
                : "text-white";
    return (
        <div className="panel p-5" data-testid={testId}>
            <div className="kicker mb-3">{label}</div>
            <div className={`font-mono text-3xl font-bold tabular ${colorClass}`}>
                {value}
            </div>
            {sublabel && (
                <div className="kicker mt-2 normal-case tracking-normal text-[var(--text-dim)]">
                    {sublabel}
                </div>
            )}
        </div>
    );
}

export default function Overview({ config, stats }) {
    const liveBalance = config.capital;             // dynamic from MT5 (or fallback)
    // Plan target: the long-term capital goal (default 4× starting capital
    // or $800 if neither is known). Used only as the headline number; the
    // dashboard's Live tab uses real-time balance for everything else.
    const target = config.capital_target ?? Math.max(800, Math.round((liveBalance || 200) * 4));
    const isLive = config.capital_source === "mt5";
    const equity = stats?.current_equity ?? liveBalance;
    const totalPnl = stats?.total_pnl_usd ?? 0;
    const totalPnlPct = liveBalance > 0 ? (totalPnl / liveBalance) * 100 : 0;
    const winRate = stats?.win_rate ?? 0;
    const expectancy = stats?.expectancy ?? 0;
    const totalTrades = stats?.total_trades ?? 0;

    const fmtMoney = (v) => `$${(v ?? 0).toFixed(2)}`;
    const riskPerTradeUsd = (liveBalance * config.max_risk_per_trade_pct) / 100;
    const dailyStopUsd = (liveBalance * config.max_daily_loss_pct) / 100;

    return (
        <section
            id="overview"
            className="px-6 py-10 border-b border-[var(--border)]"
            data-testid="section-overview"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="flex items-end justify-between mb-8 gap-4 flex-wrap">
                    <div>
                        <div className="kicker mb-2">SECCIÓN 01 / PLAN</div>
                        <h1 className="font-display text-4xl md:text-5xl font-black tracking-tight">
                            Plan de Trading
                            <br />
                            <span className="text-[var(--text-dim)]">${liveBalance?.toFixed?.(0) ?? "—"} → ${target}</span>{" "}
                            <span className="text-[var(--green)]">.</span>
                        </h1>
                        <p className="mt-4 text-[var(--text-dim)] max-w-[640px] text-[15px] leading-relaxed">
                            Sistema de trading asistido sobre MetaTrader 5. Las
                            cifras de abajo se leen en vivo desde tu cuenta. La sección{" "}
                            <a href="#live" className="text-[var(--green-bright)] underline">
                                En Vivo
                            </a>{" "}arriba refresca cada 3 s.
                        </p>
                    </div>

                    <div className="hidden md:flex flex-col items-end">
                        <div className="kicker">// IR AL</div>
                        <a
                            href="#control"
                            className="font-display font-semibold text-[var(--green-bright)] flex items-center gap-1 mt-1"
                            data-testid="overview-control-link"
                        >
                            Panel de Control
                            <ArrowUpRight size={16} />
                        </a>
                    </div>
                </div>

                {!isLive && (
                    <div
                        className="panel mb-4 px-4 py-3 flex items-center gap-3 stripes-warn"
                        data-testid="banner-no-mt5"
                    >
                        <AlertTriangle size={16} className="text-[var(--amber)]" />
                        <span className="font-mono text-xs text-[var(--text-dim)]">
                            MetaTrader no está conectado. Mostrando capital de
                            referencia (${target}). Abre tu MT5 y los números pasan
                            a ser en vivo.
                        </span>
                    </div>
                )}

                {/* Metrics grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <MetricBig
                        label="Capital de la cuenta"
                        value={fmtMoney(liveBalance)}
                        sublabel={isLive ? "en vivo desde MT5" : `objetivo $${target}`}
                        color={isLive ? "white" : "amber"}
                        testId="metric-capital"
                    />
                    <MetricBig
                        label="Equity Actual"
                        value={fmtMoney(equity)}
                        sublabel={`${totalPnlPct >= 0 ? "+" : ""}${totalPnlPct.toFixed(2)}% acumulado`}
                        color={
                            totalTrades === 0
                                ? "white"
                                : equity >= liveBalance
                                  ? "green"
                                  : equity < liveBalance * 0.95
                                    ? "red"
                                    : "amber"
                        }
                        testId="metric-equity"
                    />
                    <MetricBig
                        label="Aciertos"
                        value={`${winRate.toFixed(1)}%`}
                        sublabel={`${totalTrades} operaciones cerradas`}
                        color={
                            totalTrades < 10
                                ? "amber"
                                : winRate >= 50
                                  ? "green"
                                  : "red"
                        }
                        testId="metric-winrate"
                    />
                    <MetricBig
                        label="Expectativa por trade"
                        value={`${expectancy >= 0 ? "+" : ""}${expectancy.toFixed(2)}R`}
                        sublabel="objetivo: > +0.30R"
                        color={expectancy >= 0.3 ? "green" : expectancy >= 0 ? "amber" : "red"}
                        testId="metric-expectancy"
                    />
                </div>

                {/* Risk model strip */}
                <div className="mt-3 panel p-5 grid grid-cols-2 md:grid-cols-4 gap-6">
                    <div>
                        <div className="kicker mb-1">RIESGO POR TRADE</div>
                        <div className="font-mono text-xl font-semibold tabular">
                            {config.max_risk_per_trade_pct}%
                            <span className="text-[var(--text-dim)] text-sm ml-2">
                                = ${riskPerTradeUsd.toFixed(2)}
                            </span>
                        </div>
                    </div>
                    <div>
                        <div className="kicker mb-1">PARADA DEL DÍA</div>
                        <div className="font-mono text-xl font-semibold tabular text-[var(--red)]">
                            -{config.max_daily_loss_pct}%
                            <span className="text-[var(--text-dim)] text-sm ml-2">
                                = -${dailyStopUsd.toFixed(2)}
                            </span>
                        </div>
                    </div>
                    <div>
                        <div className="kicker mb-1">PÉRDIDAS SEGUIDAS</div>
                        <div className="font-mono text-xl font-semibold tabular">
                            {config.max_consecutive_losses}
                            <span className="text-[var(--text-dim)] text-sm ml-2">
                                seguidas → STOP
                            </span>
                        </div>
                    </div>
                    <div>
                        <div className="kicker mb-1">RIESGO / RECOMPENSA</div>
                        <div className="font-mono text-xl font-semibold tabular text-[var(--green-bright)]">
                            1 : {config.min_rr}
                            <span className="text-[var(--text-dim)] text-sm ml-2">
                                mínimo o no entras
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}
