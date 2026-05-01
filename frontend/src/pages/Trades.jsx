// Trades page — wrapper alrededor de TradeJournal section existente.
// Le agregamos copy en español, EmptyState cuando no hay trades, y un header
// consistente con las demás pages.

import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";
import { apiGet } from "@/lib/api";
import { API_BASE } from "@/lib/api";
import { useAuth } from "@/lib/AuthProvider";

import SectionHeader from "@/components/atoms/SectionHeader";
import EmptyState from "@/components/atoms/EmptyState";
import SkeletonPanel from "@/components/atoms/SkeletonPanel";

import TradeJournal from "@/sections/TradeJournal";

export default function Trades() {
    const { isAdmin } = useAuth();
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
                            body={
                                isAdmin
                                    ? "Cuando el bot opere o registres una manual, aparecerán acá. Podés registrar la primera ahora mismo."
                                    : "Cuando el bot del admin opere, las operaciones aparecerán acá."
                            }
                            cta={isAdmin ? "Registrar trade manual" : null}
                            onCtaClick={
                                isAdmin
                                    ? () => {
                                          document
                                              .querySelector('[data-testid="add-trade-toggle"]')
                                              ?.click();
                                      }
                                    : null
                            }
                        />
                        {isAdmin ? (
                            <div className="mt-6">
                                <TradeJournal
                                    api={API_BASE}
                                    strategies={planData?.strategies || []}
                                    stats={stats}
                                    onMutated={fetchAll}
                                    readOnly={false}
                                />
                            </div>
                        ) : null}
                    </div>
                </section>
            ) : (
                <TradeJournal
                    api={API_BASE}
                    strategies={planData?.strategies || []}
                    stats={stats}
                    onMutated={fetchAll}
                    readOnly={!isAdmin}
                />
            )}
        </div>
    );
}
