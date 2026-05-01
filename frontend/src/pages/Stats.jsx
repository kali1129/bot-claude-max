// Stats page — En novato: 4 KPI cards + chart de equity simple.
// En experto: agrega tabla expectancy + heatmap por hora + ProMetrics completo.

import { useEffect, useState } from "react";
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts";
import { TrendingUp, Target, Award, Activity } from "lucide-react";

import { useSettings } from "@/lib/userMode";
import { apiGet, API_BASE } from "@/lib/api";

import SectionHeader from "@/components/atoms/SectionHeader";
import KpiCard from "@/components/atoms/KpiCard";
import EmptyState from "@/components/atoms/EmptyState";
import SkeletonPanel from "@/components/atoms/SkeletonPanel";
import NovatoTooltip from "@/components/atoms/NovatoTooltip";

import ProMetrics from "@/sections/ProMetrics";

const fmtMoney = (v) => {
    const n = Number(v);
    return Number.isFinite(n)
        ? `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        : "—";
};

export default function Stats() {
    const { isExperto, isNovato } = useSettings();
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetch = async () => {
            try {
                const r = await apiGet("/journal/stats");
                setStats(r.data);
            } catch (e) {
                console.error(e);
            } finally {
                setLoading(false);
            }
        };
        fetch();
        const id = setInterval(fetch, 10000);
        return () => clearInterval(id);
    }, []);

    if (loading) {
        return (
            <section className="px-6 lg:px-10 py-8">
                <div className="max-w-[1400px] mx-auto">
                    <SectionHeader
                        code="06 / ESTADÍSTICAS"
                        title="Estadísticas"
                    />
                    <SkeletonPanel rows={6} />
                </div>
            </section>
        );
    }

    const totalTrades = stats?.total_trades || 0;
    const winRate = stats?.win_rate ?? 0;
    const totalPnl = stats?.total_pnl_usd ?? 0;
    const expectancy = stats?.expectancy ?? 0;
    const equityCurve = stats?.equity_curve || [];

    return (
        <section className="px-6 lg:px-10 py-8" data-testid="page-stats">
            <div className="max-w-[1400px] mx-auto">
                <SectionHeader
                    code="06 / ESTADÍSTICAS"
                    title="Estadísticas"
                    subtitle={
                        isNovato
                            ? "Cómo va tu cuenta a través del tiempo."
                            : "Métricas pro + expectancy por combo + heatmap."
                    }
                />

                {totalTrades === 0 ? (
                    <EmptyState
                        icon={<TrendingUp size={36} />}
                        title="Aún no hay datos para mostrar"
                        body="Cuando el bot cierre algunas operaciones, vas a ver acá tu evolución, win rate y todas las métricas."
                    />
                ) : (
                    <>
                        {/* 4 KPIs */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                            <KpiCard
                                label="P&L Total"
                                value={
                                    (totalPnl >= 0 ? "+" : "") + fmtMoney(totalPnl)
                                }
                                color={totalPnl > 0 ? "green" : totalPnl < 0 ? "red" : "white"}
                                icon={TrendingUp}
                                testId="kpi-pnl"
                            />
                            <KpiCard
                                label="Aciertos"
                                value={`${winRate.toFixed(1)}%`}
                                sublabel={`${totalTrades} operaciones`}
                                color={winRate >= 50 ? "green" : "amber"}
                                icon={Target}
                                testId="kpi-winrate"
                            />
                            <KpiCard
                                label={
                                    <NovatoTooltip term="expectancy">
                                        Expectativa
                                    </NovatoTooltip>
                                }
                                value={`${expectancy >= 0 ? "+" : ""}${expectancy.toFixed(2)}R`}
                                sublabel="objetivo > +0.30R"
                                color={
                                    expectancy >= 0.3
                                        ? "green"
                                        : expectancy >= 0
                                        ? "amber"
                                        : "red"
                                }
                                icon={Award}
                                testId="kpi-expectancy"
                            />
                            <KpiCard
                                label="Trades"
                                value={totalTrades}
                                color="white"
                                icon={Activity}
                                testId="kpi-trades"
                            />
                        </div>

                        {/* Equity curve */}
                        {equityCurve.length > 0 ? (
                            <div className="panel p-5 mb-4" data-testid="equity-curve-card">
                                <div className="kicker mb-3">EVOLUCIÓN DE LA CUENTA</div>
                                <div className="h-64">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={equityCurve}>
                                            <CartesianGrid
                                                stroke="rgba(255,255,255,0.05)"
                                                strokeDasharray="3 3"
                                            />
                                            <XAxis
                                                dataKey="trade_no"
                                                tick={{ fill: "var(--text-faint)", fontSize: 10 }}
                                                stroke="var(--border)"
                                            />
                                            <YAxis
                                                tick={{ fill: "var(--text-faint)", fontSize: 10 }}
                                                stroke="var(--border)"
                                                tickFormatter={(v) => `$${v}`}
                                            />
                                            <Tooltip
                                                formatter={(v) => [fmtMoney(v), "equity"]}
                                                contentStyle={{
                                                    background: "rgba(0,0,0,0.85)",
                                                    border: "1px solid var(--border)",
                                                    fontSize: 11,
                                                    fontFamily: "monospace",
                                                }}
                                            />
                                            <Line
                                                type="monotone"
                                                dataKey="equity"
                                                stroke="var(--green-bright)"
                                                strokeWidth={2}
                                                dot={false}
                                                isAnimationActive={false}
                                            />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>
                        ) : null}

                        {/* En modo experto, agregar el ProMetrics completo */}
                        {isExperto ? <ProMetrics api={API_BASE} /> : null}
                    </>
                )}
            </div>
        </section>
    );
}
