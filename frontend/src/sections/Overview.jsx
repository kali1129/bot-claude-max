import { ArrowUpRight } from "lucide-react";

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
    const equity = stats?.current_equity ?? config.capital;
    const totalPnl = stats?.total_pnl_usd ?? 0;
    const totalPnlPct = (totalPnl / config.capital) * 100;
    const winRate = stats?.win_rate ?? 0;
    const expectancy = stats?.expectancy ?? 0;
    const totalTrades = stats?.total_trades ?? 0;

    return (
        <section
            id="overview"
            className="px-6 py-10 border-b border-[var(--border)]"
            data-testid="section-overview"
        >
            <div className="max-w-[1400px] mx-auto">
                <div className="flex items-end justify-between mb-8 gap-4 flex-wrap">
                    <div>
                        <div className="kicker mb-2">SECTION 00 / OVERVIEW</div>
                        <h1 className="font-display text-4xl md:text-5xl font-black tracking-tight">
                            Trading Plan
                            <br />
                            <span className="text-[var(--text-dim)]">$800 ·</span>{" "}
                            Futures
                            <span className="text-[var(--green)]">.</span>
                        </h1>
                        <p className="mt-4 text-[var(--text-dim)] max-w-[640px] text-[15px] leading-relaxed">
                            Sistema operativo para trading de futuros con capital
                            real ($800), construido sobre Claude Pro Max + 4 MCPs
                            personalizados + MetaTrader 5. Reglas no negociables,
                            ejecución asistida, drawdown protegido por código.
                        </p>
                    </div>

                    <div className="hidden md:flex flex-col items-end">
                        <div className="kicker">// PRIMER PASO</div>
                        <a
                            href="#setup"
                            className="font-display font-semibold text-[var(--green-bright)] flex items-center gap-1 mt-1"
                            data-testid="overview-setup-link"
                        >
                            Configura WSL + MT5 + Claude
                            <ArrowUpRight size={16} />
                        </a>
                    </div>
                </div>

                {/* Metrics grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <MetricBig
                        label="Capital Inicial"
                        value={`$${config.capital.toFixed(2)}`}
                        sublabel="cuenta MT5 real"
                        testId="metric-capital"
                    />
                    <MetricBig
                        label="Equity Actual"
                        value={`$${equity.toFixed(2)}`}
                        sublabel={`${totalPnlPct >= 0 ? "+" : ""}${totalPnlPct.toFixed(2)}% all-time`}
                        color={
                            equity >= config.capital
                                ? "green"
                                : equity < config.capital * 0.95
                                  ? "red"
                                  : "amber"
                        }
                        testId="metric-equity"
                    />
                    <MetricBig
                        label="Win Rate"
                        value={`${winRate.toFixed(1)}%`}
                        sublabel={`${totalTrades} trades cerrados`}
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
                        label="Expectancy"
                        value={`${expectancy >= 0 ? "+" : ""}${expectancy.toFixed(2)}R`}
                        sublabel="objetivo: > +0.30R"
                        color={expectancy >= 0.3 ? "green" : expectancy >= 0 ? "amber" : "red"}
                        testId="metric-expectancy"
                    />
                </div>

                {/* Risk model strip */}
                <div className="mt-3 panel p-5 grid grid-cols-2 md:grid-cols-4 gap-6">
                    <div>
                        <div className="kicker mb-1">RIESGO / TRADE</div>
                        <div className="font-mono text-xl font-semibold tabular">
                            {config.max_risk_per_trade_pct}%
                            <span className="text-[var(--text-dim)] text-sm ml-2">
                                = ${(config.capital * config.max_risk_per_trade_pct / 100).toFixed(0)}
                            </span>
                        </div>
                    </div>
                    <div>
                        <div className="kicker mb-1">DAILY DRAWDOWN STOP</div>
                        <div className="font-mono text-xl font-semibold tabular text-[var(--red)]">
                            -{config.max_daily_loss_pct}%
                            <span className="text-[var(--text-dim)] text-sm ml-2">
                                = -${(config.capital * config.max_daily_loss_pct / 100).toFixed(0)}
                            </span>
                        </div>
                    </div>
                    <div>
                        <div className="kicker mb-1">MAX LOSS STREAK</div>
                        <div className="font-mono text-xl font-semibold tabular">
                            {config.max_consecutive_losses}
                            <span className="text-[var(--text-dim)] text-sm ml-2">
                                en línea → STOP
                            </span>
                        </div>
                    </div>
                    <div>
                        <div className="kicker mb-1">R:R MÍNIMO</div>
                        <div className="font-mono text-xl font-semibold tabular text-[var(--green-bright)]">
                            1 : {config.min_rr}
                            <span className="text-[var(--text-dim)] text-sm ml-2">
                                o no entras
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}
