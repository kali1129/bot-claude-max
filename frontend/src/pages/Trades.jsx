// Trades page — wrapper alrededor de TradeJournal section existente.
// Le agregamos copy en español, EmptyState cuando no hay trades, y un header
// consistente con las demás pages.

import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";
import { apiGet } from "@/lib/api";
import { API_BASE } from "@/lib/api";

import SectionHeader from "@/components/atoms/SectionHeader";
import EmptyState from "@/components/atoms/EmptyState";
import SkeletonPanel from "@/components/atoms/SkeletonPanel";

import TradeJournal from "@/sections/TradeJournal";

export default function Trades() {
    const [planData, setPlanData] = useState(null);
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);

    const fetchAll = async () => {
        try {
            const [p, s] = await Promise.allSettled([
                apiGet("/plan/data"),
                apiGet("/journal/stats"),
            ]);
            if (p.status === "fulfilled") setPlanData(p.value.data);
            if (s.status === "fulfilled") setStats(s.value.data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAll();
        const id = setInterval(() => apiGet("/journal/stats").then((r) => setStats(r.data)).catch(() => {}), 8000);
        return () => clearInterval(id);
    }, []);

    if (loading) {
        return (
            <section className="px-6 lg:px-10 py-8">
                <div className="max-w-[1400px] mx-auto">
                    <SectionHeader
                        code="04 / OPERACIONES"
                        title="Diario de Operaciones"
                        subtitle="Cargando…"
                    />
                    <SkeletonPanel rows={6} />
                </div>
            </section>
        );
    }

    const totalTrades = stats?.total_trades || 0;

    return (
        <div data-testid="page-trades">
            {totalTrades === 0 ? (
                <section className="px-6 lg:px-10 py-8">
                    <div className="max-w-[1400px] mx-auto">
                        <SectionHeader
                            code="04 / OPERACIONES"
                            title="Diario de Operaciones"
                            subtitle="Cada trade cerrado se registra acá. Sin journal no hay edge — anotá razón, screenshot y aprendizaje."
                        />
                        <EmptyState
                            icon={<BookOpen size={36} />}
                            title="Aún no hay operaciones"
                            body="Cuando el bot opere o registres una manual, aparecerán acá. Podés registrar la primera ahora mismo."
                            cta="Registrar trade manual"
                            onCtaClick={() => {
                                document
                                    .querySelector('[data-testid="add-trade-toggle"]')
                                    ?.click();
                            }}
                        />
                        {/* Aún así montamos TradeJournal abajo para que tengan el form a mano */}
                        <div className="mt-6">
                            <TradeJournal
                                api={API_BASE}
                                strategies={planData?.strategies || []}
                                stats={stats}
                                onMutated={fetchAll}
                            />
                        </div>
                    </div>
                </section>
            ) : (
                <TradeJournal
                    api={API_BASE}
                    strategies={planData?.strategies || []}
                    stats={stats}
                    onMutated={fetchAll}
                />
            )}
        </div>
    );
}
