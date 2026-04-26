import { useEffect, useState } from "react";
import { ArrowDownToLine, RefreshCcw } from "lucide-react";
import { toast } from "sonner";

const TICKER_ITEMS = [
    "RULE_01 · MAX 1% RISK / TRADE",
    "RULE_02 · 3% DAILY DRAWDOWN STOP",
    "RULE_03 · ONLY 1 POSITION OPEN",
    "RULE_04 · R:R MIN 1:2",
    "RULE_05 · NO TRADE 30M PRE/POST HIGH NEWS",
    "RULE_06 · 3 LOSSES IN A ROW = STOP DAY",
    "RULE_07 · DEMO 2 WEEKS BEFORE LIVE",
    "RULE_08 · NEVER MOVE SL AGAINST",
];

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

    useEffect(() => {
        const t = setInterval(() => setTime(new Date()), 1000);
        return () => clearInterval(t);
    }, []);

    const utcTime = time.toUTCString().slice(17, 25);
    const dateStr = time.toISOString().slice(0, 10);

    const equity = stats?.current_equity ?? config.capital;
    const todayPnL = stats?.today?.pnl_usd ?? 0;
    const todayPct = stats?.today?.pnl_pct ?? 0;
    const open = stats?.today?.open_positions ?? 0;
    const canTrade = stats?.today?.can_trade ?? true;

    const downloadPlan = async () => {
        try {
            const res = await fetch(
                `${process.env.REACT_APP_BACKEND_URL}/api/plan/markdown`
            );
            const txt = await res.text();
            const blob = new Blob([txt], { type: "text/markdown" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `trading-plan-${dateStr}.md`;
            a.click();
            URL.revokeObjectURL(url);
            toast.success("Plan descargado");
        } catch (e) {
            toast.error("Error descargando plan");
        }
    };

    return (
        <header
            className="sticky top-0 z-20 panel border-l-0 border-r-0 border-t-0"
            data-testid="topbar"
        >
            {/* Stat strip */}
            <div className="flex items-stretch overflow-x-auto">
                <StatCell
                    label="UTC"
                    value={utcTime}
                    testId="utc-time"
                />
                <StatCell
                    label="Equity"
                    value={`$${equity.toFixed(2)}`}
                    accent={equity >= config.capital ? "green" : "red"}
                    testId="equity-value"
                />
                <StatCell
                    label="Today P&L"
                    value={`${todayPnL >= 0 ? "+" : ""}$${todayPnL.toFixed(2)} · ${todayPct >= 0 ? "+" : ""}${todayPct.toFixed(2)}%`}
                    accent={todayPnL > 0 ? "green" : todayPnL < 0 ? "red" : "white"}
                    testId="today-pnl"
                />
                <StatCell
                    label="Open Pos"
                    value={`${open} / 1`}
                    accent={open > 1 ? "red" : open === 1 ? "amber" : "green"}
                    testId="open-positions"
                />
                <StatCell
                    label="Status"
                    value={canTrade ? "TRADEABLE" : "HALT"}
                    accent={canTrade ? "green" : "red"}
                    testId="trade-status"
                />
                <div className="flex-1" />
                <div className="flex items-center gap-2 px-4 border-l border-[var(--border)]">
                    <button
                        type="button"
                        onClick={onRefreshStats}
                        className="btn-sharp"
                        data-testid="refresh-stats-btn"
                        title="Refresh stats"
                    >
                        <RefreshCcw size={12} />
                    </button>
                    <button
                        type="button"
                        onClick={downloadPlan}
                        className="btn-sharp primary"
                        data-testid="download-plan-btn"
                    >
                        <ArrowDownToLine size={12} className="inline mr-1" />
                        Download .md
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
